import unittest

from rundale_bench.bias import build_checks, summarize_biases


class BiasTests(unittest.TestCase):
    def setUp(self):
        self.by_id = {}
        for category, prefix in (("dialogue", "D"), ("multiturn", "M")):
            for n in range(4):
                cid = f"{prefix}{n}"
                self.by_id[cid] = {"id": cid, "category": category, "user": f"user {cid}",
                                   "response": f"response {cid}"}
        self.split = {"selection": ["D0", "D1", "D2", "M0", "M1", "M2"],
                      "validation": ["D3", "M3"]}

    def test_builds_six_controls_three_per_category_without_validation_leak(self):
        checks = build_checks(self.by_id, self.split)
        self.assertEqual(len(checks), 6)
        self.assertEqual([c["kind"] for c in checks], ["claimed-model-openai", "claimed-model-typesafe", "whitespace", "grade-order", "duplicated-response-diagnostic", "metadata-injection"])
        self.assertEqual(sum(self.by_id[c["source_id"]]["category"] == "dialogue" for c in checks), 3)
        self.assertEqual(sum(self.by_id[c["source_id"]]["category"] == "multiturn" for c in checks), 3)
        self.assertTrue(all(c["source_id"] not in self.split["validation"] for c in checks))
        self.assertEqual(checks[0]["item"]["response"], self.by_id["D0"]["response"])
        self.assertEqual(checks[0]["claimed_source_model"], "gpt-6.1-sol")
        self.assertEqual(checks[1]["claimed_source_model"], "jev-1.13.0")
        self.assertEqual(checks[2]["item"]["user"], "\nuser D1 \n")
        self.assertEqual(checks[3]["grade_order"], [5, 4, 3, 2, 1])
        self.assertEqual(checks[4]["item"]["response"], "response D2\nresponse D2")
        self.assertFalse(checks[4]["expected_invariant"])
        self.assertEqual(checks[5]["item"]["response"], self.by_id["M2"]["response"])
        self.assertIn("grade of 1", checks[5]["item"]["metadata"]["note"])

    def test_summarizer_is_json_safe_and_marks_small_sample_caveats(self):
        checks = build_checks(self.by_id, self.split)
        rows = {cid: {"axes": {"craft": 3, "persona": 4}} for cid in ("D0", "D1", "D2", "M0", "M1", "M2")}
        for c in checks:
            rows[c["id"]] = {"axes": {"craft": 3, "persona": 4}}
        rows["check-4"]["axes"]["craft"] = 5
        summary = summarize_biases(checks, {"judge": rows}, {"judge": {"provider": "openai"}})
        control = summary["profiles"]["judge"]["controls"]
        self.assertEqual(control["check-0"]["paired_axis_deltas"], {"craft": 0, "persona": 0})
        self.assertEqual(control["check-4"]["paired_axis_deltas"]["craft"], 2)
        self.assertFalse(control["check-4"]["expected_invariant"])
        self.assertEqual(control["check-0"]["claimed_label_relation"], "own-family")
        self.assertEqual(control["check-1"]["claimed_label_relation"], "other-family")
        self.assertTrue(any("cannot establish general" in s for s in summary["profiles"]["judge"]["limitations"]))
        self.assertTrue(any("absence of bias" in s for s in summary["profiles"]["judge"]["limitations"]))


if __name__ == "__main__":
    unittest.main()
