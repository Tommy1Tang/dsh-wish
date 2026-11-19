# dsh-wish · 许愿式编程

**完整版 dsh 插件**：装完就能跑全链路，不依赖本机其他仓库。

- 4 个工具：`wish_route` / `wish_focus` / `wish_contract` / `wish_lint`
- 判据内核全是 Python（142 个测试）
- **`vendor/` 里随包带着两个执行体**：
  - `agent-delivery-gate`（2.8 MB / 292 文件）—— 21 节点流程、门禁、schema
  - `research-to-project-input`（14.2 MB / 471 文件）—— L2 的建模段、BPMN/OWL、SHACL

一句话需求进来，先判它该走多重，再逼出一份**可机械验收**的契约。
不判满不上工，契约不过 lint 不算完成。

```text
一句话愿望
   ↓  wish_route     判档：L0 直接做 / L1 角色链 / L2 先建模
   ↓  wish_focus     按档位出题（L0 不问 / L1 ≤3 问 / L2 不限）
   ↓  人答
   ↓  wish_contract  生成 contract.md 并跑 lint
   ↓  wish_lint      退出码 1 = 不合格，不许开工
执行：vendor/agent-delivery-gate 的 21 节点门禁
交付
```

---

## 装成插件

```jsonc
// ~/.dsh/profiles/<profile>/package.json
"dependencies": { "dsh-wish": "link:D:/aiskills/dsh-wish" },
"dsh": { "profile": { "bundles": [/* ... */, "dsh-wish"] } }
```

```bash
cd ~/.dsh/profiles/<profile> && pnpm install
# 然后重启 dsh —— 新 bundle 不热加载
```

装好后模型会多出四个工具：`wish_route` / `wish_focus` / `wish_contract` / `wish_lint`。

## 或者只当 skill 用

```bash
# 把本目录链到 skill 根（单一源，不复制）
cmd /c mklink /J "%USERPROFILE%\.dsh\..\dsh\skills\dsh-wish" "D:\aiskills\dsh-wish"
```

两种形态共用同一份 Python 内核——**插件只是外壳，判据一行都没复制**。

---

## 完整版：执行体随包带着

`vendor/` 里是两个执行体的快照，**同步自各自仓库**，不是手抄：

```json
// vendor/VENDOR.json
"gate": { "source": "D:/aiskills/.../agent-delivery-gate",
          "commit": "d0d220ca…", "files": 292, "bytes": 2798107,
          "syncedAt": "2026-11-16T11:51:45" }
"r2pi": { "source": "D:/aiskills/research-to-project-input",
          "commit": "eda30b91…", "files": 471, "bytes": 14217989,
          "syncedAt": "2026-11-16T11:51:45" }
```

同步与校验：

```bash
python tools/sync_vendor.py            # 从源仓库刷新
python tools/sync_vendor.py --check    # 只检查是否落后于源
```

`refs.py` 拿这份记录核对 6 条引用；`test_vendor.py` 真跑一次 vendor 里的脚本
（`validate_delivery.py --help`、`next_step.py --check`），确认**拷了文件不等于能跑**这件事没有发生。

> 依然保留降级路径（`--no-gate` / `DSH_WISH_GATE` 指向别处）用于测试，
> 但**默认行为是完整版**。

---

## 命令行（不走插件也能用）

```bash
python router.py "一句话"                     # 判档
python router.py --json "一句话"              # 结构化输出
python router.py "一句话" --answers "回答"     # 答完重新判档
python focus.py "一句话"                      # 建 wish/<slug>/ 并出题
python focus.py --complete wish/<slug>        # 生成契约并跑 lint
python contract_lint.py contract.md           # 只检查契约
python refs.py                                # 核对 6 条外部引用
python run_tests.py                           # 全量测试
```

## 为什么用规则而不是模型

三个理由，都是被前面两轮源码调查逼出来的：

1. **可复算**。同样输入永远同样输出。档位判错了要能追到"是哪条信号判的"，而不是"模型这次觉得"。
2. **可争论**。所有判据集中在 `router.py` 的 `RULES` 区块。你觉得"多角色不该算企业级"，改一行常量即可——不用重训、不用改提示词。
3. **可测试**。51 个测试锁住行为。改口径时先看哪个测试红了，比肉眼 review 提示词靠谱。

模型该做的是**对焦时和用户讨论 AC**，不是判断"这算不算复杂"。

---

## 两个正交维度：档位 + 工作类型

档位回答「多重」，工作类型回答「派谁、跑哪几段、验什么」。**两件事一起输出，不能只判一个。**

| profile | 形状 | 关键验收 |
| --- | --- | --- |
| `ops` | 不走开发流程，进 deploy-only | 留痕 + 回滚命令 |
| `data` | dry-run → 备份 → 执行 → 人确认 | 不可逆，禁止 AI 代签 |
| `fix` | 复现 → 定位 → 修复 → 回归 | 先红后绿；不做顺手重构 |
| `report` | 口径 → 数据源 → 实现 → 对账 | 数字与手工核算一致 |
| `frontend` | 对焦 → UI 设计 → 实现 → 浏览器 E2E | 真浏览器 |
| `backend` | 对焦 → 契约 → 实现 → 单测/集成 | E2E 走 CLI/HTTP |
| `fullstack` | 对焦 → 契约冻结 → 并行 → E2E | 未冻结禁止并行 |

「前端页面的 bug」判 `fix` 不是 `frontend`——**修 bug 的步骤和写页面不一样**。

`urgent`（产线停/赶紧/线上挂）独立于两者：前置 `止血 → 记录 → 48 小时内补流程`，
L0 时只保留这三段。**救火不走完整流程，但不许不留痕。**

---

## 三档是什么

| 档位 | 名字 | 流程 | 人审点 | 耗时 |
| --- | --- | --- | --- | --- |
| `L0` | quick | 直接做，不进交付链 | 0 | 几分钟 |
| `L1` | standard | 对焦 → PRD/AC → 假交付物 → 角色链 → 门禁 | **2** | 15~40 分钟 |
| `L2` | enterprise | 建模 → 人审 → 模型 → 人审 → L1 全部 | **4** | 2~6 小时 |

两个检查点都在**写代码之前**：对焦（锁契约）+ 假交付物（指着说"不是这个"）。

**分档判据不是"工作量"，是"不确定性 + 影响面"。** 工作量只影响耗时估算；不确定性才决定要不要先建模、要不要插人审。

---

## 判定优先级

```text
1. 单信号强档（SCALE）      → L2   （从0到1/全新系统/推倒重来）
2. 企业级信号 ≥ 2           → L2   （流程/多角色/集成/合规/调研/迁移/行为变更）
3. 交付面 ≥ 3               → L2   （数据/逻辑/接口/界面/集成，见下）
4. 加权分 > 7               → L2
5. 命中否决词               → L0   （改typo/解释/翻译/查一下/跑个命令）
6. 命中开发/修复意图        → L1
7. 加权分 > 2               → L1
8. 其余                     → L0
```

**第 3 条是后加的，因为前两条绑在措辞上。** 「从0到1建系统」和「做一个前后端都有的工单系统」
是同一件事，但只有前者命中关键词。所以改数**交付面**：

| 愿望 | 面 | 判定 |
| --- | --- | --- |
| 前后端工单系统，Vue + Spring | api/logic/ui | **L2** |
| 纯前端看板，从接口拿数据 | api/ui | L1 |
| 实现一个登录接口 | api | L1 |
| 加一个导出按钮 | ui | L1 |

**≥3 个面 = 必须先冻结契约再并行**，这就是 L2 的形状，跟工作量大小无关。

反例：「在现有系统里加一个字段，前端展示出来」跨 4 个面，但每个面都是小改——
所以有 `PASSTHROUGH` 豁免（加字段/透传/展示出来），命中时面数不参与分档。

顺序有意义：**否决词压不过企业级组合与面数**——"先看一下现状，然后要做一套审批流对接 ERP"
仍然该进 L2。这两条都有专门的测试。

---

## 输出长什么样

`router.py` 报告六块：档位判定与依据、分维度得分、命中的判据（带原文片段）、要跑的 stage、人审点表、还缺什么。

---

## 对焦清单与提问预算

档位不仅决定跑多少 stage，**还决定人被问几次**：

| 档位 | 提问预算 | 问什么 |
| --- | --- | --- |
| `L0` | 0 | 一句都不问 |
| `L1` | 3 | 缺的验收标准 / 角色 / 边界 |
| `L2` | 不限 | 业务调研本来就该访谈 |

清单分成三类，顺序不能换：

1. **`kind=fact` —— 自己去查，不问人。** 技术栈读 `tech.md`，现状派 subagent 读代码。
   抄自 `grilling` 的原则：`Finding facts is your job, never the user's`。
2. **`kind=decision` —— 必须问人，每条带推荐答案。** 抄自 `grilling` 的
   `Word each question so "yes" accepts your recommended answer`：把「问 10 个问题」
   的成本从 10 次思考降到 10 次确认。
3. **`kind=escalation` —— 不用回答，只是提示。** L1 时会附一条：如果你的回答里出现
   多部门协作 / 对接外部系统 / 审批状态流转 / 合规审计 / 存量迁移，那这件事其实是 L2。

### 为什么不是「先 grill 再判档」

`grilling` 的完成条件是「前沿为空：每个分支都走过，没有默默假设」——那是设计评审的标准。
一个 15 分钟的任务走完这棵树要问 15~20 个问题，产品当场就死了。

正确顺序是：**粗判档位 → 按档位给提问预算 → 提问结果回写并允许升档 → 锁定**。
**升档是正常路径，不是判档失败**：用户说「加个导出按钮」→ L1，问出「要对接金蝶、月度关账前必须出」→ 升 L2。

同一套技能家族里 `loop-me` 的主张正好相反且更适用于我们：

> **Push right**: defer the checkpoint as far as it will go. Do maximal work before involving the human.
> **Brief**: the user reads a brief, not a draft.

许愿式编程属于后者——人只该在「东西齐了、就等你一句话」时出现。

### 答完自动改口（不指望用户自诊断）

用户不需要知道自己该是 L1 还是 L2——他只要如实回答问题，**系统在他答完之后重新判一遍**：

```bash
python router.py "加一个导出按钮" --answers "导出是给财务对账用的，要走审批流程，还要对接金蝶的凭证接口"
```

```text
你这几句把这件事从 L1 推到 L2——因为 BUSINESS_FLOW(+3)：涉及业务流程/状态/规则、
DOMAIN_DATA(+2)：涉及领域实体与数据口径、INTEGRATION(+2)：跨系统集成。
多加业务建模段和两道人审，耗时 15~40 分钟 → 2~6 小时。
已按 L2 重排，不需要你判断；如果这不对，说一句就退回。
```

三条设计规矩：

1. **归因只算「回答里出现、原文没有」的信号**。否则等于把原判断重算一遍，用户看不出是哪句话改的档。
2. **默认按新档位走，只给一句「不对就说」的口子**。不让用户在"要不要升档"上做判断——那是系统的事。
3. **不做否定消解**。回答里说「其实不接 SAP」时，原文还在，`reroute` 不会替你猜要删哪一段，而是标记 `needsRestatement` 并请你重述整条愿望。**猜错比不猜贵。**

### 一个必须知道的数学事实

分类器对输入是**单调**的：`original + answers` 是原文的超集，所以**分数只增不减**。
这意味着：

- 升档可以自动发生（这正是我们要的）
- **降档只有两条路**：回答里出现否决词（「算了先解释一下就行」→ 退回 L0），或用户重述整条愿望

这条限制是有意的。自动"猜哪句需求作废了"会带来不可解释的档位抖动，比多问一句贵得多。

---

### grilling 治不了的部分

grilling 的前提是**用户心里有答案但没说出来**。另一种常见情况是**看到东西才知道要什么**——
这时候越问越烦。那要用原型（10~20 分钟做个玩具给他指着说「不是这个」），
而档位正好可以用来决定这两种手段各投多少。

---

## 想改口径时改哪里

全在 `router.py` 顶部：

| 想改什么 | 改哪里 |
| --- | --- |
| 什么算"不该进流水线" | `QUICK_VETO` |
| 什么算"至少是开发任务" | `DEV_INTENT` |
| 什么算"企业级特征" | `ENTERPRISE_SIGNALS` |
| 分档分数线 | `THRESHOLDS` |
| 每档问几个问题 | `PROBE_BUDGET` |
| 问什么 | `build_probes` 里的 `gap_map` |
| 升档触发器文案 | `build_probes` 末尾那条 `escalation` |
| 各信号的权重 | 各 `Signal(...)` 的第一个数字 |
| 每档的 stage 与人审点 | `stages_for` / `checkpoints_for` / `TIER_META` |

改完跑 `python tests/test_router.py`，红的那条就是被改动影响的行为。

---

## 已知的不做

- **不调用模型**。需要语义理解的部分（"用户到底想要什么"）留给对焦环节。
- **不探测项目现状**。不读 cwd、不猜技术栈、不判断仓库大小。这些是 `preflight_env_check.py` 和 `tech.md` 的事。
- **不决定 AC**。它只说"该走哪条路"，不写验收条目。
- **不做持久化**。当前是纯函数。要挂进 dsh 插件时，结果由调用方写进 `wish/<id>/route.json`。

## 与三个项目的关系

| 项目 | 关系 |
| --- | --- |
| `agent-delivery-gate` | L1/L2 的执行体。本路由器只产出它的入口参数（档位、要跑的 SP 节点、要人审的点） |
| `research-to-project-input` | L2 的前置建模段。产出 `docs/input/00-07` + `models/baseline-manifest.json`，gate 的 `validate_input_contract.py` 直接能验（C-INPUT-01..04） |
| `dsh-superagent` | 不在本阶段。它解决"多工单/常驻/面板"，不解决档位判断；到 P3 再引 |

---

## 下一步（未做）

1. 把 `route.json` 接进 `/wish` 命令，档位作为不可变的 `Mandate` 落地。
2. L1 的「对焦」环节：用 `ask_user_question` 把 `gaps` 逐条问掉，产出 `contract.md`。
3. 档位纠偏回流：记录"实际跑下来超时/返工"的愿望，回填为新的信号权重。

第 3 条是这个路由器唯一能变准的途径——它现在靠我从三个项目里读出来的判断，还没有真实数据。
