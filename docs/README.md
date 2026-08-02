# Floppy 文档索引

这里是 Floppy 后端、体验页和音频生成链路的文档入口。当前实现优先看“启动与体验”“接口对接”和“运行契约”。历史决策请查 `git log`，不再单独维护开发记录文档。

## 启动与体验

- [STARTUP.md](STARTUP.md)
  本地或服务器启动、环境变量、数据迁移和联调检查。

- [../popo/floppy/index.html](../popo/floppy/index.html)
  Floppy 产品介绍入口页，所有体验按钮进入 `/showcase`。

## 接口对接

- [frontend/backend_api_reference.md](frontend/backend_api_reference.md)
  后端接口总览，覆盖画像、推荐、生成、Agent 决策、播放、反馈和 Remix。

- [frontend/desktop_integration.md](frontend/desktop_integration.md)
  桌面端（原生 Swift 客户端）对接契约：showcase/chat 与 voice/ws 最小面。

- [frontend/home_chat_integration.md](frontend/home_chat_integration.md)
  首页对话入口的接入说明。

- [frontend/android_client_guide.md](frontend/android_client_guide.md)
  Android 客户端接入说明。

- [frontend/demo_integration.md](frontend/demo_integration.md)
  Demo 页面接入说明；涉及旧页面接口时，以接口总览和当前代码为准。

## 当前契约

- [contracts/agent_tool_contract.md](contracts/agent_tool_contract.md)
  Agent 与后端工具边界、预算和安全约束。

- [contracts/hermes_agent_runtime.md](contracts/hermes_agent_runtime.md)
  Hermes agent 运行时的装配、skill 加载和调用约定。

- [contracts/voice_dialog_ws.md](contracts/voice_dialog_ws.md)
  实时语音对话 WebSocket 协议。

- [contracts/voice_dialog_ws_backend.md](contracts/voice_dialog_ws_backend.md)
  实时语音链路的后端运维与配置说明。

- [contracts/minimax_hubless_audio_tools.md](contracts/minimax_hubless_audio_tools.md)
  MiniMax 音频生成与本地混音能力映射。

## 设计

- [design/skill_expansion.md](design/skill_expansion.md)
  skill 矩阵扩展设计与 prompt-first 分期方案。

## 验收与架构

- [qa/agent_decision_acceptance.md](qa/agent_decision_acceptance.md)
  `/agent/decide` 和生成决策链路验收用例。

- [architecture/floppy_backend_architecture.svg](architecture/floppy_backend_architecture.svg)
  后端架构图源文件。

- [architecture/floppy_backend_architecture.png](architecture/floppy_backend_architecture.png)
  后端架构图图片。
