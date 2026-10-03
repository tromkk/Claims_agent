# Insurance claims agent eval

A self-contained evaluation of the agent against a set of labeled
scenarios (in `db/seed.py`), run across a few Groq models so we can
say which one triages best, with attached uncertainty.


```
eval/
  scenarios.py        labeled claim scenarios and their expected outcomes
  fixtures.py         the preconditions each label depends on, plus a check they hold
  run_eval.py         resumable, multi-model runner; writes results/runs.jsonl
  metrics.py          the scoring maths, imported by both the CLI and the notebooks
  report.py           text summary, confusion matrix, per-scenario grid
  analysis*.ipynb     the plots and the metric/technique write-ups
  results/            the rendered report card
```

## What it measures

This runs on seeded data, so it shows the measurement loop works. It can't show
that any model matches a real adjuster. That would take real-world data.

The primary metric is decision accuracy with a Wilson 95% confidence interval. It
uses Wilson rather than a normal approximation because n per model is only in the
tens to low hundreds, where a plain proportion CI gets too optimistic. Stability
tracks how repeatable a decision is across repeated runs of the same scenario.
It's measured at the run temperature, so it depends on temperature and isn't a
fixed property of the model.

Two numbers matter more than raw accuracy here. Guardrail violations (approvals
with no policy verified in the trace) should be zero, and any nonzero count is a
bug in the agent's safety check rather than sampling noise. False-approval rate
is the expensive, one-sided error a claims org cares about: an approval where no
approval was ever acceptable. Raw accuracy hides it inside a decent-looking
aggregate.

Structural checks cover the behaviors that shouldn't need statistics to verify.
Non-claim documents call zero tools, missing or unverifiable policies come back
as `NEEDS_INFO` with the field named, fraud and near-limit and name-mismatch
cases raise a red flag, and the OCR-garbled policy number `P0L-S3276` recovers to
`POL-53276`. Cost and latency come from captured token usage per call, which is
the number that decides which model ships. Completion rate counts errored cells
instead of dropping them, so a flaky model can't look good just because its
failures never made it into the average.

### Known limitations

The scenario set is small, about a dozen cases with one document each, so the
Wilson intervals are wide. Treat any model difference that falls inside
overlapping CIs as unproven. The cheapest way to narrow them is more documents
per scenario type.

The gold labels are limited and not truly random, so read this as an internal
consistency check on the agent rather than an external benchmark.

Cost figures are list-price estimates recomputed from stored token counts, so
updating the rate table re-prices old runs without re-running them.

## How it's run

Each cell calls a real LLM, so a full sweep is many hundreds of Groq calls and
will hit free-tier rate limits well before it finishes. The runner is
append-only and resumable: every completed `(model, scenario, run)` is one line
in `results/runs.jsonl`, a fresh start skips the cells already done, and a rate
limit or Ctrl-C stops it cleanly with progress saved. So the workflow is to run
it, let it stop, and run the same command again once the limit resets.

Because sweeps stop and resume, one sweep routinely spans several commits, none
of which changed agent behavior. Each session records the git SHA, models,
temperature and scenario-set hash alongside the runs, so it's traceable after
the fact.

## Reading the results

`report.py` prints the summary tables, confusion matrices and per-scenario grid,
and can dump the aggregates as JSON. The three notebooks answer different
questions.

`analysis.ipynb` describes what happened: accuracy-with-CI bars, cost-vs-accuracy
scatter, per-model confusion heatmaps, latency box plots, and the per-scenario
decision grid. Several cells compare models against each other, so they only get
interesting once more than one model has been swept.

`analysis-metrics.ipynb` argues about the scoring. It starts from accuracy, shows
that accuracy weights a wrong approval and a wrong flag equally when their costs
differ by orders of magnitude, moves to precision on the approve decision, then
to expected loss in money, and ends on how many runs it would take to bound the
expensive error rate tightly enough to ship.

`analysis-agent-eval.ipynb` applies techniques the other two skip: pass^k instead
of mean accuracy, cluster-bootstrap intervals that treat the 60 runs as 12
correlated scenarios rather than 60 independent draws, scoring of the recorded
tool-call traces, a label-free self-contradiction check, and an audit of whether
the gold labels are still true.

All three import `eval.metrics`, so no notebook can disagree with the CLI on a
shared number.

## A drift bug that motivated the fixture checks

`db/seed.py` used to set policy dates relative to `date.today()` while
`eval/scenarios.py` hardcodes incident dates as absolute strings. The calendar
moved one and not the other, so eventually a policy started after the incident
it was meant to cover. Nothing raised. The scenario kept running and graded the
wrong thing, scoring a correct `DENY` as wrong four times out of five. The
fixture audit in `analysis-agent-eval.ipynb` is what caught it, and correcting
the arithmetic moved that sweep's headline from 90% to 95%.

The fix pins the dataset to a fixed reference date and measures the time-based
fraud signals from the incident date instead of the wall clock. It also adds
`eval/fixtures.py`, which checks every label's preconditions against the seeded
data before a sweep spends anything on API calls, so a stale label stops the run
instead of quietly mis-scoring it. The same drift had also disarmed a fraud flag
in the demo app, which is why the check covers the sample PDFs too.
