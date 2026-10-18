---
name: rundale-bench
description: Run a budgeted Benchmark 3.0 model evaluation after automated judge screening and publish its raw evidence for independent review. Use when asked to test a model or run an evaluation in this repository.
---

# Test a model

For a request to “test MODEL”, use the fixed comprehensive suite and default to
the model's highest supported native API reasoning setting. Honor a user-pinned
setting when it is supported. Read `AGENTS.md`, `docs/specification.md`,
`docs/running.md`, and the current CLI and publication implementations in
`src/rundale_bench/cli.py`, `runner.py`, `storage.py`, and `publication.py` before
acting. Follow their current interfaces; do not invent commands.

1. Check `rundale-bench status` and inspect the profile/settings, suite hash,
   pricing, credentials availability, and qualification blockers. Never make a
   paid call in CI.
2. Run `rundale-bench run MODEL --dry-run` (and include `--reasoning SETTING` if
   the user selected one). This must be valid and have no blockers before paid
   execution. Missing judge screening, a draft suite, or pending engine capture is a stop
   condition. A matching provisional receipt permits execution and provisional
   publication; preserve its label and never claim human validation.
3. If calibration is requested, use `rundale-bench qualify collect` and then
   `rundale-bench qualify screen`. Collection makes native API calls under a
   durable $10 cap; screen is offline and needs no human ratings. Reuse completed
   paid calls. Do not fabricate references or ask the owner for manual review.
   Human feedback is deferred; the optional `qualify evaluate --ratings PATH`
   workflow is only for actual future human references.
4. Once the dry run is clear, run the actual model evaluation with at most $5,
   including judge calls. Use the CLI's existing `run` options and resumable run
   ID. Inspect the local raw run record and its request, response, judgment,
   usage, cost, coverage, and failure evidence in `output/` and
   `results/3.0/runs/`.
5. For a DNF, inspect its recorded failure cause and local `issue.json`. The
   supported publication API is `publication.file_failure_issue(root, run)`;
   use it only for the recorded DNF and verify whether the issue was filed,
   already existed, or could not be confirmed. Do not report an unconfirmed
   issue as filed.
6. Prepare the public immutable result data, then use the current reviewed
   publication path in `publication.py` to create a results PR. Do not merge it
   yourself. Start a fresh-context gatekeeper to review that PR using the
   repository's gatekeeper workflow; report the PR and wait for its outcome.

Report the model and exact settings, status and coverage, raw evidence location,
actual or estimated cost, qualification state, and any DNF or publication
blocker. Do not imply an Irish fluency result: Gaeilge scoring uses source-backed
objective grammar, meaning, and code-switch checks, while naturalness/style
judgments are provisional and excluded from ranking.
