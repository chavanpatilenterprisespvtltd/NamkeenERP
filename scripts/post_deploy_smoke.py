#!/usr/bin/env python3
# FILE PATH: scripts/post_deploy_smoke.py
# ─── Post-Deploy Smoke v2.0 (Session CS2 — real HTTP checks instead of hard-coded PASS lines) ─
#
# [Session CS2] FIX — THE SMOKE TEST PRINTED "PASS" FOR 10 CHECKS WITHOUT CHECKING ANYTHING.
# Confirmed this session by reading the previous version: a loop printed f'PASS {c}' for a fixed
# list and `failed` was never appended to, so it could not fail.
# ROOT CAUSE: placeholder left in since V90.bh.
# THE FIX: calls the running API (API_BASE_URL, default http://127.0.0.1:8000):
#   /health (status ok), /ready (database ready), /version (release and schema target match
#   config/release_manifest.json), and /auth/me without a token must return 401.
# Optional --wait N retries /health for N seconds while containers start. Exit code 1 on any failure.
# NOT touched: deploy.sh flow. Stdlib only (no new dependency).
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def get(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.getenv("API_BASE_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--wait", type=int, default=0)
    a = ap.parse_args()
    base = a.base_url.rstrip("/")
    manifest = json.loads((ROOT / "config/release_manifest.json").read_text(encoding="utf-8"))
    deadline = time.time() + a.wait
    while True:
        try:
            code, body = get(base + "/health")
            break
        except (urllib.error.URLError, OSError):
            if time.time() >= deadline:
                print(f"FAIL health: API not reachable at {base}")
                return 1
            time.sleep(3)
    failed: list[str] = []
    def check(name: str, ok: bool, detail: str = "") -> None:
        print(("PASS " if ok else "FAIL ") + name + (f" ({detail})" if detail else ""))
        if not ok:
            failed.append(name)
    check("health", code == 200 and body.get("status") == "ok", str(body))
    code, body = get(base + "/ready")
    check("readiness/database", code == 200 and body.get("status") == "ready", str(body))
    code, body = get(base + "/version")
    check("release version", body.get("version") == manifest["release"], f"api={body.get('version')} manifest={manifest['release']}")
    check("schema target", int(body.get("schema_target") or 0) == int(manifest["schema_target"]), f"api={body.get('schema_target')}")
    code, _ = get(base + "/auth/me")
    check("authentication required", code == 401, f"HTTP {code}")
    total = 5
    print(f"{total - len(failed)}/{total} post-deploy smoke checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
