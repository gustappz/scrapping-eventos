@echo off
title Visite SP - Scraping
cd /d "%~dp0"
echo ===============================================
echo   VISITE SP - Scraping com IA (Gemini)
echo ===============================================
echo.
echo Vai abrir o Chrome real (passa o Cloudflare).
echo Cada evento gasta uma chamada do Gemini.
echo Cota gratuita: 250 eventos/dia.
echo.
set /p meses="Quantos meses a frente (1 a 4)? "
echo.
".\venv\Scripts\python.exe" "src\run_visite_sp.py" %meses%
echo.
echo ===============================================
echo   PRONTO! Arquivo: output\data\visiteSP.xlsx
echo ===============================================
pause
