"""
Credenciais do acesso ÚNICO da Rotina 1 (1 login / 1 senha para todas as UCs).

OBSOLETO: o login/senha da planilha agora ficam no painel (aba Conexão CRM),
criptografados no config_local.json. Só é usado se aquilo estiver vazio.
(Depois dá pra migrar isso pra variável de ambiente, se quiser mais segurança.)
"""

LOGIN = ""   # CPF/CNPJ ou usuário do acesso da Agência Virtual
SENHA = ""
