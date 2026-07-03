"""Legacy text-format ReAct agent.

Kept for comparison with the tool-calling agent (enable with USE_LEGACY_REACT_AGENT=true).
The text-based Thought/Action/Observation format is inherently fragile; the new
default lives in agents/triage_agent.py.
"""

from __future__ import annotations

from functools import lru_cache

from langchain.agents import AgentExecutor, create_react_agent
from langchain.prompts import PromptTemplate

from agents.extraction import extract_fields
from agents.llm import get_chat_model
from agents.schemas import TraceStep, TriageOutcome
from agents.triage_agent import _fallback_result
from config import get_settings
from tools import (
    amount_validator_tool,
    claims_history_tool,
    fraud_search_tool,
    policy_lookup_tool,
)

TOOLS = [policy_lookup_tool, fraud_search_tool, amount_validator_tool, claims_history_tool]

PROMPT = PromptTemplate.from_template("""You are an expert insurance claims triage agent.

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
Final Answer: APPROVE / DENY / FLAG FOR REVIEW / APPROVE WITH MONITORING / NEEDS INFO, followed by your reasoning.

WORKFLOW: extract the policy number (POL-XXXXX) and look it up; check the incident
description for fraud; review claims history; validate amounts. Only call tools when
the relevant data exists. If the document is not an insurance claim, call no tools and
answer DENY. If the policy number is missing or cannot be verified, answer NEEDS INFO.

CRITICAL: Always end with 'Final Answer:'. Never use 'Action: None'.

Begin!

Question: {input}
Thought: {agent_scratchpad}""")


@lru_cache
def get_agent_executor() -> AgentExecutor:
    settings = get_settings()
    agent = create_react_agent(get_chat_model(), TOOLS, PROMPT)
    return AgentExecutor(
        agent=agent,
        tools=TOOLS,
        verbose=False,
        return_intermediate_steps=True,
        max_iterations=settings.max_agent_iterations,
        handle_parsing_errors=(
            "Invalid format. You must either call a tool using:\n"
            "Action: <tool_name>\nAction Input: <input>\n\n"
            "OR conclude with:\nThought: I have enough information.\n"
            "Final Answer: <your decision>"
        ),
    )


def run_legacy_triage(document_text: str, confirmed_fields: dict | None = None) -> TriageOutcome:
    """Run the legacy agent and adapt its free-text output to the structured schema."""
    extracted = extract_fields(document_text)
    confirmed_block = ""
    if confirmed_fields:
        confirmed_block = "\nUSER-CONFIRMED FIELDS (authoritative):\n" + "\n".join(
            f"- {k}: {v}" for k, v in confirmed_fields.items()
        )
    settings = get_settings()
    result = get_agent_executor().invoke(
        {"input": f"INSURANCE CLAIM DOCUMENT:\n{document_text[:settings.max_document_chars]}\n{confirmed_block}"}
    )
    trace = [
        TraceStep(
            thought=getattr(action, "log", ""),
            tool=getattr(action, "tool", None),
            tool_input={"input": str(getattr(action, "tool_input", ""))},
            observation=str(observation),
        )
        for action, observation in result.get("intermediate_steps", [])
    ]
    return TriageOutcome(
        result=_fallback_result(result.get("output", "")),
        extracted=extracted,
        trace=trace,
    )
