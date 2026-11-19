#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对焦流程 (focus) 的测试.

    python tests/test_focus.py

能测的只有两头：问题生成得对不对、契约写得实不实。
中间"问得让人愿意答"测不了——那只能靠真实使用。
"""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from focus import (  # noqa: E402
    build_answers,
    build_contract,
    cmd_complete,
    cmd_start,
    parse_answers,
    slugify,
)
from router import classify  # noqa: E402

WISH = "齐套报表的齐套率算法要改，现在是按数量，要改成按金额"


class TestSlug(unittest.TestCase):
    def test_stable(self) -> None:
        self.assertEqual(slugify(WISH), slugify(WISH))

    def test_unique_for_different_wishes(self) -> None:
        self.assertNotEqual(slugify("做一个报表"), slugify("做一个看板"))

    def test_path_safe(self) -> None:
        slug = slugify('做一个 "报表" / 看板?')
        for bad in ('"', "/", "?", "\\", ":", "*"):
            self.assertNotIn(bad, slug)

    def test_keeps_some_readability(self) -> None:
        self.assertTrue(slugify(WISH).startswith("齐套报表"))


class TestAnswers(unittest.TestCase):
    def test_decisions_are_prefilled(self) -> None:
        text = build_answers(classify(WISH), WISH)
        self.assertIn("推荐：", text)
        self.assertIn("回答：", text)
        # 变更类必答题必须出现
        self.assertIn("历史数据怎么处理", text)

    def test_facts_are_not_questions(self) -> None:
        text = build_answers(classify(WISH), WISH)
        self.assertIn("我自己去查（你不用回答）", text)
        self.assertIn("技术栈基线", text)

    def test_parse_roundtrip(self) -> None:
        text = build_answers(classify(WISH), WISH)
        parsed = parse_answers(text)
        self.assertTrue(parsed)
        titles = [item["title"] for item in parsed]
        self.assertIn("谁在用", titles)
        for item in parsed:
            self.assertIn("answer", item)
            self.assertIn("recommend", item)

    def test_answer_overrides_recommend(self) -> None:
        text = build_answers(classify(WISH), WISH).replace(
            "回答：", "回答：财务和计划员", 1
        )
        parsed = parse_answers(text)
        self.assertEqual(parsed[0]["answer"], "财务和计划员")


class TestContract(unittest.TestCase):
    def _answers(self, done: str = "", scope: str = "") -> list[dict]:
        return [
            {"title": "谁在用", "answer": "财务", "recommend": "默认角色"},
            {"title": "怎么算做完了", "answer": done, "recommend": "（推荐语不应被当成验收标准）"},
            {"title": "不做什么", "answer": scope, "recommend": "默认不做权限"},
        ]

    def test_criteria_split_into_acs(self) -> None:
        contract = build_contract(
            classify(WISH), WISH,
            self._answers(done="金额差异不超过 1 元；页面 2 秒内打开"),
        )
        self.assertIn("### AC-01", contract)
        self.assertIn("### AC-02", contract)
        self.assertIn("金额差异不超过 1 元", contract)

    def test_empty_criteria_yields_single_blank_ac(self) -> None:
        contract = build_contract(classify(WISH), WISH, self._answers())
        self.assertEqual(contract.count("### AC-"), 1)
        self.assertIn("- **判定方式**：\n", contract)

    def test_recommend_is_not_used_for_acceptance(self) -> None:
        """推荐语是"怎么写", 不是验收标准本身. 拿它当 AC 会生成假的具体性."""
        contract = build_contract(classify(WISH), WISH, self._answers())
        self.assertNotIn("推荐语不应被当成验收标准", contract)

    def test_scope_falls_back_to_recommend(self) -> None:
        """边界类可以接受推荐值 —— 它有具体默认."""
        contract = build_contract(classify(WISH), WISH, self._answers(done="X 达到 5 条"))
        self.assertIn("默认不做权限", contract)

    def test_counterexample_left_empty(self) -> None:
        """反例必须留空给人填, 否则 lint 会被自己的提示语骗过去."""
        contract = build_contract(classify(WISH), WISH, self._answers(done="X 达到 5 条"))
        self.assertIn("> 反例：\n", contract)


class TestEndToEnd(unittest.TestCase):
    def test_counterexample_survives_regeneration(self) -> None:
        """重新 --complete 不能把人工想出来的反例冲掉."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                cmd_start(WISH, root, force=True)
            target = next(root.iterdir())
            answers = (target / "answers.md").read_text(encoding="utf-8")
            answers = answers.replace("回答：\n\n## Q3", "回答：金额差异不超过 1 元\n\n## Q3")
            (target / "answers.md").write_text(answers, encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cmd_complete(target), 1)   # 缺反例

            contract_path = target / "contract.md"
            contract = contract_path.read_text(encoding="utf-8")
            contract_path.write_text(
                contract.replace("> 反例：", "> 反例：只把数量乘单价显示出来，逻辑没换"),
                encoding="utf-8",
            )
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cmd_complete(target), 0)   # 重新生成但保留反例 → PASS
            self.assertIn("逻辑没换", contract_path.read_text(encoding="utf-8"))

    def test_force_drops_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                cmd_start(WISH, root, force=True)
            target = next(root.iterdir())
            answers = (target / "answers.md").read_text(encoding="utf-8")
            answers = answers.replace("回答：\n\n## Q3", "回答：金额差异不超过 1 元\n\n## Q3")
            (target / "answers.md").write_text(answers, encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                cmd_complete(target)
            contract_path = target / "contract.md"
            contract_path.write_text(
                contract_path.read_text(encoding="utf-8").replace(
                    "> 反例：", "> 反例：只把数量乘单价显示出来"
                ),
                encoding="utf-8",
            )
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cmd_complete(target, force=True), 1)
            self.assertNotIn("只把数量乘单价", contract_path.read_text(encoding="utf-8"))

    def test_complete_without_answers_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cmd_complete(Path(tmp)), 2)


class TestLog(unittest.TestCase):
    """skill 形态拦不住"没跑就声称合格", 但能事后查."""

    def test_complete_writes_log_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                cmd_start(WISH, root, force=True)
            target = next(root.iterdir())
            with redirect_stdout(io.StringIO()):
                cmd_complete(target)
            log = target / "focus-log.jsonl"
            self.assertTrue(log.is_file())
            import json as _json

            entry = _json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(entry["tier"], "L1")
            self.assertIn("lintOk", entry)
            self.assertIn("acCount", entry)

    def test_failed_lint_is_logged_too(self) -> None:
        """不合格也要记 —— 记录的是"跑过", 不是"通过"."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                cmd_start(WISH, root, force=True)
            target = next(root.iterdir())
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cmd_complete(target), 1)
            import json as _json

            entry = _json.loads(
                (target / "focus-log.jsonl").read_text(encoding="utf-8").splitlines()[-1]
            )
            self.assertFalse(entry["lintOk"])
            self.assertTrue(entry["errors"])

    def test_log_appends(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                cmd_start(WISH, root, force=True)
            target = next(root.iterdir())
            with redirect_stdout(io.StringIO()):
                cmd_complete(target)
                cmd_complete(target)
            lines = (target / "focus-log.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)


class TestNoOverwrite(unittest.TestCase):
    def test_existing_dir_needs_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cmd_start(WISH, root, force=False), 0)
                self.assertEqual(cmd_start(WISH, root, force=False), 1)
                self.assertEqual(cmd_start(WISH, root, force=True), 0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    unittest.main(verbosity=2)
