from __future__ import annotations


VOICE_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Floppy 语音对话 Demo</title>
<style>
  :root { color-scheme: light; font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }
  body { margin: 0; min-height: 100vh; background: #0f1420; color: #e8edf5; display: grid; place-items: center; }
  main { width: min(720px, calc(100vw - 32px)); padding: 24px; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  .sub { color: #8b97a8; font-size: 13px; margin: 0 0 20px; }
  .talk-btn {
    width: 100%; padding: 22px; font-size: 18px; font-weight: 600; border: none; border-radius: 14px;
    background: #2b6fff; color: #fff; cursor: pointer; user-select: none; transition: background .12s, transform .05s;
  }
  .talk-btn:active, .talk-btn.recording { background: #d33b54; transform: scale(0.99); }
  .talk-btn:disabled { background: #394456; cursor: not-allowed; }
  .status { text-align: center; font-size: 13px; color: #8b97a8; margin: 10px 0 18px; min-height: 18px; }
  .convo { background: #161d2b; border: 1px solid #243044; border-radius: 12px; padding: 14px; min-height: 160px; max-height: 320px; overflow-y: auto; }
  .msg { margin: 8px 0; line-height: 1.5; font-size: 15px; }
  .msg.user { color: #7fb4ff; }
  .msg.assistant { color: #b7f5c8; }
  .msg .who { font-size: 11px; opacity: .6; margin-right: 6px; }
  .latency { margin-top: 16px; background: #161d2b; border: 1px solid #243044; border-radius: 12px; padding: 14px; }
  .latency h2 { font-size: 13px; margin: 0 0 10px; color: #8b97a8; font-weight: 600; }
  .lat-grid { display: grid; grid-template-columns: 1fr auto auto; gap: 6px 16px; font-size: 13px; font-variant-numeric: tabular-nums; }
  .lat-grid .label { color: #b6c0d0; }
  .lat-grid .val { text-align: right; color: #fff; }
  .lat-grid .avg { text-align: right; color: #8b97a8; }
  .lat-grid .head { color: #5d6a7d; font-size: 11px; }
  .e2e { color: #ffd56b !important; font-weight: 600; }
  audio { display: none; }
</style>
</head>
<body>
<main>
  <h1>Floppy 语音对话</h1>
  <p class="sub">按住按钮说话，松开后稍候即可听到智能体的语音回复。多轮对话会记住上下文。</p>
  <button id="talk" class="talk-btn" disabled>按住说话</button>
  <div class="status" id="status">正在初始化…</div>
  <div class="convo" id="convo"></div>
  <div class="latency">
    <h2>延迟评估（毫秒）</h2>
    <div class="lat-grid">
      <span class="head label">指标</span><span class="head val">本句</span><span class="head avg">平均</span>
      <span class="label">ASR 首字</span><span class="val" id="v-asr-first">—</span><span class="avg" id="a-asr-first">—</span>
      <span class="label">ASR 定稿</span><span class="val" id="v-asr-final">—</span><span class="avg" id="a-asr-final">—</span>
      <span class="label">LLM 首句</span><span class="val" id="v-llm">—</span><span class="avg" id="a-llm">—</span>
      <span class="label">TTS 首响</span><span class="val" id="v-tts">—</span><span class="avg" id="a-tts">—</span>
      <span class="label e2e">端到端首响</span><span class="val e2e" id="v-e2e">—</span><span class="avg" id="a-e2e">—</span>
    </div>
  </div>
  <audio id="player"></audio>
  <audio id="assetPlayer" loop></audio>
</main>
<script>
__SCRIPT__
</script>
</body>
</html>
"""
