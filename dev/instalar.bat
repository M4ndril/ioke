@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0.."
title Instalador do Karaoke
echo ================================================
echo   Instalador do Karaoke
echo ================================================
echo.

rem ---------------------------------------------------------------- FFmpeg
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [1/6] FFmpeg nao encontrado. Instalando via winget...
  winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
  echo      Se o FFmpeg acabou de ser instalado, FECHE esta janela e rode o dev\instalar.bat de novo.
) else (
  echo [1/6] FFmpeg OK
)

rem ------------------------------------------------------------------- uv
set "UV=uv"
where uv >nul 2>nul
if errorlevel 1 set "UV=%USERPROFILE%\.local\bin\uv.exe"
if not "%UV%"=="uv" if not exist "%UV%" (
  echo [2/6] Instalando o uv - gerenciador de Python...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
)
if not "%UV%"=="uv" if not exist "%UV%" (
  echo ERRO: nao consegui instalar o uv. Veja https://docs.astral.sh/uv/
  pause
  exit /b 1
)
echo [2/6] uv OK

rem --------------------------------------------------------- ambiente Python
rem O Python fica dentro da pasta do projeto (nao mexe no resto do sistema)
set "UV_PYTHON_INSTALL_DIR=%~dp0..\.python"
if not exist ".venv\Scripts\python.exe" (
  echo [3/6] Criando o ambiente Python 3.12...
  "%UV%" venv .venv --python 3.12
  if errorlevel 1 goto :fail
) else (
  echo [3/6] Ambiente Python OK
)
set "PY=.venv\Scripts\python.exe"

rem ---------------------------------------------------------------- PyTorch
nvidia-smi >nul 2>nul
if errorlevel 1 (
  echo [4/6] Sem placa NVIDIA: instalando PyTorch para CPU - a separacao vai ser lenta
  "%UV%" pip install --python "%PY%" torch torchvision torchaudio
) else (
  echo [4/6] Placa NVIDIA encontrada: instalando PyTorch com CUDA - uns 3 GB, tenha paciencia
  "%UV%" pip install --python "%PY%" torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
)
if errorlevel 1 goto :fail

echo [5/6] Instalando o resto das dependencias...
"%UV%" pip install --python "%PY%" -r requirements.txt
if errorlevel 1 goto :fail

echo.
echo Baixando os modelos de separacao - uns 1,5 GB na primeira vez...
"%PY%" -m karaoke.prefetch
if errorlevel 1 (
  echo AVISO: nao consegui baixar os modelos agora. Eles serao baixados na primeira musica.
)

echo.
echo [6/6] Liberando os celulares no firewall do Windows - so a porta do karaoke, so a rede local...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\karaoke\firewall.ps1"

echo.
echo ================================================
echo   Pronto! Agora e so abrir o dev\iniciar.bat
echo ================================================
pause
exit /b 0

:fail
echo.
echo ERRO durante a instalacao. Veja as mensagens acima.
pause
exit /b 1
