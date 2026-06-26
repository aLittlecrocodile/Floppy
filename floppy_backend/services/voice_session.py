"""Full-duplex voice dialog session orchestration.

Wires together streaming ASR -> dialog LLM -> streaming TTS into one
conversational turn loop, with barge-in support (a new user utterance cancels
the in-flight LLM+TTS so the agent stops talking and listens).

Transport-agnostic: the WebSocket endpoint feeds inbound audio frames in and
consumes outbound events (audio + text) out. The ASR/LLM/TTS components are
injected so tests can supply fakes (mirrors the LocalToneAudioProvider pattern).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

from floppy_backend.services.dialog_llm import DialogTurn

# Outbound event types pushed to the client.
EVENT_USER_TEXT = "user_text"          # ASR result (partial/final)
EVENT_ASSISTANT_TEXT = "assistant_text"  # LLM sentence about to be spoken
EVENT_AUDIO = "audio"                  # TTS audio bytes
EVENT_TURN_END = "turn_end"            # assistant finished a turn
EVENT_ERROR = "error"


@dataclass
class OutboundEvent:
    type: str
    text: str | None = None
    audio: bytes | None = None
    is_final: bool = False


class ASRComponent(Protocol):
    def stream_recognize(self, audio_iter: AsyncIterator[bytes]) -> AsyncIterator: ...


class LLMComponent(Protocol):
    def stream_sentences(self, history: list[DialogTurn], user_text: str) -> AsyncIterator[str]: ...


class TTSComponent(Protocol):
    def stream_synthesize(
        self, text_iter: AsyncIterator[str], *, voice_style: str | None = ..., voice_id: str | None = ...
    ) -> AsyncIterator[bytes]: ...


@dataclass
class VoiceSession:
    asr: ASRComponent
    llm: LLMComponent
    tts: TTSComponent
    voice_style: str | None = None
    history: list[DialogTurn] = field(default_factory=list)

    async def _respond(
        self,
        user_text: str,
        emit: Callable[[OutboundEvent], Awaitable[None]],
    ) -> None:
        """Generate one assistant turn: LLM sentences -> TTS audio -> emit.

        Pipelined via a queue so TTS synthesizes sentence N while the LLM is
        still producing sentence N+1. Cancellable for barge-in.
        """
        sentence_queue: asyncio.Queue[str | None] = asyncio.Queue()
        spoken: list[str] = []

        async def _produce_sentences() -> None:
            try:
                async for sentence in self.llm.stream_sentences(self.history, user_text):
                    spoken.append(sentence)
                    await emit(OutboundEvent(type=EVENT_ASSISTANT_TEXT, text=sentence))
                    await sentence_queue.put(sentence)
            finally:
                await sentence_queue.put(None)

        async def _sentence_iter() -> AsyncIterator[str]:
            while True:
                sentence = await sentence_queue.get()
                if sentence is None:
                    return
                yield sentence

        producer = asyncio.create_task(_produce_sentences())
        try:
            async for audio in self.tts.stream_synthesize(_sentence_iter(), voice_style=self.voice_style):
                await emit(OutboundEvent(type=EVENT_AUDIO, audio=audio))
            await producer
        finally:
            if not producer.done():
                producer.cancel()

        # Commit the turn to history once fully spoken (not on barge-in cancel).
        self.history.append(DialogTurn(role="user", content=user_text))
        self.history.append(DialogTurn(role="assistant", content="".join(spoken)))
        await emit(OutboundEvent(type=EVENT_TURN_END, is_final=True))

    async def run(
        self,
        audio_in: AsyncIterator[bytes],
        emit: Callable[[OutboundEvent], Awaitable[None]],
    ) -> None:
        """Drive the session: recognize speech, respond, support barge-in.

        A finalized ASR result triggers a response turn. If a new final result
        arrives while the agent is still responding, the in-flight turn is
        cancelled (barge-in) before starting the new one.
        """
        respond_task: asyncio.Task | None = None
        try:
            async for result in self.asr.stream_recognize(audio_in):
                await emit(
                    OutboundEvent(type=EVENT_USER_TEXT, text=result.text, is_final=result.is_final)
                )
                if not result.is_final or not result.text.strip():
                    continue

                # Barge-in: a new finalized utterance cancels the prior turn.
                if respond_task and not respond_task.done():
                    respond_task.cancel()
                    try:
                        await respond_task
                    except asyncio.CancelledError:
                        pass

                respond_task = asyncio.create_task(self._respond(result.text.strip(), emit))
            # Inbound audio ended; let any final turn complete.
            if respond_task:
                await respond_task
        except Exception as exc:  # noqa: BLE001 — surface to client, don't crash socket
            await emit(OutboundEvent(type=EVENT_ERROR, text=str(exc)))
            if respond_task and not respond_task.done():
                respond_task.cancel()
