# /agent/decide 验收用例

## P0 用例（阻塞上线）

| # | 场景 | 前置条件 | 期望响应 |
|---|------|----------|----------|
| 1 | hit | 已有匹配资产（prompt_hash 命中） | `action=play_asset`, asset 非空, 无 job 创建 |
| 2 | no_match | `generation_allowed=false` 且无匹配资产 | `action=no_match`, asset 为空, 无 job 创建 |
| 3 | generate_job | `generation_allowed=true` 且无匹配资产 | `action=generate_job`, 返回 job_id, job status=generating/succeeded |
| 4 | budget | `FLOPPY_DAILY_GENERATE_COUNT=0` | HTTP 429, body 含 budget/exceeded 信息 |
| 5 | provider 隔离 | 默认 pytest（无 FLOPPY_MINIMAX_API_KEY） | 使用 local provider, 不实例化 MiniMaxTTSProvider |
| 6 | mood 字段透传 | request_text 含情绪关键词（焦虑/放松） | 响应 `normalized_request.mood` 非空数组 |
| 7 | asset tag 兜底 | 资产仅有 mood_tags + user_segment_tags | hit 场景仍可命中，不因缺少扩展标签而 miss |

## P0 Hermes Runtime 验收项（阻塞上线）

| # | 验收点 | 验证方式 | 通过标准 |
|---|--------|----------|----------|
| HR-1 | 响应字段兼容 | 断言 `/agent/decide` 200 响应包含全部必选字段 | 必含：`action`, `normalized_request`, `profile_context`, `search`, `asset`, `job_id`, `reasons`, `selected_skill`, `tool_calls` |
| HR-2 | Hermes 主路径 | mock Hermes decision | `planner_meta.planner_source=hermes`，首个 tool call 为 `hermes_agent` |
| HR-3 | Hermes hit | Hermes 返回候选 asset_id | `action=play_asset`, asset 非空, 无 job 创建 |
| HR-4 | Hermes no_match | `generation_allowed=false` 且 Hermes/no candidate 不生成 | `action=no_match` |
| HR-5 | Hermes generate_job | Hermes 返回 `generate_job` | `action=generate_job`, job_id 非空，directive 可透传 |
| HR-6 | Hermes remix | `current_asset_id` 存在且 Hermes 返回 `remix_current` | `action=remix_current`, remix_job_id 非空 |
| HR-7 | Provider 封装 | 代码检查 + 测试 | MiniMax/provider 调用仅通过 `GenerationService`，Hermes runtime 不直接实例化 provider |
| HR-8 | 默认 pytest 隔离 | 无 FLOPPY_MINIMAX_API_KEY 环境下全量 pytest | 不实例化 MiniMaxTTSProvider；Hermes 调用使用 mock |

### 已知限制（不阻塞 P0）

- **Hermes MCP 直调未启用**：当前阶段 Hermes 负责决策，Floppy 仍在本地执行 workflow。
- **LangGraph 已移除**：`FLOPPY_AGENT_RUNTIME=local` 不再支持；所有 agent 决策必须走 Hermes。

## P1 用例（不阻塞 /agent/decide 上线）

| # | 场景 | 前置条件 | 期望响应 |
|---|------|----------|----------|
| 8 | structured search plan | 用户请求含未识别声音词 | Hermes search plan 低置信或空候选时，不播放弱候选 |
| 9 | 标签清理 | catalog 资产标签无旧混淆标签 | 无 `minimal_voice`，语音资产有 `voice_present` |

## 画像更新事件契约（P0 payload 检查）

每类事件 POST `/users/{uid}/events` 必须满足：

| event_type | 必选 payload 字段 | 验收检查 |
|---|---|---|
| audio_completed | `asset_id`, `duration_listened_sec` | 201, event_id 返回 |
| audio_skipped | `asset_id`, `skip_position_sec` | 201, event_id 返回 |
| asset_disliked | `asset_id`, `reason?` | 201, event_id 返回 |
| asset_favorited | `asset_id` | 201, event_id 返回 |
| morning_feedback | `sleep_quality: 1-5`, `note?` | 201, event_id 返回 |
| conversation_signal | `signal_type`, `value` | 201, event_id 返回 |
| questionnaire_updated | `answers: object` | 201, event_id 返回 |
| checkin_submitted | `mood_tags: string[]`, `stress_level?` | 201, event_id 返回 |

## 验证方式

- 用例 1-5：TestClient + tmp_path DB，mock provider（local）
- 用例 6-7：TestClient，断言 normalized_request 含 mood；asset search 使用 mood_tags 兜底
- 用例 4：monkeypatch env `FLOPPY_DAILY_GENERATE_COUNT=0`
- 用例 5：断言 `build_audio_provider(settings)` 返回 `LocalToneAudioProvider`
- 事件契约：逐类 POST，校验 status 201 + event_id 格式

## 通过标准

- P0 全部用例在 `.venv/bin/pytest` 默认运行中 PASS
- 无真实 MiniMax API 调用
- 响应 action 字段与期望严格匹配
- normalized_request 包含 mood 字段（兼容：字段缺失时不 500，降级为空数组）

## 风险与兜底

- **asset 标签不足**：通过 catalog facets + Hermes search plan 置信度暴露给 Hermes，避免弱匹配误播放
- **mood 字段缺失兼容**：字段缺失时 backend 应降级为 `[]`，不阻塞 action 决策
- **skip 重分群**：P1，当前 segment 不会因 skip 实时变化
