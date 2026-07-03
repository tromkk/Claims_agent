"""Prior-claims lookup for a policy and its holder."""

from __future__ import annotations

from langchain.tools import tool
from sqlalchemy import select

from db.models import Claim, Policy
from db.session import get_session
from tools.policy_lookup import normalize_policy_number


@tool
def claims_history_tool(policy_number: str) -> str:
    """List prior claims for a policy (dates, amounts, statuses) and note claims on the
    holder's other policies. Use to judge whether this claimant files unusually often."""
    normalized = normalize_policy_number(policy_number)
    with get_session() as session:
        policy = session.get(Policy, normalized)
        if policy is None:
            return f"Policy {normalized} not found. No history available."

        claims = session.execute(
            select(Claim)
            .where(Claim.policy_number == normalized)
            .order_by(Claim.filed_date.desc())
            .limit(10)
        ).scalars().all()

        other_policies = [
            p for p in policy.holder.policies if p.policy_number != normalized
        ]
        other_claim_count = sum(len(p.claims) for p in other_policies)

        if not claims:
            summary = f"Policy {normalized} has NO prior claims."
        else:
            rows = "\n".join(
                f"- {c.filed_date.isoformat()}: ${c.amount:,.0f} [{c.status}] {c.description}"
                for c in claims
            )
            summary = f"Policy {normalized} has {len(claims)} prior claim(s):\n{rows}"

        if other_policies:
            summary += (
                f"\nHolder {policy.holder.name} also has {len(other_policies)} other "
                f"policy(ies) with {other_claim_count} claim(s) on them."
            )
        return summary
