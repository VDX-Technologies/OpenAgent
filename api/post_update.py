"""
Post-update steps
=================
Run by the updater with the *new* release's code right after it is installed
(``python -m api.post_update``), and safe to run again at any time. Put here
anything a release needs beyond new files and Python/UI dependencies, so users
never have to reinstall the app.

Each step must be idempotent; a failing step is reported but doesn't undo the
update (the app also re-checks the bundle on every start).
"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


def _bundle() -> str:
    from api import bundle

    return bundle.refresh()


STEPS = [("app bundle", _bundle)]


def main() -> int:
    failed = 0
    for name, step in STEPS:
        try:
            print(f"{name}: {step()}")
        except Exception as exc:  # report and keep going
            failed += 1
            print(f"{name}: failed — {exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
