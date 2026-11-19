#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""档位路由器 (Wish Tier Router).

输入一段愿望文本, 判定该走哪一档交付流程, 并给出: 为什么这么判 / 要跑哪些 stage /
要在哪几个点叫人 / 还缺什么信息.

设计原则
--------
1. 确定性. 纯规则 + 权重, 不调用任何模型. 同样输入永远同样输出 -> 可复算, 可测试,
   判错了能追到是哪条规则判的.
2. 判据集中. 所有阈值和信号都在 RULES 里, 想改口径只改那一个地方.
3. 档位按"不确定性 + 影响面"分, 不按"工作量"分. 工作量只影响耗时估算,
   不确定性才决定要不要建模、要不要插人审点.

三档
----
L0 quick       不走交付链, 直接做. 改字/解释/翻译/查一下.
L1 standard    默认. 对焦 -> PRD/AC -> 角色链 -> 门禁 -> 交付.
L2 enterprise  需求需要业务建模(流程/角色/状态/规则), 或要跨系统, 或要合规.
               research-to-project-input -> 人审建模 -> 人审模型 -> gate 全链.

用法
----
    python router.py "帮我做一个车间工单管理系统"
    python router.py --file wish.md --json
    python router.py --explain "需求文本"
    python router.py --selftest
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import deps  # noqa: E402

# ===========================================================================
# RULES -- 所有可争论的判据都在这里. 改档位口径只改这一段.
# ===========================================================================

TIERS = ("L0", "L1", "L2")

TIER_META = {
    "L0": {
        "name": "quick",
        "pipeline": "直接做",
        "duration": "几分钟",
        "review": 0,
        "summary": "不走交付链：不过 PRD、不派角色、不出 19 份文档",
    },
    "L1": {
        "name": "standard",
        "pipeline": "对焦 → PRD/AC → 假交付物 → 角色链 → 门禁 → 交付",
        "duration": "15~40 分钟",
        "review": 2,
        "summary": "标准档：先锁一份验收契约，再让角色跑，最后用脚本裁决",
    },
    "L2": {
        "name": "enterprise",
        "pipeline": "业务建模 → 人审建模 → 人审模型 → 输入契约门禁 → PRD/AC → 假交付物 → 角色链 → 门禁",
        "duration": "2~6 小时",
        "review": 4,
        "summary": "企业档：先把业务搞对，再谈代码；人审全卡在写代码之前",
    },
}

# 分数阈值: score <= quick_max 走 L0; <= standard_max 走 L1; 更高走 L2
THRESHOLDS = {"quick_max": 2, "standard_max": 7}

# --- 交付面: 一条需求要牵动几个面. >=3 个面 = 必须契约冻结 + 并行 = L2 ----
# 比"系统/平台"这类措辞可靠: 措辞会变, 面不会.
SURFACES = [
    ("data", r"(表结构|字段|数据库|数据模型|主数据|迁移|导数据|洗数据)"),
    ("api", r"(接口|API|服务端|契约|后端|微服务|后端服务)"),
    ("ui", r"(页面|界面|按钮|表单|列表|看板|大屏|弹窗|交互|样式|前端|展示|渲染)"),
    ("integration", r"(集成|对接|同步|外部系统|第三方|打通)"),
]
LOGIC_SURFACE = r"(计算|规则|校验|算法|逻辑|判定|齐套|流程|状态)"
SURFACE_MIN_FOR_L2 = 3

# 穿透 ≠ 新建. "加一个字段从前端透到后端"跨三个面, 但每个面都是小改;
# 拿面数把它判成 L2, 等于给"加个字段"配契约冻结。命中这个信号时面数不参与分档。
PASSTHROUGH = r"(加一个?字段|新增一个?字段|多加一个?字段|透传|字段带出来|展示出来|显示出来|带上这个字段)"


def detect_surfaces(text: str, hit_ids: set[str]) -> set[str]:
    """数这条需求要动几个面: 数据 / 逻辑 / 接口 / 界面 / 集成.

    一个面 = 一个人能独立干完；
    三个面以上 = 必须先冻结契约、再并行、再联调——那就是 L2 的形状，
    跟这条需求"看起来大不大"无关。
    """
    found: set[str] = set()
    for name, pattern in SURFACES:
        if re.search(pattern, text, re.IGNORECASE):
            found.add(name)
    if hit_ids & {"BUSINESS_FLOW", "BEHAVIOR_CHANGE"} or re.search(LOGIC_SURFACE, text):
        found.add("logic")
    return found


# 提问预算: 档位决定"人要被问几次". L0 一次都不问, L2 不限 (业务调研本就要访谈).
PROBE_BUDGET = {"L0": 0, "L1": 3, "L2": 999}

# --- 工作类型 (profile): 决定派谁、跑哪几段, 与档位正交 ----------------------
# 优先级有意排过: 路径形状由"部署/数据/修复"决定, 而不是由"前端后端"决定.
PROFILE_RULES = [
    ("ops", r"(部署|发布到|上线到|重启|配置一下|装个环境|环境准备|打个包)",
     "运维操作 —— 不进开发流程"),
    ("data", r"(迁移|导数据|数据清洗|初始化数据|批量修改|修数据|订正数据)",
     "数据处理 —— 不可逆, 必须先 dry-run"),
    ("fix", r"(BUG|bug|修复|报错|不生效|失效|错乱|跑不通|崩溃|异常)",
     "缺陷修复 —— 复现优先于设计"),
    ("integration", r"(对接|集成|打通|接对方|接第三方|同步数据|数据同步)",
     "对接 —— 对方的进度不是你能控制的"),
    ("refactor", r"(老系统|遗留系统|存量|技术债|技术栈.{0,8}(迁移|升级|替换)|拆成.{0,6}微服务|架构重构|系统升级)",
     "存量改造 —— 第一步不是设计，是读懂现状"),
    ("report", r"(报表|统计口径|对账|台账|月报|日报|指标定义)",
     "报表类 —— 口径就是需求"),
    ("fullstack", r"(前后端|全栈|整个系统|端到端|整条链路)",
     "全栈 —— 契约冻结是并行前置"),
    ("frontend", r"(页面|样式|组件|前端|交互|响应式|UI设计|Vue|React|H5|按钮|表单|弹窗|布局|配色)",
     "前端 —— 看效果, 不看文档"),
    ("backend", r"(接口|API|服务端|后端|数据库|定时任务|消息|队列|存储过程|计算|算法|逻辑)",
     "后端 —— 看契约与数据"),
]

# 紧迫度: 不改变档位, 改变路径顺序 (先止血, 后补流程)
URGENT_PATTERN = r"(紧急|赶紧|马上|立刻|产线停|线上挂|客户在等|今天就要|火烧眉毛|P0|急)"

# 每个 profile 的 stage 形状. {tier_stages} 会按档位拼接.
URGENT_STAGES = [
    "【止血】先让人能用：最小改动 / 手动操作 / 回滚，不追求完备",
    "【记录】当场记下改了什么、为什么、谁要求的（一句话即可）",
    "【补流程】48 小时内补契约与回归，否则视为未交付",
]

# 这两个 profile 不管档位多低都要走自己的形状: 运维不可跳, 数据不可逆
PROFILE_ALWAYS = ("ops", "data")
PROFILE_STAGES = {
    "ops": [
        "不走开发流程：直接进 gate 的 deploy-only 路由（Orchestrator → DevOps → 验证）",
        "禁止顺手改代码：发现要改代码就回退成对应 profile",
        "留痕：部署记录 + 回滚命令",
    ],
    "data": [
        "先 dry-run：在副本上跑一遍，输出影响行数与样例",
        "备份：迁移前快照 + 回滚脚本",
        "执行 + 校验：行数 / 关键字段对账",
        "不可逆操作必须有人确认（AI 不得代签）",
    ],
    "fix": [
        "复现：写一条会失败的用例（先红）",
        "定位：根因，不是症状；说清「为什么现在才出现」",
        "修复：最小改动，不做顺手重构",
        "回归：原用例转绿 + 跑一遍相邻用例（证明没弄坏别的）",
        "写清影响面：谁还会被这个改动影响",
    ],
    "report": [
        "对焦口径：指标定义、时间范围、维度、汇总规则（这四条就是需求）",
        "数据源确认：字段从哪来、有没有、准不准（未知项必须问）",
        "实现",
        "对账：报表数字与手工核算/既有系统逐项一致，差异要能解释",
        "权限：谁能看、能导出（报表最容易漏的一条）",
    ],
    "integration": [
        "要对方的接口文档 / 字段表 / 同步频率 / 失败重试约定",
        "对接清单：字段映射 + 主数据对齐 → 对方签字确认",
        "适配层实现 + mock 环境（不依赖对方在场就能开发）",
        "联调（对方排期是外部依赖，计划按对方不配合来排）",
        "异常场景逐个跑：断线 / 重复推送 / 乱序 / 对方改字段",
    ],
    # 存量改造：第一步不是设计，是读懂现状。
    # 没有"影响面清单"就动手 = 不知道会改坏什么，也不知道改完怎么证明没改坏。
    "refactor": [
        "读现状：技术栈探测 + 建代码索引，先搞清楚项目长什么样（不是猜）",
        "影响面清单：这次会动到哪些文件 / 接口 / 调用方 / 数据表，逐条列出来",
        "改之前先跑一遍基线测试并存好结果 —— 没有基线就不知道改坏了什么",
        "兼容策略：接口与数据要不要过渡期（版本化 / 双写 / 灰度）",
        "小步改 + 每步回归，不要一次改完再测",
        "回滚预案：出问题怎么退回去（分支 / 开关 / 数据快照）",
    ],
    "frontend": [
        "对焦：AC 写成「看到什么」（页面元素/文案/交互）",
        "UI 设计：ui-designer → 设计说明（颜色/间距/空态/错误态）",
        "前端实现",
        "浏览器 E2E：真浏览器跑，不用接口测试代替",
        "边界：空态、加载态、错误态、窄屏",
    ],
    "backend": [
        "对焦：AC 写成「接口返回什么」（字段/状态码/耗时）",
        "接口契约：data-contract-designer → 契约冻结",
        "后端实现",
        "单元 + 集成测试",
        "E2E：走 CLI / HTTP 公开入口，至少一个端到端场景",
    ],
    "fullstack": [
        "对焦：前后端各自的 AC 分开写",
        "接口契约冻结（SP-06）—— 未冻结禁止并行派工",
        "后端 / 前端并行实现",
        "浏览器 E2E + 接口集成",
    ],
    "generic": ["对焦", "实现", "验证"],
}

# refactor 的排列和别人不一样：读现状 → 对焦 → 其余。
# 拆成两个常量而不是靠列表切片下标，免得哪天改了顺序就错位。
REFACTOR_AFTER_FOCUS = [
    "影响面清单：这次会动到哪些文件 / 接口 / 调用方 / 数据表，逐条列出来",
    "改之前先跑一遍基线测试并存好结果 —— 没有基线就不知道改坏了什么",
    "兼容策略：接口与数据要不要过渡期（版本化 / 双写 / 灰度）",
    "小步改 + 每步回归，不要一次改完再测",
    "回滚预案：问题怎么退回去（分支 / 开关 / 数据快照）",
]


def refactor_read_now(precise: bool) -> list[str]:
    """改造存量时的"读现状"两步。精确版给能直接跑的命令，通用版给做法。"""
    if not precise:
        return ["读现状：技术栈探测 + 建代码索引，先搞清楚项目长什么样（不是猜）"]
    p = deps.cmd_prefix()
    return [
        f"读现状 1：python {p}scripts/detect_stack.py <项目根>"
        " —— 定技术栈与目录布局，不靠猜",
        f"读现状 2：python {p}scripts/build_code_index.py（按需）"
        " —— 建代码索引，后面影响面分析靠它",
    ]
ENTERPRISE_SIGNALS = (
    "SCALE", "BUSINESS_FLOW", "MULTI_ROLE", "INTEGRATION", "EXTERNAL_BOUNDARY",
    "COMPLIANCE", "RESEARCH", "MIGRATION", "BEHAVIOR_CHANGE",
)


@dataclass(frozen=True)
class Signal:
    """一条判据. weight 决定它把分数推高多少; dim 用于分维度报告."""

    id: str
    dim: str
    weight: int
    pattern: str
    note: str


# --- 降级否决: 命中即 L0 (除非同时命中 L1_MIN / L2 组合) ---------------------
QUICK_VETO = [
    Signal("TYPO", "scope", 0, r"(改个?typo|错别字|拼写错误|改个?名字|改个?变量名|加.{0,4}注释|删掉这行|格式跑了)",
           "单点微调, 无交付物"),
    Signal("EXPLAIN", "scope", 0, r"(解释一下|说明一下|这个函数|这段代码|什么意思|为什么报错|这个报错|怎么理解)",
           "阅读理解, 答疑而非开发"),
    Signal("TEXTWORK", "scope", 0, r"(翻译一下|润色一下|缩写一下|改写一下|总结一下这段)",
           "纯文本处理"),
    Signal("LOOKUP", "scope", 0, r"(查一下|看一下|对比一下|哪个更好|找一下这个文件|看看项目结构)",
           "探索/咨询, 无代码产出"),
    Signal("RUNABCMD", "scope", 0, r"(运行一下测试|执行这个命令|帮我跑一下|重启服务)",
           "纯运维操作"),
]

# --- 开发意图: 命中则至少 L1 -------------------------------------------------
DEV_INTENT = [
    Signal("DEV", "intent", 1,
           r"(做一?个|开发|实现|新增|改造|重构|搭建|写一?个|帮我做|上线|接入|支持|加上|增加|添加|加一?个|加个|优化|升级)",
           "有明确开发诉求 —— 至少 L1"),
]

# --- 项目规模: 命中即 L2, 不看分数 (单信号强制) ------------------------------
SCALE = [
    Signal("SCALE", "scale", 3,
           r"(从0到1|从零开始|从零搭建|全新系统|重新设计.{0,6}(系统|平台)|整套系统|整个系统|"
           r"系统级重构|多模块|全模块|替代现有系统|推倒重来|一期上线|全新开发)",
           "项目级规模 —— 不是改造，是重做"),
]

# --- 存量改造: 风险在"改坏"不在"做不出来", 单信号强制 L2 -------------------
# 触发词刻意收窄，不收单说「改造/重构」：
#   「改造登录页样式」是 frontend，不是存量改造。
# 只有涉及老系统、技术栈替换、架构拆分时才算，因为那时第一步不是设计，是**读懂现状**。
LEGACY = [
    Signal("LEGACY", "scale", 3,
           r"(老系统|遗留系统|技术债|存量(系统|代码|功能|数据)|"
           r"技术栈.{0,8}(迁移|升级|替换)|从.{1,10}(迁移|改造?)到|"
           r"拆成.{0,6}(微服务|服务)|架构(级|层)?重构|整体重写|系统升级到)",
           "存量改造 —— 先读懂现状，才敢动第一行"),
]

# --- 缺陷修复: 至少 L1 (但单独不构成行为变更) -------------------------------
FIX = [
    Signal("FIX", "intent", 1,
           r"(BUG|bug|修复|报错|异常|失效|错乱|跑不通|不生效|卡住|崩溃)",
           "缺陷修复 —— 至少 L1"),
]

# --- 变更风险: 影响历史数据与下游, 比"新增"危险得多 -------------------------
RISK = [
    Signal("BEHAVIOR_CHANGE", "risk", 2,
           r"(改.{0,8}(计算方式|算法|规则|逻辑|口径|公式)|调整.{0,8}(规则|逻辑|口径|算法)|"
           r"变更.{0,8}(规则|口径|逻辑)|修正.{0,8}(计算|规则|逻辑)|重算|口径.{0,4}变|"
           r"(?:算法|规则|逻辑|口径|公式|计算方式).{0,6}(?:要改|改了|变了|调整|不对|错了|换掉))",
           "行为变更 —— 影响存量数据与下游报表"),
]

# --- 业务复杂度 -------------------------------------------------------------
BUSINESS = [
    Signal("BUSINESS_FLOW", "business", 3,
           r"(流程|审批|工单|流转|泳道|状态机|状态流转|规则引擎|业务规则|单据|审批流|签核)",
           "涉及业务流程/状态/规则 —— 建模档的核心信号"),
    Signal("MULTI_ROLE", "business", 2,
           r"(多角色|角色权限|权限矩阵|多个角色|两种角色|不同部门|审批人|主管审批|管理员和|操作员和)",
           "涉及多角色与权限边界"),
    Signal("DOMAIN_DATA", "business", 2,
           r"(主数据|物料|批次|库存|BOM|工艺|设备|点检|质检|仓储|台账|对账|结算)",
           "涉及领域实体与数据口径"),
    Signal("REPORTING", "business", 1,
           r"(报表|统计口径|看板|大屏|指标|月报|日报|汇总)",
           "涉及统计口径"),
]

# --- 需求不确定性 (权重最高: 直接决定要不要先建模 + 人审) --------------------
UNCERTAINTY = [
    Signal("VAGUE", "uncertainty", 3,
           r"(不太清楚|大概|可能|应该|差不多|类似|对标|参考|听说|老板说|客户说|他们那边)",
           "需求本身没有收敛 —— 需要先对焦"),
    Signal("RESEARCH", "uncertainty", 3,
           r"(调研|业务方|需求方|甲方|现状|痛点|现场|访谈|座谈)",
           "需要业务调研才能定需求 —— 建模档信号"),
    Signal("NO_DONE", "uncertainty", 2,
           r"(能跑就行|差不多就行|先做出来再说|看着办)",
           "没有验收标准 —— 跑起来一定跑偏"),
]

# --- 系统复杂度 -------------------------------------------------------------
SYSTEM = [
    Signal("INTEGRATION", "system", 2,
           r"(集成|对接|打通|接口协议|第三方系统|外部系统|"
           r"(?:SAP|ERP|MES|PLM|WMS|CRM|OA).{0,8}(?:集成|对接|接口|同步|打通)|"
           r"(?:集成|对接|打通|接).{0,8}(?:SAP|ERP|MES|PLM|WMS|CRM|OA))",
           "跨系统集成 —— 企业档信号（系统名本身不算，要有对接动作）"),
    Signal("EXTERNAL_BOUNDARY", "system", 3,
           r"((?:对接|集成|打通|同步|接入).{0,10}"
           r"(?:SAP|ERP|WMS|PLM|CRM|OA|外部|第三方|供应商|客户|甲方|对方|银行|税局|海关)"
           r"|(?:外部|第三方|供应商|客户|甲方|对方).{0,6}(?:系统|平台|接口))",
           "跨组织边界 —— 对方系统不归你管，契约不可控、联调要排队"),
    Signal("MIGRATION", "system", 2,
           r"(迁移|存量数据|历史数据|导数据|数据清洗)",
           "数据迁移, 一步错步步错"),
    Signal("PERFORMANCE", "system", 1,
           r"(性能|并发|大数据量|百万级|高可用|压测|响应时间)",
           "有非功能指标要验"),
    Signal("MULTI_END", "system", 1,
           r"(多端|移动端|小程序|App|H5|大屏|微信)",
           "多端交付, 面变大"),
]

# --- 交付严肃度 -------------------------------------------------------------
DELIVERY = [
    Signal("PRODUCTION", "delivery", 2,
           r"(上线|生产环境|正式环境|发布到|投用|启用)",
           "要进生产 —— 门禁不能省"),
    Signal("CUSTOMER", "delivery", 2,
           r"(客户|甲方|招投标|对外交付|交付给|给别人用|外部用户)",
           "对外交付, 结论要对别人可解释"),
    Signal("COMPLIANCE", "delivery", 3,
           r"(合规|审计|等保|监管|药监|GMP|安全审查|留痕)",
           "有合规/审计要求 —— 必须可追溯"),
    Signal("LONGTERM", "delivery", 1,
           r"(长期维护|多人协作|团队|交接|二期|迭代)",
           "长期演进, 文档与契约要留"),
]

ALL_DIMENSIONS = {
    "intent": ("开发/修复意图", DEV_INTENT + FIX),
    "scale": ("项目规模/存量改造", SCALE + LEGACY),
    "business": ("业务复杂度", BUSINESS),
    "uncertainty": ("需求不确定性", UNCERTAINTY),
    "risk": ("变更风险", RISK),
    "system": ("系统复杂度", SYSTEM),
    "delivery": ("交付严肃度", DELIVERY),
}

ALL_SIGNALS = QUICK_VETO + DEV_INTENT + FIX + SCALE + LEGACY + BUSINESS + UNCERTAINTY + RISK + SYSTEM + DELIVERY
QUICK_VETO_IDS = frozenset(s.id for s in QUICK_VETO)

# 单信号即强制 L2: 命中就意味着"这不是一次改动, 是一次重做 / 一次换地基"
FORCE_L2_SINGLE = ("SCALE", "LEGACY")

# 风险标记: 不影响档位, 但必须让人看见
RISK_FLAGS = {
    "BEHAVIOR_CHANGE": "行为变更：影响存量数据与下游报表，必须回归验证 + 评估历史数据",
    "INTEGRATION": "跨系统集成：接口契约必须在建模阶段冻结",
    "EXTERNAL_BOUNDARY": "跨组织边界：对方系统不由你控制，联调排期是外部依赖",
    "MIGRATION": "数据迁移：不可逆操作，需备份与校验",
    "COMPLIANCE": "合规/审计要求：必须留痕，不得事后补",
}

# ===========================================================================
# 结果模型
# ===========================================================================


@dataclass
class Hit:
    id: str
    dim: str
    weight: int
    note: str
    matches: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "dimension": self.dim,
            "weight": self.weight,
            "note": self.note,
            "matches": self.matches,
        }


@dataclass
class Probe:
    """一条对焦问题.

    kind=fact     答案在环境里, 由 agent 去查, 不问人.
    kind=decision 必须问人, 且要带推荐答案, 让"是"就能接受.
    """

    kind: str
    title: str
    body: str
    recommended: str
    blocks: str
    escalates_to: str | None = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "title": self.title,
            "body": self.body,
            "recommended": self.recommended,
            "blocks": self.blocks,
            "escalatesTo": self.escalates_to,
        }


@dataclass
class Route:
    tier: str
    score: int
    decided_by: str
    reason: str
    dimension_scores: dict[str, int]
    hits: list[Hit]
    stages: list[str]
    checkpoints: list[dict]
    gaps: list[str]
    next_action: str
    probes: list[Probe] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    confidence: str = "high"
    profile: str = "generic"
    profile_note: str = ""
    urgent: bool = False
    surfaces: tuple[str, ...] = ()
    execution: str = "precise"      # precise | generic

    @property
    def meta(self) -> dict:
        return TIER_META[self.tier]

    def to_dict(self) -> dict:
        m = self.meta
        return {
            "tier": self.tier,
            "tierName": m["name"],
            "score": self.score,
            "decidedBy": self.decided_by,
            "reason": self.reason,
            "summary": m["summary"],
            "durationEstimate": m["duration"],
            "reviewCount": m["review"],
            "dimensionScores": self.dimension_scores,
            "hits": [h.to_dict() for h in self.hits],
            "stages": self.stages,
            "checkpoints": self.checkpoints,
            "gaps": self.gaps,
            "probeBudget": PROBE_BUDGET[self.tier],
            "probes": [p.to_dict() for p in self.probes],
            "riskFlags": self.risk_flags,
            "confidence": self.confidence,
            "profile": self.profile,
            "profileLabel": PROFILE_LABEL.get(self.profile, self.profile),
            "profileNote": self.profile_note,
            "urgent": self.urgent,
            "surfaces": list(self.surfaces),
            "execution": self.execution,
            "nextAction": self.next_action,
        }


# ===========================================================================
# 判定
# ===========================================================================


def _scan(text: str) -> list[Hit]:
    """返回命中的信号 (每个信号最多一条, 记录所有匹配片段)."""
    hits: list[Hit] = []
    for sig in ALL_SIGNALS:
        found = [m.group(0) for m in re.finditer(sig.pattern, text, re.IGNORECASE)]
        if found:
            # 去重但保序
            seen: list[str] = []
            for item in found:
                if item not in seen:
                    seen.append(item)
            hits.append(Hit(sig.id, sig.dim, sig.weight, sig.note, seen))
    return hits


def _dimension_scores(hits: list[Hit]) -> dict[str, int]:
    scores = {key: 0 for key in ALL_DIMENSIONS}
    for hit in hits:
        if hit.dim in scores:
            scores[hit.dim] += hit.weight
    return scores


def _enterprise_hits(hit_ids: set[str]) -> list[str]:
    """返回命中的企业级信号（任意两个即强制建模档）."""
    return [name for name in ENTERPRISE_SIGNALS if name in hit_ids]


def classify(text: str, precise: bool | None = None) -> Route:
    """核心判定. 纯函数, 无副作用.

    precise: None = 自动探测执行体（装了 gate 就精确，没装就通用）
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("愿望文本为空")

    if precise is None:
        precise = deps.gate_available()

    hits = _scan(text)
    hit_ids = {h.id for h in hits}
    scored = [h for h in hits if h.weight > 0]
    score = sum(h.weight for h in scored)
    dims = _dimension_scores(hits)
    enterprise = _enterprise_hits(hit_ids)
    veto_names = sorted(h.id for h in hits if h.id in QUICK_VETO_IDS)
    profile, profile_note = detect_profile(text)
    urgent = bool(re.search(URGENT_PATTERN, text))
    surfaces = detect_surfaces(text, hit_ids)

    # "前后端" 是一个复合词：ui 面认「前端」、api 面认「后端」，
    # 于是 "前后端都有的系统" 只数到 api，漏了界面。
    # profile 已经判定"前后端都有"，那是比关键词更强的证据——补上两个面。
    if profile == "fullstack":
        surfaces |= {"api", "ui"}

    passthrough = bool(re.search(PASSTHROUGH, text))

    # ---- 分档. 优先级: 单信号强档 > 企业级组合 > 面数 > 分数 > 否决 > 意图 --
    # 两种强信号要分开归因：判错了才知道该改哪一条。
    if "SCALE" in hit_ids:
        tier, decided_by = "L2", "scale"
        reason = "项目级规模 —— 这不是一次改动，是重做"
    elif "LEGACY" in hit_ids:
        tier, decided_by = "L2", "legacy"
        reason = "存量改造 —— 风险在「改坏」，不在「做不出来」"
    elif len(enterprise) >= 2:
        tier, decided_by = "L2", "enterprise"
        reason = "命中两个以上企业级特征：" + " + ".join(enterprise)
    elif len(surfaces) >= SURFACE_MIN_FOR_L2 and not passthrough:
        tier, decided_by = "L2", "surfaces"
        reason = (
            f"牵动 {len(surfaces)} 个交付面（{'/'.join(sorted(surfaces))}）"
            "——必须先冻结契约再并行，这是 L2 的形状"
        )
    elif score > THRESHOLDS["standard_max"]:
        tier, decided_by = "L2", "score"
        reason = f"加权分 {score} > {THRESHOLDS['standard_max']}，复杂度已到建模档"
    elif veto_names:
        tier, decided_by = "L0", "veto"
        reason = "命中不触发交付链的场景：" + "、".join(veto_names)
    elif "DEV" in hit_ids or "FIX" in hit_ids:
        tier, decided_by = "L1", "intent"
        reason = "有明确开发/修复诉求，且无建模级复杂度"
    elif score > THRESHOLDS["quick_max"]:
        tier, decided_by = "L1", "score"
        reason = f"加权分 {score}，有结构性诉求但无建模级复杂度"
    else:
        tier, decided_by = "L0", "score"
        reason = f"加权分 {score} <= {THRESHOLDS['quick_max']}，没有交付物诉求"

    # 工作类型可以抬档位下限: 数据迁移不可逆, 不能当小活干
    if profile == "data" and tier == "L0":
        tier, decided_by = "L1", "profile"
        reason = "数据处理：不可逆操作，至少走 L1（dry-run + 备份 + 确认）"

    gaps = detect_gaps(text, tier, profile)
    probes = build_probes(tier, gaps, text)
    risk_flags = [RISK_FLAGS[name] for name in RISK_FLAGS if name in hit_ids]

    # 信息量不足: 与其硬判, 不如承认判不准.
    #
    # 但只在"结论靠弱信号兜底"时才降置信度（decided_by 是 intent/score）。
    # 命中企业级组合或单信号强档时, 句子再短结论也是硬的 ——
    # 「要和供应商系统对接，每天同步库存」只有 16 个字, 但"对接 + 供应商系统"
    # 是两句就能钉死的事, 说它"判不准"反而是错的。
    confidence = "high"
    if (
        tier != "L0"
        and decided_by in ("intent", "score")
        and profile not in PROFILE_ALWAYS + ("fix",)
        and len(text.strip()) < 20
        and len(gaps) >= 2
    ):
        confidence = "low"
        reason += "；但描述过短、缺口过多，档位仅供参考"

    return Route(
        tier=tier,
        score=score,
        decided_by=decided_by,
        reason=reason,
        dimension_scores=dims,
        hits=scored + [h for h in hits if h.weight == 0],
        stages=stages_for(tier, dims, profile, urgent, precise),
        checkpoints=checkpoints_for(tier),
        gaps=gaps,
        next_action=(
            "描述太短，判不准。先问 2~3 个问题澄清，再定档——别急着开工"
            if confidence == "low"
            else next_action_for(tier, gaps, checkpoints_for(tier))
        ),
        probes=probes,
        risk_flags=risk_flags,
        confidence=confidence,
        profile=profile,
        profile_note=profile_note,
        urgent=urgent,
        surfaces=tuple(sorted(surfaces)),
        execution="precise" if precise else "generic",
    )


# ===========================================================================
# 改口: 答完之后重新判档, 不指望用户自诊断
# ===========================================================================

SIGNAL_BY_ID = {sig.id: sig for sig in ALL_SIGNALS}

# 回答里的否定词. 原文不会因为一句"其实不接 SAP"就消失, 所以这里只标记
# "需要重述", 不替用户猜要删哪一段 —— 猜错比不猜更贵.
NEGATION_PATTERN = r"(不对|其实不|不需要|不用|不接|不做|不搞|取消|去掉|没有|不涉及|不用了)"


@dataclass
class Reroute:
    """一轮对焦之后的档位变化."""

    before_tier: str
    after_tier: str
    direction: str          # upgrade | same | downgrade
    new_signals: list[str]  # 回答里新命中、原文没有的信号
    transition: str         # 流程与成本的变化
    message: str            # 当场改口的那一句
    gaps_before: list[str]
    gaps_after: list[str]
    needs_restatement: bool = False

    def to_dict(self) -> dict:
        return {
            "beforeTier": self.before_tier,
            "afterTier": self.after_tier,
            "direction": self.direction,
            "newSignals": self.new_signals,
            "transition": self.transition,
            "message": self.message,
            "gapsBefore": self.gaps_before,
            "gapsAfter": self.gaps_after,
            "needsRestatement": self.needs_restatement,
        }


TRANSITIONS = {
    ("L0", "L1"): "从『直接做』变成走交付链：多出对焦和门禁，耗时几分钟 → 15~40 分钟",
    ("L0", "L2"): "从『直接做』跳到建模档：耗时几分钟 → 2~6 小时",
    ("L1", "L0"): "退回『直接做』：不建交付物，也不留证据",
    ("L1", "L2"): "多加业务建模段和两道人审，耗时 15~40 分钟 → 2~6 小时",
    ("L2", "L0"): "直接退两档到『直接做』：这件事实在很小",
    ("L2", "L1"): "省掉建模段和两道人审，耗时 2~6 小时 → 15~40 分钟",
}


def _signal_label(signal_id: str) -> str:
    sig = SIGNAL_BY_ID.get(signal_id)
    if not sig:
        return signal_id
    return f"{sig.id}(+{sig.weight})：{sig.note}"


def reroute(original: str, answers: str, precise: bool | None = None) -> tuple[Reroute, Route]:
    """把用户的对焦回答拼回原文, 重新判档.

    票数归因: 只承认「回答里出现、原文没有」的信号 —— 否则等于把原来的判断
    重复算一遍, 用户看不出是哪句话改的档.
    """
    before = classify(original, precise)
    after = classify(original + "\n" + answers, precise)

    answer_ids = {hit.id for hit in _scan(answers) if hit.weight > 0}
    before_ids = {hit.id for hit in before.hits}
    new_signals = sorted(answer_ids - before_ids)

    i_before = TIERS.index(before.tier)
    i_after = TIERS.index(after.tier)
    if i_after > i_before:
        direction = "upgrade"
    elif i_after < i_before:
        direction = "downgrade"
    else:
        direction = "same"

    transition = TRANSITIONS.get((before.tier, after.tier), "")
    cause = "、".join(_signal_label(s) for s in new_signals) or "（无新增信号）"
    negated = bool(re.search(NEGATION_PATTERN, answers))

    if direction == "upgrade":
        message = (
            f"你这几句把这件事从 {before.tier} 推到 {after.tier}——因为 {cause}。"
            f"\n{transition}。\n已按 {after.tier} 重排，不需要你判断；"
            f"如果这不对，说一句就退回。"
        )
    elif direction == "downgrade":
        message = (
            f"按你说的，这件事从 {before.tier} 降回 {after.tier}——因为 {cause or '需求变小了'}。"
            f"\n{transition}。"
        )
    else:
        message = f"档位不变，仍是 {before.tier}，可以开始。"

    if negated and direction != "upgrade":
        message += (
            "\n\n⚠️ 你的回答里出现了否定的说法，但我不会替你猜要删掉原文的哪一段——"
            "如果需求确实缩水了（比如『其实不接 SAP』），请直接重述整条愿望，我再重判。"
        )

    return (
        Reroute(
            before_tier=before.tier,
            after_tier=after.tier,
            direction=direction,
            new_signals=new_signals,
            transition=transition,
            message=message,
            gaps_before=before.gaps,
            gaps_after=after.gaps,
            needs_restatement=negated and direction != "upgrade",
        ),
        after,
    )


# ===========================================================================
# 缺口检测 / 流程 / 人审点
# ===========================================================================

GAP_PATTERNS = [
    ("who", "谁用 / 什么角色在什么场景下用",
     r"(用户|客户|员工|操作员|管理员|班组长|调度员|业务员|财务|仓库|谁|角色|岗位)"),
    ("what", "要做什么 / 核心动作或产出是什么",
     r"(做|实现|支持|能|功能|管理|录入|查询|统计|生成|导出|导入|审批|流转|展示|对比|"
     r"改|调整|修正|计算|校验|增加|新增|添加|修复)"),
    ("done", "怎么算完成 / 验收标准是什么",
     r"(验收|标准|通过|达标|满足|准确率|性能|响应|测试|覆盖|能跑|交付)"),
    ("boundary", "边界在哪 / 明确不做什么",
     r"(不做|不包括|除…?外|仅|只|范围|一期|首期|MVP|最小)"),
]


def detect_gaps(text: str, tier: str, profile: str = "generic") -> list[str]:
    """返回缺失的必要素说明.

    L0 不查（它本来就不产出交付物）。
    fix / ops / data 只查"做什么"—— 修 bug 不需要回答"谁用"和"验收标准",
    那是新增功能的问法。用同一套缺口去问不同形状的活, 只会让人烦。
    """
    if tier == "L0":
        return []
    if profile in PROFILE_ALWAYS + ("fix",):
        required = ["what"]
    else:
        required = ["who", "what", "done"]
    gaps: list[str] = []
    for key, label, pattern in GAP_PATTERNS:
        if key not in required:
            continue
        if not re.search(pattern, text):
            gaps.append(label)

    # 验收标准: 出现过"上线/交付/客户"却没有任何可判定指标 -> 记一条软缺口
    if tier != "L0" and not gaps:
        if re.search(r"(上线|交付|客户|生产)", text) and not re.search(
            r"(验收|标准|通过|达标|准确率|性能|响应时间|测试|覆盖)", text
        ):
            gaps.append("可判定的验收指标（说了要上线，但没说怎么算达标）")
    return gaps


PROFILE_LABEL = {
    "ops": "运维操作",
    "data": "数据处理",
    "fix": "缺陷修复",
    "integration": "系统对接",
    "refactor": "存量改造",
    "report": "报表",
    "frontend": "前端",
    "backend": "后端",
    "fullstack": "全栈",
    "generic": "通用",
}


def detect_profile(text: str) -> tuple[str, str]:
    """按优先级取第一个命中的工作类型.

    顺序有意为之: 路径形状由"部署/数据/修复"决定, 而不是由"前端后端"决定。
    所以「前端页面的 bug」是 fix, 不是 frontend —— 修 bug 的步骤和写页面不一样。
    """
    for name, pattern, note in PROFILE_RULES:
        if re.search(pattern, text, re.IGNORECASE):
            return name, note
    return "generic", "未识别出具体类型 —— 按通用链走"


# --- 两种执行体：精确版（vendor 里有 agent-delivery-gate）和通用版 -----------
# 精确版的命令路径由 deps.cmd_prefix() 现算：随包的 vendor 给相对路径，
# 外部源仓库给绝对路径 —— 两种都能直接粘进终端。
GENERIC_HEAD = [
    "环境准备：按 tech.md 核对工具链版本（缺的自己装，不要换栈）",
    "对焦：产出 contract.md（AC 清单 + 栈 + 边界 + 档位）",
]
GENERIC_TAIL = [
    "冒烟：能启动、主流程能走通",
    "质量门禁：单测 + 集成 + 代码评审（按契约里的阈值）",
    "交付验收：逐条过 contract.md 的 AC，每条都要有证据",
    "发现这活不该做 → 报 dropped + 理由码 + 确认人（不要报「完成」，也不要报「卡住」）",
]
GENERIC_L2 = [
    "调研整理：流程 / 角色 / 状态 / 规则 / 异常路径",
    "【人审】业务确认：流程与角色对不对",
    "领域模型：实体、状态机、业务规则、待确认问题清单",
    "【人审】模型确认：BPMN / 本体 / 需求图对不对",
    "输入基线：把确认过的模型冻结成基线，后续改动必须走变更流程",
]


def precise_head() -> list[str]:
    p = deps.cmd_prefix()
    return [
        f"SP-01 环境预检（python {p}scripts/preflight_env_check.py）",
        "对焦：产出 contract.md（AC 清单 + 栈 + 边界 + 档位）",
    ]


def precise_tail() -> list[str]:
    p = deps.cmd_prefix()
    return [
        "SP-12 Smoke 前置门禁",
        "SP-13 质量门禁（覆盖率 / 单测 / 集成 / 代码评审）",
        f"SP-18 终检：python {p}scripts/validate_delivery.py",
        "发现这活不该做 → 报 dropped + 理由码 + 确认人（不要报「完成」，也不要报「卡住」）",
    ]


def precise_l2() -> list[str]:
    """L2 的建模段。r2pi 在 vendor 里就用它，否则降级。"""
    root = deps.find_related("r2pi", deps.R2PI_MARKER)
    if root is None:
        return GENERIC_L2
    try:
        rel = root.relative_to(deps.SKILL_ROOT).as_posix()
    except ValueError:
        rel = root.as_posix()
    gate_p = deps.cmd_prefix()
    return [
        f"research-to-project-input: python {rel}/scripts/pipeline_runner.py init → register-research",
        f"run-stage（建模脚手架 → 规格 → 需求图 → SHACL/OWL-RL/SPARQL → BPMN/OWL，在 {rel}/）",
        "【人审】approve --gate modeling",
        "【人审】approve --gate models",
        f"gate: python {gate_p}scripts/validate_input_contract.py（C-INPUT-01..04 防失真）",
    ]



def stages_for(
    tier: str,
    dims: dict[str, int],
    profile: str,
    urgent: bool,
    precise: bool = True,
) -> list[str]:
    """precise=True 输出具体节点编号与命令（需要 gate 在场）；
    precise=False 输出通用阶段（谁都能照着做）。"""
    if profile == "ops":
        return URGENT_STAGES[:1] + PROFILE_STAGES["ops"] if urgent else PROFILE_STAGES["ops"]
    if profile == "data":
        return URGENT_STAGES + PROFILE_STAGES["data"] if urgent else PROFILE_STAGES["data"]
    if tier == "L0" and not urgent:
        return ["直接回答 / 直接改，不进交付链"]
    if tier == "L0" and urgent:
        return URGENT_STAGES

    stages: list[str] = []
    if urgent:
        stages += URGENT_STAGES

    # 存量改造的 L2 走自己的深度：影响面 + 兼容 + 灰度。
    # 它**不套业务建模段** —— 把 JSP 换成 Vue 不需要画 BPMN 业务流程图。
    if tier == "L2" and profile != "refactor":
        stages += precise_l2() if precise else GENERIC_L2

    body = profile_stages(profile, precise)

    if profile == "refactor":
        # 读现状必须在问问题之前：先看清楚项目长什么样，再决定问什么。
        head = precise_head()[0] if precise else GENERIC_HEAD[0]     # 环境预检
        stages.append(head)
        stages += refactor_read_now(precise)
        stages.append(
            "对焦：基于读到的现状产出 contract.md（AC + 边界 + 「不许动」清单）"
        )
        stages += REFACTOR_AFTER_FOCUS
        stages += precise_tail() if precise else GENERIC_TAIL
        return stages

    stages += precise_head() if precise else GENERIC_HEAD
    stages += body
    stages += precise_tail() if precise else GENERIC_TAIL
    return stages


def profile_stages(profile: str, precise: bool) -> list[str]:
    """按工作类型给形状。

    `refactor` 在 stages_for 里单独排列（读现状在对焦之前），走不到这里；
    这里只是兜底，保证任何调用方都能拿到一份完整形状。
    """
    return [
        _localize(item, precise)
        for item in PROFILE_STAGES.get(profile, PROFILE_STAGES["generic"])
    ]


def _localize(stage: str, precise: bool) -> str:
    """profile 形状里夹带的精确编号，在通用模式下换成描述."""
    if precise:
        return stage
    replacements = {
        "接口契约冻结（SP-06）": "接口契约冻结",
        "SP-06 接口契约": "接口契约",
        "（SP-06）": "",
    }
    for old, new in replacements.items():
        stage = stage.replace(old, new)
    return stage


def checkpoints_for(tier: str) -> list[dict]:
    if tier == "L0":
        return []
    base = [
        {
            "id": "focus",
            "after": "对焦",
            "duration": "3~5 分钟",
            "reviewer": "提需求的人",
            "looks_at": "contract.md：AC 条目、技术栈、边界、档位",
            "blocks": "没点确认不派角色",
        },
        {
            "id": "fake",
            "after": "假交付物",
            "duration": "10~20 分钟做 + 2 分钟看",
            "reviewer": "提需求的人",
            "looks_at": "静态图 / 假 JSON：**是不是这个**（不是让你审文档）",
            "blocks": "没点头不改真代码",
        },
    ]
    if tier != "L2":
        return base
    return base + [
        {
            "id": "modeling",
            "after": "建模",
            "duration": "20~60 分钟",
            "reviewer": "懂业务的人（必须能看业务流程）",
            "looks_at": "models/review/00-05：流程、角色、状态、规则、待确认问题",
            "blocks": "不批准则一份 docs/input 都不生成",
        },
        {
            "id": "models",
            "after": "模型生成",
            "duration": "30~90 分钟",
            "reviewer": "懂业务 + 能看 BPMN/OWL 的人",
            "looks_at": "需求图 / BPMN / OWL / 06-模型审核记录",
            "blocks": "不批准不许进 PRD",
        },
    ]


def _hit(text: str, signal_id: str) -> bool:
    sig = SIGNAL_BY_ID.get(signal_id)
    return bool(sig and re.search(sig.pattern, text, re.IGNORECASE))


def build_probes(tier: str, gaps: list[str], text: str) -> list[Probe]:
    """按档位生成对焦清单.

    顺序有意为之: 先 fact(自己去查), 再 decision(问人). 能查的东西问人 = 失礼.
    每个 decision 都带 recommended, 让用户答"是"即可.
    """
    if tier == "L0":
        return []

    probes: list[Probe] = []

    # --- fact: 答案在环境里, 派 agent 去查, 不许问人 -----------------------
    probes.append(Probe(
        kind="fact",
        title="技术栈基线",
        body="读 assets/tech.md 与项目现有依赖，确认本次用的语言/框架/数据库版本。"
             "（这一条不问你——除非 tech.md 里没有覆盖）",
        recommended="沿用 tech.md 基线；若项目已有其他栈，以项目现实为准并记录偏离",
        blocks="选型和脚手架生成",
    ))
    if re.search(r"(改造|重构|优化|升级|迁移|存量|现有)", text):
        probes.append(Probe(
            kind="fact",
            title="现有实现现状",
            body="派 subagent 读相关模块与调用链，列出这次会碰到的文件、入口和既有约定。"
                 "（这一条不问你）",
            recommended="先出影响面清单，再动第一行代码",
            blocks="改造范围界定",
        ))

    # --- decision: 必须问人, 每条带推荐答案 -------------------------------
    gap_map = {
        "谁用": Probe(
            kind="decision",
            title="谁在用",
            body="这个功能真正的使用者是谁？给一个角色名即可（例如：仓库管理员、班组长、财务）。",
            recommended="按你描述里最可能的角色，选一个写成 AC 的『角色』字段",
            blocks="AC 的『作为谁』",
        ),
        "怎么算完成": Probe(
            kind="decision",
            title="怎么算做完了",
            body="用一句话说清验收：什么情况下你会说『这个对了』？"
                 "（例如：录入后能在列表查到、金额与手工核算一致、页面 2 秒内打开）",
            recommended="先给一条可判定的句子，写进 contract.md 的 AC-01；其余留到跑的过程中补",
            blocks="整个验收链",
            escalates_to="L2",
        ),
        "边界": Probe(
            kind="decision",
            title="明确不做什么",
            body="这次明确不做哪些？（这是防止范围蔓延最便宜的一招）",
            recommended="列出 1~3 条『本期不做』，写进 contract.md 的『不做什么』",
            blocks="范围冻结",
        ),
    }

    for gap in gaps:
        for key, probe in gap_map.items():
            if key in gap:
                probes.append(probe)
                break

    # 兜底: 缺口没被模板覆盖时给一条通用问法
    known = {"谁用", "怎么算完成", "边界"}
    for gap in gaps:
        if not any(key in gap for key in known):
            probes.append(Probe(
                kind="decision",
                title=gap,
                body=f"请补充：{gap}",
                recommended="给出你最直觉的答案，后面跑的过程中还能改",
                blocks="对焦完成",
            ))

    # --- 变更类必答项: 口径改了, 存量数据怎么办 ---------------------------
    if _hit(text, "BEHAVIOR_CHANGE"):
        probes.append(Probe(
            kind="decision",
            title="历史数据怎么处理",
            body="口径/算法变了，存量数据要按新规则重算吗？重算的话，历史报表会变，"
                 "看过旧数字的人会以为出错了。",
            recommended="默认【不重算，只对新数据生效】；若要历史可比，选【双口径并存】"
                        "（老报表冻结在旧口径，新报表用新口径）",
            blocks="下游报表与对账口径",
            escalates_to="L2",
        ))

    # --- 跨组织边界: 对方的接口不是你能定的 -------------------------------
    if _hit(text, "EXTERNAL_BOUNDARY"):
        probes.append(Probe(
            kind="fact",
            title="对方接口文档",
            body="先要对方的接口文档 / 字段表 / 同步频率 / 失败重试约定。"
                 "（这一条先自己找，找不到再问人）",
            recommended="没有文档就先做一份对接清单，让对方签字确认，再写代码",
            blocks="契约冻结（对方不确认，代码写完也要返工）",
        ))
        probes.append(Probe(
            kind="decision",
            title="联调谁配合",
            body="对方系统的联调窗口和负责人是谁？对方改字段提前多久通知你？",
            recommended="默认按【对方不配合、需要自己造 mock 环境】设计，联调排期写进计划",
            blocks="上线时间",
            escalates_to="L2",
        ))

    # --- 不要求用户自诊断: 如实回答即可, 答完系统重判 ----------------------
    if tier == "L1":
        probes.append(Probe(
            kind="escalation",
            title="不用管档位",
            body="如实回答就行，不用自己判断这是不是 L2。"
                 "回答里如果出现多部门协作 / 对接外部系统 / 审批或状态流转 / "
                 "合规审计 / 存量迁移，答完系统会自动重排档位并告诉你为什么。",
            recommended="按实际情况说，不用替系统分档",
            blocks="—",
            escalates_to="L2",
        ))

    return probes


def next_action_for(tier: str, gaps: list[str], checkpoints: list[dict]) -> str:
    if tier == "L0":
        return "直接作答，不建交付物；若后续发现要交付，再升级档位"
    if gaps:
        return "先补缺口（" + "；".join(gaps) + "），再锁定 AC 契约"
    if tier == "L2":
        return "注册调研材料并开跑建模；跑到第一道人审就停下等人"
    return "产出 contract.md 并请人确认；确认后派 product-analyst"


# ===========================================================================
# 渲染
# ===========================================================================


def render_markdown(route: Route, text: str, explain: bool = False) -> str:
    m = route.meta
    lines: list[str] = []
    lines.append(f"# 档位判定：{route.tier} {m['name']}")
    lines.append("")
    lines.append(f"- **判定依据**：{route.reason}（decided_by={route.decided_by}，score={route.score}）")
    lines.append(
        f"- **工作类型**：{PROFILE_LABEL.get(route.profile, route.profile)}"
        f"（{route.profile_note}）"
        + ("　**🔴 紧急**" if route.urgent else "")
    )
    if route.execution == "generic":
        lines.append("- **执行体**：通用版（未检测到 `agent-delivery-gate`，"
                     "清单给的是阶段名而非具体节点；装上它会更精确）")
    lines.append(f"- **预计耗时**：{m['duration']}　**人审点**：{m['review']} 个"
                 + ("　置信度：低（仅供参考）" if route.confidence == "low" else ""))
    lines.append(f"- **流程**：{m['pipeline']}")
    lines.append("")

    lines.append("## 分维度得分")
    lines.append("")
    lines.append("| 维度 | 得分 | 命中信号 |")
    lines.append("| --- | --- | --- |")
    for key, (label, _) in ALL_DIMENSIONS.items():
        got = route.dimension_scores.get(key, 0)
        names = [h.id for h in route.hits if h.dim == key and h.weight > 0]
        lines.append(f"| {label} | {got} | {', '.join(names) or '—'} |")
    lines.append("")

    if route.hits:
        lines.append("## 命中的判据")
        lines.append("")
        for hit in route.hits:
            tag = "（否决）" if hit.weight == 0 else f"+{hit.weight}"
            frag = " / ".join(hit.matches[:4])
            lines.append(f"- `{hit.id}` {tag} — {hit.note}　命中：{frag}")
        lines.append("")

    lines.append("## 要跑的 stage")
    lines.append("")
    for i, stage in enumerate(route.stages, 1):
        lines.append(f"{i}. {stage}")
    lines.append("")

    if route.checkpoints:
        lines.append("## 人审点（必须真人确认，AI 不能代签）")
        lines.append("")
        lines.append("| # | 位置 | 看什么 | 谁看 | 耗时 | 卡住什么 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for i, cp in enumerate(route.checkpoints, 1):
            lines.append(
                f"| {i} | {cp['after']} | {cp['looks_at']} | {cp['reviewer']} | {cp['duration']} | {cp['blocks']} |"
            )
        lines.append("")

    if route.gaps:
        lines.append("## 还缺什么")
        lines.append("")
        for gap in route.gaps:
            lines.append(f"- {gap}")
        lines.append("")

    if route.probes:
        budget = PROBE_BUDGET[route.tier]
        facts = [p for p in route.probes if p.kind == "fact"]
        decisions = [p for p in route.probes if p.kind == "decision"]
        escalation = [p for p in route.probes if p.kind == "escalation"]

        lines.append(f"## 对焦清单（提问预算 {budget if budget < 999 else '不限'} 次）")
        lines.append("")
        if facts:
            lines.append("### 自己去查（不问人）")
            lines.append("")
            for p in facts:
                lines.append(f"- **{p.title}** —— {p.body}")
            lines.append("")
        if decisions:
            lines.append("### 要问人（答『是』即接受推荐）")
            lines.append("")
            for i, p in enumerate(decisions, 1):
                lines.append(f"❓ **Q{i} {p.title}** —— {p.body}")
                lines.append("")
                lines.append(f"➡️ 推荐：{p.recommended}")
                lines.append("")
        if escalation:
            lines.append("### " + escalation[0].title)
            lines.append("")
            lines.append(escalation[0].body)
            lines.append("")

    lines.append("## 下一步")
    lines.append("")
    lines.append(route.next_action)
    lines.append("")

    if explain:
        lines.append("---")
        lines.append("")
        lines.append("### 原始文本")
        lines.append("")
        lines.append("```text")
        lines.append(textwrap.fill(text, 100))
        lines.append("```")

    return "\n".join(lines)


def render_selftest() -> str:
    cases = [
        ("这个函数是什么意思", "L0", "纯答疑"),
        ("帮我改个 typo", "L0", "单点微调"),
        ("实现一个用户登录接口", "L1", "单模块开发"),
        ("班组长的工序报工加上按钮权限", "L1", "有角色但无流程建模量"),
        ("做一个车间工单管理系统，要有审批流和多角色权限", "L2", "流程 + 多角色"),
        ("给客户做一套 MES，对接 SAP 和 WMS，要通过等保", "L2", "集成 + 合规"),
    ]
    rows = ["| 愿望 | 判定 | 期望 | 结果 | 依据 |", "| --- | --- | --- | --- | --- |"]
    ok = True
    for text, expected, why in cases:
        route = classify(text)
        good = route.tier == expected
        ok = ok and good
        rows.append(
            f"| {text} | {route.tier} | {expected} | {'PASS' if good else 'FAIL'} | {route.decided_by} / {route.reason if not good else why} |"
        )
    rows.append("")
    rows.append(f"**结果：{'全部通过' if ok else '有失败项'}**")
    return "\n".join(rows)


# ===========================================================================
# CLI
# ===========================================================================


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(
        description="档位路由器：判定一个愿望该走 L0/L1/L2 哪一档交付流程",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("wish", nargs="?", help="愿望文本")
    parser.add_argument("--file", help="从文件读取愿望文本")
    parser.add_argument("--answers", help="对焦回答（文本, 或一个存在的文件路径）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--explain", action="store_true", help="报告附带原始文本")
    parser.add_argument("--selftest", action="store_true", help="跑内置用例")
    parser.add_argument("--no-gate", action="store_true",
                        help="强制通用版（假定没装 agent-delivery-gate）")
    parser.add_argument("--gate", action="store_true",
                        help="强制精确版（假定装了 agent-delivery-gate）")
    args = parser.parse_args(argv)

    precise = None
    if args.no_gate:
        precise = False
    elif args.gate:
        precise = True

    if args.selftest:
        print(render_selftest())
        return 0

    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    elif args.wish:
        text = args.wish
    else:
        parser.error("需要一个愿望文本，或用 --file 指定文件")

    try:
        if args.answers:
            answers_path = Path(args.answers)
            answers = (
                answers_path.read_text(encoding="utf-8")
                if answers_path.is_file()
                else args.answers
            )
            change, route = reroute(text, answers, precise)
            if args.json:
                print(json.dumps(
                    {"reroute": change.to_dict(), "route": route.to_dict()},
                    ensure_ascii=False,
                    indent=2,
                ))
            else:
                print("## 档位改口\n")
                print(change.message)
                print()
                if change.gaps_after:
                    print("**还缺**：" + "；".join(change.gaps_after))
                    print()
                print("---\n")
                print(render_markdown(route, text + "\n\n[对焦回答]\n" + answers, explain=args.explain))
            return 0

        route = classify(text, precise)
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(route.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(render_markdown(route, text, explain=args.explain))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
