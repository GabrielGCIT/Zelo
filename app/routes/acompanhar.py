from flask import Blueprint, render_template
from app.auth import exige
acompanhar_bp = Blueprint('acompanhar', __name__)


@acompanhar_bp.route('/acompanhar')
@exige('ver')
def inicio():
    return render_template('erro.html', titulo='Em construção', texto='Esta tela chega no próximo passo.')
