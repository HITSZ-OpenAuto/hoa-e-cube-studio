#!/usr/bin/env python3
"""重新生成 `worktree` 分支上的 worktree.json。

站点（hoa.moe）通过该分支的文件清单渲染资料树，格式与课程仓一致：

    {
      "<路径>": { "size": 1234, "time": 1700000000, "hash": "<commit sha>" }
    }

实现与 HITSZ-OpenAuto/repos-management 的 scripts/generate_worktree_info.py 同构，
区别在于本脚本不自行 push，由调用方决定（本地校验或 CI 中推送）。

用法：

    python3 scripts/update-worktree.py [--push] [--branch worktree]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

COMMIT_HASH_PATTERN = re.compile(rb"<\|([0-9a-z]+)\|>")


def run(args: list[str], cwd: str | None = None) -> bytes:
    result = subprocess.run(args, check=True, capture_output=True, cwd=cwd)
    return result.stdout.strip()


def collect_files() -> tuple[str, dict]:
    """收集 HEAD 提交里每个文件的大小、最后修改时间与提交哈希。"""
    head = run(["git", "rev-parse", "HEAD"]).decode("ascii")

    files: dict[str, dict] = {}

    # core.quotepath=false：路径保持原始 UTF-8，不转义成 \xxx
    listing = run(
        ["git", "-c", "core.quotepath=false", "ls-tree", "-r", "-l", "HEAD"]
    ).decode("utf-8", "replace")
    for line in listing.splitlines():
        match = re.match(r"^\d+ \w+ ([0-9a-f]+)\s+(\d+|-)\t(.+)$", line)
        if not match:
            continue
        _, size, path = match.groups()
        files[path] = {"size": int(size) if size != "-" else 0}

    # 单次 git log 遍历，按「新→旧」为每个文件补上最后一次改动它的提交
    history = run(
        [
            "git",
            "-c",
            "core.quotepath=false",
            "log",
            "--format=COMMIT%x00%ct%x00%H",
            "--name-only",
            "--no-renames",
        ]
    )

    commit = ""
    timestamp = 0
    for raw_line in history.splitlines():
        line = raw_line.decode("utf-8", "replace")
        if line.startswith("COMMIT\x00"):
            _, raw_time, raw_hash = line.split("\x00")
            commit = raw_hash
            timestamp = int(raw_time)
            continue
        if not line or not commit:
            continue
        entry = files.get(line)
        if entry is None or "time" in entry:
            continue
        entry["time"] = timestamp
        entry["hash"] = commit

    for entry in files.values():
        entry.setdefault("time", 0)
        entry.setdefault("hash", "")

    return head, files


def previous_target(branch: str) -> str | None:
    try:
        message = run(
            ["git", "log", "-1", "--format=%s", f"origin/{branch}", "--"]
        ).decode("utf-8", "replace")
    except subprocess.CalledProcessError:
        return None

    matched = COMMIT_HASH_PATTERN.findall(message.encode("utf-8"))
    if len(matched) != 1:
        return None
    return matched[0].decode("ascii")


def write_branch(branch: str, head: str, files: dict) -> None:
    subprocess.run(["git", "checkout", branch], capture_output=True)
    branch_exists = (
        subprocess.run(
            ["git", "rev-parse", "--verify", branch],
            capture_output=True,
        ).returncode
        == 0
    )

    if not branch_exists:
        subprocess.run(["git", "checkout", "--orphan", branch], check=True)
    else:
        subprocess.run(["git", "checkout", branch], check=True)

    # 清空 worktree 分支上的旧内容
    subprocess.run(["git", "rm", "-r", "-f", "--ignore-unmatch", "."], capture_output=True)

    Path("worktree.json").write_text(
        json.dumps(files, ensure_ascii=False, indent=2) + "\n", "utf8"
    )
    history_dir = Path("history")
    history_dir.mkdir(exist_ok=True)
    (history_dir / f"{head}.json").write_text(
        json.dumps(files, ensure_ascii=False, indent=2) + "\n", "utf8"
    )

    subprocess.run(["git", "add", "worktree.json", "history/"], check=True)
    subprocess.run(
        [
            "git",
            "commit",
            "-m",
            f"update worktree info for <|{head}|>",
        ],
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--branch", default="worktree")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    head, files = collect_files()
    print(f"→ 收集到 {len(files)} 个文件（commit {head[:8]}）")

    target = previous_target(args.branch)
    if target == head and not args.force:
        print(f"→ {args.branch} 分支已是最新，无需更新")
        return 0

    write_branch(args.branch, head, files)
    print(f"→ 已更新 {args.branch} 分支")

    if args.push:
        # 用显式分支名而不是 HEAD：脚本末尾会切回 main，
        # 若此处用 HEAD 推送，在 main 上执行就会把 main 内容推上 worktree 分支。
        subprocess.run(
            ["git", "push", "--force", "origin", f"{args.branch}:{args.branch}"],
            check=True,
        )
        print(f"→ 已推送 {args.branch} 分支")

    subprocess.run(["git", "checkout", "main"], capture_output=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
