# Floppy 文档索引

本文档用于说明 `docs/` 目录分层。默认先读当前对接、契约和验收文档。

## 前端对接

- [frontend/backend_api_reference.md](frontend/backend_api_reference.md)  
  前端完整后端接口文档：覆盖全部路由（画像、问卷、检索/生成、Agent 决策、播放/反馈、Remix），含请求/响应、枚举、状态码、最小接入流程。给前端对接用的主文档。

- [frontend/demo_integration.md](frontend/demo_integration.md)  
  Demo 页面接入说明：`/demo/chat` 请求/响应、页面状态、播放器字段、当前能力边界。快速上手用。

## 当前契约

- [contracts/hermes_agent_runtime.md](contracts/hermes_agent_runtime.md)
  Hermes Runtime、MCP 工具和 Floppy workflow 的当前边界。

- [contracts/minimax_poc_checklist.md](contracts/minimax_poc_checklist.md)
  MiniMax 真实音频生成验证清单。

## QA 验收

- [qa/agent_decision_acceptance.md](qa/agent_decision_acceptance.md)  
  `/agent/decide`、Hermes runtime 的验收用例。

## 架构图

- [architecture/backend_algorithm_flow.md](architecture/backend_algorithm_flow.md)
  后端与算法流程架构图：覆盖文本入口、语音入口、Hermes Skill、MCP 工具、生成工作流、Multi-Agent、Dream Loop、多层记忆、数据状态。

- [architecture/floppy_backend_architecture.svg](architecture/floppy_backend_architecture.svg)  
  后端架构图源文件。

- [architecture/floppy_backend_architecture.png](architecture/floppy_backend_architecture.png)  
  后端架构图图片。
