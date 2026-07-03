"""SQLAlchemy models for the claims triage database."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Policyholder(Base):
    __tablename__ = "policyholders"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    email: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(40))
    address: Mapped[str] = mapped_column(String(200))
    customer_since: Mapped[date]

    policies: Mapped[list[Policy]] = relationship(back_populates="holder")


class Policy(Base):
    __tablename__ = "policies"

    policy_number: Mapped[str] = mapped_column(String(20), primary_key=True)
    holder_id: Mapped[int] = mapped_column(ForeignKey("policyholders.id"))
    coverage_type: Mapped[str] = mapped_column(String(20))  # auto | home | health
    limit_amount: Mapped[float]
    deductible: Mapped[float]
    premium: Mapped[float]
    status: Mapped[str] = mapped_column(String(20))  # active | pending | expired | lapsed | cancelled
    effective_date: Mapped[date]
    expiry_date: Mapped[date]
    insured_asset: Mapped[str | None] = mapped_column(String(200))  # vehicle / property address

    holder: Mapped[Policyholder] = relationship(back_populates="policies")
    claims: Mapped[list[Claim]] = relationship(back_populates="policy")


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(primary_key=True)
    policy_number: Mapped[str] = mapped_column(
        ForeignKey("policies.policy_number"), index=True
    )
    filed_date: Mapped[date]
    incident_date: Mapped[date]
    description: Mapped[str] = mapped_column(Text)
    amount: Mapped[float]
    status: Mapped[str] = mapped_column(String(20))  # submitted | approved | denied | flagged | paid

    policy: Mapped[Policy] = relationship(back_populates="claims")


class FraudPattern(Base):
    __tablename__ = "fraud_patterns"

    id: Mapped[int] = mapped_column(primary_key=True)
    keywords: Mapped[list] = mapped_column(JSON)  # ALL keywords must appear to match
    fraud_rate: Mapped[float]
    risk_level: Mapped[str] = mapped_column(String(10))  # low | medium | high
    rationale: Mapped[str] = mapped_column(Text)


class TriageRun(Base):
    """Audit log: one row per agent run, including any human corrections/overrides."""

    __tablename__ = "triage_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    document_name: Mapped[str] = mapped_column(String(200))
    extracted_fields: Mapped[dict] = mapped_column(JSON, default=dict)
    user_confirmed_fields: Mapped[dict] = mapped_column(JSON, default=dict)
    trace: Mapped[list] = mapped_column(JSON, default=list)  # tool calls + observations
    decision: Mapped[str] = mapped_column(String(30))
    confidence: Mapped[float | None]
    reasoning_summary: Mapped[str] = mapped_column(Text, default="")
    red_flags: Mapped[list] = mapped_column(JSON, default=list)
    override_decision: Mapped[str | None] = mapped_column(String(30))
    override_note: Mapped[str | None] = mapped_column(Text)
    overridden_at: Mapped[datetime | None]
