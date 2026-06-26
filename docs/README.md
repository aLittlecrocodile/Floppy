# Floppy 文档索引

本文档用于说明 `docs/` 目录分层。默认先读当前对接和契约文档；调研过程稿已放入 `research/`，避免干扰日常开发。

## 前端对接

- [frontend/backend_api_reference.md](frontend/backend_api_reference.md)  
  前端完整后端接口文档：覆盖全部路由（画像、问卷、检索/推荐/生成、Agent 决策、播放/反馈、Remix），含请求/响应、枚举、状态码、最小接入流程。给前端对接用的主文档。

- [frontend/demo_integration.md](frontend/demo_integration.md)  
  Demo 页面接入说明：`/demo/chat` 请求/响应、页面状态、播放器字段、当前能力边界。快速上手用。

## 当前契约

- [contracts/agent_tool_contract.md](contracts/agent_tool_contract.md)  
  Agent 与后端工具边界：ProfileContext、后端工具、预算/安全边界。

- [contracts/ai_query_planner_contract_v0.md](contracts/ai_query_planner_contract_v0.md)  
  AI Query Planner 契约：输入、输出 JSON schema、confidence、fallback。

- [contracts/profile_agent_schema_v0.md](contracts/profile_agent_schema_v0.md)  
  用户画像、分群、tag retrieval、画像更新信号。

- [contracts/minimax_poc_checklist.md](contracts/minimax_poc_checklist.md)  
  MiniMax 真实音频生成验证清单。

## QA 验收

- [qa/agent_decision_acceptance.md](qa/agent_decision_acceptance.md)  
  `/agent/decide`、LangGraph、AI Query Planner 的验收用例。

## 架构图

- [architecture/floppy_backend_architecture.svg](architecture/floppy_backend_architecture.svg)  
  后端架构图源文件。

- [architecture/floppy_backend_architecture.png](architecture/floppy_backend_architecture.png)  
  后端架构图图片。

## 开发记录

- [logs/development_log.md](logs/development_log.md)  
  项目过程日志。用于追溯历史，不作为当前对接入口。

## 调研归档

以下文档是阶段性调研或早期方案，保留作参考，不建议作为当前实现入口：

- [research/backend_algorithm_research.md](research/backend_algorithm_research.md)
- [research/tts_vendor_research.md](research/tts_vendor_research.md)
- [research/minimax_audio_workflow.md](research/minimax_audio_workflow.md)
- [research/minimax_official_deep_research.md](research/minimax_official_deep_research.md)
- [research/asmr_ambient_skill_review.md](research/asmr_ambient_skill_review.md)
- [research/agent_framework_eval_algo.md](research/agent_framework_eval_algo.md)
- [research/user_profile_design.md](research/user_profile_design.md)

