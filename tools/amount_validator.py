from langchain.tools import tool
import re

@tool
def amount_validator_tool(text: str) -> str:
    """Extract and validate claim amounts. Flag high-value claims."""
    # Extract dollar amounts
    amounts = re.findall(r'\$?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)', text)
    amounts = [float(a.replace(',', '')) for a in amounts if a.replace(',', '').isdigit()]
    
    if not amounts:
        return "No claim amounts found"
    
    max_amount = max(amounts)
    if max_amount > 10000:
        return f"🚨 HIGH VALUE CLAIM: ${max_amount:,.0f} (>$10k threshold)"
    return f"Claim amount: ${max_amount:,.0f} (normal)"
