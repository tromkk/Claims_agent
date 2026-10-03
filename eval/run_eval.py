"""Run the triage eval across one or more Groq models, resumably.

Every (model, scenario, run) cell is executed once and its result appended as one
JSON line to `eval/results/runs.jsonl`. On restart the runner reads that file and
skips cells already done, so a session that stops on a rate limit can simply be
re-run later when the limit resets and it picks up exactly where it left off.

Because each cell calls a real LLM, this is meant to be run in chunks. When the
provider rate-limits, the runner saves progress (already persisted) and exits 0
with a message; re-run the same command to continue. Use `--limit N` to cap a
session voluntarily, or `--dry-run` to preview the plan without any API calls.

Usage:
    python -m eval.run_eval                 # default models, 5 runs each
    python -m eval.run_eval --dry-run
    python -m eval.run_eval --models openai/gpt-oss-20b,qwen/qwen3.6-27b
    python -m eval.run_eval --runs 5 --limit 40
    python -m eval.run_eval --reseed        # rebuild the eval DB first
    python -m eval.run_eval --fresh         # new sweep; archive the old results

Then inspect with:  python -m eval.report
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from langchain_core.callbacks import BaseCallbackHandler

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from eval.scenarios import SCENARIOS, Scenario  # noqa: E402

# Groq-hosted, tool-calling-capable models. Verify current IDs against
# https://console.groq.com/docs/models before a real run; Groq rotates these.
DEFAULT_MODELS = [
    "openai/gpt-oss-20b",
]

RESULTS_PATH = _ROOT / "eval" / "results" / "runs.jsonl"
MANIFEST_PATH = _ROOT / "eval" / "results" / "manifests.jsonl"
EVAL_DB_URL = "sqlite:///data/eval_claims.db"


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


class TokenCounter(BaseCallbackHandler):
    """Accumulates token usage across every LLM call in a single triage run.

    Attached to the model instance (callbacks=[...]) so it fires for extraction,
    each tool-calling turn, and structured synthesis, without touching agent code.
    """

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0

    def on_llm_end(self, response, **kwargs) -> None:  # noqa: ANN001
        self.calls += 1
        usage = (response.llm_output or {}).get("token_usage") if response.llm_output else None
        if usage:
            self.input_tokens += usage.get("prompt_tokens", 0)
            self.output_tokens += usage.get("completion_tokens", 0)
            return
        # Fallback: sum usage_metadata carried on the message objects.
        for gen_list in response.generations:
            for gen in gen_list:
                msg = getattr(gen, "message", None)
                um = getattr(msg, "usage_metadata", None) if msg else None
                if um:
                    self.input_tokens += um.get("input_tokens", 0)
                    self.output_tokens += um.get("output_tokens", 0)


def git_sha() -> str:
    """Short commit SHA at the time of the run, recorded on each result row.

    A breadcrumb, not a guarantee. Because sweeps stop on rate limits and resume
    later, a single sweep routinely spans several commits: the first 60-run baseline
    here covers four. HEAD also moves for changes that cannot affect a triage
    (docs, notebooks) and stays put for uncommitted ones that can, so it answers
    "did the repo change", not "did the agent change". Use `--fresh` to start a
    clean sweep; `git log eval/results/` for the history.
    """
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=_ROOT, text=True,
            stderr=subprocess.DEVNULL,
        )
        return out.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def scenario_set_hash() -> str:
    """Stable hash of the scenario definitions; changes if a scenario or its key changes."""
    blob = json.dumps(
        [
            {
                "id": s.id,
                "document": s.document,
                "expected": [d.value for d in s.expected_decisions],
                "confirmed_fields": s.confirmed_fields,
                "zero_tool": s.expect_zero_tool_calls,
                "missing": s.expect_missing_field,
                "red_flag": s.expect_any_red_flag,
                "recovered": s.expect_recovered_policy,
            }
            for s in SCENARIOS
        ],
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def setup_database(reseed: bool) -> None:
    """Point the agent at a dedicated eval DB seeded from db.seed.

    The curated seed records use dates relative to today, so scenarios like
    'expired policy' and 'new customer' stay true. `--reseed` rebuilds the file.
    """
    os.environ["DATABASE_URL"] = EVAL_DB_URL

    from config import get_settings

    get_settings.cache_clear()

    from db.session import ensure_seeded, get_engine, reset_engine

    reset_engine()

    if reseed:
        db_file = Path(EVAL_DB_URL.removeprefix("sqlite:///"))
        if db_file.exists():
            db_file.unlink()
        reset_engine()

    ensure_seeded()
    # Touch the engine so a bad URL fails now, not mid-run.
    get_engine()


def archive_results(path: Path, dry_run: bool) -> Path | None:
    """Move an existing results file aside so a new sweep starts from nothing.

    Renamed rather than deleted: git has the history, but `report.py` and the
    notebooks read whatever is on disk, so a stale sweep left in place would get
    picked up by the next report. Returns the archive path, or None if there was
    nothing to move."""
    if not path.exists():
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.stem}-{stamp}{path.suffix}")
    if not dry_run:
        path.rename(target)
    return target


def load_done(path: Path) -> set[tuple[str, str, int]]:
    """Return the set of (model, scenario_id, run) cells already recorded."""
    done: set[tuple[str, str, int]] = set()
    if not path.exists():
        return done
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                # A half-written trailing line from a hard kill: ignore it.
                continue
            if rec.get("error"):
                continue
            done.add((rec["model"], rec["scenario_id"], rec["run"]))
    return done


def _policy_verified(trace) -> bool:
    """Mirror the agent's own guardrail check: a successful policy_lookup in the trace."""
    return any(
        step.tool == "policy_lookup_tool"
        and step.observation.startswith("Policy")
        and "NOT FOUND" not in step.observation
        for step in trace
    )


def _recovered_policy(trace, policy_number: str) -> bool:
    return any(
        step.tool == "policy_lookup_tool" and f"{policy_number} FOUND" in step.observation
        for step in trace
    )


def run_one(
    model: str,
    scenario: Scenario,
    run_idx: int,
    temperature: float,
    code_sha: str,
    scenario_hash: str,
) -> dict:
    """Execute a single triage run and score it into a JSON-able record."""
    from langchain_groq import ChatGroq

    from agents.schemas import Decision
    from agents.triage_agent import run_triage
    from config import get_settings

    api_key = get_settings().groq_api_key
    counter = TokenCounter()
    llm = ChatGroq(
        model=model, temperature=temperature, api_key=api_key, callbacks=[counter]
    )

    t0 = time.perf_counter()
    outcome = run_triage(scenario.document, confirmed_fields=scenario.confirmed_fields, llm=llm)
    latency = round(time.perf_counter() - t0, 3)

    result = outcome.result
    trace = outcome.trace
    decision = result.decision.value
    expected = [d.value for d in scenario.expected_decisions]

    verified = _policy_verified(trace)
    is_approve = result.decision == Decision.APPROVE
    guardrail_violation = is_approve and not verified

    # Structural checks (only those the scenario declares).
    structural: dict[str, bool] = {}
    if scenario.expect_zero_tool_calls is not None:
        structural["zero_tool_calls"] = (len(trace) == 0) == scenario.expect_zero_tool_calls
    if scenario.expect_missing_field is not None:
        structural["missing_field"] = (
            scenario.expect_missing_field in result.missing_or_uncertain_fields
        )
    if scenario.expect_any_red_flag is not None:
        structural["any_red_flag"] = bool(result.red_flags) == scenario.expect_any_red_flag
    if scenario.expect_recovered_policy is not None:
        structural["recovered_policy"] = _recovered_policy(trace, scenario.expect_recovered_policy)

    return {
        "timestamp": _iso_now(),
        "model": model,
        "scenario_id": scenario.id,
        "title": scenario.title,
        "run": run_idx,
        "decision": decision,
        "expected": expected,
        "correct": decision in expected,
        "guardrail_violation": guardrail_violation,
        "policy_verified": verified,
        "num_tool_calls": len(trace),
        "tools": [s.tool for s in trace],
        "trace": [s.to_dict() for s in trace],
        "confidence": result.confidence,
        "missing_fields": list(result.missing_or_uncertain_fields),
        "red_flags": list(result.red_flags),
        "reasoning_summary": result.reasoning_summary,
        "extracted": outcome.extracted.as_display_dict(),
        "structural": structural,
        "structural_ok": (all(structural.values()) if structural else None),
        "latency_s": latency,
        "temperature": temperature,
        "llm_calls": counter.calls,
        "input_tokens": counter.input_tokens,
        "output_tokens": counter.output_tokens,
        "code_sha": code_sha,
        "scenario_set_hash": scenario_hash,
    }


def build_plan(models: list[str], runs: int) -> list[tuple[str, Scenario, int]]:
    plan = []
    for model in models:
        for scenario in SCENARIOS:
            for r in range(runs):
                plan.append((model, scenario, r))
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS),
                        help="Comma-separated Groq model IDs.")
    parser.add_argument("--runs", type=int, default=5,
                        help="Runs per scenario per model (stability sample).")
    parser.add_argument("--temperature", type=float, default=None,
                        help="Override sampling temperature (default: config value).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max cells to execute this session (for pacing).")
    parser.add_argument("--reseed", action="store_true",
                        help="Rebuild the eval database before running.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the plan and remaining cells; no API calls.")
    parser.add_argument("--fresh", action="store_true",
                        help="Start a new sweep: archive any existing results file "
                             "instead of resuming into it.")
    parser.add_argument("--keep-going", action="store_true",
                        help="On an unexpected (non-rate-limit) error, log it and continue.")
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]

    setup_database(reseed=args.reseed)

    # Stale fixtures do not raise, they just quietly grade the wrong thing, so this
    # runs before any API calls rather than after a sweep has already been paid for.
    from eval.fixtures import check as check_fixtures

    if problems := check_fixtures():
        print(f"Fixture preconditions failed ({len(problems)}); the labels no longer "
              "match the seeded data:")
        for p in problems:
            print(f"  - {p}")
        print("\nRe-seed (--reseed), or fix reference_date / eval/fixtures.py.")
        return 1

    from config import get_settings
    from agents.llm import LLMConfigError, LLMRateLimitError

    settings = get_settings()
    temperature = args.temperature if args.temperature is not None else settings.temperature

    code_sha = git_sha()
    scenario_hash = scenario_set_hash()

    if args.fresh:
        archived = archive_results(RESULTS_PATH, args.dry_run)
        if archived is None:
            print("--fresh: no existing results file; starting clean.")
        else:
            verb = "would archive" if args.dry_run else "archived"
            print(f"--fresh: {verb} previous results to {archived.name}")

    plan = build_plan(models, args.runs)
    # --fresh means every cell is outstanding, whether or not the rename has
    # happened yet (it has not under --dry-run).
    done = set() if args.fresh else load_done(RESULTS_PATH)
    remaining = [cell for cell in plan if (cell[0], cell[1].id, cell[2]) not in done]

    total = len(plan)
    print(f"Models: {', '.join(models)}")
    print(f"Scenarios: {len(SCENARIOS)} | runs each: {args.runs} | temperature: {temperature}")
    print(f"Agent code: {code_sha} | scenario set: {scenario_hash}")
    print(f"Plan: {total} cells | done: {len(plan) - len(remaining)} | remaining: {len(remaining)}")
    print(f"Results file: {RESULTS_PATH}")

    if args.dry_run:
        for model, scenario, r in remaining[:20]:
            print(f"  TODO {model} :: {scenario.id} :: run {r}")
        if len(remaining) > 20:
            print(f"  ... and {len(remaining) - 20} more")
        return 0

    if not settings.groq_api_key:
        print("\nNo GROQ_API_KEY configured. Set it in .env before a real run.")
        return 1

    if not remaining:
        print("\nNothing to do, every cell is already recorded. Run: python -m eval.report")
        return 0

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)

    manifest = {
        "timestamp": _iso_now(),
        "models": models,
        "runs_per_scenario": args.runs,
        "temperature": temperature,
        "num_scenarios": len(SCENARIOS),
        "code_sha": code_sha,
        "scenario_set_hash": scenario_hash,
        "database_url": EVAL_DB_URL,
        "remaining_at_start": len(remaining),
    }
    with MANIFEST_PATH.open("a") as mf:
        mf.write(json.dumps(manifest) + "\n")

    executed = 0

    with RESULTS_PATH.open("a") as out:
        for model, scenario, r in remaining:
            if args.limit is not None and executed >= args.limit:
                print(f"\nReached --limit {args.limit}. Re-run to continue.")
                break
            label = f"{model} :: {scenario.id} :: run {r}"
            try:
                record = run_one(model, scenario, r, temperature, code_sha, scenario_hash)
            except LLMRateLimitError:
                print(f"\nRate-limited at [{label}]. Progress saved; re-run when it resets.")
                break
            except LLMConfigError as exc:
                print(f"\nConfig error: {exc}")
                return 1
            except KeyboardInterrupt:
                print(f"\nInterrupted at [{label}]. Progress saved; re-run to continue.")
                break
            except Exception as exc:  # noqa: BLE001
                if args.keep_going:
                    err = {"timestamp": _iso_now(), "model": model,
                           "scenario_id": scenario.id, "run": r, "error": str(exc)}
                    out.write(json.dumps(err) + "\n")
                    out.flush()
                    print(f"  ERROR [{label}]: {exc} (continuing)")
                    executed += 1
                    continue
                print(f"\nUnexpected error at [{label}]: {exc}")
                print("Fix it and re-run, or pass --keep-going to skip failing cells.")
                return 1

            out.write(json.dumps(record) + "\n")
            out.flush()
            executed += 1
            mark = "ok " if record["correct"] else "MISS"
            print(f"  [{mark}] {label} -> {record['decision']} ({record['latency_s']}s)")

    print(f"\nExecuted {executed} cell(s) this session. Inspect with: python -m eval.report")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
