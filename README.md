# FutureWork：由 Agent 好友组成的个人工作团队

FutureWork 是一个可以在本机安装和运行的 Agent 团队应用。界面采用好友、群聊和消息收件箱的组织方式：你与个人助理「小未」交谈，小未把任务分给擅长对应能力的 Agent 好友；好友之间也可以组成群聊。除了你，好友和群成员都是 Agent。

本项目仍在开发中。当前版本已经有可运行的网页、Python API、SQLite 持久化、多平台文本模型调用、基础工具调用和两种群聊模式。文档中的“目标架构”包含尚未完成的能力；使用前请先阅读下文的[当前能力与边界](#当前能力与边界)。

## 目录导航

- [当前能力与边界](#当前能力与边界)
- [安装与首次运行](#安装与首次运行)
- [完全使用本地模型](#完全使用本地模型)
- [模型配置说明](#模型配置说明)
- [Agent 好友和群聊](#agent-好友和群聊)
- [工具、权限与审批](#工具权限与审批)
- [用户数据目录](#用户数据目录)
- [页面与接口](#页面与接口)
- [开发、测试与常见问题](#开发测试与常见问题)

## 当前能力与边界

| 模块 | 当前实现 |
| --- | --- |
| 个人助理 | 「小未」区分聊天和任务；任务按配置的关键词拆分、匹配 Agent，缺少对应能力时创建 Agent 配置并分派。 |
| Agent 好友 | 每位好友由独立 TOML 定义，拥有自己的模型、能力、工具授权和私聊历史。 |
| 群聊 | `swarm` 模式由成员轮流响应；`controlled` 模式由小未选择成员，必要时汇总多人回复。群聊读取本群自己的历史。 |
| 模型 | 支持 OpenAI 兼容文本接口、Anthropic Messages 接口，以及 Bamboo 风格的公司 HTTP 模型代理；预置多家云平台与本地部署示例。只有选中的模型才需要可用。 |
| 工具 | 已接通计算、工作区文件读取/搜索/写入/编辑、Skill 读取、公共网页抓取与保存，以及需显式开启的命令执行；调用前复核该 Agent 的授权。 |
| 数据 | 消息、任务、审批、已读位置和事件保存在 SQLite；Agent 和 Team 定义保存在用户目录的 TOML。 |
| 页面 | 支持好友与群聊切换、最近消息、全部消息、待审批筛选、Agent 配置和任务状态查看。 |

页面现在只列出有执行器的工具。`read_file`、`glob_files`、`grep_files` 是兼容旧配置的别名；新配置使用 `read`、`glob`、`grep`。浏览器自动化、BKN、LSP、Workflow、MCP、图像和视频模型、持久任务队列、完整记忆检索尚未接入。Skill 的 `SKILL.md` 可以作为 Agent 的方法说明加载到提示词中，但安装 Skill 不会自动授予工具。任务初稿由当前服务进程的后台任务生成；服务在生成中退出时，需要人工检查任务状态。

## 安装与首次运行

需要 Python 3.12 或更高版本。在仓库根目录执行：

```bash
python -m pip install -e .
futurework init
futurework doctor
futurework serve
```

`futurework init` 创建用户目录和缺失的初始配置；默认位置是 `~/.futurework/`。`futurework doctor` 检查 TOML 引用和部分配置约束，不会连接模型服务，也不保证模型 ID 或密钥有效。`futurework serve` 默认只监听 `127.0.0.1:8000`。浏览器打开 <http://127.0.0.1:8000/>；接口文档在 <http://127.0.0.1:8000/docs>。

初始配置让小未和示例 Agent 使用 DeepSeek。如果使用云端 DeepSeek，先在**启动 FutureWork 的同一个终端**设置环境变量，再运行服务：

```bash
export DEEPSEEK_API_KEY="你的密钥"
futurework serve
```

密钥只从环境变量读取，不应写进 `models.toml`、Agent TOML 或 Git。使用其他云平台时，设置相应平台的密钥环境变量。只使用下述本地模型时，无需配置 DeepSeek 密钥。

可以用 `FUTUREWORK_HOME` 指向另一个用户目录，也可以把 `--home` 放在命令前：

```bash
futurework --home /path/to/my-futurework init
futurework --home /path/to/my-futurework doctor
futurework --home /path/to/my-futurework serve
```

首次初始化只复制缺失的默认文件，**不会覆盖已有的 `~/.futurework/models.toml`、`app.toml` 或手写 Agent/Team 定义**。更新程序后若想使用新增模型别名，请手工合并示例配置。修改 TOML 后重启服务，使新配置进入下一次运行。

## 完全使用本地模型

本地部署支持 Ollama、vLLM 的 OpenAI 兼容接口，以及下文的公司 HTTP 模型代理。Ollama 和 vLLM 使用 `/v1/chat/completions`，也可以接入实现该接口的其他本地推理服务。默认 Ollama/vLLM 示例不发送 `Authorization` 请求头，也不需要云平台密钥。

### 方案一：Ollama

先安装 Ollama，然后在终端准备模型和服务。若 Ollama 已作为系统服务运行，无需再次执行 `ollama serve`。

```bash
ollama pull qwen2.5:7b
ollama serve
```

在另一个终端确认兼容接口可以访问：

```bash
curl http://127.0.0.1:11434/v1/models
```

新用户目录已经包含以下配置；如果是旧用户目录，把相应表加入 `~/.futurework/models.toml`，或按实际端口、模型名修改已有表：

```toml
[providers.ollama]
adapter = "openai_chat"
base_url = "http://127.0.0.1:11434/v1"
allow_no_key = true
allow_insecure_http = false

[models.ollama_local]
provider = "ollama"
remote_id = "qwen2.5:7b"
supports_tools = false
```

`remote_id` 必须是 Ollama 中实际存在的模型名；可以运行 `ollama list` 核对。接着把 `~/.futurework/agents/assistant.toml` 中的 `[model] id` 改为 `ollama_local`，让小未的聊天、任务判断和群中控也使用本地模型：

```toml
[model]
id = "ollama_local"
```

如果希望**自动新建的 Agent**也默认使用 Ollama，把 `~/.futurework/app.toml` 中的 `[model] default_model` 改为 `ollama_local`。已有好友不会跟着改变；请逐个修改 `~/.futurework/agents/<好友ID>.toml` 的 `[model] id`，或者在页面为好友改模型。检查配置并重启：

```bash
futurework doctor
futurework serve
```

小未和所有会参与的好友都选用本地别名后，正常对话不需要 `DEEPSEEK_API_KEY`。本地模型本身仍需有足够资源运行，并能按 OpenAI Chat Completions 格式返回文本。

### 方案二：vLLM

安装与模型下载由 vLLM 自身负责。以下示例把 vLLM 放在 `8001` 端口，避开 FutureWork 默认的 `8000` 端口：

```bash
vllm serve Qwen/Qwen2.5-7B-Instruct --host 127.0.0.1 --port 8001
curl http://127.0.0.1:8001/v1/models
```

新用户目录中的对应配置为：

```toml
[providers.vllm]
adapter = "openai_chat"
base_url = "http://127.0.0.1:8001/v1"
allow_no_key = true
allow_insecure_http = false

[models.vllm_local]
provider = "vllm"
remote_id = "Qwen/Qwen2.5-7B-Instruct"
supports_tools = false
```

将小未、已有好友和自动新建 Agent 的模型别名按上一节的方法改为 `vllm_local`。如果 vLLM 使用了 `--served-model-name`，`remote_id` 要与其公开的名称一致。若推理服务要求 Bearer 密钥，在 Provider 表中填写 `api_key_env = "你的环境变量名"`，并把 `allow_no_key` 设为 `false`；密钥仍由环境变量提供。

### 局域网或容器中的推理服务

推理服务运行在另一台局域网机器、容器或 `host.docker.internal` 上时，把 `base_url` 改为客户端实际能访问的地址。非环回地址使用明文 HTTP 必须显式开启 `allow_insecure_http = true`，例如：

```toml
[providers.office_ollama]
adapter = "openai_chat"
base_url = "http://192.168.1.20:11434/v1"
allow_no_key = true
allow_insecure_http = true

[models.office_local]
provider = "office_ollama"
remote_id = "qwen2.5:7b"
supports_tools = false
```

这项开关只允许用户明确配置的非加密 HTTP 地址；跨机器传输可能被所在网络观察，能提供 HTTPS 时优先使用 HTTPS。服务绑定在 `0.0.0.0` 时，客户端仍应填写可访问的具体 IP 或主机名。修改后运行 `futurework doctor`，再用 `/v1/models` 检查地址及模型名。

本地示例把 `supports_tools` 设为 `false`，因为不同模型和服务对工具调用的支持不一致。只有在本地服务确实支持 OpenAI 兼容 `tools`/`tool_calls` 请求与响应时，才把它改为 `true`；否则文本对话仍可用，但不会调用内置工具。

### 方案三：公司 HTTP 模型代理

如果公司模型使用 Bamboo 的 `http_provider.py` 协议，应选用 `adapter = "http_provider"`，而非 `openai_chat`。此协议把 `base_url` 当作**完整 POST 地址**，不会自动拼接 `/chat/completions`；请求外层是 `model`、`request`、`timeout`，其中 `request.messages` 的文本内容是 `[{"type":"text","text":"..."}]` 格式。响应既可直接返回 Chat Completion，也可用 `result` 包住它；适配器同时识别 `success`、`code`、`errorCode` 业务状态和工具调用。

新用户目录内置以下示例；旧用户目录需手工把相应表加到 `~/.futurework/models.toml`：

```toml
[providers.company_http]
adapter = "http_provider"
base_url = "${HTTP_PROVIDER_BASE_URL}"
api_key_env = "HTTP_PROVIDER_API_KEY"
allow_insecure_http = true

[models.company_http_local]
provider = "company_http"
remote_id = "local_openai-gpt-5.2-chat"
supports_tools = false
temperature = 1.0
max_output_tokens = 4096
timeout_seconds = 60

[models.company_http_local.extra_body]
timeout = 30
```

运行前在启动 FutureWork 的终端设置公司代理的**完整地址**和访问密钥：

```bash
export HTTP_PROVIDER_BASE_URL="https://公司代理的完整请求地址"
export HTTP_PROVIDER_API_KEY="你的访问密钥"
futurework doctor
futurework serve
```

上面的地址只是填写位置，不是实际可访问地址。`HTTP_PROVIDER_BASE_URL` 只有选用该模型时才会读取；`futurework doctor` 可在未设置公司环境变量时检查其他配置。实际 `remote_id` 应按公司服务要求修改；当前示例会按 Bamboo 的规则将开头的 `local_` 去掉后发送。模型如需额外请求字段，可在 `[models.company_http_local.extra_body.request]` 下填写；如需额外请求头，可在 `[providers.company_http.extra_headers]` 或 `[models.company_http_local.extra_headers]` 下填写。请求头的值也可以写成完整的 `${环境变量名}` 引用，使用时再解析。只有公司服务支持同样的工具调用格式时，才把 `supports_tools` 设为 `true`。

切换小未及好友的方法与 Ollama 相同：将各自 TOML 的 `[model] id` 改为 `company_http_local`；将 `app.toml` 的 `[model] default_model` 改成该别名，才会影响之后自动创建的 Agent。服务使用局域网明文 HTTP 时保留 `allow_insecure_http = true`；使用 HTTPS 可以设为 `false`。不要把公司真实端点、密钥或内部请求头提交到仓库。

## 模型配置说明

`~/.futurework/models.toml` 把**平台连接**和**模型别名**分开。`[providers.<名称>]` 指定协议适配器、接口地址、密钥环境变量；`[models.<别名>]` 指定平台、平台原生模型 ID 和工具能力。Agent 只引用模型别名。`openai_chat` 在 `base_url` 后接 `/chat/completions`，`anthropic_messages` 使用 Messages 协议，`http_provider` 则直接请求完整的 `base_url`。

| 平台或示例 | 默认别名 | 密钥环境变量 |
| --- | --- | --- |
| DeepSeek | `default_fast`、`deepseek_chat` | `DEEPSEEK_API_KEY` |
| Kimi | `kimi_k3` | `MOONSHOT_API_KEY` |
| MiniMax | `minimax_m3` | `MINIMAX_API_KEY` |
| 小米 MiMo | `mimo_default` | `MIMO_API_KEY` |
| OpenAI GPT | `gpt_default` | `OPENAI_API_KEY` |
| Claude | `claude_default` | `ANTHROPIC_API_KEY` |
| 阿里云千问 | `aliyun_qwen_plus` | `DASHSCOPE_API_KEY` |
| 智谱 | `zhipu_glm` | `ZHIPU_API_KEY` |
| OpenRouter | `openrouter_default` | `OPENROUTER_API_KEY` |
| Ollama | `ollama_local` | 默认不需要 |
| vLLM | `vllm_local` | 默认不需要 |
| 公司 HTTP 代理 | `company_http_local` | `HTTP_PROVIDER_API_KEY`；地址由 `HTTP_PROVIDER_BASE_URL` 提供 |

这些是**可编辑的示例别名**，不是对第三方账号权限或模型可用性的保证。供应商若调整模型名、端点或参数，请修改对应 TOML。可以自行新增符合 OpenAI Chat Completions 协议的平台；`adapter = "openai_chat"` 即可复用现有适配器。公司代理使用上文所述的独立 `http_provider` 格式；其他任意自定义 HTTP 格式仍不支持。请求的超时、重试、温度和默认输出长度由 `~/.futurework/app.toml` 的 `[model]` 管理；模型条目还可以单独设置 `temperature`、`max_output_tokens`。当前实现只有文本模型请求，图像/视频生成以及视觉输入不在此版本范围内。

## Agent 好友和群聊

小未由 `~/.futurework/agents/assistant.toml` 定义，其余好友分别由 `agents/<ID>.toml` 定义。文件名必须与配置中的 `id` 一致；例如 `research.toml` 中必须有 `id = "research"`。一个简化的好友配置：

```toml
schema_version = 1
id = "research"
name = "知知"
role = "研究与洞察"
kind = "friend"
status = "active"
tools = ["calculator"]

[model]
id = "ollama_local"

[capabilities]
"research.web" = 0.9
```

用户在小未的聊天区发消息时，系统先判断是聊天还是任务。任务按 `app.toml` 中的 `[[planner.rules]]` 关键词形成步骤，再依据 Agent 能力分值和 `[matching]` 阈值选择好友；缺少合适好友时创建新的 TOML 文件并给予最小默认权限。该过程是当前版本的规则规划与模型协作，不是通用的自主多步规划引擎。

每个群由 `~/.futurework/teams/<ID>.toml` 定义。群成员填写 Agent ID，不复制成员的模型或工具配置。`swarm` 没有中控；`controlled` 的 `[controller] agent_id` 必须是 `assistant`。示例：

```toml
schema_version = 1
id = "launch"
name = "产品发布小组"
status = "active"
members = ["design", "write", "plan"]
mode = "controlled"

[reply]
max_responders_per_round = 3
max_rounds = 2
max_total_model_calls = 8

[controller]
agent_id = "assistant"
```

小未私聊、好友私聊与群聊分别读取各自的会话历史。群里的成员回复留在群会话中，不会写进对应好友的私聊。执行层将单次 Agent 身份、会话历史、模型别名和工具授权组成 `AgentRun` 对象，再通过 `ModelRequest`、`ModelResult`、`ToolRequest` 和 `ToolResult` 对象传递模型与工具数据。HTTP、TOML 和 SQLite 边界使用普通映射，进入运行层时转换为对象。

## 工具、权限与审批

| 工具名 | 能力 | 约束 |
| --- | --- | --- |
| `calculator` | 基础算术 | 只解析受限算术表达式，不执行 Python 代码。 |
| `read` | 读取 UTF-8 文本文件 | 仅在配置的工作区内读取，支持起始行与行数限制。 |
| `glob` | 按文件名模式枚举文件 | 仅在工作区内搜索，限制扫描量和返回数量。 |
| `grep` | 在工作区文本中查找正则表达式 | 限制单文件大小、扫描量和返回长度。 |
| `write` | 创建或覆盖 UTF-8 文件 | 只能写入工作区，使用原子替换；新增授权需要配置审批。 |
| `edit` | 精确替换已有文件的文本 | 支持一次替换与多处全量匹配替换；新增授权需要配置审批。 |
| `skill_load` | 读取完整 Skill 说明 | 只读取当前 Agent 已在 `[extensions]` 启用的 Skill。 |
| `web_fetch` | 读取公共网页文本 | 拒绝本地/私有 IP，每次跳转重新检查目标地址，限制响应大小、跳转次数和时长；新增授权需要配置审批。 |
| `url_to_md` | 把公共网页可见文本保存为 Markdown | 仅保存至工作区；新增授权需要配置审批。 |
| `bash` | 在工作区目录执行 POSIX shell 命令 | 需 Agent 授权且 `[tool_runtime] allow_shell = true`；限制超时和回传输出。**当前没有操作系统沙箱**，开启后命令仍可能访问工作区外的本机资源。 |

默认工作区是 `~/.futurework/workspace/`。调整 `~/.futurework/app.toml` 的 `[tool_runtime] workspace` 可改变路径；同一配置表还控制工具轮数、每轮调用数、文件大小、网页大小、命令超时和输出长度。工具真正执行前会再次检查该 Agent 的 `tools` 授权。文件工具不能通过 `../` 或指向工作区外的符号链接读取外部文件。新建 Agent 和初始示例 Agent 默认拥有 `calculator`、`read`、`glob`、`grep`、`skill_load`；已有用户目录中的 Agent TOML 不会自动改写。

页面为好友增加 `write`、`edit`、`web_fetch`、`url_to_md` 或 `bash` 等高风险工具授权时会产生**配置变更审批**，批准后写回该好友 TOML。现阶段没有每次工具调用单独弹窗审批；已经授权的工具会在模型请求时直接执行。手工编辑用户自己的 Agent TOML 也可以改变授权，重启后生效。`bash` 还必须额外在 `app.toml` 的 `[tool_runtime]` 中手工开启：

```toml
[tool_runtime]
allow_shell = true
```

只在你信任该 Agent 的模型与输入来源、了解命令能够影响本机文件和网络时启用。`bash` 子进程不会继承模型 API 密钥等环境变量，但这不构成文件系统沙箱。

手工安装 Skill：把 `SKILL.md` 放在 `~/.futurework/skills/<技能ID>/`，然后在目标好友 TOML 中显式写入：

```toml
[extensions]
skills = ["技能ID"]
```

重启后该好友的模型上下文会附加 Skill 文本；其他好友和群聊不会因此自动获得新权限。`~/.futurework/workflows/` 与 `~/.futurework/mcp/` 已预留配置位置，但执行器尚未接入。

## 用户数据目录

安装包的源码位于 `src/futurework/`，运行数据放在用户目录中。默认结构：

```text
~/.futurework/
├── app.toml                 # 服务、模型、规划、权限和工具运行参数
├── models.toml              # 平台实例与模型别名
├── agents/                 # 每位 Agent 好友的 TOML；assistant.toml 是小未
├── teams/                  # 群聊 TOML
├── skills/                 # 人工安装的 Skill
├── workflows/              # 预留的 Workflow 定义
├── mcp/                    # 预留的 MCP 连接定义
├── workspace/              # 内置文件工具的默认工作区
├── memory/                 # 按助理、好友和群预留的独立记忆目录
├── data/                   # SQLite 与其他运行数据
├── logs/                   # 运行日志目录
└── cache/                  # 可重建缓存
```

首次初始化也会写入其他配置文件，例如 `tools.toml`、`matching.toml`、`planner.toml`、`runtime.toml`、`context.toml`、`extensions.toml`。它们中部分字段仍用于目标架构或后续扩展，不能仅凭目录存在判断功能已经完成。初始化时在用户目录生成的子目录说明文件是**用户本地文件**；仓库 GitHub 只跟踪根目录这一份 `README.md`。

## 页面与接口

页面左侧可以折叠好友和群聊；中央是当前会话；右侧可查看最近消息、展开全部对话或筛选待审批。打开好友对话可以修改模型、工具和配置审批选项。前端正式资源打包在 `src/futurework/web/`，`frontend/` 保存早期静态设计原型。

主要接口都以 `/api/v1` 开头：

| 接口 | 用途 |
| --- | --- |
| `GET /health`、`GET /bootstrap` | 健康状态和页面初始化数据。 |
| `GET /agents`、`POST /agents`、`PATCH /agents/{id}` | 查看、创建和调整好友配置。 |
| `GET /conversations`、`GET/POST /conversations/{id}/messages` | 列出会话、读取和发送消息。 |
| `POST /groups` | 创建群聊。 |
| `GET /inbox?view=recent|all|approvals` | 最近消息、全部消息、待审批视图。 |
| `GET /approvals`、`POST /approvals/{id}/decision` | 查看并处理配置审批。 |
| `GET /tasks/{id}` | 查看任务和步骤状态。 |
| `GET /events` | 服务发送事件流，用于页面更新。 |

发送消息需要提供 `client_message_id`，以便重复请求按 ID 识别。完整请求结构和实时参数以运行服务后的 <http://127.0.0.1:8000/docs> 为准。详细设计分别见 [系统设计文档](docs/system-design.md) 和 [工程目录设计](docs/project-structure.md)；这两份文档包含目标方案，现有实现以本 README 的能力表和代码为准。

## 开发、测试与常见问题

在仓库根目录安装测试依赖并运行测试：

```bash
python -m pip install -e '.[test]'
python -m pytest -q
```

测试使用临时用户目录和模拟 HTTP 响应，不需要真实云平台密钥，也不会自动下载 Ollama/vLLM 模型。要预览早期静态设计原型，可在仓库根目录运行 `python -m http.server 4173`，然后打开 <http://127.0.0.1:4173/frontend/>。

**启动后提示缺少 `DEEPSEEK_API_KEY`：** 检查小未的 `agents/assistant.toml` 和正在参与回复的好友 TOML 是否仍引用 `default_fast`。只改 `app.toml` 的默认模型仅影响后来自动创建的 Agent。

**本地模型连接失败：** 先用 `curl <base_url>/models` 检查本地服务；核对端口、模型实际名称和服务绑定地址。FutureWork 默认使用 `8000`，示例 vLLM 使用 `8001`。局域网 HTTP 需要 `allow_insecure_http = true`。

**模型返回 404 或参数错误：** 检查 `remote_id` 是否与服务公开的模型名相同，以及服务是否提供 OpenAI 兼容的 `/v1/chat/completions`。默认本地示例关闭工具调用；如果本地模型不支持工具协议，不要把 `supports_tools` 改为 `true`。

**改了 TOML 却没有生效：** 当前配置在服务启动时读取；运行 `futurework doctor` 检查，再重启 `futurework serve`。用户目录现有文件不会因升级自动覆盖。

**工具没有执行：** 检查 Agent TOML 的 `tools` 列表、模型的 `supports_tools` 和本地模型是否真的支持工具调用。`skill_load` 还要求对应 Skill 已在该 Agent 的 `[extensions]` 启用；`bash` 额外要求 `allow_shell = true`。旧用户目录若仍在 `app.toml` 里保存中文占位工具名，页面会自动过滤这些未实现的名称。
