"""Seed the database with demo data.

Two layers:
1. Curated records the sample PDFs reference (edge cases: expired policy, brand-new
   customer, near-limit claim, repeat claimant, name mismatch...). Dates are relative
   to today so scenarios like "new customer" stay true over time.
2. Faker-generated bulk data (fixed seed → reproducible) so the database feels real.

Run directly to (re)seed:  python -m db.seed
"""

from __future__ import annotations

import logging
import random
from datetime import date, timedelta

from faker import Faker
from sqlalchemy.orm import Session

from db.models import Claim, FraudPattern, Policy, Policyholder

logger = logging.getLogger(__name__)

TODAY = date.today()

COVERAGE_TYPES = ("auto", "home", "health")
VEHICLES = [
    "Toyota Camry 2023", "Nissan Altima 2022", "Tesla Model 3 2023", "Honda Civic 2021",
    "Ford F-150 2020", "VW Golf 2019", "BMW 330i 2022", "Hyundai Tucson 2023",
    "Kia Sportage 2021", "Subaru Outback 2020",
]
CLAIM_DESCRIPTIONS = {
    "auto": [
        "Rear bumper damage after parking lot collision",
        "Windscreen cracked by road debris on highway",
        "Side panel scraped against garage pillar",
        "Front-end damage in intersection collision, police report filed",
        "Hail damage to roof and hood",
        "Vehicle broken into, window smashed, radio stolen",
    ],
    "home": [
        "Burst pipe caused water damage to kitchen floor",
        "Storm damage to roof tiles and gutters",
        "Burglary: forced entry through back door, electronics stolen",
        "Electrical fault caused small fire in laundry room",
        "Fallen tree damaged garage roof",
    ],
    "health": [
        "Emergency appendectomy and two-night hospital stay",
        "Fractured wrist from cycling fall, cast and physiotherapy",
        "MRI scan and specialist consultation for back pain",
        "Outpatient knee arthroscopy",
    ],
}

FRAUD_PATTERNS = [
    (["rear-end collision", "new customer"], 0.67, "high",
     "Staged rear-end collisions are commonly filed shortly after taking out a policy."),
    (["whiplash", "no witnesses"], 0.45, "medium",
     "Soft-tissue injuries without witnesses are hard to disprove and frequently exaggerated."),
    (["minor damage", "rental car"], 0.82, "high",
     "Rental claims attached to trivial damage often signal loss-of-use padding."),
    (["theft", "no forced entry"], 0.71, "high",
     "Theft claims without signs of forced entry correlate with owner give-up fraud."),
    (["total loss", "recently increased", "coverage"], 0.76, "high",
     "Total-loss events shortly after a coverage increase suggest premeditation."),
    (["fire", "financial difficulty"], 0.69, "high",
     "Property fires coinciding with documented financial distress are a classic arson marker."),
    (["soft tissue", "no police report"], 0.48, "medium",
     "Unverifiable soft-tissue injuries without an official report are commonly inflated."),
    (["hit and run", "no witnesses"], 0.41, "medium",
     "Hit-and-run without witnesses can mask single-party damage from excluded causes."),
    (["stolen", "just purchased"], 0.63, "high",
     "Theft of recently purchased high-value items suggests receipt recycling."),
    (["water damage", "delayed report"], 0.38, "medium",
     "Long-delayed water damage reports often bundle pre-existing maintenance issues."),
    (["back injury", "cash settlement"], 0.55, "medium",
     "Pressure for quick cash settlement on subjective injuries is a negotiation red flag."),
    (["multiple claims", "different insurers"], 0.85, "high",
     "The same loss shopped across insurers is outright duplication fraud."),
]


def _policy_dates(status: str, rng: random.Random) -> tuple[date, date]:
    """Return (effective, expiry) consistent with the given status."""
    if status == "expired":
        expiry = TODAY - timedelta(days=rng.randint(30, 400))
        return expiry - timedelta(days=365), expiry
    if status == "pending":
        effective = TODAY + timedelta(days=rng.randint(3, 30))
        return effective, effective + timedelta(days=365)
    if status in ("lapsed", "cancelled"):
        expiry = TODAY - timedelta(days=rng.randint(10, 200))
        return expiry - timedelta(days=365), expiry
    # active
    effective = TODAY - timedelta(days=rng.randint(40, 330))
    return effective, effective + timedelta(days=365)


def _curated(session: Session) -> None:
    """Named records that the sample PDFs and demo narratives depend on."""

    def holder(name, email, phone, address, since_days) -> Policyholder:
        h = Policyholder(
            name=name, email=email, phone=phone, address=address,
            customer_since=TODAY - timedelta(days=since_days),
        )
        session.add(h)
        return h

    def policy(number, h, coverage, limit, deductible, premium, status,
               eff_days_ago, length_days=365, asset=None) -> Policy:
        eff = TODAY - timedelta(days=eff_days_ago)
        p = Policy(
            policy_number=number, holder=h, coverage_type=coverage,
            limit_amount=limit, deductible=deductible, premium=premium, status=status,
            effective_date=eff, expiry_date=eff + timedelta(days=length_days),
            insured_asset=asset,
        )
        session.add(p)
        return p

    def claim(p, days_ago, description, amount, status, incident_offset=3) -> None:
        session.add(Claim(
            policy=p,
            filed_date=TODAY - timedelta(days=days_ago),
            incident_date=TODAY - timedelta(days=days_ago + incident_offset),
            description=description, amount=amount, status=status,
        ))

    # Clean, valid auto claim → APPROVE
    johnny = holder("Johnny Dough", "johnny.dough@example.com", "555-0101",
                    "12 Baker Street, Springfield", 2900)
    p = policy("POL-12345", johnny, "auto", 50_000, 1_000, 1_450, "active", 200,
               asset="Toyota Camry 2023")
    claim(p, 700, "Windscreen chip repair", 350, "paid")

    # Referenced by the original example PDF → APPROVE
    charlie = holder("Charlie Wilson", "charlie.wilson@techmail.co.za", "082-987-6543",
                     "28 Sunset Drive, Fourways, Johannesburg", 1800)
    policy("POL-53276", charlie, "auto", 34_000, 750, 1_100, "active", 150,
           asset="Nissan Altima 2022")

    # Expired home policy → DENY / FLAG
    jane = holder("Jane Smith", "jane.smith@example.com", "555-0134",
                  "123 Main St, Springfield", 2200)
    policy("POL-67890", jane, "home", 250_000, 2_500, 2_050, "expired", 500, 365,
           asset="123 Main St, Springfield")

    # Brand-new customer + whiplash/no-witness claim → fraud FLAG
    marcus = holder("Marcus Reed", "marcus.reed@example.com", "555-0177",
                    "77 Riverside Ave, Springfield", 21)
    policy("POL-77001", marcus, "auto", 45_000, 1_000, 1_600, "active", 20,
           asset="Honda Civic 2021")

    # High-value / near-limit claim → FLAG
    henry = holder("Henry Anderson", "henry.anderson@example.com", "555-0155",
                   "9 Hilltop Road, Springfield", 1500)
    policy("POL-90281", henry, "auto", 76_889, 2_000, 2_400, "active", 180,
           asset="Tesla Model 3 2023")

    # Name-mismatch scenario: policy belongs to Alice, claimant will be "Tom Brown"
    alice = holder("Alice Brown", "alice.brown@example.com", "555-0122",
                   "101 Elm St, Springfield", 2600)
    policy("POL-55295", alice, "home", 241_178, 2_000, 1_900, "active", 90,
           asset="101 Elm St, Springfield")

    # Repeat claimant: 3 claims in the last ~5 months → velocity flag
    priya = holder("Priya Natarajan", "priya.n@example.com", "555-0188",
                   "4 Lakeview Court, Springfield", 1100)
    p = policy("POL-31415", priya, "auto", 40_000, 800, 1_350, "active", 300,
               asset="VW Golf 2019")
    claim(p, 150, "Minor damage to front bumper, rental car requested", 1_900, "paid")
    claim(p, 95, "Scratched side panel in car park, rental car requested", 1_400, "approved")
    claim(p, 30, "Minor damage to rear door, rental car requested", 2_100, "submitted")

    # Missing-policy-number scenario: confirming this number resolves the claim
    sofia = holder("Sofia Ramirez", "sofia.ramirez@example.com", "555-0166",
                   "58 Orchard Lane, Springfield", 900)
    policy("POL-88472", sofia, "home", 180_000, 1_500, 1_700, "active", 120,
           asset="58 Orchard Lane, Springfield")

    # A lapsed policy for the explorer / ad-hoc demos
    bob = holder("Bob Johnson", "bob.johnson@example.com", "555-0119",
                 "31 Cedar Street, Springfield", 3000)
    policy("POL-11223", bob, "health", 1_000_000, 5_000, 4_800, "lapsed", 400)


def _bulk(session: Session, holders: int = 50) -> None:
    fake = Faker()
    Faker.seed(42)
    rng = random.Random(42)
    used_numbers = {p.policy_number for p in session.new if isinstance(p, Policy)}

    for _ in range(holders):
        h = Policyholder(
            name=fake.name(),
            email=fake.email(),
            phone=fake.phone_number(),
            address=fake.address().replace("\n", ", "),
            customer_since=TODAY - timedelta(days=rng.randint(60, 4000)),
        )
        session.add(h)

        for _ in range(rng.choice((1, 1, 1, 2, 2, 3))):
            number = f"POL-{rng.randint(10000, 99999)}"
            while number in used_numbers:
                number = f"POL-{rng.randint(10000, 99999)}"
            used_numbers.add(number)

            coverage = rng.choice(COVERAGE_TYPES)
            status = rng.choices(
                ("active", "pending", "expired", "lapsed", "cancelled"),
                weights=(60, 8, 18, 8, 6),
            )[0]
            effective, expiry = _policy_dates(status, rng)
            if coverage == "auto":
                limit, deductible, asset = rng.randint(25, 90) * 1000, rng.choice((500, 750, 1000, 2000)), rng.choice(VEHICLES)
            elif coverage == "home":
                limit, deductible, asset = rng.randint(150, 500) * 1000, rng.choice((1000, 2000, 2500, 5000)), h.address
            else:
                limit, deductible, asset = rng.randint(500, 2000) * 1000, rng.choice((3000, 5000, 8000)), None

            p = Policy(
                policy_number=number, holder=h, coverage_type=coverage,
                limit_amount=limit, deductible=deductible,
                premium=round(limit * rng.uniform(0.015, 0.04), 2),
                status=status, effective_date=effective, expiry_date=expiry,
                insured_asset=asset,
            )
            session.add(p)

            # Claims history (some policies clean, some busy)
            for _ in range(rng.choices((0, 1, 2, 3), weights=(35, 35, 20, 10))[0]):
                incident = effective + timedelta(
                    days=rng.randint(1, max(2, (min(expiry, TODAY) - effective).days))
                )
                session.add(Claim(
                    policy=p,
                    filed_date=incident + timedelta(days=rng.randint(0, 14)),
                    incident_date=incident,
                    description=rng.choice(CLAIM_DESCRIPTIONS[coverage]),
                    amount=round(rng.uniform(0.02, 0.6) * limit / 10, 2) * 10,
                    status=rng.choices(
                        ("paid", "approved", "denied", "flagged", "submitted"),
                        weights=(40, 20, 15, 10, 15),
                    )[0],
                ))


def seed(session: Session) -> None:
    _curated(session)
    _bulk(session)
    for keywords, rate, level, rationale in FRAUD_PATTERNS:
        session.add(FraudPattern(
            keywords=keywords, fraud_rate=rate, risk_level=level, rationale=rationale
        ))
    session.flush()
    logger.info("Seeded demo data")


if __name__ == "__main__":
    import sys

    from sqlalchemy import delete

    from db.models import Base
    from db.session import get_engine, get_session, init_db

    logging.basicConfig(level=logging.INFO)
    init_db()
    if "--reset" in sys.argv:
        Base.metadata.drop_all(get_engine())
        init_db()
    with get_session() as s:
        for table in (Claim, Policy, Policyholder, FraudPattern):
            s.execute(delete(table))
        seed(s)
    print("Database seeded.")
