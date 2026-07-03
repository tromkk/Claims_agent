"""Design tokens and the global stylesheet.

Palette (notes/colour-swatch.md): ink, charcoal, mist, navy, periwinkle, oxblood.
Widget-level colors live in .streamlit/config.toml; this module holds the tokens
shared by hand-rolled HTML components plus the CSS Streamlit can't express natively.
"""

from __future__ import annotations

import streamlit as st

INK = "#0B0B0B"
CHARCOAL = "#2E2E2E"
MIST = "#E6E8EB"
NAVY = "#1F3A5F"
PERIWINKLE = "#B6BBE8"
OXBLOOD = "#8C1D18"

SURFACE = "#161618"  # raised card surface between ink and charcoal
MUTED = "#9CA0A8"  # secondary text
BORDER = "#2E2E2E"

# Semantic status colors re-tuned for the dark background. Green/amber sit outside
# the swatch but are required for scannable decision semantics; they are muted to
# match. DENY borrows the swatch's oxblood, NEEDS_INFO its periwinkle.
GREEN = "#4E9F6E"
GOLD = "#D9A93F"
AMBER = "#C97B3D"
RED = "#C4524B"  # lightened oxblood for text contrast

_FONTS = (
    "@import url('https://fonts.googleapis.com/css2"
    "?family=Inter:wght@400;500;600"
    "&family=Space+Grotesk:wght@500;600;700"
    "&family=JetBrains+Mono:wght@400;500&display=swap');"
)

_CSS = f"""
<style>
{_FONTS}

.stMainBlockContainer {{ max-width: 52rem; padding-top: 2.5rem; }}

h1, h2, h3 {{ letter-spacing: -0.02em; }}
[data-testid="stHeaderActionElements"] {{ display: none; }}  /* anchor icons */
#MainMenu, footer, [data-testid="stAppDeployButton"] {{ visibility: hidden; }}

code, pre, kbd {{ font-family: 'JetBrains Mono', monospace; }}

::-webkit-scrollbar {{ width: 10px; height: 10px; }}
::-webkit-scrollbar-thumb {{ background: {CHARCOAL}; border-radius: 6px; }}
::-webkit-scrollbar-track {{ background: transparent; }}

/* ── Page hero ─────────────────────────────────────────────────────── */
.hero {{ margin: 0 0 0.5rem 0; }}
.hero .hero-title {{
  font-family: 'Space Grotesk', sans-serif; font-size: 2.1rem; font-weight: 700;
  letter-spacing: -0.02em; color: {MIST}; line-height: 1.15; margin: 0.15rem 0 0.4rem 0;
}}
.hero .hero-sub {{ color: {MUTED}; font-size: 1rem; max-width: 46rem; }}
.hero .hero-flows {{ margin-top: 0.8rem; }}
.hero .hero-flow {{
  font-family: 'JetBrains Mono', monospace; font-size: 0.78rem; color: {MUTED};
  margin: 0.2rem 0; overflow-wrap: anywhere;
}}
.hero .hero-flow .hf-label {{ color: {PERIWINKLE}; font-weight: 500; }}

/* ── Kickers (numbered section labels) ─────────────────────────────── */
.kicker {{
  display: flex; align-items: center; gap: 0.6rem;
  font-family: 'Space Grotesk', sans-serif; font-size: 0.78rem; font-weight: 600;
  letter-spacing: 0.18em; text-transform: uppercase; color: {PERIWINKLE};
  margin: 1.6rem 0 0.8rem 0;
}}
.kicker .kicker-num {{
  color: {MIST}; background: {NAVY}; border-radius: 6px;
  padding: 0.1rem 0.45rem; font-size: 0.75rem; letter-spacing: 0.05em;
}}
.kicker::after {{ content: ""; flex: 1; height: 1px; background: {BORDER}; }}

/* ── Chips ─────────────────────────────────────────────────────────── */
.chip {{
  display: inline-block; border-radius: 999px; padding: 0.15rem 0.7rem;
  margin: 0.1rem 0.35rem 0.1rem 0; font-size: 0.8rem; font-weight: 500;
  background: {SURFACE}; color: {MIST}; border: 1px solid {BORDER};
  white-space: nowrap;
}}
.chip-accent {{ color: {PERIWINKLE}; border-color: rgba(182,187,232,0.4); background: rgba(182,187,232,0.08); }}
.chip-danger {{ color: {RED}; border-color: rgba(140,29,24,0.65); background: rgba(140,29,24,0.18); }}
.chip-ok {{ color: {GREEN}; border-color: rgba(78,159,110,0.45); background: rgba(78,159,110,0.10); }}
.chip-warn {{ color: {GOLD}; border-color: rgba(217,169,63,0.45); background: rgba(217,169,63,0.10); }}

/* ── Cards ─────────────────────────────────────────────────────────── */
.panel {{
  background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px;
  padding: 1rem 1.25rem; margin: 0.4rem 0 1rem 0;
}}
.callout {{
  background: rgba(182,187,232,0.06); border: 1px solid rgba(182,187,232,0.35);
  border-left: 4px solid {PERIWINKLE}; border-radius: 10px;
  padding: 1rem 1.25rem; margin: 0.6rem 0 0.9rem 0;
}}
.callout .callout-title {{
  font-family: 'Space Grotesk', sans-serif; font-weight: 600; font-size: 1.05rem;
  color: {PERIWINKLE}; margin-bottom: 0.25rem;
}}
.callout .callout-body {{ color: {MUTED}; font-size: 0.9rem; }}

/* ── Decision card ─────────────────────────────────────────────────── */
.decision-card {{
  background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px;
  padding: 1.2rem 1.4rem; margin: 0.5rem 0 1rem 0; position: relative; overflow: hidden;
}}
.decision-card::before {{
  content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 5px;
  background: var(--decision-color, {PERIWINKLE});
}}
.decision-badge {{
  display: inline-block; font-family: 'Space Grotesk', sans-serif; font-weight: 700;
  font-size: 1.05rem; letter-spacing: 0.02em; border-radius: 8px;
  padding: 0.3rem 0.9rem; margin-bottom: 0.6rem;
}}
.decision-reason {{ color: {MIST}; margin: 0.2rem 0 0.7rem 0; line-height: 1.55; }}

/* ── Confidence meter ──────────────────────────────────────────────── */
.meter {{ margin-top: 0.8rem; }}
.meter .meter-label {{
  display: flex; justify-content: space-between; color: {MUTED};
  font-size: 0.78rem; letter-spacing: 0.08em; text-transform: uppercase;
  margin-bottom: 0.35rem;
}}
.meter .meter-track {{ background: {CHARCOAL}; border-radius: 999px; height: 8px; overflow: hidden; }}
.meter .meter-fill {{
  height: 100%; border-radius: 999px;
  background: linear-gradient(90deg, {NAVY}, {PERIWINKLE});
}}

/* ── Reasoning-trail timeline ──────────────────────────────────────── */
.tl-step {{ display: flex; gap: 0.8rem; }}
.tl-rail {{ display: flex; flex-direction: column; align-items: center; }}
.tl-node {{
  width: 26px; height: 26px; border-radius: 50%; flex: 0 0 auto;
  display: flex; align-items: center; justify-content: center;
  background: {NAVY}; color: {MIST}; font-family: 'Space Grotesk', sans-serif;
  font-size: 0.78rem; font-weight: 600; border: 1px solid rgba(182,187,232,0.35);
}}
.tl-rail .tl-line {{ width: 2px; flex: 1; background: {BORDER}; margin: 2px 0; }}
.tl-body {{ padding-bottom: 1rem; min-width: 0; flex: 1; }}
.tl-title {{ color: {MIST}; font-weight: 600; font-size: 0.92rem; margin-bottom: 0.2rem; }}
.tl-title code {{ color: {PERIWINKLE}; background: {INK}; padding: 0.05rem 0.4rem; border-radius: 6px; }}
.tl-input {{ color: {MUTED}; font-size: 0.82rem; font-family: 'JetBrains Mono', monospace; margin-bottom: 0.35rem; overflow-wrap: anywhere; }}
.tl-obs {{
  background: {INK}; border: 1px solid {BORDER}; border-radius: 8px;
  padding: 0.55rem 0.8rem; color: {MUTED}; font-size: 0.84rem;
  white-space: pre-wrap; overflow-wrap: anywhere;
  font-family: 'JetBrains Mono', monospace;
}}

/* ── Sidebar ───────────────────────────────────────────────────────── */
[data-testid="stNavSectionHeader"] {{
  font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1.25rem;
  letter-spacing: -0.01em; color: {MIST}; text-transform: none;
}}
.wordmark {{ padding: 0.2rem 0 0.6rem 0; }}
.wordmark .wm-title {{
  font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1.25rem;
  letter-spacing: -0.01em; color: {MIST};
}}
.wordmark .wm-title span {{ color: {PERIWINKLE}; }}
.wordmark .wm-tag {{ color: {MUTED}; font-size: 0.78rem; margin-top: 0.1rem; }}
.stat-tile {{
  background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px;
  padding: 0.55rem 0.75rem; margin-bottom: 0.6rem;
}}
.stat-tile .st-value {{
  font-family: 'Space Grotesk', sans-serif; font-size: 1.35rem; font-weight: 700;
  color: {MIST}; line-height: 1.2;
}}
.stat-tile .st-label {{
  color: {MUTED}; font-size: 0.68rem; letter-spacing: 0.1em; text-transform: uppercase;
}}
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
