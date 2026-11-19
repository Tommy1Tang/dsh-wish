#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vendor 同步脚本的测试.

    python tests/test_sync_vendor.py

核心断言：`--check` 必须真的能发现"vendor 落后于源仓库"，
而不是拿 vendor 和 vendor 比（踩过这个坑：`find_related` 默认优先 vendor，
于是 sync 脚本永远说"和源一致"）。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import deps  # noqa: E402
import sync_vendor  # noqa: E402


class TestFindSource(unittest.TestCase):
    def test_source_lookup_skips_vendor(self) -> None:
        """找源时必须 prefer_vendor=False —— 否则永远"和源一致"."""
        src = deps.find_related("gate", deps.GATE_MARKER, prefer_vendor=False)
        if src is None:
            self.skipTest("本机没有 gate 源仓库")
        self.assertFalse(
            str(src).replace("\\", "/").startswith(str(deps.VENDOR_DIR).replace("\\", "/")),
            f"源查找返回了 vendor：{src}",
        )

    def test_default_lookup_prefers_vendor(self) -> None:
        if not (deps.VENDOR_DIR / "agent-delivery-gate").is_dir():
            self.skipTest("vendor 未同步")
        found = deps.find_related("gate", deps.GATE_MARKER)
        self.assertTrue(str(found).startswith(str(deps.VENDOR_DIR)))


class TestManifestRoundtrip(unittest.TestCase):
    def test_save_and_load(self) -> None:
        original = sync_vendor.load_manifest()
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "VENDOR.json"
            old_path = sync_vendor.MANIFEST
            sync_vendor.MANIFEST = fake
            try:
                sync_vendor.save_manifest({"x": {"source": "a", "files": 1}})
                self.assertEqual(sync_vendor.load_manifest()["x"]["files"], 1)
            finally:
                sync_vendor.MANIFEST = old_path
        self.assertEqual(sync_vendor.load_manifest(), original)

    def test_scan_skips_cache_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("x", encoding="utf-8")
            cache = root / "__pycache__"
            cache.mkdir()
            (cache / "a.pyc").write_text("x" * 100, encoding="utf-8")
            count, size = sync_vendor.scan(root)
            self.assertEqual(count, 1)
            self.assertEqual(size, 1)


class TestCheckMode(unittest.TestCase):
    def test_check_detects_missing_vendor(self) -> None:
        """vendor 不存在时必须报 missing，而不是 ok."""
        original = sync_vendor.VENDOR
        with tempfile.TemporaryDirectory() as tmp:
            sync_vendor.VENDOR = Path(tmp) / "vendor"
            try:
                status, detail = sync_vendor.sync_one("gate", check_only=True)
            finally:
                sync_vendor.VENDOR = original
        if status == "missing" and "源目录找不到" in detail:
            self.skipTest("本机没有 gate 源仓库")
        self.assertEqual(status, "missing")

    def test_check_reports_stale_when_commit_differs(self) -> None:
        """记录里的 commit 和源不一致时必须报 stale."""
        original_manifest_path = sync_vendor.MANIFEST
        original_vendor = sync_vendor.VENDOR
        src = deps.find_related("gate", deps.GATE_MARKER, prefer_vendor=False)
        if src is None:
            self.skipTest("本机没有 gate 源仓库")
        with tempfile.TemporaryDirectory() as tmp:
            vendor = Path(tmp) / "vendor"
            (vendor / "agent-delivery-gate" / "scripts").mkdir(parents=True)
            (vendor / "agent-delivery-gate" / "scripts" / "validate_delivery.py").write_text(
                "", encoding="utf-8"
            )
            sync_vendor.VENDOR = vendor
            sync_vendor.MANIFEST = vendor / "VENDOR.json"
            sync_vendor.save_manifest({"gate": {"commit": "deadbeef", "files": 1}})
            try:
                status, detail = sync_vendor.sync_one("gate", check_only=True)
            finally:
                sync_vendor.MANIFEST = original_manifest_path
                sync_vendor.VENDOR = original_vendor
        self.assertEqual(status, "stale", detail)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    unittest.main(verbosity=2)
