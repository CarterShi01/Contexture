"""`python -m contexture.cli`, which the tests use and a developer may.

A package needs this where a module got it for free from
`if __name__ == "__main__"`. The console script named in `pyproject.toml`
reaches `main` directly and never comes through here.
"""

from __future__ import annotations

from .main import main

raise SystemExit(main())
