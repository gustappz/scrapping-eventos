@echo off
title Ingresse - Scraping
cd /d "%~dp0"
echo ===============================================
echo   INGRESSE - Scraping de eventos
echo ===============================================
echo.
set /p estado="Digite a sigla do estado (RJ, SP, MG, BA, PR...): "
echo.
echo Vai puxar eventos do Ingresse para %estado%.
echo Demora 30-90 segundos. Nao feche essa janela.
echo.
".\venv\Scripts\python.exe" "src\run_ingresse.py" %estado%
echo.
echo ===============================================
echo   PRONTO! Arquivo gerado:
echo   output\data\ingresse.xlsx
echo ===============================================
echo.
pause
