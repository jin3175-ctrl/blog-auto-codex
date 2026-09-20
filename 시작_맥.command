#!/bin/bash
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
export EDI_NO_WEBIMG=1
command -v claude >/dev/null 2>&1 || { echo "[!] 설치_맥.command 를 먼저 실행하세요."; read -p "엔터"; exit 1; }
echo '클로드 코드를 시작합니다.  "CLAUDE.md 읽고 시작해줘" 라고 말해보세요.'
claude
