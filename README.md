# FutureWork

本地可运行的 Agent Team 第一版。页面、Python API、SQLite 消息持久化、规则分派、自动创建 Agent、群聊、配置审批和 SSE 更新已接通。

## 安装与启动

需要 Python 3.12 或更高版本。在项目根目录执行：

```bash
python -m pip install -e .
futurework init
futurework serve
```

`pip install -e .` 安装程序；首次执行 `futurework init` 或 `futurework serve` 时创建 `~/.futurework`。`futurework paths` 查看实际目录。打开 <http://127.0.0.1:8000/>；API 文档在 <http://127.0.0.1:8000/docs>。

可用 `FUTUREWORK_HOME=/path/to/directory` 或 `futurework --home /path/to/directory serve` 选择独立用户目录。测试可安装 `pip install -e '.[test]'` 后执行 `pytest`。

## 用户目录

```text
~/.futurework/
├── app.toml              # 服务、模型、分派算法、权限和界面参数
├── agents/               # 每位 Agent 一份 <id>.toml；assistant.toml 为小未
├── teams/                # 每个群聊一份 <id>.toml
├── skills/               # 人工安装的技能目录，内部使用 SKILL.md
├── workflows/            # 人工编写的工作流 TOML
├── mcp/                  # MCP 配置 TOML
├── memory/
│   ├── assistant/
│   ├── agents/
│   └── teams/
├── data/                 # SQLite 数据库
├── logs/
└── cache/
```

首次初始化复制内置示例配置。Agent 和 Team 文件是定义来源；启动时加载并校验，再同步到 SQLite。新建 Agent、自动创建 Agent、创建群聊，以及批准或直接修改 Agent 配置，都会写回对应 TOML。手工修改 TOML 后重启服务生效；删除文件会在下次启动时将对应数据库条目标记为归档，历史消息仍保留。文件名必须与文件内 `id` 相同。`app.toml` 修改后也需要重启。

`skills/`、`workflows/`、`mcp/` 目前只提供目录和配置发现能力；执行器尚未接入。`memory/` 已预留独立目录，当前消息历史保存在 SQLite，尚未从记忆文件读取内容。

模型密钥使用环境变量，变量名由 `app.toml` 的 `model.api_key_env` 指定；程序不自动读取 `.env`。默认 `mock` 模型无需密钥，任务停在已分派状态。配置兼容 OpenAI Chat Completions 的服务后可生成步骤初稿，尚不执行外部工具。当前服务只绑定本机，未实现账号鉴权，不适合直接对公网部署。

未来完整架构见 [系统设计文档](docs/system-design.md) 和 [工程目录设计](docs/project-structure.md)。
