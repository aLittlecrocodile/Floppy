# Unwind 文档索引

这里是 Unwind 后端、体验页和音频生成链路的文档入口。当前实现优先看“启动与体验”“接口对接”和“运行契约”；开发记录仅用于查历史决策。

## 启动与体验

- [STARTUP.md](STARTUP.md)
  本地或服务器启动、环境变量、数据迁移和联调检查。

- [../popo/unwind/index.html](../popo/unwind/index.html)
  Unwind 产品介绍入口页，所有体验按钮进入 `/showcase`。

## 接口对接

- [frontend/backend_api_reference.md](frontend/backend_api_reference.md)
  后端接口总览，覆盖画像、推荐、生成、Agent 决策、播放、反馈和 Remix。

- [frontend/android_client_guide.md](frontend/android_client_guide.md)
  Android 客户端接入说明。

- [frontend/demo_integration.md](frontend/demo_integration.md)
  Demo 页面接入说明；涉及旧页面接口时，以接口总览和当前代码为准。

## 当前契约

- [contracts/agent_tool_contract.md](contracts/agent_tool_contract.md)
  Agent 与后端工具边界、预算和安全约束。

- [contracts/agent_workflow_protocol_v0.md](contracts/agent_workflow_protocol_v0.md)
  Agent 决策与音频 workflow 之间的稳定协议。

- [contracts/voice_dialog_ws.md](contracts/voice_dialog_ws.md)
  实时语音对话 WebSocket 协议。

- [contracts/voice_dialog_ws_backend.md](contracts/voice_dialog_ws_backend.md)
  实时语音链路的后端运维与配置说明。

- [contracts/ai_query_planner_contract_v0.md](contracts/ai_query_planner_contract_v0.md)
  AI Query Planner 的输入、输出和降级约束。

- [contracts/profile_agent_schema_v0.md](contracts/profile_agent_schema_v0.md)
  用户画像、分群、检索标签和画像更新信号。

- [contracts/minimax_hubless_audio_tools.md](contracts/minimax_hubless_audio_tools.md)
  MiniMax 音频生成与本地混音能力映射。

## 验收与架构

- [qa/agent_decision_acceptance.md](qa/agent_decision_acceptance.md)
  `/agent/decide` 和生成决策链路验收用例。

- [architecture/floppy_backend_architecture.svg](architecture/floppy_backend_architecture.svg)
  后端架构图源文件。

- [architecture/floppy_backend_architecture.png](architecture/floppy_backend_architecture.png)
  后端架构图图片。

## 开发记录

- [logs/development_log.md](logs/development_log.md)  项目过程记录，不作为当前实现入口。
- [contracts/algo_p0_design_v1.md](contracts/algo_p0_design_v1.md)  早期算法设计稿，仅在需要追溯时查看。
