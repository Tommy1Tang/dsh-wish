#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对焦流程 (focus).

把一次判档变成一份可填的契约：

    python focus.py "要做的事"           # 1. 判档 + 出问题 + 建目录
    #   → 编辑 wish/<slug>/answers.md（每题已预填推荐答案，答"是"即可）
    python focus.py --complete wish/<slug>   # 2. 回填 → 生成 contract.md → 跑 lint

它不是对话机器人。它做三件确定性的事：

1. 把 router 的判档结果编译成问题清单（fact 自己查 / decision 问人）
2. 把回答编译成 contract.md 骨架
3. 用 contract_lint 检查这份契约写没写实 —— **不通过就明说，不假装完成**

中间那段"问得让人愿意答"只能靠真实使用验证。这里只保证两头可测：
问题生成得对不对（router 的 72 个测试）、契约写得实不实（lint 的 15 个测试）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from contract_lint import lint_text, render as render_lint, split_acs  # noqa: E402
from router import PROFILE_LABEL, Route, classify  # noqa: E402

WISH_ROOT = Path("wish")
ANSWER_KEY = "回答"
RECOMMEND_KEY = "推荐"


# ===========================================================================
# slug
# ===========================================================================


def slugify(wish: str) -> str:
    """中文也要能落成合法的目录名。取可读前缀 + 短哈希保证唯一。"""
    readable = re.sub(r"[^\w\u4e00-\u9fff]+", "-", wish.strip())[:16].strip("-")
    digest = hashlib.sha1(wish.encode("utf-8")).hexdigest()[:6]
    return f"{readable}-{digest}" if readable else f"wish-{digest}"


# ===========================================================================
# 生成 answers.md
# ===========================================================================


def build_answers(route: Route, wish: str) -> str:
    """把 probes 编译成一份可填的答案表。

    decision 类预填推荐答案 —— 抄 grilling 的做法：让"是"就能接受。
    fact 类不预填，只写"去哪儿查"。
    """
    lines = [
        f"# 对焦回答 · {wish}",
        "",
        f"> 档位：**{route.tier}**（{route.meta['name']}）　"
        f"类型：**{PROFILE_LABEL.get(route.profile, route.profile)}**"
        + ("　🔴 紧急" if route.urgent else ""),
        f"> 依据：{route.reason}",
        "",
        "**怎么填**：每题下面「回答」留空就表示接受「推荐」。想改就直接写，一句话即可。",
        "",
        "---",
        "",
    ]

    decisions = [p for p in route.probes if p.kind == "decision"]
    facts = [p for p in route.probes if p.kind == "fact"]

    if facts:
        lines += ["## 我自己去查（你不用回答）", ""]
        for probe in facts:
            lines.append(f"- **{probe.title}**：{probe.body}")
        lines += ["", "---", ""]

    for i, probe in enumerate(decisions, 1):
        lines += [
            f"## Q{i} {probe.title}",
            "",
            probe.body,
            "",
            f"{RECOMMEND_KEY}：{probe.recommended}",
            "",
            f"{ANSWER_KEY}：",
            "",
        ]

    if not decisions:
        lines += ["（这一档不需要你回答任何问题，直接 `--complete` 即可）", ""]

    return "\n".join(lines)


def parse_answers(text: str) -> list[dict]:
    """解析 answers.md → [{title, answer, recommend}]，answer 为空表示接受推荐值."""
    blocks = re.split(r"^##\s+Q\d+\s+", text, flags=re.MULTILINE)[1:]
    out: list[dict] = []
    for block in blocks:
        title = block.splitlines()[0].strip() if block.strip() else ""
        answer_match = re.search(rf"^{ANSWER_KEY}\s*[:：]\s*(.*)$", block, re.MULTILINE)
        recommend_match = re.search(rf"^{RECOMMEND_KEY}\s*[:：]\s*(.*)$", block, re.MULTILINE)
        out.append({
            "title": title,
            "answer": (answer_match.group(1).strip() if answer_match else ""),
            "recommend": (recommend_match.group(1).strip() if recommend_match else ""),
        })
    return out


# ===========================================================================
# 生成 contract.md
# ===========================================================================


def _split_criteria(text: str) -> list[str]:
    """把一句验收描述切成多条 AC。中英文标点都认。"""
    parts = re.split(r"[；;。]\s*|\n+", text.strip())
    return [p.strip(" -·") for p in parts if len(p.strip(" -·")) >= 4]


COUNTEREXAMPLE_LINE = r"^\s*>\s*反例[:：]\s*(\S.*)$"


def collect_counterexamples(text: str) -> dict[str, str]:
    """抽出已手填的反例，按 AC 编号索引.

    没有这一步，重新 `--complete` 会把人工想出来的反例冲掉 ——
    而反例恰恰是这份契约里唯一机器想不出来、只能靠人补的东西。
    """
    out: dict[str, str] = {}
    for ac in split_acs(text):
        for line in ac.lines:
            match = re.search(COUNTEREXAMPLE_LINE, line)
            if match:
                out[ac.ac_id] = match.group(1).strip()
                break
    return out


def build_contract(
    route: Route,
    wish: str,
    answers: list[dict],
    preserved: dict[str, str] | None = None,
) -> str:
    preserved = preserved or {}
    def pick(*keywords: str, allow_recommend: bool = True) -> str:
        """按标题关键字取答案。allow_recommend=False 时只认用户真写的回答。"""
        for item in answers:
            if any(k in item["title"] for k in keywords):
                if item["answer"]:
                    return item["answer"]
                if allow_recommend:
                    return item["recommend"]
        return ""

    # "怎么算做完了" 不接受推荐值 —— 推荐语是"怎么写"，不是验收标准本身。
    # 拿它当 AC 会生成一堆看起来具体、实际没意义的条目。
    done_text = pick("怎么算做", "验收", "完成", allow_recommend=False)
    scope_out = pick("不做什么", "边界")
    history = pick("历史数据")
    peer_doc = pick("对方接口文档")
    peer_owner = pick("联调谁配合")

    criteria = _split_criteria(done_text) if done_text else []
    if not criteria:
        # 留空而不是留提示语 —— 提示语会被 lint 当成真内容，让空契约"看起来合格"
        criteria = [""]

    lines = [
        "# 交付契约",
        "",
        "> 状态：`draft`　→ 人确认后改 `locked`",
        f"> 档位：`{route.tier}`（{route.meta['name']}，{route.meta['duration']}）"
        f"　人审点：{route.meta['review']} 个",
        f"> 工作类型：`{route.profile}`（{PROFILE_LABEL.get(route.profile, route.profile)}）"
        + ("　**🔴 紧急：先止血再补流程**" if route.urgent else ""),
        f"> 判定依据：{route.reason}",
        f"> 原始愿望：{wish}",
        "",
        "---",
        "",
        "## 1. 一句话目标",
        "",
        wish,
        "",
        "## 2. 验收条目",
        "",
        "> 每条必须**只有一种读法**，并附一条 `> 反例：`。写不出反例说明还没钉住。",
        "",
    ]

    for i, item in enumerate(criteria, 1):
        ac_id = f"AC-{i:02d}"
        lines += [
            f"### {ac_id}",
            "",
            f"- **判定方式**：{item}",
            "",
            f"> 反例：{preserved.get(ac_id, '')}",
            "",
        ]

    lines += [
        "## 3. 范围",
        "",
        "### 本次做",
        "",
        f"- {wish}",
        "",
        "### 本次不做",
        "",
        f"- {scope_out}" if scope_out else "- （必填：本期明确不做什么，这是防范围蔓延最便宜的一招）",
        "",
        "## 4. 技术栈",
        "",
        "> 来自 `tech.md` 与项目现状，**不是猜的**。有偏离要写理由。",
        "",
        "| 层 | 选型 | 依据 |",
        "| --- | --- | --- |",
        "| 后端 | （读 tech.md） | tech.md |",
        "| 前端 | （读 tech.md） | tech.md |",
        "| 数据库 | （读 tech.md） | tech.md |",
        "",
        "## 5. 未知项",
        "",
    ]

    unknowns = list(route.gaps)
    if history:
        unknowns.append(f"历史数据：{history}")
    if peer_doc:
        unknowns.append(f"对方接口文档：{peer_doc}")
    if peer_owner:
        unknowns.append(f"联调配合：{peer_owner}")

    if unknowns:
        for item in unknowns:
            lines.append(f"- {item}")
    else:
        lines.append("- （无）")

    # 状态枚举只在"有状态流转"时给骨架 —— 纯 UI / 纯数据类需求不该被它绊住。
    if _has_state_flow(route, wish):
        lines += [
            "## 6. 状态枚举（填了就强制每个状态都有 AC 覆盖，没有就删掉这一节）",
            "",
            "> 漏一个状态不会让任何测试变红 —— 没写的状态自然没有对应用例。",
            "",
            "| 状态 | 说明 |",
            "| --- | --- |",
            "| （填：如「待支付」） | （进入条件 / 退出条件） |",
            "",
        ]
        section_no = 7
    else:
        section_no = 6

    lines += [
        "",
        f"## {section_no}. 什么情况下可以放弃（dropped）",
        "",
        "> **放弃不是「跳过」，是「确认不做」。** 没有这一节，执行者只能用",
        "> 「完成」（假装做完）或「卡住」（触发返工）来表达「这活不该做」，两种都在污染证据链。",
        "",
        "| 理由码 | 含义 | 确认人 |",
        "| --- | --- | --- |",
        "| `not-reproducible` | 复现不出来（查了 N 次没有） | 提需求的人 |",
        "| `obsolete` | 需求已过时 / 被废弃 | 业务方 |",
        "| `already-exists` | 现有功能已覆盖 | 提需求的人 |",
        "| `out-of-scope` | 不属本项目范围 | 项目负责人 |",
        "",
        "**规则**：报 dropped 必须同时给理由码和确认人；缺一按 `blocked` 处理。",
        "",
        f"## {section_no + 1}. 人审点",
        "",
        "| # | 位置 | 谁看 | 看什么 | 卡住什么 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for i, cp in enumerate(route.checkpoints, 1):
        lines.append(
            f"| {i} | {cp['after']} | {cp['reviewer']} | {cp['looks_at']} | {cp['blocks']} |"
        )

    lines += [
        "",
        f"## {section_no + 2}. 确认",
        "",
        "| 项 | 内容 |",
        "| --- | --- |",
        "| 确认人 | （必填） |",
        "| 确认时间 | （必填） |",
        "| 结论 | `locked` / `退回修改` |",
        "",
        "> 脚本跑成功、没有报错、AI 自审通过，**都不等于批准**。",
        "",
    ]
    return "\n".join(lines)


def _has_state_flow(route: Route, wish: str) -> bool:
    """有状态流转才给「状态枚举」骨架 —— 纯 UI / 纯数据类需求不该被它绊住。

    只认 BUSINESS_FLOW（工单/审批/流转/状态机）和愿望里的状态词。
    **不认 BEHAVIOR_CHANGE**：改口径/改算法是规则变更，不一定有状态枚举——
    给它硬塞一张状态表，只会让人填一堆不存在的状态。
    """
    if any(hit.id == "BUSINESS_FLOW" for hit in route.hits):
        return True
    return bool(re.search(r"(状态|流转|审批流|生命周期|上下架|审核|状态机)", wish))


# ===========================================================================
# 命令
# ===========================================================================


def cmd_start(wish: str, root: Path, force: bool) -> int:
    route = classify(wish)
    target = root / slugify(wish)
    if target.exists() and not force:
        print(f"目录已存在：{target}\n要覆盖加 --force", file=sys.stderr)
        return 1
    target.mkdir(parents=True, exist_ok=True)

    (target / "wish.md").write_text(
        f"# 愿望\n\n{wish}\n\n## 判档\n\n```json\n"
        + json.dumps(route.to_dict(), ensure_ascii=False, indent=2)
        + "\n```\n",
        encoding="utf-8",
    )
    (target / "answers.md").write_text(build_answers(route, wish), encoding="utf-8")

    print(f"档位：{route.tier}（{route.meta['name']}）　"
          f"类型：{PROFILE_LABEL.get(route.profile, route.profile)}"
          + ("　🔴 紧急" if route.urgent else ""))
    print(f"依据：{route.reason}")
    print(f"预计：{route.meta['duration']}　人审点：{route.meta['review']} 个")
    print()
    decisions = [p for p in route.probes if p.kind == "decision"]
    if decisions:
        print(f"要你回答 {len(decisions)} 个问题（已预填推荐答案）：")
        for i, probe in enumerate(decisions, 1):
            print(f"  Q{i}. {probe.title}")
        print()
    print(f"→ 编辑：{target / 'answers.md'}")
    print(f"→ 然后：python focus.py --complete {target}")
    return 0


LOG_NAME = "focus-log.jsonl"


def append_log(directory: Path, route: Route, report, ok: bool) -> None:
    """把每次完成记一行。

    这是插件侧录的穷人版：skill 形态下拦不住"模型没跑就声称合格"，
    但可以事后查——声称合格却没有这行记录，就是没跑过。
    """
    entry = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "tier": route.tier,
        "profile": route.profile,
        "urgent": route.urgent,
        "lintOk": ok,
        "acCount": report.ac_count,
        "errors": [f"{f.rule}:{f.where}" for f in report.errors],
    }
    with (directory / LOG_NAME).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def cmd_complete(directory: Path, force: bool = False) -> int:
    answers_path = directory / "answers.md"
    if not answers_path.is_file():
        print(f"找不到 {answers_path}", file=sys.stderr)
        return 2

    answers_text = answers_path.read_text(encoding="utf-8")
    header = re.search(r"^# 对焦回答 · (.+)$", answers_text, re.MULTILINE)
    wish = header.group(1).strip() if header else directory.name

    route = classify(wish)
    answers = parse_answers(answers_text)

    contract_path = directory / "contract.md"
    preserved: dict[str, str] = {}
    if contract_path.is_file() and not force:
        preserved = collect_counterexamples(contract_path.read_text(encoding="utf-8"))

    contract = build_contract(route, wish, answers, preserved)
    contract_path.write_text(contract, encoding="utf-8")

    report = lint_text(contract)
    append_log(directory, route, report, report.ok)
    print(f"已生成：{contract_path}")
    if preserved:
        print(f"保留了 {len(preserved)} 条已手填的反例（--force 可丢弃）")
    print()
    print(render_lint(report))
    if not report.ok:
        print()
        print("契约还不合格。上面每一条都是必须补的——补完再跑一次：")
        print(f"  python focus.py --complete {directory}")
        return 1
    print()
    print("契约合格。下一步：请人确认（AI 不得代签），然后进执行。")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(
        description="许愿式编程 · 对焦流程",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("wish", nargs="?", help="愿望文本")
    parser.add_argument("--complete", metavar="DIR", help="读 DIR/answers.md 生成 contract.md")
    parser.add_argument("--root", default=str(WISH_ROOT), help="wish 根目录（默认 ./wish）")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的目录 / 丢弃已填的反例")
    args = parser.parse_args(argv)

    if args.complete:
        return cmd_complete(Path(args.complete), force=args.force)
    if not args.wish:
        parser.error("需要一个愿望文本，或用 --complete DIR")
    return cmd_start(args.wish, Path(args.root), args.force)


if __name__ == "__main__":
    raise SystemExit(main())
