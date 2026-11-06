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
  git push origin main
  echo "==> 已推送到 main，worktree 分支将由 GitHub Actions 自动更新"
fi

if [ -n "${SITE_REPO:-}" ] && command -v gh >/dev/null 2>&1; then
  workflow="${SITE_WORKFLOW:-build.yml}"
  echo "==> 触发站点构建 ${SITE_REPO} (${workflow})"
  gh workflow run "$workflow" --repo "$SITE_REPO" --ref main
fi
