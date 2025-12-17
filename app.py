import streamlit as st
import json
import sys
from io import StringIO
from pathlib import Path
from parsers.pdf_parser import process_pdf
from agents.react_agent import get_agent_executor
from langchain_community.callbacks.streamlit import StreamlitCallbackHandler

# Page config
st.set_page_config(
    page_title="Insurance Claims AI Agent",
    page_icon="📃",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Max width of the main col
st.markdown("""
<style>
    .main .block-container {
        max-width: 1000px;  
        margin: 0 auto;
        padding-left: 2rem;
        padding-right: 2rem;
    }
</style>
""", unsafe_allow_html=True)

st.title("Insurance Claims AI Agent")
st.markdown("**Automate claims triage: parse → classify → extract → route**")

# Sidebar for data status
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

# Main app

st.header("PDF Upload")
uploaded_file = st.file_uploader(
    "Upload Claim/Renewal/Complaint PDF", 
    type="pdf",
    help="Supports text PDFs, forms, scanned docs"
)

if uploaded_file:
    # Save uploaded file
    with open("temp.pdf", "wb") as f:
        f.write(uploaded_file.getvalue())
    
    # Parse with PyMuPDF (handles forms + OCR)
    with st.spinner("Parsing PDF (text + filled forms)..."):
        docs = process_pdf("temp.pdf")
        extracted_text = "\n\n".join(d.page_content for d in docs)
    
    # Display extracted text
    st.subheader("Extracted Content")
    st.text_area(
        "Raw text + form fields", 
        extracted_text, 
        height=300,
        label_visibility="collapsed"
    )
    
    # Store in session state
    st.session_state.extracted_text = extracted_text
    st.session_state.pdf_ready = True
    st.success("✅ PDF parsed successfully!")


st.header("Agent Controls ")

if 'pdf_ready' in st.session_state and st.session_state.pdf_ready:
    if st.button("Run Agent Analysis", type="primary", use_container_width=True):
        with st.spinner("Agent reasoning..."):
            try:
                executor = get_agent_executor()

                # capture terminal ooutput
                old_stdout = sys.stdout
                captured_output = StringIO()
                sys.stdout = captured_output
                
                # AGENTIC INPUT - Agent decides which tools to use
                agent_input = f"""
                INSURANCE CLAIM DOCUMENT:
                {st.session_state.extracted_text[:4000]}
                
                INSTRUCTIONS: FIRST, Parse this messy OCR output for key fields:
                    LOOK FOR: Policy Number, Name, Vehicle, Registration, Damage description
                    Even if jumbled, extract what you can.
                    
                THEN, Reason step-by-step about this claim:
                1. Extract policy number → use policy_lookup_tool
                2. Find incident description → use fraud_search_tool  
                3. Check claim amounts → use amount_validator_tool
                4. Make final triage decision (Approve/Deny/Flag)
                
                Only call tools when relevant data exists. Explain your reasoning.
                """
                
                result = executor.invoke({"input": agent_input})
                
                # Restore stdout and get captured logs
                sys.stdout = old_stdout
                agent_logs = captured_output.getvalue()
                
                # DISPLAY TERMINAL LOGS IN UI
                st.markdown("### **Agent Reasoning**")
                st.code(agent_logs, language="text", line_numbers=True)
                
                st.markdown("### **Final Decision**")
                st.success(result["output"])
                
            except Exception as e:
                st.error(f"Agent error: {str(e)}")
                st.info("Check console for verbose logs")
else:
    st.info(" Upload PDF first!")


