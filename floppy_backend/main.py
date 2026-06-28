from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import asyncio
import json
import re
import time
import urllib.request

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from floppy_backend.config import Settings, get_settings
from floppy_backend.db import connect, initialize
from floppy_backend.demo_page import DEMO_HTML
from floppy_backend.models import (
    AgentDecideRequest,
    AgentDecideResponse,
    AssetRemixable,
    AssetSearchRequest,
    AssetSearchResponse,
    AudioType,
    EventIn,
    GenerationBudget,
    GenerationJob,
    GenerationJobCreateResponse,
    GenerationRequest,
    GenerationResponse,
    MixParams,
    NormalizeRequestIn,
    NormalizedRequestOut,
    PlaybackFeedbackIn,
    PlaybackRecord,
    PlaybackStartIn,
    ProfileCheckinIn,
    ProfileContext,
    ProfileLevel,
    Recommendation,
    RemixJob,
    RemixRequestIn,
    RemixSession,
    RemixSessionCreateIn,
    RemixSessionPatchIn,
    UserProfile,
    UserProfileIn,
    UserQuestionnaire,
    UserQuestionnaireIn,
    AudioItem,
    AudioLibrary,
    UploadItem,
    HistoryReportIn,
    HistoryProgressPatchIn,
    VoiceIntentIn,
    VoiceIntentResponse,
)
from floppy_backend.providers.audio import build_audio_provider
from floppy_backend.repositories import Repository
from floppy_backend.seed import seed_assets
from floppy_backend.services.generation import BudgetExceededError, GenerationService
from floppy_backend.services.assets import is_placeholder_created_by
from floppy_backend.services.normalizer import RequestNormalizer
from floppy_backend.services.profile import ProfileService
from floppy_backend.services.query_planner import build_query_planner
from floppy_backend.services.recommendation import RecommendationService
from floppy_backend.services.remix import RemixService
from floppy_backend.services.script import SleepScriptService
from floppy_backend.services.agent_graph import AgentGraphBuilder
from floppy_backend.services.audio_page import (
    asset_to_audio_item,
    category_for,
    upload_row_to_item,
)
from floppy_backend.storage import LocalFileStorage


class AppState:
    repository: Repository
    storage: LocalFileStorage
    profile_service: ProfileService
    recommendation_service: RecommendationService
    generation_service: GenerationService
    remix_service: RemixService
    agent_graph: AgentGraphBuilder
    agent_runtime: object


state = AppState()


class _ConversationTracker:
    """Server-side latest-wins guard for voice intents.

    Tracks the highest turnIndex seen per conversationId so that a stale turn
    (one the client has already superseded by speaking again) can skip the
    expensive generation path instead of burning provider quota on a result the
    client will discard anyway. In-memory only — process-local, which is fine
    because latest-wins is best-effort and the client is the source of truth."""

    def __init__(self) -> None:
        from threading import Lock
        self._lock = Lock()
        self._latest: dict[str, int] = {}

    def observe(self, conversation_id: str, turn_index: int) -> int:
        """Record this turn and return the current latest turnIndex for the
        conversation (>= turn_index)."""
        with self._lock:
            latest = max(self._latest.get(conversation_id, -1), turn_index)
            self._latest[conversation_id] = latest
            return latest

    def is_superseded(self, conversation_id: str, turn_index: int) -> bool:
        with self._lock:
            return turn_index < self._latest.get(conversation_id, -1)


conversation_tracker = _ConversationTracker()



@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    conn = connect(settings.database_path)
    initialize(conn)
    repository = Repository(conn)
    storage = LocalFileStorage(settings.storage_dir, settings.public_base_url)
    recommendation_service = RecommendationService(repository, settings=settings)
    state.repository = repository
    state.storage = storage
    state.profile_service = ProfileService(repository)
    state.recommendation_service = recommendation_service

    # Resolve a shared LLM credential for the directive planner + script writer.
    # They reuse the query planner / dialog creds; falls back to template-only
    # generation when no key is configured.
    _llm_key = settings.query_planner_api_key or settings.dialog_llm_api_key
    _llm_base = settings.dialog_llm_base_url or settings.query_planner_base_url
    _llm_model = settings.dialog_llm_model or settings.query_planner_model
    script_writer = None
    directive_planner = None
    if settings.directive_planner_enabled and _llm_key:
        from floppy_backend.services.directive_planner import DirectivePlanner
        from floppy_backend.services.script_writer import LLMScriptWriter
        script_writer = LLMScriptWriter(
            api_key=_llm_key,
            base_url=_llm_base,
            model=_llm_model,
            timeout_sec=settings.script_writer_timeout_sec,
            max_tokens=settings.script_writer_max_tokens,
        )
        directive_planner = DirectivePlanner(
            api_key=_llm_key,
            base_url=_llm_base,
            model=_llm_model,
            timeout_sec=settings.directive_planner_timeout_sec,
            max_tokens=settings.directive_planner_max_tokens,
            confidence_threshold=settings.directive_planner_confidence_threshold,
        )

    state.generation_service = GenerationService(
        repository=repository,
        storage=storage,
        provider=build_audio_provider(settings),
        normalizer=RequestNormalizer(),
        recommendation_service=recommendation_service,
        script_service=SleepScriptService(script_writer=script_writer),
        settings=settings,
    )
    state.remix_service = RemixService(repository, storage)
    state.agent_graph = AgentGraphBuilder(
        repository=repository,
        storage=storage,
        normalizer=state.generation_service.normalizer,
        recommendation_service=recommendation_service,
        generation_service=state.generation_service,
        settings=settings,
        query_planner=build_query_planner(
            settings.query_planner,
            api_key=settings.query_planner_api_key,
            base_url=settings.query_planner_base_url,
            model=settings.query_planner_model,
            timeout_sec=settings.query_planner_timeout_sec,
            max_tokens=settings.query_planner_max_tokens,
        ),
        remix_service=state.remix_service,
        directive_planner=directive_planner,
    )
    if settings.agent_runtime == "local":
        state.agent_runtime = state.agent_graph
    elif settings.agent_runtime == "hermes":
        from floppy_backend.services.hermes_agent import HermesAgentRuntime
        state.agent_runtime = HermesAgentRuntime(
            repository=repository,
            storage=storage,
            normalizer=state.generation_service.normalizer,
            recommendation_service=recommendation_service,
            generation_service=state.generation_service,
            remix_service=state.remix_service,
            settings=settings,
            local_agent=state.agent_graph,
        )
    else:
        raise RuntimeError(f"unsupported FLOPPY_AGENT_RUNTIME={settings.agent_runtime!r}")
    # Seed the catalog once at startup (idempotent) so voice/demo requests
    # don't pay the ~60s seeding cost on their first call.
    try:
        seed_assets(repository, storage, max_duration_sec=settings.local_provider_max_duration_sec)
    except Exception:  # noqa: BLE001 — seeding is best-effort at startup
        pass
    yield
    conn.close()


app = FastAPI(title="Floppy Backend MVP", version="0.1.0", lifespan=lifespan)

# Dev CORS: 前端跑在其他机器上，开发阶段放开所有来源。
# allow_origin_regex=".*" 配合 allow_credentials=True 可让浏览器带凭证跨域；
# 上线前应收紧为具体前端域名白名单。
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def repo() -> Repository:
    return state.repository


def storage() -> LocalFileStorage:
    return state.storage


@app.get("/health")
def health(settings: Settings = Depends(get_settings)):
    return {"status": "ok", "app": settings.app_name}


# --- Speech-to-text (ASR) for the Android home screen ---
# Two endpoints, both backed by the same Volcengine streaming ASR client:
#   1. WebSocket /v1/speech/stream  — primary: client streams 16k/mono PCM,
#      server returns partial/final text live.
#   2. POST /v1/speech/transcriptions — fallback: client uploads a whole m4a
#      file, server decodes to PCM via ffmpeg and returns the final text.

_ASR_PCM_CHUNK = 16000  # ~0.5s of 16k/mono/16bit PCM per frame fed to Volc


async def _decode_to_pcm_chunks(data: bytes, chunk_size: int = _ASR_PCM_CHUNK):
    """Decode an arbitrary audio container (m4a/aac/mp3/wav...) to raw 16k
    mono s16le PCM via ffmpeg, yielding fixed-size chunks. ffmpeg reads from
    stdin and writes PCM to stdout — no temp files."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", "pipe:0",
        "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1", "-ar", "16000",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def _feed():
        try:
            proc.stdin.write(data)
            await proc.stdin.drain()
        finally:
            proc.stdin.close()

    feed_task = asyncio.create_task(_feed())
    try:
        while True:
            chunk = await proc.stdout.read(chunk_size)
            if not chunk:
                break
            yield chunk
    finally:
        await feed_task
        err = await proc.stderr.read()
        rc = await proc.wait()
        if rc != 0:
            raise RuntimeError(f"ffmpeg decode failed (rc={rc}): {err.decode('utf-8', 'replace')[:300]}")


async def _transcribe_pcm_stream(pcm_iter) -> str:
    """Run a PCM async-iterator through Volc streaming ASR and return the final
    cumulative text (best effort: keeps the longest text seen)."""
    from floppy_backend.providers.volc_asr import VolcStreamASR

    asr = VolcStreamASR(get_settings())
    final_text = ""
    async for result in asr.stream_recognize(pcm_iter):
        if result.text:
            final_text = result.text
    return final_text


@app.post("/v1/speech/transcriptions")
async def speech_transcriptions(
    file: UploadFile = File(...),
    locale: str = Form("zh-CN"),
    source: str = Form("android_home"),
):
    """Fallback ASR: upload a whole audio file (Android sends m4a / audio/mp4),
    decode to PCM, recognize, return {"text": "..."}. On failure returns 5xx
    with a message so the client can show「语音转文字失败」."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty audio file")
    try:
        pcm_iter = _decode_to_pcm_chunks(data)
        text = await _transcribe_pcm_stream(pcm_iter)
    except Exception as exc:  # noqa: BLE001 — surface as 5xx for the client
        raise HTTPException(status_code=500, detail=f"transcription failed: {exc}") from exc
    # text may be "" when nothing was recognized — that's a valid response.
    return {"text": text}


@app.websocket("/v1/speech/stream")
async def speech_stream(websocket: WebSocket):
    """Primary ASR: client streams 16k/mono/s16le PCM, server returns live
    partial/final text.

    Protocol:
      - Client → start frame:  {"type":"start","locale":"zh-CN","sample_rate":16000,"encoding":"pcm_s16le","channels":1}
      - Client → binary frames: raw PCM 16-bit LE chunks
      - Client → stop frame:   {"type":"stop"}
      - Server → {"type":"partial","text":"..."} while recognizing
      - Server → {"type":"final","text":"..."} when a sentence finalizes / on stop
      - Server → {"type":"error","message":"识别失败"} on failure
    Server does not close on stop until a final/error has been sent.
    """
    from floppy_backend.providers.volc_asr import VolcStreamASR

    await websocket.accept()

    pcm_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def _pcm_iter():
        while True:
            chunk = await pcm_queue.get()
            if chunk is None:
                return
            yield chunk

    async def _recognize():
        """Consume the PCM queue through Volc ASR, push partial/final back."""
        try:
            asr = VolcStreamASR(get_settings())
            last_text = ""
            async for result in asr.stream_recognize(_pcm_iter()):
                if result.is_final:
                    await websocket.send_text(json.dumps(
                        {"type": "final", "text": result.text or last_text}, ensure_ascii=False))
                    last_text = ""
                elif result.text and result.text != last_text:
                    last_text = result.text
                    await websocket.send_text(json.dumps(
                        {"type": "partial", "text": result.text}, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            try:
                await websocket.send_text(json.dumps(
                    {"type": "error", "message": f"识别失败: {exc}"}, ensure_ascii=False))
            except Exception:  # noqa: BLE001 — socket may already be gone
                pass

    recognize_task: asyncio.Task | None = None
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            # Text control frames.
            if (text := message.get("text")) is not None:
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    continue
                mtype = payload.get("type")
                if mtype == "start":
                    if recognize_task is None:
                        recognize_task = asyncio.create_task(_recognize())
                elif mtype == "stop":
                    # Signal end-of-audio; ASR will emit its final, then we stop.
                    await pcm_queue.put(None)
                    if recognize_task is not None:
                        await recognize_task
                        recognize_task = None
                    # Tell the client we're done with this utterance; keep socket
                    # open in case the client wants another turn.
                    break
            # Binary audio frames.
            elif (chunk := message.get("bytes")) is not None:
                if recognize_task is None:
                    # Tolerate clients that stream before sending start.
                    recognize_task = asyncio.create_task(_recognize())
                await pcm_queue.put(chunk)
    except WebSocketDisconnect:
        pass
    finally:
        await pcm_queue.put(None)
        if recognize_task is not None:
            recognize_task.cancel()
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass



def _ensure_demo_profile(user_id: str) -> None:
    """Make sure a user has a profile (catalog is seeded at startup).

    Voice dialog and /demo/chat both need a profile for agent_graph to run;
    new ad-hoc users (e.g. a browser session) get a sensible sleep default.
    """
    if state.repository.get_profile(user_id) is None:
        state.profile_service.upsert_profile(
            user_id,
            UserProfileIn(
                audio_type_preferences=[AudioType.MEDITATION, AudioType.WHITE_NOISE, AudioType.STORY],
                voice_preferences=["warm_female"],
                background_preferences=["rain_soft"],
                duration_preference_min=15,
                stress_level=ProfileLevel.HIGH,
                anxiety_level=ProfileLevel.HIGH,
                avg_sleep_latency_min=40,
                mood_tags=["anxiety_relief"],
            ),
        )


def _resolve_audio_asset(user_id: str, request_text: str) -> dict | None:
    """Run agent_graph to match/generate a playable sleep-audio asset.

    Returns {"url", "title", "audio_type"} or None. Mirrors /demo/chat's
    play_asset / generate_job handling. Runs synchronously (call via
    asyncio.to_thread from the async ws handler).
    """
    response = state.agent_runtime.run(
        AgentDecideRequest(user_id=user_id, request_text=request_text, generation_allowed=True)
    )
    if response.action == "play_asset" and response.asset:
        return {"url": response.asset.playback_url, "title": response.asset.title}
    if response.action == "generate_job" and response.job_id:
        state.generation_service.run_job(
            response.job_id, user_id, GenerationRequest(request_text=request_text, force_generate=True)
        )
        for _ in range(10):
            job = state.repository.get_generation_job(response.job_id)
            if job and job.status in {"succeeded", "failed"}:
                if job.status == "succeeded" and job.asset:
                    return {"url": state.storage.public_url(job.asset.object_key), "title": job.asset.title}
                break
            time.sleep(0.2)
    return None


@app.websocket("/voice/ws")
async def voice_ws(websocket: WebSocket):
    """Realtime full-duplex voice dialog.

    Protocol (see docs/contracts/voice_dialog_ws.md):
      - Client connects with ?token=<shared-secret> when FLOPPY_VOICE_WS_TOKEN is set.
      - Client sends binary frames = raw PCM (16k/mono/16bit) audio chunks.
      - Client sends {"type":"utterance_end"} to finalize the CURRENT utterance
        (triggers recognition + reply) while keeping the connection open for the
        next turn — multi-turn dialog with shared history.
      - Client sends {"type":"stop"} to end the whole session.
      - Server sends text frames for transcripts/assistant text/control, and
        binary frames for TTS audio (mp3 chunks).
    """
    settings = get_settings()
    token = websocket.query_params.get("token")
    user_id = websocket.query_params.get("user_id")
    if settings.voice_ws_token and token != settings.voice_ws_token:
        await websocket.close(code=4401)
        return
    await websocket.accept()

    # Lazy imports keep optional voice deps out of the core startup path.
    from floppy_backend.providers.minimax_stream_tts import MiniMaxStreamTTS
    from floppy_backend.providers.volc_asr import VolcStreamASR
    from floppy_backend.services.dialog_llm import DialogLLM
    from floppy_backend.services.voice_session import EVENT_AUDIO, OutboundEvent, VoiceSession

    # Resolve a sleep-audio asset via agent_graph (off the event loop).
    resolve_user_id = user_id or "voice_demo_user"
    await asyncio.to_thread(_ensure_demo_profile, resolve_user_id)

    async def _audio_resolver(request_text: str, audio_type: str) -> dict | None:
        asset = await asyncio.to_thread(_resolve_audio_asset, resolve_user_id, request_text)
        if asset:
            asset.setdefault("audio_type", audio_type)
        return asset

    try:
        session = VoiceSession(
            asr=VolcStreamASR(settings),
            llm=DialogLLM(settings),
            tts=MiniMaxStreamTTS(settings),
            user_id=user_id,
            voice_style=websocket.query_params.get("voice_style"),
            audio_resolver=_audio_resolver,
        )
    except Exception as exc:  # noqa: BLE001 — config/credential errors
        await websocket.send_text(json.dumps({"type": "error", "text": str(exc)}))
        await websocket.close(code=1011)
        return

    async def _emit(event: OutboundEvent) -> None:
        if event.type == EVENT_AUDIO and event.audio is not None:
            await websocket.send_bytes(event.audio)
        else:
            await websocket.send_text(json.dumps(event.text_payload(), ensure_ascii=False))

    await _emit(session.start_event())

    # One audio queue per utterance; a new queue starts when the previous
    # utterance is finalized. The session processes utterances serially.
    audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    utterance_task: asyncio.Task | None = None

    async def _audio_in(queue: asyncio.Queue[bytes | None]):
        while True:
            chunk = await queue.get()
            if chunk is None:
                return
            yield chunk

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if (data := message.get("bytes")) is not None:
                # Start an utterance lazily on first audio frame.
                if utterance_task is None or utterance_task.done():
                    audio_queue = asyncio.Queue()
                    utterance_task = asyncio.create_task(session.run_utterance(_audio_in(audio_queue), _emit))
                await audio_queue.put(data)
            elif (text := message.get("text")) is not None:
                try:
                    ctrl = json.loads(text)
                except json.JSONDecodeError:
                    continue
                ctrl_type = ctrl.get("type")
                if ctrl_type == "utterance_end":
                    # Finalize current utterance; wait for the full reply so the
                    # next utterance sees updated history.
                    await audio_queue.put(None)
                    if utterance_task:
                        await utterance_task
                elif ctrl_type == "stop":
                    await audio_queue.put(None)
                    if utterance_task:
                        await utterance_task
                    break
    except WebSocketDisconnect:
        pass
    finally:
        await audio_queue.put(None)
        if utterance_task and not utterance_task.done():
            try:
                await asyncio.wait_for(utterance_task, timeout=30)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                utterance_task.cancel()


@app.get("/demo", response_class=HTMLResponse)
def demo_page():
    return DEMO_HTML


@app.get("/voice", response_class=HTMLResponse)
def voice_page():
    from floppy_backend.voice_page import VOICE_HTML
    from floppy_backend.voice_script import VOICE_SCRIPT
    return VOICE_HTML.replace("__SCRIPT__", VOICE_SCRIPT)


# Strip the [AUDIO:type] routing marker the dialog prompt emits for the voice
# stream — Chat only needs the natural-language sentence, not the marker.
_AUDIO_MARKER_RE = re.compile(r"^\s*\[AUDIO:[^\]]*\]\s*")


def _chat_reply_fallback(action: str) -> str:
    """Template reply used when the LLM is unavailable, so reply_text is never
    null. Tone matches dialog_system_prompt (gentle, 1 short sentence)."""
    if action == "generate_job":
        return "好的，我正在为你准备一段专属的助眠音频，稍等一下。"
    return "好的，给你找了一段适合现在听的音频，慢慢放松下来。"


def _generate_reply_text(request_text: str, action: str, settings: Settings) -> str:
    """Synchronously ask the dialog LLM for a chatbot-style reply, reusing the
    dialog system prompt. Returns a template fallback on any failure so the
    field is always populated. The [AUDIO:type] marker is stripped."""
    api_key = settings.dialog_llm_api_key or settings.query_planner_api_key
    if not api_key:
        return _chat_reply_fallback(action)

    base_url = (settings.dialog_llm_base_url or settings.query_planner_base_url).rstrip("/")
    model = settings.dialog_llm_model or settings.query_planner_model
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": settings.dialog_system_prompt},
            {"role": "user", "content": request_text},
        ],
        "temperature": settings.dialog_temperature,
        "max_tokens": settings.dialog_max_tokens,
        "stream": False,
    }
    try:
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=settings.query_planner_timeout_sec) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        choice = data["choices"][0]
        content = (choice["message"].get("content") or "").strip()
        if not content:
            content = (choice["message"].get("reasoning_content") or "").strip()
    except Exception:  # noqa: BLE001 — reply is best-effort; fall back to template
        return _chat_reply_fallback(action)

    content = _AUDIO_MARKER_RE.sub("", content).strip()
    return content or _chat_reply_fallback(action)


@app.post("/demo/chat")
def demo_chat(payload: dict):
    request_text = str(payload.get("request_text", "")).strip()
    if len(request_text) < 2:
        raise HTTPException(status_code=400, detail="request_text is required")

    seed_assets(state.repository, state.storage, max_duration_sec=get_settings().local_provider_max_duration_sec)
    demo_user = "demo_user"
    state.profile_service.upsert_profile(
        demo_user,
        UserProfileIn(
            audio_type_preferences=[AudioType.MEDITATION, AudioType.WHITE_NOISE, AudioType.STORY],
            voice_preferences=["warm_female"],
            background_preferences=["rain_soft"],
            duration_preference_min=15,
            stress_level=ProfileLevel.HIGH,
            anxiety_level=ProfileLevel.HIGH,
            avg_sleep_latency_min=40,
            mood_tags=["anxiety_relief"],
        ),
    )

    response, audio_url, job, asset_data, is_placeholder, reply_text = _run_chat_decision(
        demo_user, request_text
    )

    return {
        "action": response.action,
        "audio_url": audio_url,
        "asset": asset_data,
        "reply_text": reply_text,
        "is_placeholder": is_placeholder,
        "job_id": response.job_id,
        "job_status": job.status if job else None,
        "best_score": response.search.best_score,
        "hit": response.search.hit,
        "threshold": response.search.threshold,
        "reasons": response.reasons,
        "planner_meta": response.planner_meta.model_dump(mode="json") if response.planner_meta else None,
    }


def _run_chat_decision(user_id: str, request_text: str) -> tuple:
    """Shared agent decision + (optional) synchronous generation used by both
    /demo/chat and /voice/intent. Returns (response, audio_url, job, asset_data,
    is_placeholder, reply_text)."""
    response = state.agent_runtime.run(
        AgentDecideRequest(user_id=user_id, request_text=request_text, generation_allowed=True)
    )
    audio_url = response.asset.playback_url if response.asset else None

    job = None
    if response.action == "generate_job" and response.job_id:
        state.generation_service.run_job(
            response.job_id, user_id, GenerationRequest(request_text=request_text, force_generate=True)
        )
        for _ in range(5):
            job = state.repository.get_generation_job(response.job_id)
            if job and job.status in {"succeeded", "failed"}:
                break
            time.sleep(0.2)
        if job and job.asset:
            audio_url = state.storage.public_url(job.asset.object_key)

    asset_data = response.asset.model_dump(mode="json") if response.asset else (
        job.asset.model_dump(mode="json") if job and job.asset else None
    )
    is_placeholder = bool(asset_data and is_placeholder_created_by(asset_data.get("created_by")))
    reply_text = _generate_reply_text(request_text, response.action, get_settings())
    return response, audio_url, job, asset_data, is_placeholder, reply_text


@app.post("/voice/intent", response_model=VoiceIntentResponse)
def voice_intent(payload: VoiceIntentIn):
    """Home-screen voice intent endpoint with latest-wins correlation.

    The backend echoes conversationId / clientRequestId / turnIndex verbatim so
    the client can discard stale responses. Server-side latest-wins: a turn that
    has already been superseded by a newer turn in the same conversation skips
    the costly generation step (action="superseded"), saving provider quota on
    a result the client would drop anyway. supersedesRequestId is advisory."""
    text = payload.text.strip()
    if len(text) < 1:
        raise HTTPException(status_code=400, detail="text is required")

    # Register this turn; if a newer turn already arrived, short-circuit.
    conversation_tracker.observe(payload.conversationId, payload.turnIndex)
    if conversation_tracker.is_superseded(payload.conversationId, payload.turnIndex):
        return VoiceIntentResponse(
            conversationId=payload.conversationId,
            clientRequestId=payload.clientRequestId,
            turnIndex=payload.turnIndex,
            reply="",
            audio_url=None,
            asset=None,
            action="superseded",
            hit=False,
            best_score=None,
            reasons=["已被更新的语音请求取代"],
        )

    response, audio_url, job, asset_data, _is_placeholder, reply_text = _run_chat_decision(
        payload.user_id, text
    )

    # The user may have spoken again while we were generating; if so, drop the
    # result rather than returning a stale audio that overwrites home state.
    if conversation_tracker.is_superseded(payload.conversationId, payload.turnIndex):
        return VoiceIntentResponse(
            conversationId=payload.conversationId,
            clientRequestId=payload.clientRequestId,
            turnIndex=payload.turnIndex,
            reply="",
            audio_url=None,
            asset=None,
            action="superseded",
            hit=False,
            best_score=None,
            reasons=["已被更新的语音请求取代"],
        )

    audio_item = None
    if response.asset is not None:
        audio_item = asset_to_audio_item(
            response.asset, state.storage,
            source="Generated" if response.action == "generate_job" else "Library",
        )
    elif job is not None and job.asset is not None:
        audio_item = asset_to_audio_item(job.asset, state.storage, source="Generated")

    return VoiceIntentResponse(
        conversationId=payload.conversationId,
        clientRequestId=payload.clientRequestId,
        turnIndex=payload.turnIndex,
        reply=reply_text,
        audio_url=audio_url,
        asset=audio_item,
        action=response.action,
        hit=response.search.hit,
        best_score=response.search.best_score,
        reasons=response.reasons,
    )


@app.post("/admin/seed")
def seed():
    created = seed_assets(state.repository, state.storage, max_duration_sec=get_settings().local_provider_max_duration_sec)
    return {"created_or_updated": created}


@app.put("/users/{user_id}/profile", response_model=UserProfile)
def upsert_profile(user_id: str, profile: UserProfileIn):
    return state.profile_service.upsert_profile(user_id, profile)


@app.get("/users/{user_id}/profile", response_model=UserProfile)
def get_profile(user_id: str, repository: Repository = Depends(repo)):
    profile = repository.get_profile(user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="profile not found")
    return profile


@app.post("/users/{user_id}/profile/checkin", response_model=UserProfile)
def update_profile_signal(user_id: str, checkin: ProfileCheckinIn, repository: Repository = Depends(repo)):
    return repository.update_profile_checkin(user_id, checkin)


@app.get("/users/{user_id}/profile/context", response_model=ProfileContext)
def get_profile_context(user_id: str, settings: Settings = Depends(get_settings), repository: Repository = Depends(repo)):
    profile = repository.get_profile(user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="profile not found")
    used_chars, used_count = repository.generation_usage_since(user_id)
    return ProfileContext(
        **profile.model_dump(),
        generation_budget=GenerationBudget(
            daily_remaining_chars=max(0, settings.daily_char_budget - used_chars),
            daily_generate_count_remaining=max(0, settings.daily_generate_count - used_count),
        ),
    )


@app.post("/normalize", response_model=NormalizedRequestOut)
def normalize_request(payload: NormalizeRequestIn, repository: Repository = Depends(repo)):
    profile = repository.get_profile(payload.user_id) if payload.user_id else None
    normalized = state.generation_service.normalizer.normalize(
        GenerationRequest(request_text=payload.request_text, duration_preference_min=payload.duration_preference_min),
        profile,
    )
    return NormalizedRequestOut(normalized_request=normalized, cache_key=state.generation_service.cache_key_for(normalized))


@app.post("/assets/search", response_model=AssetSearchResponse)
def search_audio_assets(request: AssetSearchRequest):
    response = state.recommendation_service.search(request)
    for result in response.results:
        result.asset.playback_url = state.storage.public_url(result.asset.object_key)
    return response


@app.get("/users/{user_id}/recommendations", response_model=list[Recommendation])
def recommend(user_id: str, limit: int = 5, query: str | None = None):
    recommendations = state.recommendation_service.recommend(user_id, limit=limit, query=query)
    for item in recommendations:
        item.asset.playback_url = state.storage.public_url(item.asset.object_key)
    return recommendations


# --- Android Audio page: Library / Uploads / History ---


def _recommended_items(user_id: str, limit: int = 30) -> list[AudioItem]:
    """Recommended items for the Library tab. Falls back to the catalog when the
    user has no profile yet, so a fresh client still sees content."""
    recs = state.recommendation_service.recommend(user_id, limit=limit, query=None)
    if recs:
        return [
            asset_to_audio_item(r.asset, state.storage, source="Library")
            for r in recs
        ]
    # No profile / no recs -> show top catalog assets so the tab isn't empty.
    assets = state.repository.list_assets(limit=limit)
    return [asset_to_audio_item(a, state.storage, source="Library") for a in assets]


def _upload_items(user_id: str) -> list[UploadItem]:
    items: list[UploadItem] = []
    for row in state.repository.list_uploads(user_id):
        generated_asset = (
            state.repository.get_asset(row["generated_asset_id"])
            if row["generated_asset_id"]
            else None
        )
        items.append(upload_row_to_item(row, state.storage, generated_asset=generated_asset))
    return items


def _history_items(user_id: str, limit: int = 50) -> list[AudioItem]:
    records = state.repository.list_playback_history(user_id, limit=limit)
    items: list[AudioItem] = []
    for rec in records:
        asset = state.repository.get_asset(rec.asset_id)
        if asset is None:
            continue
        # PlaybackSource (recommend/generated/remix/import) -> frontend source.
        if rec.source in ("generated", "remix"):
            src = "Generated"
        elif rec.source == "import":
            src = "Upload"
        else:
            src = "Library"
        items.append(
            asset_to_audio_item(
                asset, state.storage, source=src, playback_progress=rec.progress
            )
        )
    return items


@app.get("/users/{user_id}/audio-library", response_model=AudioLibrary)
def audio_library(user_id: str):
    """Aggregated payload for the Audio page: one call returns all three tabs."""
    return AudioLibrary(
        recommended=_recommended_items(user_id),
        uploads=_upload_items(user_id),
        history=_history_items(user_id),
    )


@app.get("/users/{user_id}/audio/recommended", response_model=list[AudioItem])
def audio_recommended(user_id: str, limit: int = 30):
    return _recommended_items(user_id, limit=min(limit, 50))


@app.get("/users/{user_id}/audio/history", response_model=list[AudioItem])
def audio_history(user_id: str, limit: int = 50):
    return _history_items(user_id, limit=min(limit, 50))


@app.post("/users/{user_id}/audio/history", response_model=AudioItem)
def report_audio_history(user_id: str, payload: HistoryReportIn):
    asset = state.repository.get_asset(payload.audioId)
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    # Map frontend source back to a PlaybackSource value.
    source_map = {"Library": "recommend", "Generated": "generated", "Upload": "import"}
    pb_source = source_map.get(payload.source, "recommend")
    record_id = state.repository.record_playback_start(
        user_id, payload.audioId, asset.title, pb_source
    )
    completed = payload.event == "complete"
    state.repository.update_playback_feedback(
        record_id,
        feedback_type="complete" if completed else None,
        progress=payload.playbackProgress,
        completed=completed,
    )
    return asset_to_audio_item(
        asset, state.storage, source=payload.source, playback_progress=payload.playbackProgress
    )


@app.patch("/users/{user_id}/audio/history/{audio_id}", response_model=AudioItem)
def patch_audio_history(user_id: str, audio_id: str, payload: HistoryProgressPatchIn):
    asset = state.repository.get_asset(audio_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    record_id = state.repository.record_playback_start(
        user_id, audio_id, asset.title, "recommend"
    )
    completed = payload.playbackProgress >= 0.99
    state.repository.update_playback_feedback(
        record_id,
        feedback_type="complete" if completed else None,
        progress=payload.playbackProgress,
        completed=completed,
    )
    return asset_to_audio_item(
        asset, state.storage, playback_progress=payload.playbackProgress
    )


# --- Uploads (direct multipart upload) ---

_ALLOWED_UPLOAD_TYPES = {"pdf", "txt", "mp3", "wav", "m4a"}


def _resolve_upload_item(user_id: str, upload_id: str) -> UploadItem:
    row = state.repository.get_upload(upload_id)
    if row is None or row["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="upload not found")
    generated_asset = (
        state.repository.get_asset(row["generated_asset_id"])
        if row["generated_asset_id"]
        else None
    )
    return upload_row_to_item(row, state.storage, generated_asset=generated_asset)


@app.post("/users/{user_id}/uploads", response_model=UploadItem, status_code=201)
async def create_upload(user_id: str, file: UploadFile = File(...)):
    file_name = file.filename or "upload"
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    if ext not in _ALLOWED_UPLOAD_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported file type '{ext}'. allowed: {sorted(_ALLOWED_UPLOAD_TYPES)}",
        )
    data = await file.read()
    size_bytes = len(data)
    object_key = f"uploads/{user_id}/{file_name}"
    path = state.storage.path_for(object_key)
    path.write_bytes(data)
    is_playable_audio = ext in ("mp3", "wav", "m4a")
    upload_id = state.repository.create_upload(
        user_id,
        file_name=file_name,
        file_type=ext,
        mime_type=file.content_type,
        size_bytes=size_bytes,
        object_key=object_key,
        status="Completed",
    )
    # Audio uploads are immediately playable (file == audio). pdf/txt have no
    # generation pipeline wired yet: they're stored as Completed but the client
    # shows "待处理" because generatedAudio stays null (method A).
    message = None if is_playable_audio else "待生成音频"
    state.repository.update_upload(upload_id, progress=1.0, message=message)
    return _resolve_upload_item(user_id, upload_id)


@app.get("/users/{user_id}/uploads", response_model=list[UploadItem])
def list_uploads(user_id: str):
    return _upload_items(user_id)


@app.get("/users/{user_id}/uploads/{upload_id}", response_model=UploadItem)
def get_upload(user_id: str, upload_id: str):
    return _resolve_upload_item(user_id, upload_id)


@app.post("/users/{user_id}/uploads/{upload_id}/complete", response_model=UploadItem)
def complete_upload(user_id: str, upload_id: str):
    row = state.repository.get_upload(upload_id)
    if row is None or row["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="upload not found")
    state.repository.update_upload(upload_id, status="Completed", progress=1.0)
    return _resolve_upload_item(user_id, upload_id)


@app.post("/users/{user_id}/uploads/{upload_id}/retry", response_model=UploadItem)
def retry_upload(user_id: str, upload_id: str):
    row = state.repository.get_upload(upload_id)
    if row is None or row["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="upload not found")
    state.repository.update_upload(upload_id, status="Uploading", progress=0.0, message=None)
    return _resolve_upload_item(user_id, upload_id)


@app.delete("/users/{user_id}/uploads/{upload_id}", status_code=204)
def delete_upload(user_id: str, upload_id: str):
    row = state.repository.get_upload(upload_id)
    if row is None or row["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="upload not found")
    state.repository.delete_upload(upload_id)
    return None



@app.post("/users/{user_id}/generate-audio", response_model=GenerationResponse)
def generate_audio(user_id: str, request: GenerationRequest):
    try:
        return state.generation_service.generate_or_match(user_id, request)
    except BudgetExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


@app.post("/users/{user_id}/generation-jobs", response_model=GenerationJobCreateResponse, status_code=202)
def create_generation_job(user_id: str, request: GenerationRequest, background_tasks: BackgroundTasks):
    try:
        response = state.generation_service.enqueue_or_match(user_id, request)
    except BudgetExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    if response.status == "queued":
        background_tasks.add_task(state.generation_service.run_job, response.job_id, user_id, request)
    return response


@app.get("/generation-jobs/{job_id}", response_model=GenerationJob)
def get_generation_job(job_id: str, repository: Repository = Depends(repo)):
    job = repository.get_generation_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="generation job not found")
    if job.asset:
        job.asset.playback_url = state.storage.public_url(job.asset.object_key)
    return job


@app.post("/users/{user_id}/events")
def record_event(user_id: str, event: EventIn, repository: Repository = Depends(repo)):
    event_id = repository.record_event(user_id, event)
    return {"event_id": event_id}


@app.post("/agent/decide", response_model=AgentDecideResponse)
def agent_decide(req: AgentDecideRequest, background_tasks: BackgroundTasks):
    try:
        response = state.agent_runtime.run(req)
    except BudgetExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ValueError as exc:
        if "profile not found" in str(exc):
            raise HTTPException(status_code=404, detail="profile not found") from exc
        raise

    if response.action == "generate_job" and response.job_id:
        background_tasks.add_task(
            state.generation_service.run_job,
            response.job_id,
            req.user_id,
            GenerationRequest(request_text=req.request_text, force_generate=True),
        )
    return response


@app.get("/audio/{object_key:path}")
def get_audio(object_key: str, file_storage: LocalFileStorage = Depends(storage)):
    try:
        path = file_storage.existing_path_for(object_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid object key") from exc
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="audio not found")
    media_type = "audio/mpeg" if path.suffix.lower() == ".mp3" else "audio/wav"
    return FileResponse(Path(path), media_type=media_type)


# --- P0: Questionnaire ---


@app.put("/users/{user_id}/questionnaire", response_model=UserQuestionnaire)
def save_questionnaire(user_id: str, data: UserQuestionnaireIn):
    return state.repository.upsert_questionnaire(user_id, data)


@app.get("/users/{user_id}/questionnaire", response_model=UserQuestionnaire)
def get_questionnaire(user_id: str):
    q = state.repository.get_questionnaire(user_id)
    if q is None:
        raise HTTPException(status_code=404, detail="questionnaire not found")
    return q


# --- P0: Playback History & Feedback ---


@app.post("/users/{user_id}/playback", status_code=201)
def start_playback(user_id: str, payload: PlaybackStartIn):
    asset = state.repository.get_asset(payload.asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    record_id = state.repository.record_playback_start(
        user_id, payload.asset_id, asset.title, payload.source.value, payload.request_text,
        parent_asset_id=payload.parent_asset_id, ambient_asset_id=payload.ambient_asset_id,
    )
    return {"record_id": record_id}


@app.post("/users/{user_id}/playback/{record_id}/feedback")
def submit_playback_feedback(user_id: str, record_id: str, feedback: PlaybackFeedbackIn):
    completed = feedback.feedback_type in ("complete", "morning_feedback")
    state.repository.update_playback_feedback(
        record_id, feedback_type=feedback.feedback_type.value,
        rating=feedback.rating, progress=feedback.progress,
        morning_feedback=feedback.morning_feedback, completed=completed,
    )
    return {"status": "ok"}


@app.get("/users/{user_id}/playback/history", response_model=list[PlaybackRecord])
def get_playback_history(user_id: str, limit: int = 50):
    return state.repository.list_playback_history(user_id, limit=min(limit, 50))


# --- P0: Remix ---


@app.post("/users/{user_id}/remix", response_model=RemixJob, status_code=202)
def create_remix(user_id: str, payload: RemixRequestIn, background_tasks: BackgroundTasks):
    voice_asset = state.repository.get_asset(payload.voice_asset_id)
    if voice_asset is None:
        raise HTTPException(status_code=404, detail="voice asset not found")
    if payload.ambient_asset_id:
        ambient_asset = state.repository.get_asset(payload.ambient_asset_id)
        if ambient_asset is None:
            raise HTTPException(status_code=404, detail="ambient asset not found")
    if not payload.ambient_asset_id and not payload.sound_type:
        raise HTTPException(status_code=400, detail="either ambient_asset_id or sound_type is required")
    job_id = state.repository.create_remix_job(
        user_id, payload.voice_asset_id, payload.ambient_asset_id,
        payload.ambient_tags, payload.voice_volume, payload.ambient_volume,
        sound_type=payload.sound_type,
    )
    background_tasks.add_task(state.remix_service.run_remix, job_id)
    job = state.repository.get_remix_job(job_id)
    return job


@app.get("/remix-jobs/{job_id}", response_model=RemixJob)
def get_remix_job(job_id: str):
    job = state.repository.get_remix_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="remix job not found")
    if job.output_asset:
        job.output_asset.playback_url = state.storage.public_url(job.output_asset.object_key)
    return job


# --- P0: Remix Sessions (algo §3) ---

REMIX_HOURLY_LIMIT = 20


@app.post("/remix/sessions", response_model=RemixSession, status_code=202)
def create_remix_session(payload: RemixSessionCreateIn, background_tasks: BackgroundTasks):
    # Resolve foreground asset
    foreground_asset_id = payload.foreground_asset_id
    foreground_source = "asset_id"
    user_id: str | None = None

    if not foreground_asset_id:
        raise HTTPException(status_code=400, detail="foreground_asset_id is required (active playback inference requires user_id via /agent/decide)")

    asset = state.repository.get_asset(foreground_asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="foreground asset not found")

    # Determine user from recent playback or require explicit
    # For session API, we need user context — get from active playback
    with state.repository._lock:
        row = state.repository.conn.execute(
            "SELECT user_id FROM playback_history WHERE asset_id = ? ORDER BY started_at DESC LIMIT 1",
            (foreground_asset_id,),
        ).fetchone()
    if row is None:
        # Fallback: use a system user for direct API calls
        user_id = "api_user"
        state.repository.ensure_user(user_id)
    else:
        user_id = row["user_id"]

    # Rate limit
    count = state.repository.count_remix_last_hour(user_id)
    if count >= REMIX_HOURLY_LIMIT:
        raise HTTPException(status_code=429, detail=f"remix rate limit exceeded ({REMIX_HOURLY_LIMIT}/hour)")

    # Validate ambient source
    if not payload.ambient_asset_id and not payload.sound_type and payload.intent.value != "remove_background":
        raise HTTPException(status_code=400, detail="ambient_asset_id or sound_type required for this intent")

    job_id = state.repository.create_remix_job(
        user_id, foreground_asset_id, payload.ambient_asset_id, [],
        voice_volume=1.0, ambient_volume=payload.mix_params.background_volume,
        sound_type=payload.sound_type, intent=payload.intent.value,
        mix_params=payload.mix_params, foreground_source=foreground_source,
    )
    background_tasks.add_task(state.remix_service.run_remix, job_id)
    session = state.repository.get_remix_session(job_id)
    return session


@app.patch("/remix/sessions/{session_id}", response_model=RemixSession)
def patch_remix_session(session_id: str, patch: RemixSessionPatchIn, background_tasks: BackgroundTasks):
    session = state.repository.get_remix_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="remix session not found")

    intent = patch.intent.value if patch.intent else session.intent
    mix_params = patch.mix_params or session.mix_params or MixParams()

    # Update session metadata
    state.repository.update_remix_job(
        session_id, status="queued",
        intent=intent,
        mix_params=mix_params,
        sound_type=patch.sound_type,
        ambient_asset_id=patch.ambient_asset_id,
    )
    # Re-run remix with updated params
    background_tasks.add_task(state.remix_service.run_remix, session_id)
    return state.repository.get_remix_session(session_id)


@app.get("/remix/sessions/{session_id}", response_model=RemixSession)
def get_remix_session(session_id: str):
    session = state.repository.get_remix_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="remix session not found")
    if session.output_asset:
        session.output_asset.playback_url = state.storage.public_url(session.output_asset.object_key)
    return session


@app.get("/assets/{asset_id}/remixable", response_model=AssetRemixable)
def check_asset_remixable(asset_id: str):
    from floppy_backend.services.assets import is_placeholder_created_by
    asset = state.repository.get_asset(asset_id)
    if asset is None:
        return AssetRemixable(asset_id=asset_id, remixable=False, reason="asset not found")
    if is_placeholder_created_by(asset.created_by):
        return AssetRemixable(asset_id=asset_id, remixable=False, reason="placeholder asset")
    try:
        path = state.storage.existing_path_for(asset.object_key)
        if not path.exists():
            return AssetRemixable(asset_id=asset_id, remixable=False, reason="audio file missing")
        fmt = "mp3" if path.suffix.lower() == ".mp3" else "wav"
        return AssetRemixable(asset_id=asset_id, remixable=True, format=fmt)
    except ValueError:
        return AssetRemixable(asset_id=asset_id, remixable=False, reason="invalid object key")
