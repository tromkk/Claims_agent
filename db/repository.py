"""Persistence helpers for triage runs (audit log) used by the UI."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from agents.schemas import TriageOutcome
from db.models import TriageRun
from db.session import get_session


def save_triage_run(
    document_name: str, outcome: TriageOutcome, confirmed_fields: dict | None
) -> int:
    with get_session() as session:
        run = TriageRun(
            document_name=document_name,
            extracted_fields=outcome.extracted.as_display_dict(),
            user_confirmed_fields=confirmed_fields or {},
            trace=[step.to_dict() for step in outcome.trace],
            decision=outcome.result.decision.value,
            confidence=outcome.result.confidence,
            reasoning_summary=outcome.result.reasoning_summary,
            red_flags=outcome.result.red_flags,
        )
        session.add(run)
        session.flush()
        return run.id


def apply_override(run_id: int, decision: str, note: str) -> None:
    with get_session() as session:
        run = session.get(TriageRun, run_id)
        if run is None:
            raise ValueError(f"Triage run {run_id} not found")
        run.override_decision = decision
        run.override_note = note
        run.overridden_at = datetime.utcnow()


def recent_runs(limit: int = 200) -> list[TriageRun]:
    with get_session() as session:
        return list(
            session.execute(
                select(TriageRun).order_by(TriageRun.created_at.desc()).limit(limit)
            ).scalars()
        )


def get_run(run_id: int) -> TriageRun | None:
    with get_session() as session:
        return session.get(TriageRun, run_id)
