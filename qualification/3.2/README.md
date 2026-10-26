# Benchmark 3.2 judge calibration

Benchmark 3.2 is draft and cannot run candidates until its pinned Opus 5.5 judge passes automated screening. No calibration judgments have been collected. The first attempt was rejected at Anthropic authentication; its reservation was canceled and the sanitized summary is in `calibration-attempt.json`. The raw local error and SQLite ledger remain under ignored `output/qualification/3.2/` for audit.

The first attempt’s canceled request used the pre-attempt contract, which is preserved locally as `output/qualification/3.2/aborted-auth-contract.json` with its archival metadata. The updated profile supports all five reasoning levels and sets a 16,384-token judge output limit, leaving bounded room for adaptive thinking and rationales across the rubric axes; this is a configured ceiling, not a reliability guarantee. The Anthropic adapter sends `thinking: {"type": "adaptive"}` and `output_config.effort: "high"` for this profile. Opus 5.5 always uses adaptive thinking, and the API accepts this explicit setting ([Anthropic thinking docs](https://platform.claude.com/docs/en/build-with-claude/thinking)).

After correcting the local Anthropic credential, run calibration from the repository root:

```sh
PYTHONPATH=src python3 -m rundale_bench.cli qualify --version 3.2 collect --env-file <private-env-file>
PYTHONPATH=src python3 -m rundale_bench.cli qualify --version 3.2 screen
PYTHONPATH=src python3 -m rundale_bench.cli validate-suite --version 3.2
```

The collector uses a durable $10 ledger in `output/qualification/3.2/`. It makes one set of calibration requests to the single pinned Opus profile. A failed or interrupted collection must be investigated and resumed only through the same ledger. The screen is offline and must pass exact rubric axes, at least 90% invariant-control agreement, and nonconstant original grades for both English evaluations. It writes a provisional receipt only after those checks pass. This screen does not establish human validation or accuracy. If screening fails, preserve the evidence and keep the suite draft; do not replace the pinned judge or invent results.

Do not reuse 3.0/3.1 calibration artifacts for 3.2. Do not modify the Opus profile, calibration prompt, controls, or suite rubrics after a judgment has been collected; any policy change needs another benchmark version.

The aborted authentication contract, raw error and ledger are local-only evidence and are not included in this repository. The pre-attempt source hashes describe an intermediate working tree, not a publicly recoverable source revision. Because the only request failed authentication, the ledger contained no committed or uncertain calls, and the suite remained draft, the original contract was archived unchanged before the profile was revised. No successful judgment evidence was reset.
