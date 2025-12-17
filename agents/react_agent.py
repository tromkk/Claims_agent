import os
from dotenv import load_dotenv
load_dotenv()
os.environ["LANGCHAIN_TRACING_V2"] = "false"


# agents/react_agent.py
from langchain_openai import ChatOpenAI
from langchain.agents import create_react_agent, AgentExecutor
from langchain import hub
from tools import policy_lookup_tool, fraud_search_tool, amount_validator_tool
from pathlib import Path
import json


# Load data globally for fast access
try:
    POLICIES_DB = json.loads(Path("data/policies.json").read_text())
    FRAUD_PATTERNS = json.loads(Path("data/fraud_patterns.json").read_text())
except FileNotFoundError:
    POLICIES_DB = {}
    FRAUD_PATTERNS = []

llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.1,
    api_key=os.getenv("OPENAI_KEY")
)

tools = [policy_lookup_tool, fraud_search_tool, amount_validator_tool]

# ReAct prompt from LangChain Hub
base_prompt = hub.pull("hwchase17/react")

# CUSTOM INSURANCE PROMPT 
insurance_prompt = base_prompt.partial(
    system_message="""You are an expert insurance claims triage agent analyzing unstructured PDFs.

AVAILABLE TOOLS (call ONLY when relevant data exists):
1. policy_lookup_tool(policy_number) - Use when you see "POL-XXXXX" policy numbers
2. fraud_search_tool(description) - Use when accident/incident described (collision, whiplash, etc.)
3. amount_validator_tool(text) - Use when dollar amounts/claim values mentioned

AGENTIC WORKFLOW:
1. SCAN document for: policy #, incident description, claim amounts
2. REASON: "I see POL-12345 so I'll call policy_lookup_tool"
3. CALL tools dynamically based on content
4. SYNTHESIZE: Coverage + fraud risk + amount → final triage decision

DECISIONS: APPROVE / DENY / FLAG FOR REVIEW / APPROVE WITH MONITORING

EXAMPLE THOUGHT PROCESS:
"I notice 'POL-12345' → call policy_lookup_tool  
Document mentions 'rear-end collision' → call fraud_search_tool  
Found '$15,000 damage' → call amount_validator_tool  
Coverage valid but 67% fraud risk → APPROVE WITH MONITORING"

To call policy lookup for example:
    Action: policy_lookup_tool
    Action Input: POL-12345
    Use plain tool names WITHOUT backticks or quotes.

CRITICAL: Approve only when you are sure the policy is valid and there are no red flags

Think aloud step-by-step before calling tools."""
)

# Create ReAct agent (dynamically decides which tools to call)
agent = create_react_agent(llm, tools, insurance_prompt)

executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=True,  # Shows agent thoughts in console
    return_intermediate_steps=True,
    max_iterations=6,  
    handle_parsing_errors=True  
)

def get_agent_executor():
    return executor
