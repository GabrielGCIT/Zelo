"""Comandos de administração do Zelo.

  python manage.py importar <planilha.xlsx> [--substituir]   importa a planilha de ativos
  python manage.py recalcular                                recalcula situação de itens e linhas
  python manage.py criar-usuario <email> <nome> <perfil>     cria usuário com senha provisória
"""
import getpass
import sys

from app import create_app, db

app = create_app()


def main(args):
    if not args:
        print(__doc__)
        return 1
    cmd = args[0]
    with app.app_context():
        if cmd == 'importar':
            from app.importar import importar
            importar(args[1], substituir='--substituir' in args)
        elif cmd == 'recalcular':
            from app.regras import recalcular_tudo
            recalcular_tudo()
            print('ok')
        elif cmd == 'criar-usuario':
            from app.auth import criar_usuario
            senha = getpass.getpass('Senha provisória: ')
            criar_usuario(args[2], args[1], senha, args[3] if len(args) > 3 else 'Operador', provisoria=True)
            print('Usuário criado. Ele troca a senha no primeiro login.')
        else:
            print(__doc__)
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
