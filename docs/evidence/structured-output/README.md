# Live Google structured-output smoke test

On October 23, 2026, four native Google requests exercised the uncommitted 3.1
candidate schema path with `gemini-3.5-flash-lite`, reasoning `high`, and the
unchanged 4,096-token limit. The durable local ledger capped the test at $0.25.
[Raw evidence](google-smoke.json) retains requests, schemas, native streaming
responses, model identity, usage, timing and validation outcomes.

The four calls were d01, the saved m08 fifth-turn request that failed in 3.0
run `4b4f0c1824d6`, g01, and the g24 extraction request that failed in that run.
The m08 call replayed its saved prompt/history; it was not a fresh six-turn
conversation. All four returned the named native model, finished with `STOP`,
and passed local schema validation. Both NPC replies passed the dialogue
contract. No output repair, retries or judge calls were used.

The g01 choice scored 100 under the objective key. The g24 extraction was
schema-valid but scored 0: it returned `event: "The fair begins"` rather than
`"fair begins"`. Its meaning choice and time matched. This illustrates the
unchanged exact-string scoring limitation; neither the response nor answer key
was normalized to make it pass.

Usage-priced cost and settled exposure were $0.0112745 at pinned profile rates,
not an invoice receipt. This is four-call smoke evidence of provider schema
acceptance, not a ranked benchmark, judge qualification, quality estimate or
proof of reliability across the full suite. No published 3.0 record changed.
