VOICE_SCRIPT = r"""
const TARGET_RATE = 16000;
const FRAME_MS = 200;
const wsUrl = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/voice/ws';
const STOP_AUDIO_RE = /(停一下|停下|停止|暂停|停掉|关掉|别放了?|别播了?|不要放了?|不听了|够了|静音|安静一点)/;

const $ = (id) => document.getElementById(id);
const talkBtn = $('talk'), statusEl = $('status'), convoEl = $('convo'), player = $('player'), assetPlayer = $('assetPlayer');

let ws = null, audioCtx = null, workletNode = null, micStream = null, source = null;
let recording = false, inputRate = 48000;
let resampleBuffer = [];      // accumulated 16k Float32 samples awaiting a frame
let peakLevel = 0, sentBytes = 0;
// latency timers (per utterance)
let tRelease = 0, tAsrFinal = 0, gotAsrFirst = false;
let assistantMsgEl = null, assistantText = '', audioParts = [], gotTtsFirst = false, gotLlmFirst = false, playedFirst = false;
let replyPlaybackStarted = false, spokenReplyFinished = false;
let lastUserEl = null, pendingAsset = null, activeJobId = null, activeJobPollTimer = null;
let progressMsgEl = null, progressFillEl = null, progressLabelEl = null, progressTimer = null, progressValue = 0, progressCap = 0;
const samples = { 'asr-first': [], 'asr-final': [], 'llm': [], 'tts': [], 'e2e': [] };

function setStatus(t) { statusEl.textContent = t; }
function addMsg(role, text) {
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.innerHTML = '<span class="who">' + (role === 'user' ? '我' : '助手') + '</span>' + text;
  convoEl.appendChild(div); convoEl.scrollTop = convoEl.scrollHeight;
  return div;
}
function escapeHtml(value) {
  return String(value || '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
}
function record(metric, ms) {
  $('v-' + metric).textContent = Math.round(ms);
  samples[metric].push(ms);
  const arr = samples[metric], avg = arr.reduce((a,b)=>a+b,0)/arr.length;
  $('a-' + metric).textContent = Math.round(avg);
}

// Linear resample Float32 from inputRate -> TARGET_RATE.
function resample(float32, fromRate) {
  if (fromRate === TARGET_RATE) return float32;
  const ratio = fromRate / TARGET_RATE;
  const outLen = Math.floor(float32.length / ratio);
  const out = new Float32Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const idx = i * ratio;
    const lo = Math.floor(idx), hi = Math.min(lo + 1, float32.length - 1);
    out[i] = float32[lo] + (float32[hi] - float32[lo]) * (idx - lo);
  }
  return out;
}

function floatToInt16(float32) {
  const out = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++) {
    let s = Math.max(-1, Math.min(1, float32[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out.buffer;
}

// Called per worklet frame while recording. Resamples, tracks level, and emits
// ~FRAME_MS 16k frames over the websocket.
function onAudioFrame(float32) {
  // peak level for debug
  let peak = 0;
  for (let i = 0; i < float32.length; i++) { const a = Math.abs(float32[i]); if (a > peak) peak = a; }
  if (peak > peakLevel) peakLevel = peak;

  const rs = resample(float32, inputRate);
  for (let i = 0; i < rs.length; i++) resampleBuffer.push(rs[i]);

  const frameSamples = TARGET_RATE * FRAME_MS / 1000; // 3200
  while (resampleBuffer.length >= frameSamples) {
    const chunk = Float32Array.from(resampleBuffer.splice(0, frameSamples));
    const buf = floatToInt16(chunk);
    sentBytes += buf.byteLength;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(buf);
  }
  // live debug
  setStatus(`聆听中… 输入${inputRate}Hz 音量${(peakLevel*100).toFixed(0)}% 已发${(sentBytes/1024).toFixed(0)}KB`);
}

function flushTail() {
  if (resampleBuffer.length > 0) {
    const buf = floatToInt16(Float32Array.from(resampleBuffer));
    sentBytes += buf.byteLength;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(buf);
    resampleBuffer = [];
  }
}

async function initAudio() {
  micStream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true }
  });
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  inputRate = audioCtx.sampleRate;  // real rate (often 44100/48000), don't assume 16k
  const workletCode = `
    class PCMWorklet extends AudioWorkletProcessor {
      process(inputs) {
        const ch = inputs[0][0];
        if (ch && ch.length) this.port.postMessage(ch.slice(0));
        return true;
      }
    }
    registerProcessor('pcm-worklet', PCMWorklet);
  `;
  const blob = new Blob([workletCode], { type: 'application/javascript' });
  await audioCtx.audioWorklet.addModule(URL.createObjectURL(blob));
  source = audioCtx.createMediaStreamSource(micStream);
  workletNode = new AudioWorkletNode(audioCtx, 'pcm-worklet');
  workletNode.port.onmessage = (e) => { if (recording) onAudioFrame(e.data); };
  source.connect(workletNode);
  // Do NOT connect to destination (avoids echo). Worklet still runs.
}

function connectWS() {
  ws = new WebSocket(wsUrl);
  ws.binaryType = 'arraybuffer';
  ws.onopen = () => { setStatus('已连接，按住说话（输入采样率 ' + inputRate + 'Hz）'); talkBtn.disabled = false; };
  ws.onclose = () => { clearJobPoll(); setStatus('连接已关闭'); talkBtn.disabled = true; };
  ws.onerror = () => setStatus('连接出错');
  ws.onmessage = (ev) => {
    if (ev.data instanceof ArrayBuffer) {
      if (!gotTtsFirst) { gotTtsFirst = true; record('tts', performance.now() - tAsrFinal); }
      audioParts.push(ev.data);
      return;
    }
    const msg = JSON.parse(ev.data);
    if (msg.type === 'user_text') {
      const txt = (msg.text || '').trim();
      if (!gotAsrFirst && txt) { gotAsrFirst = true; record('asr-first', performance.now() - tRelease); }
      if (txt) updateUserMsg(txt);   // only show bubble once we have real text
      if (msg.is_final) {
        tAsrFinal = performance.now();
        record('asr-final', tAsrFinal - tRelease);
        if (isStopAudioText(txt)) stopSleepAudio('已停止当前播放');
      }
    } else if (msg.type === 'assistant_text') {
      if (!gotLlmFirst) { gotLlmFirst = true; record('llm', performance.now() - tAsrFinal); }
      if (!assistantMsgEl) { assistantMsgEl = addMsg('assistant', ''); assistantText = ''; }
      assistantText += msg.text;
      assistantMsgEl.innerHTML = '<span class="who">助手</span>' + assistantText;
    } else if (msg.type === 'stop_audio') {
      stopSleepAudio(msg.text || '已停止当前播放');
    } else if (msg.type === 'audio_lookup') {
      startProgress(msg.text || '正在查找合适的助眠音频…', 8, 55);
      setStatus('正在查找助眠音频…');
    } else if (msg.type === 'audio_asset') {
      pendingAsset = { url: msg.url, title: msg.text || '助眠音频', type: msg.audio_type };
      completeProgress('已找到：《' + pendingAsset.title + '》');
      addMsg('assistant', '<span style="color:#ffd56b">♪ 已为你找到：《' + escapeHtml(pendingAsset.title) + '》</span>');
      maybePlayPendingAsset();
    } else if (msg.type === 'audio_job') {
      const title = msg.text || '助眠音频';
      updateProgress('本地没有合适的音频，正在实时生成…', Math.max(progressValue, 58), 92);
      addMsg('assistant', '<span style="color:#ffd56b">♪ 正在生成：《' + escapeHtml(title) + '》</span>');
      pollAudioJob(msg.job_id, title, msg.audio_type);
    } else if (msg.type === 'speech_end') {
      playReply();
    } else if (msg.type === 'turn_end') {
      playReply();
      if (!activeJobId) {
        if (progressMsgEl && !pendingAsset) failProgress('暂时没找到合适的音频，可以换个说法再试试。');
        setStatus('已连接，按住说话');
      }
    } else if (msg.type === 'error') {
      setStatus('错误：' + msg.text);
    }
  };
}

function updateUserMsg(text) {
  if (!lastUserEl) lastUserEl = addMsg('user', '');
  lastUserEl.innerHTML = '<span class="who">我</span>' + text;
}

function isStopAudioText(text) {
  return STOP_AUDIO_RE.test(String(text || ''));
}

function clearProgressTimer() {
  if (progressTimer) clearInterval(progressTimer);
  progressTimer = null;
}

function renderProgress() {
  if (progressFillEl) progressFillEl.style.width = Math.max(0, Math.min(100, progressValue)) + '%';
}

function tickProgress() {
  if (!progressMsgEl || progressValue >= progressCap) return;
  const step = Math.max(1, Math.round((progressCap - progressValue) * 0.14));
  progressValue = Math.min(progressCap, progressValue + step);
  renderProgress();
}

function startProgress(label, value, cap) {
  clearProgressTimer();
  progressValue = value; progressCap = cap;
  progressMsgEl = addMsg(
    'assistant',
    '<div class="progress-card"><div class="progress-label"></div><div class="progress-track"><div class="progress-fill"></div></div></div>'
  );
  progressLabelEl = progressMsgEl.querySelector('.progress-label');
  progressFillEl = progressMsgEl.querySelector('.progress-fill');
  progressLabelEl.textContent = label;
  renderProgress();
  progressTimer = setInterval(tickProgress, 900);
}

function updateProgress(label, value, cap) {
  if (!progressMsgEl) {
    startProgress(label, value || 8, cap || 55);
    return;
  }
  if (progressLabelEl) progressLabelEl.textContent = label;
  progressValue = Math.max(progressValue, value || progressValue);
  progressCap = cap || progressCap;
  renderProgress();
}

function completeProgress(label) {
  if (!progressMsgEl) return;
  clearProgressTimer();
  if (progressLabelEl) progressLabelEl.textContent = label;
  progressValue = 100;
  renderProgress();
  progressMsgEl = progressFillEl = progressLabelEl = null;
}

function failProgress(label) {
  if (!progressMsgEl) return;
  clearProgressTimer();
  if (progressLabelEl) progressLabelEl.textContent = label;
  progressMsgEl = progressFillEl = progressLabelEl = null;
}

function clearJobPoll() {
  if (activeJobPollTimer) clearTimeout(activeJobPollTimer);
  activeJobPollTimer = null;
  activeJobId = null;
}

function stopSleepAudio(statusText) {
  pendingAsset = null;
  clearJobPoll();
  failProgress(statusText);
  assetPlayer.pause();
  assetPlayer.removeAttribute('src');
  assetPlayer.load();
  setStatus(statusText);
}

function maybePlayPendingAsset() {
  if (!pendingAsset) return;
  if (!replyPlaybackStarted || (!spokenReplyFinished && !player.ended)) return;
  playAsset();
}

function pollAudioJob(jobId, title, audioType, attempt = 0) {
  if (!jobId) return;
  activeJobId = jobId;
  setStatus('正在生成助眠音频…');
  fetch('/generation-jobs/' + encodeURIComponent(jobId))
    .then((res) => {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.json();
    })
    .then((job) => {
      if (activeJobId !== jobId) return;
      if (job.status === 'succeeded' && job.asset && job.asset.playback_url) {
        activeJobId = null;
        activeJobPollTimer = null;
        pendingAsset = {
          url: job.asset.playback_url,
          title: job.asset.title || title || '助眠音频',
          type: job.asset.type || audioType
        };
        completeProgress('已生成：《' + pendingAsset.title + '》');
        addMsg('assistant', '<span style="color:#ffd56b">♪ 已生成：《' + escapeHtml(pendingAsset.title) + '》</span>');
        maybePlayPendingAsset();
      } else if (job.status === 'failed' || job.status === 'cancelled') {
        activeJobId = null;
        activeJobPollTimer = null;
        const reason = job.error_message ? '：' + job.error_message : '';
        failProgress('生成失败' + reason);
        setStatus('生成失败' + reason);
        addMsg('assistant', '<span style="color:#ff9d9d">生成失败' + escapeHtml(reason) + '</span>');
      } else {
        updateProgress('正在实时生成…', Math.max(progressValue, 64), 92);
        const delay = attempt < 3 ? 1000 : 2500;
        activeJobPollTimer = setTimeout(() => pollAudioJob(jobId, title, audioType, attempt + 1), delay);
      }
    })
    .catch((err) => {
      if (activeJobId !== jobId) return;
      if (attempt < 20) {
        activeJobPollTimer = setTimeout(() => pollAudioJob(jobId, title, audioType, attempt + 1), 2500);
      } else {
        activeJobId = null;
        activeJobPollTimer = null;
        failProgress('生成状态查询失败：' + err.message);
        setStatus('生成状态查询失败：' + err.message);
      }
    });
}

function playReply() {
  // Play the spoken guidance (TTS mp3) first; chain the sleep-audio asset after.
  if (replyPlaybackStarted) {
    maybePlayPendingAsset();
    return;
  }
  replyPlaybackStarted = true;
  if (audioParts.length === 0) {
    spokenReplyFinished = true;
    if (pendingAsset) { playAsset(); }
    else if (!activeJobId && !progressMsgEl) { setStatus('（无音频返回，可能没识别到说话内容）'); }
    return;
  }
  const blob = new Blob(audioParts, { type: 'audio/mpeg' });
  player.src = URL.createObjectURL(blob);
  player.onended = () => {
    spokenReplyFinished = true;
    maybePlayPendingAsset();
  };
  player.play().then(() => {
    if (!playedFirst) { playedFirst = true; record('e2e', performance.now() - tRelease); }
  }).catch(() => {
    spokenReplyFinished = true;
    maybePlayPendingAsset();
  });
}

function playAsset() {
  const asset = pendingAsset; pendingAsset = null;
  if (!asset) return;
  setStatus('正在播放助眠音频：《' + asset.title + '》');
  assetPlayer.src = asset.url;
  assetPlayer.play().catch((e) => setStatus('音频播放失败：' + e.message));
}

function startUtterance() {
  if (recording || !ws || ws.readyState !== WebSocket.OPEN) return;
  recording = true;
  if (audioCtx.state === 'suspended') audioCtx.resume();
  talkBtn.classList.add('recording'); talkBtn.textContent = '松开结束';
  // reset per-utterance state
  failProgress('已收到新的语音请求');
  clearJobPoll();
  gotAsrFirst = gotLlmFirst = gotTtsFirst = playedFirst = false;
  replyPlaybackStarted = false; spokenReplyFinished = false;
  assistantMsgEl = null; assistantText = ''; lastUserEl = null; pendingAsset = null;
  audioParts = []; resampleBuffer = []; peakLevel = 0; sentBytes = 0;
  setStatus('聆听中…');
}

function endUtterance() {
  if (!recording) return;
  recording = false;
  flushTail();
  tRelease = performance.now();
  talkBtn.classList.remove('recording'); talkBtn.textContent = '按住说话';
  if (sentBytes < 3200) { setStatus('几乎没采集到音频，请检查麦克风权限/音量'); }
  else { setStatus('识别中…（音量峰值 ' + (peakLevel*100).toFixed(0) + '%）'); }
  ws.send(JSON.stringify({ type: 'utterance_end' }));
}

talkBtn.addEventListener('mousedown', startUtterance);
talkBtn.addEventListener('mouseup', endUtterance);
talkBtn.addEventListener('mouseleave', () => { if (recording) endUtterance(); });
talkBtn.addEventListener('touchstart', (e) => { e.preventDefault(); startUtterance(); });
talkBtn.addEventListener('touchend', (e) => { e.preventDefault(); endUtterance(); });

(async () => {
  try { await initAudio(); connectWS(); }
  catch (err) { setStatus('麦克风初始化失败：' + err.message); }
})();
"""
