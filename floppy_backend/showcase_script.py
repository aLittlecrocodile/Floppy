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
  // forward-compat: phase 2+ skills (backend rollout pending)
  reframe_thought: '认知重构引导',
  mood_checkin: '心情打卡',
  worry_parking: '烦恼寄存',
  gratitude_moment: '三件好事',
  update_preference: '偏好更新',
  sleep_timer: '定时停播',
  // OneTool demo skills
  weekly_ghostwriter: '周报代写',
  okr_reframe: 'OKR 实据重构',
  neisou_answer: '内搜兜底',
  calendar_sense: '下会缓冲舱',
  // chat-native dialog skills
  relax_tip: '即时呼吸引导',
  counting_ritual: '数息 · 数羊',
  encourage_me: '夸夸我',
  destress_knowledge: '减压小知识',
  comfort_card: '安心签',
};
const INTENT_LABELS = { story: '放松故事', meditation: '冥想引导', asmr: 'ASMR', white_noise: '白噪音', music: '音乐', podcast_digest: '播客精华' };
const PROGRESS_COPY = [
  '正在为你写一段专属的脚本…',
  '正在挑选合适的声音…',
  '正在合成音频…',
  '快好了，再等等…',
];

let currentAssetId = null;   // for remix_current context
let lastUserText = '';       // for comfort-card moment detection
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
const sourceLabel = (source) => ({ hermes: '智能体', exact_cache: '精确缓存', skill_demo: '技能路由 · OneTool' }[source] || source || '—');

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
  lastUserText = text;
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

  pulseSkill((data.skill_card && data.skill_card.skill) || data.selected_skill || data.action);
  if (data.skill_card) renderSkillCard(data);
  speakReply(data.reply_audio_url);
  if (data.timer_sec) armSleepTimer(data.timer_sec, data.fade_out !== false);

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
    const replyText = data.reply || '';
    if (replyText && CARD_RE.test(lastUserText)) {
      renderComfortCard(replyText, bubble);   // farewell/安心签 moment → the reply IS the card
    } else {
      attachCardify(bubble, replyText);       // any reply can be turned into a card
    }
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
  if (typeof clearSleepTimer === 'function') clearSleepTimer(true);
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

/* ================= 减压视觉交互:水波纹 ================= */
document.addEventListener('pointerdown', (e) => {
  if (e.target.closest('button, textarea, a, .chip, .msg, .comfort-card, .call-shell, .nowbar, .breathe-stage')) return;
  for (const cls of ['', 'r2']) {
    const r = document.createElement('span');
    r.className = ('ripple ' + cls).trim();
    r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
    document.body.appendChild(r);
    r.addEventListener('animationend', () => r.remove());
  }
});

/* ================= 呼吸练习:4-7-8 × 3 轮 ≈ 60s ================= */
const breatheOverlay = $('breatheOverlay'), orbEl = $('orb'), orbGlowEl = $('orbGlow');
const breathePhaseEl = $('breathePhase'), breatheCountEl = $('breatheCount');
const breatheRoundsEl = $('breatheRounds'), breatheActionsEl = $('breatheActions');
const BREATH_STEPS = [
  { label: '吸气', secs: 4, scale: 1 },
  { label: '屏住', secs: 7, scale: null },   // hold: orb stays
  { label: '呼气', secs: 8, scale: 0.72 },
];
const BREATH_TOTAL_ROUNDS = 3;
let breatheTimers = [];
const bt = (fn, ms) => breatheTimers.push(setTimeout(fn, ms));
function clearBreathe() { breatheTimers.forEach(clearTimeout); breatheTimers = []; }
function setOrb(scale, secs) {
  orbEl.style.transitionDuration = secs + 's';
  orbGlowEl.style.transitionDuration = secs + 's';
  orbEl.style.transform = 'scale(' + scale + ')';
  orbGlowEl.style.transform = 'scale(' + scale + ')';
}
function runBreatheRound(round) {
  const dots = breatheRoundsEl.querySelectorAll('i');
  dots.forEach((d, i) => d.classList.toggle('on', i < round));
  if (round >= BREATH_TOTAL_ROUNDS) {
    dots.forEach((d) => d.classList.add('on'));
    breathePhaseEl.textContent = '很好';
    breatheCountEl.textContent = '心跳慢下来了吗？带着这口气回去吧';
    breatheActionsEl.hidden = false;
    setOrb(0.8, 2);
    return;
  }
  const ticks = [];
  for (const step of BREATH_STEPS) for (let s = 0; s < step.secs; s++) ticks.push({ step, s });
  ticks.forEach((t, idx) => bt(() => {
    if (t.s === 0) {
      breathePhaseEl.textContent = t.step.label;
      if (t.step.scale != null) setOrb(t.step.scale, t.step.secs);
    }
    breatheCountEl.textContent = String(t.step.secs - t.s);
  }, idx * 1000));
  bt(() => runBreatheRound(round + 1), ticks.length * 1000);
}
function startBreathe() {
  clearBreathe();
  breatheOverlay.hidden = false;
  document.body.classList.add('call-open');  // reuse scroll lock
  breathePhaseEl.textContent = '准备';
  breatheCountEl.textContent = '找个舒服的姿势，跟着圆球呼吸';
  breatheActionsEl.hidden = true;
  breatheRoundsEl.querySelectorAll('i').forEach((d) => d.classList.remove('on'));
  setOrb(0.72, 1);
  bt(() => runBreatheRound(0), 2400);
}
function stopBreathe() {
  clearBreathe();
  breatheOverlay.hidden = true;
  if (callOverlay.hidden) document.body.classList.remove('call-open');
}
$('breatheBtn').addEventListener('click', startBreathe);
$('breatheClose').addEventListener('click', stopBreathe);
$('breatheAgain').addEventListener('click', startBreathe);
$('breatheDone').addEventListener('click', stopBreathe);
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !breatheOverlay.hidden) stopBreathe();
});

/* ================= 安心签 comfort card ================= */
const CARD_RE = /晚安|睡了|去睡|去忙|收工|下班|回去干活|再见|拜拜|告辞|安心签/;
const CN_WEEK = ['日', '一', '二', '三', '四', '五', '六'];
function cardDate() {
  const d = new Date();
  return (d.getMonth() + 1) + ' 月 ' + d.getDate() + ' 日 · 周' + CN_WEEK[d.getDay()];
}
function renderComfortCard(text, replaceEl) {
  const card = document.createElement('div');
  card.className = 'comfort-card';
  card.innerHTML =
    '<div class="cc-kicker"><span>安 心 签</span><span>' + esc(cardDate()) + '</span></div>' +
    '<div class="cc-text">' + esc(text) + '</div>' +
    '<div class="cc-foot"><span class="cc-seal">安</span><span class="cc-brand">UNWIND</span>' +
    '<button class="cc-save" type="button">保存卡片</button></div>';
  card.querySelector('.cc-save').addEventListener('click', () => saveCardImage(text));
  if (replaceEl) replaceEl.replaceWith(card); else streamEl.appendChild(card);
  streamEl.scrollTop = streamEl.scrollHeight;
  return card;
}
function attachCardify(bubble, text) {
  if (!text || !bubble || bubble.querySelector('.cc-make')) return;
  const b = document.createElement('button');
  b.className = 'cc-make'; b.type = 'button'; b.title = '制成安心签'; b.textContent = '签';
  b.addEventListener('click', () => renderComfortCard(text));
  bubble.appendChild(b);
}
function saveCardImage(text) {
  const W = 680, H = 920, dpr = 2;
  const canvas = document.createElement('canvas');
  canvas.width = W * dpr; canvas.height = H * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  // paper base
  const bg = ctx.createLinearGradient(0, 0, 0, H);
  bg.addColorStop(0, '#fffefb'); bg.addColorStop(1, '#f1eee6');
  ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);
  // ink washes
  const wash = (x, y, r, color) => {
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, color); g.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  };
  wash(90, 60, 420, 'rgba(185,208,198,.55)');
  wash(W - 60, H - 80, 460, 'rgba(236,217,200,.6)');
  wash(W - 120, 140, 260, 'rgba(214,90,71,.10)');
  // grain
  for (let i = 0; i < 1200; i++) {
    ctx.fillStyle = 'rgba(60,52,48,' + (Math.random() * 0.035).toFixed(3) + ')';
    ctx.fillRect(Math.random() * W, Math.random() * H, 1, 1);
  }
  // inner frame
  ctx.strokeStyle = 'rgba(88,78,72,.3)'; ctx.lineWidth = 1;
  ctx.strokeRect(28, 28, W - 56, H - 56);
  ctx.strokeStyle = 'rgba(88,78,72,.14)';
  ctx.strokeRect(38, 38, W - 76, H - 76);
  const serif = '"Songti SC", "Noto Serif SC", Georgia, serif';
  // kicker + date
  ctx.fillStyle = '#8a8f8c'; ctx.font = '600 20px ' + serif;
  ctx.textBaseline = 'top';
  ctx.fillText('安  心  签', 70, 84);
  ctx.font = '14px ' + serif; ctx.textAlign = 'right';
  ctx.fillText(cardDate(), W - 70, 88);
  ctx.textAlign = 'left';
  // body text, CJK-wrapped
  ctx.fillStyle = '#3a3134'; ctx.font = '500 32px ' + serif;
  const maxWidth = W - 150, lineHeight = 62, lines = [];
  let cur = '';
  for (const ch of String(text)) {
    if (ch === '\n' || ctx.measureText(cur + ch).width > maxWidth) { lines.push(cur); cur = ch === '\n' ? '' : ch; }
    else cur += ch;
  }
  if (cur) lines.push(cur);
  const shown = lines.slice(0, 8);
  let y = Math.max(210, (H - shown.length * lineHeight) / 2 - 60);
  for (const ln of shown) { ctx.fillText(ln, 76, y); y += lineHeight; }
  // seal + brand
  const sealY = H - 170;
  const sg = ctx.createLinearGradient(70, sealY, 134, sealY + 64);
  sg.addColorStop(0, '#de6a52'); sg.addColorStop(1, '#b9483a');
  ctx.fillStyle = sg;
  ctx.beginPath(); ctx.roundRect(70, sealY, 64, 64, 12); ctx.fill();
  ctx.fillStyle = '#fff7f2'; ctx.font = '600 34px ' + serif;
  ctx.fillText('安', 85, sealY + 14);
  ctx.fillStyle = '#98a09e'; ctx.font = '600 16px ' + serif;
  ctx.fillText('U N W I N D', 150, sealY + 12);
  ctx.fillStyle = '#b3b8b4'; ctx.font = '13px ' + serif;
  ctx.fillText('把压力，呼出去', 150, sealY + 38);
  // download
  const a = document.createElement('a');
  a.href = canvas.toDataURL('image/png');
  a.download = 'unwind-comfort-card.png';
  a.click();
}

/* ================= 技能矩阵 ================= */
const SKILL_CATS = { onetool: '厂内能力 · ONETOOL', ritual: '减压仪式 · 自研', sound: '声音引擎' };
const skillChipByKey = {};
async function loadSkillMatrix() {
  try {
    const r = await fetch(appPath('/showcase/skills'));
    if (!r.ok) return;
    const { skills } = await r.json();
    const groups = $('skillGroups');
    groups.innerHTML = '';
    for (const cat of Object.keys(SKILL_CATS)) {
      const items = skills.filter((s) => s.category === cat);
      if (!items.length) continue;
      const g = document.createElement('div');
      g.className = 'skill-group';
      g.innerHTML = '<div class="cap">' + esc(SKILL_CATS[cat]) + '</div>';
      const grid = document.createElement('div');
      grid.className = 'skill-grid';
      for (const s of items) {
        const chip = document.createElement('span');
        chip.className = 'skill-chip clickable';
        chip.dataset.status = s.status;
        const hint = s.status === 'planned' ? '（点击看规划）' : '（点击试试）';
        chip.innerHTML = '<i></i>' + esc(s.label) + '<span class="tip">' + esc(s.desc + ' ' + hint) + '</span>';
        chip.addEventListener('click', () => runSkillDemo(s));
        grid.appendChild(chip);
        skillChipByKey[s.key] = chip;
      }
      g.appendChild(grid);
      groups.appendChild(g);
    }
    $('skillCount').textContent = skills.length + ' 项能力';
  } catch { /* matrix is progressive enhancement */ }
}
loadSkillMatrix();
function pulseSkill(key) {
  const chip = skillChipByKey[key];
  if (!chip) return;
  chip.classList.remove('active');
  void chip.offsetWidth;  // restart animation
  chip.classList.add('active');
  setTimeout(() => chip.classList.remove('active'), 6000);
}
async function runSkillDemo(s) {
  pulseSkill(s.key);
  if (s.demo_call) { startRealtimeCall(); return; }
  if (s.status === 'planned') { renderPlannedCard(s); return; }
  if (s.demo_scenario) {
    try {
      const r = await fetch(appPath('/showcase/nudge?scenario=' + encodeURIComponent(s.demo_scenario)));
      if (r.ok) showNudge(await r.json());
    } catch { /* demo affordance */ }
    return;
  }
  if (s.demo_say) sendText(s.demo_say);
}
function renderPlannedCard(s) {
  const el = skillCardShell(s.label + ' · 规划中', 'ROADMAP');
  el.querySelector('.sc-body').innerHTML =
    '<div class="ns-answer">' + esc(s.desc) + '</div>' +
    '<div class="sc-note">该技能已完成交互设计（hermes/skills 规范文件），等待对应后端 action 接入后点亮。</div>';
  streamEl.appendChild(el);
  streamEl.scrollTop = streamEl.scrollHeight;
}

/* ================= 厂内技能卡片 ================= */
function skillCardShell(title, source) {
  const el = document.createElement('div');
  el.className = 'skill-card-msg';
  el.innerHTML = '<div class="sc-head"><span>' + esc(title) + '</span>' +
    (source ? '<span class="src">' + esc(source) + '</span>' : '') + '</div>' +
    '<div class="sc-body"></div>';
  return el;
}
function renderSkillCard(data) {
  const card = data.skill_card;
  if (!card || !card.type) return;
  let el = null;
  if (card.type === 'weekly_draft') {
    el = skillCardShell(card.title || '周报草稿', 'WEEKLY GHOSTWRITER');
    const body = el.querySelector('.sc-body');
    for (const row of card.rows || []) {
      const sec = document.createElement('div');
      sec.className = 'wd-section';
      sec.innerHTML = '<div class="wd-cap">' + esc(row.section) + '</div><ul>' +
        (row.items || []).map((it) => '<li>' + esc(it) + '</li>').join('') + '</ul>';
      body.appendChild(sec);
    }
    if (card.footnote) body.insertAdjacentHTML('beforeend', '<div class="sc-note">✓ ' + esc(card.footnote) + '</div>');
  } else if (card.type === 'okr_progress') {
    el = skillCardShell('本季度 OKR 实况', 'ENTERPRISE SEARCH');
    const body = el.querySelector('.sc-body');
    body.innerHTML = '<div class="okr-obj">' + esc(card.objective || '') + '</div>';
    for (const kr of card.krs || []) {
      const item = document.createElement('div');
      item.className = 'okr-kr' + (kr.pct < 50 ? ' low' : '');
      item.innerHTML = '<div class="kr-name"><span>' + esc(kr.name) + '</span><b>' + kr.pct + '%</b></div>' +
        '<div class="okr-bar"><span class="fill"></span></div>';
      body.appendChild(item);
      requestAnimationFrame(() => setTimeout(() => {
        item.querySelector('.fill').style.width = kr.pct + '%';
      }, 150));
    }
    if (card.insight) body.insertAdjacentHTML('beforeend', '<div class="okr-insight">' + esc(card.insight) + '</div>');
  } else if (card.type === 'ritual_receipt') {
    el = skillCardShell(card.title || '已记录', 'RITUAL');
    el.querySelector('.sc-body').innerHTML =
      (card.lines || []).map((l) => '<div class="rr-line">' + esc(l) + '</div>').join('') +
      (card.stamp ? '<span class="rr-stamp">✓ ' + esc(card.stamp) + '</span>' : '');
  } else if (card.type === 'neisou_answer') {
    el = skillCardShell('内搜 · 确定性答案', 'NEISOU');
    el.querySelector('.sc-body').innerHTML =
      '<div class="ns-answer">' + esc(card.answer || '') + '</div>' +
      '<div class="ns-meta">' +
      (card.source ? '<span class="m">📄 ' + esc(card.source) + '</span>' : '') +
      (card.owner ? '<span class="m">可求助：<b>' + esc(card.owner) + '</b></span>' : '') +
      '</div>';
  } else if (card.type === 'neisou_results') {
    el = skillCardShell('内搜 · 「' + (card.query || '') + '」', 'NEISOU LIVE');
    const body = el.querySelector('.sc-body');
    const results = card.results || [];
    if (results.length) {
      for (const r of results) {
        const item = document.createElement('div');
        item.className = 'wd-section';
        item.innerHTML = '<div class="wd-cap" style="cursor:' + (r.url ? 'pointer' : 'default') + '">📄 ' + esc(r.title) + '</div>' +
          (r.snippet ? '<div class="rr-line">' + esc(r.snippet) + '</div>' : '');
        if (r.url) item.querySelector('.wd-cap').addEventListener('click', () => window.open(r.url, '_blank'));
        body.appendChild(item);
      }
    } else {
      body.innerHTML = '<div class="rr-line">' + esc(card.status === 'unauthorized' ? '内网搜索待授权' : '这次没有拿到结果') + '</div>';
    }
    if (card.note) body.insertAdjacentHTML('beforeend', '<div class="sc-note">' + esc(card.note) + '</div>');
  }
  if (!el) return;
  if (card.type === 'ritual_receipt' && card.skill === 'worry_parking' && card.worry_text) {
    // 压力粉碎机: crumple + shred the worry before the receipt appears
    const receipt = el;
    playWorryShredder(card.worry_text, () => {
      streamEl.appendChild(receipt);
      streamEl.scrollTop = streamEl.scrollHeight;
    });
  } else {
    streamEl.appendChild(el);
    streamEl.scrollTop = streamEl.scrollHeight;
  }
  // decision timeline: surface the tool trace on node 3
  const calls = (data.tool_calls || []).filter((c) => c.name !== 'hermes_agent');
  if (calls.length) {
    $('n3title').textContent = '厂内工具调用';
    $('n3body').innerHTML = calls.map((c) =>
      line('· <b>' + esc(c.name) + '</b> — ' + esc(c.reason || '') + (c.latency_ms ? ' <span style="color:var(--text-faint)">' + c.latency_ms + ' ms</span>' : ''))
    ).join('');
    setNode('n3', 'done');
  }
}

/* ================= 情境演示 director + 主动关怀 nudge ================= */
const directorBtn = $('directorBtn'), directorMenu = $('directorMenu');
const nudgeEl = $('nudge'), nudgeIcon = $('nudgeIcon'), nudgeTitle = $('nudgeTitle');
const nudgeText = $('nudgeText'), nudgeAction = $('nudgeAction'), nudgeDismiss = $('nudgeDismiss');
let nudgeConfig = null;
directorBtn.addEventListener('click', (e) => {
  e.stopPropagation();
  directorMenu.hidden = !directorMenu.hidden;
});
document.addEventListener('click', (e) => {
  if (!directorMenu.hidden && !e.target.closest('.director')) directorMenu.hidden = true;
});
directorMenu.addEventListener('click', async (e) => {
  const btn = e.target.closest('button');
  if (!btn) return;
  directorMenu.hidden = true;
  if (btn.dataset.say) { sendText(btn.dataset.say); return; }
  const scenario = btn.dataset.scenario;
  if (!scenario) return;
  try {
    const r = await fetch(appPath('/showcase/nudge?scenario=' + encodeURIComponent(scenario)));
    if (!r.ok) return;
    showNudge(await r.json());
  } catch { /* demo affordance */ }
});
function showNudge(cfg) {
  nudgeConfig = cfg;
  nudgeIcon.textContent = cfg.icon || '💡';
  nudgeTitle.textContent = cfg.title || '';
  nudgeText.textContent = cfg.text || '';
  nudgeAction.textContent = cfg.action_label || '好';
  nudgeEl.hidden = false;
  pulseSkill(cfg.skill);
}
nudgeAction.addEventListener('click', () => {
  const cfg = nudgeConfig || {};
  nudgeEl.hidden = true;
  if (cfg.action === 'breathe') startBreathe();
  else if (cfg.action === 'send' && cfg.action_text) sendText(cfg.action_text);
});
nudgeDismiss.addEventListener('click', () => { nudgeEl.hidden = true; });

/* ================= 开口说话（回复 TTS） ================= */
const speakBtn = $('speakBtn');
let speakOn = localStorage.getItem('unwind_speak') !== 'off';
function renderSpeakBtn() {
  speakBtn.classList.toggle('muted', !speakOn);
  speakBtn.querySelector('.symbol').textContent = speakOn ? '🔊' : '🔇';
}
renderSpeakBtn();
speakBtn.addEventListener('click', () => {
  speakOn = !speakOn;
  localStorage.setItem('unwind_speak', speakOn ? 'on' : 'off');
  if (!speakOn) { try { ttsPlayer.pause(); } catch {} }
  renderSpeakBtn();
});
function speakReply(url) {
  if (!speakOn || !url) return;
  try {
    ttsPlayer.onended = null;
    ttsPlayer.src = url;
    ttsPlayer.play().catch(() => { /* autoplay blocked until first gesture */ });
  } catch { /* voice is an enhancement */ }
}

/* ================= 压力粉碎机 ================= */
const REDUCED_MOTION = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
function playWorryShredder(text, onDone) {
  if (REDUCED_MOTION) { onDone(); return; }
  const overlay = document.createElement('div');
  overlay.className = 'shred-overlay';
  const note = document.createElement('div');
  note.className = 'shred-note';
  note.textContent = text;
  overlay.appendChild(note);
  document.body.appendChild(overlay);
  const finish = () => { overlay.remove(); onDone(); };
  const failsafe = setTimeout(finish, 5200);  // never trap the receipt

  setTimeout(() => note.classList.add('crumple'), 900);
  setTimeout(() => {
    const rect = note.getBoundingClientRect();
    const cx = rect.left + rect.width / 2, cy = rect.top + rect.height / 2;
    note.style.visibility = 'hidden';
    burstShreds(cx, cy);
    const done = document.createElement('div');
    done.className = 'shred-done';
    done.textContent = '已粉碎，交给我';
    document.body.appendChild(done);
    requestAnimationFrame(() => done.classList.add('show'));
    setTimeout(() => { done.classList.remove('show'); overlay.classList.add('leaving'); }, 1400);
    setTimeout(() => { done.remove(); clearTimeout(failsafe); finish(); }, 1950);
  }, 1750);
}
function burstShreds(cx, cy) {
  const bits = [];
  for (let i = 0; i < 42; i++) {
    const el = document.createElement('span');
    el.className = 'shred-bit';
    el.style.left = cx + 'px'; el.style.top = cy + 'px';
    document.body.appendChild(el);
    const angle = Math.random() * Math.PI * 2;
    const speed = 3 + Math.random() * 7;
    bits.push({
      el, x: cx, y: cy,
      vx: Math.cos(angle) * speed, vy: Math.sin(angle) * speed - 4,
      rot: Math.random() * 360, vr: (Math.random() - .5) * 24,
      life: 1,
    });
  }
  const step = () => {
    let alive = false;
    for (const b of bits) {
      b.vy += 0.32; b.x += b.vx; b.y += b.vy; b.rot += b.vr;
      b.life -= 0.012;
      if (b.life > 0 && b.y < innerHeight + 30) {
        alive = true;
        b.el.style.left = '0'; b.el.style.top = '0';
        b.el.style.transform = 'translate(' + b.x + 'px, ' + b.y + 'px) rotate(' + b.rot + 'deg)';
        b.el.style.opacity = Math.max(0, b.life);
      } else {
        b.el.remove();
      }
    }
    if (alive) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

/* ================= 麦克风呼吸感应 ================= */
const breatheMicBtn = $('breatheMicBtn'), breatheMicLabel = $('breatheMicLabel'), micHint = $('micHint');
let micOn = false, micStreamRef = null, micCtx = null, micAnalyser = null, micRaf = null, micEnv = 0;
async function startMicBreath() {
  try {
    micStreamRef = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false } });
  } catch {
    micHint.textContent = '麦克风不可用，继续用引导节奏';
    return;
  }
  clearBreathe();                       // guided timers off — you set the pace now
  breatheActionsEl.hidden = true;
  breatheRoundsEl.style.visibility = 'hidden';
  micOn = true;
  breatheMicBtn.classList.add('on');
  breatheMicLabel.textContent = '正在听你的呼吸';
  micHint.textContent = '对着麦克风慢慢呼气，球会跟着你落下';
  micCtx = new (window.AudioContext || window.webkitAudioContext)();
  const src = micCtx.createMediaStreamSource(micStreamRef);
  micAnalyser = micCtx.createAnalyser();
  micAnalyser.fftSize = 1024;
  src.connect(micAnalyser);
  orbEl.style.transitionDuration = '0.18s';
  orbGlowEl.style.transitionDuration = '0.18s';
  const buf = new Float32Array(micAnalyser.fftSize);
  const loop = () => {
    if (!micOn) return;
    micAnalyser.getFloatTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
    const rms = Math.sqrt(sum / buf.length);
    micEnv = micEnv * 0.88 + rms * 0.12;          // smoothed breath envelope
    const level = Math.min(1, micEnv * 14);
    const scale = 1.02 - level * 0.4;              // exhale (audible) → orb settles
    orbEl.style.transform = 'scale(' + scale.toFixed(3) + ')';
    orbGlowEl.style.transform = 'scale(' + scale.toFixed(3) + ')';
    breathePhaseEl.textContent = level > 0.22 ? '呼——' : '吸气';
    breatheCountEl.textContent = level > 0.22 ? '把它都吐出去' : '轻轻地';
    micRaf = requestAnimationFrame(loop);
  };
  loop();
}
function stopMicBreath(restartGuided) {
  if (!micOn && !micStreamRef) return;
  micOn = false;
  if (micRaf) cancelAnimationFrame(micRaf);
  if (micStreamRef) { micStreamRef.getTracks().forEach((t) => t.stop()); micStreamRef = null; }
  if (micCtx && micCtx.state !== 'closed') micCtx.close();
  micCtx = null; micAnalyser = null; micEnv = 0;
  breatheMicBtn.classList.remove('on');
  breatheMicLabel.textContent = '跟随我的呼吸';
  micHint.textContent = '';
  breatheRoundsEl.style.visibility = '';
  if (restartGuided) startBreathe();
}
breatheMicBtn.addEventListener('click', () => {
  if (micOn) stopMicBreath(true);
  else startMicBreath();
});
// leaving the overlay must always release the mic — the close/done/again
// buttons captured the ORIGINAL stopBreathe reference, so they get their own
// mic-release listeners; the Escape path calls by name and hits the wrapper.
const _origStopBreathe = stopBreathe;
stopBreathe = function () { stopMicBreath(false); _origStopBreathe(); };
$('breatheClose').addEventListener('click', () => stopMicBreath(false));
$('breatheDone').addEventListener('click', () => stopMicBreath(false));
$('breatheAgain').addEventListener('click', () => stopMicBreath(false));

/* ================= 声音涟漪场 ================= */
const rippleCanvas = $('rippleCanvas');
let rippleCtx2d = null, rippleAnalyser = null, rippleAudioCtx = null, rippleRaf = null;
let rippleBands = [0, 0, 0], rippleRings = [], lastLow = 0;
function ensureRippleAudio() {
  if (rippleAudioCtx || REDUCED_MOTION) return;
  try {
    rippleAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const src = rippleAudioCtx.createMediaElementSource(player);
    rippleAnalyser = rippleAudioCtx.createAnalyser();
    rippleAnalyser.fftSize = 512;
    src.connect(rippleAnalyser);
    rippleAnalyser.connect(rippleAudioCtx.destination);  // keep audible!
  } catch { rippleAudioCtx = null; }
}
function rippleResize() {
  rippleCanvas.width = innerWidth;
  rippleCanvas.height = innerHeight;
}
addEventListener('resize', rippleResize);
function startRippleField() {
  if (REDUCED_MOTION) return;
  ensureRippleAudio();
  if (!rippleAnalyser) return;
  if (rippleAudioCtx.state === 'suspended') rippleAudioCtx.resume();
  if (!rippleCtx2d) { rippleResize(); rippleCtx2d = rippleCanvas.getContext('2d'); }
  rippleCanvas.classList.add('on');
  if (rippleRaf) return;
  const freq = new Uint8Array(rippleAnalyser.frequencyBinCount);
  const draw = () => {
    if (player.paused) {  // fade out and stop
      rippleCanvas.classList.remove('on');
      rippleCtx2d.clearRect(0, 0, rippleCanvas.width, rippleCanvas.height);
      rippleRaf = null;
      return;
    }
    rippleAnalyser.getByteFrequencyData(freq);
    const band = (a, b) => { let s = 0; for (let i = a; i < b; i++) s += freq[i]; return s / (b - a) / 255; };
    const low = band(1, 10), mid = band(12, 48), high = band(60, 160);
    rippleBands[0] = rippleBands[0] * .82 + low * .18;
    rippleBands[1] = rippleBands[1] * .82 + mid * .18;
    rippleBands[2] = rippleBands[2] * .82 + high * .18;
    // beat: rising low edge spawns an expanding ink ring
    if (low > 0.32 && low - lastLow > 0.06 && rippleRings.length < 14) {
      rippleRings.push({ r: 60, a: 0.35, v: 2.2 + low * 4 });
    }
    lastLow = low;
    const W = rippleCanvas.width, H = rippleCanvas.height;
    const cx = W / 2, cy = H + 40;   // ripples radiate from the nowbar
    rippleCtx2d.clearRect(0, 0, W, H);
    const colors = ['214,90,71', '78,125,96', '103,132,145'];
    for (let k = 0; k < 3; k++) {
      const level = rippleBands[k];
      rippleCtx2d.beginPath();
      rippleCtx2d.arc(cx, cy, 130 + k * 120 + level * 260, 0, Math.PI * 2);
      rippleCtx2d.strokeStyle = 'rgba(' + colors[k] + ',' + (0.05 + level * 0.22).toFixed(3) + ')';
      rippleCtx2d.lineWidth = 1.5 + level * 8;
      rippleCtx2d.stroke();
    }
    rippleRings = rippleRings.filter((ring) => ring.a > 0.004);
    for (const ring of rippleRings) {
      ring.r += ring.v; ring.a *= 0.965;
      rippleCtx2d.beginPath();
      rippleCtx2d.arc(cx, cy, ring.r, 0, Math.PI * 2);
      rippleCtx2d.strokeStyle = 'rgba(214,90,71,' + ring.a.toFixed(3) + ')';
      rippleCtx2d.lineWidth = 1.2;
      rippleCtx2d.stroke();
    }
    rippleRaf = requestAnimationFrame(draw);
  };
  rippleRaf = requestAnimationFrame(draw);
}
player.addEventListener('play', startRippleField);

/* ================= 定时渐弱（播放器本地执行） ================= */
let sleepTimerHandle = null, sleepTimerEnd = 0, baseSub = '';
function clearSleepTimer(restoreVolume) {
  if (sleepTimerHandle) { clearInterval(sleepTimerHandle); sleepTimerHandle = null; }
  if (restoreVolume) player.volume = 1;
}
function armSleepTimer(sec, fade) {
  clearSleepTimer(true);
  sleepTimerEnd = Date.now() + sec * 1000;
  baseSub = npSub.textContent || '';
  addMsg('system', '⏱ ' + Math.round(sec / 60) + ' 分钟后' + (fade ? '声音渐弱停止' : '自动停止'));
  const FADE_WINDOW = Math.min(30, sec / 3);
  sleepTimerHandle = setInterval(() => {
    const left = (sleepTimerEnd - Date.now()) / 1000;
    if (left <= 0) {
      clearSleepTimer(false);
      player.pause(); player.volume = 1;
      npSub.textContent = baseSub;
      nowbar.classList.remove('show');
      return;
    }
    if (fade && left <= FADE_WINDOW) player.volume = Math.max(0.02, left / FADE_WINDOW);
    const mm = String(Math.floor(left / 60)).padStart(2, '0');
    const ss = String(Math.floor(left % 60)).padStart(2, '0');
    npSub.textContent = baseSub + ' · ⏱ ' + mm + ':' + ss;
  }, 1000);
}
"""
