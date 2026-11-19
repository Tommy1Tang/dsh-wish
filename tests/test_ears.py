#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EARS 句式与状态覆盖的测试.

    python tests/test_ears.py

来源：github.com/82030615/write-ears-prd-skill 的两条硬规则，改造成可机械检查的：
- E7 涉及状态/异常的判定方式必须用 EARS 句式（When/While/If/Where 或 当/在/如果）
- E8 声明了状态枚举，每个状态都必须有 AC 覆盖

为什么值得抄：
- E4 只能查"有没有可观测名词"，查不了"这句话有几种读法"，E7 补这一半
- 漏掉一个状态不会让任何测试变红（没写的状态自然没有对应用例），只有 E8 能抓
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_lint import lint_text, parse_states, state_section  # noqa: E402

HEAD = """# 交付契约

## 2. 验收条目
"""

TAIL = """
### 本次不做
- 权限矩阵

## 6. 什么情况下可以放弃

| 理由码 | 含义 | 确认人 |
| --- | --- | --- |
| `not-reproducible` | 复现不出来 | 提需求的人 |
| `obsolete` | 需求已废弃 | 业务方 |
"""


def contract(acs: str, extra: str = "") -> str:
    return HEAD + acs + TAIL + extra


def rules(report) -> set[str]:
    return {f.rule for f in report.errors}


class TestEarsSyntax(unittest.TestCase):
    def test_state_ac_without_ears_blocks(self) -> None:
        acs = """
### AC-01
- **判定方式**：订单状态变化时通知用户，失败要重试
> 反例：通知发了但用户没收到 —— 字面通过，实际没达
"""
        self.assertIn("E7", rules(lint_text(contract(acs))))

    def test_english_when_prefix_passes(self) -> None:
        acs = """
### AC-01
- **判定方式**：When 用户提交订单，系统创建订单并把状态置为待支付，列表出现 1 条新记录
> 反例：订单创建了但状态还是草稿 —— 记录数对上了，状态没换
"""
        self.assertNotIn("E7", rules(lint_text(contract(acs))))

    def test_english_while_prefix_passes(self) -> None:
        acs = """
### AC-01
- **判定方式**：While 订单处于待支付状态期间，系统保留库存且取消按钮可点
> 反例：按钮可见但点击报错 —— 看着能取消，实际不能
"""
        self.assertNotIn("E7", rules(lint_text(contract(acs))))

    def test_chinese_prefix_passes(self) -> None:
        for prefix in ("当用户提交订单时，系统创建 1 条订单记录",
                       "在订单待支付期间，库存保留且取消按钮可点",
                       "如果订单已取消，系统拒绝支付回调"):
            with self.subTest(prefix=prefix):
                acs = f"""
### AC-01
- **判定方式**：{prefix}
> 反例：界面上看不出区别
"""
                self.assertNotIn("E7", rules(lint_text(contract(acs))))

    def test_plain_ui_ac_is_not_required(self) -> None:
        """纯界面类 AC 不涉及状态/异常，不强制 EARS —— 强制了反而别扭."""
        acs = """
### AC-01
- **判定方式**：首页在 1920×1080 下首屏 2 秒内渲染完成，标题居中
> 反例：白屏 1.9 秒后出现 —— 达标但体感是"卡了一下"
"""
        self.assertNotIn("E7", rules(lint_text(contract(acs))))


class TestStateCoverage(unittest.TestCase):
    STATES = """
## 7. 状态枚举

| 状态 | 说明 |
| --- | --- |
| 待支付 | 已下单未付款 |
| 已取消 | 用户或系统取消 |
"""

    def test_missing_state_blocks(self) -> None:
        acs = """
### AC-01
- **判定方式**：When 用户提交订单，系统创建订单并把状态置为待支付
> 反例：只写了草稿没进待支付
"""
        self.assertIn("E8", rules(lint_text(contract(acs, self.STATES))))

    def test_all_states_covered_passes(self) -> None:
        acs = """
### AC-01
- **判定方式**：When 用户提交订单，系统创建订单并把状态置为待支付
> 反例：只写了草稿没进待支付
### AC-02
- **判定方式**：When 用户点取消，系统把状态改为已取消并释放库存
> 反例：状态改了但库存没放
"""
        self.assertNotIn("E8", rules(lint_text(contract(acs, self.STATES))))

    def test_no_state_section_is_skipped(self) -> None:
        """没声明状态 = 纯 UI 或纯数据类需求，不适用."""
        acs = """
### AC-01
- **判定方式**：在列表页点『导出』，下载 `待办.xlsx`，行数等于列表条数
> 反例：下载了空文件
"""
        self.assertNotIn("E8", rules(lint_text(contract(acs))))

    def test_state_section_parsing(self) -> None:
        self.assertEqual(parse_states(self.STATES), ["待支付", "已取消"])

    def test_header_row_is_not_a_state(self) -> None:
        section = """
| 状态 | 说明 |
| --- | --- |
| 待支付 | x |
"""
        self.assertEqual(parse_states(section), ["待支付"])

    def test_english_heading(self) -> None:
        section = "## States\n\n| State | Note |\n| --- | --- |\n| pending | x |\n"
        # 英文场景解析到 `pending` 即可，不要求 locale 一致
        self.assertIn("pending", parse_states(state_section(section)))

    def test_template_placeholders_are_not_states(self) -> None:
        """模板里的 {{STATE_1}} 不是状态 —— 占位符不是内容."""
        section = "\n## 状态枚举\n\n| 状态 | 说明 |\n| --- | --- |\n| {{STATE_1}} | x |\n"
        self.assertEqual(parse_states(state_section(section)), [])

    def test_fill_hint_is_not_a_state(self) -> None:
        section = "\n## 状态枚举\n\n| 状态 | 说明 |\n| --- | --- |\n| （填：如「待支付」） | x |\n"
        self.assertEqual(parse_states(state_section(section)), [])

    def test_empty_section_blocks(self) -> None:
        empty = "\n## 7. 状态枚举\n\n| 状态 | 说明 |\n| --- | --- |\n"
        acs = """
### AC-01
- **判定方式**：When 用户提交订单，系统创建 1 条记录
> 反例：没建出来
"""
        self.assertIn("E8", rules(lint_text(contract(acs, empty))))


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    unittest.main(verbosity=2)
