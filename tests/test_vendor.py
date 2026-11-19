#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""随包分发（vendor）的测试.

    python tests/test_vendor.py

核心断言：
1. **装了就是完整版**——vendor 在场时输出精确节点，且命令路径指向 vendor，不是本机源仓库。
2. **vendor 可追溯**——VENDOR.json 记了源路径、commit、文件数，不是"悄悄抄一份"。
3. **vendor 里的脚本真能跑**——不是只拷了文件。
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import deps  # noqa: E402
from router import classify  # noqa: E402

VENDOR = ROOT / "vendor"
MANIFEST = VENDOR / "VENDOR.json"


def vendor_present() -> bool:
    return (VENDOR / "agent-delivery-gate" / deps.GATE_MARKER).is_file()


@unittest.skipUnless(vendor_present(), "vendor 未同步（先跑 python tools/sync_vendor.py）")
class TestVendoredPackage(unittest.TestCase):
    def tearDown(self) -> None:
        deps.set_gate_available(None)

    def test_vendor_wins_over_source(self) -> None:
        """随包的优先——保证"装了就完整"，不依赖本机其他仓库."""
        root = deps.find_related("gate", deps.GATE_MARKER)
        self.assertIsNotNone(root)
        self.assertTrue(
            str(root).startswith(str(VENDOR)),
            f"应当优先用 vendor，实际用了 {root}",
        )

    def test_command_paths_point_into_vendor(self) -> None:
        stages = " ".join(classify("实现一个用户登录接口", precise=True).stages)
        self.assertIn("vendor/agent-delivery-gate/scripts/", stages)
        self.assertNotIn("D:\\aiskills", stages)

    def test_l2_paths_point_into_vendor(self) -> None:
        stages = " ".join(
            classify("我需要从0到1重新设计上线一个MES系统", precise=True).stages
        )
        if deps.find_related("r2pi", deps.R2PI_MARKER):
            self.assertIn("vendor/research-to-project-input/scripts/", stages)

    def test_vendored_script_actually_runs(self) -> None:
        """拷了文件不等于能跑——真跑一次 --help."""
        script = VENDOR / "agent-delivery-gate" / "scripts" / "validate_delivery.py"
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
        )
        self.assertEqual(result.returncode, 0, result.stderr[-500:])
        self.assertIn("validate_delivery", result.stdout)


@unittest.skipUnless(MANIFEST.is_file(), "VENDOR.json 不存在")
class TestManifest(unittest.TestCase):
    def setUp(self) -> None:
        self.data = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_each_project_recorded(self) -> None:
        for key in ("gate", "r2pi"):
            with self.subTest(project=key):
                self.assertIn(key, self.data)

    def test_record_has_provenance(self) -> None:
        """没有来源和 commit 的内嵌就是抄 —— 抄了不知道抄的哪版最麻烦."""
        for key, record in self.data.items():
            with self.subTest(project=key):
                self.assertTrue(record.get("source"), "缺源路径")
                self.assertTrue(record.get("syncedAt"), "缺同步时间")
                self.assertGreater(record.get("files", 0), 0, "缺文件数")
                self.assertIn("commit", record)

    def test_recorded_size_is_plausible(self) -> None:
        for key, record in self.data.items():
            with self.subTest(project=key):
                self.assertGreater(record.get("bytes", 0), 100_000)


class TestFallbackStillWorks(unittest.TestCase):
    """强制关掉 gate 时仍要能跑 —— 降级路径不能因为加了 vendor 就坏掉."""

    def tearDown(self) -> None:
        deps.set_gate_available(None)

    def test_generic_mode_has_no_vendor_paths(self) -> None:
        deps.set_gate_available(False)
        stages = " ".join(classify("实现一个用户登录接口", precise=False).stages)
        self.assertNotIn("vendor/", stages)
        self.assertNotIn("SP-", stages)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    unittest.main(verbosity=2)
