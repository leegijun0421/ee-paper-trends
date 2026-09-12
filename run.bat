@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo 전자공학 논문 트렌드 분석 앱을 시작합니다...
echo 브라우저가 자동으로 열립니다. 종료하려면 이 창에서 Ctrl+C 를 누르세요.
echo.
python -m streamlit run app.py --server.port 8501
pause
