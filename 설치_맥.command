#!/bin/bash
cd "$(dirname "$0")"
echo "============================================"
echo "  블로그 홈판 자동화(코덱스판) 설치 (맥) - 1회만"
echo "============================================"
python3 --version || { echo "[!] 파이썬이 없습니다."; read -p "엔터"; exit 1; }
echo "[1/4] 파이썬 확인 완료"
echo "[2/4] 필요한 부품 설치 중..."
python3 -m pip install --user playwright requests pillow
echo "[3/4] 크롬 브라우저 부품 설치 중..."
python3 -m playwright install chromium
echo "[4/4] 클로드 코드 설치 중..."
command -v claude >/dev/null 2>&1 || [ -x "$HOME/.local/bin/claude" ] || curl -fsSL https://claude.ai/install.sh | bash
echo "============================================"
echo "  설치 완료! 내정보.txt 채우고 시작_맥.command 더블클릭"
echo "============================================"
read -p "엔터를 누르면 닫힙니다"
