#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""放弃条款（dropped）的测试.

    python tests/test_dropped.py

为什么单独一套：`dropped` 是最容易变成逃逸通道的状态。
"这活不用做"如果不需要理由和签字，它会立刻取代 `completed`。

核心断言：
1. 没有放弃条款的契约 = 不合格（E5）
2. 理由码不足 / 没有签字人 = 不合格（E6）
3. 四个理由码是固定枚举，不许自己编
4. focus 生成的契约自带这一节
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contract_lint import (  # noqa: E402
    DROPPED_REASONS,
    dropped_section,
    lint_text,
)
from focus import build_contract  # noqa: E402
from router import classify  # noqa: E402

BASE = """# 交付契约

## 2. 验收条目

### AC-01

- **判定方式**：点『导出』后下载 `待办.xlsx`，行数等于列表条数

> 反例：下载了空文件也算满足字面

## 3. 范围

### 本次不做

- 权限矩阵
"""

DROPPED_OK = """
## 6. 什么情况下可以放弃（dropped）

| 理由码 | 含义 | 确认人 |
| --- | --- | --- |
| `not-reproducible` | 复现不出来 | 提需求的人 |
| `obsolete` | 需求已废弃 | 业务方 |
"""


def rules(report) -> set[str]:
    return {f.rule for f in report.errors}


class TestDroppedRequired(unittest.TestCase):
    def test_missing_clause_blocks(self) -> None:
        report = lint_text(BASE)
        self.assertIn("E5", rules(report))

    def test_clause_present_passes(self) -> None:
        report = lint_text(BASE + DROPPED_OK)
        self.assertNotIn("E5", rules(report))
        self.assertNotIn("E6", rules(report))

    def test_empty_shell_blocks(self) -> None:
        report = lint_text(BASE + "\n## 6. 什么情况下可以放弃\n\n无\n")
        self.assertIn("E6", rules(report))


class TestDroppedContent(unittest.TestCase):
    def test_too_few_reason_codes(self) -> None:
        thin = """
## 6. 什么情况下可以放弃

| 理由码 | 含义 | 确认人 |
| --- | --- | --- |
| `obsolete` | 需求废弃 | 业务方 |
"""
        self.assertIn("E6", rules(lint_text(BASE + thin)))

    def test_missing_signer(self) -> None:
        no_signer = """
## 6. 什么情况下可以放弃

| 理由码 | 含义 |
| --- | --- |
| `not-reproducible` | 复现不出来 |
| `obsolete` | 需求废弃 |
"""
        self.assertIn("E6", rules(lint_text(BASE + no_signer)))

    def test_self_invented_code_does_not_count(self) -> None:
        """自己编的理由码不算 —— 否则等于没有理由."""
        invented = """
## 6. 什么情况下可以放弃

| 理由码 | 含义 | 确认人 |
| --- | --- | --- |
| `老板说不用了` | 随口一说 | 我 |
| `懒得做` | 太麻烦 | 我 |
"""
        self.assertIn("E6", rules(lint_text(BASE + invented)))

    def test_section_extraction(self) -> None:
        section = dropped_section(BASE + DROPPED_OK + "\n## 7. 确认\n\n| 确认人 | x |\n")
        self.assertIn("not-reproducible", section)
        self.assertNotIn("## 7", section)

    def test_english_heading_also_accepted(self) -> None:
        english = """
## 6. When a wish may be dropped

| Code | Meaning | Signer |
| --- | --- | --- |
| `not-reproducible` | cannot reproduce | requester |
| `out-of-scope` | not our scope | owner |
"""
        report = lint_text(BASE + english)
        self.assertNotIn("E5", rules(report))
        self.assertNotIn("E6", rules(report))


class TestReasonCodes(unittest.TestCase):
    def test_exactly_four_codes(self) -> None:
        self.assertEqual(
            set(DROPPED_REASONS),
            {"not-reproducible", "obsolete", "already-exists", "out-of-scope"},
        )


class TestFocusGeneratesClause(unittest.TestCase):
    def test_generated_contract_has_clause(self) -> None:
        route = classify("实现一个用户登录接口")
        answers = [
            {"title": "怎么算做完了", "answer": "登录成功，10 秒内返回", "recommend": ""},
            {"title": "不做什么", "answer": "权限矩阵", "recommend": ""},
        ]
        contract = build_contract(route, "实现一个用户登录接口", answers)
        self.assertIn("什么情况下可以放弃", contract)
        for code in DROPPED_REASONS:
            self.assertIn(code, contract)

    def test_generated_contract_passes_lint(self) -> None:
        """生成的契约应当只在 AC 的反例上缺东西，不该缺放弃条款."""
        route = classify("实现一个用户登录接口")
        answers = [
            {"title": "怎么算做完了", "answer": "登录成功，10 秒内返回", "recommend": ""},
            {"title": "不做什么", "answer": "权限矩阵", "recommend": ""},
        ]
        contract = build_contract(route, "实现一个用户登录接口", answers)
        report = lint_text(contract)
        self.assertNotIn("E5", rules(report))
        self.assertNotIn("E6", rules(report))


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    unittest.main(verbosity=2)
