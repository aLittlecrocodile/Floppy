from __future__ import annotations


DEMO_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Floppy Chat Demo</title>
  <style>
    :root {
      color-scheme: light;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #edf1f5;
      color: #18212f;
    }
    * {
      box-sizing: border-box;
    }
    body {
      margin: 0;
      min-height: 100vh;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.82), rgba(237,241,245,0.98)),
        url("data:image/svg+xml,%3Csvg width='160' height='160' viewBox='0 0 160 160' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' stroke='%23c9d8e6' stroke-width='1' opacity='0.5'%3E%3Cpath d='M0 92c18-18 36-18 54 0s36 18 54 0 36-18 54 0'/%3E%3Cpath d='M0 116c18-18 36-18 54 0s36 18 54 0 36-18 54 0'/%3E%3Cpath d='M0 68c18-18 36-18 54 0s36 18 54 0 36-18 54 0'/%3E%3C/g%3E%3C/svg%3E");
    }
    .app {
      width: min(1120px, 100vw);
      min-height: 100vh;
      margin: 0 auto;
      display: grid;
      grid-template-rows: auto 1fr auto;
      padding: 18px;
      gap: 14px;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      min-height: 52px;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }
    .mark {
      width: 38px;
      height: 38px;
      border-radius: 8px;
      background: #1f6f68;
      display: grid;
      place-items: center;
      color: #ffffff;
      font-weight: 800;
      font-size: 16px;
      flex: 0 0 auto;
    }
    h1 {
      margin: 0;
      font-size: 20px;
      letter-spacing: 0;
      line-height: 1.2;
    }
    .subtitle {
      margin-top: 3px;
      color: #667384;
      font-size: 13px;
      line-height: 1.35;
    }
    .status {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 34px;
      padding: 0 12px;
      border: 1px solid #c9d5df;
      border-radius: 8px;
      background: rgba(255,255,255,0.76);
      color: #324155;
      font-size: 13px;
      white-space: nowrap;
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #23866f;
    }
    main {
      min-height: 0;
      display: grid;
      grid-template-columns: minmax(0, 1fr) 300px;
      gap: 14px;
    }
    .chat {
      min-height: 0;
      border: 1px solid #ccd7e2;
      border-radius: 8px;
      background: rgba(255,255,255,0.86);
      display: grid;
      grid-template-rows: 1fr;
      overflow: hidden;
    }
    .messages {
      overflow: auto;
      padding: 18px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .msg {
      width: min(760px, 100%);
      display: grid;
      gap: 8px;
    }
    .msg.user {
      align-self: flex-end;
      justify-items: end;
    }
    .msg.assistant {
      align-self: flex-start;
    }
    .bubble {
      border: 1px solid #d5dee8;
      border-radius: 8px;
      padding: 12px 14px;
      line-height: 1.58;
      font-size: 15px;
      background: #ffffff;
      word-break: break-word;
    }
    .user .bubble {
      color: #ffffff;
      background: #245a9c;
      border-color: #245a9c;
    }
    .assistant .bubble {
      background: #fbfcfd;
    }
    .meta {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 0 9px;
      border-radius: 8px;
      border: 1px solid #d4dde7;
      background: #f6f8fa;
      color: #415067;
      font-size: 12px;
      font-weight: 650;
    }
    .player {
      border: 1px solid #d9e1e9;
      border-radius: 8px;
      background: #ffffff;
      padding: 10px;
      width: min(520px, 100%);
    }
    .player-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 8px;
      color: #263348;
      font-size: 13px;
      font-weight: 750;
    }
    audio {
      display: block;
      width: 100%;
      height: 38px;
    }
    details {
      width: min(680px, 100%);
    }
    summary {
      cursor: pointer;
      color: #526073;
      font-size: 13px;
      font-weight: 700;
      padding: 4px 0;
    }
    pre {
      white-space: pre-wrap;
      word-break: break-word;
      margin: 6px 0 0;
      background: #151b24;
      color: #e8eef5;
      border-radius: 8px;
      padding: 12px;
      max-height: 280px;
      overflow: auto;
      font-size: 12px;
      line-height: 1.5;
    }
    aside {
      border: 1px solid #ccd7e2;
      border-radius: 8px;
      background: rgba(255,255,255,0.78);
      padding: 14px;
      overflow: auto;
    }
    .panel-title {
      margin: 0 0 10px;
      font-size: 13px;
      color: #526073;
      font-weight: 800;
    }
    .quick-list {
      display: grid;
      gap: 8px;
    }
    .quick {
      width: 100%;
      min-height: 40px;
      border: 1px solid #cad6e2;
      border-radius: 8px;
      background: #ffffff;
      color: #263348;
      text-align: left;
      padding: 10px;
      font: inherit;
      line-height: 1.35;
      cursor: pointer;
    }
    .quick:hover {
      border-color: #6c91bf;
      background: #f7fbff;
    }
    .runtime {
      margin-top: 16px;
      display: grid;
      gap: 8px;
    }
    .runtime-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      border-top: 1px solid #e4eaf0;
      padding-top: 8px;
      font-size: 12px;
      color: #617085;
    }
    footer {
      border: 1px solid #ccd7e2;
      border-radius: 8px;
      background: rgba(255,255,255,0.9);
      padding: 10px;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      align-items: end;
    }
    label {
      display: block;
      margin: 0 0 6px;
      color: #526073;
      font-size: 12px;
      font-weight: 800;
    }
    textarea {
      width: 100%;
      min-height: 54px;
      max-height: 160px;
      resize: vertical;
      border: 1px solid #c5d0dc;
      border-radius: 8px;
      padding: 11px 12px;
      font: inherit;
      line-height: 1.45;
      outline: none;
      background: #ffffff;
      color: #18212f;
    }
    textarea:focus {
      border-color: #2b6c9f;
      box-shadow: 0 0 0 3px rgba(43,108,159,0.14);
    }
    .send {
      width: 96px;
      height: 54px;
      border: 0;
      border-radius: 8px;
      background: #1f6f68;
      color: #ffffff;
      font: inherit;
      font-weight: 800;
      cursor: pointer;
    }
    .send:disabled {
      cursor: wait;
      opacity: 0.58;
    }
    .pending {
      display: inline-flex;
      gap: 5px;
      align-items: center;
      color: #667384;
      font-size: 14px;
    }
    .pending span {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: #7a8a9c;
      animation: pulse 1.1s infinite ease-in-out;
    }
    .pending span:nth-child(2) {
      animation-delay: 0.16s;
    }
    .pending span:nth-child(3) {
      animation-delay: 0.32s;
    }
    @keyframes pulse {
      0%, 80%, 100% { opacity: 0.28; transform: translateY(0); }
      40% { opacity: 1; transform: translateY(-2px); }
    }
    @media (max-width: 860px) {
      .app {
        padding: 12px;
      }
      header {
        align-items: flex-start;
        flex-direction: column;
      }
      main {
        grid-template-columns: 1fr;
      }
      aside {
        max-height: 220px;
      }
      footer {
        grid-template-columns: 1fr;
      }
      .send {
        width: 100%;
      }
    }
  </style>
</head>
<body>
  <div class="app">
    <header>
      <div class="brand">
        <div class="mark">F</div>
        <div>
          <h1>Floppy 助眠对话测试台</h1>
          <div class="subtitle">Hermes Agent Runtime + Floppy 音频工作流</div>
        </div>
      </div>
      <div class="status"><span class="dot"></span><span id="status">就绪</span></div>
    </header>

    <main>
      <section class="chat" aria-label="chat">
        <div class="messages" id="messages"></div>
      </section>

      <aside>
        <p class="panel-title">试试这些</p>
        <div class="quick-list">
          <button class="quick" type="button">我今晚压力很大，想听一个温柔的呼吸冥想，带一点雨声，15分钟</button>
          <button class="quick" type="button">给我来一段海边书店的睡前故事，声音温柔一点</button>
          <button class="quick" type="button">我只想听白噪音，最好是稳定的雨声，不要有人声</button>
          <button class="quick" type="button">刚才那个音频帮我加一点海浪背景，声音不要太大</button>
        </div>
        <div class="runtime">
          <p class="panel-title">当前链路</p>
          <div class="runtime-row"><span>入口</span><b>/demo/chat</b></div>
          <div class="runtime-row"><span>用户</span><b>demo_user</b></div>
          <div class="runtime-row"><span>动作</span><b id="last-action">-</b></div>
          <div class="runtime-row"><span>Planner</span><b id="last-planner">-</b></div>
        </div>
      </aside>
    </main>

    <footer>
      <div>
        <label for="prompt">输入</label>
        <textarea id="prompt" autocomplete="off">我今晚压力很大，想听一个温柔的呼吸冥想，带一点雨声，15分钟</textarea>
      </div>
      <button class="send" id="send" type="button">发送</button>
    </footer>
  </div>

  <script>
    const messages = document.getElementById("messages");
    const promptEl = document.getElementById("prompt");
    const sendBtn = document.getElementById("send");
    const statusEl = document.getElementById("status");
    const lastAction = document.getElementById("last-action");
    const lastPlanner = document.getElementById("last-planner");

    function setStatus(text) {
      statusEl.textContent = text;
    }

    function scrollToBottom() {
      messages.scrollTop = messages.scrollHeight;
    }

    function messageShell(role) {
      const root = document.createElement("article");
      root.className = `msg ${role}`;
      const bubble = document.createElement("div");
      bubble.className = "bubble";
      root.appendChild(bubble);
      messages.appendChild(root);
      scrollToBottom();
      return {root, bubble};
    }

    function addTextMessage(role, text) {
      const {bubble} = messageShell(role);
      bubble.textContent = text;
      scrollToBottom();
      return bubble;
    }

    function addPendingMessage() {
      const {root, bubble} = messageShell("assistant");
      bubble.innerHTML = '<span class="pending"><span></span><span></span><span></span>处理中</span>';
      scrollToBottom();
      return root;
    }

    function pill(text) {
      const el = document.createElement("span");
      el.className = "pill";
      el.textContent = text;
      return el;
    }

    function safeScore(value) {
      if (value === null || value === undefined) return "-";
      const number = Number(value);
      return Number.isFinite(number) ? number.toFixed(3) : String(value);
    }

    function renderAssistant(root, data, elapsedMs) {
      root.innerHTML = "";
      const bubble = document.createElement("div");
      bubble.className = "bubble";
      bubble.textContent = data.reply_text || "我为你准备好了，可以先听听看。";
      root.appendChild(bubble);

      const meta = document.createElement("div");
      meta.className = "meta";
      meta.appendChild(pill(`动作 ${data.action || "-"}`));
      meta.appendChild(pill(`命中 ${data.hit ? "是" : "否"}`));
      meta.appendChild(pill(`分数 ${safeScore(data.best_score)}`));
      meta.appendChild(pill(`耗时 ${elapsedMs}ms`));
      if (data.planner_meta && data.planner_meta.planner_source) {
        meta.appendChild(pill(`Planner ${data.planner_meta.planner_source}`));
      }
      if (data.job_id) {
        meta.appendChild(pill(`Job ${data.job_status || "queued"}`));
      }
      root.appendChild(meta);

      if (data.audio_url) {
        const player = document.createElement("div");
        player.className = "player";
        const title = document.createElement("div");
        title.className = "player-title";
        const name = data.asset && data.asset.title ? data.asset.title : "助眠音频";
        title.textContent = name;
        const source = document.createElement("span");
        source.textContent = data.asset && data.asset.type ? data.asset.type : "audio";
        title.appendChild(source);
        const audio = document.createElement("audio");
        audio.controls = true;
        audio.src = data.audio_url;
        player.appendChild(title);
        player.appendChild(audio);
        root.appendChild(player);
      }

      const detail = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = "决策详情";
      const pre = document.createElement("pre");
      pre.textContent = JSON.stringify(data, null, 2);
      detail.appendChild(summary);
      detail.appendChild(pre);
      root.appendChild(detail);

      lastAction.textContent = data.action || "-";
      lastPlanner.textContent = data.planner_meta && data.planner_meta.planner_source
        ? data.planner_meta.planner_source
        : "-";
      scrollToBottom();
    }

    async function postJson(url, body) {
      const resp = await fetch(url, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body)
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        throw new Error(data.detail || data.error || resp.statusText || "请求失败");
      }
      return data;
    }

    async function sendPrompt(text) {
      const prompt = text.trim();
      if (!prompt || sendBtn.disabled) return;
      addTextMessage("user", prompt);
      promptEl.value = "";
      sendBtn.disabled = true;
      setStatus("处理中");
      const pending = addPendingMessage();
      const started = performance.now();
      try {
        const data = await postJson("/demo/chat", {request_text: prompt});
        renderAssistant(pending, data, Math.round(performance.now() - started));
        setStatus(data.audio_url ? "可播放" : "已返回");
      } catch (err) {
        pending.innerHTML = "";
        const bubble = document.createElement("div");
        bubble.className = "bubble";
        bubble.textContent = `失败：${err.message}`;
        pending.appendChild(bubble);
        setStatus("失败");
      } finally {
        sendBtn.disabled = false;
        promptEl.focus();
      }
    }

    sendBtn.addEventListener("click", () => sendPrompt(promptEl.value));
    promptEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendPrompt(promptEl.value);
      }
    });
    document.querySelectorAll(".quick").forEach((button) => {
      button.addEventListener("click", () => {
        promptEl.value = button.textContent.trim();
        promptEl.focus();
      });
    });

    addTextMessage("assistant", "你可以直接告诉我今晚想听什么，我会帮你查找或生成一段助眠音频。");
  </script>
</body>
</html>
"""
