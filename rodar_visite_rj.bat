@echo off
title Visite RJ - Scraping
cd /d "%~dp0"
echo ===============================================
echo   VISITE RJ - Scraping com IA (Gemini)
echo ===============================================
echo.
echo Vai abrir o Chrome real (passa o Cloudflare).
echo Cada evento gasta uma chamada do Gemini.
echo Cota gratuita: 250 eventos/dia.
echo.
set /p periodos="Quantos periodos de 5 dias a frente (1 a 15)? "
echo.
".\venv\Scripts\python.exe" "src\run_visite_rj.py" %periodos%
echo.
echo ===============================================
echo   PRONTO! Arquivo: output\data\visiteRJ.xlsx
echo ===============================================
pause
