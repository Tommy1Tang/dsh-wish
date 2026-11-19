#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实场景探测：只输出判定，不做断言。用于观察现状。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from router import ENTERPRISE_SIGNALS, classify  # noqa: E402

CASES = [
    "MES系统我有个BUG，我需要改可用库存的计算方式",
    "MES系统我需要加个功能增加功能，工序增加一个校验",
    "我需要在齐套报表中增加一个供应商库存字段",
    "我需要增加一个报表",
    "我需要从0到1重新设计上线一个MES系统，我有一个MES系统的项目",
    "我需要开发一个计算齐套的小程序，我提供物料BOM和物料库存的信息，然后系统帮我进行计算，到底能不能齐套",
]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

    for i, text in enumerate(CASES, 1):
        route = classify(text)
        ent = [h.id for h in route.hits if h.id in ENTERPRISE_SIGNALS]
        signals = ", ".join(
            f"{h.id}+{h.weight}" for h in route.hits if h.weight > 0
        ) or "—"
        print(f"{i}. {text}")
        print(f"   → {route.tier} ({route.decided_by})  score={route.score}  "
              f"置信={route.confidence}  企业级={ent or '无'}")
        print(f"   命中：{signals}")
        if route.risk_flags:
            print(f"   风险：{'；'.join(route.risk_flags)}")
        print(f"   缺口：{route.gaps or '无'}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
