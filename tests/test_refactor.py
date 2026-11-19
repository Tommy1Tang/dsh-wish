#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""存量改造（refactor）的测试.

    python tests/test_refactor.py

改已有项目和新建项目是两回事：
- 新建：风险在"做不出来"
- 改造：风险在"改坏了" —— 所以第一步不是设计，是**读懂现状**

这里钉住四件事：
1. 技术栈迁移 / 架构拆分判 L2（过去判轻成 L1）
2. 工作类型判 `refactor`，不是 `frontend` / `generic`
3. "读现状"排在"对焦"之前
4. 不套业务建模段（把 JSP 换 Vue 不需要画 BPMN）
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from router import classify  # noqa: E402


def stage_index(stages: list[str], needle: str) -> int:
    for i, stage in enumerate(stages):
        if needle in stage:
            return i
    return -1


class TestLegacyTier(unittest.TestCase):
    def test_legacy_stack_migration_is_l2(self) -> None:
        route = classify("把现在的 JSP 老系统改造成 Vue3 前后端分离", precise=True)
        self.assertEqual(route.tier, "L2")
        self.assertEqual(route.decided_by, "legacy", "归因要指向 LEGACY，不是 SCALE")
        self.assertIn("LEGACY", {h.id for h in route.hits})

    def test_attribution_is_not_scale(self) -> None:
        """「重做」和「改造」是两种风险，理由不能写成同一句."""
        legacy = classify("把现在的 JSP 老系统改造成 Vue3 前后端分离", precise=True)
        fresh = classify("从0到1做一个全新的订单系统", precise=True)
        self.assertNotEqual(legacy.decided_by, fresh.decided_by)
        self.assertNotEqual(legacy.reason, fresh.reason)

    def test_microservice_split_is_l2(self) -> None:
        route = classify("重构现有的订单服务，拆成微服务", precise=True)
        self.assertEqual(route.tier, "L2")

    def test_plain_ui_tweak_is_not_refactor(self) -> None:
        """「改造登录页样式」是前端活，不该被存量改造吞掉.

        注意它仍是 L1 而不是 L0：命中「改造」这个开发意图就至少 L1。
        这不是缺陷——它确实会产生一次真实改动，L1 的对焦最多 3 个问题。
        """
        route = classify("改造登录页的样式，按钮换个颜色", precise=True)
        self.assertNotEqual(route.profile, "refactor")
        self.assertEqual(route.profile, "frontend")
        self.assertEqual(route.tier, "L1")

    def test_plain_bug_is_not_refactor(self) -> None:
        route = classify("现有项目的登录模块有 bug，偶尔 500", precise=True)
        self.assertEqual(route.profile, "fix")

    def test_adding_a_step_to_existing_flow_stays_l1(self) -> None:
        """给现有审批流加一级：改动小、范围清，仍走 L1."""
        route = classify("我们现有的 MES 里，工单模块的审批流要加一级", precise=True)
        self.assertEqual(route.tier, "L1")


class TestRefactorProfile(unittest.TestCase):
    def setUp(self) -> None:
        self.route = classify("把现在的 JSP 老系统改造成 Vue3 前后端分离", precise=True)

    def test_profile_is_refactor(self) -> None:
        self.assertEqual(self.route.profile, "refactor")

    def test_reads_current_state_before_focus(self) -> None:
        """读现状必须在对焦之前 —— 先看清项目，再决定问什么."""
        read = stage_index(self.route.stages, "读现状")
        focus = stage_index(self.route.stages, "对焦")
        self.assertGreaterEqual(read, 0, "refactor 缺「读现状」这一步")
        self.assertGreaterEqual(focus, 0)
        self.assertLess(read, focus, "读现状排到对焦后面了")

    def test_precise_mode_points_at_real_tools(self) -> None:
        joined = " ".join(self.route.stages)
        self.assertIn("detect_stack.py", joined)
        self.assertIn("build_code_index.py", joined)

    def test_no_business_modelling_block(self) -> None:
        """改造不需要业务建模（BPMN/OWL），套上就是浪费."""
        joined = " ".join(self.route.stages)
        self.assertNotIn("pipeline_runner.py", joined)
        self.assertNotIn("approve --gate modeling", joined)

    def test_has_impact_and_rollback(self) -> None:
        joined = " ".join(self.route.stages)
        self.assertIn("影响面清单", joined)
        self.assertIn("回滚", joined)

    def test_asks_for_existing_state_facts(self) -> None:
        titles = [p.title for p in self.route.probes]
        self.assertIn("现有实现现状", titles)
        # 这是 fact 类：自己去看代码，不是问用户
        fact = next(p for p in self.route.probes if p.title == "现有实现现状")
        self.assertEqual(fact.kind, "fact")


class TestGenericMode(unittest.TestCase):
    def test_generic_keeps_same_order(self) -> None:
        route = classify("把现在的 JSP 老系统改造成 Vue3 前后端分离", precise=False)
        read = stage_index(route.stages, "读现状")
        focus = stage_index(route.stages, "对焦")
        self.assertLess(read, focus)

    def test_generic_has_no_dangling_paths(self) -> None:
        route = classify("重构现有的订单服务，拆成微服务", precise=False)
        joined = " ".join(route.stages)
        self.assertNotIn("detect_stack.py", joined)
        self.assertNotIn("vendor/", joined)
        # 但"读现状"这件事本身不能丢
        self.assertIn("读现状", joined)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    unittest.main(verbosity=2)
