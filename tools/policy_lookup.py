"""Policy lookup: exact match, OCR-aware normalization, and fuzzy suggestions."""

from __future__ import annotations

import re
from datetime import date

from langchain.tools import tool
from rapidfuzz import fuzz, process
from sqlalchemy import select

from db.models import Policy
from db.session import get_session

# Map common OCR confusions in the digit portion back to digits
_DIGIT_FIXES = str.maketrans({"O": "0", "I": "1", "L": "1", "S": "5", "B": "8"})
_POLICY_SHAPE = re.compile(r"^P[O0QD]L-?(?P<digits>[0-9OIL SB]{5,9})$")


def normalize_policy_number(raw: str) -> str:
    """Uppercase, strip noise, and repair common OCR confusions (P0L-S3276 → POL-53276)."""
    s = re.sub(r"\s+", "", raw.strip().upper()).strip("\"'`.,;:")
    s = s.replace("–", "-").replace("—", "-")
    if m := _POLICY_SHAPE.match(s):
        digits = m.group("digits").translate(_DIGIT_FIXES)
        return f"POL-{digits}"
    return s


def suggest_policy_numbers(candidate: str, limit: int = 3, cutoff: float = 70.0) -> list[dict]:
    """Fuzzy-match a candidate against all known policy numbers.

    Returns [{policy_number, holder, score}] sorted by score, best first.
    """
    normalized = normalize_policy_number(candidate) if candidate else ""
    with get_session() as session:
        policies = session.execute(select(Policy)).scalars().all()
        by_number = {p.policy_number: p for p in policies}
        if not normalized:
            return []
        matches = process.extract(
            normalized, list(by_number), scorer=fuzz.ratio, limit=limit, score_cutoff=cutoff
        )
        return [
            {
                "policy_number": number,
                "holder": by_number[number].holder.name,
                "coverage_type": by_number[number].coverage_type,
                "score": round(score, 1),
            }
            for number, score, _ in matches
        ]


def _status_note(policy: Policy) -> str:
    if policy.status == "active":
        return "Policy is ACTIVE."
    if policy.status == "expired":
        return f"WARNING: Policy EXPIRED on {policy.expiry_date.isoformat()}. Incidents after that date are not covered."
    if policy.status == "pending":
        return f"WARNING: Policy is PENDING. Coverage only starts {policy.effective_date.isoformat()}."
    return f"WARNING: Policy status is {policy.status.upper()}. Coverage is not in force."


@tool
def policy_lookup_tool(policy_number: str) -> str:
    """Look up a policy by its number (e.g. POL-12345). Returns coverage type, limit,
    deductible, policyholder name, insured asset, status and dates. If the number is
    not found, returns the closest matching policy numbers so the user can be asked
    to confirm."""
    normalized = normalize_policy_number(policy_number)
    with get_session() as session:
        policy = session.get(Policy, normalized)
        if policy is None:
            suggestions = suggest_policy_numbers(normalized)
            if suggestions:
                options = "; ".join(
                    f"{s['policy_number']} (holder: {s['holder']}, {s['coverage_type']}, similarity {s['score']}%)"
                    for s in suggestions
                )
                return (
                    f"Policy {normalized} NOT FOUND. Closest matches: {options}. "
                    "Do not assume any of these is correct: the user must confirm. "
                    "If the document's number cannot be verified, decide NEEDS_INFO."
                )
            return (
                f"Policy {normalized} NOT FOUND and no similar policy numbers exist. "
                "Decide NEEDS_INFO so the user can supply the correct number."
            )

        days_active = (date.today() - policy.effective_date).days
        return (
            f"Policy {policy.policy_number} FOUND.\n"
            f"- Policyholder: {policy.holder.name} (customer since {policy.holder.customer_since.isoformat()})\n"
            f"- Coverage: {policy.coverage_type} | Limit: ${policy.limit_amount:,.0f} | "
            f"Deductible: ${policy.deductible:,.0f}\n"
            f"- Insured asset: {policy.insured_asset or 'n/a'}\n"
            f"- Effective {policy.effective_date.isoformat()} → {policy.expiry_date.isoformat()} "
            f"({days_active} days since effective date)\n"
            f"- {_status_note(policy)}\n"
            "Check that the claimant name matches the policyholder and that the incident "
            "type matches the coverage type."
        )
