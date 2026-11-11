# PokeHunt — codigo para revisao

Codigo do helper, dependencias locais, interface HTML e testes. Inclui o layout tecnico do cliente e uma fixture de teste com IDs normalizados.

Entrada principal: helper_app.py. Motor: helper_engine.py. Leitura e entradas: helper_native.py. Captura e filtro visual: helper_debug.py e helper_labels.py. Registro independente: helper_diagnostics.py.

Nao inclui Python portatil, configuracoes pessoais, tokens, capturas, logs ou historico das contas. Os arquivos foram copiados sem alterar o codigo original. Alguns caminhos absolutos e valores padrao precisam ser revistos antes de executar em outra instalacao.

Requer Windows e Python com tkinter. Dependencia externa: requirements.txt. Para executar testes, crie runtime/tmp antes de rodar: python -B -m unittest test_helper test_diagnostics -q.

O pacote destina-se a analise do codigo. Ele nao foi iniciado durante a preparacao.
