@echo off
chcp 65001 >nul
title Iniciar Pulso Monitor
cd /d "%~dp0"

if not exist "node_modules" (
  echo Pulso Monitor aun no esta instalado.
  echo Ejecutando instalacion...
  call instalar.bat
)

if not exist "backend\.venv\Scripts\python.exe" (
  echo Falta instalar el backend. Ejecuta instalar.bat.
  pause
  exit /b 1
)

set "PULSO_ROOT=%~dp0"
start "Pulso Monitor - API" cmd /k "cd /d ""%PULSO_ROOT%backend"" && .venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload"
start "Pulso Monitor - Panel" cmd /k "cd /d ""%PULSO_ROOT%"" && npm run dev -- --hostname 127.0.0.1"

echo Iniciando Pulso Monitor...
timeout /t 5 /nobreak >nul
start "" http://localhost:3000
exit
