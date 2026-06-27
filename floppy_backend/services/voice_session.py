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
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4

from floppy_backend.services.dialog_llm import DialogTurn
from floppy_backend.utils import utcnow

# Outbound event types pushed to the client.
EVENT_SESSION_STARTED = "session_started"
EVENT_USER_TEXT = "user_text"          # ASR result (partial/final)
EVENT_ASSISTANT_TEXT = "assistant_text"  # LLM sentence about to be spoken
EVENT_AUDIO = "audio"                  # TTS audio bytes
EVENT_AUDIO_ASSET = "audio_asset"      # a sleep-audio asset to play (url + meta)
EVENT_TURN_END = "turn_end"            # assistant finished a turn
EVENT_ERROR = "error"

# Matches a leading [AUDIO:type] marker the dialog LLM emits when the user wants
# to hear a sleep-audio asset. Tolerant of half/full-width brackets and spacing.
_AUDIO_MARKER_RE = re.compile(r"^\s*[\[【]\s*AUDIO\s*[:：]\s*([a-zA-Z_]+)\s*[\]】]\s*", re.IGNORECASE)


@dataclass
class OutboundEvent:
    type: str
    text: str | None = None
    audio: bytes | None = None
    is_final: bool = False
    session_id: str | None = None
    user_id: str | None = None
    turn_id: str | None = None
    seq: int | None = None
    created_at: str | None = None
    url: str | None = None         # audio_asset: playback URL
    audio_type: str | None = None  # audio_asset: story/meditation/...

    def text_payload(self) -> dict:
        payload = {
            "type": self.type,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "turn_id": self.turn_id,
            "seq": self.seq,
            "text": self.text,
            "is_final": self.is_final,
            "created_at": self.created_at,
        }
        if self.type == EVENT_AUDIO_ASSET:
            payload["url"] = self.url
            payload["audio_type"] = self.audio_type
        return payload


class ASRComponent(Protocol):
    def stream_recognize(self, audio_iter: AsyncIterator[bytes]) -> AsyncIterator: ...


class LLMComponent(Protocol):
    def stream_sentences(self, history: list[DialogTurn], user_text: str) -> AsyncIterator[str]: ...


class TTSComponent(Protocol):
    def stream_synthesize(
        self, text_iter: AsyncIterator[str], *, voice_style: str | None = ..., voice_id: str | None = ...
    ) -> AsyncIterator[bytes]: ...


# Resolves a user request + desired audio_type into a playable asset dict
# ({"url": ..., "title": ..., "audio_type": ...}) or None if nothing matched.
# Injected by the transport layer so VoiceSession stays decoupled from app state.
AudioResolver = Callable[[str, str], Awaitable[dict | None]]


@dataclass
class VoiceSession:
    asr: ASRComponent
    llm: LLMComponent
    tts: TTSComponent
    session_id: str = field(default_factory=lambda: f"vs_{uuid4().hex}")
    user_id: str | None = None
    voice_style: str | None = None
    history: list[DialogTurn] = field(default_factory=list)
    audio_resolver: AudioResolver | None = None
    _seq: int = 0
    _turn_index: int = 0

    def start_event(self) -> OutboundEvent:
        return self._event(EVENT_SESSION_STARTED, is_final=True)

    def _next_turn_id(self) -> str:
        self._turn_index += 1
        return f"turn_{self._turn_index:04d}"

    def _event(
        self,
        event_type: str,
        *,
        text: str | None = None,
        audio: bytes | None = None,
        is_final: bool = False,
        turn_id: str | None = None,
        url: str | None = None,
        audio_type: str | None = None,
    ) -> OutboundEvent:
        self._seq += 1
        return OutboundEvent(
            type=event_type,
            text=text,
            audio=audio,
            is_final=is_final,
            session_id=self.session_id,
            user_id=self.user_id,
            turn_id=turn_id,
            seq=self._seq,
            created_at=utcnow().isoformat(),
            url=url,
            audio_type=audio_type,
        )

    async def _respond(
        self,
        user_text: str,
        turn_id: str,
        emit: Callable[[OutboundEvent], Awaitable[None]],
    ) -> None:
        """Generate one assistant turn: LLM sentences -> TTS audio -> emit.

        Pipelined via a queue so TTS synthesizes sentence N while the LLM is
        still producing sentence N+1. Cancellable for barge-in.

        If the first sentence carries an [AUDIO:type] marker, it is stripped
        (the guidance text is still spoken) and — after the spoken reply — the
        injected audio_resolver is queried; a matching asset is pushed as an
        EVENT_AUDIO_ASSET so the client can play a real sleep-audio asset.
        """
        sentence_queue: asyncio.Queue[str | None] = asyncio.Queue()
        spoken: list[str] = []
        detected = {"audio_type": None}  # set from the first sentence's marker

        async def _produce_sentences() -> None:
            first = True
            try:
                async for sentence in self.llm.stream_sentences(self.history, user_text):
                    if first:
                        first = False
                        match = _AUDIO_MARKER_RE.match(sentence)
                        if match:
                            detected["audio_type"] = match.group(1).lower()
                            sentence = sentence[match.end():].strip()
                            if not sentence:
                                continue  # marker-only chunk, nothing to speak
                    spoken.append(sentence)
                    await emit(self._event(EVENT_ASSISTANT_TEXT, text=sentence, turn_id=turn_id))
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
                await emit(self._event(EVENT_AUDIO, audio=audio, turn_id=turn_id))
            await producer
        finally:
            if not producer.done():
                producer.cancel()

        # Commit the turn to history once fully spoken (not on barge-in cancel).
        self.history.append(DialogTurn(role="user", content=user_text))
        self.history.append(DialogTurn(role="assistant", content="".join(spoken)))

        # Resolve and push a sleep-audio asset if the LLM signalled one.
        if detected["audio_type"] and self.audio_resolver is not None:
            try:
                asset = await self.audio_resolver(user_text, detected["audio_type"])
            except Exception:  # noqa: BLE001 — resolution failure shouldn't break the turn
                asset = None
            if asset and asset.get("url"):
                await emit(self._event(
                    EVENT_AUDIO_ASSET,
                    text=asset.get("title"),
                    url=asset["url"],
                    audio_type=detected["audio_type"],
                    turn_id=turn_id,
                ))

        await emit(self._event(EVENT_TURN_END, is_final=True, turn_id=turn_id))

    async def run_utterance(
        self,
        audio_in: AsyncIterator[bytes],
        emit: Callable[[OutboundEvent], Awaitable[None]],
    ) -> None:
        """Process ONE utterance: recognize a single audio segment, then respond.

        Used by the push-to-talk Demo where each "press-and-hold" is one
        utterance (one ASR connection). history persists across calls on the
        same VoiceSession, giving multi-turn context.
        """
        final_text = ""
        try:
            asr_turn_id = self._next_turn_id()
            async for result in self.asr.stream_recognize(audio_in):
                await emit(self._event(EVENT_USER_TEXT, text=result.text, is_final=result.is_final, turn_id=asr_turn_id))
                if result.text.strip():
                    final_text = result.text.strip()
            if final_text:
                await self._respond(final_text, asr_turn_id, emit)
        except Exception as exc:  # noqa: BLE001 — surface to client, don't crash socket
            await emit(self._event(EVENT_ERROR, text=str(exc)))

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
        asr_turn_id: str | None = None
        try:
            async for result in self.asr.stream_recognize(audio_in):
                if result.text.strip() and asr_turn_id is None:
                    asr_turn_id = self._next_turn_id()

                turn_id = asr_turn_id
                await emit(self._event(EVENT_USER_TEXT, text=result.text, is_final=result.is_final, turn_id=turn_id))
                if not result.is_final or not result.text.strip():
                    continue

                # Barge-in: a new finalized utterance cancels the prior turn.
                if respond_task and not respond_task.done():
                    respond_task.cancel()
                    try:
                        await respond_task
                    except asyncio.CancelledError:
                        pass

                respond_task = asyncio.create_task(self._respond(result.text.strip(), turn_id or self._next_turn_id(), emit))
                asr_turn_id = None
            # Inbound audio ended; let any final turn complete.
            if respond_task:
                await respond_task
        except Exception as exc:  # noqa: BLE001 — surface to client, don't crash socket
            await emit(self._event(EVENT_ERROR, text=str(exc)))
            if respond_task and not respond_task.done():
                respond_task.cancel()
