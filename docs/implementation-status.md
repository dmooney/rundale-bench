# Launch status

Structured-output update (October 23–24): 3.1 pins native candidate schemas and
is the CLI default. It preserves 3.0 history and reuses the unchanged automated
judge evidence without new paid calibration calls. A
[four-call Google smoke test](evidence/structured-output/README.md) passed native
schema acceptance and local shape checks for $0.0112745. One extraction still
failed the exact-string answer key.

Both full 3.1 runs completed all 68 trials with zero recorded failures. Each
contains 118 schema-valid candidate responses and 40 completed judge calls:

| Model / reasoning | Dialogue | Multi-turn | Gaeilge | Overall | Usage-priced cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| Gemini 3.5 Flash-Lite / high | 95.14 | 52.08 | 83.33 | 76.85 | $0.611842924 |
| GPT-6.1 Sol / max | 96.01 | 89.58 | 91.67 | 92.42 | $1.321573274 |

Run IDs are `gemini35-structured-20261023` and `sol61-structured-20261024`.
All 316 calls are committed in their local ledgers, with no outstanding exposure.
Costs are provider usage priced at pinned rates, not invoice receipts. Scores
are provisional automated measurements, not human validation or Irish fluency.
Sol is also the pinned multi-turn judge at high reasoning; model-family
self-judging is a limitation of this comparison.

Gemini's three code-switch extraction misses and Sol's two preserve the tested
facts but differ from canonical English strings. These remain zero under the
unchanged exact-match rule. The multi-turn scripts combine recall with
closed-world NPC restrictions, so their composite does not isolate general
memory. These limitations are not repaired or rescored in 3.1.

The 3.1 result index links both raw runs for publication through the Pages workflow.
See the [implementation provenance audit](evidence/structured-output/provenance.md)
for the uncommitted revisions used to produce them and the offline replay check. Two small-suite
runs do not establish broad model reliability.

## Archived 3.0 launch record

The implementation supports a provisional launch without manual owner ratings.
On October 18, 2026, the owner deferred human feedback (possibly MTurk or similar)
until after the system is operating. No recruitment or human-label spending is
currently required or authorized.

Native calibration completed: 22 current judgments each from Sol high and Jev,
plus three retained superseded controls, 47 paid calls, $0.315422 from usage at recorded prices (not an invoice receipt).
Automated screening selected Jev for dialogue and Sol high for multi-turn.
Jev matched all 12 dialogue invariant axes; Sol matched all nine multi-turn
axes. Sol dialogue matched 10/12, below the 90% gate. Jev multi-turn was
constant at grade 5 on all 24 original axes, so the development heuristic
rejects it despite its 9/9 invariant match. The 16 examples and six controls are tiny exposed development
samples; consistency and inter-judge agreement do not establish accuracy.
Jev assigned 5 on 64 of 72 original case axes. Grade histograms and control
ceiling counts are published: this concentration can make invariance appear
strong even for an insensitive judge. The injection control now requests 1
on a case previously graded 5; its original ineffective all-5 request is retained
as superseded evidence.
`qualification/3.0/` contains the complete provisional screening evidence.

Scores and run records are explicitly provisional. Human agreement, accuracy,
MAE against human references, and severe human-reference misses are unmeasured.
The latest Gemini 3.5 Flash-Lite high attempt (`4b4f0c1824d6`) reached 67 of
68 trials. Dialogue scored 94.27/100 across 24/24 cases; multi-turn scored
41.67/100 across 8/8 scored cases, including a confirmed malformed-output
failure scored zero. Gaeilge covered 23/24 cases and has no complete score.
The second malformed response ended the run as a model-attributed DNF, so there
is no overall score and the complete-baseline gate remains open. Both failed
responses reported native `STOP`, rather than an output-token limit. All 156
calls have committed usage: $0.636991426 known usage-priced cost and spending
exposure under the $4.80 cap. These are provisional automated component scores,
not human-validated accuracy estimates. Investigation is tracked in
[#12](https://github.com/dmooney/rundale-bench/issues/12); no retry followed the DNF.

The previous attempt (`8bff4886b04a`) retains its 93.92 dialogue score,
unknown DNF attribution and $0.178445436 reserved exposure. Its missing-zero
thinking-token adapter diagnosis was fixed in
[#10](https://github.com/dmooney/rundale-bench/pull/10), without rewriting the
original run or settling its historical ledger.

The earlier run (`5e2177f168e2`) remains a separate unknown DNF. Its original
run record, ledger, and $0.0185515 uncertain exposure are preserved; the
separate provider-monitoring estimate does not reconcile or replace them.

Publication verification: 119 Python tests and eleven site tests pass, together
with the frozen dependency install, Astro checks, and static build. The engine
exporter produced 24 exact production-path prompt captures at the pinned engine
commit. Suite-building tests now use temporary directories and cannot reset a
ready manifest or erase its pinned judges.

Remaining launch gates:

- Independent review and deployment verification.
- One complete baseline and an additional result or honest DNF under the
  approved $20 setup allocation. The native attempts remain incomplete;
  Gemini 3.7 is disabled because Google routes its API name to 3.8, so do not
  silently substitute a different candidate.
- Working public raw-evidence/archive links and a fresh agent execution check.

Gaeilge is a small objective probe backed by eight published source examples;
it does not measure fluency. Expanded Irish-BLiMP data access and Irish style
judging remain unqualified diagnostics, separate from ranked scores.
