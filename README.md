# FutureWork

`frontend/` 保留静态交互原型。`src/futurework/` 是按工程设计搭建的 Python 包骨架，已提供用户目录初始化、基础配置校验和 API 健康检查。Agent Runtime、模型适配器、工具与扩展执行仍需逐步实现。

完整的前后端、Python 算法、数据模型与接口方案见 [系统设计文档](docs/system-design.md)；可安装包目录、模型适配器、群聊模式和独立上下文的目标结构见 [工程目录设计](docs/project-structure.md)。每个目录都包含 `README.md`，每个 Python/JavaScript 脚本开头说明职责。

使用 Python 3.12 或更高版本，在项目根目录运行 `python -m pip install -e .`。首次运行 `futurework init` 或 `futurework serve` 时建立 `~/.futurework/`，之后从该目录读取配置。`futurework doctor` 校验配置，`futurework paths` 显示目录。可以用 `FUTUREWORK_HOME` 或 `--home` 选择测试目录。当前 `serve` 只提供 `/api/v1/health`；静态原型按下方方式预览。

## 预览

在项目目录运行 `python3 -m http.server 4173`，然后打开 `http://localhost:4173/frontend/`。

## 可体验的交互

- 左侧折叠 Agent 好友和群聊，点击后切换对话。
- 和个人助理发消息，体验任务分配和按需创建新 Agent 的演示流程。
- 展开右侧消息区，浏览所有对话；切换“待我审批”筛选并处理审批。
- 打开 Agent 对话后点击“配置能力”，调整模型、工具和审批权限。
- 通过“创建 Agent 好友”手动添加演示成员。
