@echo off
setlocal
cd /d "%~dp0"
title 블로그 홈판 자동화(코덱스판) 설치
echo ============================================
echo    블로그 홈판 자동화(코덱스판) 설치 - 처음 한 번만
echo ============================================
echo.
echo 지금 폴더: %CD%
echo.

set PY=
where py >nul 2>nul
if %errorlevel%==0 set PY=py
if defined PY goto HAVEPY
where python >nul 2>nul
if %errorlevel%==0 set PY=python
if defined PY goto HAVEPY
goto NOPY

:HAVEPY
"%PY%" --version >nul 2>nul
if errorlevel 1 goto NOPY
echo [1/4] 파이썬 확인 완료
echo.

echo [2/4] 필요한 부품을 설치합니다. 몇 분 걸립니다...
"%PY%" -m pip install --user --quiet playwright requests pillow
if errorlevel 1 goto PIPFAIL
echo      완료
echo.

echo [3/4] 크롬 부품을 설치합니다. 몇 분 걸립니다...
"%PY%" -m playwright install chromium
if errorlevel 1 goto PWFAIL
echo      완료
echo.

echo [4/4] 클로드 코드를 설치합니다...
where claude >nul 2>nul
if %errorlevel%==0 goto HAVECLAUDE
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://claude.ai/install.ps1 | iex"
goto DONE

:HAVECLAUDE
echo      이미 설치되어 있습니다
goto DONE

:DONE
echo.
echo ============================================
echo    설치가 끝났습니다!
echo.
echo    다음 순서
echo    1. 메모장으로 내정보.txt 를 열어 내 블로그ID 넣기
echo    2. 시작_윈도우 파일 더블클릭 - 클로드 코드가 열립니다
echo    3. "CLAUDE.md 읽고 시작해줘" 라고 말하기
echo ============================================
echo.
pause
exit /b 0

:NOPY
echo.
echo [!] 파이썬이 설치되어 있지 않습니다.
echo.
echo     1. 시작 - Microsoft Store 열기
echo     2. Python 3.12 검색해서 설치
echo     3. 이 파일을 다시 더블클릭
echo.
pause
exit /b 1

:PIPFAIL
echo.
echo [!] 부품 설치에 실패했습니다. 인터넷 연결을 확인하고 다시 해보세요.
echo     계속 안 되면 이 화면을 사진 찍어 단톡방에 올려주세요.
echo.
pause
exit /b 1

:PWFAIL
echo.
echo [!] 크롬 부품 설치에 실패했습니다. 인터넷 연결을 확인하고 다시 해보세요.
echo     계속 안 되면 이 화면을 사진 찍어 단톡방에 올려주세요.
echo.
pause
exit /b 1
