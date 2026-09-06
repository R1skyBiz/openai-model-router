"""Validate local evaluation case files without provider credentials."""

from __future__ import annotations

import json
from pathlib import Path


CASES_DIR = Path(__file__).parent / "cases"


def validate_cases() -> int:
    """Parse every non-empty JSONL row and return the number of cases."""
    case_count = 0
    for path in sorted(CASES_DIR.glob("*.jsonl")):
        with path.open(encoding="utf-8") as case_file:
            for line_number, line in enumerate(case_file, start=1):
                if not line.strip():
                    continue
                try:
                    json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"{path}:{line_number}: {error.msg}") from error
                case_count += 1
    return case_count


if __name__ == "__main__":
    total = validate_cases()
    print(f"Validated {total} evaluation cases.")
