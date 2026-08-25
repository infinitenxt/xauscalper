"""Deployment frontend environment contract.

Static-file checks (no live server needed): frontend/.env exists with a safe
relative /api value and frontend/package.json exposes a `start` script. The
actual production build is exercised separately (see test report) since it
is a multi-second build step, not a per-test HTTP assertion.
"""

import json
import os

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")


def test_frontend_env_has_safe_relative_api_base():
    env_path = os.path.join(FRONTEND_DIR, ".env")
    assert os.path.isfile(env_path), f".env missing at {env_path}"
    content = open(env_path).read()
    assert "VITE_API_BASE" in content, f"VITE_API_BASE not set in {content!r}"
    value = [
        line.split("=", 1)[1].strip()
        for line in content.splitlines()
        if line.startswith("VITE_API_BASE")
    ][0]
    assert value == "/api", f"expected a safe relative '/api' value, got {value!r}"
    assert "://" not in value, f"VITE_API_BASE must be relative, got {value!r}"


def test_frontend_package_json_exposes_start_script():
    pkg_path = os.path.join(FRONTEND_DIR, "package.json")
    assert os.path.isfile(pkg_path), f"package.json missing at {pkg_path}"
    with open(pkg_path) as f:
        pkg = json.load(f)
    scripts = pkg.get("scripts", {})
    assert "start" in scripts, f"no 'start' script in package.json scripts: {scripts}"
    assert scripts["start"], "start script is empty"
