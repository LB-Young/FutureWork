# runtime

Three conversation runtimes, two group policies, execution and checkpoints.
Agent 执行以 `AgentRun` 对象携带身份、会话历史、模型和工具授权。工具调度在每次调用前复核授权，文件工具限定用户工作区。
