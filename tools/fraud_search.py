"""Fraud checks: keyword patterns from the DB plus behavioural red flags
(claim velocity, brand-new policy, claimant/policyholder name mismatch)."""

from __future__ import annotations

from datetime import date, timedelta

from langchain.tools import tool
from rapidfuzz import fuzz
from sqlalchemy import select

from config import get_settings
from db.models import Claim, FraudPattern, Policy
from db.session import get_session
from tools.policy_lookup import normalize_policy_number


def _matched_patterns(description: str, patterns: list[FraudPattern]) -> list[FraudPattern]:
    """A pattern matches only if ALL of its keywords appear in the description."""
    desc = description.lower()
    return [p for p in patterns if all(kw.lower() in desc for kw in p.keywords)]


@tool
def fraud_search_tool(description: str, policy_number: str = "", claimant_name: str = "") -> str:
    """Check an incident description against known fraud patterns and, when a policy
    number is given, run behavioural checks: claim frequency on the policy, whether the
    policy is brand new, and whether the claimant name matches the policyholder.
    Always pass policy_number and claimant_name when you have them."""
    s = get_settings()
    flags: list[str] = []

    with get_session() as session:
        patterns = session.execute(select(FraudPattern)).scalars().all()
        for p in _matched_patterns(description, patterns):
            flags.append(
                f"Pattern match [{p.risk_level.upper()}, historical fraud rate {p.fraud_rate:.0%}]: "
                f"{' + '.join(p.keywords)}. {p.rationale}"
            )

        policy = None
        if policy_number:
            policy = session.get(Policy, normalize_policy_number(policy_number))

        if policy is not None:
            window_start = date.today() - timedelta(days=s.velocity_window_days)
            recent = session.execute(
                select(Claim).where(
                    Claim.policy_number == policy.policy_number,
                    Claim.filed_date >= window_start,
                )
            ).scalars().all()
            if len(recent) + 1 >= s.velocity_claim_count:  # +1 for the claim being triaged
                flags.append(
                    f"Claim velocity [HIGH]: this would be claim #{len(recent) + 1} on "
                    f"{policy.policy_number} within {s.velocity_window_days} days "
                    f"(prior: {', '.join(c.filed_date.isoformat() for c in recent)})."
                )

            days_since_effective = (date.today() - policy.effective_date).days
            if 0 <= days_since_effective <= s.new_policy_window_days:
                flags.append(
                    f"New policy [MEDIUM]: policy became effective only {days_since_effective} "
                    "days ago. Claims this early have elevated fraud rates."
                )

            if claimant_name:
                similarity = fuzz.token_sort_ratio(
                    claimant_name.lower(), policy.holder.name.lower()
                )
                if similarity < 80:
                    flags.append(
                        f"Name mismatch [HIGH]: claimant '{claimant_name}' vs policyholder "
                        f"'{policy.holder.name}' (similarity {similarity:.0f}%). Verify the "
                        "claimant is entitled to claim on this policy."
                    )

    if not flags:
        return "No fraud indicators found (patterns, claim velocity, policy age, name check)."
    numbered = "\n".join(f"{i}. {f}" for i, f in enumerate(flags, 1))
    return f"{len(flags)} fraud indicator(s) found:\n{numbered}"
