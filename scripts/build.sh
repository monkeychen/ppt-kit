#!/usr/bin/env bash
# Convenient packaging shortcut for macOS / Linux.
# Usage:
#   ./scripts/build.sh          # Default: build standalone binary
#   ./scripts/build.sh wheel    # Build wheel and sdist
#   ./scripts/build.sh all      # Build both
#   ./scripts/build.sh --clean  # Clean dist/ and build/ first

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"
exec uv run python scripts/build.py "$@"
