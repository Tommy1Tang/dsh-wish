#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单测入口。把各套件聚起来跑，只打摘要。

    python run_tests.py            # 全部
    python run_tests.py -v         # 每套件的详细输出
    python run_tests.py router     # 只跑名字含 router 的套件
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SUITES = [
    "test_router.py",
    "test_real_scenarios.py",
    "test_contract_lint.py",
    "test_dropped.py",
    "test_ears.py",
    "test_examples.py",
    "test_focus.py",
    "test_deps.py",
    "test_refs.py",
    "test_vendor.py",
    "test_sync_vendor.py",
    "test_consistency.py",
]


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(description="dsh-wish 单测入口")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("filter", nargs="?", default="", help="只跑名字含此串的套件")
    args = parser.parse_args(argv)

    selected = [name for name in SUITES if args.filter in name]
    if not selected:
        print(f"没有匹配 {args.filter!r} 的套件", file=sys.stderr)
        return 2

    total = failures = 0
    failed: list[str] = []
    for name in selected:
        result = subprocess.run(
            [sys.executable, str(ROOT / "tests" / name)],
            capture_output=True, text=True, timeout=300,
            encoding="utf-8", errors="replace",
        )
        output = result.stdout + result.stderr
        if args.verbose:
            print(output)
        ran = "?"
        for line in output.splitlines():
            if line.startswith("Ran ") and " tests" in line:
                ran = line.split()[1]
                total += int(ran)
        ok = result.returncode == 0
        if not ok:
            failures += 1
            failed.append(name)
        print(f"{name:<28} {ran:>4} tests  {'OK' if ok else 'FAIL'}")

    print()
    print(f"合计 {len(selected)} 套件 / {total} 个测试 —— "
          + ("全部通过" if not failures else f"{failures} 个套件失败：{', '.join(failed)}"))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
