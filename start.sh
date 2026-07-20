#!/bin/bash
# Unwind 后端启动脚本 — 固化环境（勿直接 uvicorn 裸起，见 docs/STARTUP.md）
# 关键：.baidu-int.com 必须绕过公司代理，否则 LLM 静默降级为模板生成
cd "$(dirname "$0")"
export NO_PROXY="localhost,127.0.0.1,::1,.local,.baidu-int.com"
export no_proxy="$NO_PROXY"

# 自动探测本机局域网 IP，手机端拿到的音频 URL 才永远指向可达地址。
# en0 → en1 → 保留 .env/环境里已有的值。
LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
if [ -n "$LAN_IP" ]; then
  export FLOPPY_PUBLIC_BASE_URL="http://${LAN_IP}:8000"
  echo "[start] FLOPPY_PUBLIC_BASE_URL=$FLOPPY_PUBLIC_BASE_URL (auto-detected)"
fi

# Only start the bundled local gateway when the configured Hermes endpoint is
# local. Remote OpenAI-compatible gateways (for example OneAPI) are already
# managed outside this process and must not trigger a second local gateway.
HERMES_BASE_URL="${FLOPPY_HERMES_BASE_URL:-}"
if [ -z "$HERMES_BASE_URL" ] && [ -f .env ]; then
  HERMES_BASE_URL="$(sed -n 's/^FLOPPY_HERMES_BASE_URL=//p' .env | tail -n 1)"
fi
HERMES_BASE_URL="${HERMES_BASE_URL:-http://127.0.0.1:8642}"
case "$HERMES_BASE_URL" in
  http://127.0.0.1:8642|http://localhost:8642)
    if ! curl -s -m 2 -o /dev/null "$HERMES_BASE_URL/v1/responses" -X POST; then
      if command -v hermes >/dev/null 2>&1; then
        echo "[start] 启动本地 Hermes gateway..."
        nohup hermes gateway run > /tmp/hermes_gateway.log 2>&1 &
        sleep 8
      else
        echo "[start] 警告：本地 Hermes gateway 不可用，后端将按配置降级。"
      fi
    fi
    ;;
  *)
    echo "[start] 使用远端 Hermes：$HERMES_BASE_URL"
    ;;
esac

echo "[start] 启动 Unwind 后端 0.0.0.0:8000（LAN: http://$(ipconfig getifaddr en0):8000）"
echo "[start] 访问日志（含客户端 IP）实时写入 logs/floppy.log —— 排查连接用：tail -f logs/floppy.log"
# 我们自己的 AccessLogMiddleware 已记录带客户端 IP 的访问日志，故关闭 uvicorn 内置 access log 避免重复。
exec .venv/bin/uvicorn floppy_backend.main:app --host 0.0.0.0 --port 8000 --no-access-log
