from flask import Blueprint, render_template
from app.auth import exige
estoque_bp = Blueprint('estoque', __name__)


@estoque_bp.route('/consumiveis')
@exige('ver')
def consumiveis():
    return render_template('erro.html', titulo='Em construção', texto='Esta tela chega no próximo passo.')
