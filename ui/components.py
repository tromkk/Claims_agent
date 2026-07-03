"""Reusable Streamlit rendering components (styled by ui/theme.py)."""

from __future__ import annotations

import html

import streamlit as st

from agents.schemas import DECISION_LABELS, FIELD_LABELS, Decision, TraceStep, TriageResult
from ui import theme

# decision -> (text/border color, translucent background)
DECISION_STYLE = {
    Decision.APPROVE: (theme.GREEN, "rgba(78,159,110,0.16)"),
    Decision.APPROVE_WITH_MONITORING: (theme.GOLD, "rgba(217,169,63,0.16)"),
    Decision.FLAG_FOR_REVIEW: (theme.AMBER, "rgba(201,123,61,0.16)"),
    Decision.DENY: (theme.RED, "rgba(140,29,24,0.22)"),
    Decision.NEEDS_INFO: (theme.PERIWINKLE, "rgba(182,187,232,0.14)"),
}


def page_header(
    title: str,
    subtitle: str = "",
    kicker: str = "Claims triage console",
    flows: list[tuple[str, str]] | None = None,
) -> None:
    """Page hero. `flows` are optional (label, steps) lines rendered small and
    monospace under the subtitle, e.g. ("You", "upload → confirm → decide")."""
    sub = f'<div class="hero-sub">{html.escape(subtitle)}</div>' if subtitle else ""
    flows_html = ""
    if flows:
        rows = "".join(
            f'<div class="hero-flow"><span class="hf-label">{html.escape(label)}:</span> '
            f"{html.escape(steps)}</div>"
            for label, steps in flows
        )
        flows_html = f'<div class="hero-flows">{rows}</div>'
    st.markdown(
        f"""
<div class="hero">
  <div class="kicker" style="margin-top:0">{html.escape(kicker)}</div>
  <div class="hero-title">{html.escape(title)}</div>
  {sub}
  {flows_html}
</div>
""",
        unsafe_allow_html=True,
    )


def section(num: str, label: str) -> None:
    st.markdown(
        f'<div class="kicker"><span class="kicker-num">{html.escape(num)}</span>'
        f"{html.escape(label)}</div>",
        unsafe_allow_html=True,
    )


def chips(items: list[tuple[str, str]]) -> None:
    """Render a row of pills. Each item is (text, kind) with kind in
    {"", "accent", "danger", "ok", "warn"}."""
    parts = [
        f'<span class="chip{" chip-" + kind if kind else ""}">{html.escape(text)}</span>'
        for text, kind in items
    ]
    st.markdown("<div>" + "".join(parts) + "</div>", unsafe_allow_html=True)


def stat_tile(label: str, value: object) -> None:
    st.markdown(
        f'<div class="stat-tile"><div class="st-value">{html.escape(str(value))}</div>'
        f'<div class="st-label">{html.escape(label)}</div></div>',
        unsafe_allow_html=True,
    )


def decision_card(result: TriageResult, overridden: str | None = None) -> None:
    color, bg = DECISION_STYLE[result.decision]
    flags_html = "".join(
        f'<span class="chip chip-danger">{html.escape(flag)}</span>'
        for flag in result.red_flags
    )
    override_html = (
        f'<div style="margin-top:0.7rem;font-size:0.9rem;color:{theme.MIST}">'
        f"<b>Reviewer override:</b> {html.escape(overridden)}</div>"
        if overridden
        else ""
    )
    pct = max(0.0, min(1.0, result.confidence))
    st.markdown(
        f"""
<div class="decision-card" style="--decision-color:{color}">
  <div class="decision-badge" style="color:{color};background:{bg}">
    {html.escape(DECISION_LABELS[result.decision])}
  </div>
  <div class="decision-reason">{html.escape(result.reasoning_summary)}</div>
  <div>{flags_html}</div>
  {override_html}
  <div class="meter">
    <div class="meter-label"><span>Agent confidence</span><span>{pct:.0%}</span></div>
    <div class="meter-track"><div class="meter-fill" style="width:{pct:.0%}"></div></div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def render_trace(trace: list[TraceStep]) -> None:
    if not trace:
        st.caption("The agent reached a decision without calling any tools.")
        return
    section("→", "Reasoning trail")
    steps_html = []
    for i, step in enumerate(trace, start=1):
        last = i == len(trace)
        thought = (
            f'<div class="tl-input" style="font-family:Inter,sans-serif;font-style:italic">'
            f"{html.escape(step.thought)}</div>"
            if step.thought
            else ""
        )
        steps_html.append(f"""
<div class="tl-step">
  <div class="tl-rail"><div class="tl-node">{i}</div>{"" if last else '<div class="tl-line"></div>'}</div>
  <div class="tl-body">
    <div class="tl-title">Called <code>{html.escape(step.tool)}</code></div>
    {thought}
    <div class="tl-input">{html.escape(str(step.tool_input))}</div>
    <div class="tl-obs">{html.escape(step.observation)}</div>
  </div>
</div>""")
    st.markdown("".join(steps_html), unsafe_allow_html=True)


def render_trace_step_live(container, step: TraceStep, index: int) -> None:
    """Streaming variant used inside st.status while the agent runs."""
    container.markdown(f"**Step {index}**: called `{step.tool}` with `{step.tool_input}`")
    container.text(step.observation[:400] + ("…" if len(step.observation) > 400 else ""))


def field_label(name: str) -> str:
    return FIELD_LABELS.get(name, name.replace("_", " ").title())
