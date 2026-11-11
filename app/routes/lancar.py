from flask import Blueprint, render_template
from app.auth import exige
lancar_bp = Blueprint('lancar', __name__)


@lancar_bp.route('/lancar')
@exige('ver')
def grade():
    return render_template('erro.html', titulo='Em construção', texto='Esta tela chega no próximo passo.')


@lancar_bp.route('/lancar/pessoa')
@exige('ver')
def pessoa():
    return render_template('erro.html', titulo='Em construção', texto='Esta tela chega no próximo passo.')
