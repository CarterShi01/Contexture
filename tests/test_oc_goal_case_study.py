"""Keep the real oc-goal migration sample on the supported application path."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
CASE_STUDY = ROOT / "docs" / "case-studies" / "oc-goal"


class OcGoalCaseStudyTests(unittest.TestCase):
    def test_the_real_domain_passes_through_the_production_binding(self) -> None:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(None, (str(ROOT), environment.get("PYTHONPATH")))
        )
        result = subprocess.run(
            [sys.executable, "check.py"],
            cwd=CASE_STUDY,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("schemas, resources, reads, writes, and CAS pass", result.stdout)


if __name__ == "__main__":
    unittest.main()
