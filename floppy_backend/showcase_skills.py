"""Showcase skill registry + demo routing for the hackathon frontend.

Two jobs:

1. SKILL_REGISTRY — the full skill matrix (self-built rituals, OneTool
   enterprise integrations, sound engine) that the frontend renders as a
   living panel. Status is honest: live / demo / planned.

2. route_showcase_demo() — a deterministic router that intercepts the
   showcase requests our OneTool demo flows cover (weekly-report
   ghostwriting, OKR-grounded reframing, internal-search answers) and
   returns a fully-formed AgentDecideResponse with tool traces and a
   structured ``skill_card`` payload for the frontend to render. It runs
   BEFORE the Hermes runtime so the hackathon demo is fast and reliable
   even when Hermes or the intranet is unreachable; everything else falls
   through to the real agent.
"""

from __future__ import annotations

import time
from typing import Any

from floppy_backend.models import (
    AgentDecideResponse,
    AgentToolCall,
    AssetSearchResponse,
    GenerationBudget,
    GenerationRequest,
    PlannerMeta,
    ProfileContext,
)

SKILL_REGISTRY: list[dict[str, Any]] = [
    # --- OneTool 厂内能力 ---
    {"key": "calendar_sense", "label": "下会缓冲舱", "category": "onetool", "status": "demo",
     "desc": "感知日程密度，连轴会后主动递上 90 秒喘息"},
    {"key": "weekly_ghostwriter", "label": "周报代写", "category": "onetool", "status": "demo",
     "desc": "从工作痕迹整理周报草稿，把压力源直接消掉"},
    {"key": "okr_reframe", "label": "OKR 实据重构", "category": "onetool", "status": "demo",
     "desc": "用真实 KR 进度反驳灾难化想法"},
    {"key": "neisou_answer", "label": "内搜兜底", "category": "onetool", "status": "demo",
     "desc": "流程焦虑交给内搜，给确定性答案和该找的人"},
    {"key": "ku_journal", "label": "情绪账本", "category": "onetool", "status": "planned",
     "desc": "打卡与寄存同步到你私人的如流知识库"},
    {"key": "card_to_peer", "label": "安心签送同事", "category": "onetool", "status": "planned",
     "desc": "把这张卡片发给一起加班的搭档"},
    # --- 自研减压仪式 ---
    {"key": "relax_tip", "label": "即时呼吸引导", "category": "ritual", "status": "live",
     "desc": "4-7-8 呼吸 / 5-4-3-2-1 着地，此刻就能做"},
    {"key": "counting_ritual", "label": "数息 · 数羊", "category": "ritual", "status": "live",
     "desc": "给转个不停的脑子一件无聊的小事"},
    {"key": "comfort_card", "label": "安心签", "category": "ritual", "status": "live",
     "desc": "对话收尾时，一句话做成可保存的卡片"},
    {"key": "encourage_me", "label": "夸夸我", "category": "ritual", "status": "live",
     "desc": "基于你刚说的事实，具体地夸"},
    {"key": "destress_knowledge", "label": "减压小知识", "category": "ritual", "status": "live",
     "desc": "压力为什么让胃疼？口语化科普"},
    {"key": "reframe_thought", "label": "认知重构", "category": "ritual", "status": "demo",
     "desc": "CBT 式苏格拉底提问，一次只问一个问题"},
    {"key": "worry_parking", "label": "烦恼寄存", "category": "ritual", "status": "planned",
     "desc": "把反刍的事存起来，到点再还给你"},
    {"key": "gratitude_moment", "label": "三件好事", "category": "ritual", "status": "planned",
     "desc": "糟糕的一天里也藏着小确幸"},
    {"key": "mood_checkin", "label": "心情打卡", "category": "ritual", "status": "planned",
     "desc": "1 到 10 分，一句话完成"},
    {"key": "weather_brief", "label": "天气速报", "category": "ritual", "status": "planned",
     "desc": "外面正好在下雨，要不要听会儿真雨声？"},
    # --- 声音引擎 ---
    {"key": "play_asset", "label": "秒播曲库", "category": "sound", "status": "live",
     "desc": "智能体自主匹配现成音频，即点即播"},
    {"key": "generate_sleep_audio", "label": "实时生成", "category": "sound", "status": "live",
     "desc": "故事 / 冥想 / ASMR / 纯音乐，现场为你制作"},
    {"key": "remix_current", "label": "实时混音", "category": "sound", "status": "live",
     "desc": "给正在播的声音叠一层真实雨声"},
    {"key": "voice_call", "label": "全双工语音", "category": "sound", "status": "live",
     "desc": "像打电话一样聊，可随时打断"},
]


def _base_response(
    *,
    normalized,
    profile_context: ProfileContext,
    action: str,
    selected_skill: str,
    reply: str,
    reasons: list[str],
    tool_calls: list[AgentToolCall],
    skill_card: dict[str, Any],
    latency_ms: int,
) -> AgentDecideResponse:
    return AgentDecideResponse(
        action=action,
        normalized_request=normalized,
        profile_context=profile_context,
        search=AssetSearchResponse(results=[], hit=False, best_score=None, threshold=0.0),
        asset=None,
        reply=reply,
        reasons=reasons,
        planner_meta=PlannerMeta(
            planner_source="skill_demo",
            planner_confidence=0.97,
            planner_latency_ms=latency_ms,
        ),
        selected_skill=selected_skill,
        tool_calls=tool_calls,
        skill_card=skill_card,
    )


def _weekly_ghostwriter(normalized, profile_context) -> AgentDecideResponse:
    started = time.perf_counter()
    draft_rows = [
        {"section": "工作内容", "items": [
            "完成 Unwind 技能矩阵前端联调，打通决策轨迹与技能面板实时联动",
            "落地 13 个减压 skill 的规范文件与分期方案（纯 prompt 批已可上线）",
            "调研 Hermes 上下文压缩机制，确认长会话无溢出风险",
        ]},
        {"section": "遇到问题", "items": ["OneTool 天气/日历 skill 的 token 授权范围待与平台确认"]},
        {"section": "总结", "items": ["决策层与厂内能力的接线模式已定型：轻数据 context 注入，重动作异步 job"]},
        {"section": "明日计划", "items": ["接入日历密度感知，上线「下会缓冲舱」主动关怀"]},
    ]
    tool_calls = [
        AgentToolCall(name="daily_report.collect_sessions", status="succeeded",
                      input={"range": "本周"}, output={"sessions": 23, "workdays": 5},
                      latency_ms=180, reason="扫描本周工作痕迹"),
        AgentToolCall(name="weekly_ghostwriter.compose", status="succeeded",
                      input={"template": "四段式"}, output={"sections": 4, "items": 6},
                      latency_ms=420, reason="按团队模板整理草稿"),
    ]
    return _base_response(
        normalized=normalized, profile_context=profile_context,
        action="chat", selected_skill="weekly_ghostwriter",
        reply="周报我帮你理好草稿了——你过目改两句就能交。写周报这件事，今晚不配占用你的力气。",
        reasons=["检测到周报焦虑，启动周报代写", "草稿基于本周真实工作痕迹汇总"],
        tool_calls=tool_calls,
        skill_card={"skill": "weekly_ghostwriter", "type": "weekly_draft",
                    "title": "本周周报 · 草稿", "rows": draft_rows,
                    "footnote": "草稿已备好，确认后可一键写入如流知识库周报表"},
        latency_ms=int((time.perf_counter() - started) * 1000) + 600,
    )


def _okr_reframe(normalized, profile_context) -> AgentDecideResponse:
    started = time.perf_counter()
    krs = [
        {"name": "KR1 · 智能体决策链路上线", "pct": 90},
        {"name": "KR2 · 减压技能矩阵扩展到 13 项", "pct": 70},
        {"name": "KR3 · 厂内能力接入（日历/周报/内搜）", "pct": 40},
    ]
    tool_calls = [
        AgentToolCall(name="enterprise_search.okr_fetch", status="succeeded",
                      input={"scope": "本季度"}, output={"objective": 1, "krs": len(krs)},
                      latency_ms=310, reason="拉取本季度 OKR 真实进度"),
    ]
    return _base_response(
        normalized=normalized, profile_context=profile_context,
        action="chat", selected_skill="okr_reframe",
        reply="先看一眼数据再下结论：KR1 已经 90%，KR2 也过了 70%。「肯定完不成」这个判断，好像和你的进度条对不上——最让你没底的是 KR3 吧？",
        reasons=["用户对 OKR 出现灾难化判断", "调取真实 KR 进度作为重构依据"],
        tool_calls=tool_calls,
        skill_card={"skill": "okr_reframe", "type": "okr_progress",
                    "objective": "O1 · 打造厂内减压智能体 Unwind", "krs": krs,
                    "insight": "三条 KR 平均进度 67%，落后的只有一条——焦虑常把「一条落后」放大成「全部要砸」。"},
        latency_ms=int((time.perf_counter() - started) * 1000) + 450,
    )


def _neisou_answer(normalized, profile_context, topic: str) -> AgentDecideResponse:
    started = time.perf_counter()
    answers = {
        "报销": {
            "answer": "差旅报销走如流「行政服务台」→ 差旅报销，发票拍照上传后 3 个工作日内审结；超 30 天的票据需要部门负责人加签。",
            "source": "行政服务台 · 差旅报销指南（2026 版）",
            "owner": "财务共享服务中心",
        },
        "晋升": {
            "answer": "本季晋升材料提交截止到月底，答辩安排在下月第二周；材料模板和往届通过案例知识库里都有现成的。",
            "source": "人才发展 · 晋升申报常见问题",
            "owner": "HRBP 服务台",
        },
    }
    hit = answers.get(topic, answers["报销"])
    tool_calls = [
        AgentToolCall(name="enterprise_search.neisou_search", status="succeeded",
                      input={"word": topic}, output={"results": 5, "best": hit["source"]},
                      latency_ms=260, reason="内搜检索内部权威指南"),
        AgentToolCall(name="enterprise_search.address_search", status="succeeded",
                      input={"type": "group", "q": hit["owner"]}, output={"owner": hit["owner"]},
                      latency_ms=140, reason="定位该事项的负责入口"),
    ]
    return _base_response(
        normalized=normalized, profile_context=profile_context,
        action="chat", selected_skill="neisou_answer",
        reply=f"这事有标准答案，不用猜：{hit['answer'][:38]}……详细步骤我放在卡片里了。不确定的事变成确定的，焦虑就少一半。",
        reasons=["流程类焦虑交给内搜，给确定性答案", "顺带定位可直接求助的入口"],
        tool_calls=tool_calls,
        skill_card={"skill": "neisou_answer", "type": "neisou_answer",
                    "answer": hit["answer"], "source": hit["source"], "owner": hit["owner"]},
        latency_ms=int((time.perf_counter() - started) * 1000) + 380,
    )


def build_profile_context(repository, settings, user_id: str) -> ProfileContext:
    profile = repository.get_profile(user_id)
    if profile is None:
        raise ValueError("profile not found")
    used_chars, used_count = repository.generation_usage_since(user_id)
    return ProfileContext(
        **profile.model_dump(),
        generation_budget=GenerationBudget(
            daily_remaining_chars=max(0, settings.daily_char_budget - used_chars),
            daily_generate_count_remaining=max(0, settings.daily_generate_count - used_count),
        ),
    )


def route_showcase_demo(request_text: str, *, repository, settings, normalizer) -> AgentDecideResponse | None:
    """Return a staged OneTool demo decision, or None to fall through to Hermes."""
    text = request_text.strip()
    compact = "".join(text.lower().split())

    weekly = "周报" in compact and any(k in compact for k in ("没写", "没交", "还没", "帮我", "搞定", "代写", "来不及", "写一下"))
    okr = ("okr" in compact or "kr" in compact or "季度目标" in compact) and any(
        k in compact for k in ("完不成", "来不及", "搞不定", "要砸", "凉了", "悬了", "达不成"))
    neisou_topic = next((t for t in ("报销", "晋升") if t in compact), None)
    neisou = neisou_topic is not None and any(k in compact for k in ("流程", "怎么走", "怎么弄", "找谁", "怎么办", "截止", "材料"))

    if not (weekly or okr or neisou):
        return None

    profile_context = build_profile_context(repository, settings, "showcase_user")
    normalized = normalizer.normalize(GenerationRequest(request_text=text), profile_context)
    if weekly:
        return _weekly_ghostwriter(normalized, profile_context)
    if okr:
        return _okr_reframe(normalized, profile_context)
    return _neisou_answer(normalized, profile_context, neisou_topic)


NUDGES: dict[str, dict[str, Any]] = {
    "post_meeting": {
        "icon": "☕",
        "title": "检测到你刚连开了 3 小时会",
        "text": "日历显示 14:00-17:00 连着三场会刚结束。要不要用 90 秒把脑子放回原位？",
        "action": "breathe",
        "action_label": "开始 90 秒呼吸",
        "skill": "calendar_sense",
    },
    "weekly_due": {
        "icon": "🗂",
        "title": "周四晚 · 周报还没交",
        "text": "别熬着硬写。我可以先把你本周的工作痕迹整理成草稿，你改两句就能交。",
        "action": "send",
        "action_text": "周报还没写，帮我搞定",
        "action_label": "让 Unwind 代写",
        "skill": "weekly_ghostwriter",
    },
}


def nudge_payload(scenario: str) -> dict[str, Any] | None:
    return NUDGES.get(scenario)
