@echo off
rem Executado pela Tarefa Agendada "Zelo" quando o servidor liga.
rem Para iniciar o sistema na mao, use: .venv\Scripts\python.exe run.py
rem
rem Existe separado do instalar-servico.bat porque `schtasks /TR` recusa mais de
rem 261 caracteres: a tarefa aponta para ESTE arquivo (um caminho so) e ele
rem descobre o resto com %~dp0.
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0run.py"
) else (
    "%~dp0venv\Scripts\python.exe" "%~dp0run.py"
)
