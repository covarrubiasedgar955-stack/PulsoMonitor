@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title Pulso Monitor v1.20.0
cd /d "%~dp0"

set "PULSO_ROOT=%~dp0"
set "BACKEND_PY=%PULSO_ROOT%backend\.venv\Scripts\python.exe"
set "FRONTEND_PORT=3000"
set "BACKEND_PORT=8000"

echo.
echo ========================================
echo   PULSO MONITOR v1.20.0
echo ========================================
echo.

where node >nul 2>nul || goto :missing_node
where npm.cmd >nul 2>nul || goto :missing_node
where python >nul 2>nul || goto :missing_python

if not exist "node_modules" (
  echo [1/4] Instalando dependencias del panel...
  call npm.cmd install
  if errorlevel 1 goto :install_error
) else (
  echo [1/4] Panel web listo.
)

if not exist "%BACKEND_PY%" (
  echo [2/4] Creando entorno de Python...
  python -m venv backend\.venv
  if errorlevel 1 goto :install_error
) else (
  echo [2/4] Entorno de Python listo.
)

echo [3/4] Verificando dependencias del backend...
"%BACKEND_PY%" -c "import fastapi, uvicorn, multipart" >nul 2>nul
if errorlevel 1 (
  echo Instalando dependencias faltantes...
  "%BACKEND_PY%" -m pip install -r backend\requirements.txt
  if errorlevel 1 goto :install_error
)

if not exist "backend\.env" (
  echo Generando configuracion segura inicial...
  "%BACKEND_PY%" backend\generate_config.py
  if errorlevel 1 goto :install_error
)

echo [4/4] Preparando servicios...

for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%BACKEND_PORT%" ^| findstr "LISTENING"') do set "BACKEND_PID=%%P"
if defined BACKEND_PID (
  echo El puerto %BACKEND_PORT% ya esta ocupado. Se reutilizara el backend existente.
) else (
  start "Pulso Monitor - API" cmd /k "cd /d ""%PULSO_ROOT%backend"" && ""%BACKEND_PY%"" -m uvicorn main:app --host 127.0.0.1 --port %BACKEND_PORT% --reload"
)

for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":3000" ^| findstr "LISTENING"') do set "FRONTEND_PID=%%P"
if defined FRONTEND_PID (
  echo El puerto 3000 ya esta ocupado. Probando el 3001...
  set "FRONTEND_PORT=3001"
  for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":3001" ^| findstr "LISTENING"') do set "FRONTEND2_PID=%%P"
  if defined FRONTEND2_PID (
    echo ERROR: Los puertos 3000 y 3001 estan ocupados.
    echo Cierra la aplicacion que los usa y vuelve a abrir iniciar.bat.
    pause
    exit /b 1
  )
)

start "Pulso Monitor - Panel" cmd /k "cd /d ""%PULSO_ROOT%"" && npm.cmd run dev -- --hostname 127.0.0.1 --port !FRONTEND_PORT!"

echo.
echo Esperando a que Pulso Monitor termine de iniciar...
timeout /t 5 /nobreak >nul
start "" "http://127.0.0.1:!FRONTEND_PORT!"

echo Pulso Monitor esta iniciando en http://127.0.0.1:!FRONTEND_PORT!
timeout /t 2 /nobreak >nul
exit /b 0

:missing_node
echo ERROR: Node.js o npm no esta instalado.
echo Instala Node.js y vuelve a ejecutar iniciar.bat.
pause
exit /b 1

:missing_python
echo ERROR: Python no esta instalado o no esta en PATH.
pause
exit /b 1

:install_error
echo.
echo ERROR: No fue posible preparar Pulso Monitor.
echo Revisa el mensaje anterior y vuelve a intentarlo.
pause
exit /b 1
