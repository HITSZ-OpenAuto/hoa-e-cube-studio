#!/usr/bin/env bash
# 从资料栈同步 → 提交 → 推送，并（可选）触发 hoa.moe 站点重建。
#
# 需在校园网环境下运行（资料栈地址 10.249.44.116 为校内网）。
#
#   ALIST_USERNAME=<账号> ALIST_PASSWORD=<密码> ./scripts/sync-and-push.sh
#
# 可选环境变量：
#   SITE_REPO   站点仓库（如 HITSZ-OpenAuto/hoa-fuma），配置后同步完立即触发站点构建
#   SITE_WORKFLOW  站点构建工作流名（默认 build.yml）

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

echo "==> 同步资料栈"
python3 scripts/sync-alist.py --repo "$repo_root"

echo "==> 提交变更"
git add -A
if git diff --staged --quiet; then
  echo "没有变更，跳过提交"
else
  git commit -m "chore: 同步资料栈内容"
  if git push origin HEAD:main; then
    echo "==> 已推送到 main，worktree 分支将由 GitHub Actions 自动更新"
  elif command -v gh >/dev/null 2>&1; then
    echo "==> 直接推送 main 受分支规则限制，改用 sync/alist 分支创建并合入 PR…"
    git push --force origin HEAD:refs/heads/sync/alist
    pr_url="$(gh pr list --base main --head sync/alist --state open --json url --jq '.[0].url')"
    if [ -z "$pr_url" ]; then
      pr_url="$(gh pr create --base main --head sync/alist --title 'chore: 同步资料栈内容' --body '从校内资料栈同步更新内容。')"
    fi
    gh pr merge "$pr_url" --squash --delete-branch
    git fetch origin main
    git reset --hard origin/main
    echo "==> PR 已合入 main，worktree 分支将由 GitHub Actions 自动更新"
  else
    echo "错误：直接推送 main 被拒绝，且未安装 gh CLI 无法自动创建 PR。" >&2
    exit 1
  fi
fi

if [ -n "${SITE_REPO:-}" ] && command -v gh >/dev/null 2>&1; then
  workflow="${SITE_WORKFLOW:-build.yml}"
  echo "==> 触发站点构建 ${SITE_REPO} (${workflow})"
  gh workflow run "$workflow" --repo "$SITE_REPO" --ref main
fi
