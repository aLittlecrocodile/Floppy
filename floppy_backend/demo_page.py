from __future__ import annotations


DEMO_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Floppy Demo</title>
  <style>
    :root {
      color-scheme: light;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f5f7fb;
      color: #1c2430;
    }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
    }
    main {
      width: min(880px, calc(100vw - 32px));
      background: #ffffff;
      border: 1px solid #dce3ee;
      border-radius: 8px;
      box-shadow: 0 18px 40px rgba(20, 31, 48, 0.08);
      padding: 28px;
    }
    h1 {
      margin: 0 0 6px;
      font-size: 24px;
      letter-spacing: 0;
    }
    .sub {
      margin: 0 0 22px;
      color: #5b6675;
      font-size: 14px;
    }
    label {
      display: block;
      font-size: 13px;
      font-weight: 650;
      margin-bottom: 8px;
    }
    textarea {
      box-sizing: border-box;
      width: 100%;
      min-height: 112px;
      resize: vertical;
      border: 1px solid #c9d3df;
      border-radius: 6px;
      padding: 14px;
      font: inherit;
      line-height: 1.5;
      outline: none;
    }
    textarea:focus {
      border-color: #3d6fb6;
      box-shadow: 0 0 0 3px rgba(61, 111, 182, 0.14);
    }
    .bar {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-top: 14px;
    }
    button {
      height: 40px;
      border: 0;
      border-radius: 6px;
      padding: 0 16px;
      background: #244f8f;
      color: white;
      font-weight: 700;
      cursor: pointer;
    }
    button:disabled {
      opacity: 0.55;
      cursor: wait;
    }
    .status {
      color: #5b6675;
      font-size: 14px;
    }
    .result {
      margin-top: 22px;
      border-top: 1px solid #e7edf4;
      padding-top: 18px;
      display: none;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 16px;
    }
    .metric {
      border: 1px solid #e1e7ef;
      border-radius: 6px;
      padding: 10px;
      min-height: 58px;
      background: #fbfcfe;
    }
    .metric b {
      display: block;
      font-size: 12px;
      color: #667180;
      margin-bottom: 5px;
    }
    .metric span {
      font-size: 15px;
      font-weight: 700;
      word-break: break-word;
    }
    audio {
      width: 100%;
      margin-top: 8px;
    }
    pre {
      white-space: pre-wrap;
      word-break: break-word;
      background: #111827;
      color: #e5eefb;
      border-radius: 6px;
      padding: 14px;
      max-height: 260px;
      overflow: auto;
      font-size: 12px;
    }
    @media (max-width: 720px) {
      main { padding: 20px; }
      .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .bar { align-items: stretch; flex-direction: column; }
      button { width: 100%; }
    }
  </style>
</head>
<body>
  <main>
    <h1>Floppy 助眠音频 Demo</h1>
    <p class="sub">输入一句需求，系统会用 AI 归类并播放缓存音频；未命中时会生成新音频。</p>
    <label for="prompt">需求</label>
    <textarea id="prompt">我今晚压力很大，一直胡思乱想，想听一个温柔的呼吸冥想，最好有轻微雨声，15分钟</textarea>
    <div class="bar">
      <button id="submit">生成 / 推荐音频</button>
      <span class="status" id="status">就绪</span>
    </div>
    <section class="result" id="result">
      <div class="grid">
        <div class="metric"><b>动作</b><span id="action">-</span></div>
        <div class="metric"><b>分数</b><span id="score">-</span></div>
        <div class="metric"><b>Planner</b><span id="planner">-</span></div>
        <div class="metric"><b>耗时</b><span id="latency">-</span></div>
      </div>
      <audio id="audio" controls></audio>
      <pre id="detail"></pre>
    </section>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);
    const button = $("submit");
    const status = $("status");
    const result = $("result");
    const audio = $("audio");

    async function postJson(url, body) {
      const resp = await fetch(url, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body)
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || data.error || resp.statusText);
      return data;
    }

    button.addEventListener("click", async () => {
      const prompt = $("prompt").value.trim();
      if (!prompt) return;
      button.disabled = true;
      result.style.display = "none";
      audio.removeAttribute("src");
      status.textContent = "处理中...";
      try {
        const data = await postJson("/demo/chat", {request_text: prompt});
        $("action").textContent = data.action || "-";
        $("score").textContent = data.best_score == null ? "-" : data.best_score;
        $("planner").textContent = data.planner_meta ? data.planner_meta.planner_source : "-";
        $("latency").textContent = data.planner_meta ? `${data.planner_meta.planner_latency_ms}ms` : "-";
        $("detail").textContent = JSON.stringify(data, null, 2);
        if (data.audio_url) {
          audio.src = data.audio_url;
          status.textContent = "完成，可播放";
        } else {
          status.textContent = "完成，但没有音频 URL";
        }
        result.style.display = "block";
      } catch (err) {
        status.textContent = `失败：${err.message}`;
      } finally {
        button.disabled = false;
      }
    });
  </script>
</body>
</html>
"""
