#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外部引用检查的测试.

    python tests/test_refs.py

核心断言：引用必须指向**机器可读**的锚点，且失效时能报出来。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from refs import (  # noqa: E402
    REFS,
    _check_argparse_choice,
    _check_argparse_parser,
    _check_file,
    _check_json_node,
    find_project,
    render,
    run,
)

RUNNER = """\
import argparse
p = argparse.ArgumentParser()
sub = p.add_subparsers()
sub.add_parser("init")
sub.add_parser("run-stage")
a = sub.add_parser("approve")
a.add_argument("--gate", choices=["modeling", "models"], required=True)
"""


class TestCheckers(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "runner.py").write_text(RUNNER, encoding="utf-8")
        (self.root / "process.json").write_text(
            json.dumps({"nodes": [{"nodeId": "SP-01"}, {"nodeId": "SP-18"}]}),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def spec(self, **kwargs) -> dict:
        base = {"project": "t", "why": ""}
        base.update(kwargs)
        return base

    def test_json_node_ok(self) -> None:
        r = _check_json_node(self.root, self.spec(kind="json-node", anchor="process.json", ids=["SP-01"]))
        self.assertEqual(r.status, "ok")

    def test_json_node_drift(self) -> None:
        r = _check_json_node(self.root, self.spec(kind="json-node", anchor="process.json", ids=["SP-99"]))
        self.assertEqual(r.status, "drift")
        self.assertIn("SP-99", r.detail)

    def test_json_node_missing_anchor(self) -> None:
        r = _check_json_node(self.root, self.spec(kind="json-node", anchor="nope.json", ids=["SP-01"]))
        self.assertEqual(r.status, "drift")

    def test_file_ok(self) -> None:
        r = _check_file(self.root, self.spec(kind="file", anchor="runner.py"))
        self.assertEqual(r.status, "ok")

    def test_file_drift(self) -> None:
        r = _check_file(self.root, self.spec(kind="file", anchor="nope.py"))
        self.assertEqual(r.status, "drift")

    def test_parser_ok(self) -> None:
        r = _check_argparse_parser(
            self.root, self.spec(kind="argparse-parser", anchor="runner.py", ids=["init", "approve"])
        )
        self.assertEqual(r.status, "ok")

    def test_parser_drift(self) -> None:
        r = _check_argparse_parser(
            self.root, self.spec(kind="argparse-parser", anchor="runner.py", ids=["nonexistent"])
        )
        self.assertEqual(r.status, "drift")

    def test_choice_ok(self) -> None:
        r = _check_argparse_choice(
            self.root,
            self.spec(kind="argparse-choice", anchor="runner.py", argument="--gate", ids=["modeling"]),
        )
        self.assertEqual(r.status, "ok")

    def test_choice_drift(self) -> None:
        r = _check_argparse_choice(
            self.root,
            self.spec(kind="argparse-choice", anchor="runner.py", argument="--gate", ids=["建模"]),
        )
        self.assertEqual(r.status, "drift")

    def test_choice_missing_argument(self) -> None:
        r = _check_argparse_choice(
            self.root,
            self.spec(kind="argparse-choice", anchor="runner.py", argument="--nope", ids=["a"]),
        )
        self.assertEqual(r.status, "drift")


class TestSkip(unittest.TestCase):
    def test_missing_project_is_skip_not_drift(self) -> None:
        """项目不在本机不该算失败——否则谁 clone 都能红."""
        results = run([{"project": "_ghost", "kind": "file", "anchor": "x", "why": ""}])
        self.assertEqual(results[0].status, "skip")

    def test_find_project_returns_none_for_unknown(self) -> None:
        self.assertIsNone(find_project("_ghost2"))

    def test_distribution_env_has_no_absolute_paths(self) -> None:
        """引用清单里不能出现开发机绝对路径——分发出去会指向别人的机器."""
        source = (ROOT / "refs.py").read_text(encoding="utf-8")
        self.assertNotIn("D:\\", source)
        self.assertNotIn("D:/", source)


class TestRender(unittest.TestCase):
    def test_render_mentions_drift_consequence(self) -> None:
        results = run([{"project": "gate", "kind": "file", "anchor": "no/such.py", "why": ""}])
        text = render(results)
        if results[0].status == "drift":
            self.assertIn("stage 列表是错的", text)


class TestRealRefs(unittest.TestCase):
    """对真实项目的检查。项目不在本机时 skip（这是设计，不是失败）."""

    def test_no_drift_in_declared_refs(self) -> None:
        results = run(REFS)
        drift = [item for item in results if item.status == "drift"]
        self.assertEqual(
            drift, [],
            "引用失效：" + "；".join(f"{d.project}/{d.anchor}: {d.detail}" for d in drift),
        )

    def test_every_ref_has_reason(self) -> None:
        for ref in REFS:
            with self.subTest(ref=ref["anchor"]):
                self.assertTrue(ref.get("why"), "每条引用都要写清为什么引")

    def test_every_kind_is_known(self) -> None:
        from refs import CHECKERS

        for ref in REFS:
            with self.subTest(kind=ref["kind"]):
                self.assertIn(ref["kind"], CHECKERS)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    unittest.main(verbosity=2)
