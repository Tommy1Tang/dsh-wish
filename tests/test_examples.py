#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""examples/ 下两份契约的测试.

    python tests/test_examples.py

为什么单独为"例子"写测试：**例子会腐坏**。
改了 lint 规则之后，好例子可能突然 FAIL、坏例子可能突然 PASS，
而 README 里还写着"坏例子会命中 9 条规则"——那就成了骗人的文档。

这个测试把两份例子的判定结果钉死。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contract_lint import lint_text  # noqa: E402

EXAMPLES = ROOT / "examples"


def read(name: str) -> str:
    return (EXAMPLES / name).read_text(encoding="utf-8")


class TestGoodExample(unittest.TestCase):
    def setUp(self) -> None:
        self.report = lint_text(read("contract-good.md"))

    def test_passes(self) -> None:
        self.assertTrue(
            self.report.ok,
            "合格例子不该 FAIL：" + "；".join(f"{f.rule} {f.message}" for f in self.report.errors),
        )

    def test_has_enough_acs(self) -> None:
        self.assertGreaterEqual(self.report.ac_count, 5)

    def test_has_no_errors_only_warnings(self) -> None:
        self.assertEqual(self.report.errors, [])


class TestBadExample(unittest.TestCase):
    def setUp(self) -> None:
        self.report = lint_text(read("contract-bad.md"))

    def test_fails(self) -> None:
        self.assertFalse(self.report.ok, "不合格例子必须 FAIL")

    def test_triggers_expected_rules(self) -> None:
        """README 里逐条列了它犯的错，这里逐条对上。"""
        expected = {"E1", "E2", "E3", "E4", "E5", "E7", "E8", "S1", "S2"}
        actual = {f.rule for f in self.report.errors}
        self.assertEqual(
            actual, expected,
            f"触发规则变了。多出 {actual - expected}，少了 {expected - actual}；"
            "记得同步更新 examples/README.md",
        )

    def test_soft_vague_only_warns(self) -> None:
        self.assertIn("W2", {f.rule for f in self.report.warnings})


class TestExamplesDir(unittest.TestCase):
    def test_both_files_exist(self) -> None:
        self.assertTrue((EXAMPLES / "contract-good.md").is_file())
        self.assertTrue((EXAMPLES / "contract-bad.md").is_file())
        self.assertTrue((EXAMPLES / "README.md").is_file())

    def test_no_placeholder_left_in_good(self) -> None:
        """合格例子里不该残留 {{...}} 占位符。"""
        self.assertNotIn("{{", read("contract-good.md"))


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    unittest.main(verbosity=2)
