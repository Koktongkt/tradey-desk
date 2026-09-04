#!/usr/bin/env python3
"""Verify a built public dashboard before committing/publishing it.

Checks a build output directory that contains a sanitized static dashboard
(index.html + dashboard.json, the shape Tradey Desk's public_dashboard.py emits).
Validates JSON, extracts and (if node is present) syntax-checks the inline
<script> block, and scans both files for the classes of private content that
must never reach a public repo.

Usage:  python3 verify_public_dashboard.py [DIR]     (default: ./public)

Exit code 0 = clean; 1 = a check failed. Prints PASS lines per check.
"""
from __future__ import annotations
import json
import pathlib
import re
import subprocess
import sys

BLOCKED_TERMS = [
    # account / broker identifiers and secrets
    "broker_order_id", "account_id", "account_number", "client_order_id",
    "ALPACA_API_KEY", "ALPACA_SECRET_KEY", "GITHUB_TOKEN",
    # private review / research content
    "private_prompt", "private review", "dossier_hash", "thesis", "sources",
    # absolute filesystem paths that reveal repo layout
    "/opt/data/", "/home/", "C:\\",
    # the trading account's GitHub/login handle (leaks owner identity)
    "Koktongkt",
]
AWS_KEY_RE = re.compile(r"AKIA[0-9A-Z]{16}")
IDENT_RE = re.compile(r"\b\d{17,19}\b")  # 18-digit account IDs


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def main() -> int:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "public")
    files = [p for p in root.iterdir() if p.is_file()]
    if not files:
        print(f"FAIL  no files in {root}")
        return 1

    blob = "\n".join(p.read_text(errors="ignore") for p in files)
    ok = True

    # 1. dashboard.json is valid JSON and carries expected top-level keys.
    json_path = root / "dashboard.json"
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            ok &= check("dashboard.json parses as valid JSON", True)
            # The redesigned desk exposes desk_status + outcome_horizons;
            # requiring them catches a stale/old-shape artifact.
            ok &= check("dashboard.json is the new desk shape",
                        {"desk_status", "outcome_horizons"} <= set(data),
                        ",".join(sorted(data.keys())))
        except json.JSONDecodeError as e:
            ok &= check("dashboard.json parses as valid JSON", False, str(e))

    # 2. Inline JS in index.html is extractable and (when node exists) valid.
    html = (root / "index.html").read_text(encoding="utf-8", errors="ignore")
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    ok &= check("index.html has an inline <script> block", bool(scripts))
    if scripts:
        tmp = pathlib.Path("/tmp/_dashboard_check.js")
        tmp.write_text(scripts[0], encoding="utf-8")
        if shutil_which("node"):
            proc = subprocess.run(["node", "--check", str(tmp)],
                                  capture_output=True, text=True)
            ok &= check("inline JS passes node --check", proc.returncode == 0,
                        proc.stderr.strip()[:200])
        else:
            print("SKIP  node not installed; skipped inline JS syntax check")

    # 3. Sanitization: no private content reaches the public artifact.
    leaked = [t for t in BLOCKED_TERMS if t in blob]
    ok &= check("no blocked private terms", not leaked, ",".join(leaked))
    aws = AWS_KEY_RE.search(blob)
    ok &= check("no AWS-style keys", aws is None, aws.group(0) if aws else "")
    ident = IDENT_RE.search(blob)
    ok &= check("no 18-digit account IDs", ident is None,
                ident.group(0) if ident else "")

    print("PUBLIC_REPO_SCAN_OK" if ok else "PUBLIC_REPO_SCAN_FAILED")
    return 0 if ok else 1


def shutil_which(name: str) -> str | None:
    import shutil
    return shutil.which(name)


if __name__ == "__main__":
    raise SystemExit(main())
