from langchain.tools import tool
import json
from pathlib import Path

# Load policies at module level (fast lookup)
POLICIES_DB = json.loads(Path("data/policies.json").read_text())

@tool
def policy_lookup_tool(policy_num: str) -> str:
    """Lookup policy details by policy number (e.g., POL-12345). 
    Use when document mentions a policy number."""
    policy = POLICIES_DB.get(policy_num)
    if policy:
        return (f"✅ Policy {policy_num} found: "
                f"{policy['coverage'].title()} coverage, "
                f"${policy['limit']:,} limit, "
                f"Status: {policy['status']}")
    return f"❌ Policy {policy_num} not found in database"
