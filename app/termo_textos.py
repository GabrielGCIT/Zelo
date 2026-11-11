"""Textos dos termos (os mesmos da aba Termo da planilha)."""
P_ENTREGA_1 = ('Fica V.Sa. comprometido a utilizá-los única e exclusivamente para desempenhar suas funções - conforme estabelecido em '
               'contrato de trabalho, internamente ou externamente, bem como tratar os referidos itens com o devido cuidado e cautela '
               'indispensáveis, visando a conservação, de forma a devolvê-los quando solicitado ou em caso de Rescisão de Contrato de Trabalho.')
P_ENTREGA_2 = ('Salientamos, outrossim, que V.Sa. deve comunicar à empresa, imediatamente, qualquer anomalia em relação ao seu funcionamento, '
               'dano, perda, furto, extravio etc., para que sejam tomadas as medidas cabíveis, ficando ciente de que, se qualquer destas '
               'ocorrências tiver sido ocasionada em razão do mau uso ou pela inobservância das cautelas que lhe foram transmitidas, V.Sa. '
               'será responsável pelos reparos que se façam necessários à normalização do funcionamento e/ou sua reposição, podendo o valor '
               'ser descontado em folha de pagamento. Estando os equipamentos em minha posse, estarei sujeito a inspeções sem prévio aviso.')
P_TEL_1 = ('Fica V.Sa. comprometido a utilizar os recursos acima exclusivamente para fins profissionais, sendo vedado o uso pessoal ou por '
           'terceiros. É de responsabilidade do colaborador zelar pela boa conservação e funcionamento do equipamento, devendo devolvê-lo em '
           'perfeitas condições sempre que solicitado ou em caso de desligamento da empresa. A empregadora poderá realizar o monitoramento de '
           'todos os dispositivos eletrônicos disponibilizados ao(à) empregado(a) para o exercício das suas funções, que devem ser utilizados '
           'somente para esses fins, em horário de trabalho, estando o(a) empregado(a) estritamente proibido(a) de usar respectivos '
           'dispositivos para fins pessoais, bem como proibido de conectar qualquer conta pessoal em qualquer dos aplicativos '
           'disponibilizados, reconhecendo, portanto, que não deve ter qualquer expectativa de privacidade quando do uso desses dispositivos.')
P_TEL_2 = ('Em casos de perda, roubo ou furto, o colaborador deverá registrar um Boletim de Ocorrência (B.O.) e abrir um chamado no Service '
           'Desk com o documento anexado. Em caso de comprovação de mau uso, negligência ou descumprimento das orientações, o colaborador '
           'poderá ser responsabilizado pelos custos de reparo, substituição ou ressarcimento dos itens. A utilização indevida dos recursos '
           'corporativos poderá acarretar sanções disciplinares, conforme as normas internas da empresa.')
P_EMP_1 = ('O equipamento é cedido em caráter temporário e deverá ser devolvido à área de TI até a data prevista acima, ou antes, quando '
           'solicitado ou em caso de desligamento. A renovação do prazo depende de nova autorização da TI. Fica V.Sa. comprometido a utilizá-lo '
           'única e exclusivamente para desempenhar suas funções, tratando-o com o devido cuidado e cautela indispensáveis à sua conservação.')
P_EMP_AC = ('O acessório é cedido em caráter temporário e deverá ser devolvido à área de TI até a data prevista acima, ou antes, quando '
            'solicitado ou em caso de desligamento. Fica V.Sa. comprometido a utilizá-lo única e exclusivamente para desempenhar suas funções, '
            'tratando-o com o devido cuidado e cautela indispensáveis à sua conservação.')
P_BYOD_1 = ('O chip ora disponibilizado deverá ser utilizado em equipamento de propriedade do colaborador, no âmbito da política BYOD '
            '(Bring Your Own Device), com finalidade exclusivamente corporativa. O uso deverá estar em conformidade com as normas internas da '
            'empresa, especialmente no que tange à segurança da informação e proteção de dados. O equipamento pessoal do colaborador deverá '
            'permanecer disponível para eventuais configurações exigidas pela área de Tecnologia da Informação, tais como instalação de '
            'software de gerenciamento corporativo e aplicação de políticas de segurança.')
P_BYOD_2 = ('Salientamos, outrossim, que V.Sa. deve comunicar à empresa, imediatamente, qualquer anomalia relacionada ao funcionamento do '
            'chip, dano, perda, furto, extravio etc., para que sejam tomadas as medidas cabíveis.')

TEXTOS = [
    # tipo, título, abertura, parágrafo 1, parágrafo 2, fecho, assinatura da empresa
    ('Entrega', 'TERMO DE CESSÃO, USO E RESPONSABILIDADE PELA GUARDA DE EQUIPAMENTO DE TI',
     'Servimo-nos do presente termo para formalizar a entrega dos seguintes equipamentos de TI:', P_ENTREGA_1, P_ENTREGA_2,
     'Solicitamos por seu ciente e de acordo na cópia do presente, firmando-nos.', '(empresa)'),
    ('Empréstimo', 'TERMO DE EMPRÉSTIMO TEMPORÁRIO DE EQUIPAMENTO DE TI',
     'Servimo-nos do presente termo para formalizar o empréstimo temporário do seguinte equipamento de TI:', P_EMP_1, P_ENTREGA_2,
     'Solicitamos por seu ciente e de acordo na cópia do presente, firmando-nos.', 'Ass. do Responsável pela Entrega'),
    ('Renovação de empréstimo', 'TERMO DE RENOVAÇÃO DE EMPRÉSTIMO TEMPORÁRIO DE EQUIPAMENTO DE TI',
     'Servimo-nos do presente termo para formalizar a renovação do empréstimo temporário do seguinte equipamento de TI, que permanece com V.Sa.:', P_EMP_1, P_ENTREGA_2,
     'Solicitamos por seu ciente e de acordo na cópia do presente, firmando-nos.', 'Ass. do Responsável pela Entrega'),
    ('Devolução de empréstimo', 'TERMO DE DEVOLUÇÃO DE EQUIPAMENTO EMPRESTADO',
     'Venho por meio deste formalizar a devolução do seguinte equipamento emprestado à Martin Brower Comércio, Transportes e Serviços Ltda.:',
     'Estado no recebimento:   (   ) em bom estado     (   ) com avarias: ______________________________________________',
     '', '', 'Ass. do Responsável pelo Recebimento'),
    ('Telefonia', 'TERMO DE CESSÃO E USO DO PLANO DE TELEFONIA MÓVEL CORPORATIVA',
     'Por meio deste termo, formalizamos a cessão dos seguintes recursos de telefonia móvel corporativa, de propriedade da empresa, para uso exclusivo em atividades profissionais:',
     P_TEL_1, P_TEL_2, 'Declaro estar ciente das condições acima e comprometo-me a cumprir integralmente as responsabilidades assumidas neste termo.',
     '(empresa)'),
    ('BYOD', 'TERMO DE CESSÃO E USO DO PLANO DE TELEFONIA MÓVEL CORPORATIVA – BYOD',
     'Servimo-nos do presente termo para formalizar a entrega do seguinte item:', P_BYOD_1, P_BYOD_2,
     'Solicitamos apor seu ciente e de acordo na cópia do presente, firmando-nos.', '(empresa)'),
    ('Devolução', 'TERMO DE DEVOLUÇÃO DE EQUIPAMENTO DE TI',
     'Venho por meio deste formalizar a devolução dos seguintes itens à Martin Brower Comércio, Transportes e Serviços Ltda.:',
     'Estado no recebimento:   (   ) em bom estado     (   ) com avarias: ______________________________________________',
     '', '', 'Ass. do Responsável pelo Recebimento'),
    ('Devolução telefonia', 'TERMO DE DEVOLUÇÃO DO PLANO DE TELEFONIA MÓVEL CORPORATIVA',
     'Venho por meio deste formalizar a devolução dos seguintes itens à Martin Brower Comércio, Transportes e Serviços Ltda.:',
     'Estado no recebimento:   (   ) em bom estado     (   ) com avarias: ______________________________________________',
     '', '', 'Ass. do Responsável pelo Recebimento'),
    ('Empréstimo de acessório', 'TERMO DE EMPRÉSTIMO TEMPORÁRIO DE ACESSÓRIO DE TI',
     'Servimo-nos do presente termo para formalizar o empréstimo temporário do seguinte acessório de TI:', P_EMP_AC, P_ENTREGA_2,
     'Solicitamos por seu ciente e de acordo na cópia do presente, firmando-nos.', 'Ass. do Responsável pela Entrega'),
    ('Devolução de acessório', 'TERMO DE DEVOLUÇÃO DE ACESSÓRIO EMPRESTADO',
     'Venho por meio deste formalizar a devolução do seguinte acessório emprestado à Martin Brower Comércio, Transportes e Serviços Ltda.:',
     'Estado no recebimento:   (   ) em bom estado     (   ) com avarias: ______________________________________________',
     '', '', 'Ass. do Responsável pelo Recebimento'),
    ('Sem termo', 'ESTA MOVIMENTAÇÃO NÃO PRECISA DE TERMO',
     'A linha foi entregue a um posto, modem ou equipamento, e não a uma pessoa. Se precisar de termo, escolha o tipo na célula L5.',
     '', '', '', '(empresa)'),
]
