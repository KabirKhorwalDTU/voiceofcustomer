#!/usr/bin/env python3
import argparse
import json
import sys
import time
from urllib import request
from urllib.error import HTTPError, URLError


def fetch_json(url, method="GET", body=None, timeout=30):
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = request.Request(url, data=data, headers=headers, method=method)
    with request.urlopen(req, timeout=timeout) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def fetch_status(url, timeout=30):
    req = request.Request(url, method="GET")
    with request.urlopen(req, timeout=timeout) as response:
        return response.status, response.read()


def main():
    parser = argparse.ArgumentParser(description="Smoke-test the deployed Voice of Customer platform.")
    parser.add_argument("--api", required=True, help="Base URL of the deployed FastAPI backend.")
    parser.add_argument("--frontend", required=True, help="Base URL of the deployed Vercel frontend.")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args()

    api = args.api.rstrip("/")
    frontend = args.frontend.rstrip("/")

    checks = []

    status, health = fetch_json(f"{api}/health")
    checks.append(("backend health", status == 200 and health.get("ok") is True))

    status, settings = fetch_json(f"{api}/api/settings")
    checks.append(("settings", status == 200 and settings.get("batch_size") == 25))

    _, created = fetch_json(
        f"{api}/api/runs",
        method="POST",
        body={
            "name": "Smoke Pay",
            "play_link": "https://play.google.com/store/apps/details?id=com.smoke.pay",
            "app_store_link": "https://apps.apple.com/in/app/smoke-pay/id987654321",
            "website": "https://www.smokepay.example",
        },
    )
    run_id = created["run"]["id"]

    deadline = time.time() + args.timeout_seconds
    terminal = None
    while time.time() < deadline:
        _, run = fetch_json(f"{api}/api/runs/{run_id}")
        if run["status"] in {"done", "partial", "failed"}:
            terminal = run
            break
        time.sleep(5)
    checks.append(("run reached terminal state", terminal is not None))
    checks.append(("run did not fail wholesale", terminal is not None and terminal["status"] in {"done", "partial"}))

    status, results = fetch_json(f"{api}/api/runs/{run_id}/results")
    checks.append(("results", status == 200 and results["run"]["id"] == run_id))

    for fmt in ("csv", "json", "xlsx"):
        status, body = fetch_status(f"{api}/api/runs/{run_id}/downloads/{fmt}")
        checks.append((f"{fmt} download", status == 200 and len(body) > 0))

    status, html = fetch_status(frontend)
    checks.append(("frontend", status == 200 and b"Voice of Customer AI Agent" in html))

    failed = [name for name, ok in checks if not ok]
    print(json.dumps({"checks": [{"name": name, "ok": ok} for name, ok in checks], "run_id": run_id}, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (HTTPError, URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        raise SystemExit(1)

