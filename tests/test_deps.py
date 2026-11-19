#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""执行体探测与降级的测试.

    python tests/test_deps.py

核心断言：**没装 agent-delivery-gate 也必须能用**。
别人装上这个 skill 时机器上没有那两个项目，降级不是残缺，是默认路径。
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import deps  # noqa: E402
from router import classify  # noqa: E402


class TestDetection(unittest.TestCase):
    def tearDown(self) -> None:
        deps.set_gate_available(None)

    def test_override_true(self) -> None:
        deps.set_gate_available(True)
        self.assertTrue(deps.gate_available())

    def test_override_false(self) -> None:
        deps.set_gate_available(False)
        self.assertFalse(deps.gate_available())

    def test_env_var_points_at_fake_gate(self) -> None:
        deps.set_gate_available(None)
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp)
            (fake / "scripts").mkdir()
            (fake / "scripts" / "validate_delivery.py").write_text("", encoding="utf-8")
            with mock.patch.dict(os.environ, {deps.ENV_KEY: str(fake)}):
                self.assertEqual(deps.gate_root(), fake)
                self.assertTrue(deps.gate_available())

    def test_env_var_pointing_nowhere(self) -> None:
        deps.set_gate_available(None)
        with mock.patch.dict(os.environ, {deps.ENV_KEY: "/definitely/not/here"}):
            # 其他候选路径仍可能命中（开发机），所以只断言不抛异常
            self.assertIsInstance(deps.gate_available(), bool)

    def test_describe_is_honest(self) -> None:
        deps.set_gate_available(False)
        self.assertIn("通用版", deps.describe())
        deps.set_gate_available(True)
        self.assertTrue("精确版" in deps.describe())
        deps.set_gate_available(False)


class TestDegradation(unittest.TestCase):
    def tearDown(self) -> None:
        deps.set_gate_available(None)

    def test_auto_mode_follows_detection(self) -> None:
        deps.set_gate_available(False)
        self.assertEqual(classify("实现一个登录接口").execution, "generic")
        deps.set_gate_available(True)
        self.assertEqual(classify("实现一个登录接口").execution, "precise")

    def test_generic_still_gives_full_checkpoints(self) -> None:
        """降级不该削减人审点 —— 那是判档的事，跟执行体无关."""
        deps.set_gate_available(False)
        route = classify("做一个工单审批系统，多角色权限，要上线")
        self.assertEqual(len(route.checkpoints), 4)

    def test_generic_keeps_probes_and_risks(self) -> None:
        deps.set_gate_available(False)
        route = classify("齐套报表的齐套率算法要改，现在是按数量，要改成按金额")
        self.assertTrue(any("行为变更" in flag for flag in route.risk_flags))
        self.assertTrue(any(p.title == "历史数据怎么处理" for p in route.probes))

    def test_generic_json_marks_execution(self) -> None:
        deps.set_gate_available(False)
        data = classify("实现一个登录接口").to_dict()
        self.assertEqual(data["execution"], "generic")

    def test_generic_has_no_dangling_references(self) -> None:
        """通用版里不能出现只有本机才有的路径或编号."""
        deps.set_gate_available(False)
        forbidden = ("SP-", "validate_delivery", "pipeline_runner",
                     "research-to-project-input", "approve --gate")
        samples = [
            "做一个前后端都有的工单系统",
            "把历史订单数据迁移到新表",
            "接口报错了，登录一直 500",
            "帮我把项目部署到测试环境",
        ]
        for text in samples:
            with self.subTest(wish=text):
                stages = " ".join(classify(text).stages)
                for token in forbidden:
                    self.assertNotIn(token, stages)


class TestPreciseMode(unittest.TestCase):
    def tearDown(self) -> None:
        deps.set_gate_available(None)

    def test_precise_keeps_specific_nodes(self) -> None:
        deps.set_gate_available(True)
        stages = " ".join(classify("做一个前后端都有的工单系统").stages)
        self.assertIn("SP-", stages)

    def test_profiles_are_same_in_both_modes(self) -> None:
        deps.set_gate_available(True)
        precise = classify("把历史订单数据迁移到新表")
        deps.set_gate_available(False)
        generic = classify("把历史订单数据迁移到新表")
        self.assertEqual(precise.profile, generic.profile)
        self.assertEqual(precise.stages, generic.stages, "data 的 shape 本来就是通用的")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    unittest.main(verbosity=2)
