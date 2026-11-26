# FutureWork 工程目录设计

状态：目标架构与当前可运行版本。开发分支已接通用户目录配置、SQLite 消息和任务、多平台模型网关、小未分派、Agent 私聊、两种群聊模式、显式启用的 Skill 文本加载、分层记忆检索、长上下文压缩、通用工具、媒体能力、声明式 Workflow 和本机 MCP stdio 客户端。浏览器自动化、BKN、LSP 仍属于后续阶段。

参考 Bamboo 后，当前对话执行入口先将请求转换为 `RunParams`，再由对象工厂创建类型化 `Task`，由 `TaskRuntime` 分流执行；具体 Agent 执行会把数据库/TOML 记录转换为 `AgentRun` 对象。模型网关使用 `ModelRequest` 与 `ModelResult`，工具调度使用 `ToolRequest` 与 `ToolResult`。这些对象跨运行层传递，配置文件和 HTTP/SQLite 边界仍用原生映射。新用户目录预置主流云平台、本地模型和 Bamboo 风格公司 HTTP 代理的模型别名，并提供图片、视频处理协议。供应商模型名和账号权限仍需用户核实。

## 1. 核心原则

1. **配置文件定义身份，数据库保存运行状态。** 规划使用 `~/.FutureWork/agents/<id>.toml` 和 `~/.FutureWork/teams/<id>.toml` 作为 Agent 与群聊定义的来源。消息、任务、审批、未读数存入数据库；摘要与记忆按独立作用域存储。
2. **一个 ID 对应一个配置文件。** 文件名、文件内 `id` 和数据库投影 ID 必须相同。Agent 与群聊各用自己的命名空间；不要用展示名称、数组下标或文件路径作为运行时主键。
3. **上下文按作用域隔离。** 小未对话使用 `(workspace_id, assistant, assistant_id)`；Agent 私聊使用 `(workspace_id, agent, agent_id)`；群聊使用 `(workspace_id, group, group_id)`；任务使用短期作用域 `(workspace_id, task, task_id)`。
4. **群成员共享群上下文，不共享私聊上下文。** Agent 在群聊中可用自身角色配置和该群的历史、摘要及共享记忆；不得自动读取自己与用户的私聊，也不得读取其他群的历史。
5. **版本固定。** 配置变更产生新版本；已启动任务记录 Agent/群聊配置版本与上下文快照游标，避免执行中权限和规则悄然变化。
6. **用户创建也是创建配置。** 小未或用户在页面创建 Agent/群聊时，服务端先验证并写入对应 TOML，再同步数据库投影；高风险权限仍先走审批。

## 2. 安装方式与目录布局

### 2.1 安装和首次启动契约

未来工程以 Python 包发布，在项目根目录执行 `python -m pip install -e .` 后，应能从任意工作目录使用 `futurework` 命令或 `python -m futurework`。`pyproject.toml` 声明包发现、静态页面与内置默认配置的 package data、依赖及 `futurework` 命令入口；项目运行时不得依赖当前工作目录或源码树中的相对路径。

`pip install -e .` 负责安装包和命令入口。**首次执行 `futurework init` 或 `futurework serve` 时自动创建 `~/.FutureWork/`**；`serve` 内部先执行幂等初始化，再加载配置。这样普通安装、可编辑安装和升级都遵循相同规则，安装器不会在构建阶段改写用户目录。`futurework init` 用于希望启动前先检查或手工编辑配置的用户；`futurework paths` 显示实际路径。用 `FUTUREWORK_HOME` 或 `--home` 指定另一目录时，初始化和读取都只作用于该目录。

当前实现将内置能力统一放在 `abilities/`，包含 `tools`、`skills`、`mcp`、`workflows`、`friends`、`teams` 六类。全新用户目录仅预置小未、小T、小V和媒体群；旧 `~/.futurework` 存在且新目录缺失时先复制，再补齐缺失文件。用户侧也创建 `abilities/` 同样的六类目录，新增好友/群配置参与启动加载。**唯一内置 Skill 是 `skill-creator`**，默认加载到小未，调用 `skill_create` 时仍需审批；动态计划由 `plan_update` 和 `plan_check` 工具承担。`user.md` 初始为空，所有 Agent 提示词读取至多 500 字；模型可通过受限工具追加明确的用户事实。定时任务保存在 `data/schedules/`，服务运行时轮询。图片好友已接通图片上传、视觉模型和媒体工具；视频好友已接通文生视频、关键帧理解和本地裁剪缩放工具。声明式 Agent Workflow 和本机 MCP stdio 工具已接入，权限仍由好友配置和工具审批层控制。

首次初始化只复制缺失的内置示例，不覆盖用户已有 TOML、Skill、Workflow、MCP 或记忆。旧版本升级不自动重置用户配置；需要迁移时先备份、校验 schema，再原子写入。用户目录权限默认仅当前用户可读写。初始化失败时给出具体文件路径和原因，不允许带着半套配置启动。

### 2.2 用户目录：配置和运行数据的真实位置

```text
~/.FutureWork/
├── app.toml                         # 服务、默认策略、预算和路径
├── models.toml                      # 多平台实例与模型别名
├── user.md                          # 最多 500 字的共享用户信息与偏好
├── abilities/                      # 用户自建 tools/skills/mcp/workflows/friends/teams
├── agents/
│   ├── assistant.toml               # 小未
│   ├── assistant.md                 # 小未人物长期记忆；角色、性格、职责
│   ├── <agent_id>.toml              # 手工编写或应用生成的 Agent 好友配置
│   └── <agent_id>.md                # 好友长期人物记忆；不覆盖人工编辑
├── teams/
│   ├── <team_id>.toml               # 手工编写或应用生成的群聊/Team 配置
│   └── <team_id>.md                 # 群聊长期职责与协作约定
├── prompts/                         # 被 Agent 配置显式引用的长提示词
├── skills/
│   └── <skill_id>/SKILL.md          # 用户人工安装的 Skill 及其资源
├── workflows/
│   └── <workflow_id>/workflow.toml  # 用户人工安装/编写的 Workflow
├── mcp/
│   └── <server_id>.toml             # 用户配置的 MCP 连接；不存明文密钥
├── memory/
│   ├── assistant/                   # 小未 messages.jsonl、experiences.md
│   ├── agents/<agent_id>/           # 好友私聊 messages.jsonl、experiences.md
│   └── teams/<team_id>/             # 群聊 messages.jsonl、overview.md
│       └── topics/<topic>/          # index.md 和 <person_id>.md 经验
├── data/                            # SQLite、任务产物、运行状态
├── logs/                            # 脱敏日志
└── cache/                           # 可重建缓存
```

用户可以直接编辑 `agents/*.toml`、`teams/*.toml`，并手工安装 Skill、Workflow 和 MCP 配置。加载器以文件名和内部 ID 一致为基本条件，扫描用户目录，按 `app → models/扩展注册表 → Agent → Team → Runtime` 的顺序解析与交叉校验；Team 引用的 Agent、Agent 引用的模型和扩展必须存在且可用。有效配置投影到数据库，消息、审批、任务和已读状态继续留在数据库；数据库中的旧投影不能覆盖手写 TOML。目录中存在无效配置时，保留上一个有效版本并明确报告错误，不静默跳过或使用内置示例代替。运行开始时固定配置版本；手工改文件后通过重启或显式 reload 使新配置进入后续运行，进行中的运行不换版本。

`skills/`、`workflows/`、`mcp/` 属于用户安装区域；应用随包发布的内置扩展只读，二者由同一个扩展注册表索引。发现一个扩展不等于启用或授权。`memory/` 与数据库中的消息/摘要共同组成上下文材料，但读写必须经过 `ScopeKey` 和权限策略，不能仅凭磁盘路径把某个 Agent 私聊记忆加载进群聊。密钥值由环境变量或系统密钥库提供，TOML 只保留引用。

**当前文件记忆实现：** `contexts/types.py` 定义 `ScopeKey`，`contexts/store.py` 将 SQLite 已提交的消息按小未、好友、群聊分别写入 `messages.jsonl`。文件记录保留原文、发送者、时间、消息 ID 及任务/审批关联；数据库仍是页面消息和状态的主数据源。每次数据库事务提交后同步新增消息；启动时从数据库重放并按消息 ID 去重，补齐中断时未写入的文件。自动 Markdown 经验由 `ExperienceSummarizer` 从回复中提取有限行，附源消息 ID；好友和小未写入各自的 `experiences.md`，群聊按用户话题和发言人写入 `topics/<topic>/<person_id>.md`，`topics/<topic>/index.md` 汇总该话题参与者，`overview.md` 索引所有话题。原始 JSONL 不截断，Markdown 提取长度与提示词经验预算由 `context.toml [memory]` 控制。当前摘录不是模型深度反思，也不具备跨话题语义归并。

`agents/assistant.md`、`agents/<agent_id>.md`、`teams/<team_id>.md` 是可人工维护的长期介绍。仅缺失时从 TOML 生成，不覆盖已有 Markdown。小未的个人对话和群中控都会加载所有人物、群聊介绍全文，供模型理解团队背景；当前自动分派排名仍由 `TaskPlanner` 的能力分值规则决定。个人对话只加载小未的私聊经验，群中控只加载当前群经验。好友私聊只加载该好友介绍与经验；群成员加载自己的介绍、当前群介绍和群经验，不加载其私聊经验。这是当前提示词可见性规则；后续更细的分享、检索、压缩、删除和多进程写入协调仍按目标架构扩展。

**当前检索与压缩：** `MemoryRetriever` 的 `memory_search` 先查当前人物的经验 Markdown，群成员继而查当前群索引和其他成员经验，未命中才查当前作用域的 JSONL。小未可显式指定已有群 ID；好友私聊不能跨作用域。`ContextCompactor` 对完整模型请求作保守 Token 估算，以模型别名的窗口和输出上限或 `[compaction]` 默认值决定触发；旧消息只选择不会拆散工具调用与结果的前缀，最近消息保持原样。模型摘要失败时使用有界摘录，摘要只参与本次请求，原始 SQLite/JSONL 不改写；每次有收益的压缩追加到当前作用域的 `compactions.jsonl`，保留源消息 ID 与原文哈希。当前不是精确 tokenizer，跨请求尚未复用已有压缩摘要。

**当前工具执行层：** `AgentRuntime` 把模型请求的每次工具调用封装为 `ToolCall`，交给 `ToolExecutionLayer`。该层按固定的 Agent/Scope、授权快照和 schema 验证参数，按 `tools.toml [execution]` 判断单次调用审批，必要时在现有审批列表创建带完整参数的请求并等待用户决定。审批通过后再查一次当前 Agent 授权，然后调用 `ToolRegistry` 分发到 `abilities/tools/<name>/handler.py`。输出按文本或结构化 JSON 校验并限制长度；临时 HTTP/网络/系统故障按 Bamboo 的分类只对可重放读工具在预算内重试，写类操作不自动重放。作用域内 `tool_calls.jsonl` 记录决策、哈希、尝试类别和结果；审批超时或进程退出不会自动恢复悬置的模型调用。

### 2.3 目标源码模块树（逻辑视图）

```text
FutureWork/
├── README.md
├── pyproject.toml
├── uv.lock
├── .env.example                     # 环境变量名称示例；密钥不入库
├── config/
│   ├── app.toml                     # 服务、数据库、队列、限额、前端公开参数
│   ├── models.toml                  # 模型别名、供应商实例、费用/上下文窗口
│   ├── tools.toml                   # 工具注册表、风险等级、默认审批策略
│   ├── matching.toml                # 匹配权重、阈值、负载与成本参数
│   ├── planner.toml                 # 任务拆解约束、能力词典、回退规则
│   ├── runtime.toml                 # 单次运行的循环、超时、并发、重试与预算上限
│   ├── context.toml                 # 全局上下文预算、摘要、检索和保留策略
│   ├── extensions.toml              # 扩展来源、安装目录、信任策略和资源限额
│   ├── agents/
│   │   ├── assistant.toml           # 小未；特殊 Agent，仍遵循同一配置 schema
│   │   ├── image.toml               # 小T
│   │   └── video.toml               # 小V
│   ├── teams/
│   │   └── multimedia.toml          # 媒体群
│   └── prompts/
│       ├── assistant.md
│       └── agents/                  # 可选长提示词；由 Agent TOML 显式引用
├── extensions/
│   ├── abilities/                   # 随应用版本发布；代码审查后入库
│   │   ├── tools/
│   │   │   ├── calculator/
│   │   │   │   ├── manifest.toml    # ID、版本、参数 schema、风险和入口
│   │   │   │   └── handler.py       # Python 工具实现
│   │   │   └── web_fetch/           # 经过地址检查的公共网页抓取
│   │   ├── skills/
│   │   │   └── research-brief/
│   │   │       ├── manifest.toml    # 依赖、适用 Runtime、输入和资源声明
│   │   │       ├── SKILL.md         # Agent 使用说明
│   │   │       └── resources/       # 可选模板与静态资料
│   │   ├── mcp/
│   │   │   └── example-server/
│   │   │       └── manifest.toml    # MCP 连接/启动定义，不含凭证
│   │   └── workflows/
│   │       └── product-launch/
│   │           └── workflow.toml   # 声明式步骤、依赖和审批点
│   └── schemas/                    # 扩展包 manifest、工具输入、workflow schema
├── backend/
│   ├── __main__.py                  # 从 app.toml 读取监听配置并启动
│   ├── bootstrap.py                 # 加载、校验全部配置并建立数据库投影
│   ├── api/
│   │   ├── app.py                   # FastAPI 组装，不放业务规则
│   │   ├── agents.py                # Agent 查询、创建、配置修订
│   │   ├── groups.py                # 群聊查询、创建、成员变更
│   │   ├── conversations.py         # 消息、已读、会话查询
│   │   ├── tasks.py                 # 任务与步骤
│   │   ├── approvals.py             # 精确动作/配置审批
│   │   └── events.py                # SSE 及断线重放
│   ├── schemas/
│   │   ├── agent_config.py          # Pydantic：Agent TOML schema
│   │   ├── group_config.py          # Pydantic：Group TOML schema
│   │   ├── runtime.py               # 消息、任务、审批 API schema
│   │   └── config_validation.py     # 引用完整性、唯一性、路径安全
│   ├── config_store/
│   │   ├── loader.py                # 扫描 TOML、解析、哈希、版本
│   │   ├── writer.py                # 草稿、原子写入、冲突检查
│   │   └── reconciler.py            # 文件与数据库投影对账
│   ├── domain/
│   │   ├── agents.py                # Agent 身份、版本、状态机
│   │   ├── groups.py                # 成员关系、群回复策略
│   │   ├── tasks.py                 # 任务和 DAG 状态机
│   │   ├── permissions.py           # 工具和数据作用域判定
│   │   └── matching.py              # 纯 Python 能力匹配算法
│   ├── contexts/
│   │   ├── types.py                 # ScopeKey、ContextSnapshot、引用元数据
│   │   ├── store.py                 # 当前：SQLite 消息镜像到独立 JSONL/Markdown
│   │   ├── assistant_context.py     # 小未对话、计划摘要与任务追踪
│   │   ├── agent_context.py         # Agent 私聊历史与私有记忆
│   │   ├── group_context.py         # 群消息、群摘要与共享记忆
│   │   ├── task_context.py          # 单次任务的临时输入和产物
│   │   ├── assembler.py             # 按权限组装模型上下文
│   │   ├── summarizer.py            # 增量摘要、回溯来源
│   │   ├── compactor.py             # 按模型窗口压缩旧消息并保留作用域审计记录
│   │   ├── retrieval.py             # 按作用域检索；不得跨域默认搜索
│   │   └── policy.py                # 显式分享、保留与删除规则
│   ├── runtime/
│   │   ├── run_params.py           # 入口消息、来源、目标配置快照和幂等 ID
│   │   ├── task_factory.py         # 按会话及意图创建类型化 Task；不执行副作用
│   │   ├── task_runtime.py         # 幂等检查、任务分流、持久化与后台调度
│   │   ├── router.py                # 按会话类型选择三种顶层 Runtime
│   │   ├── assistant_runtime.py     # 小未对话：规划、分派、建 Agent、汇总
│   │   ├── direct_runtime.py        # Agent 私聊：单 Agent 回复与私有上下文
│   │   ├── group_runtime.py         # 群聊公共状态机与共享上下文
│   │   ├── group_swarm.py           # 无中控：成员自治、发言队列与停止条件
│   │   ├── group_controlled.py      # 小未中控：规划、分派、跟踪与汇总
│   │   ├── agent_executor.py        # 三种 Runtime 共用的单 Agent 推理/工具循环
│   │   ├── run_spec.py              # 配置版本、上下文作用域、任务和预算快照
│   │   ├── checkpoints.py           # 运行状态持久化、恢复和取消
│   │   ├── tool_dispatch.py         # 模型可见 schema 与内置处理器分发
│   │   ├── tool_execution.py        # 入参出参校验、授权、审批、失败分类与安全重试
│   │   └── tool_approvals.py        # 单次工具调用审批持久化与等待决策
│   ├── extension_system/
│   │   ├── registry.py              # 内置与已安装扩展的统一索引、版本固定
│   │   ├── installer.py             # 下载/导入、校验、暂存、原子安装与回滚
│   │   ├── resolver.py              # 为一次 Runtime 运行解析允许的扩展快照
│   │   ├── skill_loader.py          # 加载 SKILL.md 与资源，不隐式执行代码
│   │   ├── mcp_client.py            # MCP 发现、连接、schema 与超时控制
│   │   └── workflow_runner.py       # 校验并调度声明式工作流 DAG
│   ├── services/
│   │   ├── agent_service.py          # 创建配置、审批、激活、版本切换
│   │   ├── group_service.py          # 创建群、成员变更、上下文初始化
│   │   ├── message_service.py        # 消息写入、路由、事件
│   │   ├── task_service.py           # 规划、分派、执行、汇总
│   │   └── inbox_service.py          # 最近动态/全部/待审批读模型
│   ├── integrations/
│   │   └── model_gateway/
│   │       ├── gateway.py           # 别名路由、预算、重试、用量归一化
│   │       ├── types.py             # ModelRequest/ModelResult/错误类型
│   │       ├── registry.py          # 加载平台实例和模型别名
│   │       └── adapters/
│   │           ├── openai_chat.py   # OpenAI Chat Completions 协议
│   │           ├── anthropic.py     # Claude Messages 协议
│   │           ├── base.py          # Adapter 协议与能力声明
│   │           └── profiles/        # 平台差异：阿里云、DeepSeek、Kimi、MiniMax、OpenRouter、OpenAI
│   ├── persistence/
│   │   ├── models.py                # SQLAlchemy 表
│   │   ├── repositories/            # Agent、Group、Context、Task 等仓储
│   │   └── unit_of_work.py          # 事务与 outbox
│   └── workers/
│       ├── task_worker.py           # 长任务、租约、重试
│       └── config_reconciler.py     # 配置文件与投影周期核对
├── frontend/
│   ├── index.html
│   ├── src/
│   │   ├── app/                    # 路由、初始化、SSE 客户端
│   │   ├── features/
│   │   │   ├── agents/              # 好友列表与配置抽屉
│   │   │   ├── groups/              # 群聊列表、成员管理
│   │   │   ├── chat/                # 聊天区和消息卡
│   │   │   ├── inbox/               # 最近/全部/待审批视图
│   │   │   └── tasks/               # 任务 DAG 与状态
│   │   └── shared/                 # API client、类型、通用组件
│   └── public/
├── migrations/                     # 数据库结构迁移
├── tests/
│   ├── config/                     # 文件 schema、引用和热更新测试
│   ├── contexts/                   # 私聊/群聊隔离测试
│   ├── domain/                     # 匹配、DAG、权限纯函数测试
│   ├── extensions/                 # 安装、依赖、授权、版本与沙箱测试
│   ├── api/                        # 契约与幂等测试
│   └── e2e/                        # 页面主流程
├── scripts/                        # 开发启动、导入、备份和配置检查
├── docs/                           # 架构、接口、运维与迁移方案
└── data/                           # 本地运行数据；gitignored
    └── extensions/                 # 运行时安装的扩展；生产环境改为持久卷/对象存储
        ├── skills/<publisher>/<id>/<version>/
        ├── mcp/<publisher>/<id>/<version>/
        ├── workflows/<publisher>/<id>/<version>/
        └── tools/<publisher>/<id>/<version>/
```

这是**目标模块组织方式**。Python 包位于 `src/futurework/`；上面的 `backend/` 和 `frontend/` 表达后端模块与页面资源的职责，不要求按这棵概念树在仓库根目录创建同名文件夹。`config/` 和 `data/extensions/` 所指的可写内容规划放在 `~/.FutureWork/`：`app.toml`、`models.toml`、`agents/`、`teams/`、`skills/`、`mcp/`、`workflows/`、`memory/`、`data/`。内置默认文件随包发布，首次运行复制到用户目录；以后以用户目录为准。当前静态页面原型位于 `frontend/`，其组件目录仍是骨架。

## 3. 配置文件契约

### 3.1 Agent：一个文件定义一个好友

`~/.FutureWork/agents/research.toml` 目标配置示例：

```toml
schema_version = 1
id = "research"
name = "知知"
role = "研究与洞察"
kind = "friend"
status = "active"
icon = "知"
color = "#e7e8fa"
ink = "#7873ad"
prompt_file = "prompts/agents/research.md"

[model]
id = "default_fast"                 # 引用 models.toml 中的别名
temperature = 0.4                   # 覆盖全局默认值；可省略

[capabilities]
"research.web" = 0.95
"analysis.summary" = 0.80

[permissions]
tools = ["abilities/web_fetch@1.0.0"]
approval_policy = "standard"       # 引用 tools.toml 中的策略
data_scopes = ["user_shared_files"]

[extensions]
skills = ["abilities/research-brief@1.0.0"]
mcp_servers = []
workflows = []

[context]
private_memory = true
history_token_budget = 6000
summary_trigger_tokens = 4500
memory_retention_days = 180
share_to_groups = "explicit_only"

[limits]
max_concurrent_tasks = 2
daily_token_budget = 100000

[runtime]
profile = "standard"                 # 引用 runtime.toml；小未可用 orchestrator
max_turns = 8                         # 只能在全局硬上限内覆盖
```

`assistant.toml` 使用相同 schema，增加 `kind = "assistant"`、`system = true` 和规划权限；系统内恰好一个 assistant。`prompt_file` 的相对路径只能落在 `~/.FutureWork/prompts/` 内。小型 Agent 可直接用 TOML 的 `system_prompt` 字段；长提示词用独立 Markdown 文件，仍由该 Agent 配置文件引用。

### 3.2 Group：一个文件定义一个群聊

`~/.FutureWork/teams/launch.toml` 中控群示例：

```toml
schema_version = 1
id = "launch"
name = "产品发布小组"
status = "active"
icon = "发"
color = "#e4ede7"
ink = "#398769"
members = ["design", "write", "plan"]
mode = "controlled"                 # controlled | swarm

[reply]
max_responders_per_round = 3
max_rounds = 2
max_total_model_calls = 8
on_budget_exhausted = "summarize_and_stop"

[controller]
agent_id = "assistant"              # controlled 必须为小未；swarm 禁止设置
selection_policy = "mention_then_capability"
require_plan = true
summarize_results = true

[context]
history_token_budget = 10000
summary_trigger_tokens = 7500
shared_memory = true
memory_retention_days = 180
private_chat_import = "never"
history_visibility = "since_joined"

[permissions]
allow_member_tools = true             # 不授予新权限；仍以各 Agent 的授权为上限
external_share = "approval_required"

[extensions]
skills = []                            # 群共享操作说明，不扩大成员工具权限
workflows = ["abilities/product-launch@1.0.0"]
mcp_allowlist = []                     # 群可用连接上限；成员仍须独立授权
```

`swarm` 群保留共同字段和 `[reply]`，删除整个 `[controller]` 表。群配置只引用成员 ID，不复制成员的模型、能力或工具授权。成员不存在、处于 archived 状态或重复时，启动校验失败。`mode` 只允许 `swarm`、`controlled`；`controlled` 必须指定小未，`swarm` 不得出现中控配置。群聊的 `allow_member_tools` 仅表示群内是否允许发起工具请求，不能覆盖 Agent 自身权限和用户对资源的授权。模式、成员或预算变化产生新的群配置版本，进行中的一轮继续使用启动时的快照。

**Swarm：无中控。** 每个 Agent 根据自身能力、群内消息和显式 `@` 判断是否参与；`@` 限定候选成员，无 `@` 时所有符合群订阅规则的成员可提出发言意向。`GroupChatRuntime` 只负责公平排队、并发限制、消息提交顺序、预算和停止条件，不生成任务计划，也不以小未身份决定谁该说什么。成员能看到群作用域内已提交的消息，不能读取其他成员的私聊。每轮每个成员最多一次主动发言；后续轮次只由新群消息或明确协作请求触发。所有成员间的请求和结果都写入群时间线，防止隐形对话和无限循环。

**Controlled：小未中控。** 小未在群作用域中创建结构化 `GroupPlan`（用户目标、候选成员、分派步骤、依赖、预算、停止条件），策略校验后再分派。明确 `@Agent` 是候选约束；小未可以请求补充信息、安排多名成员按步骤协作、汇总结果或发起审批。她只使用本群上下文和成员公开能力，不自动读取自己与用户的私聊记忆，也不把群聊内容写回个人助理私聊。若小未模型不可用，采用配置的降级策略：暂停并告知用户，或按显式规则选择一位成员；不能静默切到 Swarm。两种模式均受同一群权限和成本硬上限约束。

### 3.3 全局配置与覆盖顺序

`app.toml` 只放全局运行参数；模型、工具、匹配、上下文各有专用文件。**生效值 = 全局默认值 → 作用域配置覆盖 → 任务级限制收紧**。任务只能收紧限额或权限，不得扩大 Agent/群权限。敏感配置（模型 API key、数据库凭证）由环境变量或密钥管理器注入；TOML 只存环境变量名称/密钥引用。

文件解析使用 `tomllib`，Pydantic schema 设置 `extra = "forbid"`，避免拼写错误被静默忽略。校验必须覆盖：schema 版本、文件名与 ID 一致、ID 唯一、模型/工具/能力引用有效、成员关系有效、上下文预算为正、风险策略不弱于全局下限、提示词路径不能越界。配置通过校验后计算内容哈希并存入 `config_versions`；热更新只对新任务生效。

#### 3.3.1 多平台模型注册与适配器

`~/.FutureWork/models.toml` 将**平台实例**与**模型别名**分开。平台实例决定协议、接口地址和密钥环境变量；别名决定平台实例、原生模型 ID、能力、上下文窗口和预算参数。Agent 的 `[model].id` 只引用别名，不直接写 URL 或密钥。用户可以同时配置多个平台，甚至为同一供应商配置两个不同账户。示例：

```toml
schema_version = 1

[providers.aliyun_cn]
adapter = "openai_chat"
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
api_key_env = "DASHSCOPE_API_KEY"
region = "cn"

[providers.deepseek]
adapter = "openai_chat"
base_url = "https://api.deepseek.com"
api_key_env = "DEEPSEEK_API_KEY"

[providers.claude]
adapter = "anthropic_messages"
base_url = "https://api.anthropic.com"
api_key_env = "ANTHROPIC_API_KEY"
api_version = "2023-06-01"

[models.default_fast]
provider = "deepseek"
remote_id = "deepseek-chat"
context_window = 64000
supports_tools = true
supports_streaming = true
# 价格未知时省略价格字段，此模型不可用于自动成本比较或自动跨平台回退

[models.review_strong]
provider = "claude"
remote_id = "<填入账户可用的 Claude 模型 ID>"
context_window = 200000
supports_tools = true
supports_streaming = true
```

平台实例可用多个别名复用。`model_id` 与 `remote_id` 不应混用：本项目用 `models.<alias>` 作为稳定引用，普通适配器将 `remote_id` 发给平台；`http_provider` 为兼容 Bamboo，会去掉其开头的 `local_`。实际端点、模型 ID、价格、上下文限制与功能支持均由用户按账户和平台文档配置并校验；示例不承诺特定模型长期可用。

| 平台实例类型 | 目标适配器 | 关键差异 |
| --- | --- | --- |
| OpenAI GPT | `openai_chat.py` | Bearer key、Chat Completions 消息和工具调用 |
| 阿里云百炼、DeepSeek、Kimi、MiniMax | `openai_chat.py` + 各自的 profile；确有协议差异时增加平台适配器 | 优先用官方兼容端点；按平台分别校验端点、模型 ID、参数、鉴权、错误和 usage，不在业务层写平台分支 |
| OpenRouter 等第三方聚合平台 | `openai_chat.py` + 平台元数据 | 远端模型 ID 可能含供应商前缀；上游实际供应商、地域及价格需要记录，敏感数据路由受策略限制 |
| Anthropic Claude | `anthropic.py` | Messages API、`x-api-key`/版本头、独立 system 与 content block；工具结果和停止原因单独映射 |
| 公司 HTTP 模型代理 | `http_provider.py` | 向完整配置 URL 发 POST；外层 `model`、`request`、`timeout`；兼容 `result` 包裹的响应与业务状态字段，端点和密钥使用环境变量 |

`ModelGateway.generate(ModelRequest) -> ModelResult` 是唯一模型入口。请求包括别名、消息与内容块、工具 schema、流式开关、作用域、截止时间和 token/费用预算；结果统一文本、工具调用、usage、结束原因、平台 request ID 与错误类别。适配器只做协议转换、鉴权头与响应解析；网关负责路由、并发/速率限制、审计、用量与费用核算。模型参数先取全局默认，再应用平台限制和 Agent 覆盖；调用前检查 `supports_tools`、`supports_streaming`、上下文窗口及预算，不能把不支持的能力硬塞进请求。

每个平台 profile 独立声明 `endpoint_path`、默认请求头、支持的参数、工具/流式能力映射、错误码与 usage 解析规则：`openai`、`aliyun`、`deepseek`、`kimi`、`minimax`、`openrouter`；Claude 使用 `anthropic` 协议适配器和 profile。这样多平台共用协议核心，但兼容性差异有明确维护位置。未知 OpenAI 兼容平台可从受限的 `openai_chat` profile 起步，只有通过契约测试后才开放工具调用、流式输出或自动回退。平台返回的模型列表可供配置检查，但不能自动改写 Agent 已选的别名。

密钥只保存在环境变量或系统密钥库，配置文件只写引用；日志、异常和 SSE 事件必须脱敏。401/403、配置错误和能力不支持直接失败；429、5xx、超时按平台 `Retry-After` 和指数退避重试，次数与总耗时受全局硬上限约束。产生工具副作用后禁止自动重放整轮请求。跨平台回退必须由 Agent 显式列出候选别名，并逐一验证工具能力、数据地域、费用与用户授权；不能因为一个平台故障就把私有数据自动发到另一个平台。上述网关和适配器均为设计目标。

### 3.4 三种对话 Runtime

三类对话需要**三个不同的顶层 Runtime**。`runtime/router.py` 根据会话类型选择其一；它们各自决定上下文、状态流转和可执行动作，共用底层的 `AgentExecutor`、模型网关、工具检查和 checkpoint 组件。这里的 Runtime 是一次会话处理的执行器，不要求为每个好友或群聊常驻一个 Python 进程。

**当前版本的入口对象链：** API 读取会话配置并将消息归一化为 `RunParams(source, target, message, client_message_id)`；`TaskRuntime.handle` 先按客户端消息 ID 检查幂等，仅对新的小未消息做聊天/任务分类；`TaskFactory.create` 根据分类、会话类型和群模式创建 `Task(id, kind, params)`。工厂不访问数据库或模型。`TaskRuntime.run` 按 `assistant_chat`、`assistant_delegation`、`agent_chat`、`group_swarm`、`group_controlled` 分流；助理分派将同一 Task 对象交给后台步骤执行。好友私聊只取好友会话历史，群聊只取群历史；群模式在建 Task 时决定，后续按 `Task.kind` 执行。重复提交同一客户端消息 ID 返回原消息/任务 ID，跨会话复用返回冲突。这里的 Task 是一次对话执行对象；目前只有助理分派任务写入 `tasks`/`task_steps` 表，普通聊天和群聊不新增持久任务行。只读查询、配置修改和审批有独立业务语义，保持各自入口，不创建 Agent Task。

**当前版本的依赖装配：** FastAPI 启动时构造 `MessageService`、`AgentService`、`GroupService`、`AgentRuntime` 和 `TaskRuntime`。`TaskRuntime` 持有 `TaskPlanner`、`AssistantRuntime`、`DirectChatRuntime`、`GroupChatRuntime`；群运行时持有 `SwarmPolicy` 与 `GroupController`。`AgentRuntime.run(AgentRun)` 将当前会话范围内的历史与授权交给 `ModelGateway` 和单次运行的 `ToolRegistry`；模型网关按模型别名创建并缓存实现 `ModelAdapter` 的平台适配器，工具注册表用同一份授权生成 schema 并执行工具。API 不再实现消息写入、Agent 创建或群聊创建的 SQL 细节。兼容旧调用方的 `respond()`、`generate()`、`execute_async()` 等模块函数会新建对应对象；生产消息链使用已装配的对象。完整的上下文快照、持久运行 checkpoint 和跨进程恢复仍是目标设计，不能把当前对象化等同于这些能力已经完成。

| Runtime | 负责的会话 | 上下文作用域 | 核心职责 |
| --- | --- | --- | --- |
| `AssistantRuntime` | 用户 ↔ 小未 | `(workspace_id, "assistant", "assistant")` | 理解目标、规划、分派、创建 Agent 配置草案、跟踪和汇总任务 |
| `DirectChatRuntime` | 用户 ↔ 某个 Agent 好友 | `(workspace_id, "agent", agent_id)` | 加载该 Agent 配置和私聊上下文，完成单 Agent 回复与获准的工具调用 |
| `GroupChatRuntime` | 用户与多个 Agent 的群聊 | `(workspace_id, "group", group_id)` | 固定群配置版本和上下文，按 `mode` 调用 Swarm 或 Controlled 策略，控制轮次、预算与消息提交 |

```text
用户消息
  -> MessageRouter 读取会话类型与配置版本
     -> assistant_direct: AssistantRuntime.run(assistant_scope)
     -> agent_direct:   DirectChatRuntime.run(agent_scope)
     -> group:          GroupChatRuntime.run(group_scope, mode)
                         -> swarm: SwarmPolicy -> AgentExecutor(member...) * N
                         -> controlled: XiaoWeiController -> GroupPlan -> AgentExecutor(member...) * N

三种 Runtime 调用共用的 AgentExecutor：
  AgentExecutor.run(agent_config_version, allowed_context, task, budget)
    -> ModelGateway -> ToolDispatch -> Checkpoint
```

**AssistantRuntime** 可以创建任务计划和子任务，但只从自己的上下文及经授权回传的任务产物中取材。它不能因“协调者”身份直接读取任意好友私聊或绕过权限审批。**DirectChatRuntime** 固定一个好友配置版本及其私有上下文，聊天内容不会写入群共享记忆。**GroupChatRuntime** 拥有独立群状态机和上下文管理：`SwarmPolicy` 只执行成员自治发言和调度约束，`ControlledPolicy` 调用小未的群内中控子执行生成结构化计划，再把步骤交给成员的 `AgentExecutor`。两者都只传入群上下文及当前任务授权材料，不带入成员私聊。中控执行不等于 `AssistantRuntime` 的个人助理会话；它复用小未的身份配置和执行器，但使用群 `ScopeKey`、群预算、群审计记录。

群运行状态为 `received → selecting/planning → dispatching → collecting → summarizing/completed`，任一步可进入 `waiting_approval`、`failed` 或 `cancelled`。Swarm 跳过 `planning`，不生成中控总结；Controlled 可由小未生成汇总。成员结果提交到群时间线后才可作为下一轮输入。`max_rounds`、`max_responders_per_round`、`max_total_model_calls` 和 token/费用上限共同截断循环；达到上限时明确告知用户已有产物与未完成项。

三个 Runtime 的顶层状态分别持久化为 `runtime_runs` 记录，含 `run_id`、`runtime_type`、群 `mode`、`scope_key`、配置版本、消息游标、状态、预算和 checkpoint。群内小未的中控计划及每位成员的单次执行分别有 `group_plans`、`agent_executions` 子记录，关联群 `run_id`，以便取消、重试和审计。任务 worker 调用 `AgentExecutor` 完成子任务；它属于任务执行路径，不混用私聊或群聊的顶层状态机。

`runtime.toml` 统一定义最大循环次数、超时、重试、并发、token/费用硬上限和 checkpoint 周期；Agent TOML、群 TOML 只能在硬上限内收紧。`RunSpec` 固定 `agent_config_version?`、`group_config_version?`、`scope_key`、`context_cursor`、`task_id?` 和权限快照。权限变化只影响新运行；已暂停运行恢复时仍需重新检查敏感工具授权和审批有效期。

**当前实现范围：** Team TOML 的 `mode` 决定 Swarm 或小未中控的单轮执行；模型网关支持 OpenAI 兼容接口、Anthropic Messages、阿里云异步媒体和 OpenRouter 图片接口，默认文本别名指向 DeepSeek。通用工具调用、媒体处理、分层记忆检索、动态计划工具、用户画像、定时任务、声明式 Workflow 和 MCP stdio 已接通。完整多轮群计划和独立的群成员子执行记录仍待实现。

### 3.5 多入口的统一执行链（目标设计）

**当前实现：** `src/futurework/adapters/` 已有 `web/`、`api/`、`app/`、`cli/` 四个入口子目录。Web 与无页面 API 共用 FastAPI 路由和 TaskRuntime；API 入口验证 Bearer 密钥。桌面 App 使用 pywebview 加本机 loopback 服务复用网页，CLI 以进程内 ASGI 请求复用同一消息链。来源标记已归一化为 RunParams。下文的统一 TaskIngress、持久 run_id、按作用域的事件重放和跨端身份仍是下一阶段设计，不能把当前 SQLite 全局事件表等同于完整事件总线。

Bamboo 的 CLI、Web、API 和 pywebview 桌面 App 都将请求整理为 RunParams，再交给 TaskRuntime；桌面 App 通过本机 Python 桥接，不必启动 HTTP 服务。FutureWork 当前仅有 Web/FastAPI 消息入口，CLI 只有管理命令。未来增加桌面 App、版本化开放 API，CLI 聊天可随后增加。所有入口共用 TaskFactory、TaskRuntime、三种顶层 Runtime、AgentExecutor、上下文与审批；入口代码只处理身份、协议、附件和结果呈现。

```text
Web HTTP/SSE ───┐
桌面 App 本机桥 ├─> InboundAdapter ─> RunParams ─> TaskIngress ─> TaskFactory ─> TaskRuntime
开放 API HTTP ──┤                                              ├─> AssistantRuntime
CLI（后续）──────┘                                              ├─> DirectChatRuntime
                                                                └─> GroupChatRuntime
EventStore/Outbox <─ RuntimeEvent <──────────────────────────────┘
Web/App/API Presenter <─ 按权限读取事件、消息、审批和任务状态
```

现有 `RunParams(source, target, message, client_message_id)` 渐进扩展为稳定输入对象：`source` 为 `web | desktop | public_api | cli`，另有 `request_id`、`principal_id`、`workspace_id`、`target(kind,id)`、`message`、已入库的 `attachments`（对象 ID、类型、大小、哈希）、`reply_mode`、`trace_id`、`deadline`。平台用户/会话 ID 由入口认证后映射为内部 ID。客户端传来的 grants、本机路径、配置版本与 ScopeKey 不可信；权限、配置快照和上下文游标由服务端计算并固定在 RunSpec。现有 `from_http()` 可作兼容构造器，但 TaskFactory 不访问数据库、模型或平台协议。

| 入口 | 入站适配 | 出站适配 |
| --- | --- | --- |
| Web | 浏览器会话认证、上传与请求归一化 | SSE/轮询展示文本、媒体、进度和审批 |
| 桌面 App | 本机用户认证、pywebview 或等价 IPC 桥接 | 相同事件投影为窗口、通知与审批界面 |
| 开放 API | Token/OAuth、scope、限流和版本化 JSON/上传 | JSON 应答或 SSE，稳定错误码与事件游标 |
| CLI（后续） | 命令参数及本机身份转换 | 终端事件渲染与交互审批 |

`TaskIngress.submit(params)` 依次执行：验证身份和目标访问 → 附件入库与校验 → 按 `(workspace_id, principal_id, client_message_id)` 做幂等接收 → 保存用户消息与提交事件 → 创建 Task/RunSpec → 按 Task.kind 分流。重复请求返回原 run/message/task ID；相同幂等键但目标或内容哈希不同返回冲突。只读查询、配置编辑和审批走独立应用服务，不伪装成 Agent Task。网络断开不取消后台任务，取消须显式调用。

标准 `RuntimeEvent` 包含 event_id、sequence、run_id、conversation_id、scope_key、type、timestamp、payload、visibility；类型涵盖文本增量/完成、媒体、步骤、审批请求/结果、错误、取消和完成。持久化到事件表或 outbox 后分发，SSE 按 Last-Event-ID/游标重放，避免多进程下只依赖内存 EventBus。各 Presenter 仅转换输出格式与展示规则，不能修改权威消息。同步 API 等待至配置的上限，超时返回 202 和 run_id；后续用同一 run_id 查询或续订。跨 Web/App/API 查看同一会话需再次校验身份；审批绑定 approval_id、授权用户、配置版本和有效期，公开 API 默认不能自动批准。

目标模块位于 `src/futurework/`：`adapters/inbound/{web,desktop,public_api,cli}.py`、`adapters/outbound/{web,desktop,public_api,cli}.py`、`adapters/desktop/bridge.py`、`services/task_ingress.py`、`runtime/events.py`、`persistence/event_store.py`。入口监听、鉴权、允许来源、请求/附件限额、同步等待、事件保留与重放上限在 `app.toml [entrypoints.*]`；运行预算在 `runtime.toml`。桌面桥只向当前用户开放；若采用 loopback HTTP，绑定 127.0.0.1 并校验随机令牌及 Origin。

### 3.6 外部 Agent 好友的执行协议（目标设计）

**当前实现：** 用户可在 Agent TOML 的 `[execution]` 指定 `native`、`codex_cli`、`openclaw`、`process` 或 `http`，由 `agent_backends.toml` 的 profile 补充路径、端点和限制。AgentRuntime 将非 native 好友交给后端注册表；私聊、Swarm 群和任务步骤都复用这条分派链。Codex 使用非交互 CLI，OpenClaw 使用本机 `agent --local --json`，通用进程与 HTTP 使用 `futurework-agent-v1` JSON 请求/结果。当前外部后端只返回最终文本，暂无逐工具审批、OS 级沙箱、持久事件、取消或副作用确认；下文的协议和安全机制是目标，不能声称已全部落地。

OpenClaw、Codex、自编 Agent 和垂直领域 Agent 都作为配置驱动的好友接入；默认初始化仍只有小未、小T、小V和媒体群。好友的身份、能力、权限和长期人物介绍仍放 `~/.FutureWork/agents/<id>.toml` 与同目录 `<id>.md`（用户 `abilities/friends/` 使用相同 schema）。外部 Agent 是执行后端，**不是模型 provider**；内置好友仍以 `execution.kind = "native"` 走现有 AgentRuntime/ModelGateway。三种顶层 Runtime 和各自 ScopeKey 不因后端不同而变化，小未可以按能力分派，群成员也可以使用外部后端。

```text
Assistant/Direct/Group Runtime -> AgentExecutor.run(AgentRunSpec)
  -> ExecutionRegistry.resolve(execution.kind)
       native     -> AgentRuntime -> ModelGateway/ToolExecutionLayer
       codex_cli  -> 经版本探测的本机 Codex 适配器
       openclaw   -> 经验证的 OpenClaw CLI 或本地 API 适配器
       process    -> 通用 stdio JSONL/JSON-RPC 适配器
       http       -> 通用 HTTP/SSE 适配器
  -> ResultValidator -> MessageService/ContextStore -> RuntimeEvent
```

Python `AgentBackend` 协议统一为 `describe() -> CapabilityDescriptor`、`health() -> HealthState`、`run(AgentRequest) -> AsyncIterator[AgentEvent]`、`cancel(run_id)`。请求包含 run_id、幂等键、agent_id、task_kind、输入、按 ScopeKey 装配的有限上下文、获准产物引用、权限/工作区、预算和截止时间；不得传整个用户目录、其他会话历史、数据库句柄或未授权凭据。事件为 started、text_delta、artifact、approval_request、usage、completed、failed，带 run_id 与有序序号。结果包含文本或受限产物、错误类别、可选用量和外部调用 ID。只有适配器能上报并暂停每次工具调用时，才能接入 FutureWork 的逐工具 ToolExecutionLayer。

Codex 好友配置意图（CLI 的具体命令和参数必须由适配器按已安装版本探测，以下字段不是 Codex 原生命令行参数）：

```toml
schema_version = 1
id = "coder"
name = "代码助手"
kind = "friend"
status = "active"
[capabilities]
"coding.implementation" = 0.95
"coding.review" = 0.90
[execution]
kind = "codex_cli"
profile = "local_coding"
transport = "subprocess"
[execution.permissions]
workspaces = ["~/projects/approved-project"]
network = "deny"
credential_refs = []
approval_mode = "task"
```

OpenClaw 好友仅固定 FutureWork 的配置接口，适配器在安装环境中验证可用传输，不假定 OpenClaw 必然支持某一 CLI 参数或工具审批协议：

```toml
schema_version = 1
id = "openclaw_helper"
name = "本机助理"
kind = "friend"
status = "active"
[capabilities]
"operations.assistance" = 0.80
[execution]
kind = "openclaw"
profile = "local_openclaw"
transport = "auto_verified"
[execution.permissions]
workspaces = []
network = "deny"
credential_refs = []
approval_mode = "task"
```

自编/垂直 Agent 优先实现通用 `process` 或 `http` 协议，不为每个品牌重写核心 Runtime。HTTP 端点由固定引用解析并校验 allowlist，远端服务另需 TLS 和授权：

```toml
schema_version = 1
id = "legal_research"
name = "法务检索"
kind = "friend"
status = "active"
[capabilities]
"legal.research" = 0.90
[execution]
kind = "http"
profile = "legal_local"
endpoint_ref = "legal_research_endpoint"
protocol = "futurework-agent-v1"
[execution.permissions]
workspaces = []
network = "loopback_only"
credential_refs = ["LEGAL_AGENT_TOKEN"]
approval_mode = "task"
```

`~/.FutureWork/agent_backends.toml` 管理 profile、可执行文件绝对路径/版本约束、允许端点、环境变量白名单、启动参数模板、工作目录、输出和附件上限、并发、健康检查、超时、可重试错误类别；密钥仅存引用。全局硬上限在 app.toml，Agent TOML 只可收紧。安装探测不等于自动注册好友：用户显式导入后先 describe/health，展示真实文件/网络/凭据/审批权限，获准才写配置及初始化专属记忆；加入群仍走成员校验和授权。

FutureWork 的 SQLite 时间线和分作用域 JSONL/Markdown 是权威记录；外部 Agent 内部历史仅是其实现状态。请求只带当前私聊、当前群或明确分享的任务材料；外部会话 ID 按 `(agent_id, scope_key)` 映射。不支持会话隔离的后端必须无状态运行或拒绝加入群。输出经 schema、大小、媒体类型、路径和敏感字段校验后才提交消息；失败时部分增量只留运行事件。

权限模式分为 `controlled`（逐工具上报、暂停并交给 ToolExecutionLayer 审批）和 `task`（内部工具不可见，运行前按整项任务审批，并限制进程/容器、工作区挂载、网络和凭据）。TOML 声明 `network = "deny"` 不代表系统已经隔离；若宿主平台无法强制声明的边界，注册或启动必须拒绝，或展示实际可强制权限并要求按真实边界重新配置，不能靠提示词冒充隔离。子进程只用参数数组启动；记录执行文件版本/哈希、配置版本、请求与结果摘要和错误，日志脱敏。

超时、取消、断连和崩溃映射为 retryable_transport、terminal_config、permission_denied、budget_exceeded、cancelled、external_failure。只有适配器保证幂等且确认无外部副作用才自动重试；否则标记 outcome_unknown，等待用户处理。取消先调用协议取消，宽限期后终止本地进程；远端无法确认取消时明确提示仍可能运行。群中一个成员失败只影响该成员本轮，由 Swarm/Controlled 策略处理。

目标模块：`integrations/agent_backends/{base,registry,native,codex_cli,openclaw,process,http}.py`、`schemas/agent_backend.py`、`services/agent_registration.py`、`runtime/agent_executor.py`。旧 Agent 配置无 `[execution]` 时按 native 迁移并提示配置升级。实施先统一入口对象和持久事件，再验证 Web/API 跨端幂等与审批，接桌面桥；外部好友先做 process/http 契约、隔离、取消和群聊测试，再做 Codex/OpenClaw 版本探测适配。验收必须覆盖跨入口同消息只执行一次、断线续订、跨端审批归属、外部私聊不泄漏到群、权限不可强制时禁止启动，以及结果未知时不重试副作用。

### 3.7 Tool、Skill、MCP 与 Workflow 扩展目录

`extensions/abilities/` 放随应用发布且经过代码审查的内置扩展；`data/extensions/` 放用户后续安装的版本化扩展（本地开发路径，生产应为独立持久卷或扩展仓库）。两者由 `extension_system/registry.py` 统一索引，但**安装、启用、授予 Agent/群使用权**是三个独立动作。安装成功不等于自动进入任意 Agent 的上下文或获得工具权限。

| 类型 | 目录内容 | 谁调用 / 关键边界 |
| --- | --- | --- |
| Tool | `manifest.toml` + Python handler、输入/输出 schema、风险等级 | `AgentExecutor` 经 `ToolDispatch` 调用；实际权限由 Agent 配置、资源作用域和审批共同决定 |
| Skill | `manifest.toml` + `SKILL.md` + 可选静态资源 | 在适用 Runtime 中按需加载为方法说明；Skill 文本本身不能授予工具、MCP 或文件访问权 |
| MCP | 服务器连接/启动 manifest、可发现工具 schema、超时与资源限制 | `mcp_client.py` 建立连接；每个 MCP 工具仍进入统一 ToolDispatch 授权与审计链 |
| Workflow | `workflow.toml` + 可选模板、步骤 schema | `workflow_runner.py` 校验 DAG 后调度；步骤指向 Agent/能力/工具/审批点，不能直接绕过 Runtime |

扩展引用统一采用 `publisher/id@version`，类型由配置字段区分，例如 `skills = ["abilities/research-brief@1.0.0"]`。运行开始时将解析结果及内容哈希固定在 `RunSpec`；任务执行中升级扩展不改变该次运行。配置引用不存在、版本不兼容、依赖缺失或风险策略被降低时，配置发布失败。

**安装流程：** 从批准的来源获取包 → 暂存目录 → 校验 manifest/schema、内容哈希、版本与依赖 → 列出所需权限和可执行代码 → 用户审批高风险扩展 → 原子安装到 `data/extensions/<type>/<publisher>/<id>/<version>/` → 登记版本 → 由用户显式启用并分配到 Agent/群配置。更新安装新版本，不覆盖旧版本；支持回滚和停用。外部包默认不自动更新。

`config/extensions.toml` 集中管理允许的来源、安装根目录、签名/哈希要求、最大包大小、MCP 连接超时、子进程 CPU/内存/网络限制、默认禁用策略和更新策略。MCP 凭证只存密钥管理层，manifest 存环境变量名或凭证引用。来自第三方的 Python Tool 或本地 MCP 进程必须在隔离环境执行；未经审查的 Skill 附带脚本不能因为读取 `SKILL.md` 就运行。

**三种 Runtime 的用法：** `AssistantRuntime` 可提议安装 Skill/MCP/Workflow，并按获准配置调用规划类 Skill 和 Workflow；`DirectChatRuntime` 只解析该好友配置中启用的扩展；`GroupChatRuntime` 解析群级 Workflow/共享 Skill，再按成员各自权限解析 Tool/MCP。群配置的允许列表是上限，不会把某成员缺少的权限补给他。Workflow 步骤通过三种 Runtime 或任务 worker 调用 `AgentExecutor`，所有外部副作用均需对应审批。

内置 Tool 提供计算器、文件操作、媒体处理、记忆检索、动态计划和 Skill 创建等能力；内置 Skill 仅保留 `skill-creator`。其他 Skill 由用户创建或安装，并在 Agent 配置中显式启用。内置 Workflow 的产品发布示例只引用小T和小V；MCP 先提供连接模板与客户端适配，实际外部服务器由用户连接后启用。每个内置包仍有独立 manifest、版本和测试。

Workflow 使用声明式 DAG，例如：

```toml
schema_version = 1
id = "product-launch"
version = "1.0.0"
entry = "research"

[[steps]]
id = "research"
kind = "agent_task"
capability = "research.web"
depends_on = []

[[steps]]
id = "design"
kind = "agent_task"
capability = "design.visual"
depends_on = ["research"]

[[steps]]
id = "review"
kind = "approval"
depends_on = ["design"]
```

加载器校验无环、步骤数与成本上限、能力/扩展引用和审批点；`approval` 步骤只能等待用户决定，不能由 Skill 文本或模型输出自动标记为通过。

## 4. 独立上下文模型

### 4.1 四种作用域

| 作用域 | 唯一键 | 内容 | 可读取者 |
| --- | --- | --- | --- |
| 小未对话 | `(workspace_id, "assistant", "assistant")` | 用户与小未的对话、计划摘要和待跟踪任务 | 用户、小未；其他 Agent 只能接收明确分派的任务材料 |
| Agent 私聊 | `(workspace_id, "agent", agent_id)` | 用户与该 Agent 的私聊消息、私有摘要、私有记忆 | 用户、该 Agent、经明确授权的小未任务 |
| 群聊 | `(workspace_id, "group", group_id)` | 群消息、群摘要、群共享记忆、群任务关联 | 用户、当前成员 Agent；离群成员不再获得新上下文 |
| 任务 | `(workspace_id, "task", task_id)` | 本任务输入、步骤产物、引用和审批快照 | 被分派的 Agent 仅可读取自己的步骤及明确共享的产物 |

小未对话、私聊、群聊、任务共用底层存储接口 `ContextStore`，但分别由 `AssistantContextService`、`AgentContextService`、`GroupContextService`、`TaskContextService` 处理。所有存取方法必须接收类型化 `ScopeKey`；禁止只用裸 `conversation_id` 查询。数据库为每条消息/摘要/记忆加 `workspace_id`、`scope_type`、`scope_id`，并建联合索引。仓储查询总是同时按三者过滤；应用层再检查成员和授权。

**建议表：** `context_messages`、`context_summaries`、`context_memories`、`context_shares`。消息表保存发送者、所属作用域、源消息 ID、可见性；摘要表保存覆盖的消息游标和版本；记忆表保存来源、有效期、删除标记；分享表保存来源/目标作用域、分享人、目的、过期时间与撤销状态。审批、任务和配置版本各有独立表，不与上下文混为一个 JSON 字段。

### 4.2 模型上下文组装

```text
与小未对话：
  assistant.toml 配置版本 + 小未对话最近消息 + 计划摘要/任务追踪 + 获准分享的产物

与 Agent 私聊：
  Agent 配置版本 + 私聊最近消息 + 该 Agent 私有摘要/记忆 + 当前任务授权材料

在群里 @Agent：
  Agent 配置版本 + 当前群最近消息 + 该群摘要/共享记忆 + 当前群任务材料
  （不加载 Agent 私聊历史和其他群历史）

小未分派跨会话任务：
  小未自身上下文 + 用户当前任务 + 经授权分享的产物摘要
  （不复制原始私聊全文到其他 Agent 或群）
```

`assembler.py` 先调用 `policy.py` 判定可见来源，再按预算组装；`retrieval.py` 的查询必须带作用域过滤。优先保留当前用户指令、审批约束和未完成步骤；旧消息由 `summarizer.py` 增量压缩，摘要保留源消息 ID 和版本，以便追溯。摘要不能改变消息的可见范围。引用私聊内容到群聊时，用户通过明确的“分享到群聊”动作生成 `context_shares`，只分享指定消息/产物，支持撤销与过期。

### 4.3 群成员变更与生命周期

- **加入群**：新成员默认可读取加入后的群消息。是否可读取加入前历史由群配置 `history_visibility` 决定；建议默认 `since_joined`，如需历史回放须由用户授权。
- **退出群**：停止获取新消息和新摘要；已生成的任务步骤仍按启动时的成员与配置快照执行或由用户取消重分派。
- **群归档**：群配置状态变为 archived，禁止新消息/任务；历史按保留策略只读保存。
- **Agent 归档**：不删除私聊记录；群配置中的该成员引用需先移除或替换，校验器阻止悬空引用。
- **删除/导出**：按作用域导出或删除消息、摘要、记忆和索引，异步清理派生缓存；保留必要审计记录但不能保留可恢复的被删除正文。

## 5. 配置变更和动态创建

### 5.1 创建流程

```mermaid
sequenceDiagram
  participant U as 用户/小未
  participant API as Agent/Group Service
  participant V as 配置校验器
  participant W as Config Writer
  participant DB as 数据库投影
  U->>API: 创建好友或群聊
  API->>V: 生成 TOML 草案并校验 ID/引用/权限
  alt 需要审批
    API-->>U: 返回草案和审批项
    U->>API: 批准精确配置
  end
  API->>W: 写临时文件、fsync、原子替换
  W-->>API: 文件哈希与版本
  API->>DB: 投影配置版本、创建上下文作用域、写 outbox
  API-->>U: 返回可用 Agent/群聊
```

文件是权威来源，数据库是可查询的投影。**不能在生产多实例里让每个 API Pod 写自己的本地目录。** 本地版可直接原子写入 `~/.FutureWork/agents/` 或 `~/.FutureWork/teams/`；生产版使用独立的可写配置仓库/配置服务，验证后提交版本，再由各实例同步。若文件写入成功而数据库事务失败，`reconciler.py` 根据文件哈希重建投影；若数据库中有未对应文件的临时草案，不将其视为 active。配置写入必须有文件锁/版本条件，避免并发覆盖。

### 5.2 编辑与审批

页面编辑 Agent 或群聊时提交 `expected_config_version`。服务端比较差异：模型/能力/成员/上下文策略/工具授权等是否扩大访问范围。低风险更新写新文件版本；高风险更新先存草案和审批，批准后才发布新文件版本。**不能在批准前直接修改 active 配置。** 任务步骤记录 `agent_config_version`、`group_config_version?` 和 `context_cursor`；执行过程中仅使用该快照。

## 6. 未来实现顺序

1. **建立逐文件配置。** 定义 `~/.FutureWork/agents/`、`~/.FutureWork/teams/`、`models.toml` 的 schema、内容哈希、版本冲突检查、加载与数据库投影；保留已有原型中的 Agent 和群名称。
2. **引入类型化上下文。** 消息和已读游标带 `scope_type`、`scope_id`、`workspace_id`，建立联合索引，所有查询改用 `ScopeKey`。检查无同名 ID 混淆和跨群读取。
3. **建立模型网关及三种 Runtime。** 按本文设计实现协议适配器、别名注册表、预算与错误映射；先验证 OpenAI 兼容平台及 Anthropic Messages，再按平台实际差异扩展。按会话类型实现 `AssistantRuntime`、`DirectChatRuntime`、`GroupChatRuntime`，共同复用 `AgentExecutor`。
4. **把群 Runtime 分成两种策略。** 先给 Team 配置增加 `mode` 与预算字段、数据库投影和版本固定，再实现 `SwarmPolicy` 的成员自治和 `ControlledPolicy` 的小未群内计划。页面应显示群模式并允许创建或编辑时选择；模式切换只影响新运行。
5. **实现配置写入闭环。** 手动创建、由小未创建、群聊创建及配置编辑都走同一个 writer + validator；高风险草案先审批。增加文件与投影对账、版本冲突和崩溃恢复测试。
6. **建立扩展注册与安装链。** 先实现内置 Tool/Skill/Workflow 的 manifest 校验和 Runtime 解析，再接 MCP 客户端；第三方安装须完成暂存、校验、权限审批、版本固定和隔离执行。
7. **最后替换运行基础设施。** 按 [系统设计](system-design.md) 引入 PostgreSQL、持久队列、用户鉴权和工具沙箱；上下文作用域与配置契约无需再改。

## 7. 必须通过的隔离测试

- 同一条用户消息按会话类型只进入对应 Runtime；小未对话、Agent 私聊和群聊分别写入自己的 `ScopeKey` 与 checkpoint。
- Agent A 私聊中出现的唯一标记，不得出现在 Agent B 私聊或任一群上下文的检索结果中。
- Agent A 加入群 X，不得因此读取自己私聊或群 Y 的摘要；群 X 新成员默认不得读取加入前历史。
- 小未把私聊产物分享至群 X 时，只能看到指定产物，撤销后检索结果中消失。
- 同时编辑同一 Agent 配置，旧 `expected_config_version` 必须返回冲突；旧审批不能激活新草案。
- 配置文件缺失、ID 与文件名不一致、群成员不存在、工具未注册、提示词路径越界，启动或发布必须失败且 active 版本保持不变。
- 安装 Skill 不得自动授予其声明的 Tool/MCP；未授权的 MCP 工具调用必须被 `ToolDispatch` 拒绝并写审计事件。
- 扩展升级后旧任务继续使用原版本；停用、回滚和依赖缺失不得让运行中的 Workflow 静默切换实现。
- 重启服务后从文件重建数据库投影，原有消息、审批和上下文摘要仍属于原作用域。
- 同一用户目录同时启用阿里云、DeepSeek、Kimi、MiniMax、OpenAI、OpenRouter 和 Claude 配置时，Agent 别名必须路由到正确平台与协议；密钥不得进入日志、配置回显或模型响应。Anthropic 的 system/content block 与 OpenAI 兼容消息、工具调用、usage、结束原因分别做契约测试。
- 模型别名不存在、平台失效、能力不支持、429/超时、预算耗尽和跨平台回退未授权时，应返回明确状态；不得自动把私有群消息发往未许可的平台。
- Swarm 群运行中不能产生小未中控计划；成员仅看到本群已提交消息，回应人数和轮次达上限后停止。Controlled 群由小未生成可审计计划，`@` 约束生效，小未不能读取个人助理私聊记忆；切换群模式后旧运行仍按原版本完成或取消。
