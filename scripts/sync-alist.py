#!/usr/bin/env python3
"""从 Alist 资料栈同步资料到本仓库。

资料栈部署在校内网，GitHub Actions 的 runner 访问不到，
因此本脚本在**校园网环境**下运行；同步结果 push 到 main 后，
由 `.github/workflows/update-worktree.yml` 重新生成 worktree 分支，
站点再从 worktree 分支读取文件清单。

用法：

    ALIST_USERNAME=<账号> ALIST_PASSWORD=<密码> python3 scripts/sync-alist.py

参数：

    --repo <path>   仓库根目录（默认脚本所在仓库）
    --base <url>    资料栈地址（默认 http://10.249.44.116:5244）
    --no-download   只刷新清单，不下载文件
    --dry-run       只打印将要发生的变更
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# 收录策略
# ---------------------------------------------------------------------------

# 入库体积上限：单文件超过 50 MiB 的不入库，站内列出并跳资料栈原地址下载
# （GitHub 单文件硬限制是 100 MiB，这里留一半余量，避免仓库过大拖慢克隆与 CI）
MIRROR_MAX_SIZE = 50 * 1024 * 1024

# 资料栈根目录的文件改名后放进 docs/，
# 一是避免和仓库自身的 README.md 大小写冲突，二是让资料树顶层更干净。
RENAME = {
    "readme.md": "docs/资料栈说明.md",
    "QQ群二维码.jpg": "docs/QQ群二维码.jpg",
    "“程序援”学风涵养工作室资料栈用户反馈问卷二维码.png": "docs/用户反馈问卷二维码.png",
}

# 仓库自身文件，不属于资料栈内容
REPO_OWNED = {
    "README.md",
    "LICENSE",
    "resources.json",
    ".gitignore",
    ".gitattributes",
    ".sync-state.json",
}

# 仓库自身的目录，不参与同步（.git 尤其不能碰）
REPO_OWNED_DIRS = {"scripts", ".github", ".git", "history"}

DEFAULT_BASE = "http://10.249.44.116:5244"
TIMEOUT = 60


def log(message: str) -> None:
    print(message, flush=True)


class Alist:
    def __init__(self, base: str, username: str, password: str) -> None:
        self.base = base.rstrip("/")
        # 内网地址必须绕过系统代理
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.token = ""
        self.token = self._login(username, password)

    def _request(self, path: str, payload=None):
        url = f"{self.base}/api{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(url, data=data)
        request.add_header("Content-Type", "application/json")
        request.add_header("User-Agent", "hoa-e-cube-sync")
        if data is None:
            request.method = "GET"
        if self.token:
            request.add_header("Authorization", self.token)

        with self.opener.open(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))

    def _login(self, username: str, password: str) -> str:
        result = self._request("/auth/login", {"username": username, "password": password})
        if result.get("code") != 200:
            raise RuntimeError(f"登录失败：{result.get('message')}")
        return result["data"]["token"]

    def list_dir(self, path: str) -> list:
        result = self._request(
            "/fs/list",
            {
                "path": path,
                "password": "",
                "page": 1,
                "per_page": 0,
                "refresh": False,
            },
        )
        if result.get("code") != 200:
            raise RuntimeError(f"列目录失败 {path}：{result.get('message')}")
        return (result.get("data") or {}).get("content") or []

    def get_file(self, path: str) -> dict:
        """取单个文件的 raw_url / sign（Alist 会给出带永久签名的直链）。"""
        result = self._request("/fs/get", {"path": path, "password": ""})
        if result.get("code") != 200:
            raise RuntimeError(f"取文件失败 {path}：{result.get('message')}")
        return result["data"]

    def walk(self) -> list:
        entries = []

        def _walk(path: str) -> None:
            for item in self.list_dir(path):
                full = f"{path.rstrip('/')}/{item['name']}"
                if item.get("is_dir"):
                    _walk(full)
                    continue
                entries.append(
                    {
                        "path": full.lstrip("/"),
                        "size": item.get("size", 0),
                        "modified": item.get("modified"),
                    }
                )

        _walk("/")
        return entries

    def download(self, url: str, target: Path) -> None:
        request = urllib.request.Request(url)
        request.add_header("User-Agent", "hoa-e-cube-sync")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".part")

        last_error = None
        for attempt in range(1, 4):
            try:
                with self.opener.open(request, timeout=TIMEOUT) as response:
                    with tmp.open("wb") as handle:
                        while True:
                            chunk = response.read(1 << 20)
                            if not chunk:
                                break
                            handle.write(chunk)
                tmp.replace(target)
                return
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                last_error = error
                log(f"    ! 第 {attempt} 次下载失败：{error}")
                time.sleep(attempt * 2)

        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"下载失败：{url}（{last_error}）")


def to_unix_timestamp(modified: str | None) -> int:
    if not modified:
        return 0
    # Alist 返回形如 2024-11-21T20:59:36.11+08:00
    try:
        from datetime import datetime

        return int(datetime.fromisoformat(modified).timestamp())
    except ValueError:
        return 0


def is_external(entry: dict) -> bool:
    """只有超过 GitHub 单文件硬限制的文件才不入库。"""
    return entry["size"] > MIRROR_MAX_SIZE


def target_path(entry: dict) -> str:
    """资料栈内路径 → 仓库内路径（含改名规则）。"""
    return RENAME.get(entry["path"], entry["path"])


def html_to_markdown(text: str) -> str:
    """资料栈的说明文档原本用 HTML 标签排版，这里转成 Markdown 便于阅读。"""
    import html
    import re

    text = re.sub(r"<h1[^>]*>(.*?)</h1>", r"# \1\n", text, flags=re.S)
    text = re.sub(
        r"<h([2-6])[^>]*>(.*?)</h\1>",
        lambda m: "\n" + "#" * int(m.group(1)) + " " + m.group(2).strip() + "\n",
        text,
        flags=re.S,
    )
    text = re.sub(r"<li[^>]*>(.*?)</li>", r"- \1\n", text, flags=re.S)
    text = re.sub(r"</?ul[^>]*>", "\n", text)
    text = re.sub(
        r"<a[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
        r"[\2](\1)",
        text,
        flags=re.S,
    )
    text = re.sub(r"<strong[^>]*>(.*?)</strong>", r"**\1**", text, flags=re.S)
    text = re.sub(r"<em[^>]*>(.*?)</em>", r"*\1*", text, flags=re.S)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<p[^>]*>(.*?)</p>", r"\n\1\n", text, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)

    def is_cjk(char: str) -> bool:
        code = ord(char)
        return (
            0x3000 <= code <= 0x303F
            or 0x4E00 <= code <= 0x9FFF
            or 0xFF00 <= code <= 0xFFEF
        )

    # 原文按宽度硬换行，这里把段落内的换行合并回一行
    blocks = []
    for block in re.split(r"\n\s*\n", text):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        merged = lines[0]
        for line in lines[1:]:
            if is_cjk(merged[-1]) and is_cjk(line[0]):
                merged += line
            else:
                merged += " " + line
        blocks.append(merged)

    return "\n\n".join(blocks).strip() + "\n"


def human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def is_repo_owned(relative: str) -> bool:
    """判断仓库内相对路径是否属于仓库自身（脚本、配置、.git 等）。"""
    head = relative.split("/")[0]
    return relative in REPO_OWNED or head in REPO_OWNED_DIRS


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--base", default=os.environ.get("ALIST_BASE", DEFAULT_BASE))
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument(
        "--seed-state",
        action="store_true",
        help="用源端时间补齐状态文件：本地已有文件就跳过下载（仅在状态文件丢失时使用）",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    username = os.environ.get("ALIST_USERNAME")
    password = os.environ.get("ALIST_PASSWORD")
    if not username or not password:
        log("请通过环境变量提供 ALIST_USERNAME / ALIST_PASSWORD")
        return 2

    repo = Path(args.repo).resolve()
    # 资料内容与组织课程仓一致，直接放在仓库根目录
    content_root = repo

    log(f"→ 连接资料栈 {args.base}")
    client = Alist(args.base, username, password)
    entries = client.walk()
    log(f"  资料栈共 {len(entries)} 个文件")

    mirrored = [item for item in entries if not is_external(item)]
    external = [item for item in entries if is_external(item)]
    log(
        f"  入库 {len(mirrored)} 个（{human(sum(i['size'] for i in mirrored))}），"
        f"仅登记原地址 {len(external)} 个（{human(sum(i['size'] for i in external))}）"
    )

    # ---------------------------------------------------------------- 下载
    #
    # Alist 的 size 字段偶尔与实际字节数不一致（例如带换行的短文本），
    # 只按 size 判断会反复重下同样的文件。这里用「源端 modified 时间 +
    # 本地状态文件」判断文件是否变化。
    state_path = repo / ".sync-state.json"
    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text("utf-8"))
        except ValueError:
            state = {}

    changed = 0
    if not args.no_download:
        for index, item in enumerate(mirrored, start=1):
            relative = target_path(item)
            target = content_root / relative
            recorded = state.get(item["path"])
            unchanged = (
                recorded is not None
                and recorded.get("modified") == item["modified"]
                and target.exists()
            )
            if unchanged:
                continue

            # 补种状态：本地已有文件就认为是最新的
            if args.seed_state and target.exists():
                state[item["path"]] = {
                    "size": item["size"],
                    "modified": item["modified"],
                }
                continue

            changed += 1
            log(f"  [{index}/{len(mirrored)}] {item['path']}")
            if args.dry_run:
                continue
            info = client.get_file("/" + item["path"])
            client.download(info["raw_url"], target)
            if relative in RENAME.values() and relative.endswith(".md"):
                target.write_text(
                    html_to_markdown(target.read_text("utf-8", "replace")), "utf8"
                )
            state[item["path"]] = {
                "size": item["size"],
                "modified": item["modified"],
            }

        if not args.dry_run:
            state_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2) + "\n", "utf8"
            )
        log(f"  本次更新 {changed} 个文件")

    # ------------------------------------------------------- 清理失效文件
    wanted = {target_path(item) for item in mirrored}
    if not args.dry_run:
        for path in sorted(content_root.rglob("*"), reverse=True):
            if not path.is_file():
                continue
            relative = str(path.relative_to(content_root))
            if relative in wanted or is_repo_owned(relative):
                continue
            log(f"  - 删除失效文件 {relative}")
            path.unlink()

    # -------------------------------------------------------- resources.json
    external_entries = []
    for item in external:
        raw_url = "" if args.dry_run else client.get_file("/" + item["path"])["raw_url"]
        external_entries.append(
            {
                "path": item["path"],
                "name": Path(item["path"]).name,
                "size": item["size"],
                "time": to_unix_timestamp(item["modified"]),
                "url": raw_url,
                "note": "超过 GitHub 单文件上限，保留在资料栈原地址下载",
            }
        )

    meta_path = repo / "resources.json"
    meta = json.loads(meta_path.read_text("utf-8")) if meta_path.exists() else {}
    meta["external"] = external_entries
    meta["policy"] = {
        "mirroredMaxSize": MIRROR_MAX_SIZE,
        "mirroredCount": len(mirrored),
        "externalCount": len(external),
        "mirroredSize": sum(i["size"] for i in mirrored),
        "externalSize": sum(i["size"] for i in external),
        "syncedAt": int(time.time()),
    }

    if not args.dry_run:
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", "utf8"
        )
        log(f"→ 已更新 {meta_path.relative_to(repo)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
