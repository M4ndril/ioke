@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo O Karaoke ainda nao foi instalado. Abrindo o instalador...
  call "%~dp0instalar.bat"
  if not exist ".venv\Scripts\python.exe" exit /b 1
)
title Karaoke
rem Se o servidor cair no meio da festa, ele volta sozinho em alguns segundos.
rem (0 = fechou normal, 3 = ja estava aberto em outra janela: nao tenta de novo)
:loop
".venv\Scripts\python.exe" server.py
set CODE=%ERRORLEVEL%
if "%CODE%"=="0" goto fim
if "%CODE%"=="3" goto fim
echo.
echo  O servidor parou (codigo %CODE%). Voltando em 3 segundos...
echo  O motivo fica em data\logs\karaoke.log. Feche esta janela para desligar.
set KARAOKE_NO_BROWSER=1
timeout /t 3 /nobreak >nul
goto loop
:fim
pause
