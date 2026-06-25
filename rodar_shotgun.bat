@echo off
title Shotgun - Scraping
cd /d "%~dp0"
echo ===============================================
echo   SHOTGUN - Scraping de eventos
echo ===============================================
echo.
echo Vai abrir o Chrome real (passa o anti-bot).
echo Demora 1-3 minutos.
echo.
echo Cidades comuns:
echo   - Sao Paulo
echo   - Rio de Janeiro
echo   - Porto Alegre
echo   - Belo Horizonte
echo   - Curitiba
echo   - Salvador
echo.
set /p cidade="Digite a cidade: "
echo.
".\venv\Scripts\python.exe" "src\run_shotgun.py" "%cidade%"
echo.
echo ===============================================
echo   PRONTO! Arquivo: output\data\shotgun.xlsx
echo ===============================================
pause
