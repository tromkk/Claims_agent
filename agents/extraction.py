"""Deterministic-first field extraction.

Regexes handle the predictable fields (policy number, amounts, dates, labelled
names); an optional LLM pass fills only the gaps. Per-field confidence drives
the confirm-with-user flow in the UI.
"""

from __future__ import annotations

import logging
import re

from agents.schemas import ExtractedField, ExtractedFields

logger = logging.getLogger(__name__)

'''
Allows common OCR confusions inside the digits (O↔0, I/l↔1, S↔5, B↔8)
stray OCR punctuation (a period/comma) between the "POL" prefix and the digits.
The lookbehind lets "POL" follow a glued label ("Policy numberPOL-67890", which
is how some form layouts extract) while still refusing a match inside an all-caps run
'''

POLICY_RE = re.compile(r"(?<!(?-i:[A-Z0-9]))P[O0QD]L[\s\-–.,]*([0-9OIlSB]{5,9})\b", re.IGNORECASE)
CLEAN_POLICY_RE = re.compile(r"^POL-\d{5,9}$")

NAME_RE = re.compile(
    r"(?:name\s*&\s*surname|claimant(?:\s*name)?|insured(?:\s*name)?|policy\s*holder|full\s*name)"
    r"\s*[:\-]\s*(?P<value>[A-Za-z][A-Za-z .'\-]{2,60})",
    re.IGNORECASE,
)

DATE_RE = re.compile(
    r"(?:date\s*of\s*(?:incident|accident|loss)|incident\s*date|accident\s*date|loss\s*date)"
    r"\s*[:\-]\s*(?P<value>[0-9]{1,4}[/\-. ][0-9A-Za-z]{1,9}[/\-. ][0-9]{1,4})",
    re.IGNORECASE,
)

# The label that introduces a free-text incident description. The description
# itself may run over several lines, so it is captured by _extract_description
# (a line-by-line scan) rather than a single fixed-width pattern.
DESCRIPTION_LABEL_RE = re.compile(
    r"(?:damage\s*to\s*own\s*vehicle|description\s*of\s*(?:incident|loss|damage)"
    r"|incident\s*description|damage|what\s*happened)"
    r"\s*[:\-]\s*",
    re.IGNORECASE,
)

# A line that opens a *new* labelled field (e.g. "Repair estimate:", "Date -").
# Marks the end of a multi-line description so it doesn't swallow later fields.
NEXT_FIELD_LINE_RE = re.compile(r"^\s*[A-Za-z][A-Za-z /&'\-]{1,40}\s*[:\-]\s+\S")

# Longest description we keep; also caps how much free text reaches the LLM.
MAX_DESCRIPTION_CHARS = 600


def _snippet(text: str, start: int, end: int, pad: int = 45) -> str:
    return text[max(0, start - pad) : min(len(text), end + pad)].replace("\n", " ").strip()


def _extract_description(text: str) -> tuple[str, str] | None:
    """Capture a possibly multi-line incident description after its label.

    Scans from the label to the next blank line or labelled field, then collapses
    the block to a single line. Collapsing is deliberate: besides reading cleanly,
    it stops a malicious document from smuggling forged "Field:" lines (or prompt
    fence markers) into the prompt via embedded newlines. Returns (value, snippet).
    """
    m = DESCRIPTION_LABEL_RE.search(text)
    if not m:
        return None
    segments = text[m.end() :].split("\n")
    collected: list[str] = []
    consumed = 0  # chars of the post-label text we absorbed (for the snippet span)
    for i, seg in enumerate(segments):
        seg_len = len(seg) + (1 if i < len(segments) - 1 else 0)  # +1 for the '\n'
        stripped = seg.strip()
        if i == 0:
            # Remainder of the label's own line ("... incident: <here>").
            if stripped:
                collected.append(stripped)
            consumed += seg_len
            continue
        if not stripped or NEXT_FIELD_LINE_RE.match(seg):
            break
        collected.append(stripped)
        consumed += seg_len
    value = re.sub(r"\s+", " ", " ".join(collected)).strip()[:MAX_DESCRIPTION_CHARS]
    if len(value) < 10:
        return None
    return value, _snippet(text, m.start(), m.end() + consumed)


def regex_extract(text: str) -> ExtractedFields:
    fields = ExtractedFields()

    # Import here to avoid a tools<->agents import cycle at module load
    from tools.policy_lookup import normalize_policy_number

    matches = list(POLICY_RE.finditer(text))
    if matches:
        raw = matches[0].group(0)
        normalized = normalize_policy_number(raw)
        distinct = {normalize_policy_number(m.group(0)) for m in matches}
        if len(distinct) > 1:
            confidence = 0.5  # several different numbers on the page: ambiguous
        elif CLEAN_POLICY_RE.match(raw.upper().replace(" ", "")):
            confidence = 0.95
        else:
            confidence = 0.6  # needed OCR-style cleanup
        fields.policy_number = ExtractedField(
            value=normalized,
            confidence=confidence,
            source_snippet=_snippet(text, matches[0].start(), matches[0].end()),
        )

    if m := NAME_RE.search(text):
        fields.claimant_name = ExtractedField(
            value=m.group("value").strip(),
            confidence=0.75,
            source_snippet=_snippet(text, m.start(), m.end()),
        )

    if m := DATE_RE.search(text):
        fields.incident_date = ExtractedField(
            value=m.group("value").strip(),
            confidence=0.7,
            source_snippet=_snippet(text, m.start(), m.end()),
        )

    if desc := _extract_description(text):
        value, snippet = desc
        fields.incident_description = ExtractedField(
            value=value,
            # A clearly-labelled, substantial block is a confident capture and
            # need not force a confirm prompt; a terse one stays below the
            # confirm threshold so the UI double-checks it.
            confidence=0.8 if len(value) >= 25 else 0.6,
            source_snippet=snippet,
        )

    from tools.amount_validator import extract_amounts

    amounts = extract_amounts(text)
    if amounts:
        top = max(amounts, key=lambda a: a.value)
        fields.claim_amount = ExtractedField(
            value=f"{top.value:,.2f}",
            confidence=0.8 if top.dollar_prefixed else 0.55,
            source_snippet=top.snippet,
        )

    return fields


def llm_fill_gaps(text: str, fields: ExtractedFields, llm) -> ExtractedFields:
    """Ask the LLM only for fields regex could not find (or found with low confidence)."""
    missing = [
        name
        for name in ExtractedFields.model_fields
        if getattr(fields, name) is None or getattr(fields, name).confidence < 0.6
    ]
    if not missing or llm is None:
        return fields
    try:
        structured = llm.with_structured_output(ExtractedFields)
        prompt = (
            "Extract these fields from the insurance claim document below: "
            f"{', '.join(missing)}. For each, give the exact value, a confidence 0-1, "
            "and the short source snippet it came from. Leave a field null if absent.\n\n"
            f"DOCUMENT:\n{text[:4000]}"
        )
        llm_fields: ExtractedFields = structured.invoke(prompt)
        for name in missing:
            candidate = getattr(llm_fields, name)
            current = getattr(fields, name)
            if candidate and candidate.value and (
                current is None or candidate.confidence > current.confidence
            ):
                setattr(fields, name, candidate)
    except Exception as exc:  # noqa: BLE001 - extraction must never break the run
        logger.warning("LLM gap-fill extraction failed, using regex-only fields: %s", exc)
    return fields


def extract_fields(text: str, llm=None) -> ExtractedFields:
    fields = regex_extract(text)
    return llm_fill_gaps(text, fields, llm)
