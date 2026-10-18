from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SiteContractTests(unittest.TestCase):
    def test_dashboard_uses_dynamic_latest_rows_and_distinct_run_history(self):
        page = (ROOT / "site/src/pages/index.astro").read_text()
        for required in (
            "latestRows(version)", "findRun(version, runId)", "qualificationCopy(version)",
            "performanceLabel(row.uncertainty)", "coverageLabel(row.coverage)",
            "runNoticeLabel(row)", "runStatusLabel(row)", "spending_exposure_usd",
            "Quality qualification", "Irish-style impressions are provisional",
            "Raw request, response, and judgment record", "Download raw run JSON",
        ):
            self.assertIn(required, page)
        self.assertIn("latestRows(version)", page)
        self.assertNotIn("const runs=v.runs||[]", page)
        helpers = (ROOT / "site/src/lib/dashboard.mjs").read_text()
        self.assertIn("export function latestRows", helpers)
        self.assertIn("export function qualificationCopy", helpers)
        node_tests = (ROOT / "site/tests/dashboard.test.mjs").read_text()
        for behavior in ("latest rows and raw history", "DNF, reason", "qualification and performance summaries"):
            self.assertIn(behavior, node_tests)

    def test_build_copies_published_raw_run_records(self):
        script = (ROOT / "site/scripts/prepare-data.mjs").read_text()
        self.assertIn("results/index.json", script)
        self.assertIn("results', version.version, 'runs", script)
        self.assertIn("results.json", script)

    def test_review_is_offline_and_pages_are_native(self):
        review = ROOT / "review/review.html"
        self.assertTrue(review.is_file())
        contents = review.read_text()
        self.assertIn("localStorage", contents)
        self.assertIn("Download ratings", contents)
        config = (ROOT / "site/astro.config.mjs").read_text()
        self.assertIn("/rundale-bench", config)
        workflow = (ROOT / ".github/workflows/pages.yml").read_text()
        self.assertIn("permissions:", workflow)
        self.assertIn("pages: write", workflow)
        self.assertIn("pnpm install --frozen-lockfile", workflow)
        self.assertIn("pnpm run test", workflow)
        package = (ROOT / "site/package.json").read_text()
        self.assertIn('"test": "node --test tests/*.test.mjs"', package)
        self.assertIn("actions/deploy-pages@v4", workflow)


if __name__ == "__main__":
    unittest.main()
