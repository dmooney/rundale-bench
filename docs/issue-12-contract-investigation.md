# Gemini output contracts: issue #12

This is an append-only diagnostic of run `4b4f0c1824d6`, not a replacement run
or a scoring correction. The original DNF, `failure_cause: model`, two failure
events, costs and grades remain frozen. No paid reproduction is needed to
establish the observations below.

## Evidence and reproduction

The [issue and prior investigation](https://github.com/dmooney/rundale-bench/issues/12)
identify the source artifact and production-contract uncertainty.
The [immutable run](../results/3.0/runs/4b4f0c1824d6.json) has SHA-256
`90fe38027bc3c04e18f76333e08e410b8bd7aca65d3db5c64cddf1025db697e8`.
The attempt used implementation `54c193055c03bbfc64d34078b882a914139cf930`
and engine capture `5c14ea236022aed698e478837a6c754657239ae7`.

Run `PYTHONPATH=src python3 -m unittest discover -s tests -p test_gemini_archived_failures.py -v`.
The regression replays both saved native chunk sequences through
`NativeClient.generate`, using an in-memory transport and blocking sockets.
It compares text and canonical usage exactly, checks the source hash, and
reproduces the strict runner/scorer failures without printing candidate prose.

| Request | Text SHA-256 | Native metering (input / output / reasoning) |
| --- | --- | --- |
| `m08:0:candidate:4` | `a9424e24c8e3beec955c35fed9fbea72b862f30e110e2feaef6bd60c6d3ae3b8` | 2959 / 1293 / 0 |
| `g24:0:candidate:0` | `5e4180a6d3203cba7f9ddb7341d320b4b60f899e2326086ee920e561d6266667` | 89 / 1267 / 1229 |

Both finish with `STOP`, below the 4096 output-token cap. Neither native stream
marks any part `thought: true`. Ordinary text parts concatenate exactly to the
archived response, including escaping and literal newlines. There is no evidence
of text corruption or a separately flagged thought channel being exposed.
Reconstructed requests retain `thinkingLevel: high`, the saved message history,
and no `responseMimeType` or `responseSchema`. Candidate calls supply no schema;
the adapter's optional constrained-output path is used for judges, not candidates.

## Separate causes and ownership

**NPC:** the fifth turn of `m08` follows the saved conversation about uncertainty
over an eviction notice; the player offers to bring bread tomorrow. The history
still contains the NPC JSON instruction. A literal newline inside a JSON string
at character 41 causes strict parsing to fail. Allowing control characters still
fails on a later delimiter. The resulting text also presents a `thought_process`
field outside the allowed NPC keys. The immediate failure belongs to model output
under the benchmark's prompt-only contract; the adapter preserves it faithfully.
Why the model produced that content is unresolved by a single saved response.

**Gaeilge:** `g24` explicitly requests exactly one JSON object. Markdown fences
violate that instruction and cause parsing to fail at character zero. This is a
model formatting failure under the frozen contract. Removing fences diagnostically
still scores zero: `event` is `The fair`, while the answer key requires
`fair begins`. However, the prompt does not define a canonical event phrase.
That lexical mismatch is a benchmark prompt/answer-key design weakness, not
independent evidence of a meaning error. Both responses extract the same time;
the returned Irish choice is correct. The formatting failure alone is sufficient
for the archived malformed-output event.

**Production parity:** production-path prompt capture does not establish the
resolved generation contract. The pinned engine's
[configuration](https://github.com/dmooney/Rundale/blob/5c14ea236022aed698e478837a6c754657239ae7/limerick/crates/limerick-config/src/engine/inference.rs#L180)
defaults `json_mode` to true, while its
[resolver](https://github.com/dmooney/Rundale/blob/5c14ea236022aed698e478837a6c754657239ae7/limerick/crates/limerick-inference/src/worker.rs#L60)
allows `PromptValidatedJson` to override native constraints, as recorded in the
issue's production investigation. The capture omits the resolved route contract.
Production-equivalent failure attribution therefore remains unresolved; it would
be incorrect to call omission of a schema a proven production adapter defect.

This diagnostic qualifies the scope of the original `model` attribution: it
describes failures against Benchmark 3.0's actual prompt-only contract, not a
verified production wire contract. No attribution correction is justified for
the two observed formatting failures. The historical exact-event zero must not
be presented as proof of semantic misunderstanding.

## Contract decision and version boundary

Retain Benchmark 3.0 as a strict, prompt-only output assessment. Do not add schema
arguments, strip fences, repair JSON, accept synonyms, resume the terminal run,
or recompute its grades. This preserves comparability with existing 3.0 results;
it does not assert that prompt-only output was a documented production-parity
decision when the suite was built.

For the next version, use these acceptance criteria before freezing a suite:

1. Capture and hash the resolved production route contract, generation settings,
   output mode and schema alongside prompts. Record whether the route requires
   prompt-validated JSON, JSON-object mode, or a native schema. Map that exact
   contract for each supported native provider, with request-body regressions.
   Native constraints should follow the captured route, not be added just to
   rescue a failing candidate. Block claims of production parity until captured.
2. Replace free-form event labels in code-switch cases with explicit closed
   choices for the English proposition (for example, `fair begins` versus
   `fair ends`) and state the accepted values in the prompt. Retain the Irish
   choice and time fields. Test every accepted value, incorrect propositions,
   missing/extra fields, and non-JSON output. This avoids an unbounded synonym
   list or a paid semantic judge for an objective task.
3. Pin the revised prompts, answer keys, route metadata and scoring policy under
   a new benchmark version. Re-run applicable suite/qualification gates before
   paid execution; publish new results separately. Do not pool their scores with
   3.0 or describe constrained and prompt-only success rates as interchangeable.

These are future-suite requirements, not an implemented or qualified new version.
The present change adds evidence and regression coverage only.
