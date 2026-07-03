"""Claim amount extraction and validation against the policy's limit/deductible."""

from __future__ import annotations

import re
from dataclasses import dataclass

from langchain.tools import tool

from config import get_settings
from db.session import get_session
from tools.policy_lookup import normalize_policy_number

# $-prefixed amounts, or bare numbers appearing near money context words.
DOLLAR_RE = re.compile(r"\$\s?(?P<num>\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{2})?")
CONTEXT_RE = re.compile(
    r"(?:cost|estimate|total|amount|repair|damages?|invoice|quote|claim(?:ed|ing)?|bill)"
    r"[^\n$]{0,40}?(?<![\d.\-/])(?P<num>\d{1,3}(?:,\d{3})+|\d{3,7})(?:\.\d{2})?(?![\d/])",
    re.IGNORECASE,
)
YEAR_RANGE = range(1980, 2100)


@dataclass
class Amount:
    value: float
    dollar_prefixed: bool
    snippet: str


def extract_amounts(text: str) -> list[Amount]:
    """Extract plausible monetary amounts; excludes years and policy-number digits."""
    amounts: list[Amount] = []
    seen_spans: list[tuple[int, int]] = []

    for match in DOLLAR_RE.finditer(text):
        value = float(match.group("num").replace(",", ""))
        amounts.append(Amount(value, True, _snip(text, match)))
        seen_spans.append(match.span())

    for match in CONTEXT_RE.finditer(text):
        if any(s <= match.start("num") < e for s, e in seen_spans):
            continue
        value = float(match.group("num").replace(",", ""))
        if int(value) in YEAR_RANGE and "," not in match.group("num"):
            continue  # likely a year (e.g. "Toyota Camry 2023")
        amounts.append(Amount(value, False, _snip(text, match)))

    return amounts


def _snip(text: str, match: re.Match, pad: int = 40) -> str:
    return text[max(0, match.start() - pad) : match.end() + pad].replace("\n", " ").strip()


@tool
def amount_validator_tool(text: str, policy_number: str = "") -> str:
    """Extract claim amounts from text and validate them: flags high-value claims and,
    when a policy number is given, compares the amount against the policy's coverage
    limit and deductible. Pass the incident/damage text plus any amounts you saw."""
    s = get_settings()
    amounts = extract_amounts(text)
    if not amounts:
        return (
            "No claim amounts found in the provided text. If the document has no amount, "
            "list 'claim_amount' as missing information."
        )

    claim_amount = max(a.value for a in amounts)
    lines = [f"Detected claim amount: ${claim_amount:,.0f} "
             f"(from: \"{max(amounts, key=lambda a: a.value).snippet}\")"]

    if claim_amount > s.high_value_threshold:
        lines.append(
            f"HIGH VALUE: exceeds the ${s.high_value_threshold:,.0f} auto-approval threshold "
            "and requires closer review."
        )
    else:
        lines.append(f"Amount is below the ${s.high_value_threshold:,.0f} high-value threshold.")

    if policy_number:
        with get_session() as session:
            from db.models import Policy

            policy = session.get(Policy, normalize_policy_number(policy_number))
            if policy is None:
                lines.append(f"Policy {policy_number} not found. Cannot compare against limits.")
            else:
                if claim_amount > policy.limit_amount:
                    lines.append(
                        f"EXCEEDS LIMIT: claim ${claim_amount:,.0f} is above the policy limit "
                        f"${policy.limit_amount:,.0f}."
                    )
                elif claim_amount >= s.near_limit_ratio * policy.limit_amount:
                    lines.append(
                        f"NEAR LIMIT: claim ${claim_amount:,.0f} is ≥{s.near_limit_ratio:.0%} of the "
                        f"${policy.limit_amount:,.0f} policy limit, a known fraud indicator."
                    )
                else:
                    lines.append(
                        f"Within policy limit (${claim_amount:,.0f} of ${policy.limit_amount:,.0f})."
                    )
                if claim_amount <= policy.deductible:
                    lines.append(
                        f"Below the ${policy.deductible:,.0f} deductible: nothing would be paid out."
                    )

    return "\n".join(lines)
