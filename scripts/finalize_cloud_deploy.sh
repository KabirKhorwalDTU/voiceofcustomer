#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${VITE_API_BASE_URL:-}" ]]; then
  echo "Set VITE_API_BASE_URL to the deployed Render backend URL." >&2
  exit 1
fi

FRONTEND_URL="${FRONTEND_URL:-https://frontend-eight-sandy-65.vercel.app}"
HEALTH_URL="${VITE_API_BASE_URL%/}/health"

if [[ -n "${RENDER_DEPLOY_HOOK_URL:-}" ]]; then
  curl --fail-with-body --request POST "$RENDER_DEPLOY_HOOK_URL" >/dev/null
elif [[ -n "${RENDER_API_KEY:-}" && -n "${RENDER_SERVICE_ID:-}" ]]; then
  curl --fail-with-body \
    --request POST \
    --url "https://api.render.com/v1/services/${RENDER_SERVICE_ID}/deploys" \
    --header "accept: application/json" \
    --header "authorization: Bearer ${RENDER_API_KEY}" \
    --header "content-type: application/json" \
    --data '{"clearCache":"do_not_clear"}' >/dev/null
else
  echo "No Render deploy trigger configured; will verify the backend URL as-is." >&2
fi

echo "Waiting for backend health at $HEALTH_URL"
for _ in $(seq 1 90); do
  if curl --silent --fail "$HEALTH_URL" >/dev/null; then
    echo "Backend health check passed."
    ./scripts/set_vercel_api_url.sh
    python3 scripts/cloud_smoke.py --api "$VITE_API_BASE_URL" --frontend "$FRONTEND_URL"
    exit 0
  fi
  sleep 10
done

echo "Backend did not become healthy before timeout." >&2
exit 1
