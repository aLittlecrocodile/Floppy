SHOWCASE_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>墨息 Truce · AI 原生降压工具</title>
<style>
  :root {
    --ink: #0a0e17;
    --ink-2: #101828;
    --panel: rgba(20, 28, 46, 0.72);
    --panel-border: rgba(120, 150, 220, 0.14);
    --text: #dce4f2;
    --text-dim: #8b97ad;
    --accent: #7c9cf5;
    --accent-soft: rgba(124, 156, 245, 0.16);
    --good: #6fd3a3;
    --warn: #f5c97c;
    --bad: #f08a8a;
    --radius: 14px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; }
  body {
    font-family: "PingFang SC", "Microsoft YaHei", -apple-system, "Segoe UI", sans-serif;
    color: var(--text);
    background: var(--ink);
    overflow-x: hidden;
  }

  /* ---- ambient background ---- */
  .ambient {
    position: fixed; inset: 0; z-index: -2;
    background:
      radial-gradient(60% 80% at 20% 10%, rgba(60, 80, 160, 0.35), transparent 60%),
      radial-gradient(50% 70% at 85% 25%, rgba(90, 60, 150, 0.22), transparent 65%),
      radial-gradient(70% 60% at 50% 100%, rgba(30, 60, 110, 0.30), transparent 70%),
      var(--ink);
    animation: drift 24s ease-in-out infinite alternate;
  }
  @keyframes drift {
    0%   { filter: hue-rotate(0deg) brightness(1); }
    100% { filter: hue-rotate(18deg) brightness(1.08); }
  }
  .orb {
    position: fixed; z-index: -1;
    top: 8vh; right: 6vw;
    width: 26vmin; height: 26vmin; border-radius: 50%;
    background: radial-gradient(circle at 38% 34%, rgba(160, 185, 255, 0.35), rgba(124, 156, 245, 0.10) 55%, transparent 75%);
    animation: breathe 4.5s ease-in-out infinite;
    pointer-events: none;
  }
  @keyframes breathe {
    0%, 100% { transform: scale(1);    opacity: 0.75; }
    50%      { transform: scale(1.12); opacity: 1; }
  }
  @media (prefers-reduced-motion: reduce) {
    .ambient, .orb { animation: none; }
    * { transition: none !important; }
  }

  /* ---- layout ---- */
  .wrap { max-width: 1180px; margin: 0 auto; padding: 28px 24px 120px; }

  header.hero { padding: 8px 4px 26px; display: flex; align-items: baseline; gap: 16px; flex-wrap: wrap; }
  .wordmark { font-size: 30px; font-weight: 700; letter-spacing: 2px; }
  .wordmark .en { color: var(--accent); font-weight: 600; margin-left: 8px; font-size: 22px; letter-spacing: 4px; }
  .tagline { color: var(--text-dim); font-size: 15px; }
  .health { margin-left: auto; display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--text-dim); }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--text-dim); }
  .dot.ok  { background: var(--good); box-shadow: 0 0 8px rgba(111, 211, 163, 0.7); }
  .dot.down{ background: var(--bad);  box-shadow: 0 0 8px rgba(240, 138, 138, 0.7); }

  main { display: grid; grid-template-columns: minmax(0, 7fr) minmax(0, 5fr); gap: 20px; }
  @media (max-width: 900px) { main { grid-template-columns: 1fr; } }

  .card {
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-radius: var(--radius);
    backdrop-filter: blur(14px);
  }

  /* ---- chat column ---- */
  .chat { display: flex; flex-direction: column; min-height: 66vh; }
  .chat-head { padding: 16px 20px 12px; border-bottom: 1px solid var(--panel-border); font-size: 14px; color: var(--text-dim); }
  .stream { flex: 1; overflow-y: auto; padding: 18px 20px; display: flex; flex-direction: column; gap: 12px; scroll-behavior: smooth; }
  .msg { max-width: 84%; padding: 10px 14px; border-radius: 12px; font-size: 14.5px; line-height: 1.65; animation: rise .3s ease; }
  @keyframes rise { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
  .msg.user { align-self: flex-end; background: var(--accent-soft); border: 1px solid rgba(124,156,245,0.25); }
  .msg.assistant { align-self: flex-start; background: rgba(255,255,255,0.045); border: 1px solid rgba(255,255,255,0.06); }
  .msg.system { align-self: center; color: var(--text-dim); font-size: 12.5px; background: none; border: none; padding: 2px; }

  .chips { display: flex; gap: 8px; flex-wrap: wrap; padding: 0 20px 12px; }
  .chip {
    font-size: 12.5px; color: var(--text-dim);
    border: 1px solid var(--panel-border); border-radius: 999px;
    padding: 6px 13px; cursor: pointer; background: rgba(255,255,255,0.03);
    transition: all .18s ease;
  }
  .chip:hover { color: var(--text); border-color: var(--accent); background: var(--accent-soft); }

  .input-row { display: flex; gap: 10px; padding: 14px 20px 18px; border-top: 1px solid var(--panel-border); align-items: flex-end; }
  textarea#prompt {
    flex: 1; resize: none; min-height: 46px; max-height: 120px;
    background: rgba(255,255,255,0.05); color: var(--text);
    border: 1px solid var(--panel-border); border-radius: 10px;
    padding: 12px 14px; font-size: 14px; font-family: inherit; line-height: 1.5;
    outline: none; transition: border-color .18s ease;
  }
  textarea#prompt:focus { border-color: var(--accent); }
  .btn {
    border: none; border-radius: 10px; cursor: pointer;
    font-size: 14px; font-family: inherit; padding: 12px 18px;
    color: #0b1020; background: var(--accent); font-weight: 600;
    transition: transform .12s ease, opacity .18s ease;
    white-space: nowrap;
  }
  .btn:hover { transform: translateY(-1px); }
  .btn:disabled { opacity: 0.45; cursor: not-allowed; transform: none; }
  .btn.ghost {
    color: var(--text); background: rgba(255,255,255,0.06);
    border: 1px solid var(--panel-border); font-weight: 500;
  }
  .btn.ghost.recording { background: var(--bad); color: #1a0d0d; border-color: transparent; animation: pulse 1.2s ease-in-out infinite; }
  @keyframes pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(240,138,138,0.5); } 50% { box-shadow: 0 0 0 9px rgba(240,138,138,0); } }

  /* ---- timeline column ---- */
  .tl-card { padding: 18px 20px 22px; align-self: start; position: sticky; top: 20px; }
  .tl-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 4px; }
  .tl-head h2 { font-size: 16px; font-weight: 600; }
  .tl-head .sub { font-size: 12px; color: var(--text-dim); }
  .tl-empty { color: var(--text-dim); font-size: 13px; padding: 26px 4px; text-align: center; }

  .tl { list-style: none; margin-top: 14px; }
  .tl li { position: relative; padding: 0 0 20px 30px; opacity: 0.35; transition: opacity .4s ease; }
  .tl li:last-child { padding-bottom: 2px; }
  .tl li::before {
    content: ''; position: absolute; left: 8px; top: 22px; bottom: 0;
    width: 1.5px; background: var(--panel-border);
  }
  .tl li:last-child::before { display: none; }
  .tl .node {
    position: absolute; left: 0; top: 3px;
    width: 17px; height: 17px; border-radius: 50%;
    border: 2px solid var(--text-dim); background: var(--ink-2);
  }
  .tl li.active { opacity: 1; }
  .tl li.active .node { border-color: var(--accent); box-shadow: 0 0 10px rgba(124,156,245,0.55); }
  .tl li.running .node { animation: nodeBreathe 1.4s ease-in-out infinite; }
  @keyframes nodeBreathe { 0%,100% { box-shadow: 0 0 4px rgba(124,156,245,0.3); } 50% { box-shadow: 0 0 14px rgba(124,156,245,0.85); } }
  .tl li.done .node { background: var(--accent); border-color: var(--accent); }
  .tl li.failed .node { background: var(--bad); border-color: var(--bad); box-shadow: none; }

  .tl h3 { font-size: 13.5px; font-weight: 600; margin-bottom: 4px; display: flex; align-items: center; gap: 8px; }
  .tl .meta { font-size: 11.5px; color: var(--text-dim); }
  .tl .body { font-size: 12.5px; color: var(--text-dim); line-height: 1.7; margin-top: 4px; }
  .tl .body .line { animation: rise .35s ease both; }

  .badge {
    display: inline-block; font-size: 11px; font-weight: 600;
    padding: 2px 9px; border-radius: 999px;
    background: var(--accent-soft); color: var(--accent);
    border: 1px solid rgba(124,156,245,0.3);
  }
  .badge.cache { background: rgba(111,211,163,0.12); color: var(--good); border-color: rgba(111,211,163,0.3); }
  .badge.warn  { background: rgba(245,201,124,0.12); color: var(--warn); border-color: rgba(245,201,124,0.3); }

  .tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
  .tag { font-size: 11px; padding: 2px 9px; border-radius: 999px; background: rgba(255,255,255,0.06); color: var(--text-dim); border: 1px solid var(--panel-border); }

  .conf { display: inline-flex; align-items: center; gap: 6px; margin-left: 4px; }
  .conf .bar { width: 54px; height: 4px; border-radius: 2px; background: rgba(255,255,255,0.1); overflow: hidden; }
  .conf .fill { height: 100%; border-radius: 2px; background: var(--accent); transition: width .6s ease; }

  .shimmer {
    background: linear-gradient(90deg, rgba(255,255,255,0.05) 25%, rgba(255,255,255,0.14) 50%, rgba(255,255,255,0.05) 75%);
    background-size: 200% 100%; animation: shimmer 1.6s linear infinite;
    border-radius: 6px; color: transparent; user-select: none;
  }
  @keyframes shimmer { from { background-position: 200% 0; } to { background-position: -200% 0; } }

  .progress-ring { display: flex; align-items: center; gap: 10px; margin-top: 8px; }
  .ring {
    width: 22px; height: 22px; border-radius: 50%;
    border: 2.5px solid rgba(124,156,245,0.2); border-top-color: var(--accent);
    animation: spin 1.4s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .progress-copy { font-size: 12.5px; color: var(--text-dim); }

  .suggest { margin-top: 10px; display: flex; flex-direction: column; gap: 8px; }
  .suggest .item {
    display: flex; align-items: center; justify-content: space-between; gap: 10px;
    font-size: 13px; padding: 9px 13px; border-radius: 10px;
    background: rgba(255,255,255,0.04); border: 1px solid var(--panel-border);
    cursor: pointer; transition: all .18s ease;
  }
  .suggest .item:hover { border-color: var(--accent); background: var(--accent-soft); }
  .suggest .item .play-ico { color: var(--accent); font-size: 15px; }

  /* ---- now playing bar ---- */
  .nowbar {
    position: fixed; left: 50%; bottom: 18px; transform: translate(-50%, 140%);
    width: min(720px, calc(100vw - 32px));
    display: flex; align-items: center; gap: 14px;
    padding: 12px 18px;
    background: rgba(16, 24, 40, 0.9);
    border: 1px solid var(--panel-border); border-radius: 16px;
    backdrop-filter: blur(18px);
    box-shadow: 0 12px 40px rgba(0,0,0,0.45);
    transition: transform .45s cubic-bezier(.22,.9,.3,1);
    z-index: 10;
  }
  .nowbar.show { transform: translate(-50%, 0); }
  .nowbar .play {
    width: 42px; height: 42px; border-radius: 50%; border: none; cursor: pointer;
    background: var(--accent); color: #0b1020; font-size: 16px;
    display: flex; align-items: center; justify-content: center; flex-shrink: 0;
  }
  .nowbar .info { flex: 1; min-width: 0; }
  .nowbar .title { font-size: 14px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .nowbar .sub { font-size: 11.5px; color: var(--text-dim); margin-top: 2px; }
  .wave { display: flex; align-items: center; gap: 3px; height: 26px; flex-shrink: 0; }
  .wave span { width: 3px; border-radius: 2px; background: var(--accent); height: 6px; opacity: .8; }
  .nowbar.playing .wave span { animation: wave 1.6s ease-in-out infinite; }
  .wave span:nth-child(2) { animation-delay: .18s; } .wave span:nth-child(3) { animation-delay: .36s; }
  .wave span:nth-child(4) { animation-delay: .54s; } .wave span:nth-child(5) { animation-delay: .72s; }
  @keyframes wave { 0%,100% { height: 6px; } 50% { height: 22px; } }

  footer { margin-top: 34px; text-align: center; font-size: 11.5px; color: rgba(139,151,173,0.55); }
</style>
</head>
<body>
<div class="ambient"></div>
<div class="orb"></div>

<div class="wrap">
  <header class="hero">
    <div class="wordmark">墨息<span class="en">TRUCE</span></div>
    <div class="tagline">面向高压研发团队的 AI 原生降压工具 · 与压力停战</div>
    <div class="health"><span class="dot" id="healthDot"></span><span id="healthText">检测服务状态…</span></div>
  </header>

  <main>
    <section class="card chat">
      <div class="chat-head">告诉墨息你现在的状态，它会决定为你播放、生成还是改编一段声音</div>
      <div class="stream" id="stream">
        <div class="msg assistant">你好，我是墨息。刚下会？发版了？还是脑子转个不停——说说看，我来帮你按下暂停键。</div>
      </div>
      <div class="chips" id="chips">
        <button class="chip">刚下线一个大版本，脑子还在转，帮我放松一下</button>
        <button class="chip">给我讲一个海边书店的睡前故事，十五分钟</button>
        <button class="chip">在现在的声音里加一点雨声</button>
        <button class="chip">带我做一段五分钟的呼吸冥想</button>
      </div>
      <div class="input-row">
        <textarea id="prompt" rows="1" placeholder="用一句话描述你现在的状态或想听的内容…"></textarea>
        <button class="btn ghost" id="talk" disabled>按住说话</button>
        <button class="btn" id="send">发送</button>
      </div>
    </section>

    <aside class="card tl-card">
      <div class="tl-head">
        <h2>Hermes 决策轨迹</h2>
        <span class="sub">agent 的每一步真实决策</span>
      </div>
      <div class="tl-empty" id="tlEmpty">发出第一条请求后，这里会展示智能体的实时决策过程</div>
      <ol class="tl" id="tl" style="display:none">
        <li id="n1"><span class="node"></span><h3>理解意图</h3><div class="meta" id="n1meta"></div><div class="body" id="n1body"></div></li>
        <li id="n2"><span class="node"></span><h3>选择技能 <span id="n2badge"></span></h3><div class="meta" id="n2meta"></div><div class="body" id="n2body"></div></li>
        <li id="n3"><span class="node"></span><h3 id="n3title">生成指令要点</h3><div class="body" id="n3body"></div></li>
        <li id="n4"><span class="node"></span><h3>执行结果</h3><div class="meta" id="n4meta"></div><div class="body" id="n4body"></div></li>
      </ol>
    </aside>
  </main>

  <footer>墨息 Truce · Hermes Agent 驱动 · 内部演示版</footer>
</div>

<div class="nowbar" id="nowbar">
  <button class="play" id="playBtn">▶</button>
  <div class="info">
    <div class="title" id="npTitle">—</div>
    <div class="sub" id="npSub">—</div>
  </div>
  <div class="wave"><span></span><span></span><span></span><span></span><span></span></div>
</div>

<audio id="player" preload="auto"></audio>
<audio id="ttsPlayer" preload="auto"></audio>

<script>
__SCRIPT__
</script>
</body>
</html>
"""
