"""Read-only acceptance of the frozen beta artifacts."""

import json
import unittest

from macfit import PROJECT_ROOT, __version__, FROZEN_RESULTS
from macfit.settings import PROFILES
from macfit.verification import verify_model


class ReleaseTests(unittest.TestCase):
    def test_frozen_artifacts(self):
        for name, profile in PROFILES.items():
            with self.subTest(model=name):
                folder = FROZEN_RESULTS / profile["output_folder"]
                self.assertTrue(folder.is_dir(), "Frozen beta results are missing")
                result = verify_model(folder)
                self.assertTrue(result["three_dimensional_roundtrip"])
                report = json.loads((folder / "optimized_report.json").read_text(encoding="utf-8"))
                self.assertEqual(report["source_sha256"], profile["source_sha256"])
                self.assertEqual(report["version"], __version__)
                expected = "bezier7" if name == "mini" else "previous"
                self.assertEqual(report["selected_model"], expected)
                ceiling = 0.032 if name == "mini" else 0.148
                self.assertLess(report["model"]["test"]["rms_mm"], ceiling)


if __name__ == "__main__":
    unittest.main()
