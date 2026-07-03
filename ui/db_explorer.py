"""Database explorer: browse the data the agent checks claims against."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from db.session import get_engine
from ui.components import page_header, stat_tile


@st.cache_data(ttl=60)
def _table(query: str) -> pd.DataFrame:
    return pd.read_sql(query, get_engine())


def render() -> None:
    page_header(
        "Database Explorer",
        "A synthetic relational database backing the agent's tools. Use it to pick "
        "policy numbers and names for your own test documents.",
    )

    counts = _table(
        """
        SELECT (SELECT COUNT(*) FROM policies)      AS policies,
               (SELECT COUNT(*) FROM policyholders) AS holders,
               (SELECT COUNT(*) FROM claims)        AS claims,
               (SELECT COUNT(*) FROM fraud_patterns) AS patterns
        """
    ).iloc[0]
    for col, (label, value) in zip(
        st.columns(4),
        [
            ("Policies", counts["policies"]),
            ("Policyholders", counts["holders"]),
            ("Claims on file", counts["claims"]),
            ("Fraud patterns", counts["patterns"]),
        ],
        strict=True,
    ):
        with col:
            stat_tile(label, value)

    policies_tab, holders_tab, claims_tab, fraud_tab = st.tabs(
        ["Policies", "Policyholders", "Claims history", "Fraud patterns"]
    )

    with policies_tab:
        search = st.text_input("Search by policy number or holder name", key="pol_search")
        df = _table(
            """
            SELECT p.policy_number, h.name AS policyholder, p.coverage_type,
                   p.status, p.limit_amount, p.deductible, p.premium,
                   p.effective_date, p.expiry_date, p.insured_asset
            FROM policies p JOIN policyholders h ON h.id = p.holder_id
            ORDER BY p.policy_number
            """
        )
        if search:
            mask = (
                df["policy_number"].str.contains(search, case=False)
                | df["policyholder"].str.contains(search, case=False)
            )
            df = df[mask]
        st.dataframe(df, width="stretch", hide_index=True)
        st.caption(f"{len(df)} policies")

    with holders_tab:
        st.dataframe(
            _table("SELECT name, email, phone, address, customer_since FROM policyholders ORDER BY name"),
            width="stretch",
            hide_index=True,
        )

    with claims_tab:
        st.dataframe(
            _table(
                """
                SELECT c.policy_number, c.filed_date, c.incident_date,
                       c.description, c.amount, c.status
                FROM claims c ORDER BY c.filed_date DESC
                """
            ),
            width="stretch",
            hide_index=True,
        )

    with fraud_tab:
        st.dataframe(
            _table("SELECT keywords, fraud_rate, risk_level, rationale FROM fraud_patterns"),
            width="stretch",
            hide_index=True,
        )
        st.caption("A pattern only matches when ALL of its keywords appear in the incident description.")
