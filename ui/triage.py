"""Triage page: upload → parse → agent run → human-in-the-loop confirmation → override."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import streamlit as st

from agents.llm import LLMConfigError
from agents.schemas import DECISION_LABELS, Decision, ExtractedFields
from agents.triage_agent import run_triage
from config import get_settings
from db.repository import apply_override, save_triage_run
from parsers.pdf_parser import process_pdf
from tools.policy_lookup import suggest_policy_numbers
from ui.components import (
    chips,
    decision_card,
    field_label,
    page_header,
    render_trace,
    render_trace_step_live,
    section,
)

SAMPLES_DIR = Path("sample_pdfs")


# ── Session helpers ────────────────────────────────────────────────────────────


def _reset_run_state() -> None:
    for key in ("outcome", "run_id", "confirmed_fields", "override_display"):
        st.session_state.pop(key, None)


def _load_document(doc_id: str, name: str, path: str) -> None:
    if st.session_state.get("doc_id") == doc_id:
        return
    with st.spinner(f"Parsing {name}…"):
        parsed = process_pdf(path)
    st.session_state.doc_id = doc_id
    st.session_state.doc = {
        "name": name,
        "text": parsed.text,
        "used_ocr": parsed.used_ocr,
        "num_pages": parsed.num_pages,
        "error": parsed.error,
    }
    _reset_run_state()


def _confirmed() -> dict:
    return st.session_state.setdefault("confirmed_fields", {})


# ── Agent execution ────────────────────────────────────────────────────────────


def _execute_run() -> None:
    doc = st.session_state.doc
    confirmed = _confirmed()
    status = st.status("Agent analysing the claim…", expanded=True)
    step_count = 0

    def on_step(step):
        nonlocal step_count
        step_count += 1
        render_trace_step_live(status, step, step_count)

    try:
        outcome = run_triage(doc["text"], confirmed_fields=confirmed or None, on_step=on_step)
    except LLMConfigError as exc:
        status.update(label="LLM not configured", state="error")
        st.error(str(exc))
        return
    except Exception as exc:  # noqa: BLE001 - surface anything to the user
        status.update(label="Agent run failed", state="error")
        st.error(f"Agent error: {exc}")
        return

    status.update(
        label=f"Agent finished: {step_count} tool call(s), decision "
        f"{DECISION_LABELS[outcome.result.decision]}",
        state="complete",
        expanded=False,
    )
    st.session_state.outcome = outcome
    st.session_state.run_id = save_triage_run(doc["name"], outcome, confirmed)


def _confirm_and_rerun(updates: dict[str, str]) -> None:
    _confirmed().update({k: v.strip() for k, v in updates.items() if v and v.strip()})
    _execute_run()
    st.rerun()


# ── Sections ───────────────────────────────────────────────────────────────────


def _document_section() -> None:
    section("01", "Claim document")
    upload_tab, samples_tab = st.tabs(["Upload PDF", "Sample gallery"])

    with upload_tab:
        uploaded = st.file_uploader(
            "Upload a claim document (PDF)", type="pdf", label_visibility="collapsed"
        )
        if uploaded is not None:
            doc_id = f"upload:{uploaded.name}:{uploaded.size}"
            if st.session_state.get("doc_id") != doc_id:
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(uploaded.getvalue())
                _load_document(doc_id, uploaded.name, tmp.name)
                Path(tmp.name).unlink(missing_ok=True)

    with samples_tab:
        manifest_path = SAMPLES_DIR / "manifest.json"
        if manifest_path.exists():
            samples = json.loads(manifest_path.read_text(encoding="utf-8"))
        else:
            samples = [
                {"file": p.name, "title": p.stem, "description": ""}
                for p in sorted(SAMPLES_DIR.glob("*.pdf"))
            ]
        if not samples:
            st.info("No sample documents found. Run `python scripts/generate_sample_pdfs.py`.")
        else:
            by_title = {s["title"]: s for s in samples}
            picked = st.pills(
                "Pick a scenario",
                list(by_title),
                default=next(iter(by_title)),
                label_visibility="collapsed",
            )
            if picked:
                choice = by_title[picked]
                st.caption(choice.get("description", ""))
                if st.button("Load this sample", type="primary"):
                    _load_document(
                        f"sample:{choice['file']}",
                        choice["file"],
                        str(SAMPLES_DIR / choice["file"]),
                    )

    doc = st.session_state.get("doc")
    if not doc:
        return
    if doc.get("error"):
        st.error(doc["error"])
        return

    badges = [(doc["name"], "accent"), (f"{doc['num_pages']} page(s)", "")]
    if doc["used_ocr"]:
        badges.append(("scanned: OCR used, extraction confidence lowered", "warn"))
    chips(badges)
    with st.expander("Preview / edit extracted text", expanded=False):
        edited = st.text_area(
            "Extracted text (editable)", doc["text"], height=220, label_visibility="collapsed"
        )
        if edited != doc["text"]:
            doc["text"] = edited
            _reset_run_state()


def _needs_info_section() -> None:
    """The human-in-the-loop core: ask the user to confirm/supply uncertain fields."""
    outcome = st.session_state.outcome
    result = outcome.result
    confirmed = _confirmed()
    missing = [f for f in result.missing_or_uncertain_fields if f not in confirmed]
    if result.decision != Decision.NEEDS_INFO and not missing:
        return

    st.markdown(
        """
<div class="callout">
  <div class="callout-title">The agent needs your input</div>
  <div class="callout-body">These fields could not be extracted with enough confidence.
  Confirm or correct them and the agent will re-run with your values treated as
  authoritative.</div>
</div>
""",
        unsafe_allow_html=True,
    )

    if "policy_number" in missing:
        extracted_pn = outcome.extracted.policy_number
        candidate = extracted_pn.value if extracted_pn else ""
        if extracted_pn and extracted_pn.source_snippet:
            st.caption(f"Seen in document: “…{extracted_pn.source_snippet}…”")
        suggestions = suggest_policy_numbers(candidate) if candidate else []
        if suggestions:
            st.markdown("**Did you mean one of these policies?**")
            cols = st.columns(len(suggestions))
            for col, s in zip(cols, suggestions, strict=False):
                label = f"{s['policy_number']}\n{s['holder']} · {s['coverage_type']} · {s['score']:.0f}% match"
                if col.button(label, key=f"suggest_{s['policy_number']}"):
                    _confirm_and_rerun({"policy_number": s["policy_number"]})

    with st.form("needs_info_form"):
        inputs: dict[str, str] = {}
        for name in missing:
            current = getattr(outcome.extracted, name, None)
            inputs[name] = st.text_input(
                field_label(name),
                value=(current.value if current else ""),
                help=(f"Agent's guess (confidence {current.confidence:.0%}); "
                      f"source: “{current.source_snippet}”") if current else "Not found in the document",
            )
        if st.form_submit_button("Confirm & re-run agent", type="primary"):
            _confirm_and_rerun(inputs)


def _review_panel() -> None:
    outcome = st.session_state.outcome
    confirmed = _confirmed()
    with st.expander("Review / correct extracted fields and re-run", expanded=False):
        with st.form("review_form"):
            inputs: dict[str, str] = {}
            for name in ExtractedFields.model_fields:
                field = getattr(outcome.extracted, name, None)
                value = confirmed.get(name) or (field.value if field else "")
                conf = "user-confirmed" if name in confirmed else (
                    f"{field.confidence:.0%} confidence" if field else "not found"
                )
                inputs[name] = st.text_input(f"{field_label(name)} ({conf})", value=value)
            if st.form_submit_button("Re-run with corrections"):
                _confirm_and_rerun(inputs)


def _override_section() -> None:
    run_id = st.session_state.get("run_id")
    if not run_id:
        return
    with st.expander("Reviewer override (recorded in the audit log)", expanded=False):
        decision = st.selectbox(
            "Final decision",
            [d.value for d in Decision],
            index=[d.value for d in Decision].index(st.session_state.outcome.result.decision.value),
        )
        note = st.text_area("Override note (required)", placeholder="Why are you overriding?")
        if st.button("Record override"):
            if not note.strip():
                st.warning("An override note is required.")
            else:
                apply_override(run_id, decision, note.strip())
                st.session_state.override_display = f"{DECISION_LABELS[Decision(decision)]}: {note.strip()}"
                st.rerun()


def _results_section() -> None:
    outcome = st.session_state.get("outcome")
    if not outcome:
        return
    section("03", "Triage result")
    decision_card(outcome.result, overridden=st.session_state.get("override_display"))
    _needs_info_section()
    render_trace(outcome.trace)
    _review_panel()
    _override_section()
    st.caption(f"Run #{st.session_state.get('run_id', '-')} recorded in the audit log "
               "(see the Claims Queue page).")


def render() -> None:
    page_header(
        "Insurance Claims Triage Agent",
        "Agentic pre-screening for incoming claims: the agent reads the document, "
        "verifies it against company records, and recommends a decision. Whenever it "
        "is unsure, it asks you to clarify; the final decision is always yours.",
        flows=[
            ("You", "upload a PDF (digital or scanned) → confirm anything the agent "
                    "asks → review the reasoning trail → accept or override"),
            ("Agent", "parses the PDF → extracts fields → verifies against company data → checks "
                      "fraud signals → recommends a decision"),
        ],
    )

    _document_section()

    section("02", "Agent analysis")
    doc = st.session_state.get("doc")
    if not doc or doc.get("error"):
        st.info("Load a claim document above to enable the analysis.")
    else:
        settings = get_settings()
        if not (settings.groq_api_key or settings.openai_api_key):
            st.warning(
                "No LLM API key configured: set `GROQ_API_KEY` or `OPENAI_API_KEY` "
                "as an environment variable or Streamlit secret."
            )
        if st.button("Run agent triage", type="primary", width="stretch"):
            _confirmed().clear()
            st.session_state.pop("override_display", None)
            _execute_run()

    _results_section()
