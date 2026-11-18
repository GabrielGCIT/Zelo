@echo off
rem Remove o agente do Zelo desta maquina: a tarefa agendada e a pasta C:\ProgramData\Zelo\Agente.
setlocal
chcp 65001 >nul
title Zelo - remover o agente

net session >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Precisa rodar como administrador.
    echo    Clique com o botao direito neste arquivo e escolha "Executar como administrador".
    pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar-agente.ps1" -Remover
echo.
pause
