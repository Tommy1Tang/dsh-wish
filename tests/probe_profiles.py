#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工作类型（profile）探测：用户提到的五类真实工作 + 两个边界。

    python tests/probe_profiles.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from router import PROFILE_LABEL, classify  # noqa: E402

CASES = [
    "把登录页的样式改一下，按钮换个颜色",
    "做一个纯前端的数据看板页面，从接口拿数据渲染图表",
    "做一个前后端都有的工单系统，前端 Vue 后端 Spring",
    "接口报错了，登录一直 500",
    "产线停了，赶紧把库存锁解开",
    "帮我把项目部署到测试环境",
    "把历史订单数据迁移到新表",
]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

    for i, text in enumerate(CASES, 1):
        route = classify(text)
        label = PROFILE_LABEL.get(route.profile, route.profile)
        urgent = "🔴紧急" if route.urgent else ""
        print(f"{i}. {text}")
        print(f"   → {route.tier} / {route.profile}({label}) {urgent}  "
              f"置信={route.confidence}  score={route.score}")
        for stage in route.stages[:6]:
            print(f"     · {stage}")
        if len(route.stages) > 6:
            print(f"     … 共 {len(route.stages)} 步")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
