"""Read the disclosure text from a source checkout, without installing.

The inspector itself lives in the package, at `contexture.inspection`, and is
reachable as `contexture inspect` wherever the package is installed. That is
deliberate: the person who most needs to read their own disclosure text is
whoever just wrote a Role against this framework, and a script under `tools/`
would not ship to them.

This file is the checkout-local door to the same command, for the same reason
`run_tests.py` sits at the root — so working on the framework never requires
installing it first.

It defaults to the bundled reference application, because this repository is
the framework and has no `[tool.contexture]` project of its own to inspect.
Pass `--target package.module:RoleClass` to point it at another one.

**Not named `inspect.py`.** Running a script puts its own directory first on
`sys.path`, so a file by that name here shadows the standard library's
`inspect` — which `dataclasses` imports, which is to say everything imports.
The failure is a circular-import error from inside the standard library and
names nothing that would point back at this file.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from contexture.cli import DEMO_TARGET, main  # noqa: E402  (after sys.path)


def _with_default_target(arguments: list[str]) -> list[str]:
    named = any(
        argument == "--target" or argument.startswith("--target=")
        for argument in arguments
    )
    return arguments if named else ["--target", DEMO_TARGET, *arguments]


if __name__ == "__main__":
    raise SystemExit(main(["inspect", *_with_default_target(sys.argv[1:])]))
