# Claims Agent

**Agentic pre-screening for insurance claims.** 
Upload a claim document and the agent reads it,
checks the details against company records, looks for fraud signals, and recommends a
decision, with a full reasoning trail attached. When it is not sure, it stops and asks you
for clarification instead of guessing. The final call is always yours.

**[Try the live demo](https://claims-agent.streamlit.app/)**

![The triage console: title, what the agent does, and the You/Agent flow](imgs/triage-hero.png)

---

### The problem

Insurance carriers take in thousands of new claims a day, and the first pass over them is
still often manual. The documents are messy: digital forms, scans of hand-filled paper,
emails, loose free text. They are often incomplete, and the important details are buried in
unstructured prose. Rule-based automation cracks under that variability, so the tedious job
of reading, cross-checking, and sorting lands on people.

### What this does

This app slots an LLM agent in front of that first pass. Rather than following a rigid
script, it reasons about each claim and reaches for a verification tool only when the data
it needs is actually there, then returns a structured recommendation you can act on. It is
built to assist an adjuster, not replace them: the output is a fast, well-evidenced starting
point, and every run leaves a trail you can inspect.

Two design choices toward trustworthiness:

- **It finds the limits of what it read.** A missing policy number, an OCR-mangled scan, an
  ambiguous name: none of these earn a confident guess. The agent returns `NEEDS_INFO`, the
  UI asks you to confirm or fill the gap, and the run resumes with your input treated as
  authoritative.
- **It doesn't approve what it never verified.** Deterministic guardrails wrap the model, so
  a claim whose policy was never matched in the database can never come back APPROVE. The
  model recommends; the rules keep it honest.

