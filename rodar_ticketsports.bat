@echo off
title TicketSports - Scraping
cd /d "%~dp0"
echo ===============================================
echo   TicketSports - Scraping de eventos
echo ===============================================
echo.
set /p estado="Digite a sigla do estado (RJ, SP, MG, PR...): "
echo.
echo Vai puxar todos os eventos do estado %estado%.
echo Demora uns 1-3 minutos. Nao feche essa janela.
echo.
".\venv\Scripts\python.exe" "src\run_ticketsports.py" %estado%
echo.
echo ===============================================
echo   PRONTO! Arquivo gerado:
echo   output\data\ticketsports.xlsx
echo ===============================================
echo.
pause
