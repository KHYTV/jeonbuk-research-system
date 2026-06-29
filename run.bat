@echo off
chcp 65001 >nul
REM ── 전북 연구 시스템 원클릭 실행 (Windows) ──────────────────
REM .env 의 키를 환경변수로 로드 → 수집 → 분석/기사/대시보드
cd /d "%~dp0"

if exist .env (
  for /f "usebackq tokens=1,* delims==" %%a in (".env") do set "%%a=%%b"
) else (
  echo [!] .env 파일이 없습니다. .env.example 을 복사해 .env 로 만들고 키를 채우세요.
)

echo [1/2] 데이터 수집 (pipeline)
cd pipeline
python main.py weekly
cd ..

echo [2/2] 분석 + 뉴스기사 + 대시보드 (bridge)
python bridge.py

echo.
echo 완료. 대시보드: jeonbuk\web\index.html  (GitHub Pages: docs\index.html)
pause
