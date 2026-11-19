#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交付契约机械检查 (lint_contract).

PLAN §7 写了三条硬规则, 但"写在文档里"等于没写。这个脚本把它们变成退出码。

检查项
------
E1  每条 AC 必须附 `> 反例：`          —— 反向判据, 举得出反例才算钉住
E2  每条 AC 必须有判定方式             —— 没有判定方式就无法验收
E3  不得出现模糊词                     —— 友好/合理/尽量/快速/…
E4  每条 AC 至少一个可观测对象          —— 数字/文件名/引号内名称/比较符/字段名
W1  每条 AC 至少一处具体名词（软提示）   —— 只有动词的 AC 通常是"能跑就行"
S1  「本次不做」不得为空                —— 防范围蔓延最便宜的一招
S2  AC 编号必须连续                     —— AC-01, AC-02, …
E5  必须有「放弃条款」                  —— 否则"这活不用做"只能伪装成完成或卡住
E6  放弃条款必须给理由码 + 签字人        —— 否则它是最顺手的逃逸通道
E7  状态/异常类 AC 必须用 EARS 句式       —— 把"只有一种读法"从靠人判断变成靠句式
E8  声明了状态枚举就必须每个状态有覆盖     —— 漏场景是需求缺陷里最常见的一种

用法
----
    python contract_lint.py contract.md
    python contract_lint.py contract.md --json
    python contract_lint.py --selftest

退出码: 0 = 通过（可含警告）, 1 = 有阻断项, 2 = 文件不可读
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ===========================================================================
# 规则表 —— 想改口径只改这里
# ===========================================================================

VAGUE_WORDS = [
    "友好", "合理", "尽量", "快速", "适当", "较好", "完善", "优化一下",
    "简洁", "美观", "流畅", "稳定", "高效", "满意", "良好", "易用",
]

# 可观测对象: 任何一条命中即算"说得具体"
OBSERVABLE_PATTERNS = [
    (r"\d+(?:\.\d+)?\s*(?:秒|毫秒|ms|条|行|个|次|%|元|字|px|MB|KB)", "数字+单位"),
    (r"[A-Za-z_][A-Za-z0-9_\-]*\.(?:xlsx|csv|json|md|txt|pdf|log|yaml|yml)", "文件名"),
    (r"[「『\"“][^」』\"”]{2,}[」』\"”]", "引号内具体名称"),
    (r"(?:第[一二三四五六七八九十\d]+列|表头|字段名|列名|按钮|输入框|下拉|页签)", "界面元素"),
    (r"(?:=|==|等于|大于|小于|不超过|不少于|≥|≤|>|<)", "数量关系"),
    (r"(?:AC-\d+|\d{4}-\d{2}-\d{2}|\d{2}:\d{2})", "标识或时间"),
]

AC_HEADING = r"^###\s+(AC-\d+)\s*(.*)$"
COUNTEREXAMPLE = r"^\s*>\s*反例[:：]\s*(\S.*)$"
VERDICT_LINE = (
    r"^\s*[-*]?\s*\*\*判定方式\*\*\s*(?:（[^）]*）|\([^)]*\))?\s*[:：]\s*(.+)$"
    r"|^\s*[-*]?\s*判定方式\s*(?:（[^）]*）|\([^)]*\))?\s*[:：]\s*(.+)$"
)
SCOPE_HEADING = r"^###?\s*(?:本次做|本次不做)\s*$"

# 未填的模板占位符. 占位符不是内容 —— 把它当内容会让空模板"看起来合格".
PLACEHOLDER = r"\{\{[^}]*\}\}"

# --- 放弃条款 -------------------------------------------------------------
# dropped 不是"跳过"，是"确认不做"。缺了它，执行者只能用 completed（假装做完）
# 或 blocked（触发返工）来表达"这活不该做"—— 两种都污染证据链。
DROPPED_HEADING = r"^#{2,3}\s*.*(?:放弃|dropped|不做的情况|废弃)"
# 允许的放弃理由码。固定枚举，不许自己编 —— 编出来的理由等于没有理由。
DROPPED_REASONS = (
    "not-reproducible",   # 复现不出来
    "obsolete",           # 需求已过时/废弃
    "already-exists",     # 现有功能已覆盖
    "out-of-scope",       # 不属本项目范围
)
# 每个理由后面必须能追到"谁确认的"
DROPPED_SIGNER = r"(确认人|签字|确认|谁同意|approver|signer|approved by|sign[- ]?off)"

# --- EARS 句式 ------------------------------------------------------------
# 来源：github.com/82030615/write-ears-prd-skill（EARS 规范）。
# 只吸收两条可机械检查的规则，不引入它的 PRD 模板——
# 那是"一个系统的需求规格"，这里是"一次交付的验收依据"，不是一回事。
#
# 为什么需要：E4 只能查"有没有可观测名词"，查不了"这句话有几种读法"。
# EARS 把需求强制拆成「触发条件 + 系统 + 响应」，读法被压到一种。
EARS_PREFIX = r"^\s*(?:\*\*)?(When|While|If|Where|Complex|当|在|如果|若|一旦)"
# 什么时候**必须**用 EARS：需求里出现状态流转或异常分支。
EARS_REQUIRED_HINT = r"(状态|流转|期间|超时|失败|不足|冲突|不存在|重复|越界|为空|已取消|已完成)"

# --- 状态 × 事件覆盖 -------------------------------------------------------
# EARS 的「组合覆盖度矩阵」。声明了状态枚举就必须每个状态都有需求覆盖，
# 否则"漏掉一个状态"这种最常见的需求缺陷，lint 一个字都不会说。
STATE_HEADING = r"^#{2,3}\s*.*(?:状态与事件|状态枚举|状态机|states?)"
# 表格行里第一列的状态名：`| 待支付 | ... |`
STATE_ROW = r"^\|\s*([^|\-\s][^|]*?)\s*\|"


# ===========================================================================
# 结果模型
# ===========================================================================


@dataclass
class Finding:
    rule: str
    level: str          # error | warning
    where: str          # AC-01 / 范围 / 文档
    message: str

    def to_dict(self) -> dict:
        return {"rule": self.rule, "level": self.level, "where": self.where, "message": self.message}


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    ac_count: int = 0

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, rule: str, level: str, where: str, message: str) -> None:
        self.findings.append(Finding(rule, level, where, message))

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "acCount": self.ac_count,
            "errors": [f.to_dict() for f in self.errors],
            "warnings": [f.to_dict() for f in self.warnings],
        }


# ===========================================================================
# 解析
# ===========================================================================


@dataclass
class AcBlock:
    ac_id: str
    title: str
    lines: list[str]

    @property
    def body(self) -> str:
        return "\n".join(self.lines)

    @property
    def stripped_body(self) -> str:
        """去掉未填的占位符后的正文."""
        return re.sub(PLACEHOLDER, "", self.body)

    def has_counterexample(self) -> bool:
        clean = self.stripped_body
        return any(
            re.search(COUNTEREXAMPLE, line)
            for line in clean.splitlines()
        )

    def verdict_text(self) -> str:
        for line in self.stripped_body.splitlines():
            match = re.search(VERDICT_LINE, line)
            if match:
                return (match.group(1) or match.group(2) or "").strip()
        return ""


def split_acs(text: str) -> list[AcBlock]:
    blocks: list[AcBlock] = []
    current: AcBlock | None = None
    for line in text.splitlines():
        match = re.match(AC_HEADING, line)
        if match:
            if current:
                blocks.append(current)
            current = AcBlock(match.group(1), match.group(2).strip(), [])
            continue
        if current is not None:
            # 遇到同级或更高级标题就结束当前块
            if re.match(r"^#{1,3}\s+", line) and not re.match(AC_HEADING, line):
                blocks.append(current)
                current = None
                continue
            current.lines.append(line)
    if current:
        blocks.append(current)
    return blocks


def scope_section_empty(text: str, heading_kw: str) -> bool:
    """判断 `### 本次不做` 段落是否为空（没有实质内容行）。"""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(rf"^###?\s*{heading_kw}\s*$", line):
            start = i + 1
            break
    if start is None:
        return True
    for line in lines[start:]:
        stripped = line.strip()
        if re.match(r"^#{1,3}\s+", line):
            break
        if not stripped:
            continue
        if re.fullmatch(r"[-*]\s*", stripped):        # 空 bullet
            continue
        if re.search(r"\{\{[^}]+\}\}", stripped):     # 未替换的占位符
            continue
        if stripped in ("无", "暂无"):
            continue
        return False
    return True


# ===========================================================================
# 检查
# ===========================================================================


def lint_text(text: str) -> Report:
    report = Report()
    acs = split_acs(text)
    report.ac_count = len(acs)

    if not acs:
        report.add("E0", "error", "文档", "没有找到任何 `### AC-NN` 验收条目")
        return report

    expected = [f"AC-{i:02d}" for i in range(1, len(acs) + 1)]
    actual = [ac.ac_id for ac in acs]
    if actual != expected:
        report.add("S2", "error", "文档", f"AC 编号不连续：期望 {expected}，实际 {actual}")

    for ac in acs:
        body = ac.stripped_body

        # E1 反例
        if not ac.has_counterexample():
            report.add("E1", "error", ac.ac_id,
                       "缺 `> 反例：`。举不出反例说明这条 AC 还没钉住")

        # E2 判定方式
        if not ac.verdict_text():
            report.add("E2", "error", ac.ac_id, "缺判定方式")

        # E3 模糊词
        hits = [word for word in VAGUE_WORDS if word in body]
        if hits:
            report.add("E3", "error", ac.ac_id, f"出现模糊词：{'、'.join(hits)}")

        # E7 EARS 句式：涉及状态流转/异常分支的 AC 必须用 EARS 开头
        verdict = ac.verdict_text()
        if verdict and re.search(EARS_REQUIRED_HINT, verdict):
            if not re.search(EARS_PREFIX, verdict, re.IGNORECASE):
                report.add(
                    "E7", "error", ac.ac_id,
                    "涉及状态/异常，判定方式必须以 EARS 句式开头"
                    "（When/While/If/Where 或 当/在/如果），否则有多种读法",
                )

        # E4 可观测对象（只看正文，不看 `> 反例：` 里的内容 ——
        #    反例是"通过但不满足"的例子，它的具体性不能算这条 AC 的具体性）
        prose = "\n".join(
            line for line in body.splitlines()
            if not line.lstrip().startswith(">")
        )
        markers = [
            label for pattern, label in OBSERVABLE_PATTERNS
            if re.search(pattern, prose)
        ]
        if not markers:
            report.add("E4", "error", ac.ac_id,
                       "没有任何可观测对象（数字/文件名/引号内名称/界面元素/数量关系）")
        elif len(markers) == 1:
            report.add("W1", "warning", ac.ac_id,
                       f"只有一类可观测对象（{markers[0]}），可能仍不够具体")

    # S1 本次不做
    if scope_section_empty(text, "本次不做"):
        report.add("S1", "error", "范围",
                   "「本次不做」为空。这是防范围蔓延最便宜的一招，必须写")

    check_dropped(text, report)
    check_state_coverage(text, acs, report)
    return report


def state_section(text: str) -> str:
    """切出「状态与事件 / 状态枚举」那一节。没有就返回空串（跳过检查）。"""
    lines = text.splitlines()
    start = level = None
    for index, line in enumerate(lines):
        match = re.match(r"^(#{2,3})\s*.*?(?:状态与事件|状态枚举|状态机|states?\b)",
                         line, re.IGNORECASE)
        if match:
            start, level = index + 1, len(match.group(1))
            break
    if start is None:
        return ""
    body: list[str] = []
    for line in lines[start:]:
        heading = re.match(r"^(#{1,6})\s+", line)
        if heading and len(heading.group(1)) <= level:
            break
        body.append(line)
    return "\n".join(body)


def parse_states(section: str) -> list[str]:
    """从表格第一列提取状态名。跳过表头行、分隔行、以及 `-` / `N/A` 这类占位。"""
    states: list[str] = []
    for line in section.splitlines():
        match = re.match(STATE_ROW, line)
        if not match:
            continue
        name = match.group(1).strip().strip("`* ")
        if not name or name in ("状态", "State", "状态名", "—", "-", "N/A"):
            continue
        if set(name) <= set("-: "):
            continue
        if "{{" in name:
            continue        # 未填的模板占位符不是状态
        if name.startswith(("（", "(")) and name.endswith(("）", ")")):
            continue        # 「（填：如『待支付』）」这种填写提示不是状态
        states.append(name)
    return states


def check_state_coverage(text: str, acs: list[AcBlock], report: Report) -> None:
    """E8：声明了状态枚举，就必须每个状态都有 AC 覆盖。

    「漏掉一个状态」是需求缺陷里最常见的一种，而且**不会让任何测试变红** ——
    因为没写的状态自然也就没有对应用例。所以只能在这里查。
    """
    section = state_section(text)
    if not section.strip():
        return          # 没声明状态 = 纯 UI 或纯数据类需求，不适用

    states = parse_states(section)
    if not states:
        report.add("E8", "error", "状态枚举", "这一节没有可识别的状态（表格第一列）")
        return

    haystack = "\n".join(ac.stripped_body for ac in acs)
    missing = [state for state in states if state not in haystack]
    if missing:
        report.add(
            "E8", "error", "状态枚举",
            f"这些状态没有任何 AC 覆盖：{'、'.join(missing)}"
            "（漏状态不会让测试变红，只会让需求缺一块）",
        )


def dropped_section(text: str) -> str:
    """切出「放弃条款」那一节（到下一个同级或更高级标题为止）。"""
    lines = text.splitlines()
    start = level = None
    for index, line in enumerate(lines):
        match = re.match(r"^(#{2,3})\s*.*?(?:放弃|dropped|不做的情况|废弃)", line, re.IGNORECASE)
        if match:
            start, level = index + 1, len(match.group(1))
            break
    if start is None:
        return ""
    body: list[str] = []
    for line in lines[start:]:
        heading = re.match(r"^(#{1,6})\s+", line)
        if heading and len(heading.group(1)) <= level:
            break
        body.append(line)
    return "\n".join(body)


def check_dropped(text: str, report: Report) -> None:
    """E5/E6：放弃条款必须存在，且必须给理由码 + 签字人。

    为什么是 error 而不是 warning：没有放弃条款的契约，等于逼执行者
    用 `completed`（假装做完）或 `blocked`（触发返工）来表达"这活不该做"。
    两种都在污染证据链。
    """
    section = dropped_section(text)
    if not section.strip():
        report.add(
            "E5", "error", "放弃条款",
            "缺「什么情况下可以放弃」。没有这一节，执行者只能用"
            "「完成」或「卡住」来表达「这活不该做」",
        )
        return

    found = [code for code in DROPPED_REASONS if code in section]
    if len(found) < 2:
        report.add(
            "E6", "error", "放弃条款",
            f"理由码不足（找到 {found or '无'}）。至少给 2 个，"
            f"可选：{' / '.join(DROPPED_REASONS)}",
        )

    if not re.search(DROPPED_SIGNER, section, re.IGNORECASE):
        report.add(
            "E6", "error", "放弃条款",
            "没有签字人。放弃必须有人确认，否则它是最顺手的逃逸通道",
        )

    # 只要用了 `无` 之类的空壳占位，视为没写
    if re.fullmatch(r"[\s\-|:：]*(无|暂无|N/A)[\s\-|:：]*", section.strip()):
        report.add("E6", "error", "放弃条款", "这一节是空的")


# ===========================================================================
# 渲染 / CLI
# ===========================================================================


def render(report: Report) -> str:
    lines = [f"契约检查：{'PASS' if report.ok else 'FAIL'}", f"AC 条数：{report.ac_count}", ""]
    for f in report.errors:
        lines.append(f"  ✗ [{f.rule}] {f.where}：{f.message}")
    for f in report.warnings:
        lines.append(f"  ! [{f.rule}] {f.where}：{f.message}")
    if not report.findings:
        lines.append("  无问题")
    return "\n".join(lines)


SELFTEST_GOOD = """# 交付契约
## 2. 验收条目
### AC-01
- **判定方式**：在待办列表页点『导出』，浏览器下载 `待办.xlsx`，数据行数等于当前列表条数
> 反例：下载了空文件也算满足字面
### AC-02
- **判定方式**：点『提交』后 2 秒内页面出现新行
> 反例：后端 200ms 返回，前端轮询 10 秒
### AC-03
- **判定方式**：While 订单处于待支付状态期间，系统保留库存；该状态下的取消按钮可见可点
> 反例：状态显示待支付，但取消按钮是灰的 —— 字面满足，行为不通
### AC-04
- **判定方式**：If 订单已取消，则系统拒绝后续支付回调，且列表显示「已取消」标签
> 反例：回调返回成功但状态仍是已取消 —— 看起来被拒了，实际没拒

### 本次不做
- 权限矩阵

## 6. 什么情况下可以放弃

| 理由码 | 含义 | 确认人 |
| --- | --- | --- |
| `not-reproducible` | 复现不出来 | 提需求的人 |
| `obsolete` | 需求已废弃 | 业务方 |

## 7. 状态枚举

| 状态 | 说明 |
| --- | --- |
| 待支付 | 已下单未付款 |
| 已取消 | 用户或系统取消 |
"""

SELFTEST_BAD = """# 交付契约
## 2. 验收条目
### AC-01
- **判定方式**：导出功能要友好易用
### AC-02
- **判定方式**：订单状态变化时要通知，失败时要重试
> 反例：通知发了但没人收到
### 本次不做
- {{OUT_OF_SCOPE_1}}
"""


def selftest() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    good = lint_text(SELFTEST_GOOD)
    bad = lint_text(SELFTEST_BAD)
    print("== 合格样例 ==")
    print(render(good))
    print()
    print("== 不合格样例 ==")
    print(render(bad))
    print()
    ok = good.ok and not bad.ok
    print("自检：" + ("通过" if ok else "失败"))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(
        description="交付契约机械检查",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("path", nargs="?", help="contract.md 路径")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--selftest", action="store_true", help="跑内置样例")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.path:
        parser.error("需要一个 contract.md 路径")

    try:
        text = Path(args.path).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"读不到文件：{exc}", file=sys.stderr)
        return 2

    report = lint_text(text)
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(render(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
