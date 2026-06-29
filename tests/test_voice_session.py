"""Voice dialog session orchestration tests.

Uses fake ASR/LLM/TTS components (no real API calls) to verify:
  - sentence chunking flows LLM -> TTS -> audio events
  - history is committed after a completed turn
  - barge-in: a new final ASR result cancels the in-flight response
Driven via asyncio.run (project has no pytest-asyncio).
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from floppy_backend.services.dialog_llm import DialogTurn
from floppy_backend.services.voice_session import (
    EVENT_ASSISTANT_TEXT,
    EVENT_AUDIO,
    EVENT_AUDIO_ASSET,
    EVENT_AUDIO_JOB,
    EVENT_AUDIO_LOOKUP,
    EVENT_SESSION_STARTED,
    EVENT_SPEECH_END,
    EVENT_STOP_AUDIO,
    EVENT_TURN_END,
    EVENT_USER_TEXT,
    OutboundEvent,
    VoiceSession,
)
from floppy_backend.services.voice_dialog_router import VoiceDialogRoute


def test_volc_asr_prefers_api_key_headers():
    from floppy_backend.config import Settings
    from floppy_backend.providers.volc_asr import VolcStreamASR

    asr = VolcStreamASR(Settings(volc_asr_api_key="api-key-test", volc_asr_app_key="app", volc_asr_access_key="access"))
    headers = asr._headers()

    assert headers["X-Api-Key"] == "api-key-test"
    assert "X-Api-App-Key" not in headers
    assert "X-Api-Access-Key" not in headers
    assert headers["X-Api-Resource-Id"] == "volc.bigasr.sauc.duration"


class FakeASRResult:
    def __init__(self, text: str, is_final: bool):
        self.text = text
        self.is_final = is_final


class FakeASR:
    """Emits a scripted sequence of recognition results, ignoring audio."""

    def __init__(self, results: list[FakeASRResult], gap: float = 0.0):
        self._results = results
        self._gap = gap

    async def stream_recognize(self, audio_iter: AsyncIterator[bytes]):
        # Drain inbound audio in the background so the caller's queue empties.
        async def _drain():
            async for _ in audio_iter:
                pass

        drain = asyncio.create_task(_drain())
        try:
            for result in self._results:
                if self._gap:
                    await asyncio.sleep(self._gap)
                yield result
        finally:
            drain.cancel()


class FakeLLM:
    """Yields fixed sentences for any input; optional per-sentence delay."""

    def __init__(self, sentences: list[str], delay: float = 0.0):
        self._sentences = sentences
        self._delay = delay
        self.calls: list[str] = []

    async def stream_sentences(self, history: list[DialogTurn], user_text: str):
        self.calls.append(user_text)
        for sentence in self._sentences:
            if self._delay:
                await asyncio.sleep(self._delay)
            yield sentence


class FakeTTS:
    """Turns each text chunk into a deterministic audio frame."""

    async def stream_synthesize(self, text_iter, *, voice_style=None, voice_id=None):
        async for text in text_iter:
            yield f"AUDIO[{text}]".encode("utf-8")


class FakeRouter:
    def __init__(self, route: VoiceDialogRoute):
        self.route = route
        self.calls: list[tuple[str, str | None]] = []

    async def __call__(
        self,
        history: list[DialogTurn],
        user_text: str,
        current_asset_id: str | None,
    ) -> VoiceDialogRoute:
        self.calls.append((user_text, current_asset_id))
        return self.route


async def _collect(session: VoiceSession, audio_chunks: list[bytes]) -> list[OutboundEvent]:
    events: list[OutboundEvent] = []

    async def emit(event: OutboundEvent) -> None:
        events.append(event)

    async def audio_in():
        for chunk in audio_chunks:
            yield chunk

    await session.run(audio_in(), emit)
    return events


def test_basic_turn_flows_through_pipeline():
    asr = FakeASR([FakeASRResult("我睡不着", is_final=True)])
    llm = FakeLLM(["别担心。", "我陪着你。"])
    session = VoiceSession(asr=asr, llm=llm, tts=FakeTTS())

    events = asyncio.run(_collect(session, [b"x"]))
    types = [e.type for e in events]

    assert EVENT_USER_TEXT in types
    assert llm.calls == ["我睡不着"]
    assistant_texts = [e.text for e in events if e.type == EVENT_ASSISTANT_TEXT]
    assert assistant_texts == ["别担心。", "我陪着你。"]
    audio = [e.audio for e in events if e.type == EVENT_AUDIO]
    assert audio == [b"AUDIO[\xe5\x88\xab\xe6\x8b\x85\xe5\xbf\x83\xe3\x80\x82]", "AUDIO[我陪着你。]".encode()]
    assert types[-1] == EVENT_TURN_END


def test_history_committed_after_turn():
    asr = FakeASR([FakeASRResult("你好", is_final=True)])
    llm = FakeLLM(["嗨。"])
    session = VoiceSession(asr=asr, llm=llm, tts=FakeTTS())

    asyncio.run(_collect(session, [b"x"]))

    assert len(session.history) == 2
    assert session.history[0] == DialogTurn(role="user", content="你好")
    assert session.history[1] == DialogTurn(role="assistant", content="嗨。")


def test_partial_results_do_not_trigger_response():
    asr = FakeASR([FakeASRResult("我睡", is_final=False), FakeASRResult("我睡不着", is_final=True)])
    llm = FakeLLM(["好。"])
    session = VoiceSession(asr=asr, llm=llm, tts=FakeTTS())

    asyncio.run(_collect(session, [b"x"]))

    # LLM called exactly once, only for the final result.
    assert llm.calls == ["我睡不着"]


def test_events_include_session_turn_and_sequence_metadata():
    asr = FakeASR([FakeASRResult("我睡", is_final=False), FakeASRResult("我睡不着", is_final=True)])
    llm = FakeLLM(["好。"])
    session = VoiceSession(asr=asr, llm=llm, tts=FakeTTS(), session_id="vs_test", user_id="u_test")

    started = session.start_event()
    events = asyncio.run(_collect(session, [b"x"]))
    text_events = [started, *[e for e in events if e.type != EVENT_AUDIO]]
    user_events = [e for e in text_events if e.type == EVENT_USER_TEXT]
    assistant_event = next(e for e in text_events if e.type == EVENT_ASSISTANT_TEXT)
    turn_end = next(e for e in text_events if e.type == EVENT_TURN_END)

    assert started.type == EVENT_SESSION_STARTED
    assert {e.session_id for e in text_events} == {"vs_test"}
    assert {e.user_id for e in text_events} == {"u_test"}
    assert [e.seq for e in text_events] == sorted(e.seq for e in text_events)
    assert all(e.created_at for e in text_events)
    assert user_events[0].turn_id == user_events[1].turn_id
    assert assistant_event.turn_id == user_events[1].turn_id
    assert turn_end.turn_id == user_events[1].turn_id
    assert user_events[0].text_payload()["session_id"] == "vs_test"


def test_barge_in_cancels_in_flight_turn():
    # First final triggers a slow response; second final arrives during it.
    asr = FakeASR(
        [FakeASRResult("第一句", is_final=True), FakeASRResult("打断你", is_final=True)],
        gap=0.05,
    )
    # Slow LLM so the second ASR result lands mid-response.
    llm = FakeLLM(["慢慢的回答。", "还有更多。"], delay=0.2)
    session = VoiceSession(asr=asr, llm=llm, tts=FakeTTS())

    events = asyncio.run(_collect(session, [b"x", b"y"]))

    # Both finals were processed by the LLM (the first got cancelled, second ran).
    assert llm.calls == ["第一句", "打断你"]
    # The first turn was cancelled before committing, so history reflects the
    # second (completed) turn — not two full turns.
    user_turns = [t for t in session.history if t.role == "user"]
    assert "打断你" in [t.content for t in user_turns]


def test_dialog_router_chat_turn_does_not_resolve_audio():
    asr = FakeASR([FakeASRResult("我睡不着", is_final=True)])
    router = FakeRouter(
        VoiceDialogRoute(
            action="chat",
            reply_text="听起来今晚不太容易，我在这里陪你。",
            reasons=["用户在倾诉"],
        )
    )

    async def fail_resolver(request_text: str, audio_type: str, current_asset_id: str | None):
        raise AssertionError("chat route should not resolve audio")

    session = VoiceSession(
        asr=asr,
        tts=FakeTTS(),
        dialog_router=router,
        audio_resolver=fail_resolver,
    )

    events = asyncio.run(_collect(session, [b"x"]))

    assert router.calls == [("我睡不着", None)]
    assert [e.text for e in events if e.type == EVENT_ASSISTANT_TEXT] == ["听起来今晚不太容易，我在这里陪你。"]
    assert not [e for e in events if e.type == EVENT_AUDIO_ASSET]
    assert session.history[-1] == DialogTurn(role="assistant", content="听起来今晚不太容易，我在这里陪你。")


def test_dialog_router_audio_workflow_resolves_asset_after_reply():
    asr = FakeASR([FakeASRResult("放点雨声", is_final=True)])
    router = FakeRouter(
        VoiceDialogRoute(
            action="audio_workflow",
            reply_text="好的，我给你找一段雨声。",
            audio_request_text="给我放雨声，不要人声",
            audio_intent_hint="white_noise",
            reasons=["用户明确要雨声"],
        )
    )
    resolver_calls: list[tuple[str, str, str | None]] = []

    async def resolver(request_text: str, audio_type: str, current_asset_id: str | None):
        resolver_calls.append((request_text, audio_type, current_asset_id))
        return {"url": "http://127.0.0.1/audio/rain.mp3", "title": "夜雨轻敲", "asset_id": "aud_rain"}

    session = VoiceSession(
        asr=asr,
        tts=FakeTTS(),
        dialog_router=router,
        audio_resolver=resolver,
    )

    events = asyncio.run(_collect(session, [b"x"]))
    types = [e.type for e in events]
    asset_events = [e for e in events if e.type == EVENT_AUDIO_ASSET]

    assert router.calls == [("放点雨声", None)]
    assert resolver_calls == [("给我放雨声，不要人声", "white_noise", None)]
    assert types.index(EVENT_SPEECH_END) < types.index(EVENT_AUDIO_LOOKUP) < types.index(EVENT_AUDIO_ASSET) < types.index(EVENT_TURN_END)
    assert len(asset_events) == 1
    assert asset_events[0].url == "http://127.0.0.1/audio/rain.mp3"
    assert asset_events[0].text == "夜雨轻敲"
    assert asset_events[0].audio_type == "white_noise"
    assert asset_events[0].asset_id == "aud_rain"
    assert session.current_asset_id == "aud_rain"


def test_dialog_router_remix_uses_current_asset_context():
    asr = FakeASR([FakeASRResult("加点海浪", is_final=True)])
    router = FakeRouter(
        VoiceDialogRoute(
            action="remix_current",
            reply_text="好的，我给当前音频加一点海浪。",
            audio_request_text="给当前音频加一点海浪",
            audio_intent_hint="white_noise",
        )
    )
    resolver_calls: list[tuple[str, str, str | None]] = []

    async def resolver(request_text: str, audio_type: str, current_asset_id: str | None):
        resolver_calls.append((request_text, audio_type, current_asset_id))
        return {"url": "http://127.0.0.1/audio/remix.mp3", "title": "海浪混音", "asset_id": "aud_remix"}

    session = VoiceSession(
        asr=asr,
        tts=FakeTTS(),
        dialog_router=router,
        audio_resolver=resolver,
        current_asset_id="aud_original",
    )

    events = asyncio.run(_collect(session, [b"x"]))
    asset_events = [e for e in events if e.type == EVENT_AUDIO_ASSET]

    assert router.calls == [("加点海浪", "aud_original")]
    assert resolver_calls == [("给当前音频加一点海浪", "white_noise", "aud_original")]
    assert asset_events[0].asset_id == "aud_remix"
    assert session.current_asset_id == "aud_remix"


def test_dialog_router_generation_job_emits_pollable_job_event():
    asr = FakeASR([FakeASRResult("讲个故事", is_final=True)])
    router = FakeRouter(
        VoiceDialogRoute(
            action="audio_workflow",
            reply_text="好的，我给你准备一段故事。",
            audio_request_text="讲个睡前故事",
            audio_intent_hint="story",
        )
    )

    async def resolver(request_text: str, audio_type: str, current_asset_id: str | None):
        return {"job_id": "job_story", "job_status": "queued", "audio_type": audio_type}

    session = VoiceSession(
        asr=asr,
        tts=FakeTTS(),
        dialog_router=router,
        audio_resolver=resolver,
    )

    events = asyncio.run(_collect(session, [b"x"]))
    types = [e.type for e in events]
    job_events = [e for e in events if e.type == EVENT_AUDIO_JOB]

    assert len(job_events) == 1
    assert types.index(EVENT_SPEECH_END) < types.index(EVENT_AUDIO_LOOKUP) < types.index(EVENT_AUDIO_JOB) < types.index(EVENT_TURN_END)
    assert job_events[0].job_id == "job_story"
    assert job_events[0].job_status == "queued"
    assert job_events[0].audio_type == "story"


def test_dialog_router_stop_audio_emits_control_event_without_resolver():
    asr = FakeASR([FakeASRResult("停止音乐", is_final=True)])
    router = FakeRouter(
        VoiceDialogRoute(
            action="stop_audio",
            reply_text="好的，先帮你停掉。",
        )
    )

    async def fail_resolver(request_text: str, audio_type: str, current_asset_id: str | None):
        raise AssertionError("stop_audio route should not resolve audio")

    session = VoiceSession(
        asr=asr,
        tts=FakeTTS(),
        dialog_router=router,
        audio_resolver=fail_resolver,
        current_asset_id="aud_playing",
    )

    events = asyncio.run(_collect(session, [b"x"]))
    types = [e.type for e in events]

    assert EVENT_STOP_AUDIO in types
    assert EVENT_AUDIO_LOOKUP not in types
    assert EVENT_AUDIO_ASSET not in types
    assert types.index(EVENT_STOP_AUDIO) < types.index(EVENT_ASSISTANT_TEXT) < types.index(EVENT_TURN_END)
    assert session.current_asset_id is None
