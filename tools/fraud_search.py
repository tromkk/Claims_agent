from langchain.tools import tool
import json
from pathlib import Path

# Load fraud patterns
FRAUD_PATTERNS = json.loads(Path("data/fraud_patterns.json").read_text())

@tool
def fraud_search_tool(description: str) -> str:
    """Check incident description against known fraud patterns.
    Use when document describes accident/claim details."""
    matches = []
    desc_lower = description.lower()
    
    for pattern in FRAUD_PATTERNS:
        if any(word in desc_lower for word in pattern['text'].lower().split(' + ')):
            matches.append(pattern)
    
    if matches:
        avg_fraud = sum(p['fraud_rate'] for p in matches) / len(matches)
        return (f"⚠️ {len(matches)} fraud patterns matched\n"
                f"Risk level: {max(p['risk_level'] for p in matches).upper()}\n"
                f"Avg fraud rate: {avg_fraud:.0%}")
    return "✅ No known fraud patterns detected"
