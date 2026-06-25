@echo off
title Clubinho - Scraping
cd /d "%~dp0"
echo ===============================================
echo   CLUBINHO - Scraping de eventos
echo ===============================================
echo.
echo Cidades disponiveis:
echo   - Rio de Janeiro
echo   - Sao Paulo
echo   - Niteroi
echo   - Porto Alegre
echo   - Goiania
echo   - Olinda
echo   - Minas Gerais
echo   - Sao Caetano do Sul
echo.
set /p cidade="Digite a cidade: "
echo.
echo Vai puxar todos os eventos de %cidade%.
echo Demora uns 1-3 minutos. Nao feche essa janela.
echo.
".\venv\Scripts\python.exe" "src\run_clubinho.py" "%cidade%"
echo.
echo ===============================================
echo   PRONTO! Arquivo gerado:
echo   output\data\clubinho.xlsx
echo ===============================================
echo.
pause
