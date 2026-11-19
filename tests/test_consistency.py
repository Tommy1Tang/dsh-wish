#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档与代码一致性检查.

PLAN.md 里写的人审点数量必须等于 checkpoints_for() 返回的数量。
写这个脚本是因为踩过一次：PLAN 写着 L1 有两个检查点，代码只给了一个。

    python tests/test_consistency.py
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from router import TIER_META, checkpoints_for  # noqa: E402


class TestDocCodeConsistency(unittest.TestCase):
    def test_review_counts_match(self) -> None:
        for tier in ("L0", "L1", "L2"):
            with self.subTest(tier=tier):
                self.assertEqual(
                    TIER_META[tier]["review"],
                    len(checkpoints_for(tier)),
                    f"{tier} 文档写的人审数与代码不一致",
                )

    def test_plan_mentions_checkpoint_numbers(self) -> None:
        """PLAN 的检查点表要和代码对齐（0 / 2 / 4）."""
        plan = ROOT / "PLAN.md"
        if not plan.is_file():
            self.skipTest("PLAN.md 不存在")
        text = plan.read_text(encoding="utf-8")
        for tier, expected in (("L0", 0), ("L1", 2), ("L2", 4)):
            pattern = rf"\|\s*{tier}\s*\|\s*{expected}\b"
            self.assertRegex(text, pattern, f"PLAN 里 {tier} 应写 {expected} 个检查点")

    def test_every_profile_has_stages(self) -> None:
        from router import PROFILE_LABEL, PROFILE_STAGES

        for key in PROFILE_LABEL:
            with self.subTest(profile=key):
                self.assertIn(key, PROFILE_STAGES, f"{key} 没有 shape")
                self.assertTrue(PROFILE_STAGES[key], f"{key} 的 shape 是空的")

    def test_test_counts_in_plan_are_plausible(self) -> None:
        """PLAN 顶部写的测试总数不能比实际测试方法少.

        只认顶部那行 `> 测试：N` —— 别抓正文里的局部计数（踩过：抓到 §13 表格里的 40）。
        """
        plan = ROOT / "PLAN.md"
        if not plan.is_file():
            self.skipTest("PLAN.md 不存在")
        text = plan.read_text(encoding="utf-8")
        match = re.search(r"^> 测试：(\d+)", text, re.MULTILINE)
        self.assertIsNotNone(match, "PLAN 顶部应有 `> 测试：N` 一行")
        claimed = int(match.group(1))
        python_actual = sum(
            len(re.findall(r"^\s+def test_", path.read_text(encoding="utf-8"), re.MULTILINE))
            for path in (ROOT / "tests").glob("test_*.py")
        )
        node_actual = sum(
            len(re.findall(r"^test\(", path.read_text(encoding="utf-8"), re.MULTILINE))
            for path in (ROOT / "test").glob("*.mjs")
        )
        actual = python_actual + node_actual
        self.assertGreaterEqual(claimed, actual - 5, f"PLAN 声称 {claimed}，实际约 {actual}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    unittest.main(verbosity=2)
