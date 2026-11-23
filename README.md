# FutureWork

本地可运行的 Agent Team 第一版。页面、Python API、SQLite 消息持久化、规则分派、自动创建 Agent、群聊、配置审批和 SSE 更新已接通。

## 快速启动

需要 Python 3.12。以 `uv` 为例：

```bash
uv sync --extra test
uv run python -m backend
```

打开 <http://127.0.0.1:8000/>。API 文档在 <http://127.0.0.1:8000/docs>。测试：`uv run pytest`。

## 配置

- `config/app.toml`：服务地址、数据库位置、模型、能力匹配权重与阈值、任务关键词、初始 Agent 和群聊、工具权限、审批时效、界面文案与数量限制。修改后重启服务生效。
- 可用 `FUTUREWORK_CONFIG` 指向另一份 TOML 配置文件；数据库相对路径仍以项目根目录为基准。
- `frontend/config.json`：API 前缀、事件重连与刷新时间、提示显示时间。
- `frontend/styles.css`、`frontend/responsive.css`：样式与布局参数。
- 模型密钥放环境变量，名称由 `config/app.toml` 的 `model.api_key_env` 指定；不要提交密钥。`.env.example` 给出变量名，程序不会自动加载 `.env`。

默认 `model.provider = "mock"`，不用密钥即可体验分派、持久化和审批。接入兼容 OpenAI Chat Completions 的模型服务时，设置 `model.provider = "openai_compatible"`、`model.api_url`、`model.available_models`、`model.default_model`，并导出 `FUTUREWORK_MODEL_API_KEY`。各 Agent 的模型可在页面配置。

## 当前能力与边界

- 小未按 `planner.rules` 把请求拆成步骤，使用 `matching` 权重选择 Agent；没有合格 Agent 时按最小权限创建新成员。演示模型下任务停在 `assigned`；配置真实模型后会在后台生成各步骤初稿并汇总，但尚不执行外部工具。
- 一对一和群聊消息保存到 `data/futurework.sqlite3`。页面可以创建 Agent 与群聊；群聊 `@Agent名` 会由指定成员回复，没有 `@` 时由首位成员回复。
- 权限扩大需审批，批准前不生效；配置保留版本号，旧审批不能覆盖新版本。工具授权仅存配置，真实工具执行器尚未接入。
- 此版仅绑定本机、未实现账号鉴权、多用户隔离、后台队列和生产级工具沙箱，不能直接对公网部署。

完整目标架构见 [系统设计文档](docs/system-design.md)。
