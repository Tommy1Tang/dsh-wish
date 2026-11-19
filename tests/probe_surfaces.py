#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交付面（surfaces）探测：为什么跨前后端就是 L2。

    python tests/probe_surfaces.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from router import PROFILE_LABEL, classify  # noqa: E402

CASES = [
    "做一个前后端都有的工单系统，前端 Vue 后端 Spring",
    "做一个纯前端的数据看板页面，从接口拿数据渲染图表",
    "实现一个用户登录接口，支持手机号验证码登录",
    "在现有的工单系统里，后端接口加一个字段，前端列表展示出来",
    "MES系统我有个BUG，我需要改可用库存的计算方式",
    "我需要在齐套报表中增加一个供应商库存字段",
    "开发一个计算齐套的小程序，我提供BOM和库存，帮我算能不能齐套",
    "给客户做一套MES，对接SAP和WMS，要通过等保",
    "加一个导出按钮",
]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

    print(f"{'档位':<4}{'依据':<12}{'交付面':<26}{'类型':<10}愿望")
    print("-" * 96)
    for text in CASES:
        route = classify(text)
        faces = "/".join(route.surfaces) or "-"
        print(
            f"{route.tier:<4}{route.decided_by:<12}{faces:<26}"
            f"{PROFILE_LABEL.get(route.profile, route.profile):<10}{text[:36]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
