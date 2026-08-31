@echo off
chcp 65001 >nul
title Instalar Pulso Monitor
cd /d "%~dp0"

echo.
echo ========================================
echo   INSTALANDO PULSO MONITOR v1.21.0
echo ========================================
echo.

where node >nul 2>nul || (echo ERROR: Node.js no esta instalado. & pause & exit /b 1)
where npm.cmd >nul 2>nul || (echo ERROR: npm no esta instalado. & pause & exit /b 1)
where python >nul 2>nul || (echo ERROR: Python no esta instalado. & pause & exit /b 1)

echo [1/3] Instalando el panel web...
call npm.cmd install
if errorlevel 1 (echo ERROR al instalar el panel. & pause & exit /b 1)

echo [2/3] Preparando el backend...
if not exist "backend\.venv\Scripts\python.exe" python -m venv backend\.venv
if errorlevel 1 (echo ERROR al crear el entorno de Python. & pause & exit /b 1)

echo [3/3] Instalando la API...
call backend\.venv\Scripts\python.exe -m pip install --upgrade pip
call backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if errorlevel 1 (echo ERROR al instalar la API. & pause & exit /b 1)

call backend\.venv\Scripts\python.exe -c "import multipart" >nul 2>nul
if errorlevel 1 (echo ERROR: python-multipart no quedo instalado correctamente. & pause & exit /b 1)

echo [SEGURIDAD] Generando acceso privado...
call backend\.venv\Scripts\python.exe backend\generate_config.py
if errorlevel 1 (echo ERROR al generar los datos de acceso. & pause & exit /b 1)

echo.
echo ========================================
echo   INSTALACION TERMINADA
echo ========================================
echo Tus datos y usuarios existentes se conservaron.
echo En una instalacion nueva, el acceso inicial se guarda en ACCESO.txt.
echo Ahora solo abre iniciar.bat para arrancar Pulso Monitor.
echo.
if exist "%~dp0ACCESO.txt" start "" notepad.exe "%~dp0ACCESO.txt"
pause
