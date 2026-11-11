from flask import Blueprint, render_template
from app.auth import exige
manutencao_bp = Blueprint('manutencao', __name__)


@manutencao_bp.route('/manutencao')
@exige('ver')
def inicio():
    return render_template('erro.html', titulo='Em construção', texto='Esta tela chega no próximo passo.')
