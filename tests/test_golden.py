"""The bundled demo, byte for byte.

Every other test in this directory says *why* a payload looks the way it does.
This one says only that it has not changed — which is the one thing a large
refactor cannot check by reading, and the reason `spec/golden/` exists.

A failure here is not automatically a bug. It is a change to something an agent
reads, and the question it asks is whether that change was intended. If it was,
regenerate deliberately::

    .venv/bin/python tests/golden.py --update

and the diff on `spec/golden/` is the review.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import golden  # noqa: E402


class GoldenTests(unittest.TestCase):
    maxDiff = None

    def test_every_golden_file_still_has_a_producer(self) -> None:
        """A file nobody writes any more is a hole in the net, not a pass."""

        on_disk = {path.name for path in golden.GOLDEN.iterdir() if path.is_file()}
        self.assertEqual(on_disk, set(golden.capture()))

    def test_the_demo_says_exactly_what_it_said_before(self) -> None:
        for name, produced in golden.capture().items():
            with self.subTest(golden=name):
                recorded = (golden.GOLDEN / name).read_text(encoding="utf-8")
                self.assertEqual(
                    recorded,
                    produced,
                    f"{name} changed. If that was intended, regenerate with "
                    "`python tests/golden.py --update` and review the diff.",
                )


if __name__ == "__main__":
    unittest.main()
