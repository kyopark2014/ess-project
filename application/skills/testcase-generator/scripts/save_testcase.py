#!/usr/bin/env python3
"""Persist a generated test-case xlsx into ``ess/test_cases/``.

Copies the workbook (and optional cases JSON) from the draft/artifacts location
into ``{SESSION_STORAGE}/{user}/ess/test_cases/`` and upserts
``test_cases_list.json`` (same shape as ``project_list.json``).

Usage (from application/):
    python skills/testcase-generator/scripts/save_testcase.py \\
        --xlsx /path/to/artifacts/tc/NFPA855_2023_testcase.xlsx \\
        --cases /path/to/artifacts/tc/NFPA855_2023_cases.json \\
        --user ksdyb
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def _application_dir() -> Path:
    # .../application/skills/testcase-generator/scripts/this.py
    return Path(__file__).resolve().parents[3]


def _ensure_app_on_path() -> None:
    app = str(_application_dir())
    if app not in sys.path:
        sys.path.insert(0, app)


def _safe_user(user_id: str | None) -> str:
    raw = (user_id or "").strip() or "default"
    return (
        raw.replace("/", "_").replace("\\", "_").replace("..", "_")[:128] or "default"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Save generated test-case xlsx into ess/test_cases + test_cases_list.json"
    )
    parser.add_argument("--xlsx", required=True, help="Path to generated .xlsx")
    parser.add_argument(
        "--cases",
        default=None,
        help="Optional cases JSON to store as {stem}.json sidecar",
    )
    parser.add_argument("--user", default=None, help="User id (session segment)")
    parser.add_argument(
        "--filename",
        default=None,
        help="Destination basename under ess/test_cases (default: xlsx basename)",
    )
    parser.add_argument("--title", default=None, help="Optional title metadata")
    parser.add_argument("--standard", default=None, help="Optional standard metadata")
    parser.add_argument("--source-md", default=None, help="Optional source md path")
    parser.add_argument("--rows", type=int, default=None, help="Optional row count")
    args = parser.parse_args()

    xlsx = Path(os.path.expanduser(args.xlsx)).resolve()
    if not xlsx.is_file():
        print(json.dumps({"ok": False, "error": f"xlsx not found: {xlsx}"}))
        return 1

    cases_path = None
    if args.cases:
        cases_path = Path(os.path.expanduser(args.cases)).resolve()
        if not cases_path.is_file():
            print(
                json.dumps(
                    {"ok": False, "error": f"cases file not found: {cases_path}"}
                )
            )
            return 1

    _ensure_app_on_path()
    try:
        import utils
    except ImportError as exc:
        print(json.dumps({"ok": False, "error": f"utils import failed: {exc}"}))
        return 1

    user_id = _safe_user(
        args.user
        or os.environ.get("ESS_USER_ID")
        or os.environ.get("USER_ID")
    )

    try:
        result = utils.save_ess_testcase(
            str(xlsx),
            user_id=user_id,
            cases_json_path=str(cases_path) if cases_path else None,
            title=args.title,
            standard=args.standard,
            source_md=args.source_md,
            rows=args.rows,
            filename=args.filename,
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    out: dict[str, Any] = {"ok": True, "user_id": user_id, **result}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
