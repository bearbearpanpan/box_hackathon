#!/usr/bin/env bash
#
# One-time setup: point git at the repo's tracked hooks directory so the
# pre-commit SBOM refresh runs on every commit.
#
# Usage:
#   ./scripts/install-hooks.sh
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

git config core.hooksPath .githooks
chmod +x .githooks/* 2>/dev/null || true

echo "Installed git hooks (core.hooksPath -> .githooks)."
echo "The SBOM will now be regenerated and staged on every commit."
