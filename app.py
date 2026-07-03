"""App entry point: navigation, sidebar status panel, and one-time DB seeding."""

import logging

import streamlit as st

logging.basicConfig(level=logging.INFO)

st.set_page_config(
    page_title="Insurance Claims AI Agent",
    layout="wide",
    initial_sidebar_state="collapsed",
)

from ui import theme

theme.inject_css()


@st.cache_resource
def _bootstrap_database() -> bool:
    from db.session import ensure_seeded

    ensure_seeded()
    return True


_bootstrap_database()


def _sidebar() -> None:
    from sqlalchemy import func, select

    from config import get_settings
    from db.models import TriageRun
    from db.session import get_session
    from ui.components import chips, stat_tile

    settings = get_settings()
    with st.sidebar:
        st.markdown(
            """
<div class="wordmark">
  <div class="wm-title">Current <span>session</span></div>
</div>
""",
            unsafe_allow_html=True,
        )

        with get_session() as session:
            run_count = session.scalar(select(func.count()).select_from(TriageRun))
        stat_tile("Triage runs", run_count)

        if settings.groq_api_key or settings.openai_api_key:
            chips([("LLM connected", "ok")])
        else:
            chips([("No LLM API key configured", "danger")])
        if settings.use_legacy_react_agent:
            chips([("Legacy text-ReAct agent enabled", "warn")])


_sidebar()

from ui import claims_queue, db_explorer, triage  # noqa: E402 - after page config

navigation = st.navigation(
    {
        "Views": [
            st.Page(triage.render, title="Triage", url_path="triage", default=True),
            st.Page(claims_queue.render, title="Claims Queue", url_path="queue"),
            st.Page(db_explorer.render, title="Database Explorer", url_path="database"),
        ]
    }
)
navigation.run()
