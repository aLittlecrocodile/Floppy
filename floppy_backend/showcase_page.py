SHOWCASE_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Unwind · 让压力小一点</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ccircle cx='16' cy='16' r='13' fill='%23d65a47'/%3E%3Ccircle cx='21' cy='13' r='11' fill='%23fff8f3'/%3E%3C/svg%3E">
<style>
  :root {
    --ink: #f1edeb;
    --ink-2: #fffdfb;
    --panel: #fffdfb;
    --panel-border: #dfd4cf;
    --panel-border-lit: #cbbab2;
    --text: #372b2e;
    --text-dim: #766568;
    --text-faint: #9b8785;
    --accent: #d65a47;
    --accent-2: #4e7d60;
    --accent-soft: #f9e3dc;
    --good: #3f7c59;
    --warn: #b67a24;
    --bad: #bb433e;
    --r-lg: 8px;
    --r-md: 7px;
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

  @media (prefers-reduced-motion: reduce) {
    * { transition: none !important; animation-duration: .01s !important; }
  }

  /* ---------- layout ---------- */
  .wrap { max-width: 1200px; margin: 0 auto; padding: 40px 28px 140px; }

  header.hero { padding: 4px 6px 34px; display: flex; align-items: baseline; gap: 18px; flex-wrap: wrap; }
  .brand-lockup { display: flex; align-items: center; gap: 12px; }
  .mascot {
    width: 52px; height: 52px; flex: 0 0 auto; overflow: hidden;
    border-radius: 16px; background: #fbf8f2;
    border: 1px solid rgba(255,255,255,0.20);
    box-shadow: 0 8px 22px -12px rgba(0,0,0,0.8);
  }
  .mascot img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .wordmark {
    font-family: Georgia, "Times New Roman", "Songti SC", serif;
    font-size: 40px; font-weight: 600; letter-spacing: .5px; line-height: 1;
    background: linear-gradient(115deg, #fff7f2 20%, var(--accent) 60%, var(--accent-2) 95%);
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
  .stream::-webkit-scrollbar-thumb { background: rgba(118,101,104,0.22); border-radius: 3px; }
  .msg {
    max-width: 82%; padding: 11px 16px; border-radius: 16px;
    font-size: 14.5px; line-height: 1.7; animation: rise .35s cubic-bezier(.22,.9,.34,1) both;
  }
  @keyframes rise { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
  .msg.user {
    align-self: flex-end;
    background: linear-gradient(135deg, rgba(214,90,71,0.16), rgba(78,125,96,0.13));
    border: 1px solid rgba(214,90,71,0.22);
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
    color: var(--text); border-color: rgba(214,90,71,0.45);
    background: var(--accent-soft);
    box-shadow: 0 0 18px -6px rgba(214,90,71,0.35);
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
  textarea#prompt:focus { border-color: rgba(214,90,71,0.5); box-shadow: 0 0 0 3px rgba(214,90,71,0.10); }
  .btn {
    border: none; border-radius: var(--r-md); cursor: pointer;
    font-size: 14px; font-family: inherit; padding: 13px 20px; font-weight: 600;
    color: #372b2e;
    background: linear-gradient(135deg, #ef8a73, var(--accent) 55%, #c94f3d);
    box-shadow: 0 6px 22px -8px rgba(214,90,71,0.5);
    transition: transform .14s ease, box-shadow .2s ease, opacity .2s ease;
    white-space: nowrap;
  }
  .btn:hover { transform: translateY(-1px); box-shadow: 0 10px 26px -8px rgba(214,90,71,0.6); }
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
    background: linear-gradient(rgba(214,90,71,0.35), rgba(118,101,104,0.08));
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
  .tl li.done .node { border-color: var(--accent); box-shadow: 0 0 14px -2px rgba(214,90,71,0.45); }
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
    border: 1px solid rgba(214,90,71,0.28);
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
    border: 2px solid rgba(214,90,71,0.16); border-top-color: var(--accent);
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
    border-color: rgba(214,90,71,0.4); background: var(--accent-soft);
    transform: translateX(3px);
  }
  .suggest .item .play-ico { color: var(--accent); font-size: 13px; }

  /* ---------- now playing ---------- */
  .nowbar {
    position: fixed; left: 50%; bottom: 22px; transform: translate(-50%, 150%);
    width: min(680px, calc(100vw - 36px));
    display: flex; align-items: center; gap: 15px;
    padding: 13px 20px;
    background: rgba(58, 42, 45, 0.92);
    border: 1px solid var(--panel-border-lit); border-radius: 20px;
    backdrop-filter: blur(24px) saturate(1.3);
    box-shadow: 0 18px 50px -12px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.05);
    transition: transform .5s cubic-bezier(.22,.9,.3,1);
    z-index: 10;
  }
  .nowbar.show { transform: translate(-50%, 0); }
  .nowbar .play {
    width: 44px; height: 44px; border-radius: 50%; border: none; cursor: pointer;
    background: linear-gradient(135deg, #ef8a73, var(--accent));
    color: #372b2e; font-size: 15px;
    display: flex; align-items: center; justify-content: center; flex-shrink: 0;
    box-shadow: 0 6px 18px -6px rgba(214,90,71,0.5);
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

  /* ---------- warm visual system ---------- */
  body { background: #f1edeb; }
  body.call-open { overflow: hidden; }
  .wrap { max-width: 1240px; padding-top: 28px; }
  header.hero { align-items: center; padding: 0 0 24px; }
  .mascot {
    border-radius: 8px; border-color: #d9cbc4;
    box-shadow: 0 9px 24px -16px rgba(76, 47, 47, .55);
  }
  .wordmark {
    background: linear-gradient(110deg, #402f31 12%, #c85140 62%, #4e7d60 100%);
    -webkit-background-clip: text; background-clip: text; color: transparent;
  }
  .tagline { color: #766568; }
  .tagline::before { background: #c2afa7; }
  .header-actions { margin-left: auto; display: flex; align-items: center; gap: 10px; }
  .health {
    margin-left: 0; background: #fffdfb; border-color: #dfd4cf;
    box-shadow: 0 5px 18px -14px rgba(72,42,44,.6);
  }
  .dot.ok { box-shadow: 0 0 0 3px rgba(63,124,89,.13); }
  .dot.down { box-shadow: 0 0 0 3px rgba(187,67,62,.12); }
  .call-entry {
    height: 36px; display: inline-flex; align-items: center; gap: 8px;
    border: 1px solid #c94f3d; border-radius: 7px; padding: 0 13px;
    color: #fff; background: #d65a47; font: 600 12.5px/1 inherit;
    cursor: pointer; box-shadow: 0 8px 20px -13px rgba(157,55,43,.75);
    transition: transform .16s ease, background .16s ease;
  }
  .call-entry:hover { background: #c94f3d; transform: translateY(-1px); }
  .call-entry:disabled { opacity: .55; cursor: wait; transform: none; }
  .call-entry .symbol { font-size: 16px; line-height: 1; }

  .card {
    background: #fffdfb; border-color: #dfd4cf; backdrop-filter: none;
    box-shadow: 0 18px 48px -34px rgba(75,45,47,.42);
  }
  .chat-head { background: #fff7f2; border-color: #e6dad4; color: #756164; }
  .msg { border-radius: 8px; }
  .msg.user {
    background: #f8ddd5; border-color: #ebbaa9; border-bottom-right-radius: 2px;
  }
  .msg.assistant {
    background: #eef4ef; border-color: #d3e2d6; border-bottom-left-radius: 2px;
  }
  .chip {
    border-radius: 6px; background: #fffaf7; border-color: #dfd4cf;
    color: #766568; padding: 7px 12px;
  }
  .chip:hover {
    color: #a63f34; border-color: #dc8e7d; background: #fff1eb;
    box-shadow: none;
  }
  .input-row { border-color: #e6dad4; background: #fffaf7; }
  textarea#prompt { background: #fff; border-color: #d9ccc6; color: #372b2e; }
  textarea#prompt:focus { border-color: #d65a47; box-shadow: 0 0 0 3px rgba(214,90,71,.10); }
  .btn {
    border-radius: 7px; color: #fff; background: #d65a47;
    box-shadow: 0 7px 18px -12px rgba(157,55,43,.85);
  }
  .btn:hover { background: #c94f3d; box-shadow: 0 9px 20px -13px rgba(157,55,43,.85); }
  .btn.ghost { color: #674f52; background: #f5ece7; border-color: #d9ccc6; }
  .btn.ghost:hover { background: #efe1da; border-color: #cbb7ae; }
  .btn.ghost.recording { background: #bb433e; color: #fff; }
  .tl-card { background: #fbfaf7; }
  .tl li::before { background: #ddcec7; }
  .tl .node { background: #fbfaf7; }
  .badge { background: #f9e3dc; color: #a53f33; border-color: #eab5a8; }
  .badge.cache { background: #e9f2eb; color: #356b4c; border-color: #bcd4c3; }
  .badge.warn { background: #fff2d7; color: #966115; border-color: #ead29d; }
  .tag { background: #f4eeea; border-color: #ded1cb; }
  .shimmer {
    background: linear-gradient(90deg, #f1e6e1 25%, #f8d8ce 50%, #f1e6e1 75%);
    background-size: 200% 100%;
  }
  .suggest .item { background: #fffaf7; border-color: #dfd4cf; border-radius: 7px; }
  .suggest .item:hover { border-color: #dc8e7d; background: #fff1eb; }
  .nowbar {
    background: rgba(58,42,45,.95); border-color: #624b4f; border-radius: 8px;
    color: #fff8f3; backdrop-filter: blur(16px);
  }
  .nowbar .play { background: #ef7b64; color: #2d2022; box-shadow: none; }
  .nowbar .sub { color: #d8c6c4; }
  .wave span { background: linear-gradient(#ef7b64, #76a384); }

  /* ---------- realtime call modal ---------- */
  .call-overlay[hidden] { display: none; }
  .call-overlay {
    position: fixed; inset: 0; z-index: 30; display: grid; place-items: center;
    padding: 24px; background: rgba(49,35,38,.58); backdrop-filter: blur(8px);
  }
  .call-shell {
    width: min(440px, 100%); max-height: calc(100vh - 48px); overflow: auto;
    position: relative; padding: 30px 30px 26px; border-radius: 8px;
    color: #372b2e; background: #fffdfb; border: 1px solid #dccfc9;
    box-shadow: 0 30px 70px -28px rgba(45,27,30,.75); text-align: center;
  }
  .call-close {
    position: absolute; top: 13px; right: 13px; width: 32px; height: 32px;
    border: 0; border-radius: 50%; color: #735f62; background: #f5ece7;
    font: 400 24px/30px inherit; cursor: pointer;
  }
  .call-avatar {
    width: 104px; height: 104px; margin: 4px auto 14px; border-radius: 28px;
    overflow: hidden; border: 1px solid #ddcec7; background: #fff8f3;
    transition: box-shadow .25s ease, transform .25s ease;
  }
  .call-avatar.live { box-shadow: 0 0 0 7px rgba(214,90,71,.11), 0 0 0 14px rgba(78,125,96,.07); }
  .call-avatar.speaking { transform: scale(1.035); }
  .call-avatar img { width: 100%; height: 100%; display: block; object-fit: cover; }
  .call-kicker { color: #a75547; font-size: 10.5px; font-weight: 700; letter-spacing: 1.4px; }
  .call-shell h2 { margin-top: 7px; font-size: 20px; letter-spacing: 0; }
  .call-state { min-height: 22px; margin-top: 8px; color: #766568; font-size: 13px; }
  .call-timer { margin-top: 2px; color: #a08b87; font: 500 12px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; }
  .call-wave {
    height: 40px; margin: 16px auto 10px; display: flex; align-items: center;
    justify-content: center; gap: 5px;
  }
  .call-wave span { width: 4px; height: 6px; border-radius: 3px; background: #d65a47; opacity: .55; }
  .call-wave.active span { animation: callWave 1.15s ease-in-out infinite; }
  .call-wave span:nth-child(2), .call-wave span:nth-child(6) { animation-delay: .12s; }
  .call-wave span:nth-child(3), .call-wave span:nth-child(5) { animation-delay: .24s; }
  .call-wave span:nth-child(4) { animation-delay: .36s; background: #4e7d60; }
  @keyframes callWave { 0%,100% { height: 6px; } 50% { height: 30px; } }
  .call-transcript {
    min-height: 108px; max-height: 180px; overflow-y: auto; margin: 0 -2px 20px;
    padding: 13px 4px; border-top: 1px solid #eadfda; border-bottom: 1px solid #eadfda;
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
    .wrap { padding: 18px 14px 120px; }
    header.hero { gap: 12px; }
    .brand-lockup { width: 100%; }
    .tagline { order: 3; width: 100%; }
    .header-actions { margin-left: 0; width: 100%; justify-content: space-between; }
    .chat { height: min(68vh, 700px); }
    .chat-head, .stream, .chips, .input-row { padding-left: 16px; padding-right: 16px; }
    .input-row { display: grid; grid-template-columns: 1fr auto; }
    textarea#prompt { grid-column: 1 / -1; }
    .btn { min-height: 44px; }
    .tl-card { position: static; }
    .call-overlay { padding: 12px; }
    .call-shell { max-height: calc(100vh - 24px); padding: 24px 20px 22px; }
  }
</style>
</head>
<body>
<div class="wrap">
  <header class="hero">
    <div class="brand-lockup">
      <div class="mascot"><img src="showcase/assets/baidu-bear.png" alt="百度小熊"></div>
      <div class="wordmark">Unwind</div>
    </div>
    <div class="tagline">让各位同学，压力小一点</div>
    <div class="header-actions">
      <div class="health"><span class="dot" id="healthDot"></span><span id="healthText">检测服务状态…</span></div>
      <button class="call-entry" id="callBtn" type="button"><span class="symbol" aria-hidden="true">☎</span><span>语音通话</span></button>
    </div>
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
        <h2>智能体决策轨迹</h2>
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

  <footer>UNWIND · 智能体驱动 · 内部演示版</footer>
</div>

<div class="nowbar" id="nowbar">
  <button class="play" id="playBtn">▶</button>
  <div class="info">
    <div class="title" id="npTitle">—</div>
    <div class="sub" id="npSub">—</div>
  </div>
  <div class="wave"><span></span><span></span><span></span><span></span><span></span></div>
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
