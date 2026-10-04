#!/usr/bin/env bash
set -euo pipefail

# Render's Python native runtime includes Node and npm for this frontend build.
export NEXT_TELEMETRY_DISABLED=1
python -m pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.lock.txt
cd frontend
npm exec --yes --package=pnpm@11.25.0 -- pnpm install --frozen-lockfile
npm exec --yes --package=pnpm@11.25.0 -- pnpm run typecheck
npm exec --yes --package=pnpm@11.25.0 -- pnpm run build
test -f out/index.html
