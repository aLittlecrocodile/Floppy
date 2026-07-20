SHOWCASE_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Unwind · AI 原生降压工具</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ccircle cx='16' cy='16' r='13' fill='%238fb0ff'/%3E%3Ccircle cx='21' cy='13' r='11' fill='%23070b14'/%3E%3C/svg%3E">
<style>
  :root {
    --ink: #070b14;
    --ink-2: #0d1322;
    --panel: rgba(16, 23, 40, 0.55);
    --panel-border: rgba(148, 170, 220, 0.10);
    --panel-border-lit: rgba(148, 170, 220, 0.22);
    --text: #e6ecf7;
    --text-dim: #7e8aa3;
    --text-faint: #55607a;
    --accent: #8fb0ff;
    --accent-2: #a78bfa;
    --accent-soft: rgba(143, 176, 255, 0.13);
    --good: #7dd8ab;
    --warn: #f2c98a;
    --bad: #ef9a9a;
    --r-lg: 22px;
    --r-md: 14px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; }
  body {
    font-family: "PingFang SC", "HarmonyOS Sans SC", "Microsoft YaHei", -apple-system, "Segoe UI", sans-serif;
    color: var(--text);
    background: var(--ink);
    overflow-x: hidden;
    -webkit-font-smoothing: antialiased;
  }

  /* ---------- ambient aurora ---------- */
  .ambient {
    position: fixed; inset: -20%; z-index: -3;
    background:
      radial-gradient(42% 55% at 18% 12%, rgba(64, 92, 180, 0.34), transparent 62%),
      radial-gradient(38% 52% at 82% 18%, rgba(122, 82, 190, 0.24), transparent 64%),
      radial-gradient(55% 48% at 55% 96%, rgba(38, 84, 130, 0.30), transparent 68%),
      var(--ink);
    animation: aurora 30s ease-in-out infinite alternate;
  }
  @keyframes aurora {
    0%   { transform: translate(0, 0) scale(1); }
    100% { transform: translate(-2.5%, 2%) scale(1.06); }
  }
  /* fine grain to kill banding */
  .grain {
    position: fixed; inset: 0; z-index: -2; pointer-events: none; opacity: .05;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='120' height='120' filter='url(%23n)' opacity='0.55'/%3E%3C/svg%3E");
  }
  .orb {
    position: fixed; z-index: -1; top: 10vh; right: 7vw;
    width: 30vmin; height: 30vmin; border-radius: 50%;
    background: radial-gradient(circle at 36% 32%,
      rgba(178, 198, 255, 0.30), rgba(143, 176, 255, 0.09) 52%, transparent 74%);
    filter: blur(2px);
    animation: breathe 5.2s ease-in-out infinite;
    pointer-events: none;
  }
  @keyframes breathe {
    0%, 100% { transform: scale(1);    opacity: .65; }
    50%      { transform: scale(1.14); opacity: 1; }
  }
  @media (prefers-reduced-motion: reduce) {
    .ambient, .orb { animation: none; }
    * { transition: none !important; animation-duration: .01s !important; }
  }

  /* ---------- layout ---------- */
  .wrap { max-width: 1200px; margin: 0 auto; padding: 40px 28px 140px; }

  header.hero { padding: 4px 6px 34px; display: flex; align-items: baseline; gap: 18px; flex-wrap: wrap; }
  .wordmark {
    font-family: Georgia, "Times New Roman", "Songti SC", serif;
    font-size: 40px; font-weight: 600; letter-spacing: .5px; line-height: 1;
    background: linear-gradient(115deg, #f0f4ff 20%, var(--accent) 60%, var(--accent-2) 95%);
    -webkit-background-clip: text; background-clip: text; color: transparent;
  }
  .tagline { color: var(--text-dim); font-size: 14.5px; letter-spacing: .3px; }
  .tagline::before {
    content: ''; display: inline-block; width: 26px; height: 1px;
    background: var(--text-faint); vertical-align: middle; margin-right: 12px;
  }
  .health {
    margin-left: auto; display: flex; align-items: center; gap: 8px;
    font-size: 12px; color: var(--text-dim);
    padding: 6px 14px; border-radius: 999px;
    border: 1px solid var(--panel-border); background: rgba(255,255,255,0.02);
  }
  .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--text-faint); }
  .dot.ok  { background: var(--good); box-shadow: 0 0 10px rgba(125, 216, 171, 0.8); }
  .dot.down{ background: var(--bad);  box-shadow: 0 0 10px rgba(239, 154, 154, 0.8); }

  main { display: grid; grid-template-columns: minmax(0, 58fr) minmax(0, 42fr); gap: 22px; align-items: start; }
  @media (max-width: 920px) { main { grid-template-columns: 1fr; } }

  .card {
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-radius: var(--r-lg);
    backdrop-filter: blur(22px) saturate(1.25);
    box-shadow: 0 24px 60px -28px rgba(0, 0, 0, 0.65), inset 0 1px 0 rgba(255,255,255,0.04);
  }

  /* ---------- chat ---------- */
  .chat { display: flex; flex-direction: column; height: min(72vh, 780px); overflow: hidden; }
  .chat-head {
    padding: 18px 24px 15px;
    font-size: 13px; color: var(--text-dim); letter-spacing: .2px;
    border-bottom: 1px solid var(--panel-border);
    background: linear-gradient(rgba(255,255,255,0.025), transparent);
  }
  .stream { flex: 1; overflow-y: auto; padding: 22px 24px 10px; display: flex; flex-direction: column; gap: 14px; scroll-behavior: smooth; }
  .stream::-webkit-scrollbar { width: 5px; }
  .stream::-webkit-scrollbar-thumb { background: rgba(148,170,220,0.16); border-radius: 3px; }
  .msg {
    max-width: 82%; padding: 11px 16px; border-radius: 16px;
    font-size: 14.5px; line-height: 1.7; animation: rise .35s cubic-bezier(.22,.9,.34,1) both;
  }
  @keyframes rise { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
  .msg.user {
    align-self: flex-end;
    background: linear-gradient(135deg, rgba(143,176,255,0.16), rgba(167,139,250,0.13));
    border: 1px solid rgba(143,176,255,0.22);
    border-bottom-right-radius: 6px;
  }
  .msg.assistant {
    align-self: flex-start;
    background: rgba(255,255,255,0.035);
    border: 1px solid rgba(255,255,255,0.055);
    border-bottom-left-radius: 6px;
  }
  .msg.system { align-self: center; color: var(--text-faint); font-size: 12px; background: none; border: none; padding: 2px; }

  .chips { display: flex; gap: 9px; flex-wrap: wrap; padding: 12px 24px 14px; }
  .chip {
    font-size: 12.5px; color: var(--text-dim); font-family: inherit;
    border: 1px solid var(--panel-border); border-radius: 999px;
    padding: 7px 15px; cursor: pointer; background: rgba(255,255,255,0.025);
    transition: all .2s ease;
  }
  .chip:hover {
    color: var(--text); border-color: rgba(143,176,255,0.45);
    background: var(--accent-soft);
    box-shadow: 0 0 18px -6px rgba(143,176,255,0.5);
    transform: translateY(-1px);
  }

  .input-row {
    display: flex; gap: 10px; padding: 16px 24px 20px; align-items: flex-end;
    border-top: 1px solid var(--panel-border);
    background: linear-gradient(transparent, rgba(255,255,255,0.02));
  }
  textarea#prompt {
    flex: 1; resize: none; min-height: 48px; max-height: 120px;
    background: rgba(255,255,255,0.045); color: var(--text);
    border: 1px solid var(--panel-border); border-radius: var(--r-md);
    padding: 13px 16px; font-size: 14px; font-family: inherit; line-height: 1.55;
    outline: none; transition: border-color .2s ease, box-shadow .2s ease;
  }
  textarea#prompt::placeholder { color: var(--text-faint); }
  textarea#prompt:focus { border-color: rgba(143,176,255,0.5); box-shadow: 0 0 0 3px rgba(143,176,255,0.10); }
  .btn {
    border: none; border-radius: var(--r-md); cursor: pointer;
    font-size: 14px; font-family: inherit; padding: 13px 20px; font-weight: 600;
    color: #0a0f1e;
    background: linear-gradient(135deg, #a8c2ff, var(--accent) 55%, #97a8f5);
    box-shadow: 0 6px 22px -8px rgba(143,176,255,0.65);
    transition: transform .14s ease, box-shadow .2s ease, opacity .2s ease;
    white-space: nowrap;
  }
  .btn:hover { transform: translateY(-1px); box-shadow: 0 10px 26px -8px rgba(143,176,255,0.8); }
  .btn:disabled { opacity: .4; cursor: not-allowed; transform: none; box-shadow: none; }
  .btn.ghost {
    color: var(--text); background: rgba(255,255,255,0.05);
    border: 1px solid var(--panel-border); font-weight: 500; box-shadow: none;
  }
  .btn.ghost:hover { border-color: var(--panel-border-lit); }
  .btn.ghost.recording {
    background: linear-gradient(135deg, #f2a3a3, var(--bad));
    color: #23100f; border-color: transparent;
    animation: pulse 1.2s ease-in-out infinite;
  }
  @keyframes pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(239,154,154,0.45); } 50% { box-shadow: 0 0 0 10px rgba(239,154,154,0); } }

  /* ---------- decision timeline ---------- */
  .tl-card { padding: 22px 24px 26px; position: sticky; top: 24px; }
  .tl-head { display: flex; align-items: baseline; gap: 10px; }
  .tl-head h2 { font-size: 15.5px; font-weight: 600; letter-spacing: .3px; }
  .tl-head .sub { font-size: 11.5px; color: var(--text-faint); }
  .tl-empty { color: var(--text-faint); font-size: 13px; padding: 34px 8px; text-align: center; line-height: 1.8; }

  .tl { list-style: none; margin-top: 18px; }
  .tl li { position: relative; padding: 0 0 22px 34px; opacity: .28; transition: opacity .5s ease; }
  .tl li:last-child { padding-bottom: 2px; }
  .tl li::before {
    content: ''; position: absolute; left: 9px; top: 24px; bottom: 2px;
    width: 1px;
    background: linear-gradient(rgba(143,176,255,0.35), rgba(148,170,220,0.08));
  }
  .tl li:last-child::before { display: none; }
  .tl .node {
    position: absolute; left: 0; top: 3px;
    width: 19px; height: 19px; border-radius: 50%;
    border: 1.5px solid var(--text-faint); background: var(--ink-2);
    transition: all .35s ease;
  }
  .tl .node::after {
    content: ''; position: absolute; inset: 4.5px; border-radius: 50%;
    background: transparent; transition: background .35s ease;
  }
  .tl li.active { opacity: 1; }
  .tl li.active .node { border-color: var(--accent); }
  .tl li.running .node::after { background: var(--accent); animation: nodeBreathe 1.3s ease-in-out infinite; }
  @keyframes nodeBreathe { 0%,100% { opacity: .35; transform: scale(.7); } 50% { opacity: 1; transform: scale(1); } }
  .tl li.done .node { border-color: var(--accent); box-shadow: 0 0 14px -2px rgba(143,176,255,0.6); }
  .tl li.done .node::after { background: var(--accent); }
  .tl li.failed .node { border-color: var(--bad); box-shadow: none; }
  .tl li.failed .node::after { background: var(--bad); }

  .tl h3 { font-size: 13.5px; font-weight: 600; margin-bottom: 5px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .tl .meta { font-size: 11px; color: var(--text-faint); letter-spacing: .2px; }
  .tl .body { font-size: 12.5px; color: var(--text-dim); line-height: 1.75; margin-top: 5px; }
  .tl .body .line { animation: rise .4s ease both; }

  .badge {
    display: inline-block; font-size: 11px; font-weight: 600; letter-spacing: .3px;
    padding: 2.5px 10px; border-radius: 999px;
    background: var(--accent-soft); color: var(--accent);
    border: 1px solid rgba(143,176,255,0.28);
  }
  .badge.cache { background: rgba(125,216,171,0.10); color: var(--good); border-color: rgba(125,216,171,0.28); }
  .badge.warn  { background: rgba(242,201,138,0.10); color: var(--warn); border-color: rgba(242,201,138,0.28); }

  .tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 7px; }
  .tag {
    font-size: 11px; padding: 2.5px 10px; border-radius: 999px;
    background: rgba(255,255,255,0.045); color: var(--text-dim);
    border: 1px solid var(--panel-border);
  }

  .conf { display: inline-flex; align-items: center; gap: 7px; }
  .conf .bar { width: 58px; height: 3px; border-radius: 2px; background: rgba(255,255,255,0.09); overflow: hidden; }
  .conf .fill { height: 100%; border-radius: 2px; background: linear-gradient(90deg, var(--accent), var(--accent-2)); transition: width .7s cubic-bezier(.22,.9,.34,1); }

  .shimmer {
    display: inline-block;
    background: linear-gradient(90deg, rgba(255,255,255,0.05) 25%, rgba(255,255,255,0.13) 50%, rgba(255,255,255,0.05) 75%);
    background-size: 200% 100%; animation: shimmer 1.7s linear infinite;
    border-radius: 6px; color: transparent; user-select: none;
  }
  @keyframes shimmer { from { background-position: 200% 0; } to { background-position: -200% 0; } }

  .progress-ring { display: flex; align-items: center; gap: 11px; margin-top: 8px; }
  .ring {
    width: 20px; height: 20px; border-radius: 50%;
    border: 2px solid rgba(143,176,255,0.16); border-top-color: var(--accent);
    animation: spin 1.3s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .progress-copy { font-size: 12.5px; color: var(--text-dim); }

  .suggest { margin-top: 12px; display: flex; flex-direction: column; gap: 8px; }
  .suggest .item {
    display: flex; align-items: center; justify-content: space-between; gap: 10px;
    font-size: 13px; padding: 10px 15px; border-radius: var(--r-md);
    background: rgba(255,255,255,0.03); border: 1px solid var(--panel-border);
    cursor: pointer; transition: all .2s ease;
  }
  .suggest .item:hover {
    border-color: rgba(143,176,255,0.4); background: var(--accent-soft);
    transform: translateX(3px);
  }
  .suggest .item .play-ico { color: var(--accent); font-size: 13px; }

  /* ---------- now playing ---------- */
  .nowbar {
    position: fixed; left: 50%; bottom: 22px; transform: translate(-50%, 150%);
    width: min(680px, calc(100vw - 36px));
    display: flex; align-items: center; gap: 15px;
    padding: 13px 20px;
    background: rgba(13, 19, 34, 0.82);
    border: 1px solid var(--panel-border-lit); border-radius: 20px;
    backdrop-filter: blur(24px) saturate(1.3);
    box-shadow: 0 18px 50px -12px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.05);
    transition: transform .5s cubic-bezier(.22,.9,.3,1);
    z-index: 10;
  }
  .nowbar.show { transform: translate(-50%, 0); }
  .nowbar .play {
    width: 44px; height: 44px; border-radius: 50%; border: none; cursor: pointer;
    background: linear-gradient(135deg, #a8c2ff, var(--accent));
    color: #0a0f1e; font-size: 15px;
    display: flex; align-items: center; justify-content: center; flex-shrink: 0;
    box-shadow: 0 6px 18px -6px rgba(143,176,255,0.7);
    transition: transform .15s ease;
  }
  .nowbar .play:hover { transform: scale(1.06); }
  .nowbar .info { flex: 1; min-width: 0; }
  .nowbar .title { font-size: 14px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .nowbar .sub { font-size: 11px; color: var(--text-dim); margin-top: 2px; letter-spacing: .3px; }
  .wave { display: flex; align-items: center; gap: 3px; height: 26px; flex-shrink: 0; }
  .wave span { width: 2.5px; border-radius: 2px; background: linear-gradient(var(--accent), var(--accent-2)); height: 5px; opacity: .85; transition: height .3s ease; }
  .nowbar.playing .wave span { animation: wave 1.5s ease-in-out infinite; }
  .wave span:nth-child(2) { animation-delay: .16s; } .wave span:nth-child(3) { animation-delay: .32s; }
  .wave span:nth-child(4) { animation-delay: .48s; } .wave span:nth-child(5) { animation-delay: .64s; }
  @keyframes wave { 0%,100% { height: 5px; } 50% { height: 22px; } }

  footer { margin-top: 42px; text-align: center; font-size: 11px; color: var(--text-faint); letter-spacing: .6px; }
</style>
</head>
<body>
<div class="ambient"></div>
<div class="grain"></div>
<div class="orb"></div>

<div class="wrap">
  <header class="hero">
    <div class="wordmark">Unwind</div>
    <div class="tagline">面向高压研发团队的 AI 原生降压工具</div>
    <div class="health"><span class="dot" id="healthDot"></span><span id="healthText">检测服务状态…</span></div>
  </header>

  <main>
    <section class="card chat">
      <div class="chat-head">说说你现在的状态 — Unwind 会自主决定为你播放、生成，还是改编一段声音</div>
      <div class="stream" id="stream">
        <div class="msg assistant">你好，我是 Unwind。刚下会？发版了？还是脑子转个不停——说说看，我来帮你按下暂停键。</div>
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
      <div class="tl-empty" id="tlEmpty">发出第一条请求后<br>这里会展示智能体的实时决策过程</div>
      <ol class="tl" id="tl" style="display:none">
        <li id="n1"><span class="node"></span><h3>理解意图</h3><div class="meta" id="n1meta"></div><div class="body" id="n1body"></div></li>
        <li id="n2"><span class="node"></span><h3>选择技能 <span id="n2badge"></span></h3><div class="meta" id="n2meta"></div><div class="body" id="n2body"></div></li>
        <li id="n3"><span class="node"></span><h3 id="n3title">生成指令要点</h3><div class="body" id="n3body"></div></li>
        <li id="n4"><span class="node"></span><h3>执行结果</h3><div class="meta" id="n4meta"></div><div class="body" id="n4body"></div></li>
      </ol>
    </aside>
  </main>

  <footer>UNWIND · POWERED BY HERMES AGENT · 内部演示版</footer>
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
