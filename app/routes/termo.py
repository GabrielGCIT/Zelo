from flask import Blueprint, render_template
from app.auth import exige
termo_bp = Blueprint('termo', __name__)


@termo_bp.route('/termo')
@exige('ver')
def inicio():
    return render_template('erro.html', titulo='Em construção', texto='Esta tela chega no próximo passo.')
