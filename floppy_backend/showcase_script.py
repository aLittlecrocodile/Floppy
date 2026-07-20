SHOWCASE_SCRIPT = r"""
'use strict';
const USER_ID = 'showcase_user';
const $ = (id) => document.getElementById(id);

// The showcase can run at /showcase or under /unwind/showcase beside another
// application. Resolve the mount prefix once so all API and WebSocket calls
// stay same-origin in either deployment mode.
const APP_BASE = (() => {
  const parts = location.pathname.split('/').filter(Boolean);
  const showcaseIndex = parts.lastIndexOf('showcase');
  return showcaseIndex > 0 ? '/' + parts.slice(0, showcaseIndex).join('/') : '';
})();
const appPath = (path) => APP_BASE + path;

const streamEl = $('stream'), promptEl = $('prompt'), sendBtn = $('send'), talkBtn = $('talk');
const nowbar = $('nowbar'), playBtn = $('playBtn'), npTitle = $('npTitle'), npSub = $('npSub');
const player = $('player'), ttsPlayer = $('ttsPlayer');
const callBtn = $('callBtn'), callOverlay = $('callOverlay'), callClose = $('callClose');
const callState = $('callState'), callTimer = $('callTimer'), callWave = $('callWave');
const callAvatar = $('callAvatar'), callTranscript = $('callTranscript');
const callMute = $('callMute'), callMuteLabel = $('callMuteLabel'), callHangup = $('callHangup');

const SKILL_LABELS = {
  play_asset: '播放已有音频',
  generate_sleep_audio: '生成新音频',
  remix_current: '混音当前音频',
  chat: '对话陪伴',
  no_match: '未匹配',
};
const INTENT_LABELS = { story: '睡前故事', meditation: '冥想引导', asmr: 'ASMR', white_noise: '白噪音', music: '音乐' };
const PROGRESS_COPY = [
  '正在为你写一段专属的脚本…',
  '正在挑选合适的声音…',
  '正在合成音频…',
  '快好了，再等等…',
];

let currentAssetId = null;   // for remix_current context
let pollTimer = null, progressTimer = null;

/* ---------- chat stream ---------- */
function addMsg(role, html) {
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.innerHTML = html;
  streamEl.appendChild(div);
  streamEl.scrollTop = streamEl.scrollHeight;
  return div;
}
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

/* ---------- health ---------- */
async function checkHealth() {
  try {
    const r = await fetch(appPath('/health')); const d = await r.json();
    const ok = d.hermes === 'ok';
    $('healthDot').className = 'dot ' + (ok ? 'ok' : 'down');
    $('healthText').textContent = ok ? '智能体决策在线' : '智能体离线 · 降级模式';
  } catch { $('healthDot').className = 'dot down'; $('healthText').textContent = '服务不可达'; }
}
checkHealth(); setInterval(checkHealth, 30000);

/* ---------- decision timeline ---------- */
function tlReset() {
  clearInterval(pollTimer); clearInterval(progressTimer);
  $('tlEmpty').style.display = 'none';
  $('tl').style.display = '';
  for (const n of ['n1','n2','n3','n4']) { $(n).className = ''; }
  $('n1meta').textContent = ''; $('n1body').innerHTML = '';
  $('n2badge').innerHTML = ''; $('n2meta').textContent = ''; $('n2body').innerHTML = '';
  $('n3title').textContent = '生成指令要点'; $('n3body').innerHTML = '';
  $('n4meta').textContent = ''; $('n4body').innerHTML = '';
  setNode('n1', 'running');
  $('n1body').innerHTML = '<span class="line">智能体正在理解你的请求…</span>';
}
function setNode(id, state) { $(id).className = state === 'running' ? 'active running' : 'active ' + state; }
const line = (t) => '<div class="line">' + t + '</div>';
const sourceLabel = (source) => ({ hermes: '智能体', exact_cache: '精确缓存' }[source] || source || '—');

function renderIntentNode(data) {
  const pm = data.planner_meta || {};
  const cached = pm.planner_source === 'exact_cache';
  setNode('n1', 'done');
    $('n1meta').textContent = cached ? '' : ('决策来源 ' + sourceLabel(pm.planner_source) + ' · ' + (pm.planner_latency_ms || 0) + ' ms');
  const intent = data.normalized_request && data.normalized_request.intent;
  let html = '';
  if (cached) {
    html += line('<span class="badge cache">缓存直达</span> 同样的请求此前已生成，直接复用，不消耗一次决策与合成');
  } else {
    html += line('识别意图：' + (INTENT_LABELS[intent] || intent || '—'));
  }
  $('n1body').innerHTML = html;
}

function renderSkillNode(data) {
  const pm = data.planner_meta || {};
  const skill = data.selected_skill || data.action;
  setNode('n2', 'done');
  const degraded = (pm.fallback_reason || '').startsWith('hermes_unavailable');
  $('n2badge').innerHTML = degraded
    ? '<span class="badge warn">决策服务暂不可用</span>'
    : '<span class="badge">' + esc(SKILL_LABELS[skill] || skill || '—') + '</span>';
  if (!degraded && pm.planner_confidence != null) {
    const pct = Math.round(pm.planner_confidence * 100);
    $('n2meta').innerHTML = '置信度 <span class="conf"><span class="bar"><span class="fill" style="width:' + pct + '%"></span></span> ' + pct + '%</span>';
  }
  const reasons = (data.reasons || []).slice(0, 3);
  $('n2body').innerHTML = reasons.map((r) => line('· ' + esc(r))).join('');
}

function renderDirective(d) {
  if (!d) return false;
  const parts = [];
  if (d.tone) parts.push(line('基调：' + esc(d.tone)));
  if (d.duration_sec) parts.push(line('时长：约 ' + Math.round(d.duration_sec / 60) + ' 分钟'));
  if (d.content_brief) parts.push(line('主题：' + esc(d.content_brief)));
  (d.outline || []).forEach((o, i) => parts.push('<div class="line" style="animation-delay:' + (i * 0.12) + 's">— ' + esc(o) + '</div>'));
  if ((d.key_elements || []).length) {
    parts.push('<div class="tags">' + d.key_elements.map((k) => '<span class="tag">' + esc(k) + '</span>').join('') + '</div>');
  }
  if (!parts.length) return false;
  $('n3body').innerHTML = parts.join('');
  setNode('n3', 'done');
  return true;
}

function showAssetCard(asset, title) {
  $('n3title').textContent = title || '匹配到的音频';
  $('n3body').innerHTML = line('《' + esc(asset.title) + '》') +
    line('<span class="tags"><span class="tag">' + esc(INTENT_LABELS[asset.type] || asset.type || '') + '</span>' +
      (asset.duration_sec ? '<span class="tag">' + Math.round(asset.duration_sec / 60) + ' 分钟</span>' : '') + '</span>');
  setNode('n3', 'done');
}

function execTool(data) {
  // second tool_call entry = the executed skill
  return (data.tool_calls || []).find((c) => c.name !== 'hermes_agent') || null;
}

/* ---------- fallback suggestions ---------- */
async function showSuggestions(container) {
  try {
    const r = await fetch(appPath('/users/' + USER_ID + '/recommendations?limit=3'));
    if (!r.ok) return;
    const items = await r.json();
    if (!items.length) return;
    const box = document.createElement('div');
    box.className = 'suggest';
    for (const it of items) {
      const a = it.asset || it;
      if (!a.playback_url) continue;
      const el = document.createElement('div');
      el.className = 'item';
      el.innerHTML = '<span>《' + esc(a.title) + '》</span><span class="play-ico">▶</span>';
      el.onclick = () => playAudio(a.playback_url, a.title, '精选推荐', a.id);
      box.appendChild(el);
    }
    container.appendChild(box);
    streamEl.scrollTop = streamEl.scrollHeight;
  } catch { /* suggestions are best-effort */ }
}

/* ---------- text chat ---------- */
async function sendText(text) {
  text = (text || '').trim();
  if (text.length < 2) return;
  promptEl.value = '';
  sendBtn.disabled = true;
  addMsg('user', esc(text));
  tlReset();
  const thinking = addMsg('assistant', '<span class="shimmer">Unwind 正在思考…</span>');
  try {
    const r = await fetch(appPath('/showcase/chat'), {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ request_text: text, current_asset_id: currentAssetId }),
    });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    handleDecision(data, thinking);
  } catch (e) {
    thinking.innerHTML = '抱歉，这一次请求没有成功，请再试一下。';
    setNode('n1', 'failed');
    $('n1body').innerHTML = line('请求失败：' + esc(e.message));
  } finally {
    sendBtn.disabled = false;
  }
}

function handleDecision(data, bubble) {
  renderIntentNode(data);
  renderSkillNode(data);
  const pm = data.planner_meta || {};
  const degraded = (pm.fallback_reason || '').startsWith('hermes_unavailable');
  bubble.innerHTML = esc(data.reply || defaultReply(data.action));

  const tool = execTool(data);

  if (data.action === 'play_asset' && data.asset) {
    showAssetCard(data.asset, '匹配到的音频');
    setNode('n4', 'done');
    $('n4meta').textContent = tool ? ('执行 ' + tool.latency_ms + ' ms') : '';
    $('n4body').innerHTML = line('已就绪，即刻播放');
    playAudio(data.asset.playback_url, data.asset.title, pm.planner_source === 'exact_cache' ? '缓存直达' : '音频库匹配', data.asset.id);
    return;
  }

  if (data.action === 'remix_current') {
    $('n3title').textContent = '混音方案';
    const st = tool && tool.output && tool.output.sound_type;
    $('n3body').innerHTML = line('在当前音频中叠加背景音' + (st ? '：' + esc(st) : ''));
    setNode('n3', 'done');
    if (data.asset && data.asset.playback_url) {
      setNode('n4', 'done');
      $('n4body').innerHTML = line('混音完成，即刻播放');
      playAudio(data.asset.playback_url, data.asset.title, '实时混音', data.asset.id);
    } else if (data.remix_job_id) {
      pollRemix(data.remix_job_id);
    } else {
      setNode('n4', 'failed');
      $('n4body').innerHTML = line('混音未能启动');
    }
    return;
  }

  if (data.action === 'generate_job' && data.job_id) {
    setNode('n3', 'running');
    $('n3body').innerHTML = '<span class="shimmer">智能体规划中……………………</span>';
    startProgress();
    pollJob(data.job_id);
    return;
  }

  // chat / no_match / degraded
  setNode('n4', degraded ? 'failed' : 'done');
  if (degraded) {
    $('n4body').innerHTML = line('决策服务暂不可用，已为你准备精选内容');
    const holder = addMsg('assistant', '这些是为你准备的精选内容：');
    showSuggestions(holder);
  } else if (data.action === 'no_match') {
    $('n4body').innerHTML = line('本次未匹配到合适内容');
    const holder = addMsg('assistant', '也可以听听这些：');
    showSuggestions(holder);
  } else {
    $('n4body').innerHTML = line('以对话回应');
  }
}

function defaultReply(action) {
  return {
    play_asset: '找到一段很适合你的声音，现在开始播放。',
    generate_job: '我来为你专门生成一段，请稍等片刻。',
    remix_current: '好的，正在为当前的声音调整背景。',
    no_match: '这次没有找到特别合适的内容。',
    chat: '我在。',
  }[action] || '收到。';
}

/* ---------- generation job polling ---------- */
function startProgress() {
  setNode('n4', 'running');
  let i = 0;
  const render = () => {
    $('n4body').innerHTML = '<div class="progress-ring"><span class="ring"></span><span class="progress-copy">' + PROGRESS_COPY[i % PROGRESS_COPY.length] + '</span></div>';
    i += 1;
  };
  render();
  progressTimer = setInterval(render, 6000);
}

function pollJob(jobId) {
  const started = Date.now();
  let directiveShown = false;
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    if (Date.now() - started > 240000) { clearInterval(pollTimer); jobFailed('生成超时了'); return; }
    let job;
    try {
      const r = await fetch(appPath('/generation-jobs/' + jobId));
      if (!r.ok) return;
      job = await r.json();
    } catch { return; }
    if (!directiveShown && job.directive) directiveShown = renderDirective(job.directive);
    $('n4meta').textContent = { queued: '排队中', running: '生成中', succeeded: '', failed: '' }[job.status] || '';
    if (job.status === 'succeeded' && job.asset && job.asset.playback_url) {
      clearInterval(pollTimer); clearInterval(progressTimer);
      if (!directiveShown) { $('n3body').innerHTML = line('（本次未产出结构化指令）'); setNode('n3', 'done'); }
      setNode('n4', 'done');
      $('n4body').innerHTML = line('生成完成' + (job.latency_ms ? ' · ' + (job.latency_ms / 1000).toFixed(1) + ' s' : ''));
      addMsg('assistant', '你的专属音频已经生成好了：《' + esc(job.asset.title) + '》');
      playAudio(job.asset.playback_url, job.asset.title, '为你生成', job.asset.id);
    } else if (job.status === 'failed') {
      clearInterval(pollTimer); jobFailed(job.error_message || '生成没有成功');
    }
  }, 2000);
}

function jobFailed(msg) {
  clearInterval(progressTimer);
  setNode('n4', 'failed');
  $('n4body').innerHTML = line('很抱歉，' + esc(msg) + '。');
  const holder = addMsg('assistant', '这次生成没有成功，先听听这些吧：');
  showSuggestions(holder);
}

function pollRemix(jobId) {
  setNode('n4', 'running');
  $('n4body').innerHTML = '<div class="progress-ring"><span class="ring"></span><span class="progress-copy">正在混音…</span></div>';
  const started = Date.now();
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    if (Date.now() - started > 90000) { clearInterval(pollTimer); jobFailed('混音超时了'); return; }
    let job;
    try {
      const r = await fetch(appPath('/remix-jobs/' + jobId));
      if (!r.ok) return;
      job = await r.json();
    } catch { return; }
    if (job.status === 'succeeded' && job.output_asset && job.output_asset.playback_url) {
      clearInterval(pollTimer);
      setNode('n4', 'done');
      $('n4body').innerHTML = line('混音完成');
      playAudio(job.output_asset.playback_url, job.output_asset.title, '实时混音', job.output_asset.id);
    } else if (job.status === 'failed') {
      clearInterval(pollTimer); jobFailed(job.error_message || '混音没有成功');
    }
  }, 2000);
}

/* ---------- now playing ---------- */
function playAudio(url, title, sub, assetId) {
  if (!url) return;
  currentAssetId = assetId || null;
  npTitle.textContent = '《' + (title || '未命名') + '》';
  npSub.textContent = sub || '';
  nowbar.classList.add('show');
  player.src = url;
  player.play().then(() => setPlayingUI(true)).catch(() => setPlayingUI(false));
}
function setPlayingUI(playing) {
  playBtn.textContent = playing ? '❚❚' : '▶';
  nowbar.classList.toggle('playing', playing);
}
playBtn.onclick = () => { if (player.paused) { player.play().then(() => setPlayingUI(true)).catch(() => {}); } else { player.pause(); setPlayingUI(false); } };
player.onended = () => setPlayingUI(false);
player.onpause = () => setPlayingUI(false);
player.onplay = () => setPlayingUI(true);

/* ---------- input bindings ---------- */
sendBtn.onclick = () => sendText(promptEl.value);
promptEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendText(promptEl.value); }
});
$('chips').addEventListener('click', (e) => {
  if (e.target.classList.contains('chip')) sendText(e.target.textContent);
});

/* ================= voice capture primitives ================= */
const TARGET_RATE = 16000, FRAME_MS = 200;
const wsScheme = location.protocol === 'https:' ? 'wss://' : 'ws://';
const pttWsUrl = wsScheme + location.host + appPath('/voice/ws?user_id=' + USER_ID);
const realtimeWsUrl = wsScheme + location.host + appPath('/voice/realtime?user_id=' + USER_ID);
const MIC_OPTIONS = { audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } };

async function createCaptureWorklet(context, mediaStream, onFrame) {
  const workletCode = `
    class UnwindPCMWorklet extends AudioWorkletProcessor {
      process(inputs) {
        const channel = inputs[0][0];
        if (channel && channel.length) this.port.postMessage(channel.slice(0));
        return true;
      }
    }
    registerProcessor('unwind-pcm-capture', UnwindPCMWorklet);
  `;
  const moduleUrl = URL.createObjectURL(new Blob([workletCode], { type: 'application/javascript' }));
  await context.audioWorklet.addModule(moduleUrl);
  URL.revokeObjectURL(moduleUrl);
  const source = context.createMediaStreamSource(mediaStream);
  const node = new AudioWorkletNode(context, 'unwind-pcm-capture');
  const silent = context.createGain();
  silent.gain.value = 0;
  node.port.onmessage = (event) => onFrame(event.data);
  source.connect(node); node.connect(silent); silent.connect(context.destination);
  return { source, node, silent };
}

function resample(f32, fromRate) {
  if (fromRate === TARGET_RATE) return f32;
  const ratio = fromRate / TARGET_RATE, outLen = Math.floor(f32.length / ratio), out = new Float32Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const idx = i * ratio, lo = Math.floor(idx), hi = Math.min(lo + 1, f32.length - 1);
    out[i] = f32[lo] + (f32[hi] - f32[lo]) * (idx - lo);
  }
  return out;
}
function floatToInt16(f32) {
  const out = new Int16Array(f32.length);
  for (let i = 0; i < f32.length; i++) { const s = Math.max(-1, Math.min(1, f32[i])); out[i] = s < 0 ? s * 0x8000 : s * 0x7fff; }
  return out.buffer;
}

/* ================= push-to-talk over /voice/ws ================= */
let ws = null, audioCtx = null, workletNode = null, micStream = null, micSource = null, micMonitor = null;
let recording = false, pttHeld = false, inputRate = 48000, resampleBuffer = [], sentBytes = 0;
let vUserEl = null, vAssistantEl = null, vAssistantText = '', audioParts = [], pendingAsset = null;
let voiceReady = false, audioInitPromise = null;

function onAudioFrame(f32) {
  const rs = resample(f32, inputRate);
  for (let i = 0; i < rs.length; i++) resampleBuffer.push(rs[i]);
  const frameSamples = TARGET_RATE * FRAME_MS / 1000;
  while (resampleBuffer.length >= frameSamples) {
    const buf = floatToInt16(Float32Array.from(resampleBuffer.splice(0, frameSamples)));
    sentBytes += buf.byteLength;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(buf);
  }
}
function flushTail() {
  if (resampleBuffer.length > 0) {
    const buf = floatToInt16(Float32Array.from(resampleBuffer));
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(buf);
    resampleBuffer = [];
  }
}
async function initAudio() {
  micStream = await navigator.mediaDevices.getUserMedia(MIC_OPTIONS);
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  inputRate = audioCtx.sampleRate;
  const capture = await createCaptureWorklet(audioCtx, micStream, (frame) => { if (recording) onAudioFrame(frame); });
  micSource = capture.source; workletNode = capture.node; micMonitor = capture.silent;
}
function connectWS() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  ws = new WebSocket(pttWsUrl);
  ws.binaryType = 'arraybuffer';
  ws.onopen = () => { talkBtn.disabled = false; talkBtn.title = '按住说话'; };
  ws.onclose = () => { talkBtn.disabled = true; talkBtn.title = '语音连接已断开'; };
  ws.onerror = () => { talkBtn.disabled = true; talkBtn.title = '语音服务暂不可用'; };
  ws.onmessage = (ev) => {
    if (ev.data instanceof ArrayBuffer) { audioParts.push(ev.data); return; }
    let msg; try { msg = JSON.parse(ev.data); } catch { return; }
    if (msg.type === 'user_text') {
      const txt = (msg.text || '').trim();
      if (txt) {
        if (!vUserEl) vUserEl = addMsg('user', '');
        vUserEl.innerHTML = esc(txt);
      }
    } else if (msg.type === 'assistant_text') {
      if (!vAssistantEl) { vAssistantEl = addMsg('assistant', ''); vAssistantText = ''; }
      vAssistantText += msg.text;
      vAssistantEl.innerHTML = esc(vAssistantText);
    } else if (msg.type === 'audio_asset') {
      pendingAsset = { url: msg.url, title: msg.text || '专属音频' };
    } else if (msg.type === 'turn_end') {
      playVoiceReply();
    } else if (msg.type === 'error') {
      addMsg('system', '语音链路：' + esc(msg.text));
    }
  };
}
function playVoiceReply() {
  const chainAsset = () => { if (pendingAsset) { playAudio(pendingAsset.url, pendingAsset.title, '语音对话'); pendingAsset = null; } };
  if (audioParts.length === 0) { chainAsset(); return; }
  ttsPlayer.src = URL.createObjectURL(new Blob(audioParts, { type: 'audio/mpeg' }));
  ttsPlayer.onended = chainAsset;
  ttsPlayer.play().catch(chainAsset);
}
async function ensureVoice() {
  if (voiceReady) return;
  connectWS();
  voiceReady = true;
}
async function startUtterance() {
  pttHeld = true;
  if (recording || !ws || ws.readyState !== WebSocket.OPEN) return;
  if (!audioCtx) {
    talkBtn.textContent = '正在开启麦克风…';
    try {
      audioInitPromise = audioInitPromise || initAudio();
      await audioInitPromise;
    } catch (error) {
      audioInitPromise = null;
      talkBtn.textContent = '按住说话'; talkBtn.disabled = true;
      talkBtn.title = '麦克风不可用';
      addMsg('system', '未能打开麦克风：' + esc(error.message || '请检查浏览器权限'));
      return;
    }
  }
  if (!pttHeld || !ws || ws.readyState !== WebSocket.OPEN) { talkBtn.textContent = '按住说话'; return; }
  recording = true;
  if (audioCtx.state === 'suspended') audioCtx.resume();
  talkBtn.classList.add('recording'); talkBtn.textContent = '松开结束';
  vUserEl = null; vAssistantEl = null; vAssistantText = ''; pendingAsset = null;
  audioParts = []; resampleBuffer = []; sentBytes = 0;
}
function endUtterance() {
  pttHeld = false;
  if (!recording) return;
  recording = false;
  flushTail();
  talkBtn.classList.remove('recording'); talkBtn.textContent = '按住说话';
  if (sentBytes < 3200) addMsg('system', '几乎没有采集到声音，请检查麦克风');
  ws.send(JSON.stringify({ type: 'utterance_end' }));
}
talkBtn.addEventListener('pointerdown', (event) => {
  event.preventDefault(); talkBtn.setPointerCapture(event.pointerId); startUtterance();
});
talkBtn.addEventListener('pointerup', endUtterance);
talkBtn.addEventListener('pointercancel', endUtterance);
talkBtn.addEventListener('lostpointercapture', () => { if (pttHeld || recording) endUtterance(); });

/* ================= realtime call over /voice/realtime ================= */
const CALL_FRAME_SAMPLES = 320;
let callWs = null, callInputCtx = null, callOutputCtx = null, callMicStream = null;
let callCaptureNode = null, callCaptureSource = null, callCaptureMonitor = null;
let callInputBuffer = [], callReady = false, callMutedState = false, callEnding = false;
let callStartedAt = 0, callTimerHandle = null, callNextPlayTime = 0;
let callSources = new Set(), callUserLine = null, callAssistantLine = null, callAssistantText = '';
let callPendingAsset = null;

function setCallState(text, mode) {
  callState.textContent = text;
  callState.classList.toggle('call-error', mode === 'error');
  const active = mode === 'listening' || mode === 'speaking';
  callWave.classList.toggle('active', active);
  callAvatar.classList.toggle('live', active || mode === 'connected');
  callAvatar.classList.toggle('speaking', mode === 'speaking');
}
function formatCallTime(seconds) {
  const mins = Math.floor(seconds / 60), secs = seconds % 60;
  return String(mins).padStart(2, '0') + ':' + String(secs).padStart(2, '0');
}
function startCallTimer() {
  callStartedAt = Date.now(); clearInterval(callTimerHandle);
  const tick = () => { callTimer.textContent = formatCallTime(Math.floor((Date.now() - callStartedAt) / 1000)); };
  tick(); callTimerHandle = setInterval(tick, 1000);
}
function resetCallTranscript() {
  callTranscript.innerHTML = '<p class="empty">通话字幕会显示在这里</p>';
  callUserLine = null; callAssistantLine = null; callAssistantText = '';
}
function appendCallLine(role, label, text, existing) {
  const empty = callTranscript.querySelector('.empty'); if (empty) empty.remove();
  const lineEl = existing || document.createElement('p');
  lineEl.className = 'call-line ' + role;
  lineEl.innerHTML = '<strong>' + esc(label) + '</strong><span>' + esc(text) + '</span>';
  if (!existing) callTranscript.appendChild(lineEl);
  callTranscript.scrollTop = callTranscript.scrollHeight;
  return lineEl;
}
function appendCallSystem(text) { appendCallLine('system', '', text, null); }

function pushRealtimeAudio(frame) {
  if (!callReady || callMutedState || !callWs || callWs.readyState !== WebSocket.OPEN) return;
  const samples = resample(frame, callInputCtx.sampleRate);
  for (let i = 0; i < samples.length; i++) callInputBuffer.push(samples[i]);
  while (callInputBuffer.length >= CALL_FRAME_SAMPLES) {
    callWs.send(floatToInt16(Float32Array.from(callInputBuffer.splice(0, CALL_FRAME_SAMPLES))));
  }
}
function stopCallPlayback() {
  for (const source of callSources) { try { source.stop(); } catch {} }
  callSources.clear();
  callNextPlayTime = callOutputCtx ? callOutputCtx.currentTime : 0;
}
function queueCallPCM(arrayBuffer) {
  if (!callOutputCtx || !arrayBuffer.byteLength) return;
  const view = new DataView(arrayBuffer), sampleCount = Math.floor(arrayBuffer.byteLength / 2);
  const floats = new Float32Array(sampleCount);
  for (let i = 0; i < sampleCount; i++) floats[i] = view.getInt16(i * 2, true) / 32768;
  const audioBuffer = callOutputCtx.createBuffer(1, sampleCount, 24000);
  audioBuffer.copyToChannel(floats, 0);
  const source = callOutputCtx.createBufferSource();
  source.buffer = audioBuffer; source.connect(callOutputCtx.destination);
  const startAt = Math.max(callOutputCtx.currentTime + .025, callNextPlayTime);
  source.start(startAt); callNextPlayTime = startAt + audioBuffer.duration;
  callSources.add(source); source.onended = () => callSources.delete(source);
  setCallState('Unwind 正在回应', 'speaking');
}
function queuedCallAsset() {
  if (!callPendingAsset) return;
  const pending = callPendingAsset; callPendingAsset = null;
  const playAsset = () => playAudio(pending.url, pending.title, '通话中为你准备', pending.id);
  if (pending.notifyUrl) {
    ttsPlayer.src = pending.notifyUrl; ttsPlayer.onended = playAsset;
    ttsPlayer.play().catch(playAsset);
  } else playAsset();
}
function cleanupRealtimeCall(playPending) {
  clearInterval(callTimerHandle); callTimerHandle = null;
  stopCallPlayback();
  if (callMicStream) callMicStream.getTracks().forEach((track) => track.stop());
  if (callCaptureNode) callCaptureNode.disconnect();
  if (callCaptureSource) callCaptureSource.disconnect();
  if (callCaptureMonitor) callCaptureMonitor.disconnect();
  if (callInputCtx && callInputCtx.state !== 'closed') callInputCtx.close();
  if (callOutputCtx && callOutputCtx.state !== 'closed') callOutputCtx.close();
  callInputCtx = null; callOutputCtx = null; callMicStream = null;
  callCaptureNode = null; callCaptureSource = null; callCaptureMonitor = null;
  callInputBuffer = []; callReady = false; callMutedState = false;
  callMute.setAttribute('aria-pressed', 'false'); callMuteLabel.textContent = '静音';
  callAvatar.classList.remove('live', 'speaking'); callWave.classList.remove('active');
  callBtn.disabled = false; talkBtn.disabled = !(ws && ws.readyState === WebSocket.OPEN);
  document.body.classList.remove('call-open'); callOverlay.hidden = true;
  if (playPending) queuedCallAsset(); else callPendingAsset = null;
}
function finishRealtimeCall(playPending) {
  if (callEnding) return; callEnding = true;
  setCallState('正在结束通话', 'connected');
  const socket = callWs; callWs = null;
  if (socket && socket.readyState === WebSocket.OPEN) {
    try { socket.send(JSON.stringify({ type: 'stop' })); } catch {}
    setTimeout(() => { try { socket.close(); } catch {} }, 100);
  }
  setTimeout(() => { cleanupRealtimeCall(playPending); callEnding = false; }, 180);
}
function handleRealtimeEvent(message) {
  if (message.type === 'ready') {
    callReady = true; startCallTimer(); setCallState('已接通，我在听', 'listening');
  } else if (message.type === 'asr_info') {
    stopCallPlayback(); setCallState('我在听', 'listening');
  } else if (message.type === 'asr') {
    const text = (message.text || '').trim(); if (!text) return;
    callUserLine = appendCallLine('user', '你', text, callUserLine);
    if (!message.interim) { addMsg('user', esc(text)); callUserLine = null; }
  } else if (message.type === 'chat') {
    callAssistantText += message.text || '';
    callAssistantLine = appendCallLine('assistant', 'Unwind', callAssistantText, callAssistantLine);
    setCallState('Unwind 正在回应', 'speaking');
  } else if (message.type === 'tts_end') {
    if (callAssistantText) addMsg('assistant', esc(callAssistantText));
    callAssistantText = ''; callAssistantLine = null;
    if (callPendingAsset) {
      appendCallSystem('专属音频已准备好，即将为你播放');
      finishRealtimeCall(true);
    } else setCallState('我在听', 'listening');
  } else if (message.type === 'generation_started') {
    appendCallSystem('智能体正在为你准备专属音频');
  } else if (message.type === 'generation_done') {
    const audio = message.audio || {};
    const url = audio.streamUrl || audio.playback_url || audio.url;
    if (url) callPendingAsset = {
      url, title: audio.title || '专属音频', id: audio.id || null, notifyUrl: message.notifyAudioUrl || null,
    };
    appendCallSystem('专属音频已生成完成');
  } else if (message.type === 'session_end') {
    finishRealtimeCall(true);
  } else if (message.type === 'error') {
    appendCallSystem(message.message || '通话发生错误');
    setCallState(message.message || '通话发生错误', 'error');
  }
}
async function startRealtimeCall() {
  if (callWs && (callWs.readyState === WebSocket.OPEN || callWs.readyState === WebSocket.CONNECTING)) {
    callOverlay.hidden = false; document.body.classList.add('call-open'); return;
  }
  callEnding = false; callPendingAsset = null; callBtn.disabled = true; talkBtn.disabled = true;
  callOverlay.hidden = false; document.body.classList.add('call-open');
  resetCallTranscript(); callTimer.textContent = '00:00'; setCallState('正在申请麦克风权限', 'connecting');
  try {
    callMicStream = await navigator.mediaDevices.getUserMedia(MIC_OPTIONS);
    callInputCtx = new (window.AudioContext || window.webkitAudioContext)();
    callOutputCtx = new (window.AudioContext || window.webkitAudioContext)();
    await callInputCtx.resume(); await callOutputCtx.resume();
    const capture = await createCaptureWorklet(callInputCtx, callMicStream, pushRealtimeAudio);
    callCaptureSource = capture.source; callCaptureNode = capture.node; callCaptureMonitor = capture.silent;
    setCallState('正在接通', 'connecting');
    callWs = new WebSocket(realtimeWsUrl); callWs.binaryType = 'arraybuffer';
    callWs.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) { queueCallPCM(event.data); return; }
      let message; try { message = JSON.parse(event.data); } catch { return; }
      handleRealtimeEvent(message);
    };
    callWs.onerror = () => setCallState('通话服务暂不可用', 'error');
    callWs.onclose = () => {
      if (!callEnding) {
        setCallState(callReady ? '通话已结束' : '未能接通，请稍后再试', 'error');
        setTimeout(() => cleanupRealtimeCall(true), 180);
      }
    };
  } catch (error) {
    if (callMicStream) callMicStream.getTracks().forEach((track) => track.stop());
    if (callInputCtx && callInputCtx.state !== 'closed') callInputCtx.close();
    if (callOutputCtx && callOutputCtx.state !== 'closed') callOutputCtx.close();
    callMicStream = null; callInputCtx = null; callOutputCtx = null;
    appendCallSystem(error.message || '无法使用麦克风');
    setCallState('无法使用麦克风，请检查浏览器权限', 'error');
    callBtn.disabled = false; talkBtn.disabled = !(ws && ws.readyState === WebSocket.OPEN);
  }
}

callBtn.addEventListener('click', startRealtimeCall);
callHangup.addEventListener('click', () => finishRealtimeCall(true));
callClose.addEventListener('click', () => finishRealtimeCall(true));
callMute.addEventListener('click', () => {
  callMutedState = !callMutedState;
  callMute.setAttribute('aria-pressed', String(callMutedState));
  callMuteLabel.textContent = callMutedState ? '取消静音' : '静音';
  setCallState(callMutedState ? '已静音' : '我在听', callMutedState ? 'connected' : 'listening');
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && !callOverlay.hidden) finishRealtimeCall(true);
});

(async () => {
  try { await ensureVoice(); }
  catch { talkBtn.disabled = true; talkBtn.title = '语音服务暂不可用'; }
})();
"""
