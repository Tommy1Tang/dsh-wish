# dsh-wish · 许愿式编程

### Wish-Driven Development (WDD) for [DeepSeek Harness](https://github.com/deepseek-ai)

**语言**：简体中文 · [English](README.en.md)

[![tests](https://github.com/Tommy1Tang/dsh-wish/actions/workflows/tests.yml/badge.svg)](https://github.com/Tommy1Tang/dsh-wish/actions/workflows/tests.yml)
[![python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](#要求)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

> 你说一句话，脑子里是一幅画。这条链的活儿不是"把你的话记下来"，
> 而是**在写第一行代码之前，把那幅画逼成一份只有一种读法、而且能被脚本判定的契约**。

一句需求进来 → 判它该走多重 → 问该问的问题 → 锁一份验收契约 → **契约不合格，不许开工**。

---

## 它解决什么问题

AI 写代码最常见的失败不是"写不出来"，是**写出来的不是你要的，而且你没法证明**。

| 没有它 | 有它 |
| --- | --- |
| 「我要个导出功能」→ 做出来是后台定时生成 CSV 落盘，而你想要的是页面上点一下下载 Excel | 契约写成：点『导出』→ 浏览器下载 `待办_20260101.xlsx` → 行数等于列表条数 |
| 交付时说「都做完了」，你只能信或不信 | `wish_lint` 退出码 0 才算合格，每一条都能复算 |
| 想清楚之前就开工，返工时已经写了两千行 | 两个检查点都在**写代码之前** |
| 每个需求都被拉进同一套重流程，改个 typo 也要 19 份文档 | 三档分流：改 typo 直接做，建系统才走全链 |

---

## 快速开始

### 要求

- DeepSeek Harness `0.2.x`
- Node.js ≥ 18（插件宿主半侧）
- Python ≥ 3.10（判据内核；**dsh 自带的 Python 3.12 可直接用**）
- 无第三方 Python 依赖

### 装成 dsh 插件（推荐）

```bash
git clone https://github.com/Tommy1Tang/dsh-wish.git
```

在 profile 的 `package.json` 里加两处：

```jsonc
{
  "dependencies": { "dsh-wish": "link:/path/to/dsh-wish" },
  "dsh": { "profile": { "bundles": [ /* ... */, "dsh-wish" ] } }
}
```

```bash
cd ~/.dsh/profiles/<你的 profile> && pnpm install
# 重启 dsh —— 新 bundle 不热加载
```

装好后模型多出四个工具：

| 工具 | 干什么 |
| --- | --- |
| `wish_route` | 判档：L0/L1/L2 + 工作类型 + 人审点 + 风险 + 该问什么 |
| `wish_focus` | 按档位出题，生成 `wish/<slug>/answers.md` |
| `wish_contract` | 回填 → 生成 `contract.md` → 跑检查 |
| `wish_lint` | 单独检查一份契约 |

> 想知道插件到底有没有生效？别猜，查会话日志——[有一节专门讲怎么看](#确认插件真的生效了)。

### 或者只当 skill 用

不想装插件、或换到别的 harness（Claude Code / Codex / Qoder），把本目录丢进 skill 根即可：

```bash
# Windows（junction，单一源不复制）
cmd /c mklink /J "%USERPROFILE%\.dsh\skills\dsh-wish" "D:\path\to\dsh-wish"
# macOS / Linux
ln -s /path/to/dsh-wish ~/.dsh/skills/dsh-wish
```

两种形态共用同一份 Python 内核——**插件只是外壳，判据一行都没复制**。

### 或者纯命令行

```bash
python router.py "做一个前后端都有的工单系统"        # 判档
python focus.py "做一个前后端都有的工单系统"         # 出题，建 wish/<slug>/
python focus.py --complete wish/<slug>              # 生成契约并检查
python contract_lint.py contract.md                 # 只检查一份契约
```

---

## 一次完整使用长什么样

```text
$ python router.py "要和供应商系统对接，每天同步库存"

档位：L2（enterprise）　类型：系统对接
依据：命中两个以上企业级特征：INTEGRATION + EXTERNAL_BOUNDARY
预计：2~6 小时　人审点：4 个

要你回答 2 个问题（已预填推荐答案）：
  Q1. 对方接口文档
  Q2. 联调谁配合
```

答完再跑：

```bash
$ python focus.py --complete wish/要和供应商系统对接-xxx
契约检查：FAIL
AC 条数：1
  ✗ [E1] AC-01：缺 `> 反例：`。举不出反例说明这条 AC 还没钉住
  ✗ [E4] AC-01：没有任何可观测对象（数字/文件名/引号内名称/界面元素）
```

补完再跑，直到 `PASS`。**在此之前不许写代码。**

---

## 三种档位

| 档位 | 什么时候 | 流程 | 人审点 | 耗时 |
| --- | --- | --- | --- | --- |
| **L0** 直接做 | 改 typo、解释代码、查日志、翻译 | 不进交付链 | 0 | 几分钟 |
| **L1** 标准 | 加个功能、修个 bug、改个口径 | 对焦 → 契约 → 假交付物 → 角色链 → 门禁 | 2 | 15~40 分钟 |
| **L2** 企业级 | 建系统、跨系统对接、有合规要求、要业务建模 | 建模 → 人审 → 模型 → 人审 → L1 全部 | 4 | 2~6 小时 |

**分档看的是「不确定性 + 影响面」，不是工作量。** 工作量只影响耗时估算。

同时还判**工作类型**（决定派谁、验什么）：

| 类型 | 形状 | 触发例 |
| --- | --- | --- |
| `fix` | 复现 → 定位 → 修复 → 回归 | bug / 报错 / 不生效 |
| `refactor` | **读现状 → 影响面 → 基线 → 兼容 → 小步改 → 回滚** | 老系统改造 / 技术栈迁移 / 拆微服务 |
| `data` | dry-run → 备份 → 执行 → 人确认 | 迁移 / 订正数据 |
| `integration` | 对方文档 → 对接清单签字 → 适配层 → 联调 | 对接 / 数据同步 |
| `report` | 口径 → 数据源 → 实现 → 对账 | 报表 / 对账 |
| `frontend` | UI 设计 → 实现 → 浏览器 E2E | 页面 / 样式 / 组件 |
| `backend` | 契约冻结 → 实现 → 单测/集成 | 接口 / 计算 / 定时任务 |
| `fullstack` | 契约冻结 → 并行 → E2E | 前后端一起改 |
| `ops` | 不进开发流程，走 deploy-only | 部署 / 重启 |
| `generic` | 通用链 | 识别不出类型时 |

> **「前端页面的 bug」判 `fix` 而不是 `frontend`**——修 bug 的步骤和写页面不一样。
>
> **改存量系统判 `refactor` 而不是 `fullstack`**——它的第一步不是设计，是**读懂现状**：
> 先跑 `detect_stack.py` 定技术栈、建代码索引，再列影响面清单，然后才动第一行。
> 它也不会套业务建模段——把 JSP 换成 Vue 不需要画 BPMN。

还有独立的**紧迫度**：命中「产线停 / 赶紧 / 线上挂」时，前置 `止血 → 记录 → 48 小时内补流程`。
救火不走完整流程，但**不许不留痕**。

---

## 契约长什么样

> 下面是一份**真的会被 lint 判定**的契约节选。完整版见
> [`examples/contract-good.md`](examples/contract-good.md)（PASS），
> 以及一组故意写坏的对照 [`examples/contract-bad.md`](examples/contract-bad.md)（命中 9 条规则）。
> 两份都在 CI 里跑，不会跟规则脱节。

```markdown
## 验收条目（每条必须只有一种读法）

### AC-01
- **判定方式**：在待办列表页点『导出』，浏览器下载 `待办.xlsx`，
  用 Excel 打开第一行是「编号/标题/状态」，数据行数等于当前列表条数
> 反例：只把数量乘单价显示出来，没有真的重算 —— 数字对上了，逻辑没换

### AC-02
- **判定方式**：While 订单处于待支付状态期间，系统保留库存且取消按钮可点
> 反例：按钮可见但点击报错 —— 看着能取消，实际不能

### 本次不做
- 权限矩阵 / 消息通知 / 移动端

## 状态枚举
| 状态 | 说明 |
| --- | --- |
| 待支付 | 已下单未付款 |
| 已取消 | 用户或系统取消 |

## 什么情况下可以放弃（dropped）
| 理由码 | 含义 | 确认人 |
| --- | --- | --- |
| `not-reproducible` | 复现不出来 | 提需求的人 |
| `obsolete` | 需求已废弃 | 业务方 |
| `already-exists` | 现有功能已覆盖 | 提需求的人 |
| `out-of-scope` | 不属本项目范围 | 项目负责人 |
```

### 检查什么（10 条规则，退出码即结论）

| 规则 | 检查 |
| --- | --- |
| E1 | 每条 AC 必须附 `> 反例：` |
| E2 | 每条 AC 必须有判定方式 |
| E3 | 不得出现模糊词（友好 / 合理 / 尽量 / 快速 / 适当…） |
| E4 | 每条 AC 至少一个可观测对象（数字 / 文件名 / 引用名称 / 界面元素） |
| E5 | 必须有「放弃条款」 |
| E6 | 放弃条款必须给固定理由码 + 签字人 |
| E7 | 涉及状态/异常的 AC 必须用 EARS 句式（When / While / If / Where） |
| E8 | 声明了状态枚举，每个状态都必须有 AC 覆盖 |
| S1 | 「本次不做」不得为空 |
| S2 | AC 编号必须连续 |

---

## 常见问题

**Q：它帮我写代码吗？**

不写。它负责**把需求逼清楚、把验收钉死**，代码由 dsh 的模型或你指定的执行体来写。
装完不等于自动开发，等于"不会糊里糊涂地开发"。

**Q：会不会很慢很烦？**

改 typo、解释代码、查日志这类会判成 **L0，一个问题都不问**，直接做。
只有 L1 才问最多 3 个问题，每题都带推荐答案——**答「是」就行**。

**Q：判错了怎么办？**

1. 判据是纯规则（不是模型），所以同样的输入永远同样输出，**能追到是哪条信号判的**；
2. 回答里出现新信息时会**自动改口**并告诉你原因；
3. 真觉得不对，改 `router.py` 顶部的规则表，跑 `python tests/test_router.py`，红的那条就是被影响的行为。

**Q：没装 `agent-delivery-gate` / `research-to-project-input` 能用吗？**

**能。** 这两个执行体已经随包放在 `vendor/` 里，clone 下来就是完整版。
如果你自己装了更新版本，`deps.py` 也支持用环境变量指向它们。

**Q：会不会把我的需求发到网上？**

不会。判档和契约检查全是本地 Python，**不联网、不调用任何模型**（模型只在对焦提问时参与）。

**Q：支持 Claude Code / Codex / Qoder 吗？**

支持，但只有 skill 形态（`SKILL.md`）。插件形态是 dsh 专用的。

**Q：为什么叫"许愿式"？**

因为用户给的是一句话，脑子里是一幅画。英文用 **Wish-Driven** 而不是 wishful——
`wishful thinking` 在英文里是"一厢情愿"，那是这个项目要治的病，不是它的名字。

---

## 确认插件真的生效了

不要靠"看工具列表觉得像新的"。**查会话日志**，那里面是实际发给模型的内容：

```bash
node -e "
const fs=require('fs'), zlib=require('zlib');
const buf=fs.readFileSync(process.argv[1]);
const magic=Buffer.from([0x28,0xB5,0x2F,0xFD]);
let pos=0, cuts=[]; while(true){const i=buf.indexOf(magic,pos); if(i<0)break; cuts.push(i); pos=i+1;}
let out=''; for(let k=0;k<cuts.length;k++){const s=cuts[k],e=k+1<cuts.length?cuts[k+1]:buf.length;
  try{out+=zlib.zstdDecompressSync(buf.subarray(s,e)).toString('utf8')}catch{}}
console.log('提示片段在:', out.includes('【许愿式编程】'));
console.log('工具描述在:', out.includes('下一步：L0 直接做'));
" ~/.dsh/sessions/<你的会话目录>/session.v4.jsonl.zstd
```

两个都 `true` = 插件、工具描述、系统提示片段**三层都进了模型上下文**。

---

## 项目结构

```text
dsh-wish/
├── lib/index.js          插件宿主半侧：注册 4 个工具，shell out 到 Python
├── router.py             判档内核（三维度 + 三判据）
├── focus.py              对焦：出题 → 回填 → 生成契约
├── contract_lint.py      契约检查（10 条规则），退出码即结论
├── deps.py               执行体探测与降级
├── refs.py               外部引用核对
├── templates/            契约模板
├── vendor/               随包分发的两个执行体（见 THIRD_PARTY_NOTICES.md）
├── tools/sync_vendor.py  vendor 同步与溯源
└── tests/ + test/        185 个测试
```

---

## 相关文档

- [PLAN.md](PLAN.md) —— 为什么这么设计、判据的来历、**已知不解决什么**（想评估可靠性先读这个）
- [SKILL.md](SKILL.md) —— skill 形态的操作说明
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) —— `vendor/` 里两个执行体的许可证与归属

## License

[MIT](LICENSE)。`vendor/` 下的两个执行体沿用各自许可证，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
