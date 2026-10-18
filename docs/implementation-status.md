# Launch status

The implementation contains native adapters, frozen engine captures and rubrics,
budget accounting, resume protection, objective Gaeilge checks, a blind owner
review, failure issue preparation/filing, immutable results, and a Pages site.
It does not contain new qualified model scores.

Offline verification: 61 Python tests pass; four dashboard tests, the site check, and build pass.
The engine exporter was built and run against the pinned engine commit, producing
24 exact request captures. Browser checks exercised review navigation and local
save/resume using explicitly labelled UI-only skipped ratings; those are not
reference scores.

Remaining launch gates:

- Owner ratings for the 16 English cases (eight dialogue, eight multi-turn).
- Native Sol-high/Jev collection and validation. Automatic approval review
  blocked sending the full calibration pack to both providers; explicit approval
  for that payload is pending. No paid calibration calls were made by this runner.
- One complete baseline and a second result or honest DNF under the approved
  $20 setup allocation. Gemini 3.7 is disabled because Google routes its API name
  to 3.8; do not silently substitute a different candidate.
- Independent review, deployment verification, and a fresh agent execution check.

Gaeilge coverage is a small published-example probe, not a fluency benchmark.
The larger manually gated Irish-BLiMP diagnostic subset and Irish style judging
remain unqualified. The 16-case English validation is also too small to support
population accuracy claims. Verbosity, model-family and broader domain biases
remain unmeasured; repeat agreement alone does not establish their absence.
