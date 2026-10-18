# Benchmark 3.0 specification

Benchmark 3.0 is an agent-operated evaluation of models used in Rundale. It uses
native provider APIs and reports three equally weighted evaluations: dialogue,
multi-turn play, and Gaeilge. Each evaluation is scored from 0 to 100. The overall
score is a product-specific composite, not a measure of general intelligence.

Dialogue and multi-turn scores use fixed, anchored dimensions rated from 1 to 5.
The dimensions and primary cases receive equal weight, and the mean rating is
converted to a 0–100 score with `25 × (rating − 1)`. Repeated trials estimate
variability; they do not change the weight of primary cases. Gaeilge equally
weights source-backed grammar, meaning, and code-switch compliance. Its judgments
are objective checks against published Irish examples and glosses, paired with
authored English facts where needed. Irish naturalness and style judgments are
provisional diagnostics and never affect rankings. The benchmark makes no claim
that a fluent Irish reviewer is available or that the system measures fluency.

The initial fixed suite contains 24 dialogue cases, 8 six-turn conversations, and
24 Gaeilge cases (8 in each Gaeilge subcategory). It includes 6 dialogue, 2
conversation, and 4 Gaeilge repeat trials. The engine revision is pinned to
`5c14ea236022aed698e478837a6c754657239ae7`. Existing prompt snapshots do not prove
that they were captured from this revision. Until an engine capture is verified,
the suite remains blocked from a launch claim. Full sessions, intent, simulation,
reactions, local models, and app delivery are deferred.

## Judge qualification

English judge qualification uses 16 blind cases in total, split
deterministically into 8 selection cases and 8 validation cases, with four
cases per evaluation in each split. The
owner supplies reference ratings. Synthetic pilot ratings can help develop the
process but are not qualification evidence. Freeze the suite and rubric before
collecting the owner's ratings. The initial candidates are native API GPT-6.1 Sol
at high reasoning and Jev 1.13.0. Codex subagent results do not establish native API
cost or qualification.

The initial acceptance gates are mean absolute error (MAE) no greater than 0.75,
no owner rating of 1–2 judged as 4–5, and at least 90% of axes unchanged on
controlled repeats. These are project startup choices, not industry standards.
Choose the candidate with lower MAE; a difference under 0.1 is a tie, broken by
measured cost. Each evaluation must pass its own validation split.
Unknown or null reference axes stay unlabelled, and too little usable validation
means qualification remains pending. Confidence intervals and judge agreement do
not replace accuracy against the owner's references. Gaeilge objective scores use attributed published answer keys. An expanded
Irish-BLiMP diagnostic qualification corpus remains pending dataset access; it
does not qualify an Irish style judge. Synthetic Irish labels are never gold. Any judge change requires a new
suite version.

## Execution and cost

Use native provider APIs only. Unless the user pins another supported setting,
select the candidate's highest supported reasoning level and record the exact
settings. An explicitly selected setting is a distinct result row. Every model
uses the same fixed comprehensive suite.

A normal run may spend at most $5, including judge calls. Qualification and launch
have a one-time combined cap of $20: up to $10 for qualification and two launch
runs capped at $5 each. CI must never make paid calls. Before each request, reserve
a conservative estimate for input and maximum output/reasoning cost; also reserve
enough to judge completed work. Reconcile against actual usage, including cached
tokens, and do not charge reasoning tokens twice when they are already included in
output usage. Unknown prices or uncertain billing stop further requests; never
record invented zero costs. A resumed run reuses confirmed completed calls. Do not
silently reduce the sample or launch automatic repair campaigns.

The second rejection or malformed-output event in one run ends it as a DNF and
creates a deduplicated issue payload. An API refusal is distinct from an
appropriate in-character refusal. A confirmed candidate-model failure scores
zero. Unknown or tooling causes cannot produce a complete ranking. A budget DNF
does not indicate poor model quality. A confirmed model DNF replaces that model's
score; infrastructure, budget, or unknown failures retain the previous result
with a dated incomplete-attempt notice.

## Publication

The public repository is [`dmooney/rundale-bench`](https://github.com/dmooney/rundale-bench)
and the results site is [rundale-bench on GitHub Pages](https://dmooney.github.io/rundale-bench/).
Version 3.0 starts empty; earlier results remain in the archive. Publish complete
raw requests, responses, judgments, coverage, settings, actual or estimated cost,
timing, and any DNF reason. Do not publish generated strength summaries. Preserve
immutable history and choose the displayed latest run using failure precedence.

Scores require complete primary coverage and qualified judges. Raw or provisional
grades may be shown, but must not appear as qualified rankings. Keep versions in
separate tables. Report showcase-level paired bootstrap intervals and Wilson
intervals for accuracy, with small sample sizes made clear. Owner ratings are
references for product preferences, not population consensus. Once public,
validation data are no longer untouched holdouts.

## Completion

Code, site, and readiness work may finish before owner ratings are available. A
full launch additionally requires qualified English judges, mandatory
reference-backed Gaeilge, one complete actual run, a second result or an honestly
reported DNF, verified live evidence, a fresh independent agent workflow, and
total spend no greater than $20. Do not claim completion while any required gate
remains unmet.
