"""Claims queue: browsable audit log of every triage run."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from agents.schemas import DECISION_LABELS, Decision, TraceStep, TriageResult
from db.repository import get_run, recent_runs
from ui.components import chips, decision_card, field_label, page_header, render_trace, section


def render() -> None:
    page_header(
        "Claims Queue",
        "An overview of every claim evaluation you have run. Select a run by its number "
        "below the table to see its extracted fields and the agent's full reasoning trail.",
    )

    runs = recent_runs()
    if not runs:
        st.info("No triage runs yet. Analyse a document on the Triage page first.")
        return

    decisions = st.segmented_control(
        "Filter by decision",
        [d.value for d in Decision],
        format_func=lambda v: DECISION_LABELS[Decision(v)],
        selection_mode="multi",
    )
    filtered = [r for r in runs if not decisions or r.decision in decisions]

    df = pd.DataFrame(
        {
            "Run": [r.id for r in filtered],
            "When": [r.created_at.strftime("%Y-%m-%d %H:%M") for r in filtered],
            "Document": [r.document_name for r in filtered],
            "Decision": [DECISION_LABELS.get(Decision(r.decision), r.decision) for r in filtered],
            "Confidence": [r.confidence for r in filtered],
            "Red flags": [len(r.red_flags or []) for r in filtered],
            "Overridden": [r.override_decision if r.override_decision else "" for r in filtered],
        }
    )
    st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        column_config={
            "Run": st.column_config.NumberColumn(width="small"),
            "Confidence": st.column_config.ProgressColumn(
                min_value=0.0, max_value=1.0, format="percent"
            ),
            "Red flags": st.column_config.NumberColumn(width="small"),
        },
    )

    section("→", "Inspect a run")
    selected = st.selectbox(
        "Inspect a run",
        [r.id for r in filtered],
        format_func=lambda i: f"Run #{i}",
        label_visibility="collapsed",
    )
    run = get_run(selected)
    if run is None:
        return

    result = TriageResult(
        decision=Decision(run.decision),
        confidence=run.confidence if run.confidence is not None else 0.0,
        red_flags=run.red_flags or [],
        reasoning_summary=run.reasoning_summary or "",
    )
    override = (
        f"{DECISION_LABELS.get(Decision(run.override_decision), run.override_decision)}: "
        f"{run.override_note} ({run.overridden_at:%Y-%m-%d %H:%M})"
        if run.override_decision
        else None
    )
    chips(
        [
            (f"Run #{run.id}", "accent"),
            (run.document_name, ""),
            (f"{run.created_at:%Y-%m-%d %H:%M}", ""),
        ]
    )
    decision_card(result, overridden=override)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("##### Extracted fields")
        if run.extracted_fields:
            for name, f in run.extracted_fields.items():
                st.markdown(f"- **{field_label(name)}**: {f['value']} ({f['confidence']:.0%})")
        else:
            st.caption("None extracted.")
    with col2:
        st.markdown("##### User-confirmed fields")
        if run.user_confirmed_fields:
            for name, value in run.user_confirmed_fields.items():
                st.markdown(f"- **{field_label(name)}**: {value}")
        else:
            st.caption("None. The agent didn't need help on this run.")

    render_trace([TraceStep(**step) for step in (run.trace or [])])
