# Benchmark specification

Benchmark 3.1 is an agent-operated evaluation of models used in Rundale. It uses
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
`5c14ea236022aed698e478837a6c754657239ae7`. The 24 dialogue requests were exported through the production
`prepare_npc_conversation_turn` path at that revision and are frozen in
`suites/3.0/engine_capture.jsonl`. The manifest records the capture and source
hashes; engine capture is complete. A matching automated-screening receipt
permits a provisional launch. Full sessions, intent, simulation,
reactions, local models, and app delivery are deferred.

## Native structured output (3.1)

Owner decision, October 23, 2026: candidate JSON contracts must use native
schema-constrained generation. Production is still under development; this is
an explicit benchmark contract, not a claim of production-wire equivalence.
Version 3.1 is the CLI default. Version 3.0 remains frozen and can be selected
explicitly with `--version 3.0`; results from the two versions are not pooled.

Every 3.1 case pins a response schema in the hashed cases file. NPC responses
require dialogue, action, mood, language_hints (word/pronunciation/meaning
objects), and nullable assigned_task, with no extra fields. Property order puts
dialogue first and assigned_task last. Gaeilge choices use an `answer` object
field restricted to A or B; extraction tasks constrain requested keys and
string types. Schemas never contain the correct choice or expected fact values.

Google requests use `responseMimeType: application/json` and `responseJsonSchema`
(the JSON Schema field rather than the older OpenAPI `responseSchema` field).
The adapter uses this field for any Google schema request, including a future
Google judge request; no current pinned judge uses Google.
OpenAI uses strict Responses JSON Schema; Anthropic uses native JSON Schema
output configuration. Anthropic candidate schemas are unit-tested only; the live
3.1 evidence covers Google and OpenAI. Unsupported candidate providers are blocked. See
[Google's native structured-output documentation](https://ai.google.dev/gemini-api/docs/generate-content/structured-output).
Schema validation still runs locally. No Markdown-fence removal, JSON repair,
semantic answer normalization, or automatic retries are introduced.

The same primary scenarios, source examples, engine capture, repeats, rubrics,
objective answer keys, judge profiles, scoring and stop rule are retained.
The 16 Gaeilge A/B choice prompts replace “Reply A or B only.” with
“Reply with exactly one JSON object: {"answer":"A"} or {"answer":"B"}.”
All remaining choice-prompt text is unchanged. This is an explicit change to
candidate instructions as well as native decoding, so 3.0 and 3.1 results must
not be pooled. The eight JSON extraction prompts are unchanged. Gaeilge exact-string answers
remain a narrow canonical-extraction measure; semantically equivalent wording
can still score zero. Changing that policy is separate work. Schema shape does
not establish correctness, Irish fluency, or production quality.

3.1 reuses the original automated judge screening: its judge requests, anchors,
profiles and calibration inputs are unchanged. The receipt records the source
suite and receipt hashes, retains original screening dates and limitations,
and includes byte-identical screening artifacts. This is no new qualification
or human validation, and makes no new paid calibration calls. Changed judge
profiles or rubrics still block execution. Candidate request evidence and the
resume digest include the full schema and output protocol; reservations account
for schema input. Old paid responses cannot silently satisfy a changed request.

## Judge screening and validation

Owner decision, October 18, 2026: manual review is not a launch requirement.
Publish a provisional leaderboard using automated judge screening, without a
claim of human validation. Human feedback through MTurk or another service may
be considered later; recruitment and spending on it are deferred.

Native GPT-6.1 Sol at high reasoning and Jev 1.13.0 each score the frozen 16
English calibration cases and six controlled variants. The earlier 8/8 split
is retained for provenance; it no longer supplies a human validation holdout.
All published calibration examples are exposed development evidence.

For each English evaluation, require complete integer grades on exactly its
rubric axes, at least 90% unchanged axes on the invariant controls, and at least
two distinct original axis grades within each eval. Reject constant grading as
a pre-launch development heuristic. This was added after inspecting the exposed
calibration data; it is not independent validation and may reject legitimately
uniform grades. Exclude
the duplicated-response diagnostic from this invariance gate. Among passing
judges, pin the one with the lower measured total calibration cost (profile ID
breaks a tie). This chooses a low-cost judge passing these narrow checks; it does not
establish accuracy, score sensitivity, or ranking quality. Publish controls, per-axis changes, costs, and inter-judge
agreement, per-judge grade distributions, and ceiling fractions. Many calibration
axes are already at grade 5; a constant high grader can pass invariance alone, and
upward label preference cannot be observed on a ceiling axis. Recompute these diagnostics from raw grades; agreement between
judges is not a reference answer and does not establish correctness.

The receipt and every run must retain `provisional` status and
`automated_checks_only` validation basis. Human agreement, accuracy, MAE against
human ratings, and severe human-reference misses remain unmeasured. No synthetic
or model-generated rating becomes a human reference. Failing automated checks
still blocks paid execution; pending evidence is not a bypass flag.

Optional future human validation can use the retained blind review workflow
in a new benchmark version. Version 3.0 rejects human evaluation once its
provisional policy is pinned, preserving both successful and failed evidence.
References must be real, match the frozen pack/rubric, and contain no invented
labels. The original human-reference gates (MAE <=0.75, no 1–2 reference rated
4–5, selection then separate validation) remain available for that workflow in a new benchmark version;
they are project thresholds, not industry guarantees. Future feedback collection
needs its own sampling and adjudication design. Do not retroactively relabel old
provisional runs as human validated. Changing a pinned judge or scoring policy
requires a new benchmark version.

Benchmark 3.2 is a separate draft policy for one native Anthropic Claude Opus
5.5 judge at high effort on both English evaluations. Anthropic models are
reserved for judging and are excluded as 3.2 candidate models. This policy is
not launch-ready until Opus calibration has been collected and passes the
versioned automated screen; no 3.0 or 3.1 evidence is reused as Opus evidence.
The first calibration attempt stopped at provider authentication before any
judgment was collected. See `qualification/3.2/calibration-attempt.json` and the pre-attempt per-file source hashes under `docs/evidence/opus-judge/`. Correct the credential before another calibration attempt.

Gaeilge scores use attributed objective answer keys. Expanded Irish-BLiMP
qualification remains pending dataset access; Irish naturalness/style remains
unqualified and excluded from ranking.

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

A provider-reported output token limit is a configured-resource stop for both
candidate and judge calls. It ends the run as a setup DNF, does not count as a
confirmed model refusal/malformed-output event, and retains an earlier result.
Preserve any known final usage cost; an interrupted stream's prior usage is
not final and must remain billing-uncertain. Do not grade truncated text, change
the token limit, or retry automatically. The same policy applies to native
OpenAI, Google, and Anthropic termination signals.

Budget status describes the ledger independently of failure attribution. A run
with an unknown failure but no outstanding reservation remains `within_cap`;
only unresolved reserved exposure makes its billing uncertain.

## Publication

The public repository is [`dmooney/rundale-bench`](https://github.com/dmooney/rundale-bench)
and the results site is [rundale-bench on GitHub Pages](https://dmooney.github.io/rundale-bench/).
Version 3.0 starts empty; earlier results remain in the archive. Publish complete
raw requests, responses, judgments, coverage, settings, actual or estimated cost,
timing, and any DNF reason. Do not publish generated strength summaries. Preserve
immutable history and choose the displayed latest run using failure precedence.

A later provider-monitoring billing reconciliation is a separate dated,
hash-bound artifact. Preserve the original run and ledger, unknown attribution,
and reserved exposure. Display any monitoring estimate with its evidence and
identity limitations; it is not invoice-backed actual cost or permission for
further paid work.

Scores require complete primary coverage and matching pinned judge-screening
evidence. Provisional rankings are permitted, prominently labeled as automated
and not human validated, including each historical run. Keep versions in
separate tables. Report showcase-level paired bootstrap intervals and Wilson
intervals for accuracy, with small sample sizes made clear. Future human ratings would be references for product preferences, not population consensus. Once public,
validation data are no longer untouched holdouts.

## Completion

A provisional launch requires passing automated screening with its limitations
published, mandatory reference-backed Gaeilge, one complete actual run, a second
result or an honestly reported DNF, verified live evidence, a fresh independent
agent workflow, and total spend no greater than $20. Human feedback is deferred;
it is not a launch blocker. Do not claim human qualification or completion of
any remaining required gate.
