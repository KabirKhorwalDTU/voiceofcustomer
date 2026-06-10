#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${VITE_API_BASE_URL:-}" ]]; then
  echo "Set VITE_API_BASE_URL to the deployed Render backend URL." >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"

cd "$FRONTEND_DIR"

npx vercel env rm VITE_API_BASE_URL production --yes >/dev/null 2>&1 || true
printf "%s" "$VITE_API_BASE_URL" | npx vercel env add VITE_API_BASE_URL production
npx vercel deploy --prod --yes
