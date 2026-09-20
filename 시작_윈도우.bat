@echo off
setlocal
cd /d "%~dp0"
title 블로그 홈판 자동화(코덱스판)
set EDI_NO_WEBIMG=1
where claude >nul 2>nul
if %errorlevel%==0 goto RUN
if exist "%USERPROFILE%\.local\bin\claude.exe" goto RUNLOCAL
echo.
echo [!] 클로드 코드가 설치되어 있지 않습니다.
echo     설치_윈도우 파일을 먼저 더블클릭해 주세요.
echo.
pause
exit /b 1

:RUNLOCAL
set PATH=%USERPROFILE%\.local\bin;%PATH%
goto RUN

:RUN
echo.
echo  클로드 코드를 시작합니다.
echo  아래처럼 말해보세요.
echo.
echo     CLAUDE.md 읽고 시작해줘
echo.
claude
