"""Preconditions the labeled fixtures depend on, and a check that they still hold.

A gold label is only correct if the world it was written against still looks the way
the author assumed. `fraud_new_customer` is labeled FLAG_FOR_REVIEW because POL-77001
is supposed to be days old when the incident happens and the claim is supposed to be
covered; if the seed drifts until the policy starts *after* the incident, the agent
correctly answers DENY and gets marked wrong. Nothing errors. The suite just measures
something other than what it claims to.

Those assumptions used to live only in the gap between `db/seed.py` and the fixed
incident dates in `eval/scenarios.py` and `sample_pdfs/`, which is why the drift went
unnoticed. Writing them down here makes them checkable before a sweep spends money.

    python -m eval.fixtures

This is not only an eval concern: the sample PDFs are what the demo app runs on, and
the same drift silently disarmed the new-policy fraud signal on `suspicious_whiplash`.
Both sets are checked together because one seed has to satisfy both.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select

from config import get_settings
from db.models import Claim, Policy
from db.session import get_session
from eval.scenarios import SCENARIOS


@dataclass(frozen=True)
class Precondition:
    """What a fixture needs to be true of the seeded data for its label to mean
    what it says."""

    policy_number: str
    incident_date: date
    covered: bool = True
    new_policy: bool = False
    velocity: bool = False
    claim_amount: float | None = None
    near_limit: bool = False


D = date.fromisoformat

# Keyed "eval:<scenario id>" and "pdf:<filename stem>". Incident dates are the ones
# written in the documents: literals in eval/scenarios.py, and for the PDFs, pixels
# in a rasterized image that cannot be edited without regenerating the file.
FIXTURES: dict[str, Precondition] = {
    "eval:clean_approve":         Precondition("POL-53276", D("2026-06-12")),
    "eval:expired_policy":        Precondition("POL-67890", D("2026-07-04"), covered=False),
    "eval:fraud_new_customer":    Precondition("POL-77001", D("2026-07-20"), new_policy=True),
    "eval:near_limit":            Precondition("POL-90281", D("2026-07-15"),
                                               claim_amount=74_500, near_limit=True),
    "eval:name_mismatch":         Precondition("POL-55295", D("2026-07-10")),
    "eval:velocity_repeat":       Precondition("POL-31415", D("2026-07-25"), velocity=True),
    "eval:ocr_recovery":          Precondition("POL-53276", D("2026-06-12")),
    "eval:confirmation_resolves": Precondition("POL-88472", D("2026-07-16")),
    "pdf:valid_auto_claim":       Precondition("POL-12345", D("2026-06-15")),
    "pdf:high_value_tesla":       Precondition("POL-90281", D("2026-06-22"),
                                               claim_amount=70_500, near_limit=True),
    "pdf:name_mismatch":          Precondition("POL-55295", D("2026-06-24")),
    "pdf:repeat_claimant":        Precondition("POL-31415", D("2026-06-30"), velocity=True),
    "pdf:suspicious_whiplash":    Precondition("POL-77001", D("2026-06-28"), new_policy=True),
    "pdf:expired_policy_home":    Precondition("POL-67890", D("2026-06-20"), covered=False),
    "pdf:scanned_low_quality":    Precondition("POL-53276", D("2026-06-18")),
    "pdf:missing_policy_number":  Precondition("POL-88472", D("2026-06-25")),
}


def _check_one(name: str, pre: Precondition, session) -> list[str]:
    s = get_settings()
    policy = session.get(Policy, pre.policy_number)
    if policy is None:
        return [f"{name}: policy {pre.policy_number} is not in the database"]

    bad: list[str] = []
    inc, eff, exp = pre.incident_date, policy.effective_date, policy.expiry_date
    covered = eff <= inc <= exp

    if pre.covered and not covered:
        bad.append(
            f"{name}: incident {inc} falls outside {pre.policy_number} coverage "
            f"{eff}..{exp}, so the agent will answer on coverage rather than on "
            "what this fixture is testing"
        )
    if not pre.covered and covered:
        bad.append(
            f"{name}: incident {inc} is inside {pre.policy_number} coverage "
            f"{eff}..{exp}, but this fixture requires an uncovered incident"
        )

    if pre.new_policy:
        age = (inc - eff).days
        if not 0 <= age <= s.new_policy_window_days:
            bad.append(
                f"{name}: {pre.policy_number} was {age} days old at the incident, "
                f"outside the 0..{s.new_policy_window_days} day new-policy window, so "
                "the new-customer fraud signal will not fire"
            )

    if pre.velocity:
        window_start = inc - timedelta(days=s.velocity_window_days)
        prior = session.execute(
            select(Claim).where(
                Claim.policy_number == pre.policy_number,
                Claim.filed_date >= window_start,
                Claim.filed_date <= inc,
            )
        ).scalars().all()
        if len(prior) + 1 < s.velocity_claim_count:
            bad.append(
                f"{name}: only {len(prior)} prior claims on {pre.policy_number} within "
                f"{s.velocity_window_days} days of the incident; the velocity rule needs "
                f"{s.velocity_claim_count - 1} to fire"
            )

    if pre.near_limit and pre.claim_amount is not None:
        ratio = pre.claim_amount / policy.limit_amount
        if ratio < s.near_limit_ratio:
            bad.append(
                f"{name}: claim ${pre.claim_amount:,.0f} is {ratio:.1%} of the "
                f"${policy.limit_amount:,.0f} limit, below the {s.near_limit_ratio:.0%} "
                "near-limit threshold this fixture depends on"
            )
        if ratio > 1.0:
            bad.append(
                f"{name}: claim ${pre.claim_amount:,.0f} exceeds the "
                f"${policy.limit_amount:,.0f} limit, which makes it an over-limit "
                "case rather than a near-limit one"
            )

    return bad


def _check_dates_match_documents() -> list[str]:
    """Guard against this table drifting away from the scenario documents it
    describes. The PDFs cannot be checked this way; their dates are pixels."""
    bad = []
    by_id = {s.id: s for s in SCENARIOS}
    for name, pre in FIXTURES.items():
        kind, _, key = name.partition(":")
        if kind != "eval":
            continue
        scenario = by_id.get(key)
        if scenario is None:
            bad.append(f"{name}: no scenario with id {key!r}")
            continue
        if pre.incident_date.strftime("%d/%m/%Y") not in scenario.document:
            bad.append(
                f"{name}: declared incident {pre.incident_date} does not appear in the "
                "scenario document; this table is out of date"
            )
    return bad


def check() -> list[str]:
    """Every unmet precondition, as human-readable strings. Empty means the seeded
    data still supports the labels."""
    bad = _check_dates_match_documents()
    with get_session() as session:
        for name, pre in FIXTURES.items():
            bad.extend(_check_one(name, pre, session))
    return bad


def main() -> int:
    settings = get_settings()
    problems = check()
    print(f"reference date: {settings.reference_date}")
    print(f"database: {settings.database_url}")
    print(f"checked {len(FIXTURES)} fixtures")
    if not problems:
        print("all preconditions hold")
        return 0
    print(f"\n{len(problems)} unmet precondition(s):")
    for p in problems:
        print(f"  - {p}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
