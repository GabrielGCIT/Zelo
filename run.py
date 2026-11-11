"""Entrypoint do Zelo.  Uso: python run.py

Sobe sem nenhuma variável de ambiente: o banco nasce em instance/zelo.db e a
SECRET_KEY é gerada e guardada em instance/secret_key no primeiro boot.
Enquanto não houver usuário, o boot imprime o endereço de primeiro acesso.
ZELO_DEBUG=1 liga o modo de desenvolvimento (nunca numa máquina que a rede alcança).
"""
import os

from app import INSTANCE_FOLDER, ROOT_DIR, create_app
from app.configuracao import garantir_arquivo, porta as porta_configurada
from app.registro import anunciar, configurar as configurar_log

app = create_app()

if __name__ == '__main__':
    arquivo_cfg = garantir_arquivo(INSTANCE_FOLDER)
    porta = porta_configurada(INSTANCE_FOLDER)
    arquivo_log = configurar_log(app, ROOT_DIR)
    if arquivo_log:
        anunciar(f'[Zelo] Registro de eventos em {arquivo_log}')
    with app.app_context():
        from app.auth import preparar_primeiro_acesso
        token = preparar_primeiro_acesso()
        if token:
            anunciar('=' * 72)
            anunciar('[PRIMEIRO ACESSO] Esta instalação ainda não tem administrador. Abra no navegador:')
            anunciar(f'[PRIMEIRO ACESSO]   http://<endereco-do-servidor>:{porta}/primeiro-acesso/{token}')
            anunciar(f'[PRIMEIRO ACESSO]   (nesta máquina: http://127.0.0.1:{porta}/primeiro-acesso/{token})')
            anunciar('=' * 72)
    from app.agendador import iniciar as iniciar_backup
    iniciar_backup(app)
    if os.environ.get('ZELO_DEBUG') == '1':
        app.run(debug=True, host='127.0.0.1', port=porta)
    else:
        from waitress import serve
        anunciar(f'[Zelo] No ar na porta {porta}. Esta janela pode ficar aberta.')
        if arquivo_cfg:
            anunciar(f'[Zelo] Para trocar a porta: {arquivo_cfg}')
        # '*' atende IPv4 e IPv6 (no Windows o nome do servidor resolve para IPv6 primeiro).
        # Máquina sem IPv6: cai para só IPv4 em vez de não subir.
        import socket
        try:
            socket.socket(socket.AF_INET6, socket.SOCK_STREAM).close()
            onde = f'*:{porta}'
        except OSError:
            onde = f'0.0.0.0:{porta}'
        serve(app, listen=onde, threads=8, ident='Zelo')
