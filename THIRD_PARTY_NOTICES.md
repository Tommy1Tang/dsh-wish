# 第三方组件声明 (Third-Party Notices)

本仓库的 `vendor/` 目录**随包分发**了两个外部项目的快照，用于让插件"装完就能跑全链路"。
它们不是本项目的代码，各自保留原许可证。同步方式与版本见 `vendor/VENDOR.json`。

---

## 1. agent-delivery-gate

- **位置**：`vendor/agent-delivery-gate/`
- **许可证**：MIT
- **版权**：Copyright (c) 2026 tommytang
- **同步来源**：见 `vendor/VENDOR.json` 的 `gate.source` / `gate.commit`
- **改动**：未改动内容，仅整体复制（排除 `.git`、`__pycache__`）

许可证全文见 `vendor/agent-delivery-gate/LICENSE`。

---

## 2. research-to-project-input

- **位置**：`vendor/research-to-project-input/`
- **许可证**：Apache License 2.0
- **同步来源**：见 `vendor/VENDOR.json` 的 `r2pi.source` / `r2pi.commit`
- **改动**：未改动内容，仅整体复制（排除 `.git`、`__pycache__`）

Apache-2.0 §4 要求：保留许可证副本、保留版权与归属声明、修改文件需标注。
本项目**未修改**其任何文件；许可证全文见 `vendor/research-to-project-input/LICENSE`。

---

## 3. research-to-project-input 内嵌的第三方库

`vendor/research-to-project-input/vendor/` 下还有一层第三方库（该项目的上游已把它们 vendor 化）。
它们随该项目原样分发，**本项目未做任何改动**：

| 库 | 许可证（以各自 dist-info 为准） |
| --- | --- |
| rdflib | BSD-3-Clause |
| pyshacl | Apache-2.0 |
| owlrl | W3C / BSD-3-Clause |
| pyparsing | MIT |
| packaging | Apache-2.0 或 BSD-2-Clause |
| prettytable | BSD-3-Clause |
| wcwidth | MIT |
| html5rdf | MIT |

每个库的许可证文本位于其 `<包名>-<版本>.dist-info/` 目录下。

---

## 如果你不想分发这些代码

两个选择：

1. **不进本仓库**：把 `vendor/` 加进 `.gitignore`，使用者自行安装那两个 skill，
   本项目的 `deps.py` 会去同级目录 / 环境变量 / `deps.local.json` 找它们（会降级但仍可用）。
2. **只留说明**：保留 `vendor/VENDOR.json` 作为版本锚点，不提交实际文件。

当前选择是**随包分发**，理由是使用者装完即可跑通全链路，不需要先找齐三个仓库。
