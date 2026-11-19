#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实场景回归基线.

这 6 条来自一个真实 MES 开发者给的口语化需求。它们不是凭空设计的用例——
第一次跑的时候 6/6 全判 L1，等于分类器退化成了常量。这个文件就是防止再退回去。

**期望值是人的判断，不是真理。** 觉得某条判错就改期望值并注释理由，
但不要为了让测试变绿而改期望值。

    python tests/test_real_scenarios.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from router import classify  # noqa: E402

# (愿望, 期望档位, 期望工作类型, 理由)
BASELINE = [
    (
        "MES系统我有个BUG，我需要改可用库存的计算方式",
        "L1", "fix",
        "范围是单个计算规则, 不是系统重建; 属行为变更, 必须带风险标记",
    ),
    (
        "MES系统我需要加个功能增加功能，工序增加一个校验",
        "L1", "generic",
        "加一条校验规则, 识别不出具体类型, 走通用链",
    ),
    (
        "我需要在齐套报表中增加一个供应商库存字段",
        "L1", "report",
        "加字段; 供应商库存的数据来源是未知项, 但对焦会问出来",
    ),
    (
        "我需要增加一个报表",
        "L1", "report",
        "信息不足, 档位仅供参考 —— 关键是置信度必须为 low",
    ),
    (
        "我需要从0到1重新设计上线一个MES系统，我有一个MES系统的项目",
        "L2", "generic",
        "项目级规模, 单信号即强制: 这是重做, 不是改动",
    ),
    (
        "我需要开发一个计算齐套的小程序，我提供物料BOM和物料库存的信息，然后系统帮我进行计算，到底能不能齐套",
        "L1", "backend",
        "独立小工具, 核心是计算逻辑不是界面",
    ),
]

# 另外五类真实工作（用户点名的: 纯前端 / 前后端 / 小优化 / bug / 紧急）
PROFILE_BASELINE = [
    ("把登录页的样式改一下，按钮换个颜色", "L0", "frontend", False),
    ("做一个纯前端的数据看板页面，从接口拿数据渲染图表", "L1", "frontend", False),
    ("做一个前后端都有的工单系统，前端 Vue 后端 Spring", "L2", "fullstack", False),
    ("接口报错了，登录一直 500", "L1", "fix", False),
    ("产线停了，赶紧把库存锁解开", "L0", "generic", True),
    ("帮我把项目部署到测试环境", "L0", "ops", False),
    ("把历史订单数据迁移到新表", "L1", "data", False),
    ("加一个导出按钮", "L1", "frontend", False),
    # 第三轮补充: "看起来是改动, 实际是变更"的两类
    ("齐套报表的齐套率算法要改，现在是按数量，要改成按金额", "L1", "report", False),
    ("要和供应商系统对接，每天同步库存", "L2", "integration", False),
]

# 交付面判据的边界: 跨面的"新建"是 L2, 跨面的"穿透"仍是 L1
SURFACE_BASELINE = [
    ("做一个前后端都有的工单系统，前端 Vue 后端 Spring", "L2", "surfaces"),
    ("在现有的工单系统里，后端接口加一个字段，前端列表展示出来", "L1", "intent"),
    ("实现一个用户登录接口，支持手机号验证码登录", "L1", "intent"),
]


class TestRealScenarios(unittest.TestCase):
    def test_no_constant_tier_regression(self) -> None:
        """最重要的断言: 不能所有场景同一个档位."""
        tiers = {classify(text).tier for text, _, _, _ in BASELINE}
        self.assertGreater(len(tiers), 1, "分类器在真实数据上退化成常量了")

    def test_each_baseline(self) -> None:
        for text, expected, profile, why in BASELINE:
            with self.subTest(wish=text):
                route = classify(text)
                self.assertEqual(route.tier, expected, f"{text} → {route.tier}：{why}")
                self.assertEqual(route.profile, profile, f"{text} 类型判错：{why}")

    def test_profile_baseline(self) -> None:
        for text, tier, profile, urgent in PROFILE_BASELINE:
            with self.subTest(wish=text):
                route = classify(text)
                self.assertEqual(route.tier, tier, f"{text} → {route.tier}")
                self.assertEqual(route.profile, profile, f"{text} → {route.profile}")
                self.assertEqual(route.urgent, urgent, f"{text} 紧迫度判错")

    def test_work_shape_differs_by_profile(self) -> None:
        """不同工作类型必须给出不同形状的 stage, 不是同一个列表换标题."""
        fix = " ".join(classify("接口报错了，登录一直 500").stages)
        fe = " ".join(classify("做一个纯前端的数据看板页面").stages)
        data = " ".join(classify("把历史订单数据迁移到新表").stages)
        ops = " ".join(classify("帮我把项目部署到测试环境").stages)
        self.assertIn("复现", fix)
        self.assertIn("浏览器 E2E", fe)
        self.assertIn("dry-run", data)
        self.assertIn("deploy-only", ops)

    def test_urgent_has_stopgap_first(self) -> None:
        route = classify("产线停了，赶紧把库存锁解开")
        self.assertTrue(route.urgent)
        self.assertIn("止血", route.stages[0])
        self.assertIn("补流程", route.stages[-1])

    def test_surface_baseline(self) -> None:
        """跨面新建 = L2; 跨面穿透 = 仍是 L1. 面数多不等于复杂."""
        for text, tier, decided_by in SURFACE_BASELINE:
            with self.subTest(wish=text):
                route = classify(text)
                self.assertEqual(route.tier, tier, f"{text} → {route.tier}")
                self.assertEqual(route.decided_by, decided_by, f"{text} 依据错")

    def test_fullstack_new_system_is_l2(self) -> None:
        route = classify("做一个前后端都有的工单系统，前端 Vue 后端 Spring")
        self.assertEqual(route.tier, "L2")
        self.assertGreaterEqual(len(route.surfaces), 3)

    def test_passthrough_does_not_inflate(self) -> None:
        """加字段透传跨 4 个面, 但不能因此配契约冻结."""
        route = classify("在现有的工单系统里，后端接口加一个字段，前端列表展示出来")
        self.assertEqual(route.tier, "L1")
        self.assertGreaterEqual(len(route.surfaces), 3)

    def test_behavior_change_probe_is_mandatory(self) -> None:
        """改了口径, 必须问"历史数据怎么办" —— 这是最容易漏的一条."""
        route = classify("齐套报表的齐套率算法要改，现在是按数量，要改成按金额")
        titles = [p.title for p in route.probes]
        self.assertIn("历史数据怎么处理", titles)
        self.assertTrue(any("行为变更" in flag for flag in route.risk_flags))

    def test_external_boundary_is_l2(self) -> None:
        """对接外部系统 = 集成 + 跨组织边界 = 两个企业级特征."""
        route = classify("要和供应商系统对接，每天同步库存")
        self.assertEqual(route.tier, "L2")
        self.assertEqual(route.profile, "integration")
        self.assertTrue(any("跨组织边界" in flag for flag in route.risk_flags))
        titles = [p.title for p in route.probes]
        self.assertIn("对方接口文档", titles)
        self.assertIn("联调谁配合", titles)

    def test_data_cannot_be_quick(self) -> None:
        """数据迁移不可逆, 不能被判成 L0."""
        route = classify("把历史订单数据迁移到新表")
        self.assertNotEqual(route.tier, "L0")
        self.assertEqual(route.decided_by, "profile")

    def test_system_name_is_not_integration(self) -> None:
        """只说 MES 不算集成; 要有对接动作才算."""
        route = classify("MES系统我有个BUG，我需要改可用库存的计算方式")
        self.assertNotIn("INTEGRATION", {h.id for h in route.hits})

    def test_behavior_change_is_flagged(self) -> None:
        """改计算方式必须打风险标记, 即使档位只是 L1."""
        route = classify("MES系统我有个BUG，我需要改可用库存的计算方式")
        self.assertIn("BEHAVIOR_CHANGE", {h.id for h in route.hits})
        self.assertTrue(any("行为变更" in flag for flag in route.risk_flags))

    def test_scale_forces_l2(self) -> None:
        route = classify("从0到1做一个全新的订单系统")
        self.assertEqual(route.tier, "L2")
        self.assertEqual(route.decided_by, "scale")

    def test_short_vague_wish_is_low_confidence(self) -> None:
        route = classify("我需要增加一个报表")
        self.assertEqual(route.confidence, "low")
        self.assertIn("判不准", route.next_action)

    def test_short_but_decisive_is_high_confidence(self) -> None:
        """句子短不等于判不准 —— 命中企业级组合时结论是硬的.

        踩过：「要和供应商系统对接，每天同步库存」判 L2 却说"仅供参考"，
        而"对接 + 供应商系统"两句话就能钉死这件事。
        """
        route = classify("要和供应商系统对接，每天同步库存")
        self.assertEqual(route.tier, "L2")
        self.assertEqual(route.decided_by, "enterprise")
        self.assertEqual(route.confidence, "high")
        self.assertNotIn("仅供参考", route.reason)

    def test_scale_signal_keeps_high_confidence(self) -> None:
        route = classify("从0到1做个系统")
        self.assertEqual(route.decided_by, "scale")
        self.assertEqual(route.confidence, "high")

    def test_reroute_escalates_behavior_change(self) -> None:
        """场景 1 追问后应升档: 改计算方式牵动下游报表."""
        from router import reroute

        change, route = reroute(
            "MES系统我有个BUG，我需要改可用库存的计算方式",
            "这个库存口径变了以后，齐套报表和多角色权限下的可用量都要跟着变，还要过审计",
        )
        self.assertEqual(change.direction, "upgrade")
        self.assertEqual(route.tier, "L2")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    unittest.main(verbosity=2)
