# /agent/decide 验收用例

## P0 用例（阻塞上线）

| # | 场景 | 前置条件 | 期望响应 |
|---|------|----------|----------|
| 1 | hit | 已有匹配资产（prompt_hash 命中） | `action=play_asset`, asset 非空, 无 job 创建 |
| 2 | no_match | `generation_allowed=false` 且无匹配资产 | `action=no_match`, asset 为空, 无 job 创建 |
| 3 | generate_job | `generation_allowed=true` 且无匹配资产 | `action=generate_job`, 返回 job_id, job status=generating/succeeded |
| 4 | budget | `FLOPPY_DAILY_GENERATE_COUNT=0` | HTTP 429, body 含 budget/exceeded 信息 |
| 5 | provider 隔离 | 默认 pytest（无 FLOPPY_MINIMAX_API_KEY） | 使用 local provider, 不实例化 MiniMaxTTSProvider |
| 6 | mood 字段透传 | request_text 含情绪关键词（焦虑/放松） | 响应 `normalized_request.mood` 非空数组，或 `structured_query.mood` 存在 |
| 7 | asset tag 兜底 | 资产仅有 mood_tags + user_segment_tags | hit 场景仍可命中，不因缺少扩展标签而 miss |

## P0 LangGraph 验收项（阻塞上线）

| # | 验收点 | 验证方式 | 通过标准 |
|---|--------|----------|----------|
| LG-1 | 响应字段兼容 | 断言 `/agent/decide` 200 响应包含全部必选字段 | 必含：`action`, `normalized_request`, `profile_context`, `search`, `asset`, `job_id`, `reasons` |
| LG-2 | Graph 路由 hit | seed 资产 + 匹配请求 | `action=play_asset`, asset 非空, 无 job 创建 |
| LG-3 | Graph 路由 no_match | `generation_allowed=false` + miss | `action=no_match` |
| LG-4 | Graph 路由 generate_job | `generation_allowed=true` + miss | `action=generate_job`, job_id 非空 |
| LG-5 | Graph 路由 budget | `FLOPPY_DAILY_GENERATE_COUNT=0` | HTTP 429 |
| LG-6 | Provider 封装 | 代码检查 + 测试 | MiniMax/provider 调用仅通过 `GenerationService`，graph node 不直接实例化 provider |
| LG-7 | 默认 pytest 隔离 | 无 FLOPPY_MINIMAX_API_KEY 环境下全量 pytest | 不实例化 MiniMaxTTSProvider |
| LG-8 | Graph 确定性可测 | 单元测试 mock 所有外部依赖 | graph runner 输入固定 → 输出固定，无随机/时间依赖 |

### 已知限制（不阻塞 P0）

- **SQLite checkpointer 未接入**：P0 graph 无状态持久化；重启后无法恢复中间态。P1 接入。
- **Graph 重试/fallback**：P0 不要求 node 级重试；provider 失败直接返回 failed job。

## P0 AI Query Planner 验收项（阻塞上线）

| # | 验收点 | 验证方式 | 通过标准 |
|---|--------|----------|----------|
| AQP-1 | 默认 pytest 不访问真实 AI/外部 API | 无 AI provider key 环境下全量 pytest | 通过，无网络调用；AI planner 必须可 mock/stub |
| AQP-2 | Mock AI planner → tag 命中 | mock planner 返回 `preferred_tags=["grounding"]` | `/agent/decide` 按 AI tags 命中资产，action=play_asset |
| AQP-3 | AI planner 是主路径，规则仅 fallback | 代码检查 agent_graph search node | 主路径调用 AI planner；segment_map 仅在 planner unavailable/low-confidence 时使用 |
| AQP-4 | AI low confidence / unavailable → fallback | mock planner raise/返回 confidence<阈值 | fallback 到规则标签，reasons 含 "fallback" 字样 |
| AQP-5 | Fallback 不绕过预算/429 | fallback + `FLOPPY_DAILY_GENERATE_COUNT=0` | 仍返回 429，生成仍走 GenerationService |
| AQP-6 | 响应字段兼容 | 断言 200 响应字段 | 必含：action/normalized_request/profile_context/search/asset/job_id/reasons |
| AQP-7 | AI provider key 不入库不进日志 | grep 代码 + pytest 输出 | 无 hardcoded key；测试日志无 key 泄漏；env var 命名 `FLOPPY_AI_PLANNER_*` |

### AI Planner 已知限制（不阻塞 P0）

- **Planner 延迟**：P0 不要求 planner 调用有 SLA；超时直接 fallback。
- **Planner 结果缓存**：P0 不要求缓存 AI 输出；P1 可加 TTL 缓存减少调用。

## P1 用例（不阻塞 /agent/decide 上线）

| # | 场景 | 前置条件 | 期望响应 |
|---|------|----------|----------|
| 8 | skip>=3 触发重分群 | 用户连续 skip 3+ 次 | profile.segment 更新，后续推荐结果变化 |
| 9 | 扩展标签索引 | 资产有 required/preferred/negative tags | 匹配精度优于纯 mood_tags 兜底 |

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
- 用例 6-7：TestClient，断言 normalized_request/structured_query 含 mood；asset search 使用 mood_tags 兜底
- 用例 4：monkeypatch env `FLOPPY_DAILY_GENERATE_COUNT=0`
- 用例 5：断言 `build_audio_provider(settings)` 返回 `LocalToneAudioProvider`
- 事件契约：逐类 POST，校验 status 201 + event_id 格式

## 通过标准

- P0 全部用例在 `.venv/bin/pytest` 默认运行中 PASS
- 无真实 MiniMax API 调用
- 响应 action 字段与期望严格匹配
- normalized_request 包含 mood 字段（兼容：字段缺失时不 500，降级为空数组）

## 风险与兜底

- **asset 标签不足**：P0 用 `mood_tags` + `user_segment_tags` 做匹配；P1 扩展 required/preferred/negative tags 索引
- **mood 字段缺失兼容**：若 algo 未返回 mood，backend 应降级为 `[]`，不阻塞 action 决策
- **skip 重分群**：P1，当前 segment 不会因 skip 实时变化
