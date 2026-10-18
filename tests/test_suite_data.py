import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "suites/3.0"


class SuiteDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([sys.executable, str(ROOT / "scripts/build_suite.py")], check=True)
        cls.manifest = json.loads((SUITE / "manifest.json").read_text())
        cls.cases_bytes = (SUITE / "cases.jsonl").read_bytes()
        cls.cases = [json.loads(line) for line in cls.cases_bytes.splitlines()]

    def test_manifest_hashes_and_counts(self):
        self.assertEqual(hashlib.sha256(self.cases_bytes).hexdigest(), self.manifest["cases_sha256"])
        self.assertEqual(hashlib.sha256((SUITE / "rubrics.json").read_bytes()).hexdigest(), self.manifest["rubrics_sha256"])
        self.assertEqual(len(self.cases), 56)
        self.assertEqual(self.manifest["counts"], {"dialogue": 24, "multiturn": 8, "gaeilge": 24})
        self.assertEqual(self.manifest["status"], "draft")
        self.assertEqual(self.manifest["launch_blocker"], "English judge qualification pending")
        self.assertIn("manually gated", " ".join(self.manifest["diagnostic_blockers"]))
        capture = (SUITE / "engine_capture.jsonl").read_bytes()
        self.assertEqual(hashlib.sha256(capture).hexdigest(), self.manifest["engine"]["capture_sha256"])
        self.assertEqual(self.manifest["generation"]["max_output_tokens"], 4096)
        self.assertEqual(self.manifest["engine"]["capture_function"], "limerick-core::ipc::handlers::prepare_npc_conversation_turn")
        self.assertEqual(len(self.manifest["engine"]["capture_source_sha256"]), 64)
        self.assertIsNone(self.manifest["selection"]["irish_blimp"]["qualification_plan"]["actual_split_disjointness_verified"])

    def test_captured_dialogue_envelopes_and_current_engine_pin(self):
        captures = [json.loads(line) for line in (SUITE / "engine_capture.jsonl").read_text().splitlines()]
        dialogue = [c for c in self.cases if c["eval"] == "dialogue"]
        self.assertEqual(len(captures), 24)
        self.assertTrue(all(c["engine_revision"] == self.manifest["engine"]["commit"] for c in captures))
        for case, capture in zip(dialogue, captures):
            self.assertEqual(case["metadata"]["engine_prompt_id"], capture["prompt_id"])
            self.assertEqual(case["messages"], [{"role": "system", "content": capture["system"]}, {"role": "user", "content": capture["request"]}])
        multi = [c for c in self.cases if c["eval"] == "multiturn"]
        self.assertTrue(all(c["system"] in {p["system"] for p in captures} for c in multi))
        for case in multi:
            self.assertIn(case["initial_context"], [p["request"] for p in captures])
            self.assertEqual(len(case["turns"]), 6)
            for turn in case["turns"]:
                self.assertFalse(any(phrase in turn for phrase in ("He says", "She says", "They say", "The farmer says")))

    def test_case_shapes_subcategories_and_six_turns(self):
        ids = [c["id"] for c in self.cases]
        self.assertEqual(len(ids), len(set(ids)))
        for case in self.cases:
            self.assertIn("max_output_tokens", case)
            if case["eval"] in {"dialogue", "gaeilge"}:
                self.assertTrue(case["messages"])
                self.assertTrue(all(m["role"] in {"system", "user", "assistant"} for m in case["messages"]))
            if case["eval"] == "multiturn":
                self.assertEqual(len(case["turns"]), 6)
            if case["eval"] == "gaeilge":
                self.assertIn(case["subcategory"], {"grammar", "meaning", "code_switch"})
                self.assertIn(case["answer"]["type"], {"choice", "exact_json"})
        ga = [c for c in self.cases if c["eval"] == "gaeilge"]
        self.assertEqual({k: sum(c["subcategory"] == k for c in ga) for k in ("grammar", "meaning", "code_switch")}, {"grammar": 8, "meaning": 8, "code_switch": 8})

    def test_repeat_plan_and_unqualified_external_sources_are_explicit(self):
        repeated = [c["id"] for c in self.cases if c["metadata"].get("repeat")]
        self.assertEqual(repeated, self.manifest["repeat_ids"])
        self.assertEqual(sum(c["eval"] == "dialogue" and c["metadata"].get("repeat") for c in self.cases), 6)
        self.assertEqual(sum(c["eval"] == "multiturn" and c["metadata"].get("repeat") for c in self.cases), 2)
        self.assertEqual(sum(c["eval"] == "gaeilge" and c["metadata"].get("repeat") for c in self.cases), 4)
        qual = self.manifest["selection"]["irish_blimp"]["qualification_plan"]
        self.assertEqual(qual["planned_pairs_per_feature"] * qual["feature_count"], qual["planned_total_pairs"])
        self.assertIsNone(qual["actual_dev_record_count"])
        self.assertIsNone(qual["actual_qualification_record_count"])
        self.assertIsNone(qual["actual_split_disjointness_verified"])
        self.assertEqual(qual["status"], "diagnostic_pending_manual_dataset_gate")
        self.assertEqual(self.manifest["judge_policy"], {"dialogue": None, "multiturn": None})

    def test_gaeilge_gold_has_paper_attribution_and_rubrics_are_anchored(self):
        ga = [c for c in self.cases if c["eval"] == "gaeilge"]
        self.assertTrue(all(c["metadata"]["reference"].startswith("https://arxiv.org/html/2510.20957v1#S3.2.") for c in ga))
        self.assertTrue(all(c["metadata"]["license"] == "CC BY 4.0" for c in ga))
        self.assertTrue(all(c["metadata"]["attribution"].startswith("McGiff et al.") for c in ga))
        for subcategory in ("grammar", "meaning", "code_switch"):
            items = [c for c in ga if c["subcategory"] == subcategory]
            letter_for = lambda c: c["answer"]["expected"] if subcategory != "code_switch" else c["answer"]["expected"]["irish_meaning_choice"]
            answer_counts = {letter: sum(letter_for(c) == letter for c in items) for letter in "AB"}
            self.assertEqual(answer_counts, {"A": 4, "B": 4})
            for case in items:
                prompt = case["messages"][0]["content"]
                if subcategory == "code_switch":
                    expected = case["answer"]["expected"]
                    self.assertEqual(prompt.count(case["metadata"]["source_gloss"]), 1)
                    self.assertIn(f"{case['metadata']['answer_letter']}: {case['metadata']['source_gloss']}", prompt)
                    self.assertEqual(expected["irish_meaning_choice"], case["metadata"]["answer_letter"])
                    self.assertEqual({k: v for k, v in expected.items() if k != "irish_meaning_choice"}, case["metadata"]["english_facts"])
                    self.assertIn("Mixed-language report:", prompt)
                    self.assertNotIn("Published English gloss:", prompt)
                else:
                    correct = case["metadata"].get("correct_sentence", case["metadata"].get("source_gloss"))
                    self.assertIsNotNone(correct)
                    self.assertIn(f"{case['answer']['expected']}: {correct}", prompt)
        switches = [c for c in ga if c["subcategory"] == "code_switch"]
        ochtar = next(c for c in switches if c["id"] == "g22")
        self.assertEqual(ochtar["answer"]["expected"]["gate_state"], "closed")
        report = ochtar["messages"][0]["content"].lower().split("irish meaning options:", 1)[0]
        self.assertNotIn("eight men", report)
        coverage = self.manifest["source_coverage"]
        self.assertEqual(coverage["published_irish_examples"], 8)
        self.assertEqual(coverage["probe_groups_per_example"], 3)
        self.assertEqual(coverage["independent_irish_source_items"], 8)
        self.assertFalse(coverage["observations_are_independent"])
        self.assertTrue(all(c["max_output_tokens"] == 4096 for c in self.cases))
        rubrics = json.loads((SUITE / "rubrics.json").read_text())
        for groups in rubrics.values():
            for rubric in groups.values():
                self.assertEqual(set(rubric["anchors"]), {"1", "2", "3", "4", "5"})
                self.assertEqual(len(set(rubric["anchors"].values())), 5)
                self.assertNotIn("harmful", " ".join(rubric["anchors"].values()))


if __name__ == "__main__":
    unittest.main()
