#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把外部项目同步进 vendor/，让插件自包含。

为什么要有这个脚本，而不是直接 copy：

内嵌的风险不是"多占 20MB"，是**悄悄分叉**——vendor 里改了，源仓库不知道；
源仓库改了，vendor 不知道。所以每次同步都写 `vendor/VENDOR.json`，记下：
源路径、git commit、文件数、总字节、快照时间。

`refs.py` 会拿这份记录和源仓库的当前 commit 对比，不一致就报出来。

    python tools/sync_vendor.py            # 同步全部
    python tools/sync_vendor.py gate       # 只同步 gate
    python tools/sync_vendor.py --check    # 只检查是否需要同步，不写文件

退出码：0 = 一致或已同步；1 = 有项目不是最新（--check 模式）
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor"
MANIFEST = VENDOR / "VENDOR.json"

sys.path.insert(0, str(ROOT))
import deps  # noqa: E402

# 同步哪些项目、各自的标记文件（用来确认目录没认错）
PROJECTS = {
    "gate": {
        "pkg_name": "agent-delivery-gate",
        "marker": deps.GATE_MARKER,
        "why": "L1/L2 的执行体：流程节点、门禁脚本、schema、模板",
    },
    "r2pi": {
        "pkg_name": "research-to-project-input",
        "marker": deps.R2PI_MARKER,
        "why": "L2 的建模段：需求图、BPMN/OWL 生成、SHACL 校验",
    },
}

# 不该进包的：版本库、缓存、编辑器垃圾
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", "node_modules", ".idea", ".vscode"}
SKIP_FILES = {".DS_Store", "Thumbs.db"}


def git_commit(path: Path) -> str | None:
    """拿源目录的 git commit（如果有）。这是"是不是最新"的判据。"""
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def scan(path: Path) -> tuple[int, int]:
    """返回 (文件数, 总字节)，跳过不该进包的东西。"""
    count = size = 0
    for item in path.rglob("*"):
        if not item.is_file():
            continue
        if any(part in SKIP_DIRS for part in item.parts):
            continue
        if item.name in SKIP_FILES:
            continue
        count += 1
        try:
            size += item.stat().st_size
        except OSError:
            pass
    return count, size


def copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(
        src, dst,
        ignore=shutil.ignore_patterns(*SKIP_DIRS, *SKIP_FILES),
        dirs_exist_ok=False,
    )


def load_manifest() -> dict:
    if MANIFEST.is_file():
        try:
            return json.loads(MANIFEST.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return {}


def save_manifest(data: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def sync_one(key: str, check_only: bool) -> tuple[str, str]:
    """返回 (状态, 说明)。状态：ok / synced / stale / missing"""
    spec = PROJECTS[key]
    # 关键：这里要的是**源仓库**，不是 vendor 里的副本。
    # 用默认的 prefer_vendor=True 会找到 vendor 自己，于是永远"和源一致"。
    src = deps.find_related(key, spec["marker"], prefer_vendor=False)
    if src is None:
        return "missing", "源目录找不到（可用 deps.local.json 指定）"

    manifest = load_manifest()
    record = manifest.get(key, {})
    commit = git_commit(src)
    files, size = scan(src)
    dst = VENDOR / spec["pkg_name"]

    up_to_date = (
        dst.is_dir()
        and record.get("commit") == commit
        and record.get("files") == files
    )

    if check_only:
        if not dst.is_dir():
            return "missing", "vendor 里还没有"
        if up_to_date:
            return "ok", f"{files} 个文件 / {size:,} 字节，与源一致"
        return "stale", f"vendor={record.get('commit', '?')[:8]} 源={str(commit)[:8]}"

    copy_tree(src, dst)
    record = {
        "source": str(src),
        "commit": commit,
        "files": files,
        "bytes": size,
        "syncedAt": datetime.now().isoformat(timespec="seconds"),
        "why": spec["why"],
    }
    manifest[key] = record
    save_manifest(manifest)
    return "synced", f"{files} 个文件 / {size:,} 字节 ← {src}"


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(description="同步外部项目到 vendor/")
    parser.add_argument(
        "targets", nargs="*", metavar="TARGET",
        help=f"要同步的项目：{' / '.join(PROJECTS)} / all（默认 all）",
    )
    parser.add_argument("--check", action="store_true", help="只检查，不写文件")
    args = parser.parse_args(argv)

    targets = args.targets or ["all"]
    unknown = [t for t in targets if t != "all" and t not in PROJECTS]
    if unknown:
        parser.error(f"不认识的项目：{unknown}（可选：{' / '.join(PROJECTS)} / all）")
    keys = list(PROJECTS) if "all" in targets else targets

    worst = 0
    for key in keys:
        status, detail = sync_one(key, args.check)
        mark = {"ok": "OK", "synced": "SYNCED", "stale": "STALE", "missing": "MISSING"}[status]
        print(f"{key:<6} {mark:<8} {detail}")
        if status in ("missing", "stale"):
            worst = 1

    if not args.check:
        total_files, total_bytes = 0, 0
        for item in VENDOR.rglob("*"):
            if item.is_file() and item.name != "VENDOR.json":
                total_files += 1
                try:
                    total_bytes += item.stat().st_size
                except OSError:
                    pass
        print(f"\nvendor/ 合计：{total_files} 个文件 / {total_bytes:,} 字节")
        print(f"清单：{MANIFEST}")
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
