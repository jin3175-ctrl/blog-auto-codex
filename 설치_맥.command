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
echo "[+] 에고라이트 확인 (네이버 임시저장은 에고라이트로 합니다)"
if [ -d "/Applications/ego lite.app" ] || [ -d "$HOME/Applications/ego lite.app" ]; then
  echo "    에고라이트 있음. 에고라이트를 열고 네이버에 직접 로그인해 두세요."
else
  echo "    에고라이트가 없습니다. 열리는 페이지에서 내려받아 설치 → 앱을 한 번 열어 첫 화면을 끝내 주세요."
  open "https://lite.ego.app/"
fi
echo "============================================"
echo "  설치 완료! 내정보.txt 채우고 시작_맥.command 더블클릭"
echo "============================================"
read -p "엔터를 누르면 닫힙니다"
