# FutureWork：由 Agent 好友组成的个人工作团队

FutureWork 是一个可以在本机安装和运行的 Agent 团队应用。界面采用好友、群聊和消息收件箱的组织方式：你与个人助理「小未」交谈，小未把任务分给擅长对应能力的 Agent 好友；好友之间也可以组成群聊。除了你，好友和群成员都是 Agent。

当前版本提供网页、桌面 App 入口、终端聊天入口、带密钥的无页面 API、SQLite 持久化、多平台模型调用、通用工具和两种群聊模式。小未、小T、小V、Codex、OpenClaw、Claude Code 和媒体群随首次初始化安装；其他 Agent 可通过本机 CLI、JSONL 进程协议或 HTTP 协议接入。文档中的“目标架构”仍包含后续能力；使用前请先阅读下文的[当前能力与边界](#当前能力与边界)。

## 目录导航

- [当前能力与边界](#当前能力与边界)
- [安装与首次运行](#安装与首次运行)
- [完全使用本地模型](#完全使用本地模型)
- [模型配置说明](#模型配置说明)
- [Agent 好友和群聊](#agent-好友和群聊)
- [工具、权限与审批](#工具权限与审批)
- [用户数据目录](#用户数据目录)
- [页面与接口](#页面与接口)
- [多种入口与外部 Agent 好友](#多种入口与外部-agent-好友)
- [开发、测试与常见问题](#开发测试与常见问题)

## 当前能力与边界

| 模块 | 当前实现 |
| --- | --- |
| 个人助理 | 小未与好友使用同一个 Agent loop。`delegate_task` 只向已有好友或群聊分派任务；创建好友用 `friend_create`，创建群聊用 `team_create`，两者调用前均需审批。简单问题由小未直接回答。 |
| 对话执行入口 | Web、无页面 API、桌面 App 和 CLI 都进入相同的 `RunParams → TaskFactory → TaskRuntime` 链；TaskRuntime 按会话目标路由，不预先分类聊天/任务。 |
| 对象调用链 | API 创建数据库、消息及配置服务，然后交给 `TaskRuntime`；`TaskRuntime` 一次性装配 `AgentRuntime`、`TeamRuntime`、工具审批和分派服务。API 通过其 `agent` 属性复用同一执行器。 |
| Agent 好友 | 每位好友由独立 TOML 定义，拥有自己的能力、权限和私聊历史；可选内置模型、Codex、OpenClaw、JSONL 进程或 HTTP 执行后端。 |
| 初始成员 | 全新用户目录预置小未、小T、小V、Codex、OpenClaw、Claude Code 和一个「媒体群」；外部 CLI 好友的实际调用依赖本机安装、账户和配置健康。 |
| 群聊 | `swarm` 模式由成员轮流响应；`controlled` 模式由小未逐次决定下一位成员；每位成员回复后，小未读取更新的群历史继续判断，最后向用户汇报。成员数和模型调用次数受群配置限制。群聊读取本群自己的历史。 |
| 模型 | 支持 OpenAI 兼容文本接口、Anthropic Messages 接口，以及 Bamboo 风格的公司 HTTP 模型代理；预置多家云平台与本地部署示例。只有选中的模型才需要可用。 |
| 工具 | 已接通计算、工作区文件读取/搜索/写入/编辑、Skill 读取、公共网页抓取与保存，以及需显式开启的命令执行；调用前复核该 Agent 的授权。 |
| 数据与记忆 | 消息、任务、审批、已读位置和事件保存在 SQLite；提交后的消息按小未、好友、群聊分别镜像为原始 JSONL，并生成有来源标记的 Markdown 经验。人物和群聊长期介绍保存在对应 TOML 旁边。 |
| 页面 | 支持好友与群聊切换、最近消息、全部消息、待审批筛选、Agent 配置和任务状态查看。 |

页面现在只列出有执行器的工具。`read_file`、`glob_files`、`grep_files` 是兼容旧配置的别名；新配置使用 `read`、`glob`、`grep`。模型运行时另有只读的 `memory_search`，按当前作用域检索记忆。图片理解、生成与编辑、文生视频、视频关键帧理解、本地裁剪与缩放、声明式 Agent Workflow 以及用户启用的 MCP stdio 工具已接入；浏览器自动化、BKN、LSP 和生成式视频编辑尚未接入。Skill 的 `SKILL.md` 可以作为 Agent 的方法说明加载到提示词中，但安装 Skill 不会自动授予工具。小未调用 `delegate_task` 时，分派的步骤在当前请求中执行并保存；重启时旧版未完成的分派任务会标记失败，不会盲目重放可能已生效的操作。

## 安装与首次运行

需要 Python 3.12 或更高版本。在仓库根目录执行：

```bash
python -m pip install -e .
futurework init
futurework doctor
futurework serve
```

`futurework init` 创建用户目录和缺失的初始配置；默认位置是 `~/.FutureWork/`。`futurework doctor` 检查 TOML 配置和外部 Agent 的本机 CLI 健康状态；执行器不可用时返回非零状态。它不会连接模型服务，也不保证模型 ID、账户余额或密钥有效。`futurework serve` 默认只监听 `127.0.0.1:8000`。浏览器打开 <http://127.0.0.1:8000/>；接口文档在 <http://127.0.0.1:8000/docs>。

### 关闭并重新启动服务

如果 `futurework serve` 正在当前终端前台运行，按 `Ctrl+C` 停止；等待出现 `Application shutdown complete` 后，再执行 `futurework serve`。

如果终端已经关闭，或启动时报 `address already in use`，先查看占用端口的进程：

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

确认输出的进程确实是要关闭的 FutureWork 服务后，记下 `PID` 列，用实际数字替换下面示例中的 `12345`，再重新启动：

```bash
kill -TERM 12345
futurework serve
```

如果此前用其他端口启动（例如 `8001`），把查询命令里的 `8000` 换成对应端口。不要仅凭端口号关闭不认识的进程；先检查 `COMMAND` 和 `PID`。密钥可填写在下述 `.env` 中，修改后重启服务。

`futurework init` 会生成权限为 `0600` 的 `~/.FutureWork/.env`。初始配置让小未和示例 Agent 使用 DeepSeek，可在该文件中填写：

```dotenv
DEEPSEEK_API_KEY=你的密钥
```

保存后运行 `futurework serve`；Web、App、API 和 CLI 入口都会自动读取所选用户目录的 `.env`。其中预列 DeepSeek、OpenAI、阿里云、Kimi、MiniMax、OpenRouter、Anthropic、MiMo、智谱、公司 HTTP 代理、无页面 API、Claude Code 和 Codex 等所需变量；用不到的项留空。显式设置在启动进程里的同名环境变量优先。密钥不要写入 `models.toml`、Agent TOML 或 Git。只使用下述本地模型时，无需配置 DeepSeek 密钥。

初始化和每次启动只会在 `.env` **末尾追加缺少的变量名**，不会删除或改写已有赋值。安装新 Skill、MCP 或配置新的模型变量后再次运行 `futurework init`；通过 `skill_create` 创建且说明中引用了新变量的 Skill 会立即把变量名追加到 `.env`。程序没有直接修改已有 `.env` 值的接口；已有值只能由用户本人编辑。将来若增加应用内修改入口，必须先提交审批，不能静默改值。`.env` 不提交仓库；修改后需重启服务。`FUTUREWORK_HOME` 决定去哪个目录找 `.env`，因此它应在启动命令的环境中或用 `--home` 指定，不能靠 `.env` 自己改变目录。

可以用 `FUTUREWORK_HOME` 指向另一个用户目录，也可以把 `--home` 放在命令前：

```bash
futurework --home /path/to/my-futurework init
futurework --home /path/to/my-futurework doctor
futurework --home /path/to/my-futurework serve
```

首次初始化只复制缺失的默认文件，**不会覆盖已有的 `~/.FutureWork/models.toml`、`app.toml` 或手写 Agent/Team 定义**。更新程序后若想使用新增模型别名，请手工合并示例配置。修改 TOML 后重启服务，使新配置进入下一次运行。

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

新用户目录已经包含以下配置；如果是旧用户目录，把相应表加入 `~/.FutureWork/models.toml`，或按实际端口、模型名修改已有表：

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

`remote_id` 必须是 Ollama 中实际存在的模型名；可以运行 `ollama list` 核对。接着把 `~/.FutureWork/agents/assistant.toml` 中的 `[model] id` 改为 `ollama_local`，让小未的聊天、任务分派工具调用和群中控也使用本地模型：

```toml
[model]
id = "ollama_local"
```

如果希望**新建 Agent 的默认模型**是 Ollama，把 `~/.FutureWork/app.toml` 中的 `[model] default_model` 改为 `ollama_local`。已有好友不会跟着改变；请逐个修改 `~/.FutureWork/agents/<好友ID>.toml` 的 `[model] id`，或者在页面为好友改模型。检查配置并重启：

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

将小未、已有好友或新建 Agent 的模型别名按上一节的方法改为 `vllm_local`。如果 vLLM 使用了 `--served-model-name`，`remote_id` 要与其公开的名称一致。若推理服务要求 Bearer 密钥，在 Provider 表中填写 `api_key_env = "你的环境变量名"`，并把 `allow_no_key` 设为 `false`；密钥仍由环境变量提供。

### 同时配置多个 Ollama 和 vLLM 服务

`models.toml` 的每个 `[providers.<名称>]` 对应一个服务地址，每个 `[models.<别名>]` 对应一个模型。可以同时配置多个本机端口，并让不同好友在各自 TOML 的 `[model] id` 选择不同别名。例如在 `~/.FutureWork/models.toml` 末尾追加：

```toml
[providers.ollama_second]
adapter = "openai_chat"
base_url = "http://127.0.0.1:11435/v1"
allow_no_key = true

[providers.vllm_code]
adapter = "openai_chat"
base_url = "http://127.0.0.1:8011/v1"
allow_no_key = true

[models.ollama_qwen3]
provider = "ollama_second"
remote_id = "qwen3:8b"
supports_tools = true

[models.vllm_coder]
provider = "vllm_code"
remote_id = "local-code"
supports_tools = true
```

然后给好友甲设置 `[model] id = "ollama_qwen3"`，给好友乙设置 `[model] id = "vllm_coder"`；小未也可以选择其中一个别名。`supports_tools` 必须与该服务的实际工具调用能力一致；小未若要调用分派、创建等工具，其模型必须支持工具调用。`8011` 只是示例端口，按实际 vLLM 端口填写。修改 `models.toml` 或手写好友 TOML 后重启 FutureWork；在运行中的页面或 API 创建好友时，可以直接选已加载的模型别名。

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

新用户目录内置以下示例；旧用户目录需手工把相应表加到 `~/.FutureWork/models.toml`：

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

切换小未及好友的方法与 Ollama 相同：将各自 TOML 的 `[model] id` 改为 `company_http_local`；将 `app.toml` 的 `[model] default_model` 改成该别名，会影响之后创建且未显式指定模型的 Agent。服务使用局域网明文 HTTP 时保留 `allow_insecure_http = true`；使用 HTTPS 可以设为 `false`。不要把公司真实端点、密钥或内部请求头提交到仓库。

## 模型配置说明

`~/.FutureWork/models.toml` 把**平台连接**和**模型别名**分开。`[providers.<名称>]` 指定协议适配器、接口地址、密钥环境变量；`[models.<别名>]` 指定平台、平台原生模型 ID 和工具能力。Agent 只引用模型别名。`openai_chat` 在 `base_url` 后接 `/chat/completions`，`anthropic_messages` 使用 Messages 协议，`http_provider` 则直接请求完整的 `base_url`。

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

这些是**可编辑的示例别名**，不是对第三方账号权限或模型可用性的保证。供应商若调整模型名、端点或参数，请修改对应 TOML。可以自行新增符合 OpenAI Chat Completions 协议的平台；`adapter = "openai_chat"` 即可复用现有适配器。公司代理使用上文所述的独立 `http_provider` 格式；其他任意自定义 HTTP 格式仍不支持。请求的超时、重试、温度和默认输出长度由 `~/.FutureWork/app.toml` 的 `[model]` 管理；模型条目还可以单独设置 `temperature`、`max_output_tokens`。图片、视频和视觉模型的当前能力见下文媒体能力说明。

## Agent 好友和群聊

小未由 `~/.FutureWork/agents/assistant.toml` 定义，其余好友分别由 `agents/<ID>.toml` 定义。文件名必须与配置中的 `id` 一致；例如 `research.toml` 中必须有 `id = "research"`。一个简化的好友配置：

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

用户在小未的聊天区发消息后，小未先进入与其他好友相同的 Agent loop。模型认为需要其他好友或群协作时，可调用 `delegate_task`，指定已有好友、已有群，或选择自动匹配。自动匹配按 `app.toml` 中的 `[[planner.rules]]` 关键词形成步骤，并依据 Agent 能力分值和 `[matching]` 阈值选择好友；缺少合适好友时只返回缺失的能力和建议配置，**不会暗中创建**。小未应先用 `friend_create` 创建并配置好友，再重新分派。需要新群聊时，用 `team_create` 指定已有好友 ID 和 `controlled` 或 `swarm` 模式，之后再分派。创建工具调用会显示审批，批准后才写配置。简单问题可以直接回答，不产生分派任务。

创建好友时可以指定 `name`、`role`、已配置的 `model` 别名、`tools` 列表、`skills` 列表和能力熟练度映射 `capabilities`；创建结果会写入 `~/.FutureWork/agents/<ID>.toml`，Skill 写入同一文件的 `[extensions] skills`。例如调用 `POST /api/v1/agents` 时提交：

```json
{"name":"本地研究员","role":"竞品研究","model":"ollama_qwen3","tools":["read","grep"],"skills":[],"capabilities":{"analysis.competitor":0.9}}
```

群聊可通过 `POST /api/v1/groups` 提交 `{"name":"研究群","member_ids":["好友ID"],"mode":"swarm"}`。`friend_create` 和 `team_create` 使用同一创建服务和配置校验；前者不能使用未在 `models.toml` 配置的模型或未安装的 Skill，后者只能选择已有且可用的好友。

每个群由 `~/.FutureWork/teams/<ID>.toml` 定义。群成员填写 Agent ID，不复制成员的模型或工具配置。`swarm` 没有中控；`controlled` 的 `[controller] agent_id` 必须是 `assistant`。示例：

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

当前消息执行链为 `POST /conversations/{id}/messages → RunParams → TaskFactory → TaskRuntime → AgentRuntime 或 TeamRuntime`。`RunParams` 包含入口来源、会话目标快照、消息正文及客户端消息 ID；工厂只按会话目标创建 `agent_chat`、`group_swarm` 或 `group_controlled` 三类 Task，不调用模型、不写数据库。小未和其他好友统一进入 AgentRuntime；小未选择调用 `delegate_task` 时才由工具执行层创建并运行持久任务。查询、配置修改和审批接口仍走各自的业务路径。

运行时依赖在启动时装配一次：API 先创建数据库、消息、配置和好友／群服务，TaskRuntime 在构造时统一初始化 AgentRuntime、TeamRuntime、审批和分派服务。TaskRuntime 负责幂等、持久化用户消息、路由和任务级错误处理；AgentRuntime 拥有小未与好友的同一套模型/工具 loop；TeamRuntime 持有 SwarmPolicy 或 GroupController 并调用成员的 AgentRuntime。`TaskPlanner` 只存在于 `delegate_task` 的执行服务中，由小未实际调用后才进行规则拆解和已有好友的能力匹配。模型网关按别名缓存适配器；Agent、Team 和 Task 各有独立的有限重试配置，工具执行层只自动重试可重放读类工具。全部重试次数和退避参数都在用户目录的 `runtime.toml`、`tools.toml` 与 `app.toml` 中。

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
| `delegate_task` | 向已有好友或群聊指派任务 | 只在小未私聊开放；能力缺失时返回建议，不创建配置。 |
| `friend_create` | 创建并配置 Agent 好友 | 只在小未私聊开放，指定模型、工具、Skill 和能力；调用前必须审批。 |
| `team_create` | 创建协作群聊 | 只在小未私聊开放，指定已有好友和 `controlled`／`swarm` 模式；调用前必须审批。 |
| `web_fetch` | 读取公共网页文本 | 拒绝本地/私有 IP，每次跳转重新检查目标地址，限制响应大小、跳转次数和时长；新增授权需要配置审批。 |
| `url_to_md` | 把公共网页可见文本保存为 Markdown | 仅保存至工作区；新增授权需要配置审批。 |
| `bash` | 在工作区目录执行 POSIX shell 命令 | 需 Agent 授权且 `[tool_runtime] allow_shell = true`；限制超时和回传输出。**当前没有操作系统沙箱**，开启后命令仍可能访问工作区外的本机资源。 |

默认工作区是 `~/.FutureWork/workspace/`。调整 `~/.FutureWork/app.toml` 的 `[tool_runtime] workspace` 可改变路径；同一配置表还控制工具轮数、每轮调用数、文件大小、网页大小、命令超时和输出长度。工具真正执行前会再次检查该 Agent 的 `tools` 授权。文件工具不能通过 `../` 或指向工作区外的符号链接读取外部文件。新建 Agent 的安全默认工具由 `app.toml [permissions] safe_default_tools` 控制；小未、小T、小V分别使用自己的 TOML 工具列表。已有用户目录中的自定义 Agent TOML 不会自动改写。

页面为好友增加 `write`、`edit`、`web_fetch`、`url_to_md` 或 `bash` 等高风险工具授权时会产生**配置变更审批**，批准后写回该好友 TOML。模型实际调用工具时，执行层再次检查 Agent ID、会话作用域和授权；`tools.toml [execution] require_approval_for` 列出的工具会产生**单次调用审批**，显示工具名和具体参数。当前默认包含 `write`、`edit`、`bash`、`url_to_md`、`schedule_create`、`skill_create`、`friend_create`、`team_create`、媒体生成、视频编辑和 MCP 调用等。用户在待审批区批准后，运行中的调用才继续；拒绝或超时不会执行。审批等待期间如果该 Agent 的授权被撤销，也不会执行。Agent 配置的 `approval = false` 可以跳过普通工具的单次调用审批，但 `friend_create` 和 `team_create` 始终需要审批；关闭普通工具审批本身需要走配置变更审批。手工编辑用户自己的 Agent TOML 也可以改变授权，重启后生效。`bash` 还必须额外在 `app.toml` 的 `[tool_runtime]` 中手工开启：

```toml
[tool_runtime]
allow_shell = true
```

只在你信任该 Agent 的模型与输入来源、了解命令能够影响本机文件和网络时启用。`bash` 子进程不会继承模型 API 密钥等环境变量，但这不构成文件系统沙箱。

### 工具执行层与失败重试

`runtime/tool_execution.py` 接收一条固定了调用 ID、Agent ID、作用域、工具名和参数的 `ToolCall`。它先按模型收到的 schema 检查必填字段、字段类型、额外字段与输入长度，再判断授权和是否需要审批。通过后调用 `abilities/tools/<工具名>/handler.py`，校验返回内容类型、结构化 JSON 的形状及输出长度；普通文本超长会截断，结构化 JSON 超长则报错，避免把截断后的非法 JSON 送回模型。每次结果写入当前小未、好友或群聊记忆目录的 `tool_calls.jsonl`，记录决策、调用 ID、参数哈希、尝试次数、各次失败类别和耗时；不在审计日志中复制完整入参。

Bamboo 的工具调用在超时、异常或返回失败时会记录审计并把错误交还 Agent，本身不立即重放该工具；其模型接口把 HTTP `408`、`429`、`5xx` 和传输错误标为可重试，任务层另有有限恢复预算。FutureWork 参考这一分类增加更严格的工具重试：HTTP `408`、`429`、`5xx`，网络连接/读取超时及指定的临时系统错误，属于暂时故障；HTTP `401`、`403`、普通 `4xx`、权限拒绝、审批拒绝、参数与输出校验错误不重试。即使是暂时故障，也只有 `tools.toml [execution] retry_read_tools` 中的可重放读类工具会自动重试；写文件、命令、定时任务创建等有副作用的调用不会重放，以免第一次已生效而第二次重复执行。`max_attempts`、退避间隔、单次调用超时、审批等待和输入输出上限都由该配置表控制。模型网关的重试另由 `app.toml [model]` 控制，两者相互独立。未连接审批存储的独立运行会拒绝需要单次审批的调用。

手工安装 Skill：把 `SKILL.md` 放在 `~/.FutureWork/skills/<技能ID>/`，然后在目标好友 TOML 中显式写入：

```toml
[extensions]
skills = ["技能ID"]
```

也可以把 Skill 放在 `~/.FutureWork/abilities/skills/<技能ID>/`；同名 Skill 按用户 `abilities/skills`、旧版 `skills`、包内内置 Skill 的顺序加载。重启后该好友的模型上下文会附加 Skill 文本；其他好友和群聊不会因此自动获得新权限。

MCP stdio 服务的定义放在 `~/.FutureWork/abilities/mcp/<服务ID>/manifest.toml`，设置 `id`、`enabled = true`、`command`、`args` 和可选的 `env = ["变量名"]`。在需要使用它的好友 TOML 的 `tools` 中显式加入 `mcp_list`、`mcp_call`，并在 `[extensions]` 中写 `mcp = ["服务ID"]`。模型先调用 `mcp_list` 获取服务公开的工具，再用 `mcp_call(server_id, tool_name, arguments)` 执行；调用前会验证服务属于该好友的启用列表，且工具确实在服务的 `tools/list` 中。两个调用默认都需单次人工审批，且不自动重试。服务进程的环境只带基础变量及 manifest 显式列出的变量，可从本机 Bamboo `.env` 同名变量读取；MCP 服务的启动、请求及结果大小受 `extensions.toml [mcp]` 控制。当前只支持本机 stdio 传输，不支持远程 HTTP MCP。

Workflow 可以放在 `~/.FutureWork/abilities/workflows/<ID>/workflow.toml`，旧版 `workflows/<ID>/workflow.toml` 也可用。当前支持 `enabled = true` 的声明式 `agent_task` 步骤，每步必须有 `id`、`agent_id`、`prompt` 和 `depends_on`；提示词支持 `{{input}}` 和直接依赖步骤的 `{{steps.<ID>}}`。调用 `POST /api/v1/workflows/<ID>/runs`，JSON 正文为 `{"input":"用户需求"}`。系统按依赖顺序调用已配置的 Agent Runtime，运行结果逐步保存到 `data/workflows/<运行ID>.json`，Agent 对话也会记录指令和回复。内置 `product_launch` 由小T制定主视觉方案，再由小V制定视频方案。可调节步骤数和输入输出上限在 `extensions.toml [workflow]`。暂不支持任意脚本步骤、MCP 步骤或并行 DAG 执行；Workflow 的 Agent 工具调用仍经过原有授权和审批层。

### 内置能力、Skill 创建与用户画像

包内 `src/futurework/abilities/` 统一存放六类内置资源：`tools/`、`skills/`、`mcp/`、`workflows/`、`friends/`、`teams/`。每个可用工具目录都有 `manifest.toml` 和真正执行的 `handler.py`，例如 `tools/read/handler.py` 读取工作区文件、`tools/grep/handler.py` 搜索内容、`tools/bash/handler.py` 执行受限命令、`tools/memory_search/handler.py` 执行分层记忆检索。网页抓取、网页转 Markdown、Skill 加载、计划更新/验收、定时任务创建/查询和用户画像追加也各有执行脚本；共享的路径约束与原子写入放在 `tools/common.py`，计划和定时任务持久化放在 `tools/management.py`、`tools/schedule.py`。`runtime/tool_dispatch.py` 负责工具 schema 和处理器分发；模型调用统一经过工具执行层。未实现的网页搜索占位工具已从内置工具目录移除。

全新初始化复制小未、小T、小V、Codex、OpenClaw、Claude Code 的好友配置和媒体群配置。随包提供的 Skill **只有 `skill-creator`**，小未默认加载它；小未可在用户提出创建可复用技能时调用 `skill_create`，经单次审批后写入 `~/.FutureWork/abilities/skills/<ID>/`。创建后不会自动授予任何 Agent 使用权，仍需在该 Agent TOML 的 `[extensions] skills` 中启用。Skill 的触发边界、目录结构和验收步骤参考 Bamboo 的 skill-creator，并针对 FutureWork 的权限和用户目录调整。`skill_create` 的名称和内容长度上限由 `extensions.toml [skill_creator]` 控制；创建或改进 Skill 的请求由小未直接处理，识别词可在 `app.toml [assistant_routing]` 调整。动态计划现在是 `plan_update`、`plan_check` 两个内置工具，不再是随包 Skill；计划按作用域和执行者存在 `data/plans/`。旧版小未若仍只引用已移除的 `dynamic_plan`，初始化会把该引用迁移为 `skill-creator` 并加入创建工具；其他自定义 Skill 不会被删除。升级自旧版本时，用户目录里已有的研究、设计等 TOML 和历史记录也不会被自动删除；若希望界面只保留三位默认 Agent，请先核对其会话与记忆，再自行移走旧示例配置并重启。

`user.md` 首次创建时为空。所有 Agent 的模型提示词都会读取其最多 500 字内容；模型可以调用 `user_profile_update` 追加用户明确表达的稳定信息和偏好，重复事实去重，超出上限拒绝写入。`context.toml [user_profile] max_chars` 可在 1～500 范围内调整。模型不支持工具调用时仍可读取画像，但不会自动更新。

`schedule_create` 支持带时区的 ISO 时间和可选重复间隔，`schedule_list` 查询状态。定时任务保存在 `data/schedules/`，服务运行期间按 `app.toml [schedule] poll_seconds` 扫描，到期后作为小未会话请求执行；服务停止期间不会执行，重新启动后会处理逾期任务。重复间隔不能短于 `min_interval_seconds`。定时任务执行仍依赖已配置的模型。

**媒体能力：** 小T默认使用文本模型调度 `image_analyze` 和 `media_generate`；前者把工作区图片或 HTTPS 图片传给配置的视觉模型，后者按 `image_generation`、`image_edit`、`video_generation` 选择媒体模型。小V默认可用 `media_generate` 文生视频、`video_analyze` 抽帧理解工作区视频、`video_edit` 用本机 FFmpeg 裁剪和缩放视频。媒体群可由小未分派给这两个好友。网页输入框的 `＋` 可以上传 PNG、JPEG、WebP、GIF、MP4、MOV 或 WebM；上传后输入框会插入工作区相对路径。图片与视频最大体积、抽帧数、处理超时和 FFmpeg 程序路径由 `media.toml [media]` 控制。视频分析需要系统安装 FFmpeg 和 FFprobe；编辑结果存于用户工作区 `outputs/`。图片编辑的 `image_url` 当前要求提供媒体平台可访问的 URL；本地上传路径仅供图片理解工具读取。

`models.toml` 已包含 Bamboo 对应的阿里云万相文生图、图片编辑、文生视频、OpenRouter 图片模型和阿里云 Qwen-VL 视觉模型。`media.toml [media.aliases]` 按能力选择模型别名。阿里云媒体任务使用异步提交和限时轮询，返回任务 ID 与结果 URL；OpenRouter 图片接口返回的 `b64_json` 会保存到 `~/.FutureWork/data/media/`，并提供 `/api/v1/artifacts/media/<文件名>` 供本地页面预览。FFmpeg 编辑产物可从 `/api/v1/artifacts/outputs/<文件名>` 预览。云平台若返回 URL，当前直接显示 URL，不自动下载远程文件。轮询超时会返回 `PENDING` 和任务 ID；可以在平台侧继续查询。视频理解基于少量关键帧，不能理解完整音轨和逐帧动作；视频编辑当前仅支持本地裁剪和可选缩放，不提供生成式重绘。

密钥解析顺序为对应进程环境变量、本机 `~/.bamboo/.env` 同名变量，再按 `providers.<平台>.bamboo_model` 指定的模型名读取 `~/.bamboo/configs/models.yaml` 的 `api_key`；该字段若为 `${变量名}`，会从进程环境或 Bamboo 的 `.env` 解析。读取只发生在调用模型时；FutureWork 仓库、用户 TOML 和 API 返回值都不保存该密钥。若你的 Bamboo 配置目录不同，请通过环境变量提供密钥。建议在多个模型使用不同账号时单独设置环境变量，避免同平台共用 Bamboo 模型的密钥。

## 用户数据目录

安装包的源码位于 `src/futurework/`，运行数据放在用户目录中。默认结构：

```text
~/.FutureWork/
├── app.toml                 # 服务、模型、规划、权限和工具运行参数
├── models.toml              # 平台实例与模型别名
├── user.md                  # 空白起始、最多 500 字的共享用户画像
├── agents/                 # assistant.toml/assistant.md，以及每位好友的 <id>.toml/<id>.md
├── teams/                  # 每个群聊的 <id>.toml/<id>.md
├── abilities/              # 用户自建能力：tools、skills、mcp、workflows、friends、teams
├── skills/                 # 人工安装的 Skill
├── workflows/              # 预留的 Workflow 定义
├── mcp/                    # 预留的 MCP 连接定义
├── workspace/              # 内置文件工具的默认工作区
├── memory/
│   ├── assistant/          # 小未私聊 messages.jsonl、experiences.md
│   ├── agents/<id>/        # 好友私聊 messages.jsonl、experiences.md
│   └── teams/<id>/         # 群聊 messages.jsonl、overview.md、topics/<话题>/<参与者>.md
├── data/                   # SQLite、plans/ 与 schedules/
├── logs/                   # 运行日志目录
└── cache/                  # 可重建缓存
```

首次初始化也会写入其他配置文件，例如 `tools.toml`、`matching.toml`、`planner.toml`、`runtime.toml`、`context.toml`、`extensions.toml`。它们中部分字段仍用于目标架构或后续扩展，不能仅凭目录存在判断功能已经完成。初始化时在用户目录生成的子目录说明文件是**用户本地文件**；仓库 GitHub 只跟踪根目录这一份 `README.md`。

默认目录名从旧版 `~/.futurework` 改为 `~/.FutureWork`。第一次执行 `futurework init` 或 `futurework serve` 时，如果新目录不存在且旧目录存在，会先复制旧目录（保留旧目录作为备份），再补齐缺失的内置配置。使用 `FUTUREWORK_HOME` 或 `--home` 时只作用于指定路径。`pip install -e .` 安装包和命令本身不会运行初始化钩子；安装后执行一次 `futurework init` 即可创建数据目录。`abilities/friends/*.toml`、`abilities/teams/*.toml` 可供用户新增好友与群配置，ID 不得与顶层 `agents/`、`teams/` 重复；修改后重启服务生效。

首次初始化会从 TOML 生成缺失的 `agents/<id>.md`、`teams/<id>.md` 人物或群聊长期介绍，包含角色、性格或协作职责等初始内容；以后可直接编辑 Markdown，程序不会覆盖。小未的介绍在 `agents/assistant.md`。小未每次调用模型时加载所有 Agent 和群聊的介绍全文；目前自动分派的 Agent 排名仍由能力分值规则决定。她在个人私聊中只读取自己的经验，在群中控时只读取当前群的经验。好友私聊只读取该好友的经验，群成员只读取该群的经验和自己的角色介绍，不能自动读取私聊经验。

`messages.jsonl` 保存 SQLite 已提交消息的完整原文、发送者、时间、消息 ID 和关联任务/审批 ID；群聊日志保留每个发言人的名字。Markdown 经验由当前版本按用户请求和 Agent 回复自动提取若干行，写入 `experiences.md` 或群聊的主题/参与者文件，并以 `source` 标记关联原消息；它是可编辑的简要记录，不是模型生成的深度反思。`overview.md` 索引群聊处理过的话题，主题目录的 `index.md` 索引参与者经验。启动时会补齐数据库中尚未镜像的消息，重复启动不会重复追加。`context.toml` 的 `[memory]` 表控制经验提取行数、长度、主题名长度和注入提示词的经验长度；原始 JSONL 不截断。介绍 Markdown 全文会进入小未提示词，维护时应控制其篇幅。

### 记忆检索与长上下文压缩

模型可调用 `memory_search(query, limit?, group_id?)`。小未和好友私聊先搜索各自的 `experiences.md`，没有相关命中再查各自的 `messages.jsonl`。群聊成员先查本群 `topics/*/<成员ID>.md`，再查 `overview.md` 和本群其他成员的经验文件；索引命中时会附带话题下的成员经验。仍未命中时，先查本人在本群的原始消息，再查本群全部原始消息。返回值是 JSON，包含命中层级、文件相对路径、内容、评分和可用的源消息 ID。好友私聊无法指定其他群；小未私聊只有明确指定已配置的群 ID 才能检索该群。当前检索为关键词匹配，不是向量语义搜索；中文用连续双字片段匹配。`context.toml [memory]` 中的 `search_*` 参数控制开关、文件/日志扫描量、结果数和长度。

运行时按当前模型别名的 `context_window`、`max_output_tokens`（未填写时用 `context.toml [compaction]` 的默认值）、完整消息和工具定义估算 Token。达到触发比例或剩余预算阈值时，保留最近消息与完整工具调用轮次，将更早的消息交给当前模型总结为一条摘要；模型失败时使用有限长度的原文摘录。摘要仅替换本次模型请求中的旧消息，不会修改 SQLite 历史或 `messages.jsonl`。压缩记录写入当前作用域的 `compactions.jsonl`，包含参与者、源消息 ID、原文哈希、摘要、方法和压缩前后估算量。小未、好友和群聊各有独立目录。`[compaction]` 提供触发比例、窗口默认值、输出预留、最近消息数量、压缩轮数和摘要长度等配置。估算器按 UTF-8 字节数估算，实际平台 Token 计数可能不同；如果固定的系统提示词或最近消息本身超过模型窗口，需要扩大模型窗口或缩短输入。

## 多种入口与外部 Agent 好友

四种入口使用同一套消息、任务、群聊和审批服务。Web 入口运行 `futurework serve`；桌面入口使用 `futurework app`，它在本机启动同一服务并用 pywebview 打开原生窗口。桌面依赖随 `pip install -e .` 一同安装。桌面版使用 `app.toml [server]` 中的端口；若端口已经被别的服务占用，先更换端口。桌面窗口与 Web 共享相同的用户目录和消息数据库。

终端单次对话使用：

```bash
futurework chat --conversation assistant --message "帮我梳理今天的工作"
futurework chat --conversation image --message "介绍你的职责"
```

无页面 API 使用 `futurework api` 启动，仍监听 `app.toml [server]` 指定的本机地址和端口，但不会挂载网页静态文件。启动前须设置 `FUTUREWORK_API_KEY`，或在 `app.toml [entrypoints.api]` 的 `key_env` 指定另一个环境变量名。所有业务接口都要求 `Authorization: Bearer <key>`。例如：

```bash
export FUTUREWORK_API_KEY="请设置一个随机长密钥"
futurework api
curl -H "Authorization: Bearer $FUTUREWORK_API_KEY" http://127.0.0.1:8000/api/v1/agents
```

Codex、OpenClaw 和 Claude Code 已作为内置好友安装，默认执行目录是 `~/.FutureWork/workspace/`。首次安装后运行 `futurework doctor` 并请求 `GET /api/v1/agents/<id>/health` 检查执行器；健康检查只验证 CLI 和配置，不代表模型账号有余额。当前内置 Codex profile 的模型别名为 `gpt-6.2-sol`，可以在 `~/.FutureWork/agent_backends.toml` 覆盖 `model`；默认 `workspace-write` 沙箱只能写其配置工作目录。用户自建好友仍是在 `~/.FutureWork/agents/` 写同名 TOML，再在 `agent_backends.toml` 定义 profile。下面展示一个自建的只读 Codex profile：

```toml
# ~/.FutureWork/agent_backends.toml
[profiles.local_codex]
executable = "codex"
workdir = "/绝对路径/已授权项目"
sandbox = "read-only"
timeout_seconds = 120
max_input_chars = 40000
max_output_bytes = 1000000
history_messages = 20
environment = ["PATH", "HOME", "LANG", "TMPDIR", "CODEX_HOME"]
```

```toml
# ~/.FutureWork/agents/coder.toml
schema_version = 1
id = "coder"
name = "代码助手"
role = "分析代码和给出修改建议"
kind = "friend"
status = "active"
[capabilities]
"engineering.code" = 0.95
[execution]
kind = "codex_cli"
profile = "local_codex"
```

OpenClaw 好友使用 `openclaw agent --local --json`，每次调用使用新的 OpenClaw session，FutureWork 只传当前私聊或群聊上下文，不加 `--deliver`，因此不会向外部聊天渠道发送结果。若 OpenClaw 使用 nvm 安装且启动进程的 Node 版本偏旧，执行器会优先使用 OpenClaw 可执行文件同目录的 Node；也可在 profile 填 `node_bin = "/绝对路径/node所在目录"`。本机 OpenClaw 配置和模型服务必须由 OpenClaw 自身验证通过。

Claude Code 好友使用本机 `claude -p --output-format json`，每次显式提供当前作用域上下文并关闭 Claude 会话持久化。默认 `acceptEdits` 模式只对配置的工作目录生效；其环境变量白名单包括 `ANTHROPIC_API_KEY`、`ANTHROPIC_AUTH_TOKEN` 和 `ANTHROPIC_BASE_URL`。使用前通过 `claude auth status` 检查账号，再发送一个简短请求验证模型服务与余额。

自编 Agent 可使用 `kind = "process"`：profile 填 `executable` 与 `arguments = ["/绝对路径/agent.py"]`。FutureWork 向标准输入写一行 JSON，包含 `protocol: futurework-agent-v1`、`agent_id`、`scope: {type,id}`、`message` 和当前会话的 `history`；进程从标准输出返回一行 `{"text":"回复内容"}`。HTTP Agent 使用 `kind = "http"`，profile 填固定的 `endpoint`，接收相同 JSON 并返回相同结构；明文 HTTP 仅允许环回地址，远端须使用 HTTPS。需要鉴权时填 `auth_env = "某环境变量名"`，请求会携带对应 Bearer 凭据。profile 可覆盖 `agent_backends.toml [defaults]` 中的超时、历史条数、输入和输出上限。Codex/OpenClaw/自编 Agent 都不会自动读取 FutureWork 的其他私聊或群聊历史，FutureWork 仅把当前作用域的有限历史传给它们。

外部进程以当前操作系统用户身份运行，因此可访问该用户本来有权访问的文件和网络。FutureWork 当前能限制传给外部 Agent 的上下文、工作目录、执行时间和返回大小，**不能把这些配置当作操作系统级文件或网络隔离**。请只配置可信的本机程序，并使用 Codex 自带的沙箱选项或自行在容器中运行外部程序。OpenClaw 和通用进程后端内部工具调用不会进入 FutureWork 的逐工具审批层。

## 页面与接口

页面左侧可以折叠好友和群聊；中央是当前会话；右侧可查看最近消息、展开全部对话或筛选待审批。打开小未或普通好友对话可以修改模型、工具和配置审批选项。小未的专属工具也会在抽屉中显示；高风险权限变化进入审批，批准后才生效。输入框中 Enter 换行或确认输入法候选词，Command/Ctrl + Enter 或点击发送按钮才会发送。前端正式资源打包在 `src/futurework/web/`，`frontend/` 保存早期静态设计原型。

主要接口都以 `/api/v1` 开头：

| 接口 | 用途 |
| --- | --- |
| `GET /health`、`GET /bootstrap` | 健康状态和页面初始化数据。 |
| `GET /agents`、`POST /agents`、`PATCH /agents/{id}` | 查看、创建和调整好友配置。 |
| `GET /conversations`、`GET/POST /conversations/{id}/messages` | 列出会话、读取和发送消息。 |
| `POST /groups` | 创建群聊。 |
| `GET /inbox?view=recent|all|approvals` | 最近消息、全部消息、待审批视图。 |
| `GET /approvals`、`POST /approvals/{id}/decision` | 查看并处理配置变更与单次工具调用审批。 |
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

**启动后提示缺少 `DEEPSEEK_API_KEY`：** 检查小未的 `agents/assistant.toml` 和正在参与回复的好友 TOML 是否仍引用 `default_fast`。只改 `app.toml` 的默认模型仅影响之后创建且未显式指定模型的 Agent。

**本地模型连接失败：** 先用 `curl <base_url>/models` 检查本地服务；核对端口、模型实际名称和服务绑定地址。FutureWork 默认使用 `8000`，示例 vLLM 使用 `8001`。局域网 HTTP 需要 `allow_insecure_http = true`。

**模型返回 404 或参数错误：** 检查 `remote_id` 是否与服务公开的模型名相同，以及服务是否提供 OpenAI 兼容的 `/v1/chat/completions`。默认本地示例关闭工具调用；如果本地模型不支持工具协议，不要把 `supports_tools` 改为 `true`。

**改了 TOML 却没有生效：** 当前配置在服务启动时读取；运行 `futurework doctor` 检查，再重启 `futurework serve`。用户目录现有文件不会因升级自动覆盖。

**工具没有执行：** 检查 Agent TOML 的 `tools` 列表、模型的 `supports_tools` 和本地模型是否真的支持工具调用。`skill_load` 还要求对应 Skill 已在该 Agent 的 `[extensions]` 启用；`bash` 额外要求 `allow_shell = true`。旧用户目录若仍在 `app.toml` 里保存中文占位工具名，页面会自动过滤这些未实现的名称。
