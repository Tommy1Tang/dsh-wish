# Technical Architecture & Coding Guidelines (技术架构与开发规范)

> **[System Note for AI]**
> 1. When generating, refactoring, or reviewing code, you MUST strictly read and follow the technology stack and rules defined in this document. 
> 2. If a user's request conflicts with these guidelines, prioritize these guidelines, warn the user, and provide compliant code. Do not use outdated libraries.
> 3. **Never output partial code with `// ... existing code ...`** unless the file is huge. Provide complete, runnable code. Keep your explanations concise.
> 4. 🔴 **本地开发机环境不支持本文档技术栈时，不得更换技术栈。** 缺少 Node.js 22 / Python 3.12 / Git 2+ 等工具链时，唯一合法路径是按 `references/environment-provisioning.md` **自动安装开发环境**（Windows 首选 `winget`，版本必须按该文档钉死；全新系统 Python 不可用时先执行 `scripts/bootstrap_env.ps1` 引导），安装无需用户确认；安装不可行时挂起（`halted-pending-user`）问用户，换栈只能由用户明确授权。「环境不支持」永远不是换栈或降级交付的理由。
> 5. 🔴 **本栈不引入 PostgreSQL、Redis、Java/JDK、Maven。** 持久化用 SQLite（世界级单文件库）、向量检索用 ChromaDB，二者均本地进程内使用，不存在需要直连的部署服务器依赖。`scripts/preflight_env_check.py` 对 JDK / Maven / 远程 PostgreSQL / 远程 Redis 的检查必须以本文件声明的栈为准进行裁剪，不得对本项目报出这些工具链缺失（那是 Java 栈的基线，不是本项目的基线）。

---

## 1. 技术栈选型 (Technology Stack)

> **[Instruction for User]** 以下是本项目技术栈清单。基线来源：`需求文档.md` 技术栈章节，以及 `docs/input/06-调研台账摘要.md` 的 EV-DOC-005 / EV-DOC-006 / EV-SUP-005。变更需走 `references/change-management-workflow.md`。

### 1.1 前端 (Frontend)
- **核心框架**: React 19
- **开发语言**: TypeScript (Strict Mode)
- **UI 库 & 样式**: Ant Design 6 + Tailwind CSS 4
- **状态管理**: Zustand
- **构建工具**: Vite 8
- **实时通道**: 浏览器原生 `EventSource`（消费后端 SSE 事件流）

### 1.2 后端 (Backend)
- **开发语言**: Python 3.12
- **Web 框架**: FastAPI
- **数据校验 / 契约**: Pydantic（请求与响应模型；接口文档由 FastAPI 自动生成的 OpenAPI 承载，见 Q-API-001）
- **持久层**: SQLAlchemy ORM + SQLite
- **向量存储**: ChromaDB（三层记忆的语义检索）
- **LLM 引擎**: DeepSeek v4（默认引擎，经 `IF-LLM` 出站调用）
- **流式推送**: SSE（`IF-SSE`）

### 1.3 数据与基础设施 (Data & Infrastructure)
- **关系型数据库**: SQLite（世界级库文件 `worlds/{world_id}/world.db`）
- **向量索引**: ChromaDB（`worlds/{world_id}/vectors`、全局 `chroma`）
- **应用配置**: `settings.json`；世界清单 `main.db`
- **API 规范**: RESTful API + JSON；流式事件走 SSE
- **部署形态**: 单用户自用，挂公网但不对外提供（无账号体系、无多用户隔离）

---

## 2. 核心共识 (The Golden Rules)

无论使用何种语言，所有代码必须遵循以下基本原则：

1. **命名即注释 (Naming is Documenting)**：拒绝 `a`, `temp`, `data` 等无意义命名。变量和方法名必须准确表达其业务含义。
2. **单一职责 (Single Responsibility)**：一个函数/组件只做一件事。函数超过 50 行（前端组件逻辑超过 100 行）必须评估拆分。
3. **尽早返回 (Early Return)**：拒绝深层嵌套的 `if-else`。优先校验错误和边界条件，不满足则立即 `return` 或抛出异常。
4. **消除魔法值 (No Magic Numbers)**：严禁出现未解释的硬编码数字或状态字符串，必须提取为常量或枚举。**数值系统尤其如此**：好感度系数、衰减半衰期、Token 预算比例、成功率斜率等一律从配置读取，不得内联（多数已在 `docs/input/07-待确认问题.md` 标注为「保留为配置项」）。
5. **防御性编程 (Defensive Programming)**：永远不要信任外部输入。LLM 输出、故事包内容、玩家输入都必须校验后再进入业务逻辑。
6. **完善日志记录 (Logging)**：关键业务流转、异常捕获处必须打印日志（包含上下文参数），严禁生吞异常。

---

## 3. 后端开发规范 (Backend Guidelines)

### 3.1 架构与隔离 (Architecture & DTO)

- **RESTful 规范**: URI 强制使用全小写、名词复数、中划线分隔（如 `/api/v1/user-profiles`），禁止在路径中使用动词。
- **严格数据映射**: 严禁将 SQLAlchemy ORM 实体直接返回给前端。必须定义独立的 Pydantic 响应模型（`*Response`），与请求模型（`*Request`）分开。
- **架构分层**: 严格遵守 `Router` → `Service` → `Repository/DAO` 单向调用，严禁跨层（如 Router 直接查库）。对应 `docs/input/05-流程模型.md` 的职责划分，业务编排放 Service，图/记忆/约束等机制各自独立成模块。
- **引擎与内容分离**: 🔴 引擎代码不得内置任何具体故事的角色、场景、阶段名称与阈值、关系类型或写作模板正文（见 `docs/input/00-项目概述.md` 非功能约束 EV-BND-001）。这些一律来自故事包（`docs/story-package-contract.md`）。新增硬编码的故事内容即视为缺陷。

### 3.2 Python 特定规范

- **类型标注**: 所有函数签名必须有完整类型标注，禁止裸 `Any` 逃逸；复杂结构用 `dataclass` 或 Pydantic 模型表达。
- **异步边界**: FastAPI 路由与 LLM/SSE 调用使用 `async def`；CPU 密集与阻塞 IO（如 SQLite 同步驱动、ChromaDB 调用）不得阻塞事件循环，必要时走线程池。
- **依赖注入**: 使用 FastAPI `Depends` 注入会话、配置与服务，禁止模块级全局可变状态。
- **异常与返回**: 业务错误抛出自定义 `BusinessException`；错误响应统一为同一结构（见 Q-API-001）。返回集合的方法必须返回空列表，严禁返回 `None`。
- **事务管理**: 写操作必须在显式事务内提交；写失败时回滚本回合事务并保留事件日志以便重放（对应 `IF-PERSIST` 的失败处理）。
- **虚拟环境**: 统一使用 `py -3.12 -m venv .venv`；依赖固定版本写入 `requirements.txt` 或 `pyproject.toml`。

### 3.3 状态写入与一致性（本项目特有硬约束）

- 🔴 **LLM 不得直接改写状态**: LLM 只能输出结构化状态变更提案，经约束引擎与推理机校验通过后才写入存档（EV-BND-006、`CAP-PROPOSAL-VALIDATE`）。
- 🔴 **数值精度**: 好感度内部计算保留一位小数，落库与展示取整（Q-AFF-003）；`-100~100` 区间截断必须先于持久化。
- 🔴 **双向一致性校验**: 叙事声明与状态变更提案必须双向比对，任一方向不一致按硬驳回处理（`CAP-CONSISTENCY`）。
- 🔴 **内容分级不泄漏**: 非分级内容不得进入受限分级世界的提示词；受限内容不得落库到全年龄世界（`CAP-BOUNDARY-FILTER`，成功度量指标之一）。
- 🔴 **可还原性**: 随机种子必须入档，读档重放为确定性过程，禁止用反复读档刷新检定或战斗结果（Q-SAVE-002）。

### 3.4 安全规范 (Security)

- **防 SQL 注入**: 强制使用 SQLAlchemy 参数化查询，**严禁**手动拼接 SQL 字符串。
- **密钥管理**: LLM API Key 等凭据一律走环境变量或本地 `settings.json`，**严禁**硬编码进代码或提交进仓库。
- **公网暴露**: 本系统挂公网但为单用户自用；任何新增对外端口或放宽暴露面的改动属 `ASK_USER_TRIGGERS` 场景，必须先问用户。

---

## 4. 前端开发规范 (Frontend Guidelines)

### 4.1 TypeScript 与强类型

- **严禁 Any 滥用**：应使用 `unknown` 替代，或定义具体的 `interface` / `type`。
- **接口命名**：不要使用 `I` 作为前缀（拒绝 `IUser`），直接命名为 `User` 或 `UserProps`。
- **后端契约对齐**：前端类型应与 FastAPI 生成的 OpenAPI schema 保持一致，禁止手写与后端漂移的重复类型。

### 4.2 组件化与解耦

- **组件命名**：文件和组件名称强制使用 `PascalCase`（如 `UserProfile.tsx`）。
- **逻辑抽离**：非视图逻辑（如复杂纯计算、SSE 重连状态机）必须抽离为独立 hooks（`use*`）或纯函数模块。
- **API 层抽离**：严禁在视图组件中直接写 `fetch` / `axios`，所有 API 必须统一在 `src/api/` 下封装并导出。
- **状态管理**：跨组件共享状态放 Zustand store；组件本地 UI 状态用 `useState`，禁止把本地状态提升到全局 store。
- **样式隔离**：优先 Tailwind 原子类；需要复用样式时抽为组件，禁止写全局污染的 CSS。

### 4.3 移动端 Web（必做，非可选）

- 🔴 手机浏览器是目标场景之一，必须自适应：主屏只保留叙事展示与输入区，角色面板、背包、任务追踪、关系网络等收进侧边抽屉按需展开（Q-MOB-005）。
- 🔴 必须在现有栈内完成，**不得引入第二套前端工程**（EV-SUP-005）。
- 🔴 SSE 断连是移动端必然事件（切后台 / 切网络 / 锁屏），必须实现断连挂起与按事件序号重连增量补发；只补发已完成回合结果，不补发中间生成过程（Q-MOB-003、`CAP-MOBILE-RESILIENCE`）。
- 性能指标：移动网络下首屏 3 秒内出界面，单轮生成 10 秒内出首字（流式返回）；超出记录时延埋点告警，不做硬性阻断（Q-MOB-002）。

---

## 5. 数据库与 SQL 规范 (Database & SQL)

### 5.1 DDL 建表规范

- **命名**: 表名和列名强制 `snake_case`（全小写下划线），不使用 SQLite 保留字。
- **主键**: 每张表必须有且仅有一个名为 `id` 的主键（INTEGER 主键或 UUID 文本）。
- **强制审计字段**：
  - `created_at` (TIMESTAMP), `updated_at` (TIMESTAMP)
  - `created_by` (TEXT), `updated_by` (TEXT)
  - `is_deleted` (INTEGER, 0=未删除, 1=已删除，**强制软删除**)
- **索引策略**: `WHERE`、`ORDER BY` 及 `JOIN` 关联字段必须建索引。存在软删除时，业务唯一键需与 `is_deleted` 建立联合唯一索引（SQLite 支持部分索引 `WHERE is_deleted = 0`）。
- **注释**: SQLite 无原生列注释；表与字段的业务含义必须写入 `docs/05-数据设计说明书.md`，并在模型类中以 docstring 复述。
- **时间与数值**: 世界时间等业务时间戳与系统时间分开存列，不得混用。

### 5.2 DML 查询规范

- **禁止 SELECT \***：明确写出需要查询的字段名。
- **业务逻辑前置**：禁止使用存储过程、触发器或外键级联。所有数据完整性校验在应用层实现。
- **事件溯源**: 事件日志按 `docs/input/07-待确认问题.md` Q-SAVE-001 约定保留最近 200 条用于回看与增量补发，更早的按需归档，不随存档膨胀。
- **迁移**: SQLite 结构变更必须提供可回滚脚本，并用 `scripts/migration_safety_check.py` 校验。

---

## 6. Git 工程化工作流 (Git Workflow)

> **[Note for AI]** When generating commit messages, strictly follow this Angular convention: `<type>(<scope>): <subject>`

- `feat`: 新增功能 (Feature)
- `fix`: 修复 Bug
- `docs`: 仅文档修改
- `style`: 代码格式调整（空格、格式化，不影响逻辑）
- `refactor`: 重构代码（不新增功能也不修复 bug）
- `perf`: 性能优化
- `test`: 新增或修改测试用例
- `ci`: CI/CD 配置变动
- `chore`: 构建过程或辅助工具变动

**稳定 ID 回链（本项目强制）**：提交信息与代码模块头必须回链上游稳定 ID，便于 `scripts/trace_requirements.py` 校验：

| 交付物 | 必须携带 |
|--------|---------|
| 代码（模块头或关键函数注释） | `capability_id`、相关 `entity_id` / `rule_id` |
| 测试用例 | `capability_id`、`node_id`、`rule_id` |
| 提交信息 scope | 相关 `capability_id`（如 `feat(CAP-MEMORY): 事实层半衰期衰减`） |
