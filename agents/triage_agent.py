"""Tool-calling triage agent.

Replaces the fragile text-format ReAct loop with native tool calling: the model
returns structured tool invocations, we execute them, feed observations back, and
finally synthesize a structured `TriageResult`. The reasoning trail is preserved
step by step for the UI and the audit log. The legacy text-ReAct agent is still
available behind `USE_LEGACY_REACT_AGENT=true` (see agents/react_agent.py).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agents.extraction import extract_fields
from agents.llm import get_chat_model, get_fallback_model, invoke_with_retry
from agents.schemas import (
    Decision,
    ExtractedField,
    ExtractedFields,
    TraceStep,
    TriageOutcome,
    TriageResult,
)
from config import get_settings
from tools import (
    amount_validator_tool,
    claims_history_tool,
    fraud_search_tool,
    policy_lookup_tool,
)

logger = logging.getLogger(__name__)

TOOLS = [policy_lookup_tool, fraud_search_tool, amount_validator_tool, claims_history_tool]
TOOL_MAP = {t.name: t for t in TOOLS}

SYSTEM_PROMPT = """You are an expert insurance claims triage agent. You pre-screen incoming
claim documents and produce a triage decision with clear reasoning for human reviewers.

WORKFLOW
1. Review the pre-extracted fields and the document text.
2. If a policy number is present (or user-confirmed), call policy_lookup_tool.
3. If a policy was found, call claims_history_tool to review prior claims.
4. If there is an incident description, call fraud_search_tool; always pass the
   policy_number and claimant_name too when you have them.
5. If amounts are mentioned, call amount_validator_tool with the relevant text and
   the policy_number.
6. Then stop calling tools and give your conclusion in plain text.

DECISIONS
- APPROVE: policy active, coverage matches the incident type, claimant matches the
  policyholder, amount within limits, no fraud indicators.
- APPROVE_WITH_MONITORING: essentially valid but with one mild concern worth tracking.
- FLAG_FOR_REVIEW: fraud indicators, name mismatch, near/over limit amounts, coverage
  mismatch (e.g. water damage claimed on an auto policy), or expired/pending policy
  where the situation is unclear.
- DENY: clearly not covered (policy expired/lapsed before the incident, not an
  insurance claim document at all, or claim excluded).
- NEEDS_INFO: a required field (especially the policy number) is missing, unverifiable,
  or ambiguous. Name exactly which fields the user must confirm. Never guess a policy
  number: if lookup fails and only fuzzy suggestions exist, decide NEEDS_INFO.

RULES
- USER-CONFIRMED fields are authoritative; do not second-guess them.
- Call each tool at most twice; do not repeat identical calls.
- If the document is not an insurance claim at all, call no tools and DENY.
- Be conservative: APPROVE only when every check passed."""


def _fields_block(extracted: ExtractedFields, confirmed: dict[str, str] | None) -> str:
    lines = []
    for name, f in extracted.as_display_dict().items():
        lines.append(
            f"- {name}: {f['value']!r} (confidence {f['confidence']:.0%})"
        )
    if not lines:
        lines.append("- (nothing extracted)")
    block = "PRE-EXTRACTED FIELDS:\n" + "\n".join(lines)
    if confirmed:
        block += "\n\nUSER-CONFIRMED FIELDS (authoritative, use these values):\n" + "\n".join(
            f"- {k}: {v!r}" for k, v in confirmed.items()
        )
    return block


def _build_messages(text: str, extracted: ExtractedFields, confirmed: dict | None) -> list:
    s = get_settings()
    user = (
        f"{_fields_block(extracted, confirmed)}\n\n"
        f"CLAIM DOCUMENT TEXT:\n{text[:s.max_document_chars]}\n\n"
        "Triage this claim following the workflow. Use tools only when the relevant "
        "data exists, then conclude."
    )
    return [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user)]


SYNTHESIS_PROMPT = (
    "Based on the investigation above, produce the final structured triage result. "
    "decision must be one of APPROVE, APPROVE_WITH_MONITORING, FLAG_FOR_REVIEW, DENY, "
    "NEEDS_INFO. In missing_or_uncertain_fields use snake_case field names such as "
    "policy_number, claimant_name, incident_date, incident_description, claim_amount. "
    "red_flags should be short labels. reasoning_summary is 2-5 sentences for a human reviewer."
)


def synthesize(messages: list, llm) -> TriageResult:
    """Convert the finished conversation into a structured TriageResult."""
    structured = llm.with_structured_output(TriageResult)
    return invoke_with_retry(structured, messages + [HumanMessage(content=SYNTHESIS_PROMPT)])


def _fallback_result(final_text: str) -> TriageResult:
    """Heuristic rescue if structured synthesis fails: parse the decision from text."""
    upper = final_text.upper()
    decision = Decision.FLAG_FOR_REVIEW
    for d in (Decision.NEEDS_INFO, Decision.DENY, Decision.APPROVE_WITH_MONITORING,
              Decision.FLAG_FOR_REVIEW, Decision.APPROVE):
        if d.value in upper or d.value.replace("_", " ") in upper:
            decision = d
            break
    return TriageResult(
        decision=decision,
        confidence=0.3,
        missing_or_uncertain_fields=[],
        red_flags=["structured_output_unavailable"],
        reasoning_summary=final_text[:1000] or "Agent produced no final reasoning.",
    )


def _apply_guardrails(
    result: TriageResult, extracted: ExtractedFields, confirmed: dict | None, trace: list[TraceStep]
) -> TriageResult:
    """Deterministic checks on top of the LLM's answer."""
    s = get_settings()
    confirmed = confirmed or {}

    # Low-confidence extracted fields must be surfaced for confirmation
    for name, f in extracted.as_display_dict().items():
        if (
            f["confidence"] < s.confidence_confirm_threshold
            and name not in confirmed
            and name not in result.missing_or_uncertain_fields
        ):
            result.missing_or_uncertain_fields.append(name)

    has_policy = bool(confirmed.get("policy_number")) or (
        extracted.policy_number is not None
        and extracted.policy_number.confidence >= s.confidence_confirm_threshold
    )
    policy_verified = any(
        step.tool == "policy_lookup_tool"
        and step.observation.startswith("Policy")
        and "NOT FOUND" not in step.observation
        for step in trace
    )

    # Never approve without a verified policy: downgrade to NEEDS_INFO
    if result.decision in (Decision.APPROVE, Decision.APPROVE_WITH_MONITORING):
        if not policy_verified:
            result.decision = Decision.NEEDS_INFO
            if "policy_number" not in result.missing_or_uncertain_fields:
                result.missing_or_uncertain_fields.append("policy_number")
            result.red_flags.append("approval_without_verified_policy")
            result.reasoning_summary += (
                " [System check: the policy was never verified against the database, "
                "so the approval was downgraded to NEEDS_INFO.]"
            )
        elif not has_policy and "policy_number" not in confirmed:
            result.missing_or_uncertain_fields.append("policy_number")

    return result


def _serialize_args(args: dict) -> dict:
    try:
        return json.loads(json.dumps(args, default=str))
    except Exception:  # noqa: BLE001
        return {"raw": str(args)}


def run_triage(
    document_text: str,
    confirmed_fields: dict[str, str] | None = None,
    on_step: Callable[[TraceStep], None] | None = None,
    llm=None,
) -> TriageOutcome:
    """Run the full triage loop over a parsed claim document.

    confirmed_fields: values the user confirmed in the UI (authoritative).
    on_step: callback fired after each tool observation (for live UI updates).
    llm: injectable chat model (tests); defaults to the configured provider.
    """
    s = get_settings()
    if s.use_legacy_react_agent and llm is None:
        from agents.react_agent import run_legacy_triage

        return run_legacy_triage(document_text, confirmed_fields)

    base_llm = llm or get_chat_model()
    extracted = extract_fields(document_text, llm=base_llm)
    if confirmed_fields:
        for name, value in confirmed_fields.items():
            if name in ExtractedFields.model_fields and value:
                setattr(
                    extracted, name,
                    ExtractedField(value=str(value), confidence=1.0, source_snippet="user-confirmed"),
                )

    messages = _build_messages(document_text, extracted, confirmed_fields)
    llm_with_tools = base_llm.bind_tools(TOOLS)
    trace: list[TraceStep] = []
    final_text = ""

    for _ in range(s.max_agent_iterations):
        try:
            ai: AIMessage = invoke_with_retry(llm_with_tools, messages)
        except Exception as exc:  # noqa: BLE001
            fallback = get_fallback_model() if llm is None else None
            if fallback is None:
                raise
            logger.warning("Primary LLM failed (%s); switching to fallback provider", exc)
            base_llm = fallback
            llm_with_tools = fallback.bind_tools(TOOLS)
            ai = invoke_with_retry(llm_with_tools, messages)

        messages.append(ai)
        thought = ai.content if isinstance(ai.content, str) else str(ai.content)

        if not ai.tool_calls:
            final_text = thought
            break

        for call in ai.tool_calls:
            tool = TOOL_MAP.get(call["name"])
            if tool is None:
                observation = f"Unknown tool '{call['name']}'. Available: {list(TOOL_MAP)}"
            else:
                try:
                    observation = str(tool.invoke(call["args"]))
                except Exception as exc:  # noqa: BLE001 - a tool error must not kill the run
                    observation = f"Tool error: {exc}"
                    logger.exception("Tool %s failed", call["name"])
            messages.append(ToolMessage(content=observation, tool_call_id=call["id"]))
            step = TraceStep(
                thought=thought,
                tool=call["name"],
                tool_input=_serialize_args(call["args"]),
                observation=observation,
            )
            trace.append(step)
            if on_step:
                on_step(step)
    else:
        final_text = "Iteration limit reached before the agent concluded."
        logger.warning("Agent hit max_agent_iterations=%s", s.max_agent_iterations)

    try:
        result = synthesize(messages, base_llm)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Structured synthesis failed (%s); using heuristic fallback", exc)
        result = _fallback_result(final_text)

    result = _apply_guardrails(result, extracted, confirmed_fields, trace)
    return TriageOutcome(result=result, extracted=extracted, trace=trace)
