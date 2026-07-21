#!/usr/bin/env bash
# Prepare a clean, history-free "deploy" branch for the public GitHub repo.
#
# Why: branches `main`/`va` carry personal portfolio .db files in their
# history. The public repo must contain ONLY the current working state.
# This builds an orphan branch (no history) and STOPS before pushing —
# you run the printed push command yourself (outward-facing action).
#
# Usage:   ./deploy.sh
set -euo pipefail
cd "$(dirname "$0")"

REMOTE_URL="https://github.com/SadSlicer/gpcp-dashboard.git"
SRC_BRANCH="saas"
DEPLOY_BRANCH="deploy"

echo "▶ Safety check: no sensitive files tracked…"
if git ls-files | grep -iE 'portfolios/.*\.db|portfolios/_registry\.json|\.streamlit/secrets\.toml|^\.env$'; then
  echo "❌ ABORT: a sensitive file is tracked (above). Fix .gitignore / git rm --cached first."
  exit 1
fi
echo "  ✅ clean"

CURRENT="$(git rev-parse --abbrev-ref HEAD)"
if [ "$CURRENT" != "$SRC_BRANCH" ]; then
  echo "⚠️  You are on '$CURRENT', not '$SRC_BRANCH'. Checkout saas first."
  exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
  echo "⚠️  Working tree not clean — commit or stash on '$SRC_BRANCH' first."
  git status --short
  exit 1
fi

echo "▶ Building orphan branch '$DEPLOY_BRANCH' from current state of '$SRC_BRANCH'…"
git branch -D "$DEPLOY_BRANCH" 2>/dev/null || true
git checkout --orphan "$DEPLOY_BRANCH"
git rm -rf --cached portfolios >/dev/null 2>&1 || true   # double safety
git add -A
git commit -q -m "Public deploy ($(date +%Y-%m-%d))"
echo "  ✅ orphan commit created (no history)"

echo "▶ Ensuring 'origin' remote…"
if ! git remote get-url origin >/dev/null 2>&1; then
  git remote add origin "$REMOTE_URL"
  echo "  added origin → $REMOTE_URL"
else
  echo "  origin already set → $(git remote get-url origin)"
fi

cat <<EOF

────────────────────────────────────────────────────────────
✅ Ready. Review, then PUSH YOURSELF (force replaces remote main):

    git push -f origin ${DEPLOY_BRANCH}:main

Then return to development:

    git checkout ${SRC_BRANCH}

(The push is left to you — it publishes to a public repo.)
────────────────────────────────────────────────────────────
EOF
