import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.capture_engine_prompts import PINNED_REVISION, capture


class CaptureTests(unittest.TestCase):
    def test_rejects_unpinned_engine_before_build(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mod = root / "mod"
            mod.mkdir()
            (mod / "mod.toml").touch()
            with patch("scripts.capture_engine_prompts.git_revision", return_value="other"):
                with patch("scripts.capture_engine_prompts.subprocess.run") as run:
                    with self.assertRaisesRegex(ValueError, "revision mismatch"):
                        capture(root, mod, root / "capture.jsonl", root / "target")
                    run.assert_not_called()

    def test_pin_is_full_commit_hash(self):
        self.assertRegex(PINNED_REVISION, r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
