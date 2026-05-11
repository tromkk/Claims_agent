import streamlit as st
import json
from pathlib import Path
from parsers.pdf_parser import process_pdf
from agents.react_agent import get_agent_executor

st.set_page_config(
    page_title="Insurance Claims AI Agent",
    page_icon="📃",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    .main .block-container {
        max-width: 860px;
        margin: 0 auto;
        padding: 2rem;
    }
    .section-card {
        background: #1e1e1e;
        border: 1px solid #333;
        border-radius: 12px;
        padding: 1.5rem 2rem;
        margin-bottom: 1.5rem;
    }
    .section-header {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        margin-bottom: 1.25rem;
    }
    .step-badge {
        background: #c0392b;
        color: white;
        border-radius: 50%;
        width: 32px;
        height: 32px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: bold;
        font-size: 0.95rem;
        flex-shrink: 0;
    }
</style>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.header("Data Status")
    if Path("data/policies.json").exists():
        policies = json.load(open("data/policies.json"))
        st.success(f"✅ {len(policies)} policies loaded")
    else:
        st.warning("⚠️ Create data/policies.json")
    if Path("data/fraud_patterns.json").exists():
        patterns = json.load(open("data/fraud_patterns.json"))
        st.success(f"✅ {len(patterns)} fraud patterns")
    else:
        st.warning("⚠️ Create data/fraud_patterns.json")

# MAIN APP

st.title("Insurance Claims AI Agent")
st.markdown("Automate claims triage: **parse → classify → extract → route**")
st.divider()


# SECTION 1 — Upload Document

st.markdown("""
<div class="section-header">
    <div class="step-badge">1</div>
    <h3 style="margin:0">Start by uploading a claim document</h3>
</div>
""", unsafe_allow_html=True)

uploaded_file = st.file_uploader(
    "Upload a PDF claim, renewal, or complaint",
    type="pdf",
    help="Supports text PDFs, forms, and scanned docs",
    label_visibility="collapsed"
)

col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    st.markdown("<div style='text-align:center; color:#888; margin: 0.5rem 0'>— or —</div>", unsafe_allow_html=True)
    load_example = st.button("Load example claim", type="primary", use_container_width=True)

# Resolve PDF path
pdf_path, source_label = None, None
if uploaded_file:
    with open("temp.pdf", "wb") as f:
        f.write(uploaded_file.getvalue())
    pdf_path = "temp.pdf"
    source_label = uploaded_file.name
elif load_example:
    pdf_path = "sample_pdfs/example_claim_car_valid.pdf"
    source_label = "example_claim_car_valid.pdf"

# Parse PDF
if pdf_path:
    with st.spinner("Parsing PDF..."):
        docs = process_pdf(pdf_path)
        extracted_text = "\n\n".join(d.page_content for d in docs)
    st.session_state.extracted_text = extracted_text
    st.session_state.pdf_ready = True

    st.success(f"✅ **{source_label}** parsed successfully")
    with st.expander("Preview extracted text", expanded=False):
        edited = st.text_area(
            "Raw text + form fields (editable)",
            extracted_text,
            height=220,
            label_visibility="collapsed"
        )
        if edited != extracted_text:
            st.session_state.extracted_text = edited

st.divider()

# SECTION 2 — Run Agent Analysis

st.markdown("""
<div class="section-header">
    <div class="step-badge">2</div>
    <h3 style="margin:0">Then, run the agent analysis</h3>
</div>
""", unsafe_allow_html=True)

pdf_ready = st.session_state.get("pdf_ready", False)

if not pdf_ready:
    st.info("⬆️ Upload or load the example of a claim document first to enable this analysis section.")
else:
    st.markdown(f"Ready to analyse **{source_label or 'uploaded document'}**.")

    if st.button("▶ Run Agent Now", type="primary", use_container_width=True, disabled=not pdf_ready):
        with st.spinner("Agent reasoning..."):
            try:
                executor = get_agent_executor()
                agent_input = f"""
                INSURANCE CLAIM DOCUMENT:
                {st.session_state.extracted_text[:4000]}

                INSTRUCTIONS: Parse this OCR output for key fields:
                LOOK FOR: Policy Number, Name, Vehicle (if applicable), Registration (if applicable), Damage/incident description

                Then reason step-by-step:
                1. Extract policy number → use policy_lookup_tool
                2. Find incident description → use fraud_search_tool
                3. Check claim amounts → use amount_validator_tool
                4. Make final triage decision (Approve/Deny/Flag)

                Only call tools when relevant data exists. Explain your reasoning.
                """
                result = executor.invoke({"input": agent_input})

                # ── Steps ──
                steps = result.get("intermediate_steps", [])
                if steps:
                    st.markdown("#### Agent reasoning trail and tools used")
                    for i, (action, observation) in enumerate(steps, start=1):
                        with st.expander(f"Step {i}: `{getattr(action, 'tool', 'Agent')}`", expanded=False):
                            if hasattr(action, "log") and action.log:
                                st.info(action.log.strip())
                            if hasattr(action, "tool"):
                                st.code(f"Tool: {action.tool}\nInput: {action.tool_input}", language="text")
                            st.success(str(observation)[:500] + ("..." if len(str(observation)) > 500 else ""))

                # ── Final Decision ──
                st.markdown("#### Final Decision")
                decision = result.get("output", "No decision returned.")

                # Colour the decision box based on outcome
                decision_upper = decision.upper()
                if "DENY" in decision_upper:
                    st.error(decision)
                elif "FLAG" in decision_upper:
                    st.warning(decision)
                elif "MONITORING" in decision_upper:
                    st.warning(decision)
                else:
                    st.success(decision)

            except Exception as e:
                st.error(f"Agent error: {str(e)}")
                st.info("Check console for verbose logs")