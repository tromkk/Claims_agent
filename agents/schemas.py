"""Pydantic schemas for structured agent I/O."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum

from pydantic import BaseModel, Field


class Decision(StrEnum):
    APPROVE = "APPROVE"
    APPROVE_WITH_MONITORING = "APPROVE_WITH_MONITORING"
    FLAG_FOR_REVIEW = "FLAG_FOR_REVIEW"
    DENY = "DENY"
    NEEDS_INFO = "NEEDS_INFO"


DECISION_LABELS = {
    Decision.APPROVE: "Approve",
    Decision.APPROVE_WITH_MONITORING: "Approve with monitoring",
    Decision.FLAG_FOR_REVIEW: "Flag for review",
    Decision.DENY: "Deny",
    Decision.NEEDS_INFO: "Needs information",
}


class ExtractedField(BaseModel):
    """A single field pulled from the document, with provenance."""

    value: str
    confidence: float = Field(ge=0.0, le=1.0)
    source_snippet: str = ""


class ExtractedFields(BaseModel):
    policy_number: ExtractedField | None = None
    claimant_name: ExtractedField | None = None
    incident_date: ExtractedField | None = None
    incident_description: ExtractedField | None = None
    claim_amount: ExtractedField | None = None

    def as_display_dict(self) -> dict[str, dict]:
        return {
            name: f.model_dump()
            for name, f in self.__dict__.items()
            if isinstance(f, ExtractedField)
        }


FIELD_LABELS = {
    "policy_number": "Policy number",
    "claimant_name": "Claimant name",
    "incident_date": "Incident date",
    "incident_description": "Incident description",
    "claim_amount": "Claim amount",
}


class TriageResult(BaseModel):
    """Structured final output of a triage run."""

    decision: Decision = Field(description="Final triage decision")
    confidence: float = Field(
        ge=0.0, le=1.0, description="Overall confidence in the decision"
    )
    missing_or_uncertain_fields: list[str] = Field(
        default_factory=list,
        description="Field names (e.g. 'policy_number') the user should confirm or supply",
    )
    red_flags: list[str] = Field(
        default_factory=list, description="Short labels for each risk indicator found"
    )
    reasoning_summary: str = Field(
        description="2-5 sentence explanation of the decision for a human reviewer"
    )


@dataclass
class TraceStep:
    """One step of the agent loop, for the UI reasoning trail and the audit log."""

    thought: str = ""
    tool: str | None = None
    tool_input: dict = field(default_factory=dict)
    observation: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TriageOutcome:
    """Everything a single run produced."""

    result: TriageResult
    extracted: ExtractedFields
    trace: list[TraceStep] = field(default_factory=list)
