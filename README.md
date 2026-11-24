# FutureWork

`frontend/` 保留静态设计原型；运行中的页面打包在 `src/futurework/web/`。当前版本已接通小未任务分派、Agent 私聊、Swarm/小未中控群聊、SQLite 消息历史、配置审批与多平台文本模型网关。Agent 可通过 TOML 显式启用用户安装的 Skill 文本。工具、Workflow 和 MCP 的执行器仍未接入；界面中的工具配置是授权记录，不会触发实际工具调用。

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

手工安装 Skill 时，将 `SKILL.md` 放在 `~/.futurework/skills/<id>/`，再在对应 Agent TOML 中写入 `[extensions] skills = ["<id>"]`。重启后该 Agent 的模型上下文会包含 Skill 说明；Skill 不会自动获得工具或文件权限。

## 静态原型预览

在项目目录运行 `python3 -m http.server 4173`，然后打开 `http://localhost:4173/frontend/`。

## 可体验的交互

- 左侧折叠 Agent 好友和群聊，点击后切换对话。
- 和个人助理发消息，体验任务分配和按需创建新 Agent 的演示流程。
- 展开右侧消息区，浏览所有对话；切换“待我审批”筛选并处理审批。
- 打开 Agent 对话后点击“配置能力”，调整模型、工具和审批权限。
- 通过“创建 Agent 好友”手动添加演示成员。
