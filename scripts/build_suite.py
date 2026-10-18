#!/usr/bin/env python3
"""Build the v3.0 benchmark pack and its integrity manifest.

Dialogue envelopes come from a pinned production engine capture. Multi-turn and
Gaeilge cases are authored or source-backed fixtures, not observed gameplay.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "suites/3.0"
ENGINE_COMMIT = "5c14ea236022aed698e478837a6c754657239ae7"
MAX_OUTPUT_TOKENS = 4096

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def msg(content: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": content}]

def build_cases() -> list[dict]:
    cases: list[dict] = []
    capture_path = OUT / "engine_capture.jsonl"
    captures = [json.loads(line) for line in capture_path.read_text().splitlines()]
    for i, item in enumerate(captures, 1):
        cases.append({"id": f"d{i:02}", "eval": "dialogue", "messages": [
            {"role": "system", "content": item["system"]},
            {"role": "user", "content": item["request"]}],
            "max_output_tokens": MAX_OUTPUT_TOKENS, "metadata": {"source": "pinned_engine_capture", "engine_prompt_id": item["prompt_id"], "npc_id": item["npc_id"], "npc_name": item["npc_name"], "repeat": i in {2, 8, 14, 20, 22, 24}}})

    scenarios = [
        (["My name is Eamon Byrne, and I mend nets for a living.", "I am bound for Ballinasloe market tomorrow.", "My sister Nora will meet me at the bridge at noon.", "I have a parcel of linen to bring her.", "I may stop at the mill, though I have not decided.", "Remind me of my name, my work, where and when Nora will meet me, what I carry, and whether the mill stop is settled."], "Retain the player's name, trade, meeting place and time, parcel, and uncertainty about the mill stop."),
        (["I am Bríd Fallon, a seamstress from the south road.", "My brown cow was last seen by the river at noon.", "I saw a gate on the western bank, but it was locked.", "The field beyond it bears an O'Rourke name-board.", "I did not see the cow cross the river.", "Tell me my name and trade, where and when I last saw the cow, what blocked the western bank, and whether I saw her cross."], "Retain player identity and trade, cow sighting, time, locked gate, O'Rourke board, and explicit uncertainty about crossing."),
        (["I am Seamus Ward, a carter staying here until Friday.", "I read a notice saying the fair begins Friday.", "The notice gave no hour for the first event.", "I need a cart for the road to the mill.", "I have asked Tomás, but he has not answered me.", "What day is the fair, what time does it begin, and has Tomás agreed to lend me a cart?"], "Keep the stated fair day, missing event time, and unanswered cart request distinct."),
        (["My name is Nóra Kelly, and I keep accounts for the shop.", "I owe six pence, due next Monday.", "The coin is wrapped in a blue cloth in my pocket.", "I promised to bring the receipt to the chapel gate.", "I have not yet chosen a meeting hour.", "How much do I owe, when is it due, where is the coin, and what meeting details remain undecided?"], "Retain amount, due date, coin location, receipt destination, and unknown meeting hour."),
        (["I am Liam Walsh, a miller's apprentice.", "I need the north lane to reach the mill.", "A notice says the bridge is closed.", "The map shows a shallow ford east of the bridge.", "No one has told me if the ford is safe after rain.", "Repeat my destination and route, the bridge status, the ford's direction, and what is still unknown about safety."], "Retain destination, north-lane route, closure, ford direction, and uncertainty about safety."),
        (["I am Maeve Doyle, a traveler seeking a bed.", "The innkeeper's slate says every bed is taken.", "A separate note offers the loft for one night.", "The note says the loft is dry but cold.", "It also says one blanket remains; I have not taken it yet.", "Where can I sleep, what are the loft's conditions, and have I taken the blanket?"], "Distinguish the full beds, available loft, its conditions, and the blanket not yet taken."),
        (["My name is Ciarán Flynn, and I am carrying a parcel.", "The brown paper is torn along one edge.", "The contents look sound to me.", "A boy from the eastern road brought it.", "I did not learn the boy's name.", "What is damaged, what seems sound, who delivered the parcel, and do I know his name?"], "Retain the tear, apparently sound contents, eastern-road messenger, and unknown name."),
        (["I am Aisling Byrne, a widow from the lower field.", "I heard one unnamed family received an eviction notice.", "I do not know which family it was.", "A neighbor told me bread may be useful to them.", "I offered to bring bread tomorrow.", "What do I know about the notice and family, and what help did I offer and when?"], "Do not infer a family identity; retain the report's uncertainty and offer of bread tomorrow."),
    ]
    for i, (turns, criterion) in enumerate(scenarios, 1):
        captured = captures[(i - 1) * 3]
        cases.append({"id": f"m{i:02}", "eval": "multiturn", "system": captured["system"], "initial_context": captured["request"], "turns": turns, "max_output_tokens": MAX_OUTPUT_TOKENS, "metadata": {"source": "authored_six_turn_script_with_pinned_engine_system_and_context", "engine_prompt_id": captured["prompt_id"], "npc_name": captured["npc_name"], "memory_criterion": criterion, "repeat": i in {2, 6}}})

    # The accepted/unaccepted pairs and glosses below are copied from the
    # CC-BY-4.0 Irish-BLiMP paper's worked examples, not the gated HF dataset.
    grammar = [
        ("Baineadh geit aisti ar maidin.", "Bhaineadh geit aisti ar maidin.", "She got a fright in the morning."),
        ("Cailín bocht.", "Cailín bhocht.", "Poor girl."),
        ("An duine is ciúine.", "An duine is ciúin.", "The quietest person."),
        ("Sin ár n-arán-na.", "Sin ár arán-na.", "That's our bread."),
        ("Ar an lampa.", "Ar an nlampa.", "On the lamp."),
        ("Ochtar fear.", "Ochtar fhear.", "Eight men."),
        ("Is cluichire mé.", "Tá mé cluichire.", "I am a gamer."),
        ("Labhróidh Liam amárach.", "Liam labhróidh amárach.", "Liam will speak tomorrow."),
    ]
    paper_ref = "https://arxiv.org/html/2510.20957v1"
    paper_license = "CC BY 4.0"
    paper_sections = ["3.2.1", "3.2.2", "3.2.3", "3.2.4", "3.2.5", "3.2.6", "3.2.7", "3.2.8"]
    grammar_shuffle = random.Random(3)
    for i, (good, bad, gloss) in enumerate(grammar, 1):
        option_text = [good, bad]
        grammar_shuffle.shuffle(option_text)
        options = [("AB"[j], text) for j, text in enumerate(option_text)]
        answer = next(letter for letter, text in options if text == good)
        prompt = "Choose the standard grammatical Irish sentence. Reply A or B only.\n" + "\n".join(f"{letter}: {text}" for letter, text in options)
        section = paper_sections[i - 1]
        cases.append({"id": f"g{i:02}", "eval": "gaeilge", "subcategory": "grammar", "messages": msg(prompt), "max_output_tokens": MAX_OUTPUT_TOKENS, "answer": {"type": "choice", "expected": answer}, "metadata": {"source": "Irish-BLiMP paper worked example", "reference": f"{paper_ref}#S{section}", "license": paper_license, "attribution": f"McGiff et al., Irish-BLiMP (2025), Section {section}", "source_gloss": gloss, "correct_sentence": good, "shuffle_seed": 3, "repeat": i in {1, 5}}})

    meanings = [
        ("Baineadh geit aisti ar maidin.", "She got a fright in the morning.", "She gave a fright in the morning."),
        ("Cailín bocht.", "Poor girl.", "Rich girl."),
        ("An duine is ciúine.", "The quietest person.", "The loudest person."),
        ("Sin ár n-arán-na.", "That's our bread.", "That's their bread."),
        ("Ar an lampa.", "On the lamp.", "Under the lamp."),
        ("Ochtar fear.", "Eight men.", "Eight women."),
        ("Is cluichire mé.", "I am a gamer.", "I am a farmer."),
        ("Labhróidh Liam amárach.", "Liam will speak tomorrow.", "Liam spoke yesterday."),
    ]
    meaning_shuffle = random.Random(11)
    for i, (ga, en, distractor) in enumerate(meanings, 1):
        option_text = [en, distractor]
        meaning_shuffle.shuffle(option_text)
        options = [("AB"[j], text) for j, text in enumerate(option_text)]
        answer = next(letter for letter, text in options if text == en)
        prompt = f"Which option is the published English gloss for this Irish sentence? Reply A or B only.\nIrish: {ga}\n" + "\n".join(f"{letter}: {text}" for letter, text in options)
        section = paper_sections[i - 1]
        cases.append({"id": f"g{8+i:02}", "eval": "gaeilge", "subcategory": "meaning", "messages": msg(prompt), "max_output_tokens": MAX_OUTPUT_TOKENS, "answer": {"type": "choice", "expected": answer}, "metadata": {"source": "Irish-BLiMP paper worked example gloss", "reference": f"{paper_ref}#S{section}", "license": paper_license, "attribution": f"McGiff et al., Irish-BLiMP (2025), Section {section}", "source_gloss": en, "shuffle_seed": 11, "repeat": i in {2}}})

    switches = [
        ("Baineadh geit aisti ar maidin.", "She got a fright in the morning.", "The sealed parcel is under the bench.", "The parcel is sealed.", {"parcel_location": "under the bench", "parcel_condition": "sealed"}),
        ("Cailín bocht.", "Poor girl.", "The blue cup is beside the hearth.", "The cup is green and beside the hearth.", {"cup_color": "blue", "cup_location": "beside the hearth"}),
        ("An duine is ciúine.", "The quietest person.", "The narrow gate is open.", "The wide gate is open.", {"gate_state": "open", "gate_width": "narrow"}),
        ("Sin ár n-arán-na.", "That's our bread.", "We have two loaves for the road.", "We have two loaves for supper.", {"loaves": "two", "purpose": "for the road"}),
        ("Ar an lampa.", "On the lamp.", "The key is in the drawer.", "The key is under the drawer.", {"key_location": "in the drawer"}),
        ("Ochtar fear.", "Eight men.", "The gate by the chapel is closed.", "Eight women.", {"gate_state": "closed"}),
        ("Is cluichire mé.", "I am a gamer.", "The small boat belongs to me.", "The large boat belongs to me.", {"boat_size": "small", "boat_owner": "speaker"}),
        ("Labhróidh Liam amárach.", "Liam will speak tomorrow.", "The fair begins at noon tomorrow.", "The fair begins at dusk tomorrow.", {"event": "fair begins", "time": "noon tomorrow"}),
    ]
    switch_shuffle = random.Random(17)
    answer_letters = ["A"] * 4 + ["B"] * 4
    switch_shuffle.shuffle(answer_letters)
    for i, (ga, gloss, english, contrast, fact_keys) in enumerate(switches, 1):
        answer = answer_letters[i - 1]
        options = [("A", gloss if answer == "A" else contrast), ("B", gloss if answer == "B" else contrast)]
        expected = {"irish_meaning_choice": answer, **fact_keys}
        prompt = (f"Mixed-language report: {ga} {english}\n"
                  "Choose the option that gives the meaning of the Irish phrase. Also extract only facts stated in English. "
                  "Return exactly one JSON object with string values, using these keys: "
                  f"{', '.join(expected)}.\nIrish meaning options:\n" +
                  "\n".join(f"{letter}: {text}" for letter, text in options))
        section = paper_sections[i - 1]
        cases.append({"id": f"g{16+i:02}", "eval": "gaeilge", "subcategory": "code_switch", "messages": msg(prompt), "max_output_tokens": MAX_OUTPUT_TOKENS, "answer": {"type": "exact_json", "expected": expected}, "metadata": {"source": "Irish-BLiMP paper Irish example and gloss plus authored English facts and contrast", "reference": f"{paper_ref}#S{section}", "license": paper_license, "attribution": f"McGiff et al., Irish-BLiMP (2025), Section {section}; English facts and contrast authored for this test", "source_gloss": gloss, "authored_contrast": contrast, "english_facts": fact_keys, "answer_letter": answer, "shuffle_seed": 17, "repeat": i in {1}}})
    return cases

def rubrics() -> dict:
    axes = {
        "character": ("Uses the captured NPC role, knowledge, and established voice.", ["Speaks as an incompatible role or claims expertise explicitly forbidden by the system.", "Mostly departs from role or voice, with a major knowledge-boundary breach.", "Role is recognizable but includes one notable voice or knowledge mismatch.", "Role and voice fit; only a small mismatch.", "Distinctly fits the captured role, knowledge boundary, and voice." ]),
        "period_authenticity": ("Fits the captured 1820 rural Roscommon setting and cultural instructions.", ["Clear modern anachronism or degrading stage-Irish caricature.", "Multiple period errors or a strong stereotyped portrayal.", "Mostly plausible with one noticeable anachronism or cultural mismatch.", "Fits the period and instructions with only a minor wording issue.", "Plausible to the setting and culturally respectful throughout." ]),
        "responsiveness": ("Addresses the player's current request in a way that can continue the exchange.", ["Does not address the request or answers an unrelated one.", "Touches the topic but misses the player's central request.", "Partly answers, with a material omission or awkward redirection.", "Answers the request; a minor detail is missed.", "Directly answers the request and creates a natural next conversational step." ]),
        "grounding": ("Uses only scene and character facts that are supplied or securely established.", ["Invents consequential facts or presents unknown information as certain.", "Adds multiple unsupported claims or one consequential false certainty.", "Mostly grounded with one unsupported but low-impact claim.", "Grounded; any inference is clearly bounded.", "Uses established facts precisely and states uncertainty where the context is silent." ]),
        "craft": ("Produces concise, clear spoken dialogue suited to the captured prompt.", ["Incoherent, non-dialogue, or so overlong/repetitive that the turn fails.", "Several clarity problems, repeated phrasing, or substantial excess length.", "Understandable but noticeably repetitive, stiff, or overlong.", "Clear and concise with a small stylistic flaw.", "Natural, cleanly phrased dialogue of an appropriate length." ]),
        "mood_fidelity": ("Matches explicit mood and relationship cues in the captured system prompt.", ["Emotional tone directly contradicts the stated mood or relationship.", "Strongly mismatched warmth, hostility, or distress.", "Some tonal fit but a notable mismatch remains.", "Fits the current mood with only a small shift.", "Tone consistently reflects the stated mood and relationship." ]),
        "memory_consistency": ("Retains facts and uncertainty established over the six scripted turns.", ["Contradicts or loses multiple central facts.", "Contradicts one central fact or invents certainty about an unknown.", "Retains most facts with one material omission or minor contradiction.", "Retains all central facts; only a minor omission.", "Accurately carries forward every relevant fact, change, and uncertainty." ]),
        "persona_consistency": ("Maintains the same captured NPC role, knowledge boundary, and voice throughout.", ["Switches to an incompatible identity or role.", "Several substantial voice/knowledge mismatches.", "Mostly consistent with one notable lapse.", "Consistent with a minor lapse.", "Consistently expresses the captured NPC's role and knowledge boundary." ]),
        "conversational_relevance": ("Responds to the current user turn while using relevant prior context.", ["Ignores the current turn or ends the conversation with an unwarranted farewell.", "Mostly responds to a prior turn or drifts to an unrelated topic.", "Partly answers the current turn but misses a relevant contextual link.", "Answers the current turn and uses context with a minor omission.", "Directly answers the current turn and uses prior context only where relevant." ]),
    }
    return {group: {axis: {"description": axes[axis][0], "anchors": {str(n): text for n, text in enumerate(axes[axis][1], 1)}} for axis in names} for group, names in {"dialogue": ["character", "period_authenticity", "responsiveness", "grounding", "craft", "mood_fidelity"], "multiturn": ["memory_consistency", "persona_consistency", "conversational_relevance"]}.items()}

def main() -> None:
    existing = OUT / "manifest.json"
    if existing.exists() and json.loads(existing.read_text()).get("status") == "ready":
        raise ValueError("Ready suite is frozen; build a new benchmark version instead")
    OUT.mkdir(parents=True, exist_ok=True)
    cases = build_cases()
    case_bytes = b"".join((json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n").encode() for c in cases)
    rubric_bytes = (json.dumps(rubrics(), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    (OUT / "cases.jsonl").write_bytes(case_bytes)
    (OUT / "rubrics.json").write_bytes(rubric_bytes)
    counts = {name: sum(c["eval"] == name for c in cases) for name in ["dialogue", "multiturn", "gaeilge"]}
    capture_sha = digest((OUT / "engine_capture.jsonl").read_bytes())
    manifest = {
        "version": "3.0",
        "status": "draft",
        "launch_blocker": "English judge qualification pending",
        "diagnostic_blockers": [
            "The HF Irish-BLiMP dataset is manually gated; the 20-pairs-per-feature diagnostic selection is pending access."
        ],
        "engine": {
            "repository": "dmooney/Rundale",
            "commit": ENGINE_COMMIT,
            "capture_function": "limerick-core::ipc::handlers::prepare_npc_conversation_turn",
            "capture_source_file": "limerick/crates/limerick-core/src/ipc/handlers.rs",
            "capture_source_sha256": "ac640093287fe15ec29a6fa90be9c141f1fca58da30ea7e65242a99485af3925",
            "capture_file": "suites/3.0/engine_capture.jsonl",
            "capture_sha256": capture_sha,
        },
        "generation": {
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "prompt_contract": "Concise player-facing dialogue; token allowance permits provider reasoning or structured output without artificial truncation.",
        },
        "cases_sha256": digest(case_bytes),
        "rubrics_sha256": digest(rubric_bytes),
        "counts": counts,
        "repeat_ids": [c["id"] for c in cases if c["metadata"].get("repeat")],
        "sources": {
            "irish_blimp_paper": {
                "url": "https://arxiv.org/html/2510.20957v1",
                "pdf_sha256": "fb482892b645bf583c1e5ec47530bf07da9ea895fe1e7cae647582e4c61ec9ab",
                "license": "CC BY 4.0",
                "attribution": "McGiff et al. (2025), Irish-BLiMP, Sections 3.2.1–3.2.8",
                "example_choice_shuffle_seed": 3,
                "gloss_choice_shuffle_seed": 11,
            }
        },
        "source_coverage": {
            "published_irish_examples": 8,
            "probe_groups_per_example": 3,
            "independent_irish_source_items": 8,
            "probe_observations": 24,
            "observations_are_independent": False,
            "note": "The same eight published examples support grammar, meaning, and code-switch probes; 24 observations are not 24 independent Irish source items.",
        },
        "selection": {
            "irish_blimp": {
                "repository": "https://github.com/ReML-AI/Irish-BLiMP",
                "repository_commit": "5a49894e7d7068d2187773248f64dd1d0bce22f6",
                "repository_license": "MIT",
                "hf_dataset": "https://huggingface.co/datasets/ReliableAI/irish_blimp",
                "hf_dataset_revision": "160b545b14f76423ccd2c4c27b177cfe26f21b96",
                "hf_license": "MIT",
                "access": "manual-gated; dataset rows and parquet returned HTTP 401 without authentication",
                "split_keys": [
                    "1_verbal_morphology", "2_nouns_cases", "3_adjectives_comparison",
                    "4_pronouns", "5_articles_determiners", "6_numbers", "7_copula_bí",
                    "8_clause_structure_word_order", "9_questions_negations",
                    "10_discourse_sentence_types", "11_adverbs_modifiers",
                ],
                "qualification_plan": {
                    "planned_pairs_per_feature": 20,
                    "feature_count": 11,
                    "planned_total_pairs": 220,
                    "planned_per_split_per_feature": 10,
                    "actual_dev_record_count": None,
                    "actual_qualification_record_count": None,
                    "actual_split_disjointness_verified": None,
                    "status": "diagnostic_pending_manual_dataset_gate",
                },
            },
            "eu_mmlu": {
                "source": "https://huggingface.co/datasets/EC-DGT-AI/EU-MMLU",
                "revision": "6bf04b0030783b3c9074c8d59416ff761962568a",
                "config": "GA_IE",
                "license": "MIT",
                "available_subjects": ["global_facts", "international_law", "management", "sociology"],
                "status": "reviewed; no game-relevant subset identified; no items imported",
            },
        },
        "judge_policy": {"dialogue": None, "multiturn": None},
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

if __name__ == "__main__":
    main()
