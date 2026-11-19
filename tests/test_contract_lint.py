#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""contract_lint 的单元测试.

    python tests/test_contract_lint.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contract_lint import lint_text, split_acs  # noqa: E402

GOOD = """# 交付契约
## 2. 验收条目
### AC-01 导出
- **判定方式**：在列表页点『导出』，下载 `待办.xlsx`，行数等于列表条数
> 反例：下载了空文件也算满足字面

### AC-02 提交
- **判定方式**：点『提交』后 2 秒内页面出现新行
> 反例：后端 200ms 返回但前端轮询 10 秒

### 本次不做
- 权限矩阵

## 6. 什么情况下可以放弃

| 理由码 | 含义 | 确认人 |
| --- | --- | --- |
| `not-reproducible` | 复现不出来 | 提需求的人 |
| `obsolete` | 需求已废弃 | 业务方 |
"""


def rules(report) -> set[str]:
    return {f.rule for f in report.errors}


class TestLint(unittest.TestCase):
    def test_good_contract_passes(self) -> None:
        report = lint_text(GOOD)
        self.assertTrue(report.ok, [f.message for f in report.errors])
        self.assertEqual(report.ac_count, 2)

    def test_missing_counterexample(self) -> None:
        text = GOOD.replace("> 反例：下载了空文件也算满足字面", "")
        self.assertIn("E1", rules(lint_text(text)))

    def test_empty_counterexample_counts_as_missing(self) -> None:
        text = GOOD.replace("> 反例：下载了空文件也算满足字面", "> 反例：")
        self.assertIn("E1", rules(lint_text(text)))

    def test_missing_verdict(self) -> None:
        text = GOOD.replace(
            "- **判定方式**：点『提交』后 2 秒内页面出现新行", "- 点『提交』后 2 秒内出现新行"
        )
        self.assertIn("E2", rules(lint_text(text)))

    def test_verdict_with_parenthetical_is_accepted(self) -> None:
        text = GOOD.replace("- **判定方式**：点『提交』", "- **判定方式**（可写成测试）：点『提交』")
        report = lint_text(text)
        self.assertNotIn("E2", rules(report))

    def test_vague_words_block(self) -> None:
        text = GOOD.replace("点『提交』后 2 秒内页面出现新行", "提交后体验要友好流畅")
        self.assertIn("E3", rules(lint_text(text)))

    def test_nothing_observable_blocks(self) -> None:
        text = GOOD.replace(
            "在列表页点『导出』，下载 `待办.xlsx`，行数等于列表条数", "把数据导出来"
        )
        self.assertIn("E4", rules(lint_text(text)))

    def test_blockquote_does_not_count_as_observable(self) -> None:
        """`> 反例：` 里的 `>` 不能被当成"数量关系" —— 这是踩过的假阳性."""
        text = """# 契约
### AC-01
- **判定方式**：把数据导出来
> 反例：导出的数据不全
### 本次不做
- 权限
"""
        self.assertIn("E4", rules(lint_text(text)))

    def test_empty_out_of_scope(self) -> None:
        text = GOOD.replace("- 权限矩阵", "- {{OUT_OF_SCOPE}}")
        self.assertIn("S1", rules(lint_text(text)))

    def test_missing_out_of_scope_section(self) -> None:
        text = GOOD.split("### 本次不做")[0]
        self.assertIn("S1", rules(lint_text(text)))

    def test_ac_numbering_must_be_continuous(self) -> None:
        text = GOOD.replace("### AC-02", "### AC-03")
        self.assertIn("S2", rules(lint_text(text)))

    def test_no_acs_at_all(self) -> None:
        report = lint_text("# 契约\n## 范围\n### 本次不做\n- 权限\n")
        self.assertIn("E0", rules(report))

    def test_unfilled_template_fails_loudly(self) -> None:
        """未填的模板必须 FAIL —— 否则 lint 等于没有."""
        template = Path(__file__).resolve().parents[1] / "templates" / "contract.template.md"
        if not template.is_file():
            self.skipTest("模板不存在")
        report = lint_text(template.read_text(encoding="utf-8"))
        self.assertFalse(report.ok)
        self.assertIn("E1", rules(report))
        self.assertIn("E2", rules(report))


class TestSplit(unittest.TestCase):
    def test_split_by_heading(self) -> None:
        blocks = split_acs(GOOD)
        self.assertEqual([b.ac_id for b in blocks], ["AC-01", "AC-02"])

    def test_heading_title_kept(self) -> None:
        blocks = split_acs(GOOD)
        self.assertEqual(blocks[0].title, "导出")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    unittest.main(verbosity=2)
