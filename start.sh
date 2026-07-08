#!/bin/bash
# Floppy 后端启动脚本 — 固化环境（勿直接 uvicorn 裸起，见 docs/STARTUP.md）
# 关键：.baidu-int.com 必须绕过公司代理，否则 LLM 静默降级为模板生成
cd "$(dirname "$0")"
export NO_PROXY="localhost,127.0.0.1,::1,.local,.baidu-int.com"
export no_proxy="$NO_PROXY"

# Hermes gateway（决策层，8642）——未运行则拉起
if ! curl -s -m 2 -o /dev/null http://127.0.0.1:8642/v1/responses -X POST; then
  echo "[start] 启动 Hermes gateway..."
  nohup hermes gateway run > /tmp/hermes_gateway.log 2>&1 &
  sleep 8
fi

echo "[start] 启动 Floppy 后端 0.0.0.0:8000（LAN: http://$(ipconfig getifaddr en0):8000）"
exec .venv/bin/uvicorn floppy_backend.main:app --host 0.0.0.0 --port 8000
