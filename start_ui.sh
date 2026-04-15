#!/usr/bin/env bash
set -euo pipefail

if ! lsof -nP -iTCP:8791 -sTCP:LISTEN >/dev/null 2>&1; then
  nohup python3 /Users/toby/Documents/local-ai-chat/tools/terminal_api.py >/tmp/local-ai-chat-terminal-api.log 2>&1 &
fi

if ! lsof -nP -iTCP:8790 -sTCP:LISTEN >/dev/null 2>&1; then
  cd /Users/toby/Documents/local-ai-chat/ui
  nohup python3 -m http.server 8790 >/tmp/local-ai-chat-ui.log 2>&1 &
fi

open "http://127.0.0.1:8790/"
