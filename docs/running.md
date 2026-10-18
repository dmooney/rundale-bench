# Running Benchmark 3.0

Install the package in editable mode with `python3 -m pip install -e .`. The fixed suite is validated with `rundale-bench validate-suite`; `rundale-bench status` prints candidate profiles and the qualification receipt status.

Before spending, preview the exact candidate settings and blockers:

```sh
rundale-bench run gpt-6.1-sol --dry-run
```

The default is the highest reasoning profile listed for the model. Pin an available setting with `--reasoning`. A launch is capped at $5, including required judgments. Paid execution requires a ready suite, a matching qualification receipt for its manifest hash, pinned dialogue and multiturn judges with passing automated screening (provisional) or human-reference qualification, engine capture, valid pricing, and credentials. A dry run checks these conditions without making network requests. A full-suite worst-case estimate above $5 is a warning: the runner still attempts the fixed suite, while per-call reservations can end it as budget DNF with completed evidence preserved. Supply credentials through the process environment or an explicit `--env-file`; values in that file take precedence. Files are read as dotenv-style key/value pairs and never sourced by the shell.

Dry runs exit nonzero when any validation error or launch blocker remains. Profiles marked unavailable (including deprecated models whose API aliases can change) are reported as unavailable rather than redirected to another model.

```sh
rundale-bench run gpt-6.1-sol --budget 5 --env-file .env.bench
rundale-bench run gpt-6.1-sol --reasoning high --resume RUN_ID --env-file .env.bench
```

Intermediate responses and the durable SQLite cost ledger are stored under `output/RUN_ID/`. Resuming reuses confirmed calls and refuses changed requests or unresolved billing. Completed and failed evidence is written to `results/3.0/runs/`; `rundale-bench publish` rebuilds the public index after importing reviewed run evidence. A second confirmed refusal or malformed response ends the run and writes a deduplicated-issue payload to the run directory. Unknown billing or infrastructure failures stop execution and preserve the raw diagnostic evidence.

Native judge calibration has a fixed $10 total cap and saves resumable evidence
under `output/qualification/`. The default launch path requires no human ratings:

```sh
rundale-bench qualify collect --env-file .env.bench
rundale-bench qualify screen
```

`screen` is offline, makes no paid calls, and reuses completed calibration. It
checks all 44 current results and retains superseded paid evidence and frozen controls, chooses the cheapest passing judge per
English eval, and publishes explicitly provisional screening evidence. It never
produces human accuracy labels. If collection is already complete, do not start
another collection directory to reset its cap.

Compare two published run IDs using paired primary-case scores (repeat trials do not affect the comparison):

```sh
rundale-bench compare RUN_ID_A RUN_ID_B
```

The run records retain prompts, responses, judgments, token usage, timings, costs, settings, coverage, and failure reasons. Do not publish credential values or private reviewer identifiers.

## Screening evidence and optional future feedback

The six controls are described in [judge bias diagnostics](judge-bias.md). The
exact controls are hashed into the collection contract; changed requests cannot
silently reuse paid evidence. Screening checks schema, invariant-axis agreement, and nonconstant original grades
within each English eval, while inter-judge agreement and verbosity effects remain diagnostics.
The resulting manifest and evidence hashes are frozen. Candidate runs retain
their own provisional status even if a later version gains human validation.

Human feedback is deferred. The blind form and `qualify evaluate --ratings PATH`
are retained for real future reference labels in a new benchmark version.
Version 3.0 refuses that evaluation once its provisional policy is pinned;
it cannot replace provisional evidence with pending or qualified status. Do not ask the owner to
complete the form as a launch prerequisite, fabricate references, or treat model
agreement as human validation. A new judge or scoring policy needs a new version.

## Publish a result

`rundale-bench publish` rebuilds the local index. From a clean checkout with only
`results/` changes, `rundale_bench.publication.publish_results_pr(root)` runs the
offline gates and opens a results PR. An agent then attaches that PR to its task,
waits for CI, and starts an independent gatekeeper. The gatekeeper decides whether
to merge; Pages deploys main. For a DNF, call
`rundale_bench.publication.file_failure_issue(root, run)` and verify its receipt.
Neither helper claims an unconfirmed external action succeeded.

An infrastructure DNF whose response has final usage is charged and cached;
resuming replays that failure instead of making another paid call. Diagnose the
issue before starting a new run. An interrupted or unmetered request retains its
reservation and blocks further paid work until billing is reconciled. Gemini
usage without an explicit thinking-token count also remains uncertain rather
than assuming that count is zero.

For an explicitly approved pre-launch control or adapter correction, use
`qualify collect --amend-controls --env-file .env.bench`. It archives the prior
contract, preserves superseded paid responses, reuses every identical request
by its digest, and pays only for changed requests under the same ledger/cap.
Pack, rubric, split, and profile changes are refused. This does not amend a
published judge policy: an already published screening receipt stays frozen.
The 3.0 human evaluator is retained implementation for future adaptation; a
new benchmark version must explicitly add its paths and validation design.
