# Paid-run implementation provenance

Both 3.1 paid runs were produced from **uncommitted working-tree states** based
on main `768e0ff809d034df37de9f1da5478ec6005e90d2`. Exact implementation snapshots
were not recorded at launch. They are not claimed to have run at a later PR
commit, and the missing revision cannot be recovered from file modification
times. Their frozen suite hash is
`1905b2708add5b7dc1b421fd444c6c67a4cebed53eceeabc8fac25de56a63055`.

- `gemini35-structured-20261023` was produced by an earlier uncommitted 3.1
  revision, before the subsequent review edits.
- `sol61-structured-20261024` also began from an uncommitted state. Some review
  edits were made while its process was running; its exact loaded source
  snapshot is not pinned either.

The later runtime edit consolidates identical supported-provider tuples into
one constant. The builder and reused receipt have a **description-only basis
clarification** disclosing the 16 A/B answer-envelope prompt rewrites. That
instruction change was already present in the hashed 3.1 cases used by both
runs; it was initially under-described. The receipt's judge selections, gates,
metrics and evidence hashes were not changed or reset. The source 3.0 receipt
and four screening artifacts remain byte-identical. Site version selection,
regression tests and documentation were also updated. No manifest, case,
schema, rubric, answer key, candidate profile or pinned judge profile changed
between these paid runs and the final-code audit.

## Offline final-code equivalence audit

[The audit receipt](cached-replay.json) pins the audited runtime file hashes,
the audit-script hash, the original run-file hashes and local ledger rows.
It was produced with:

```sh
PYTHONPATH=src python3 scripts/replay_cached_run.py \
  gemini35-structured-20261023 sol61-structured-20261024 \
  --output docs/evidence/structured-output/cached-replay.json
```

The script copies suites, configuration, screening and SQLite caches into a
temporary fixture root. It clears only the copied run's reconstructed result
lists and invokes the final runner with a client that rejects new generation
and judge calls. Every candidate and judge request therefore passes the
original ledger's digest check. Both runs reproduced all 158 logical request
digests, every primary/repeat case score, aggregate score, coverage and cost
exactly. Original run and ledger files are not modified. There were zero
provider calls. A fixture test verifies successful replay and rejection after
an original ledger digest is deliberately changed in a temporary fixture.

This establishes equivalence of final-code logical requests and scoring on the
saved responses. It does not recover the unrecorded implementation snapshots,
prove original wire-byte equality, validate judges against humans, or supply a
new live evaluation. The raw native responses and the four-call live Google
smoke evidence remain the separate records of actual provider execution.
