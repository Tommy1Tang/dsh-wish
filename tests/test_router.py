#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""档位路由器的单元测试. 只用标准库.

    python tests/test_router.py
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from router import (  # noqa: E402
    ENTERPRISE_SIGNALS,
    Route,
    TIER_META,
    classify,
    detect_gaps,
    render_markdown,
    reroute,
)


class TestVeto(unittest.TestCase):
    """否决规则必须先于任何加分生效, 否则"改个 typo"也会进流水线."""

    def test_qa_is_quick(self) -> None:
        self.assertEqual(classify("这个函数是什么意思").tier, "L0")

    def test_typo_is_quick(self) -> None:
        self.assertEqual(classify("帮我改个 typo").tier, "L0")

    def test_lookup_is_quick(self) -> None:
        self.assertEqual(classify("看一下项目结构").tier, "L0")

    def test_veto_survives_incidental_dev_word(self) -> None:
        """否决命中时, 顺带出现"做/实现"不该把档位拉起来."""
        self.assertEqual(classify("解释一下这个流程为什么要这么做").tier, "L0")

    def test_veto_does_not_beat_enterprise(self) -> None:
        """但如果同时是企业级组合, 否决要让位 —— 说明它其实是个交付任务."""
        route = classify("先看一下现状，然后要做一套审批流对接 ERP")
        self.assertEqual(route.tier, "L2")
        self.assertEqual(route.decided_by, "enterprise")


class TestTiering(unittest.TestCase):
    def test_dev_intent_is_standard(self) -> None:
        self.assertEqual(classify("实现一个用户登录接口").tier, "L1")

    def test_structural_word_is_standard(self) -> None:
        self.assertEqual(classify("班组长的工序报工加上按钮权限").tier, "L1")

    def test_flow_plus_multi_role_is_enterprise(self) -> None:
        route = classify("做一个车间工单管理系统，要有审批流和多角色权限")
        self.assertEqual(route.tier, "L2")
        self.assertEqual(route.decided_by, "enterprise")

    def test_integration_plus_compliance_is_enterprise(self) -> None:
        route = classify("给客户做一套 MES，对接 SAP 和 WMS，要通过等保")
        self.assertEqual(route.tier, "L2")

    def test_score_alone_can_reach_enterprise(self) -> None:
        # 没有两个企业级信号, 但业务+交付特征堆够分数
        route = classify("要做领域数据台账，涉及对账结算，报表口径要统一，客户验收，必须上线")
        self.assertIn(route.decided_by, {"enterprise", "score"})
        self.assertEqual(route.tier, "L2")

    def test_one_enterprise_signal_is_not_enough(self) -> None:
        route = classify("增加一个导出按钮")
        self.assertEqual(route.tier, "L1")
        self.assertNotEqual(route.decided_by, "enterprise")


class TestGaps(unittest.TestCase):
    def test_quick_tier_reports_no_gaps(self) -> None:
        self.assertEqual(detect_gaps("这个函数是什么意思", "L0"), [])

    def test_missing_acceptance_is_reported(self) -> None:
        gaps = detect_gaps("给客户做一个系统，要上线", "L1")
        self.assertTrue(any("验收" in gap for gap in gaps))

    def test_complete_wish_has_no_gaps(self) -> None:
        text = "给仓库管理员做一个入库登记页面，能录入批次和数量，验收标准是能正确保存并查询"
        self.assertEqual(detect_gaps(text, "L1"), [])


class TestStructure(unittest.TestCase):
    def test_empty_text_raises(self) -> None:
        with self.assertRaises(ValueError):
            classify("   ")

    def test_checkpoint_counts(self) -> None:
        self.assertEqual(len(classify("看一下日志").checkpoints), 0)
        self.assertEqual(len(classify("实现一个登录接口").checkpoints), 2)
        self.assertEqual(
            len(classify("做一个工单审批系统，多角色权限，要上线").checkpoints), 4
        )

    def test_every_checkpoint_has_a_reviewer(self) -> None:
        """每个检查点都必须说清谁看、看什么、卡住什么."""
        for tier_text in ("实现一个登录接口", "做一个工单审批系统，多角色权限，要上线"):
            for cp in classify(tier_text).checkpoints:
                for key in ("reviewer", "looks_at", "blocks"):
                    self.assertTrue(cp.get(key), f"{cp['id']} 缺 {key}")

    def test_fake_deliverable_checkpoint_exists(self) -> None:
        """假交付物是 L1 起就有的检查点, 不是 L2 专属."""
        ids = [cp["id"] for cp in classify("实现一个登录接口").checkpoints]
        self.assertIn("fake", ids)

    def test_quick_tier_has_single_stage(self) -> None:
        self.assertEqual(len(classify("翻译一下这段").stages), 1)

    def test_fullstack_implies_interface_and_ui_surfaces(self) -> None:
        """「前后端」是复合词：ui 面认「前端」、api 面认「后端」，会漏掉界面面.

        这是测试抓出来的：profile 判成 fullstack，面数却只有 2 个，于是判成 L1。
        profile 说"前后端都有"，那是比关键词更强的证据。
        """
        route = classify("做一个前后端都有的工单系统", precise=False)
        self.assertEqual(route.profile, "fullstack")
        self.assertIn("api", route.surfaces)
        self.assertIn("ui", route.surfaces)

    def test_enterprise_stages_include_both_human_gates(self) -> None:
        stages = " ".join(
            classify("给客户做 MES，对接 SAP，要过等保", precise=True).stages
        )
        self.assertIn("approve --gate modeling", stages)
        self.assertIn("approve --gate models", stages)

    def test_generic_mode_has_no_project_specific_nodes(self) -> None:
        """没装 gate 时不能输出 SP-xx 和对方脚本名 —— 照着做会卡在第 1 步."""
        stages = " ".join(
            classify("给客户做 MES，对接 SAP，要过等保", precise=False).stages
        )
        self.assertNotIn("SP-", stages)
        self.assertNotIn("validate_delivery", stages)
        self.assertNotIn("approve --gate", stages)
        self.assertIn("交付验收", stages)

    def test_tier_is_independent_of_execution_mode(self) -> None:
        """降级只影响清单粗细，不影响档位判断."""
        for text in ("做一个前后端都有的工单系统", "改个 typo", "把数据迁移到新表"):
            with self.subTest(wish=text):
                self.assertEqual(
                    classify(text, precise=True).tier,
                    classify(text, precise=False).tier,
                )

    def test_every_tier_is_declared(self) -> None:
        for tier in TIER_META:
            self.assertIn(tier, {"L0", "L1", "L2"})

    def test_enterprise_signal_ids_exist(self) -> None:
        """企业级名单里的 id 必须真的存在于信号表, 否则规则永远不触发."""
        route = classify("对接 SAP 并通过等保审计")
        hit_ids = {hit.id for hit in route.hits}
        for name in ENTERPRISE_SIGNALS:
            self.assertIsInstance(name, str)
        self.assertTrue(hit_ids & set(ENTERPRISE_SIGNALS))


class TestProbes(unittest.TestCase):
    """提问预算由档位决定; 能查的事实绝不问人."""

    def test_quick_tier_asks_nothing(self) -> None:
        route = classify("帮我改个 typo")
        self.assertEqual(route.probes, [])
        self.assertEqual(route.to_dict()["probeBudget"], 0)

    def test_standard_tier_has_budget(self) -> None:
        route = classify("实现一个用户登录接口")
        self.assertEqual(route.to_dict()["probeBudget"], 3)
        decisions = [p for p in route.probes if p.kind == "decision"]
        self.assertTrue(decisions, "L1 至少要问出验收标准")
        for probe in decisions:
            self.assertTrue(probe.recommended, "每条要问的都必须带推荐答案")

    def test_facts_are_never_asked(self) -> None:
        route = classify("改造现有的登录模块")
        facts = [p for p in route.probes if p.kind == "fact"]
        self.assertTrue(any("技术栈" in p.title for p in facts))
        self.assertTrue(any("现状" in p.title for p in facts))

    def test_enterprise_tier_unbounded(self) -> None:
        self.assertEqual(classify("给客户做 MES，对接 SAP，要过等保").to_dict()["probeBudget"], 999)

    def test_standard_tier_mentions_escalation(self) -> None:
        route = classify("实现一个用户登录接口")
        self.assertTrue(any(p.kind == "escalation" for p in route.probes))


class TestReroute(unittest.TestCase):
    """答完之后重判. 归因只能算回答里新增的信号, 否则用户看不出是哪句改的档."""

    def test_upgrade_l1_to_l2_with_attribution(self) -> None:
        change, route = reroute(
            "加一个导出按钮",
            "导出是给财务对账用的，要走审批流程，还要对接金蝶的凭证接口",
        )
        self.assertEqual(change.before_tier, "L1")
        self.assertEqual(change.after_tier, "L2")
        self.assertEqual(change.direction, "upgrade")
        self.assertIn("BUSINESS_FLOW", change.new_signals)
        self.assertIn("INTEGRATION", change.new_signals)
        self.assertIn("不需要你判断", change.message)
        self.assertEqual(route.tier, "L2")

    def test_upgrade_jumps_two_tiers(self) -> None:
        change, _ = reroute("做个待办清单", "要给三个部门用，有审批流转，要过审计")
        self.assertEqual(change.direction, "upgrade")
        self.assertEqual(change.after_tier, "L2")

    def test_same_tier(self) -> None:
        change, route = reroute(
            "实现一个用户登录接口",
            "仓库管理员用；验收标准是手机号能收到验证码并登录成功",
        )
        self.assertEqual(change.direction, "same")
        self.assertEqual(route.tier, "L1")
        self.assertIn("档位不变", change.message)

    def test_internal_acceptance_is_not_customer_delivery(self) -> None:
        """「验收标准」是内部项目的常用词, 不该被当成对外客户交付."""
        route = classify("实现一个登录接口，验收标准是能收到验证码")
        self.assertNotIn("CUSTOMER", {h.id for h in route.hits})

    def test_answers_can_fill_gaps(self) -> None:
        change, _ = reroute(
            "实现一个用户登录接口",
            "仓库管理员用；验收标准是手机号能收到验证码并登录成功",
        )
        self.assertTrue(change.gaps_before)
        self.assertEqual(change.gaps_after, [])

    def test_downgrade_via_veto(self) -> None:
        """分数只增不减, 所以"缩水"只有否决词这条路."""
        change, _ = reroute("实现一个用户登录接口", "算了不用做了，先解释一下现有代码")
        self.assertEqual(change.direction, "downgrade")
        self.assertEqual(change.after_tier, "L0")

    def test_negation_requires_restatement(self) -> None:
        change, _ = reroute(
            "给客户做一套 MES，对接 SAP，要过等保",
            "其实不用对接 SAP 了，也不上线",
        )
        self.assertTrue(change.needs_restatement)
        self.assertIn("重述", change.message)
        # 不猜: 原文里的信号不会因为一句否定就消失
        self.assertEqual(change.after_tier, "L2")

    def test_no_false_attribution(self) -> None:
        """回答里重复原文已有的信号, 不算新归因."""
        change, _ = reroute("给客户做 MES，要过等保", "等保还是要过的")
        self.assertNotIn("COMPLIANCE", change.new_signals)


class TestSerialization(unittest.TestCase):
    def test_json_round_trip(self) -> None:
        route: Route = classify("做一个工单审批系统，多角色权限")
        payload = json.dumps(route.to_dict(), ensure_ascii=False)
        restored = json.loads(payload)
        self.assertEqual(restored["tier"], route.tier)
        self.assertEqual(restored["tierName"], route.meta["name"])
        self.assertIsInstance(restored["hits"], list)
        self.assertIsInstance(restored["dimensionScores"], dict)

    def test_markdown_has_core_sections(self) -> None:
        md = render_markdown(classify("做一个工单审批系统，多角色权限"), "原文")
        for section in ("# 档位判定", "## 分维度得分", "## 要跑的 stage", "## 下一步"):
            self.assertIn(section, md)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    unittest.main(verbosity=2)
