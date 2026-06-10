#!/usr/bin/env python3
from pathlib import Path
import json
import os
import sys


ROOT = Path(__file__).resolve().parents[1]


REQUIRED_FILES = [
    ".env.example",
    ".env.production.example",
    "render.yaml",
    "backend/Dockerfile",
    "data/supabase/schema.sql",
    "docs/DEPLOYMENT.md",
    "scripts/cloud_smoke.py",
    "scripts/create_render_backend.py",
    "scripts/finalize_cloud_deploy.sh",
    "scripts/set_vercel_api_url.sh",
    ".github/workflows/ci.yml",
    ".github/workflows/render-backend.yml",
    ".github/workflows/vercel-frontend.yml",
    "frontend/vercel.json",
]


REQUIRED_RENDER_STRINGS = [
    "rootDir: backend",
    "healthCheckPath: /health",
    "ALLOW_DEV_LLM_FALLBACK",
    'value: "false"',
    "ALLOW_DEV_INGESTION_FALLBACK",
]


REQUIRED_SCHEMA_STRINGS = [
    "create table if not exists companies",
    "create table if not exists runs",
    "create table if not exists reviews",
    "create table if not exists themes",
    "create table if not exists settings",
    "reviews_run_hash_unique",
]


def fail(message: str) -> None:
    print(json.dumps({"ok": False, "error": message}, indent=2))
    raise SystemExit(1)


def main() -> int:
    for relative in REQUIRED_FILES:
        path = ROOT / relative
        if not path.exists():
            fail(f"Missing required deploy artifact: {relative}")

    render_yaml = (ROOT / "render.yaml").read_text()
    for marker in REQUIRED_RENDER_STRINGS:
        if marker not in render_yaml:
            fail(f"render.yaml missing marker: {marker}")

    schema = (ROOT / "data/supabase/schema.sql").read_text().lower()
    for marker in REQUIRED_SCHEMA_STRINGS:
        if marker not in schema:
            fail(f"schema missing marker: {marker}")

    for relative in (
        "scripts/cloud_smoke.py",
        "scripts/create_render_backend.py",
        "scripts/finalize_cloud_deploy.sh",
        "scripts/set_vercel_api_url.sh",
    ):
        if not os.access(ROOT / relative, os.X_OK):
            fail(f"Script is not executable: {relative}")

    prod_env = (ROOT / ".env.production.example").read_text()
    for key in ("DATABASE_URL", "APIFY_TOKEN", "GEMINI_API_KEY", "BACKEND_CORS_ORIGINS", "VITE_API_BASE_URL"):
        if key not in prod_env:
            fail(f".env.production.example missing key: {key}")

    print(json.dumps({"ok": True, "checked_files": len(REQUIRED_FILES)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
