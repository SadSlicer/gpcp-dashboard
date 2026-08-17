#!/usr/bin/env bash
#
# One-command deploy prep for the GPCP SaaS dashboard.   →   ./SAAS/deploy.sh
#
# Every step below is LOCAL. The actual `git push` is only PRINTED for you to
# run yourself, because the assistant's auto-mode classifier blocks pushing a
# repo tree to the public remote.
#
# Why this script exists:
#  • The public repo's `main` is a single orphan commit rebuilt from `saas` on
#    every deploy. A manual deploy would REVERT any ETF-composition auto-refresh
#    unless the refresh is folded into the deploy itself — step 1 does exactly
#    that, so compositions stay current without depending on the monthly GitHub
#    Action (which the orphan model fights, and which has never reliably run).
#  • The deploy commit is built with `git commit-tree` straight from the `saas`
#    tree, so the working tree is NEVER touched — earlier `checkout --orphan` +
#    `git add -A` would sweep up untracked files (it once silently deleted
#    SAAS/HANDOFF.md). Only files COMMITTED to `saas` are deployed.
#
set -euo pipefail
cd "$(dirname "$0")/.."

REPO_URL="https://github.com/SadSlicer/gpcp-dashboard.git"

branch="$(git rev-parse --abbrev-ref HEAD)"
if [ "$branch" != "saas" ]; then
  echo "✗ Run this from the 'saas' branch (currently on '$branch')."; exit 1
fi

echo "→ [1/6] Refreshing ETF compositions from live factsheets (best-effort)…"
if [ -x .venv/bin/python ]; then
  .venv/bin/python monthly_compositions_update.py \
    || echo "  (refresh failed — keeping the committed compositions)"
else
  echo "  (.venv missing — skipping refresh)"
fi

echo "→ [2/6] Committing composition changes (if any)…"
if git diff --quiet -- etf_compositions.json; then
  echo "  no change."
else
  git add etf_compositions.json
  git commit -q -m "saas: refresh ETF compositions ($(date -u +%Y-%m-%d))"
  echo "  committed."
fi

echo "→ [3/6] Building orphan 'deploy' from the 'saas' tree (working tree untouched)…"
tree="$(git rev-parse 'saas^{tree}')"
commit="$(git -c user.name='SadSlicer' \
              -c user.email='SadSlicer@users.noreply.github.com' \
              commit-tree "$tree" -m 'GPCP Dashboard — public deploy')"
git branch -f deploy "$commit" >/dev/null
echo "  built $(git rev-parse --short deploy)."

echo "→ [4/6] Checking the bundle for secrets/data…"
if git ls-tree -r --name-only deploy \
     | grep -iE '\.xlsm|\.xlsx|\.db$|secrets|\.env|_registry\.json'; then
  echo "✗ ABORT: a secret/data file is in the deploy bundle (listed above)."; exit 1
fi
echo "  clean."

echo "→ [5/6] Saving current live version into 'rollback'…"
if git fetch "$REPO_URL" "+main:rollback" 2>/dev/null; then
  echo "  rollback = $(git rev-parse --short rollback)."
else
  echo "  (could not fetch live main — rollback unchanged)"
fi

echo ""
echo "→ [6/6] Ready. Push with your GitHub PAT (token scopes: repo + workflow):"
echo ""
echo "  git push -f \"https://SadSlicer:<TOKEN>@github.com/SadSlicer/gpcp-dashboard.git\" deploy:main"
echo ""
echo "Then on Streamlit Cloud:  Manage app → ⋮ → Reboot app,  then Cmd+Shift+R."
