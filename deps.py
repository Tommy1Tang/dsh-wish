#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""执行体探测 (dependencies).

这个 skill 有两种输出：

- **精确版**：给出 `SP-01` / `validate_delivery.py` 这种具体节点和命令。
  只有装了 `agent-delivery-gate` 才有意义——否则照着做会卡在第 1 步。

- **通用版**：给出"环境准备 / 实现 / 冒烟 / 验收"这种阶段名。谁都能照着做。

分发场景下别人机器上没有 gate，所以默认**自动探测、探测不到就降级**。
降级不是残缺——它照样能判档、能对焦、能出契约，只是清单粗一点。

探测顺序（**不含任何硬编码绝对路径**，否则分发出去会指向别人的机器）：

1. 环境变量 `DSH_WISH_GATE`
2. 与本 skill 同级的 `agent-delivery-gate`（随包分发的常见形态）
3. 向上 3 层目录里找 `agent-delivery-gate`
4. 本机开发配置 `deps.local.json`（**不随包分发**，见 .gitignore）

本地开发时把真实路径写进 `deps.local.json`，分发时它不该存在——
这样"我自己能用精确版"和"别人装了也不报错"可以同时成立。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ENV_KEY = "DSH_WISH_GATE"
LOCAL_CONFIG = "deps.local.json"
GATE_MARKER = Path("scripts") / "validate_delivery.py"
R2PI_MARKER = Path("scripts") / "pipeline_runner.py"
SKILL_ROOT = Path(__file__).resolve().parent
VENDOR_DIR = SKILL_ROOT / "vendor"

# 随包分发的目录名（vendor/ 下）。装了就有，不依赖本机其他仓库。
VENDOR_PKG = {
    "gate": "agent-delivery-gate",
    "r2pi": "research-to-project-input",
}

# 分发出去时，同级目录里可能有这些兄弟项目
SIBLING_MARKERS = {
    "gate": GATE_MARKER,
    "agent-delivery-gate": GATE_MARKER,
    "r2pi": R2PI_MARKER,
    "research-to-project-input": R2PI_MARKER,
}

_override: bool | None = None
_cached: bool | None = None


def _local_paths(name: str) -> list[Path]:
    """读本机开发配置里某个项目的路径。文件不存在就是空——分发环境正常的形态。"""
    config = SKILL_ROOT / LOCAL_CONFIG
    if not config.is_file():
        return []
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    raw = data.get(name, []) if isinstance(data, dict) else []
    if isinstance(raw, str):
        raw = [raw]
    return [Path(item) for item in raw if isinstance(item, str)]


def find_related(
    name: str,
    marker: Path | None = None,
    prefer_vendor: bool = True,
) -> Path | None:
    """按名字找一个相关项目（gate / r2pi）。

    prefer_vendor=True（默认）：优先用随包的 `vendor/<项目>`，保证"装了就完整"。
    prefer_vendor=False：跳过 vendor 去源仓库找——`refs.py` 用它核对是否漂移。

    候选顺序：显式环境变量 → vendor → 同级目录 → 向上 3 层 → 本机配置。
    **不含硬编码绝对路径** —— 分发出去不能指向开发机。
    """
    marker = marker or SIBLING_MARKERS.get(name)
    if marker is None:
        return None

    candidates: list[Path] = []
    explicit = os.environ.get(f"DSH_WISH_{name.upper().replace('-', '_')}")
    if explicit:
        candidates.append(Path(explicit))
    if prefer_vendor:
        candidates.append(VENDOR_DIR / VENDOR_PKG.get(name, name))
    candidates.append(SKILL_ROOT.parent / name)
    for depth in range(1, 4):
        try:
            candidates.append(SKILL_ROOT.parents[depth] / name)
        except IndexError:
            break
    candidates.extend(_local_paths(name))

    for candidate in candidates:
        try:
            if (candidate / marker).is_file():
                return candidate
        except OSError:
            continue
    return None


def gate_root() -> Path | None:
    """找到 agent-delivery-gate 的根目录，没有返回 None."""
    return find_related("gate", GATE_MARKER)


def cmd_prefix(root: Path | None = None) -> str:
    """给命令行/文本用的路径前缀。

    vendor 里的项目返回相对路径（`vendor/agent-delivery-gate/`），
    外部路径返回绝对路径。这样写进 stage 清单的命令可以直接粘进终端。
    """
    target = root or gate_root()
    if target is None:
        return "scripts/"
    try:
        return target.relative_to(SKILL_ROOT).as_posix() + "/"
    except ValueError:
        return target.as_posix() + "/"


def gate_available() -> bool:
    global _cached
    if _override is not None:
        return _override
    if _cached is None:
        _cached = gate_root() is not None
    return _cached


def set_gate_available(value: bool | None) -> None:
    """测试用：强制指定，None 表示恢复自动探测并清缓存."""
    global _override, _cached
    _override = value
    if value is None:
        _cached = None


def describe() -> str:
    if gate_available():
        root = gate_root()
        return f"精确版（检测到 {root}）"
    return (
        "通用版（未检测到 agent-delivery-gate）。"
        f"把它的路径写进 {LOCAL_CONFIG} 或设环境变量 {ENV_KEY} 即可切到精确版"
    )
