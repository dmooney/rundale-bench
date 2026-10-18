# v3.0 dataset provenance

The 24 dialogue cases use the exact `system` and `user` strings returned by
`prepare_npc_conversation_turn` in `dmooney/Rundale` at engine commit
`5c14ea236022aed698e478837a6c754657239ae7`. The capture source is
`limerick/crates/limerick-core/src/ipc/handlers.rs`; its file hash, function,
revision, and the frozen JSONL hash are in the manifest. Each case retains its
engine prompt ID, NPC ID, and NPC name.

The eight six-turn memory scripts are authored benchmark fixtures. Each keeps
the exact captured NPC system prompt and request in separate `system` and
`initial_context` fields. The six turns are player utterances that introduce
facts or uncertainty and later ask the NPC to recall them; they do not script
NPC replies as if they were observed. They are not captured gameplay
transcripts. All cases reserve 4096 output tokens so provider reasoning or
structured output is not truncated by a small artificial cap; prompts still ask
for concise player-facing replies.

All 24 Gaeilge cases draw Irish examples and English glosses from worked
examples in Sections 3.2.1–3.2.8 of McGiff et al., [*Irish-BLiMP: A Linguistic
Benchmark for Evaluating Human and Language Model Performance in a Low-Resource
Setting*, version 1](https://arxiv.org/html/2510.20957v1). The paper is licensed
CC BY 4.0; each item carries section-level attribution and its exact gloss.
The paper reports that the authors manually constructed the examples and had
each pair reviewed by at least two fluent Irish speakers. The grammar cases
preserve its accepted/unaccepted labels. The meaning cases use its English
glosses verbatim as balanced multiple-choice keys, with an authored contrast as
the distractor. Code-switch cases place a published Irish phrase in a mixed
Irish-English report alongside newly authored English facts. They do not show
the Irish gloss to the model: a balanced A/B choice asks for the Irish meaning,
and exact JSON keys score that choice plus the independently stated English
facts. English contrast options and report facts are authored and attributed as
such. The same eight published Irish examples are reused across grammar,
meaning, and code-switch, so the 24 Gaeilge observations are dependent probes
from eight independent source sentences, not 24 independent Irish examples.
This 24-item probe is not a full Irish-BLiMP benchmark result.

The [Irish-BLiMP repository](https://github.com/ReML-AI/Irish-BLiMP) and its
MIT-licensed Hugging Face dataset are separate sources. Their revisions,
licenses, and config names are recorded in the manifest. The repository's task
YAMLs verify the config keys and label fields (`response1`, `response2`,
`correct_response`). The Hugging Face dataset is manually gated: public
metadata is visible, while dataset-row and parquet requests returned HTTP 401
without an authenticated grant. No dataset records, record keys, or selected
subsets are claimed as imported. The research diagnostic target is 20 pairs per
feature across 11 features, with planned development and qualification splits
of 10 pairs per feature each. The actual records, per-split counts, and
disjointness remain unverified until access is granted and selection is done.
This diagnostic gate does not qualify an Irish judge; the Gaeilge objective
items above are scored only against their published answer labels and glosses.

The [EU-MMLU dataset](https://huggingface.co/datasets/EC-DGT-AI/EU-MMLU) is
MIT-licensed and publishes an Irish (`GA_IE`) config. Its visible subjects are
`global_facts`, `international_law`, `management`, and `sociology`. I found no
game-relevant subset, so no EU-MMLU items or answer keys are included.

The manifest pins canonical cases, rubrics, captures, and source hashes; it
reports repeat IDs. The builder produces an unselected draft; automated
screening pins the judge policy and permits an explicitly provisional launch.
`python3 scripts/build_suite.py` refuses to overwrite a ready suite. Tests build
in temporary directories, preserving the active manifest and evidence.
