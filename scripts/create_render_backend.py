#!/usr/bin/env python3
import json
import os
import sys
from typing import Dict, List, Optional
from urllib import request
from urllib.error import HTTPError, URLError


API_BASE = "https://api.render.com/v1"
DEFAULT_SERVICE_NAME = "voc-ai-agent-api"
DEFAULT_FRONTEND_URL = "https://frontend-eight-sandy-65.vercel.app"


def env(name: str, required: bool = True, default: str = "") -> str:
    value = os.environ.get(name, default).strip()
    if required and not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def render_request(path: str, method: str = "GET", body: Optional[Dict] = None) -> Dict:
    token = env("RENDER_API_KEY")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = request.Request(
        f"{API_BASE}{path}",
        data=data,
        method=method,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def required_env_vars() -> List[Dict[str, str]]:
    cors = env("BACKEND_CORS_ORIGINS", required=False, default=DEFAULT_FRONTEND_URL)
    values = {
        "DATABASE_URL": env("DATABASE_URL"),
        "APIFY_TOKEN": env("APIFY_TOKEN"),
        "GEMINI_API_KEY": env("GEMINI_API_KEY"),
        "DEEPSEEK_API_KEY": env("DEEPSEEK_API_KEY", required=False),
        "PYTHON_VERSION": env("PYTHON_VERSION", required=False, default="3.11.11"),
        "ALLOW_DEV_LLM_FALLBACK": "false",
        "ALLOW_DEV_INGESTION_FALLBACK": "false",
        "BACKEND_CORS_ORIGINS": cors,
    }
    return [{"key": key, "value": value} for key, value in values.items()]


def create_payload() -> Dict:
    repo = env("RENDER_REPO_URL")
    branch = env("RENDER_BRANCH", required=False, default="main")
    service_name = env("RENDER_SERVICE_NAME", required=False, default=DEFAULT_SERVICE_NAME)
    owner_id = env("RENDER_OWNER_ID")
    region = env("RENDER_REGION", required=False, default="singapore")
    plan = env("RENDER_PLAN", required=False, default="starter")
    auto_deploy = env("RENDER_AUTO_DEPLOY", required=False, default="yes").lower() in {"1", "true", "yes"}
    return {
        "type": "web_service",
        "name": service_name,
        "ownerId": owner_id,
        "repo": repo,
        "branch": branch,
        "rootDir": "backend",
        "autoDeploy": "yes" if auto_deploy else "no",
        "envVars": required_env_vars(),
        "serviceDetails": {
            "runtime": "python",
            "plan": plan,
            "region": region,
            "healthCheckPath": "/health",
            "envSpecificDetails": {
                "buildCommand": "pip install -r requirements.txt",
                "startCommand": "uvicorn app.main:app --host 0.0.0.0 --port $PORT",
            },
        },
    }


def main() -> int:
    dry_run = os.environ.get("DRY_RUN", "").lower() in {"1", "true", "yes"}
    payload = create_payload()
    if dry_run:
        redacted = json.loads(json.dumps(payload))
        for item in redacted["envVars"]:
            if item["key"] not in {"ALLOW_DEV_LLM_FALLBACK", "ALLOW_DEV_INGESTION_FALLBACK", "BACKEND_CORS_ORIGINS"}:
                item["value"] = "***"
        print(json.dumps({"dry_run": True, "payload": redacted}, indent=2))
        return 0

    response = render_request("/services", method="POST", body=payload)
    service = response.get("service", {})
    output = {
        "service_id": service.get("id"),
        "service_name": service.get("name"),
        "service_url": service.get("serviceDetails", {}).get("url"),
        "deploy_id": response.get("deployId"),
    }
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        raise SystemExit(1)
