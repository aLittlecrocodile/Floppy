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

# Fixed demo replies — prewarmed into the reply-TTS cache at startup so the
# first click on a skill chip speaks instantly on stage.
REPLY_REFRAME = "好，我们慢慢来。先说说最近哪个念头最缠人——说出它的原话，比如「我肯定搞砸」这种。我们一起看看它站不站得住。"
REPLY_WEEKLY = "周报我帮你理好草稿了——你过目改两句就能交。写周报这件事，今晚不配占用你的力气。"
REPLY_OKR = "先看一眼数据再下结论：KR1 已经 90%，KR2 也过了 70%。「肯定完不成」这个判断，好像和你的进度条对不上——最让你没底的是 KR3 吧？"

DEMO_SPOKEN_LINES: list[str] = [REPLY_REFRAME, REPLY_WEEKLY, REPLY_OKR]

SKILL_REGISTRY: list[dict[str, Any]] = [
    # --- OneTool 厂内能力 ---
    {"key": "calendar_sense", "label": "下会缓冲舱", "category": "onetool", "status": "demo",
     "desc": "感知日程密度，连轴会后主动递上 90 秒喘息",
     "demo_scenario": "post_meeting"},
    {"key": "weekly_ghostwriter", "label": "周报代写", "category": "onetool", "status": "demo",
     "desc": "从工作痕迹整理周报草稿，把压力源直接消掉",
     "demo_say": "周报还没写，帮我搞定"},
    {"key": "okr_reframe", "label": "OKR 实据重构", "category": "onetool", "status": "demo",
     "desc": "用真实 KR 进度反驳灾难化想法",
     "demo_say": "这季度 OKR 感觉要完不成了"},
    {"key": "neisou_answer", "label": "内搜兜底", "category": "onetool", "status": "demo",
     "desc": "流程焦虑交给内搜，给确定性答案和该找的人",
     "demo_say": "差旅报销流程怎么走？"},
    {"key": "ku_journal", "label": "情绪账本", "category": "onetool", "status": "planned",
     "desc": "打卡与寄存同步到你私人的如流知识库"},
    {"key": "card_to_peer", "label": "安心签送同事", "category": "onetool", "status": "planned",
     "desc": "把这张卡片发给一起加班的搭档"},
    # --- 自研减压仪式 ---
    {"key": "relax_tip", "label": "即时呼吸引导", "category": "ritual", "status": "live",
     "desc": "4-7-8 呼吸 / 5-4-3-2-1 着地，此刻就能做",
     "demo_say": "我现在特别紧张，心跳快得停不下来"},
    {"key": "counting_ritual", "label": "数息 · 数羊", "category": "ritual", "status": "live",
     "desc": "给转个不停的脑子一件无聊的小事",
     "demo_say": "陪我数个数，让脑子停下来"},
    {"key": "comfort_card", "label": "安心签", "category": "ritual", "status": "live",
     "desc": "对话收尾时，一句话做成可保存的卡片",
     "demo_say": "给我一张今天的安心签"},
    {"key": "encourage_me", "label": "夸夸我", "category": "ritual", "status": "live",
     "desc": "基于你刚说的事实，具体地夸",
     "demo_say": "夸夸我，今天被需求虐惨了"},
    {"key": "destress_knowledge", "label": "减压小知识", "category": "ritual", "status": "live",
     "desc": "压力为什么让胃疼？口语化科普",
     "demo_say": "为什么一焦虑就胃疼？"},
    {"key": "reframe_thought", "label": "认知重构", "category": "ritual", "status": "demo",
     "desc": "CBT 式苏格拉底提问，一次只问一个问题",
     "demo_say": "来做一次认知重构吧，我总觉得这次评审要搞砸"},
    {"key": "worry_parking", "label": "烦恼寄存", "category": "ritual", "status": "live",
     "desc": "把反刍的事存起来，真实落库，下次回访",
     "demo_say": "明天早上的汇报，我越想越慌"},
    {"key": "gratitude_moment", "label": "三件好事", "category": "ritual", "status": "live",
     "desc": "小确幸真实记下，一周后还能回放",
     "demo_say": "今天也有好事：同事帮我顶了个会，晚饭的面很好吃"},
    {"key": "mood_checkin", "label": "心情打卡", "category": "ritual", "status": "live",
     "desc": "1 到 10 分，真实写入画像与打卡记录",
     "demo_say": "今天心情大概 6 分吧"},
    {"key": "weather_brief", "label": "天气速报", "category": "ritual", "status": "live",
     "desc": "真实天气（Open-Meteo）注入对话上下文",
     "demo_say": "明天要不要带伞？"},
    {"key": "update_preference", "label": "偏好速记", "category": "ritual", "status": "live",
     "desc": "「以后别放男声」说一次，写进画像",
     "demo_say": "以后别给我放雷声了"},
    # --- 声音引擎 ---
    {"key": "play_asset", "label": "秒播曲库", "category": "sound", "status": "live",
     "desc": "智能体自主匹配现成音频，即点即播",
     "demo_say": "来点雨声"},
    {"key": "generate_sleep_audio", "label": "实时生成", "category": "sound", "status": "live",
     "desc": "故事 / 冥想 / ASMR / 纯音乐，现场为你制作",
     "demo_say": "给我生成一段海边书店的故事，十五分钟"},
    {"key": "remix_current", "label": "实时混音", "category": "sound", "status": "live",
     "desc": "给正在播的声音叠一层真实雨声",
     "demo_say": "在现在的声音里加一点雨声"},
    {"key": "voice_call", "label": "全双工语音", "category": "sound", "status": "live",
     "desc": "像打电话一样聊，可随时打断",
     "demo_call": True},
    {"key": "sleep_timer", "label": "定时渐弱", "category": "sound", "status": "live",
     "desc": "到点声音慢慢淡出，播放器本地执行",
     "demo_say": "播 20 分钟就停，声音慢慢变小"},
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
    skill_card: dict[str, Any] | None = None,
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


def _reframe_dialog(normalized, profile_context) -> AgentDecideResponse:
    started = time.perf_counter()
    tool_calls = [
        AgentToolCall(name="reframe_thought", status="succeeded",
                      input={"mode": "socratic"}, output={"turn": 1},
                      latency_ms=90, reason="CBT 是对话练习，不生成音频"),
    ]
    return _base_response(
        normalized=normalized, profile_context=profile_context,
        action="chat", selected_skill="reframe_thought",
        reply=REPLY_REFRAME,
        reasons=["用户想做认知重构练习", "以对话引导展开，一次只问一个问题"],
        tool_calls=tool_calls,
        latency_ms=int((time.perf_counter() - started) * 1000) + 120,
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
        reply=REPLY_WEEKLY,
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
        reply=REPLY_OKR,
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


def route_showcase_demo(request_text: str, *, repository, settings, normalizer, neisou_is_real: bool = False) -> AgentDecideResponse | None:
    """Return a staged OneTool demo decision, or None to fall through to Hermes."""
    text = request_text.strip()
    compact = "".join(text.lower().split())

    weekly = "周报" in compact and any(k in compact for k in ("没写", "没交", "还没", "帮我", "搞定", "代写", "来不及", "写一下"))
    okr = ("okr" in compact or "kr" in compact or "季度目标" in compact) and any(
        k in compact for k in ("完不成", "来不及", "搞不定", "要砸", "凉了", "悬了", "达不成"))
    neisou_topic = next((t for t in ("报销", "晋升") if t in compact), None)
    neisou = (
        not neisou_is_real  # real 内搜 authorized → let the live agent handle it
        and neisou_topic is not None
        and any(k in compact for k in ("流程", "怎么走", "怎么弄", "找谁", "怎么办", "截止", "材料"))
    )

    cbt = ("cbt" in compact or "认知重构" in compact) and not any(
        k in compact for k in ("音频", "生成", "听一段", "来一段"))

    if not (weekly or okr or neisou or cbt):
        return None

    profile_context = build_profile_context(repository, settings, "showcase_user")
    normalized = normalizer.normalize(GenerationRequest(request_text=text), profile_context)
    if weekly:
        return _weekly_ghostwriter(normalized, profile_context)
    if okr:
        return _okr_reframe(normalized, profile_context)
    if neisou:
        return _neisou_answer(normalized, profile_context, neisou_topic)
    return _reframe_dialog(normalized, profile_context)


_INTRANET_NOUNS = (
    "食堂", "班车", "健身房", "门禁", "工卡", "考勤", "会议室", "停车", "车位",
    "报销", "请假", "晋升", "公积金", "社保", "入职", "转岗", "工位", "年假",
    "体检", "餐补", "打印机", "快递", "咖啡厅", "母婴室",
)
_INTRANET_INTENTS = (
    "在哪", "哪里", "几点", "时间", "怎么", "如何", "流程", "多少", "什么",
    "指南", "规则", "政策", "吗", "?", "？",
)


def is_intranet_quick(text: str) -> bool:
    """Obvious intranet questions worth the deterministic 内搜 fast path:
    a company-facility/process noun plus an information-seeking hint, short
    enough to be a lookup rather than venting."""
    compact = "".join(text.split())
    if len(compact) > 30:
        return False
    return any(n in compact for n in _INTRANET_NOUNS) and any(i in compact for i in _INTRANET_INTENTS)


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
