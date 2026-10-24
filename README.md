# Rundale Benchmark

Benchmark 3.1 evaluates Rundale dialogue, six-turn play, and Gaeilge with fixed,
versioned cases. These are product-specific evaluation scores, not measures of
general intelligence. The Gaeilge evaluation uses source-backed objective checks
and makes no Irish fluency claim.

Version 3.1 requests native schema-constrained candidate JSON and reuses the
unchanged provisional judge screening. Version 3.0 evidence stays frozen in its
own table. The 3.1 result index links two complete runs and their raw evidence for the
existing Pages publication workflow. [Implementation provenance](docs/evidence/structured-output/provenance.md)
records their uncommitted source states and final-code replay verification.

Version 3.0 publishes provisional scores after automated judge screening. Human
agreement and accuracy have not been measured; no manual review is required to
run it. Provisional dialogue and multi-turn component scores and DNF evidence
are published. A complete baseline is still required for launch acceptance.

## Requirements and installation

Install Node.js 24 and Python 3.12. From this repository, install the Python
package and site dependencies:

```sh
python3.12 -m pip install -e .
cd site && pnpm install --frozen-lockfile
```

Check suite and qualification readiness with:

```sh
rundale-bench validate-suite
rundale-bench status
```

Read the [benchmark specification](docs/specification.md), [running guide](docs/running.md),
[provider details](docs/providers.md), and [data provenance](docs/data-provenance.md)
before working on scoring or execution. Published records are shown at
[dmooney.github.io/rundale-bench](https://dmooney.github.io/rundale-bench/).
