@echo off
setlocal
chcp 65001 >nul
title Zelo - iniciar junto com o Windows

rem Versao para quem instalou clonando o repositorio (o pacote do empacotar.py
rem gera o proprio instalar-servico.bat, e este arquivo nao vai nele).
rem Mesma ideia: Tarefa Agendada no boot, como SYSTEM, sem ninguem logado.
rem Rode como administrador, na pasta do clone, depois de criar o ambiente
rem (python -m venv .venv  e  pip install -r requirements.txt).

net session >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Este arquivo precisa ser executado como administrador.
    echo    Clique com o botao direito e escolha "Executar como administrador".
    pause
    exit /b 1
)

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%~dp0venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [ERRO] Nao achei o ambiente Python desta pasta ^(.venv^).
    echo    Crie com:  python -m venv .venv
    echo    e instale: .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

rem A porta vem do mesmo lugar que o run.py le (instance\zelo.cfg ou PORT), em
rem vez de ficar fixa em 5001: porta trocada na configuracao e liberada no
rem firewall errado e o sistema que sobe e nao abre nas outras maquinas.
rem O "2^>nul" no fim nao e enfeite: se o comando comecar E terminar com aspas,
rem o cmd arranca as aspas de fora e o caminho do Python quebra no meio.
set "PORTA="
cd /d "%~dp0"
for /f %%p in ('"%PY%" -c "from app import INSTANCE_FOLDER; from app.configuracao import porta; print(porta(INSTANCE_FOLDER))" 2^>nul') do set "PORTA=%%p"
if not defined PORTA set "PORTA=5001"

echo [1/2] Liberando a porta %PORTA% no firewall...
rem Sem esta regra o sistema funciona na maquina do servidor e NAO abre em
rem nenhuma outra: o Windows recusa a conexao de entrada sem deixar erro no log.
rem TCP de proposito: HTTP e TCP.
netsh advfirewall firewall delete rule name="Zelo (HTTP)" >nul 2>&1
netsh advfirewall firewall add rule name="Zelo (HTTP)" dir=in action=allow ^
    protocol=TCP localport=%PORTA% profile=any >nul
if errorlevel 1 (
    echo    [AVISO] Nao consegui liberar a porta %PORTA% no firewall.
    echo    O sistema vai funcionar nesta maquina, mas pode nao abrir nas outras.
    echo    Peca a quem cuida da rede para liberar a porta %PORTA% ^(TCP^).
) else (
    echo    Porta %PORTA% liberada.
)

echo [2/2] Registrando o Zelo para iniciar junto com o Windows...
rem SYSTEM de proposito: tarefa amarrada a conta de pessoa para de rodar quando
rem a senha dela muda. Consequencia: o Python base precisa estar instalado para
rem todos os usuarios ^(ex.: C:\Program Files\Python3xx^), nao em AppData.
schtasks /Create /TN "Zelo" /SC ONSTART /RU "SYSTEM" /RL HIGHEST /F ^
    /TR "%~dp0servico-run.bat"
if errorlevel 1 (
    echo [ERRO] Nao consegui registrar. Confira se a politica da maquina
    echo    permite criar tarefas agendadas.
    pause
    exit /b 1
)

echo.
echo Pronto. O Zelo vai subir sozinho toda vez que o servidor ligar.
echo Para iniciar agora sem reiniciar:  schtasks /Run /TN "Zelo"
echo Para parar:                         schtasks /End /TN "Zelo"
echo Para desfazer:                      schtasks /Delete /TN "Zelo" /F
echo.
pause
