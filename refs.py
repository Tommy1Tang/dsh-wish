#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外部引用检查 (checked references).

`router.py` 的 stage 列表里写死了别人的节点编号和命令名：

    SP-01 / SP-06 / SP-12 / SP-13 / SP-18     ← agent-delivery-gate 的流程节点
    run-stage / approve --gate modeling|models  ← research-to-project-input 的子命令

**这些是裸字符串**。对方改一个编号、删一个子命令，这边不会报错，只会继续输出错的流程。

裸引用有两个毛病，这个脚本治第二个：
1. 会漂移（无法根治，除非内嵌——但内嵌就是双份维护）
2. **漂移了你也不知道**（可根治：每次指向机器可读的锚点去验）

所以引用一律指向**机器可读**的东西：
- 流程节点 → `assets/config/skill-process.json` 的 `nodeId`
- 子命令 → `pipeline_runner.py` 里的 `add_parser(...)`
- 参数取值 → `add_argument("--gate", choices=[...])`
- 脚本 → 文件是否存在

**不要指向散文。** 实测过：`approve --gate modeling` 在 `pipeline-commands.md` 里是
跨行写的（PowerShell 反引号续行），字符串搜不到，会误判成"引用失效"。

    python refs.py            # 表格
    python refs.py --json
    python refs.py --selftest

退出码: 0 = 全部有效（或有项目缺席被跳过）, 1 = 有引用失效
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import deps  # noqa: E402

# ===========================================================================
# 引用清单 —— 改 router.py 的 stage 列表时，同步改这里
# ===========================================================================

# 路径不写死：交给 deps 按 环境变量 → 同级目录 → 向上查找 → deps.local.json 解析。
# 分发环境里这些项目不存在时，全部 SKIP —— 换台机器不该红。
PROJECT_MARKERS = {
    "gate": deps.GATE_MARKER,
    "r2pi": deps.R2PI_MARKER,
}

REFS = [
    # --- agent-delivery-gate -------------------------------------------------
    {
        "project": "gate",
        "kind": "json-node",
        "anchor": "assets/config/skill-process.json",
        "ids": ["SP-01", "SP-06", "SP-12", "SP-13", "SP-18"],
        "why": "stages_for() 里写死的流程节点",
    },
    {
        "project": "gate",
        "kind": "file",
        "anchor": "scripts/validate_delivery.py",
        "why": "SP-18 终检",
    },
    {
        "project": "gate",
        "kind": "file",
        "anchor": "scripts/preflight_env_check.py",
        "why": "SP-01 环境预检",
    },
    {
        "project": "gate",
        "kind": "file",
        "anchor": "scripts/validate_input_contract.py",
        "why": "L2 的输入契约门禁（C-INPUT-01..04）",
    },
    # --- research-to-project-input ------------------------------------------
    {
        "project": "r2pi",
        "kind": "argparse-parser",
        "anchor": "scripts/pipeline_runner.py",
        "ids": ["init", "register-research", "run-stage", "approve", "validate"],
        "why": "L2 建模段的子命令",
    },
    {
        "project": "r2pi",
        "kind": "argparse-choice",
        "anchor": "scripts/pipeline_runner.py",
        "argument": "--gate",
        "ids": ["modeling", "models"],
        "why": "两道人审的 gate 名",
    },
]


# ===========================================================================
# 结果
# ===========================================================================


@dataclass
class CheckResult:
    project: str
    kind: str
    anchor: str
    status: str          # ok | drift | skip
    detail: str

    def to_dict(self) -> dict:
        return {
            "project": self.project,
            "kind": self.kind,
            "anchor": self.anchor,
            "status": self.status,
            "detail": self.detail,
        }


def find_project(name: str, markers: dict[str, Path] | None = None) -> Path | None:
    table = markers or PROJECT_MARKERS
    return deps.find_related(name, table.get(name))


# ===========================================================================
# 各 kind 的验证
# ===========================================================================


def _check_json_node(root: Path, ref: dict) -> CheckResult:
    path = root / ref["anchor"]
    if not path.is_file():
        return CheckResult(ref["project"], "json-node", ref["anchor"], "drift", "锚点文件不存在")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ids = {node["nodeId"] for node in data.get("nodes", [])}
    except (OSError, ValueError, KeyError) as exc:
        return CheckResult(ref["project"], "json-node", ref["anchor"], "drift", f"读不了流程模型：{exc}")
    missing = [item for item in ref["ids"] if item not in ids]
    if missing:
        return CheckResult(
            ref["project"], "json-node", ref["anchor"], "drift",
            f"引用了不存在的节点：{missing}（现有 {len(ids)} 个）",
        )
    return CheckResult(
        ref["project"], "json-node", ref["anchor"], "ok",
        f"{len(ref['ids'])} 个节点全部存在",
    )


def _check_file(root: Path, ref: dict) -> CheckResult:
    path = root / ref["anchor"]
    if path.is_file():
        return CheckResult(ref["project"], "file", ref["anchor"], "ok", "存在")
    return CheckResult(ref["project"], "file", ref["anchor"], "drift", "文件不存在")


def _check_argparse_parser(root: Path, ref: dict) -> CheckResult:
    path = root / ref["anchor"]
    if not path.is_file():
        return CheckResult(ref["project"], "argparse-parser", ref["anchor"], "drift", "锚点文件不存在")
    text = path.read_text(encoding="utf-8")
    found = set(re.findall(r"add_parser\(\s*[\"']([a-z\-]+)[\"']", text))
    missing = [item for item in ref["ids"] if item not in found]
    if missing:
        return CheckResult(
            ref["project"], "argparse-parser", ref["anchor"], "drift",
            f"引用了不存在的子命令：{missing}",
        )
    return CheckResult(
        ref["project"], "argparse-parser", ref["anchor"], "ok",
        f"{len(ref['ids'])} 个子命令全部存在",
    )


def _check_argparse_choice(root: Path, ref: dict) -> CheckResult:
    path = root / ref["anchor"]
    if not path.is_file():
        return CheckResult(ref["project"], "argparse-choice", ref["anchor"], "drift", "锚点文件不存在")
    text = path.read_text(encoding="utf-8")
    argument = ref["argument"]
    pattern = rf"add_argument\(\s*[\"']{re.escape(argument)}[\"']\s*,\s*choices=\[([^\]]*)\]"
    match = re.search(pattern, text, re.S)
    if not match:
        return CheckResult(
            ref["project"], "argparse-choice", ref["anchor"], "drift",
            f"找不到 `{argument}` 的 choices 定义",
        )
    choices = re.findall(r"[\"']([^\"']+)[\"']", match.group(1))
    missing = [item for item in ref["ids"] if item not in choices]
    if missing:
        return CheckResult(
            ref["project"], "argparse-choice", ref["anchor"], "drift",
            f"`{argument}` 不再接受：{missing}（现有 {choices}）",
        )
    return CheckResult(
        ref["project"], "argparse-choice", ref["anchor"], "ok",
        f"`{argument}` 接受 {choices}",
    )


CHECKERS = {
    "json-node": _check_json_node,
    "file": _check_file,
    "argparse-parser": _check_argparse_parser,
    "argparse-choice": _check_argparse_choice,
}


# ===========================================================================
# 主流程
# ===========================================================================


def run(refs: list[dict] | None = None, markers: dict[str, Path] | None = None) -> list[CheckResult]:
    results: list[CheckResult] = []
    for ref in refs or REFS:
        root = find_project(ref["project"], markers)
        if root is None:
            results.append(CheckResult(
                ref["project"], ref["kind"], ref["anchor"], "skip",
                "项目不在本机（可用环境变量或 deps.local.json 指定路径）",
            ))
            continue
        checker = CHECKERS[ref["kind"]]
        results.append(checker(root, ref))
    return results


def render(results: list[CheckResult]) -> str:
    lines = [f"{'项目':<6}{'方式':<18}{'锚点':<42}{'状态':<6}说明"]
    lines.append("-" * 110)
    for item in results:
        mark = {"ok": "OK", "drift": "DRIFT", "skip": "SKIP"}[item.status]
        lines.append(f"{item.project:<6}{item.kind:<18}{item.anchor:<42}{mark:<6}{item.detail}")
    drift = sum(1 for item in results if item.status == "drift")
    skip = sum(1 for item in results if item.status == "skip")
    lines.append("")
    lines.append(f"合计 {len(results)} 项：OK {len(results) - drift - skip}　DRIFT {drift}　SKIP {skip}")
    if drift:
        lines.append("")
        lines.append("引用失效了。router.py 现在输出的 stage 列表是错的——先修引用，再继续。")
    return "\n".join(lines)


SELFTEST_FILE = """\
import argparse
p = argparse.ArgumentParser()
sub = p.add_subparsers()
sub.add_parser("init")
sub.add_parser("run-stage")
a = sub.add_parser("approve")
a.add_argument("--gate", choices=["modeling", "models"], required=True)
"""

SELFTEST_PROCESS = json.dumps({"nodes": [{"nodeId": f"SP-{i:02d}"} for i in range(1, 20)]})


def selftest() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "runner.py").write_text(SELFTEST_FILE, encoding="utf-8")
        (root / "process.json").write_text(SELFTEST_PROCESS, encoding="utf-8")
        good = [
            {"project": "x", "kind": "json-node", "anchor": "process.json", "ids": ["SP-01"]},
            {"project": "x", "kind": "argparse-parser", "anchor": "runner.py", "ids": ["init", "run-stage"]},
            {"project": "x", "kind": "argparse-choice", "anchor": "runner.py", "argument": "--gate", "ids": ["modeling"]},
        ]
        bad = [
            {"project": "x", "kind": "json-node", "anchor": "process.json", "ids": ["SP-99"]},
            {"project": "x", "kind": "argparse-parser", "anchor": "runner.py", "ids": ["nope"]},
            {"project": "x", "kind": "argparse-choice", "anchor": "runner.py", "argument": "--gate", "ids": ["建模"]},
        ]
        # 用环境变量指向临时目录，不碰任何全局状态
        previous = os.environ.get("DSH_WISH_X")
        os.environ["DSH_WISH_X"] = str(root)
        try:
            good_results = run(good, markers={"x": Path("runner.py")})
            bad_results = run(bad, markers={"x": Path("runner.py")})
        finally:
            if previous is None:
                os.environ.pop("DSH_WISH_X", None)
            else:
                os.environ["DSH_WISH_X"] = previous

    print("== 有效引用 ==")
    print(render(good_results))
    print()
    print("== 失效引用 ==")
    print(render(bad_results))
    print()
    ok = (
        all(item.status == "ok" for item in good_results)
        and all(item.status == "drift" for item in bad_results)
    )
    print("自检：" + ("通过" if ok else "失败"))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(
        description="检查 router.py 对外部流程节点/命令的引用是否仍然有效",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--selftest", action="store_true", help="跑内置样例")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    results = run()
    if args.json:
        print(json.dumps([item.to_dict() for item in results], ensure_ascii=False, indent=2))
    else:
        print(render(results))
    return 1 if any(item.status == "drift" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
