"""Pure scoring/aggregation helpers shared by the runner, the report CLI, and the
analysis notebook. No I/O beyond reading the results file; no plotting. Keeping the
maths here means the notebook and the CLI can never disagree about a number.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

# Decision label order used for confusion matrices and tables.
DECISIONS = [
    "APPROVE",
    "FLAG_FOR_REVIEW",
    "DENY",
    "NEEDS_INFO",
]
APPROVE_CLASS = {"APPROVE"}

# Groq list price, USD per 1M tokens (input, output). Verify against
# https://groq.com/pricing before quoting cost; these move. Unpriced model -> cost is None.
PRICING: dict[str, tuple[float, float]] = {
    # Retired by Groq mid-project (now 404s), kept on purpose: it was the original
    # primary model, and hosted model IDs do get pulled during a project. Cost is
    # recomputed from stored token counts, so its old runs are still priceable.
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "openai/gpt-oss-20b": (0.10, 0.50),
}


def load_all(path: str | Path) -> tuple[list[dict], list[dict]]:
    """Return (successful_runs, error_records) from a results JSONL. Tolerant of a
    half-written trailing line from a hard kill."""
    path = Path(path)
    runs: list[dict] = []
    errors: list[dict] = []
    if not path.exists():
        return runs, errors
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            (errors if rec.get("error") else runs).append(rec)
    return runs, errors


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (better than normal approx at small n)."""
    if n == 0:
        return (0.0, 0.0)
    phat = successes / n
    denom = 1 + z**2 / n
    center = (phat + z**2 / (2 * n)) / denom
    margin = z * math.sqrt(phat * (1 - phat) / n + z**2 / (4 * n**2)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def cost_for(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """USD cost of a run given its token counts, or None if the model isn't priced."""
    price = PRICING.get(model)
    if price is None:
        return None
    in_rate, out_rate = price
    return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000


def _primary_gold(rec: dict) -> str:
    """The canonical expected decision for confusion-matrix purposes (first in the set)."""
    expected = rec.get("expected") or []
    return expected[0] if expected else "?"


def is_false_approval(rec: dict) -> bool:
    """The run approved when no approval was ever an acceptable answer."""
    expected = set(rec.get("expected") or [])
    return rec["decision"] in APPROVE_CLASS and not (expected & APPROVE_CLASS)


def summarize(runs: list[dict], errors: list[dict] | None = None) -> dict[str, dict]:
    """Per-model aggregate metrics. Robust to records missing the newer fields."""
    errors = errors or []
    by_model: dict[str, list[dict]] = defaultdict(list)
    for rec in runs:
        by_model[rec["model"]].append(rec)
    errs_by_model: dict[str, int] = Counter(e.get("model", "?") for e in errors)

    summary: dict[str, dict] = {}
    for model, group in by_model.items():
        n = len(group)
        correct = sum(r["correct"] for r in group)
        lo, hi = wilson_interval(correct, n)

        # Stability: per scenario, share of runs equal to that scenario's modal decision.
        by_scenario: dict[str, list[str]] = defaultdict(list)
        for r in group:
            by_scenario[r["scenario_id"]].append(r["decision"])
        stabilities = [
            Counter(ds).most_common(1)[0][1] / len(ds) for ds in by_scenario.values()
        ]
        stability = sum(stabilities) / len(stabilities) if stabilities else 0.0

        nonapprove = [r for r in group if not (set(r.get("expected") or []) & APPROVE_CLASS)]
        false_approvals = sum(is_false_approval(r) for r in group)

        structural = [r for r in group if r.get("structural_ok") is not None]
        priced = [cost_for(model, r.get("input_tokens", 0), r.get("output_tokens", 0))
                  for r in group]
        priced = [c for c in priced if c is not None]

        n_err = errs_by_model.get(model, 0)
        summary[model] = {
            "runs": n,
            "errors": n_err,
            "completion_rate": n / (n + n_err) if (n + n_err) else 0.0,
            "scenarios": len(by_scenario),
            "accuracy": correct / n if n else 0.0,
            "accuracy_ci": (lo, hi),
            "correct": correct,
            "stability": stability,
            "guardrail_violations": sum(r["guardrail_violation"] for r in group),
            "false_approvals": false_approvals,
            "false_approval_rate": (false_approvals / len(nonapprove)) if nonapprove else 0.0,
            "structural_ok": sum(r["structural_ok"] for r in structural),
            "structural_total": len(structural),
            "mean_latency_s": (sum(r["latency_s"] for r in group) / n) if n else 0.0,
            "mean_llm_calls": (sum(r.get("llm_calls", 0) for r in group) / n) if n else 0.0,
            "mean_total_tokens": (
                sum(r.get("input_tokens", 0) + r.get("output_tokens", 0) for r in group) / n
                if n else 0.0
            ),
            "mean_cost_usd": (sum(priced) / len(priced)) if priced else None,
        }
    return summary


def confusion(runs: list[dict], model: str) -> dict[tuple[str, str], int]:
    """Counts keyed by (primary_gold_decision, predicted_decision) for one model."""
    matrix: Counter = Counter()
    for r in runs:
        if r["model"] != model:
            continue
        matrix[(_primary_gold(r), r["decision"])] += 1
    return dict(matrix)


def best_model(summary: dict[str, dict]) -> tuple[str | None, bool]:
    """Return (best_model_by_accuracy_then_stability, distinguishable).

    `distinguishable` is False when the top two models' accuracy confidence
    intervals overlap, meaning the data can't actually separate them yet.
    """
    if not summary:
        return None, False
    ranked = sorted(
        summary.items(), key=lambda kv: (kv[1]["accuracy"], kv[1]["stability"]), reverse=True
    )
    top = ranked[0]
    if len(ranked) == 1:
        return top[0], True
    runner = ranked[1]
    top_lo = top[1]["accuracy_ci"][0]
    runner_hi = runner[1]["accuracy_ci"][1]
    distinguishable = top_lo > runner_hi
    return top[0], distinguishable
