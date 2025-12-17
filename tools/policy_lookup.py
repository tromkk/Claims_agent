from langchain.tools import tool
import json
from pathlib import Path

# Load policies at module level (fast lookup)
POLICIES_DB = json.loads(Path("data/policies.json").read_text())

'''
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
'''
'''
@tool
def policy_lookup_tool(policy_number: str) -> str:
    """Lookup policy details by policy number."""
    try:
        with open("data/policies.json", "r") as f:
            policies = json.load(f)
        
        if policy_number in policies:
            policy = policies[policy_number]
            return f"✅ Policy {policy_number} FOUND: {policy['coverage']} coverage, ${policy['limit']:,} limit, {policy['policyholder']}, {policy['vehicle']}, status: {policy['status']}"
        else:
            return f"❌ Policy {policy_number} NOT FOUND"
            
    except Exception as e:
        return f"❌ Policy lookup error: {str(e)}"
'''

@tool
def policy_lookup_tool(policy_number: str) -> str:
    """Lookup policy details by policy number."""
    try:
        # 🛡️ FIX: Clean input (remove quotes, whitespace, truncation)
        clean_policy = policy_number.strip().strip('"\'`')
        first_token = clean_policy.split()[0]
        clean_policy = first_token.replace('"', '').replace("'", "")

        print(f"🔍 DEBUG: Raw input: '{policy_number}' First token: '{first_token} → Cleaned: '{clean_policy}'")
        
        with open("data/policies.json", "r") as f:
            policies = json.load(f)
        
        print(f"🔍 DEBUG: Available keys: {list(policies.keys())}")
        
        if clean_policy in policies:
            policy = policies[clean_policy]
            return f"✅ Policy {clean_policy} FOUND: {policy['coverage']} coverage, ${policy['limit']:,} limit, {policy['policyholder']}, {policy['vehicle']}, status: {policy['status']}"
        else:
            return f"❌ Policy {clean_policy} NOT FOUND (keys: {list(policies.keys())})"
            
    except Exception as e:
        return f"❌ Policy lookup error: {str(e)}"


# print(policy_lookup_tool.invoke({"policy_number": "POL-123456789"}))