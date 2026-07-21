SHOWCASE_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Unwind · 把压力，呼出去</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ccircle cx='16' cy='16' r='13' fill='%23d65a47'/%3E%3Ccircle cx='21' cy='13' r='11' fill='%23f4f1ea'/%3E%3C/svg%3E">
<style>
  :root {
    --paper: #eef0ec;
    --panel: rgba(255, 255, 253, 0.78);
    --panel-solid: #fffefb;
    --panel-border: rgba(88, 78, 72, 0.14);
    --panel-border-lit: rgba(88, 78, 72, 0.26);
    --text: #33383a;
    --text-dim: #6b7476;
    --text-faint: #98a0a0;
    --accent: #d65a47;      /* 朱砂 */
    --accent-deep: #b9483a;
    --accent-soft: rgba(214, 90, 71, 0.10);
    --moss: #4e7d60;        /* 苔绿 */
    --mist: #8fb0c9;        /* 雾蓝 */
    --good: #3f7c59;
    --warn: #b67a24;
    --bad: #bb433e;
    --serif: "Songti SC", "Noto Serif SC", Georgia, "Times New Roman", serif;
    --r-lg: 18px;
    --r-md: 12px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; }
  body {
    font-family: "PingFang SC", "HarmonyOS Sans SC", "Microsoft YaHei", -apple-system, "Segoe UI", sans-serif;
    color: var(--text);
    background: var(--paper);
    overflow-x: hidden;
    -webkit-font-smoothing: antialiased;
  }
  button { font-family: inherit; }

  @media (prefers-reduced-motion: reduce) {
    * { transition: none !important; animation-duration: .01s !important; animation-iteration-count: 1 !important; }
  }

  /* ================= living ink sky ================= */
  .sky { position: fixed; inset: 0; z-index: -2; overflow: hidden; background: var(--paper); }
  .sky .blob {
    position: absolute; border-radius: 50%; filter: blur(90px);
    opacity: .55; will-change: transform;
  }
  .sky .b1 { width: 58vw; height: 58vw; left: -16vw; top: -22vw;
    background: radial-gradient(circle at 40% 40%, #b9d0c6, transparent 65%);
    animation: drift1 67s ease-in-out infinite alternate; }
  .sky .b2 { width: 52vw; height: 52vw; right: -18vw; top: -8vw;
    background: radial-gradient(circle at 55% 45%, #c3d2df, transparent 65%);
    animation: drift2 83s ease-in-out infinite alternate; }
  .sky .b3 { width: 60vw; height: 60vw; left: 8vw; bottom: -30vw;
    background: radial-gradient(circle at 50% 40%, #ecd9c8, transparent 62%);
    animation: drift3 74s ease-in-out infinite alternate; }
  .sky .b4 { width: 34vw; height: 34vw; right: 4vw; bottom: -10vw;
    background: radial-gradient(circle at 50% 50%, rgba(214,90,71,.32), transparent 60%);
    animation: drift2 96s ease-in-out infinite alternate-reverse; }
  @keyframes drift1 { to { transform: translate(9vw, 7vh) scale(1.12); } }
  @keyframes drift2 { to { transform: translate(-8vw, 9vh) scale(1.08) rotate(12deg); } }
  @keyframes drift3 { to { transform: translate(6vw, -8vh) scale(1.15); } }

  /* whole-page breath halo */
  .sky .halo {
    position: absolute; left: 50%; top: 44%; width: min(88vw, 900px); aspect-ratio: 1;
    transform: translate(-50%, -50%);
    background: radial-gradient(circle, rgba(255,255,252,.85) 0%, rgba(255,255,252,.28) 42%, transparent 68%);
    animation: haloBreath 9s ease-in-out infinite;
  }
  @keyframes haloBreath {
    0%, 100% { transform: translate(-50%, -50%) scale(1); opacity: .85; }
    45%      { transform: translate(-50%, -50%) scale(1.07); opacity: 1; }
  }
  /* paper grain */
  .sky::after {
    content: ''; position: absolute; inset: 0; opacity: .5; mix-blend-mode: multiply;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3CfeComponentTransfer%3E%3CfeFuncA type='linear' slope='0.05'/%3E%3C/feComponentTransfer%3E%3C/filter%3E%3Crect width='160' height='160' filter='url(%23n)'/%3E%3C/svg%3E");
  }

  /* ================= sound ripple field ================= */
  #rippleCanvas {
    position: fixed; inset: 0; z-index: -1; pointer-events: none;
    opacity: 0; transition: opacity 1.2s ease;
  }
  #rippleCanvas.on { opacity: 1; }

  /* ================= worry shredder ================= */
  .shred-overlay {
    position: fixed; inset: 0; z-index: 50; display: grid; place-items: center;
    background: rgba(46, 40, 38, .32); backdrop-filter: blur(6px);
    animation: fadeIn .3s ease both;
  }
  .shred-overlay.leaving { opacity: 0; transition: opacity .5s ease; }
  .shred-note {
    position: relative; width: min(340px, 80vw); padding: 30px 28px;
    background:
      radial-gradient(120% 100% at 15% 0%, rgba(185,208,198,.35), transparent 55%),
      linear-gradient(168deg, #fffefb, #f3f0e8);
    border: 1px solid rgba(88,78,72,.25); border-radius: 6px;
    box-shadow: 0 30px 60px -24px rgba(30, 20, 18, .7);
    font-family: var(--serif); font-size: 17px; line-height: 1.9; color: #3a3134;
    transform-origin: 50% 55%;
  }
  .shred-note::before {
    content: '烦 恼 寄 存'; position: absolute; top: -28px; left: 2px;
    font-size: 11px; letter-spacing: .5em; color: rgba(255,255,252,.85);
  }
  .shred-note.crumple {
    animation: crumple .75s cubic-bezier(.55,-.2,.6,1.2) forwards;
  }
  @keyframes crumple {
    0%   { transform: none; border-radius: 6px; filter: none; }
    45%  { transform: scale(.55) rotate(-7deg) skewX(6deg); border-radius: 30% 55% 40% 60%; }
    100% { transform: scale(.12) rotate(14deg); border-radius: 50%; filter: brightness(.92); opacity: .9; }
  }
  .shred-bit {
    position: fixed; z-index: 51; pointer-events: none;
    width: 9px; height: 13px; border-radius: 2px;
    background: linear-gradient(170deg, #fffefb, #efe9dd);
    border: 1px solid rgba(88,78,72,.22);
    will-change: transform, opacity;
  }
  .shred-done {
    position: fixed; z-index: 52; left: 50%; top: 50%;
    transform: translate(-50%, -50%) scale(.7); opacity: 0;
    font-family: var(--serif); font-size: 20px; letter-spacing: .4em; text-indent: .4em;
    color: #fff7f2; text-align: center;
    padding: 14px 26px; border-radius: 999px;
    background: rgba(63,124,89,.92);
    box-shadow: 0 18px 40px -16px rgba(30,60,44,.8);
    transition: all .45s cubic-bezier(.2,.9,.3,1.4);
  }
  .shred-done.show { transform: translate(-50%, -50%) scale(1); opacity: 1; }

  /* breathe mic-follow */
  .breathe-mic { margin-top: 20px; }
  .breathe-mic .pill-btn.on {
    color: #fff; background: linear-gradient(135deg, #6f9d84, var(--moss));
    border-color: transparent;
  }
  .mic-hint { margin-top: 9px; font-size: 11px; color: var(--text-faint); letter-spacing: .1em; min-height: 16px; }

  /* click ripple (解压水纹) */
  .ripple {
    position: fixed; z-index: 0; pointer-events: none;
    width: 14px; height: 14px; border-radius: 50%;
    border: 1.5px solid rgba(103, 132, 145, .55);
    transform: translate(-50%, -50%) scale(.4); opacity: .9;
    animation: rippleGo 1.1s cubic-bezier(.16,.6,.4,1) forwards;
  }
  .ripple.r2 { animation-delay: .12s; animation-duration: 1.3s; }
  @keyframes rippleGo {
    to { transform: translate(-50%, -50%) scale(11); opacity: 0; }
  }

  /* ================= layout ================= */
  .wrap { max-width: 1240px; margin: 0 auto; padding: 30px 28px 150px; position: relative; }

  header.hero { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; padding: 2px 4px 22px; }
  .brand-lockup { display: flex; align-items: center; gap: 13px; }
  .mascot {
    width: 50px; height: 50px; flex: 0 0 auto; overflow: hidden;
    border-radius: 14px; background: #fbf8f2;
    border: 1px solid rgba(88,78,72,.16);
    box-shadow: 0 10px 26px -16px rgba(76, 47, 47, .6);
  }
  .mascot img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .wordmark {
    font-family: var(--serif);
    font-size: 38px; font-weight: 600; letter-spacing: .5px; line-height: 1;
    background: linear-gradient(110deg, #3a3134 8%, var(--accent) 58%, var(--moss) 100%);
    -webkit-background-clip: text; background-clip: text; color: transparent;
    position: relative;
  }
  .tagline { color: var(--text-dim); font-size: 14px; letter-spacing: .4px; }
  .tagline::before {
    content: ''; display: inline-block; width: 26px; height: 1px;
    background: var(--text-faint); vertical-align: middle; margin-right: 12px;
  }
  .header-actions { margin-left: auto; display: flex; align-items: center; gap: 10px; }
  .health {
    display: flex; align-items: center; gap: 8px;
    font-size: 12px; color: var(--text-dim);
    padding: 7px 14px; border-radius: 999px;
    border: 1px solid var(--panel-border); background: var(--panel);
    backdrop-filter: blur(10px);
  }
  .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--text-faint); }
  .dot.ok  { background: var(--good); box-shadow: 0 0 0 3px rgba(63,124,89,.15); }
  .dot.down{ background: var(--bad);  box-shadow: 0 0 0 3px rgba(187,67,62,.13); }

  .pill-btn {
    height: 36px; display: inline-flex; align-items: center; gap: 8px;
    border: 1px solid var(--panel-border); border-radius: 999px; padding: 0 15px;
    color: var(--text); background: var(--panel); font: 600 12.5px/1 inherit;
    cursor: pointer; backdrop-filter: blur(10px);
    transition: transform .16s ease, border-color .16s ease, background .16s ease;
  }
  .pill-btn:hover { transform: translateY(-1px); border-color: var(--panel-border-lit); background: #fff; }
  .pill-btn .symbol { font-size: 15px; line-height: 1; }
  .pill-btn.primary {
    color: #fff; background: linear-gradient(135deg, #e2705c, var(--accent) 60%, var(--accent-deep));
    border-color: transparent;
    box-shadow: 0 10px 24px -14px rgba(157,55,43,.9);
  }
  .pill-btn.primary:hover { box-shadow: 0 12px 26px -13px rgba(157,55,43,.95); }
  .pill-btn:disabled { opacity: .55; cursor: wait; transform: none; }
  .breath-dot {
    width: 9px; height: 9px; border-radius: 50%;
    background: radial-gradient(circle at 35% 35%, #fff, #ffd9cf 45%, var(--accent));
    animation: dotBreath 4.5s ease-in-out infinite;
  }
  @keyframes dotBreath { 0%,100% { transform: scale(.75); opacity: .75; } 50% { transform: scale(1.25); opacity: 1; } }

  /* headline strip */
  .headline {
    font-family: var(--serif); font-size: clamp(24px, 3.4vw, 40px); font-weight: 600;
    letter-spacing: .12em; color: #3c3436; padding: 6px 4px 26px; line-height: 1.3;
  }
  .headline .breathe-word {
    background: linear-gradient(120deg, var(--accent) 20%, var(--moss) 90%);
    -webkit-background-clip: text; background-clip: text; color: transparent;
  }
  .headline small {
    display: block; font-family: inherit; font-size: 13px; letter-spacing: .35em;
    color: var(--text-faint); margin-top: 10px; font-weight: 400;
  }

  main { display: grid; grid-template-columns: minmax(0, 58fr) minmax(0, 42fr); gap: 22px; align-items: start; }
  @media (max-width: 920px) { main { grid-template-columns: 1fr; } }

  .card {
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-radius: var(--r-lg);
    backdrop-filter: blur(24px) saturate(1.15);
    box-shadow:
      0 30px 70px -42px rgba(63, 43, 41, .5),
      inset 0 1px 0 rgba(255,255,255,.7);
  }

  /* ================= chat ================= */
  .chat { display: flex; flex-direction: column; height: min(72vh, 800px); overflow: hidden; }
  .chat-head {
    padding: 16px 24px 14px;
    font-size: 13px; color: var(--text-dim); letter-spacing: .2px;
    border-bottom: 1px solid rgba(88,78,72,.10);
    background: linear-gradient(rgba(255,255,255,.5), transparent);
  }
  .stream { flex: 1; overflow-y: auto; padding: 22px 24px 10px; display: flex; flex-direction: column; gap: 14px; scroll-behavior: smooth; }
  .stream::-webkit-scrollbar { width: 5px; }
  .stream::-webkit-scrollbar-thumb { background: rgba(107,116,118,.28); border-radius: 3px; }
  .msg {
    position: relative;
    flex: 0 0 auto;
    max-width: 82%; padding: 11px 16px; border-radius: 16px;
    font-size: 14.5px; line-height: 1.75; animation: rise .4s cubic-bezier(.22,.9,.34,1) both;
  }
  @keyframes rise { from { opacity: 0; transform: translateY(9px); } to { opacity: 1; transform: none; } }
  .msg.user {
    align-self: flex-end;
    background: linear-gradient(135deg, rgba(214,90,71,.14), rgba(214,90,71,.07));
    border: 1px solid rgba(214,90,71,.26);
    border-bottom-right-radius: 5px;
  }
  .msg.assistant {
    align-self: flex-start;
    background: rgba(255,255,253,.9);
    border: 1px solid rgba(88,78,72,.13);
    border-bottom-left-radius: 5px;
    box-shadow: 0 6px 18px -14px rgba(63,43,41,.45);
  }
  .msg.system { align-self: center; color: var(--text-faint); font-size: 12px; background: none; border: none; padding: 2px; }

  /* cardify affordance on assistant bubbles */
  .cc-make {
    position: absolute; right: -10px; top: -10px;
    width: 26px; height: 26px; border-radius: 50%;
    border: 1px solid rgba(214,90,71,.4); background: #fff; color: var(--accent);
    font: 600 12px/24px var(--serif); text-align: center; cursor: pointer;
    opacity: 0; transform: scale(.8); transition: all .18s ease;
    box-shadow: 0 4px 12px -6px rgba(157,55,43,.6);
  }
  .msg.assistant:hover .cc-make { opacity: 1; transform: none; }
  .cc-make:hover { background: var(--accent); color: #fff; }

  /* ================= 安心签 comfort card ================= */
  .comfort-card {
    flex: 0 0 auto;
    align-self: center; width: min(340px, 92%);
    margin: 6px 0 2px; padding: 26px 26px 20px;
    border-radius: 14px; position: relative; overflow: hidden;
    background:
      radial-gradient(120% 90% at 12% 0%, rgba(185,208,198,.5), transparent 55%),
      radial-gradient(130% 100% at 100% 100%, rgba(236,217,200,.55), transparent 60%),
      linear-gradient(165deg, #fffefb, #f4f2ec);
    border: 1px solid rgba(88,78,72,.18);
    box-shadow: 0 26px 50px -30px rgba(63,43,41,.55), inset 0 1px 0 rgba(255,255,255,.8);
    animation: ccIn .7s cubic-bezier(.2,.85,.3,1) both;
  }
  @keyframes ccIn { from { opacity: 0; transform: translateY(16px) scale(.96); } to { opacity: 1; transform: none; } }
  .comfort-card::before {
    content: ''; position: absolute; inset: 7px; border-radius: 9px;
    border: 1px solid rgba(88,78,72,.14); pointer-events: none;
  }
  .cc-kicker {
    display: flex; justify-content: space-between; align-items: baseline;
    font-size: 10.5px; letter-spacing: .32em; color: var(--text-faint);
  }
  .cc-text {
    font-family: var(--serif); font-size: 17.5px; line-height: 2;
    letter-spacing: .06em; color: #3a3134; margin: 16px 2px 18px;
    text-align: justify;
  }
  .cc-foot { display: flex; align-items: center; gap: 10px; }
  .cc-seal {
    width: 30px; height: 30px; border-radius: 6px; flex: 0 0 auto;
    background: linear-gradient(150deg, #de6a52, var(--accent-deep));
    color: #fff7f2; font: 600 15px/30px var(--serif); text-align: center;
    box-shadow: 0 4px 10px -4px rgba(157,55,43,.8);
  }
  .cc-brand { font-size: 10px; letter-spacing: .3em; color: var(--text-faint); }
  .cc-save {
    margin-left: auto; border: 1px solid rgba(214,90,71,.4); border-radius: 999px;
    background: none; color: var(--accent); font-size: 11.5px; padding: 5px 13px;
    cursor: pointer; transition: all .16s ease;
  }
  .cc-save:hover { background: var(--accent); color: #fff; }

  .chips { display: flex; gap: 9px; flex-wrap: wrap; padding: 12px 24px 14px; }
  .chip {
    font-size: 12.5px; color: var(--text-dim);
    border: 1px solid var(--panel-border); border-radius: 999px;
    padding: 7px 14px; cursor: pointer; background: rgba(255,255,253,.75);
    transition: all .2s ease;
  }
  .chip:hover {
    color: var(--accent-deep); border-color: rgba(214,90,71,.5); background: #fff2ec;
    transform: translateY(-1px);
  }

  .input-row {
    display: flex; gap: 10px; padding: 15px 24px 19px; align-items: flex-end;
    border-top: 1px solid rgba(88,78,72,.10);
    background: linear-gradient(transparent, rgba(255,255,255,.55));
  }
  textarea#prompt {
    flex: 1; resize: none; min-height: 48px; max-height: 120px;
    background: #fff; color: var(--text);
    border: 1px solid rgba(88,78,72,.2); border-radius: var(--r-md);
    padding: 13px 16px; font-size: 14px; font-family: inherit; line-height: 1.55;
    outline: none; transition: border-color .2s ease, box-shadow .2s ease;
  }
  textarea#prompt::placeholder { color: var(--text-faint); }
  textarea#prompt:focus { border-color: rgba(214,90,71,.55); box-shadow: 0 0 0 4px rgba(214,90,71,.09); }
  .btn {
    border: none; border-radius: var(--r-md); cursor: pointer;
    font-size: 14px; padding: 13px 20px; font-weight: 600;
    color: #fff;
    background: linear-gradient(135deg, #e2705c, var(--accent) 55%, var(--accent-deep));
    box-shadow: 0 10px 24px -12px rgba(157,55,43,.85);
    transition: transform .14s ease, box-shadow .2s ease, opacity .2s ease;
    white-space: nowrap;
  }
  .btn:hover { transform: translateY(-1px); box-shadow: 0 12px 28px -12px rgba(157,55,43,.9); }
  .btn:disabled { opacity: .4; cursor: not-allowed; transform: none; box-shadow: none; }
  .btn.ghost {
    color: #5d4f52; background: rgba(255,255,253,.8);
    border: 1px solid rgba(88,78,72,.2); font-weight: 500; box-shadow: none;
  }
  .btn.ghost:hover { border-color: rgba(88,78,72,.34); background: #fff; }
  .btn.ghost.recording {
    background: linear-gradient(135deg, #d6675f, var(--bad)); color: #fff; border-color: transparent;
    animation: pulse 1.2s ease-in-out infinite;
  }
  @keyframes pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(187,67,62,.4); } 50% { box-shadow: 0 0 0 11px rgba(187,67,62,0); } }

  /* ================= right column ================= */
  .side { position: sticky; top: 24px; display: flex; flex-direction: column; gap: 20px; }

  /* ================= decision timeline ================= */
  .tl-card { padding: 22px 24px 26px; }
  .tl-head { display: flex; align-items: baseline; gap: 10px; }
  .tl-head h2 { font-size: 15.5px; font-weight: 600; letter-spacing: .3px; }
  .tl-head .sub { font-size: 11.5px; color: var(--text-faint); }
  .tl-empty { color: var(--text-faint); font-size: 13px; padding: 40px 8px; text-align: center; line-height: 1.9; }
  .tl-empty .zen {
    width: 44px; height: 44px; margin: 0 auto 14px; border-radius: 50%;
    border: 1px solid rgba(88,78,72,.2);
    background: radial-gradient(circle at 38% 34%, rgba(214,90,71,.25), transparent 55%);
    animation: dotBreath 5s ease-in-out infinite;
  }

  .tl { list-style: none; margin-top: 18px; }
  .tl li { position: relative; padding: 0 0 22px 36px; opacity: .3; transition: opacity .5s ease; }
  .tl li:last-child { padding-bottom: 2px; }
  .tl li::before {
    content: ''; position: absolute; left: 10px; top: 26px; bottom: 2px;
    width: 1.5px; border-radius: 1px;
    background: linear-gradient(rgba(214,90,71,.4), rgba(88,78,72,.07));
  }
  .tl li:last-child::before { display: none; }
  .tl .node {
    position: absolute; left: 0; top: 3px;
    width: 21px; height: 21px; border-radius: 50%;
    border: 1.5px solid var(--text-faint); background: var(--panel-solid);
    transition: all .35s ease;
  }
  .tl .node::after {
    content: ''; position: absolute; inset: 5px; border-radius: 50%;
    background: transparent; transition: background .35s ease;
  }
  .tl li.active { opacity: 1; }
  .tl li.active .node { border-color: var(--accent); }
  .tl li.running .node::after { background: var(--accent); animation: nodeBreathe 1.3s ease-in-out infinite; }
  @keyframes nodeBreathe { 0%,100% { opacity: .35; transform: scale(.68); } 50% { opacity: 1; transform: scale(1); } }
  .tl li.done .node { border-color: var(--accent); box-shadow: 0 0 0 4px rgba(214,90,71,.12); }
  .tl li.done .node::after { background: radial-gradient(circle at 36% 32%, #ef8a73, var(--accent-deep)); }
  .tl li.failed .node { border-color: var(--bad); box-shadow: none; }
  .tl li.failed .node::after { background: var(--bad); }

  .tl h3 { font-size: 13.5px; font-weight: 600; margin-bottom: 5px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .tl .meta { font-size: 11px; color: var(--text-faint); letter-spacing: .2px; }
  .tl .body { font-size: 12.5px; color: var(--text-dim); line-height: 1.75; margin-top: 5px; }
  .tl .body .line { animation: rise .4s ease both; }

  .badge {
    display: inline-block; font-size: 11px; font-weight: 600; letter-spacing: .3px;
    padding: 2.5px 10px; border-radius: 999px;
    background: var(--accent-soft); color: var(--accent-deep);
    border: 1px solid rgba(214,90,71,.3);
  }
  .badge.cache { background: rgba(63,124,89,.1); color: var(--good); border-color: rgba(63,124,89,.3); }
  .badge.warn  { background: rgba(182,122,36,.1); color: var(--warn); border-color: rgba(182,122,36,.3); }

  .tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 7px; }
  .tag {
    font-size: 11px; padding: 2.5px 10px; border-radius: 999px;
    background: rgba(255,255,253,.8); color: var(--text-dim);
    border: 1px solid var(--panel-border);
  }

  .conf { display: inline-flex; align-items: center; gap: 7px; }
  .conf .bar { width: 58px; height: 3px; border-radius: 2px; background: rgba(88,78,72,.14); overflow: hidden; }
  .conf .fill { height: 100%; border-radius: 2px; background: linear-gradient(90deg, var(--accent), var(--moss)); transition: width .7s cubic-bezier(.22,.9,.34,1); }

  .shimmer {
    display: inline-block;
    background: linear-gradient(90deg, #ece5df 25%, #f6d9cf 50%, #ece5df 75%);
    background-size: 200% 100%; animation: shimmer 1.7s linear infinite;
    border-radius: 6px; color: transparent; user-select: none;
  }
  @keyframes shimmer { from { background-position: 200% 0; } to { background-position: -200% 0; } }

  .progress-ring { display: flex; align-items: center; gap: 11px; margin-top: 8px; }
  .ring {
    width: 20px; height: 20px; border-radius: 50%;
    border: 2px solid rgba(214,90,71,.18); border-top-color: var(--accent);
    animation: spin 1.3s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .progress-copy { font-size: 12.5px; color: var(--text-dim); }

  .suggest { margin-top: 12px; display: flex; flex-direction: column; gap: 8px; }
  .suggest .item {
    display: flex; align-items: center; justify-content: space-between; gap: 10px;
    font-size: 13px; padding: 10px 15px; border-radius: var(--r-md);
    background: rgba(255,255,253,.8); border: 1px solid var(--panel-border);
    cursor: pointer; transition: all .2s ease;
  }
  .suggest .item:hover {
    border-color: rgba(214,90,71,.45); background: #fff2ec;
    transform: translateX(3px);
  }
  .suggest .item .play-ico { color: var(--accent); font-size: 13px; }

  /* ================= skill matrix ================= */
  .skills-card { padding: 20px 24px 22px; }
  .skills-head { display: flex; align-items: baseline; gap: 10px; }
  .skills-head h2 { font-size: 15.5px; font-weight: 600; letter-spacing: .3px; }
  .skills-head .sub { font-size: 11.5px; color: var(--text-faint); }
  .skills-legend { margin-left: auto; display: flex; gap: 10px; font-size: 10.5px; color: var(--text-faint); }
  .skills-legend i { display: inline-block; width: 6px; height: 6px; border-radius: 50%; margin-right: 4px; vertical-align: 1px; }
  .skills-legend .lv i { background: var(--good); }
  .skills-legend .dm i { background: var(--accent); }
  .skills-legend .pl i { background: none; border: 1px solid var(--text-faint); }
  .skill-group { margin-top: 14px; }
  .skill-group .cap {
    font-size: 10.5px; letter-spacing: .28em; color: var(--text-faint); margin-bottom: 8px;
  }
  .skill-grid { display: flex; flex-wrap: wrap; gap: 7px; }
  .skill-chip {
    position: relative; display: inline-flex; align-items: center; gap: 6px;
    font-size: 12px; color: var(--text-dim); cursor: default;
    border: 1px solid var(--panel-border); border-radius: 999px;
    padding: 5.5px 12px; background: rgba(255,255,253,.75);
    transition: all .25s ease;
  }
  .skill-chip i { width: 6px; height: 6px; border-radius: 50%; flex: 0 0 auto; }
  .skill-chip[data-status="live"] i { background: var(--good); }
  .skill-chip[data-status="demo"] i { background: var(--accent); }
  .skill-chip[data-status="planned"] { opacity: .5; }
  .skill-chip[data-status="planned"] i { background: none; border: 1px solid var(--text-faint); }
  .skill-chip:hover { border-color: var(--panel-border-lit); color: var(--text); opacity: 1; }
  .skill-chip.clickable { cursor: pointer; }
  .skill-chip.clickable:hover { transform: translateY(-1px); background: #fff; }
  .skill-chip.clickable:active { transform: translateY(0); }
  .skill-chip.active {
    color: var(--accent-deep); border-color: rgba(214,90,71,.6); background: #fff2ec;
    box-shadow: 0 0 0 5px rgba(214,90,71,.12);
    animation: skillPulse 1.6s ease-in-out 2;
  }
  @keyframes skillPulse {
    0%,100% { box-shadow: 0 0 0 4px rgba(214,90,71,.1); }
    50%     { box-shadow: 0 0 0 9px rgba(214,90,71,.02), 0 0 24px -4px rgba(214,90,71,.55); }
  }
  .skill-chip .tip {
    position: absolute; left: 50%; bottom: calc(100% + 8px); transform: translateX(-50%);
    width: max-content; max-width: 220px; padding: 7px 11px; border-radius: 9px;
    font-size: 11.5px; line-height: 1.6; color: #fff; text-align: left;
    background: rgba(47,41,40,.94); pointer-events: none; opacity: 0;
    transition: opacity .18s ease; z-index: 5;
  }
  .skill-chip:hover .tip { opacity: 1; }

  /* ================= nudge banner ================= */
  .nudge[hidden] { display: none; }
  .nudge {
    display: flex; align-items: center; gap: 12px;
    margin: 14px 24px 0; padding: 12px 16px;
    border-radius: 14px; border: 1px solid rgba(214,90,71,.3);
    background:
      radial-gradient(120% 140% at 0% 0%, rgba(214,90,71,.1), transparent 55%),
      rgba(255,255,253,.9);
    animation: nudgeIn .5s cubic-bezier(.2,.85,.3,1) both;
  }
  @keyframes nudgeIn { from { opacity: 0; transform: translateY(-10px); } to { opacity: 1; transform: none; } }
  .nudge .ic { font-size: 20px; }
  .nudge .nbody { flex: 1; min-width: 0; }
  .nudge .ntitle { font-size: 13px; font-weight: 600; }
  .nudge .ntext { font-size: 12px; color: var(--text-dim); margin-top: 2px; line-height: 1.6; }
  .nudge .nact {
    flex: 0 0 auto; border: none; border-radius: 999px; cursor: pointer;
    font-size: 12px; font-weight: 600; color: #fff; padding: 8px 14px;
    background: linear-gradient(135deg, #e2705c, var(--accent-deep));
    box-shadow: 0 8px 18px -10px rgba(157,55,43,.9);
  }
  .nudge .ndismiss {
    flex: 0 0 auto; border: none; background: none; color: var(--text-faint);
    font-size: 16px; cursor: pointer; padding: 4px;
  }

  /* ================= demo director menu ================= */
  .director { position: relative; }
  .director-menu[hidden] { display: none; }
  .director-menu {
    position: absolute; right: 0; top: calc(100% + 8px); z-index: 20;
    width: 240px; padding: 8px; border-radius: 14px;
    background: rgba(255,255,253,.97); border: 1px solid var(--panel-border-lit);
    box-shadow: 0 24px 50px -22px rgba(63,43,41,.6);
  }
  .director-menu .dm-cap { font-size: 10.5px; letter-spacing: .25em; color: var(--text-faint); padding: 6px 10px 4px; }
  .director-menu button {
    display: block; width: 100%; text-align: left; border: none; cursor: pointer;
    background: none; border-radius: 9px; padding: 9px 10px;
    font-size: 12.5px; color: var(--text);
  }
  .director-menu button:hover { background: #fff2ec; color: var(--accent-deep); }
  .director-menu .dm-note { font-size: 10.5px; color: var(--text-faint); padding: 4px 10px 6px; line-height: 1.6; }

  /* ================= skill cards in stream ================= */
  .skill-card-msg {
    flex: 0 0 auto;
    align-self: flex-start; width: min(420px, 96%);
    border-radius: 16px; overflow: hidden;
    background: rgba(255,255,253,.94);
    border: 1px solid rgba(88,78,72,.16);
    box-shadow: 0 18px 40px -26px rgba(63,43,41,.6);
    animation: ccIn .6s cubic-bezier(.2,.85,.3,1) both;
  }
  .skill-card-msg .sc-head {
    display: flex; align-items: center; gap: 8px;
    padding: 11px 16px; font-size: 12px; font-weight: 600;
    color: var(--accent-deep); background: linear-gradient(rgba(214,90,71,.08), transparent);
    border-bottom: 1px solid rgba(88,78,72,.09);
  }
  .skill-card-msg .sc-head .src { margin-left: auto; font-weight: 400; font-size: 10.5px; color: var(--text-faint); letter-spacing: .1em; }
  .skill-card-msg .sc-body { padding: 14px 16px 15px; font-size: 13px; line-height: 1.75; color: var(--text); }
  .sc-note { margin-top: 10px; font-size: 11.5px; color: var(--text-faint); line-height: 1.6; }
  /* weekly draft */
  .wd-section { margin-bottom: 10px; }
  .wd-section:last-child { margin-bottom: 0; }
  .wd-section .wd-cap { font-size: 11px; font-weight: 600; color: var(--moss); letter-spacing: .12em; margin-bottom: 4px; }
  .wd-section li { margin: 3px 0 3px 18px; font-size: 12.5px; color: var(--text-dim); }
  /* okr bars */
  .okr-obj { font-weight: 600; font-size: 13px; margin-bottom: 10px; }
  .okr-kr { margin: 9px 0; }
  .okr-kr .kr-name { display: flex; justify-content: space-between; font-size: 12px; color: var(--text-dim); margin-bottom: 4px; }
  .okr-kr .kr-name b { color: var(--text); font-weight: 600; }
  .okr-bar { height: 6px; border-radius: 3px; background: rgba(88,78,72,.12); overflow: hidden; }
  .okr-bar .fill {
    height: 100%; border-radius: 3px; width: 0;
    background: linear-gradient(90deg, var(--moss), #7fb094);
    transition: width 1.1s cubic-bezier(.22,.9,.34,1);
  }
  .okr-kr.low .okr-bar .fill { background: linear-gradient(90deg, #d9a05a, var(--warn)); }
  .okr-insight {
    margin-top: 12px; padding: 9px 12px; border-radius: 10px; font-size: 12px;
    color: var(--accent-deep); background: var(--accent-soft); line-height: 1.7;
  }
  /* ritual receipt */
  .rr-title { font-family: var(--serif); font-size: 15px; font-weight: 600; margin-bottom: 8px; }
  .rr-line { font-size: 12.5px; color: var(--text-dim); line-height: 1.9; }
  .rr-stamp {
    display: inline-flex; align-items: center; gap: 6px; margin-top: 11px;
    font-size: 11px; color: var(--moss); font-weight: 600;
    padding: 4px 11px; border-radius: 999px;
    background: rgba(63,124,89,.08); border: 1px solid rgba(63,124,89,.25);
  }
  .pill-btn.muted { opacity: .55; }
  /* neisou */
  .ns-answer { font-size: 13px; line-height: 1.8; }
  .ns-meta { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 11px; }
  .ns-meta .m {
    font-size: 11px; padding: 4px 11px; border-radius: 999px;
    background: rgba(255,255,253,.85); border: 1px solid var(--panel-border); color: var(--text-dim);
  }
  .ns-meta .m b { color: var(--moss); font-weight: 600; }

  /* ================= now playing ================= */
  .nowbar {
    position: fixed; left: 50%; bottom: 22px; transform: translate(-50%, 160%);
    width: min(680px, calc(100vw - 36px));
    display: flex; align-items: center; gap: 15px;
    padding: 13px 20px;
    background: rgba(47, 41, 40, .9);
    border: 1px solid rgba(255,255,255,.14); border-radius: 999px;
    backdrop-filter: blur(24px) saturate(1.3);
    box-shadow: 0 24px 60px -18px rgba(30, 18, 16, .7), inset 0 1px 0 rgba(255,255,255,.1);
    transition: transform .55s cubic-bezier(.22,.9,.3,1);
    z-index: 10; color: #f6efe9;
  }
  .nowbar.show { transform: translate(-50%, 0); }
  .nowbar .play {
    width: 44px; height: 44px; border-radius: 50%; border: none; cursor: pointer;
    background:
      radial-gradient(circle at 50% 50%, rgba(255,255,255,.24) 0 3px, transparent 4px),
      repeating-radial-gradient(circle at 50% 50%, rgba(255,255,255,.07) 0 2px, transparent 2px 5px),
      linear-gradient(135deg, #ef8a73, var(--accent-deep));
    color: #fff; font-size: 14px;
    display: flex; align-items: center; justify-content: center; flex-shrink: 0;
    box-shadow: 0 8px 20px -8px rgba(157,55,43,.9);
    transition: transform .15s ease;
  }
  .nowbar.playing .play { animation: discSpin 9s linear infinite; }
  @keyframes discSpin { to { transform: rotate(360deg); } }
  .nowbar .play:hover { transform: scale(1.06); }
  .nowbar .info { flex: 1; min-width: 0; }
  .nowbar .title { font-size: 14px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .nowbar .sub { font-size: 11px; color: rgba(246,239,233,.62); margin-top: 2px; letter-spacing: .3px; }
  .wave { display: flex; align-items: center; gap: 3px; height: 26px; flex-shrink: 0; }
  .wave span { width: 2.5px; border-radius: 2px; background: linear-gradient(#ef8a73, #8fb59d); height: 5px; opacity: .9; transition: height .3s ease; }
  .nowbar.playing .wave span { animation: wave 1.5s ease-in-out infinite; }
  .wave span:nth-child(2) { animation-delay: .16s; } .wave span:nth-child(3) { animation-delay: .32s; }
  .wave span:nth-child(4) { animation-delay: .48s; } .wave span:nth-child(5) { animation-delay: .64s; }
  @keyframes wave { 0%,100% { height: 5px; } 50% { height: 22px; } }

  footer { margin-top: 46px; text-align: center; font-size: 11px; color: var(--text-faint); letter-spacing: .6em; }

  /* ================= breathing overlay ================= */
  .breathe-overlay[hidden] { display: none; }
  .breathe-overlay {
    position: fixed; inset: 0; z-index: 40; display: grid; place-items: center;
    background:
      radial-gradient(90% 70% at 50% 30%, rgba(185,208,198,.5), transparent 70%),
      radial-gradient(80% 70% at 80% 90%, rgba(236,217,200,.55), transparent 70%),
      rgba(238, 240, 236, .96);
    backdrop-filter: blur(14px);
    animation: fadeIn .5s ease both;
  }
  @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
  .breathe-close {
    position: absolute; top: 22px; right: 26px; width: 38px; height: 38px;
    border: 1px solid rgba(88,78,72,.2); border-radius: 50%;
    background: rgba(255,255,253,.8); color: var(--text-dim);
    font: 300 22px/34px inherit; cursor: pointer;
  }
  .breathe-stage { text-align: center; padding: 20px; }
  .orb-shell { position: relative; width: min(300px, 62vw); aspect-ratio: 1; margin: 0 auto 34px; }
  .orb-ring {
    position: absolute; inset: -13%; border-radius: 50%;
    border: 1px dashed rgba(88,78,72,.22);
    animation: spin 70s linear infinite;
  }
  .orb {
    position: absolute; inset: 0; border-radius: 50%;
    background:
      radial-gradient(circle at 36% 30%, rgba(255,255,255,.95), transparent 46%),
      radial-gradient(circle at 66% 74%, rgba(214,90,71,.34), transparent 58%),
      radial-gradient(circle at 50% 50%, #cfe0d6 0%, #a9c6b6 58%, #8fb0a0 100%);
    box-shadow:
      0 34px 70px -30px rgba(78, 105, 92, .75),
      inset 0 -14px 34px rgba(78, 105, 92, .35),
      inset 0 10px 26px rgba(255,255,255,.7);
    transform: scale(.72);
    transition: transform 4s cubic-bezier(.42,0,.35,1);
  }
  .orb-glow {
    position: absolute; inset: -22%; border-radius: 50%; z-index: -1;
    background: radial-gradient(circle, rgba(169,198,182,.5), transparent 62%);
    transform: scale(.72);
    transition: transform 4s cubic-bezier(.42,0,.35,1);
  }
  .breathe-phase {
    font-family: var(--serif); font-size: 30px; letter-spacing: .5em; text-indent: .5em;
    color: #3a3134; min-height: 44px;
  }
  .breathe-count { margin-top: 6px; font-size: 13px; color: var(--text-dim); letter-spacing: .2em; min-height: 20px; }
  .breathe-rounds { margin-top: 16px; display: flex; gap: 8px; justify-content: center; }
  .breathe-rounds i {
    width: 7px; height: 7px; border-radius: 50%; background: rgba(88,78,72,.2);
    transition: background .3s ease, transform .3s ease;
  }
  .breathe-rounds i.on { background: var(--accent); transform: scale(1.25); }
  .breathe-actions { margin-top: 26px; display: flex; gap: 12px; justify-content: center; }
  .breathe-actions[hidden] { display: none; }

  /* ================= realtime call modal ================= */
  .call-overlay[hidden] { display: none; }
  .call-overlay {
    position: fixed; inset: 0; z-index: 30; display: grid; place-items: center;
    padding: 24px; background: rgba(52, 43, 41, .5); backdrop-filter: blur(10px);
  }
  body.call-open { overflow: hidden; }
  .call-shell {
    width: min(440px, 100%); max-height: calc(100vh - 48px); overflow: auto;
    position: relative; padding: 30px 30px 26px; border-radius: 22px;
    color: var(--text); background: rgba(255,255,253,.94); border: 1px solid rgba(88,78,72,.16);
    box-shadow: 0 40px 90px -30px rgba(40, 24, 22, .8); text-align: center;
    backdrop-filter: blur(20px);
  }
  .call-close {
    position: absolute; top: 13px; right: 13px; width: 32px; height: 32px;
    border: 0; border-radius: 50%; color: #735f62; background: #f1ebe5;
    font: 400 24px/30px inherit; cursor: pointer;
  }
  .call-avatar {
    width: 104px; height: 104px; margin: 4px auto 14px; border-radius: 30px;
    overflow: hidden; border: 1px solid rgba(88,78,72,.18); background: #fff8f3;
    transition: box-shadow .25s ease, transform .25s ease;
  }
  .call-avatar.live { box-shadow: 0 0 0 8px rgba(214,90,71,.1), 0 0 0 16px rgba(78,125,96,.07); }
  .call-avatar.speaking { transform: scale(1.035); }
  .call-avatar img { width: 100%; height: 100%; display: block; object-fit: cover; }
  .call-kicker { color: #a75547; font-size: 10.5px; font-weight: 700; letter-spacing: 1.6px; }
  .call-shell h2 { margin-top: 7px; font-size: 20px; font-family: var(--serif); }
  .call-state { min-height: 22px; margin-top: 8px; color: var(--text-dim); font-size: 13px; }
  .call-timer { margin-top: 2px; color: #a08b87; font: 500 12px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; }
  .call-wave {
    height: 40px; margin: 16px auto 10px; display: flex; align-items: center;
    justify-content: center; gap: 5px;
  }
  .call-wave span { width: 4px; height: 6px; border-radius: 3px; background: var(--accent); opacity: .55; }
  .call-wave.active span { animation: callWave 1.15s ease-in-out infinite; }
  .call-wave span:nth-child(2), .call-wave span:nth-child(6) { animation-delay: .12s; }
  .call-wave span:nth-child(3), .call-wave span:nth-child(5) { animation-delay: .24s; }
  .call-wave span:nth-child(4) { animation-delay: .36s; background: var(--moss); }
  @keyframes callWave { 0%,100% { height: 6px; } 50% { height: 30px; } }
  .call-transcript {
    min-height: 108px; max-height: 180px; overflow-y: auto; margin: 0 -2px 20px;
    padding: 13px 4px; border-top: 1px solid #e8e0d8; border-bottom: 1px solid #e8e0d8;
    text-align: left; color: #6f5c5f; font-size: 13px; line-height: 1.65;
  }
  .call-transcript .empty { color: #a28f8b; text-align: center; padding-top: 28px; }
  .call-line { margin: 7px 0; }
  .call-line strong { color: #443437; margin-right: 7px; font-size: 12px; }
  .call-line.user strong { color: #a74437; }
  .call-line.assistant strong { color: #356b4c; }
  .call-line.system { color: #9a6a21; text-align: center; font-size: 12px; }
  .call-controls { display: flex; align-items: flex-start; justify-content: center; gap: 40px; }
  .call-control-wrap { display: grid; justify-items: center; gap: 7px; color: #756164; font-size: 11px; }
  .call-control {
    width: 54px; height: 54px; border-radius: 50%; border: 1px solid #d8cac4;
    background: #f7efeb; color: #4f3c40; font-size: 20px; cursor: pointer;
  }
  .call-control[aria-pressed="true"] { background: #3f3336; color: #fff; border-color: #3f3336; }
  .call-control.hangup { background: #c7483f; color: #fff; border-color: #c7483f; transform: rotate(135deg); }
  .call-error { color: #ad3f39; }

  @media (max-width: 720px) {
    .wrap { padding: 16px 14px 130px; }
    header.hero { gap: 12px; }
    .brand-lockup { width: 100%; }
    .tagline { order: 3; width: 100%; }
    .header-actions { margin-left: 0; width: 100%; justify-content: space-between; flex-wrap: wrap; }
    .headline { padding-bottom: 18px; }
    .chat { height: min(68vh, 700px); }
    .chat-head, .stream, .chips, .input-row { padding-left: 16px; padding-right: 16px; }
    .input-row { display: grid; grid-template-columns: 1fr auto; }
    textarea#prompt { grid-column: 1 / -1; }
    .btn { min-height: 44px; }
    .side { position: static; }
    .director-menu { right: auto; left: 0; }
    .call-overlay { padding: 12px; }
    .call-shell { max-height: calc(100vh - 24px); padding: 24px 20px 22px; }
  }
</style>
</head>
<body>
<div class="sky" aria-hidden="true">
  <div class="blob b1"></div><div class="blob b2"></div><div class="blob b3"></div><div class="blob b4"></div>
  <div class="halo"></div>
</div>
<canvas id="rippleCanvas" aria-hidden="true"></canvas>

<div class="wrap">
  <header class="hero">
    <div class="brand-lockup">
      <div class="mascot"><img src="showcase/assets/baidu-bear.png" alt="百度小熊"></div>
      <div class="wordmark">Unwind</div>
    </div>
    <div class="tagline">让各位同学，压力小一点</div>
    <div class="header-actions">
      <div class="health"><span class="dot" id="healthDot"></span><span id="healthText">检测服务状态…</span></div>
      <button class="pill-btn" id="speakBtn" type="button" title="回复是否开口说话"><span class="symbol" aria-hidden="true">🔊</span><span>开口说话</span></button>
      <button class="pill-btn" id="breatheBtn" type="button"><span class="breath-dot" aria-hidden="true"></span><span>呼吸 60 秒</span></button>
      <div class="director">
        <button class="pill-btn" id="directorBtn" type="button"><span class="symbol" aria-hidden="true">🎬</span><span>情境演示</span></button>
        <div class="director-menu" id="directorMenu" hidden>
          <div class="dm-cap">主动关怀情境</div>
          <button data-scenario="post_meeting" type="button">☕ 刚连开 3 小时会</button>
          <button data-scenario="weekly_due" type="button">🗂 周四晚 · 周报未交</button>
          <div class="dm-cap">厂内技能对话</div>
          <button data-say="周报还没写，帮我搞定" type="button">「周报还没写，帮我搞定」</button>
          <button data-say="这季度 OKR 感觉要完不成了" type="button">「OKR 感觉要完不成了」</button>
          <button data-say="差旅报销流程怎么走？" type="button">「差旅报销流程怎么走」</button>
          <div class="dm-note">演示情境由后端技能路由真实执行，含工具调用轨迹</div>
        </div>
      </div>
      <button class="pill-btn primary" id="callBtn" type="button"><span class="symbol" aria-hidden="true">☎</span><span>语音通话</span></button>
    </div>
  </header>

  <h1 class="headline">把压力，<span class="breathe-word">呼</span>出去。<small>UNWIND · A PAUSE BUTTON FOR YOUR DAY</small></h1>

  <main>
    <section class="card chat">
      <div class="chat-head">说说你现在的状态 — Unwind 会自己决定陪你聊、放一段声音，还是现场为你生成</div>
      <div class="nudge" id="nudge" hidden>
        <span class="ic" id="nudgeIcon">☕</span>
        <div class="nbody">
          <div class="ntitle" id="nudgeTitle"></div>
          <div class="ntext" id="nudgeText"></div>
        </div>
        <button class="nact" id="nudgeAction" type="button"></button>
        <button class="ndismiss" id="nudgeDismiss" type="button" aria-label="关闭">×</button>
      </div>
      <div class="stream" id="stream">
        <div class="msg assistant">你好，我是 Unwind。刚下会？发版了？还是脑子转个不停——说说看，我来帮你按下暂停键。</div>
      </div>
      <div class="chips" id="chips">
        <button class="chip">刚下线一个大版本，脑子还在转，帮我放松一下</button>
        <button class="chip">夸夸我，今天被需求虐惨了</button>
        <button class="chip">在现在的声音里加一点雨声</button>
        <button class="chip">带我做一段五分钟的呼吸冥想</button>
        <button class="chip">给我一张今天的安心签</button>
      </div>
      <div class="input-row">
        <textarea id="prompt" rows="1" placeholder="用一句话描述你现在的状态或想听的内容…"></textarea>
        <button class="btn ghost" id="talk" disabled>按住说话</button>
        <button class="btn" id="send">发送</button>
      </div>
    </section>

    <div class="side">
      <aside class="card tl-card">
        <div class="tl-head">
          <h2>智能体决策轨迹</h2>
          <span class="sub">agent 的每一步真实决策</span>
        </div>
        <div class="tl-empty" id="tlEmpty"><div class="zen"></div>发出第一条请求后<br>这里会展示智能体的实时决策过程</div>
        <ol class="tl" id="tl" style="display:none">
          <li id="n1"><span class="node"></span><h3>理解意图</h3><div class="meta" id="n1meta"></div><div class="body" id="n1body"></div></li>
          <li id="n2"><span class="node"></span><h3>选择技能 <span id="n2badge"></span></h3><div class="meta" id="n2meta"></div><div class="body" id="n2body"></div></li>
          <li id="n3"><span class="node"></span><h3 id="n3title">生成指令要点</h3><div class="body" id="n3body"></div></li>
          <li id="n4"><span class="node"></span><h3>执行结果</h3><div class="meta" id="n4meta"></div><div class="body" id="n4body"></div></li>
        </ol>
      </aside>

      <aside class="card skills-card">
        <div class="skills-head">
          <h2>技能矩阵</h2>
          <span class="sub" id="skillCount"></span>
          <div class="skills-legend">
            <span class="lv"><i></i>已上线</span>
            <span class="dm"><i></i>演示</span>
            <span class="pl"><i></i>规划中</span>
          </div>
        </div>
        <div id="skillGroups"></div>
      </aside>
    </div>
  </main>

  <footer>UNWIND · 把压力，呼出去</footer>
</div>

<div class="nowbar" id="nowbar">
  <button class="play" id="playBtn">▶</button>
  <div class="info">
    <div class="title" id="npTitle">—</div>
    <div class="sub" id="npSub">—</div>
  </div>
  <div class="wave"><span></span><span></span><span></span><span></span><span></span></div>
</div>

<div class="breathe-overlay" id="breatheOverlay" role="dialog" aria-modal="true" aria-label="呼吸练习" hidden>
  <button class="breathe-close" id="breatheClose" type="button" aria-label="退出呼吸练习">×</button>
  <div class="breathe-stage">
    <div class="orb-shell">
      <div class="orb-glow" id="orbGlow"></div>
      <div class="orb-ring"></div>
      <div class="orb" id="orb"></div>
    </div>
    <div class="breathe-phase" id="breathePhase">准备</div>
    <div class="breathe-count" id="breatheCount">找个舒服的姿势</div>
    <div class="breathe-rounds" id="breatheRounds"><i></i><i></i><i></i></div>
    <div class="breathe-mic">
      <button class="pill-btn" id="breatheMicBtn" type="button"><span class="symbol" aria-hidden="true">🎙</span><span id="breatheMicLabel">跟随我的呼吸</span></button>
      <div class="mic-hint" id="micHint"></div>
    </div>
    <div class="breathe-actions" id="breatheActions" hidden>
      <button class="pill-btn" id="breatheAgain" type="button">再来一轮</button>
      <button class="pill-btn primary" id="breatheDone" type="button">回到对话</button>
    </div>
  </div>
</div>

<div class="call-overlay" id="callOverlay" role="dialog" aria-modal="true" aria-labelledby="callTitle" hidden>
  <section class="call-shell">
    <button class="call-close" id="callClose" type="button" aria-label="关闭通话窗口">×</button>
    <div class="call-avatar" id="callAvatar"><img src="showcase/assets/baidu-bear.png" alt="百度小熊"></div>
    <div class="call-kicker">UNWIND VOICE</div>
    <h2 id="callTitle">和 Unwind 聊一会儿</h2>
    <div class="call-state" id="callState">准备接通</div>
    <div class="call-timer" id="callTimer">00:00</div>
    <div class="call-wave" id="callWave" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span><span></span><span></span></div>
    <div class="call-transcript" id="callTranscript" aria-live="polite"><p class="empty">通话字幕会显示在这里</p></div>
    <div class="call-controls">
      <div class="call-control-wrap">
        <button class="call-control" id="callMute" type="button" aria-label="静音" aria-pressed="false">🔇</button>
        <span id="callMuteLabel">静音</span>
      </div>
      <div class="call-control-wrap">
        <button class="call-control hangup" id="callHangup" type="button" aria-label="挂断">☎</button>
        <span>挂断</span>
      </div>
    </div>
  </section>
</div>

<audio id="player" preload="auto"></audio>
<audio id="ttsPlayer" preload="auto"></audio>

<script>
__SCRIPT__
</script>
</body>
</html>
"""
