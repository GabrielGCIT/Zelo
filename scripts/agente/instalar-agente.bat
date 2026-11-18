@echo off
rem Instala o agente do Zelo nesta maquina. Botao direito > Executar como administrador.
rem Existe porque .ps1 nao abre com dois cliques, e a politica de execucao padrao do Windows
rem recusa script baixado: o -ExecutionPolicy Bypass vale so para esta chamada.
setlocal
chcp 65001 >nul
title Zelo - instalar o agente

net session >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Precisa rodar como administrador.
    echo    Clique com o botao direito neste arquivo e escolha "Executar como administrador".
    pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar-agente.ps1"
echo.
pause
