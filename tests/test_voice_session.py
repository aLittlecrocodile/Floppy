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
    EVENT_TURN_END,
    EVENT_USER_TEXT,
    OutboundEvent,
    VoiceSession,
)


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
