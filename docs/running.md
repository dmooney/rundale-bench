# Running Benchmark 3.0

Install the package in editable mode with `python3 -m pip install -e .`. The fixed suite is validated with `rundale-bench validate-suite`; `rundale-bench status` prints candidate profiles and the qualification receipt status.

Before spending, preview the exact candidate settings and blockers:

```sh
rundale-bench run gpt-6.1-sol --dry-run
```

The default is the highest reasoning profile listed for the model. Pin an available setting with `--reasoning`. A launch is capped at $5, including required judgments. Paid execution requires a ready suite, a matching qualification receipt for its manifest hash, qualified and pinned dialogue and multiturn judges, engine capture, valid pricing, and credentials. A dry run checks these conditions without making network requests. Supply credentials through the process environment or an explicit `--env-file`; values in that file take precedence. Files are read as dotenv-style key/value pairs and never sourced by the shell.

Dry runs exit nonzero when any validation error or launch blocker remains. Profiles marked unavailable (including deprecated models whose API aliases can change) are reported as unavailable rather than redirected to another model.

```sh
rundale-bench run gpt-6.1-sol --budget 5 --env-file .env.bench
rundale-bench run gpt-6.1-sol --reasoning high --resume RUN_ID --env-file .env.bench
```

Intermediate responses and the durable SQLite cost ledger are stored under `output/RUN_ID/`. Resuming reuses confirmed calls and refuses changed requests or unresolved billing. Completed and failed evidence is written to `results/3.0/runs/`; `rundale-bench publish` rebuilds the public index after importing reviewed run evidence. A second confirmed refusal or malformed response ends the run and writes a deduplicated-issue payload to the run directory. Unknown billing or infrastructure failures stop execution and preserve the raw diagnostic evidence.

English judge qualification is a separate native API workflow with a fixed $10 cap. It saves private judgments under `output/qualification/`; the owner's frozen ratings file is supplied only to offline evaluation:

```sh
rundale-bench qualify collect --env-file .env.bench
rundale-bench qualify evaluate --ratings owner-ratings.json
```

Compare two published run IDs using paired primary-case scores (repeat trials do not affect the comparison):

```sh
rundale-bench compare RUN_ID_A RUN_ID_B
```

The run records retain prompts, responses, judgments, token usage, timings, costs, settings, coverage, and failure reasons. Do not publish credential values or private reviewer identifiers.

## Calibrate the English judges

Open the site's [blind review form](https://dmooney.github.io/rundale-bench/review/index.html)
and grade the 16 English cases. No Irish reviewer is required for this track.
Save the exported JSON locally; do not commit reviewer identifiers. A skipped
axis remains unlabelled and cannot qualify a judge.

```sh
rundale-bench qualify collect --env-file .env.bench
python3 review/validate_ratings.py /path/to/ratings.json
rundale-bench qualify evaluate --ratings /path/to/ratings.json
```

Collection is resumable under its durable $10 total cap. It sends the frozen
English pack to native Sol high and Jev. Evaluation selects on eight cases,
validates on eight separate cases, and pins the selected judges and provider
configuration only if both evals pass. Public review examples are development
validation, not a secret contamination-resistant holdout. Qualification evidence
publishes the axis references without the reviewer's identifier. Once qualified,
change the benchmark version to change its cases, rubric, judges, or profiles.

## Publish a result

`rundale-bench publish` rebuilds the local index. From a clean checkout with only
`results/` changes, `rundale_bench.publication.publish_results_pr(root)` runs the
offline gates and opens a results PR. An agent then attaches that PR to its task,
waits for CI, and starts an independent gatekeeper. The gatekeeper decides whether
to merge; Pages deploys main. For a DNF, call
`rundale_bench.publication.file_failure_issue(root, run)` and verify its receipt.
Neither helper claims an unconfirmed external action succeeded.
