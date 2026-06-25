@echo off
title MapaDosFestivais - Scraping
cd /d "%~dp0"
echo ===============================================
echo   RODANDO: MapaDosFestivais
echo   Vai puxar todos os festivais (cerca de 135).
echo   Demora uns 4-6 minutos. Nao feche essa janela.
echo ===============================================
echo.
".\venv\Scripts\python.exe" "src\run_mapadosfestivais.py"
echo.
echo ===============================================
echo   PRONTO! O arquivo Excel foi gerado em:
echo   output\data\mapadosfestivais.xlsx
echo ===============================================
echo.
pause
