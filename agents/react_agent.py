import os
from dotenv import load_dotenv
load_dotenv()
os.environ["LANGCHAIN_TRACING_V2"] = "false"


# from langchain_openai import ChatOpenAI
from langchain_groq import ChatGroq
from langchain.agents import create_react_agent, AgentExecutor
from langchain.prompts import PromptTemplate
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

llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0.1,
    api_key=os.getenv("GROQ_API_KEY")
)

tools = [policy_lookup_tool, fraud_search_tool, amount_validator_tool]

# ReAct prompt
base_prompt = PromptTemplate.from_template("""You are an expert insurance claims triage agent.

{system_message}

You have access to these tools:
{tools}

Use this EXACT format for every response:

Question: the input question you must answer
Thought: your reasoning about what to do next
Action: the tool to use, must be one of [{tool_names}]
Action Input: the input to the tool
Observation: the result of the tool
... (repeat Thought/Action/Action Input/Observation as needed)
Thought: I now have enough information to make a final decision.
Final Answer: APPROVE / DENY / FLAG FOR REVIEW / APPROVE WITH MONITORING — followed by your reasoning.

CRITICAL: Always end with 'Final Answer:'. Never use 'Action: None'.

Begin!

Question: {input}
Thought: {agent_scratchpad}""")

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

CRITICAL: Approve only when you are sure the policy exists, is valid and there are no red flags

"""
)

# Create ReAct agent (dynamically decides which tools to call)
agent = create_react_agent(llm, tools, insurance_prompt)

executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=True,  # Shows agent thoughts in console
    return_intermediate_steps=True,
    max_iterations=6,  
    handle_parsing_errors=(
        "Invalid format. You must either call a tool using:\n"
        "Action: <tool_name>\nAction Input: <input>\n\n"
        "OR conclude with:\n"
        "Thought: I have enough information.\n"
        "Final Answer: <your decision>"
    )  
)

def get_agent_executor():
    return executor
