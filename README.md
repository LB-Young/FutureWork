# FutureWork

`frontend/` 保留静态设计原型；运行中的页面打包在 `src/futurework/web/`。当前版本已接通小未任务分派、Agent 私聊、Swarm/小未中控群聊、SQLite 消息历史、配置审批与多平台文本模型网关。Agent 可通过 TOML 显式启用用户安装的 Skill 文本。模型可调用 `calculator`、`read_file`、`glob_files`、`grep_files` 四个内置工具；其他界面工具选项仍只是授权记录，Workflow 和 MCP 执行器尚未接入。

完整的前后端、Python 算法、数据模型与接口方案见 [系统设计文档](docs/system-design.md)；可安装包目录、模型适配器、群聊模式和独立上下文的目标结构见 [工程目录设计](docs/project-structure.md)。每个目录都包含 `README.md`，每个 Python/JavaScript 脚本开头说明职责。

使用 Python 3.12 或更高版本，在项目根目录运行：

```bash
python -m pip install -e .
futurework init
# 在当前 shell 中设置 DEEPSEEK_API_KEY 后执行：
futurework serve
```

默认模型别名 `default_fast` 指向 DeepSeek `deepseek-chat`。密钥从 `DEEPSEEK_API_KEY` 环境变量读取，程序不会把它写入 TOML、数据库或 Git。打开 <http://127.0.0.1:8000/> 使用正式页面；API 文档在 <http://127.0.0.1:8000/docs>。首次运行 `init` 或 `serve` 时建立 `~/.futurework/`；`futurework doctor` 校验配置，`futurework paths` 显示目录。可用 `FUTUREWORK_HOME` 或 `--home` 指向独立用户目录。若此前已创建过用户目录，程序不会覆盖已有 `models.toml`；请手工把 `models.default_fast.provider` 设为 `deepseek` 并填写对应的 `remote_id`。

Agent、Team 和模型配置分别位于 `~/.futurework/agents/`、`teams/` 和 `models.toml`。手工修改后重启服务生效。自动创建的 Agent、页面创建的 Team 以及获批的 Agent 配置会写回 TOML。群聊的 `mode` 可设为 `swarm` 或 `controlled`；前者由成员依次回复，后者由小未选择成员、分派并汇总多人结果。消息、任务、审批和已读状态保存在 `~/.futurework/data/`。

参考 Bamboo 的模型注册表，新建用户目录的 `models.toml` 提供 DeepSeek、Kimi、MiniMax、MiMo、GPT、Claude、阿里云千问、智谱、OpenRouter，以及本地 Ollama/vLLM 文本模型别名。默认仍为 DeepSeek。云端模型各自读取环境变量；本地模型无需密钥，但需自行启动服务并按实际端口与模型名调整 TOML。图像、视频模型及 Bamboo 的通用自定义 HTTP 协议尚未实现。现有 `~/.futurework/models.toml` 不会被覆盖，需手工补入新条目。

执行层把 Agent 身份、当前会话历史、模型别名与工具授权收拢到 `AgentRun` 对象，再以 `ModelRequest`/`ModelResult` 对象通过网关和适配器传递。`calculator` 默认授予新 Agent 和示例 Agent；文件工具需在 Agent 配置中授权，页面增加权限会进入审批。三个文件工具只访问 `~/.futurework/workspace`（可在 `app.toml` 的 `[tool_runtime]` 修改），所有调用有轮数、输出和文件大小限制。已有 Agent 配置不会自动增添工具授权。

手工安装 Skill 时，将 `SKILL.md` 放在 `~/.futurework/skills/<id>/`，再在对应 Agent TOML 中写入 `[extensions] skills = ["<id>"]`。重启后该 Agent 的模型上下文会包含 Skill 说明；Skill 不会自动获得工具或文件权限。

## 静态原型预览

在项目目录运行 `python3 -m http.server 4173`，然后打开 `http://localhost:4173/frontend/`。

## 可体验的交互

- 左侧折叠 Agent 好友和群聊，点击后切换对话。
- 和个人助理发消息，体验任务分配和按需创建新 Agent 的演示流程。
- 展开右侧消息区，浏览所有对话；切换“待我审批”筛选并处理审批。
- 打开 Agent 对话后点击“配置能力”，调整模型、工具和审批权限。
- 通过“创建 Agent 好友”手动添加演示成员。
