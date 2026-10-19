# Launch status

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
The first Gemini 3.5 Flash-Lite baseline attempt (`8bff4886b04a`) completed all
24 dialogue cases and scored 93.92 on dialogue. It completed no multi-turn or
Gaeilge cases (30 of 68 trials total), so it has no overall score and does not
meet the complete-baseline gate. The run ended with an unknown DNF because a
Google response omitted `thoughtsTokenCount`; billing remains uncertain in
the immutable run record. Subsequent diagnosis identified our adapter as the
cause: the final total exactly matched prompt plus candidate tokens, but the
adapter required an explicit zero thinking count. A narrowly checked accounting
fix was independently reviewed and merged in [#10](https://github.com/dmooney/rundale-bench/pull/10);
this diagnosis does not rewrite the original run or settle its ledger. The runner recorded $0.159474 of known usage and $0.178445 of total spending
exposure under its $4.98 cap. This is an automated provisional component score,
not an accuracy-validated or full benchmark result. Its deduplicated failure
issue is [#9](https://github.com/dmooney/rundale-bench/issues/9).

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
  approved $20 setup allocation. The first baseline attempt is incomplete;
  Gemini 3.7 is disabled because Google routes its API name to 3.8, so do not
  silently substitute a different candidate.
- Working public raw-evidence/archive links and a fresh agent execution check.

Gaeilge is a small objective probe backed by eight published source examples;
it does not measure fluency. Expanded Irish-BLiMP data access and Irish style
judging remain unqualified diagnostics, separate from ranked scores.
