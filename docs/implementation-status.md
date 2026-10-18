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
There are no new completed candidate scores yet. The baseline dry run is valid
and has no launch blockers.

Offline verification: 82 Python tests and six site tests pass. The engine
exporter produced 24 exact production-path prompt captures at the pinned engine
commit. Suite-building tests now use temporary directories and cannot reset a
ready manifest or erase its pinned judges.

Remaining launch gates:

- Independent review and deployment verification.
- One complete baseline and a second result or honest DNF under the approved
  $20 setup allocation. Gemini 3.7 is disabled because Google routes its API name
  to 3.8; do not silently substitute a different candidate.
- Working public raw-evidence/archive links and a fresh agent execution check.

Gaeilge is a small objective probe backed by eight published source examples;
it does not measure fluency. Expanded Irish-BLiMP data access and Irish style
judging remain unqualified diagnostics, separate from ranked scores.
