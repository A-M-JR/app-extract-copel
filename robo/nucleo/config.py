"""
Configurações centrais do robô de faturas da COPEL.

Tudo que você pode querer ajustar (URLs, pastas, tempos de espera, tentativas)
fica aqui, num lugar só.
"""
from pathlib import Path
import os
import re

# Raiz do projeto (a pasta onde este arquivo está)
RAIZ = Path(__file__).resolve().parents[2]      # extract_copel/ (config.py fica em robo/nucleo)
ROBO = RAIZ / "robo"                             # scripts do robô

# Config editável pelo painel (config_local.json) — sobrepõe URL/token da API.
import json as _json
def _cfg_local() -> dict:
    p = RAIZ / "config_local.json"
    if p.exists():
        try:
            return _json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}
_LOCAL = _cfg_local()
from segredos import revelar   # token/senhas ficam criptografados no config_local.json

NOME_PASTA_EXTRACAO = "Extração-copel"


def _area_trabalho() -> Path:
    """Descobre a Área de Trabalho do usuário (funciona em outra máquina / OneDrive)."""
    home = Path.home()
    candidatos = [
        home / "Desktop",
        home / "Área de Trabalho",
        home / "OneDrive" / "Desktop",
        home / "OneDrive" / "Área de Trabalho",
    ]
    for pai in home.glob("OneDrive*"):
        candidatos.extend((pai / "Desktop", pai / "Área de Trabalho"))
    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        base = Path(userprofile)
        candidatos.extend((base / "Desktop", base / "Área de Trabalho"))
    visto: set[Path] = set()
    for caminho in candidatos:
        if caminho in visto:
            continue
        visto.add(caminho)
        if caminho.is_dir():
            return caminho
    destino = home / "Desktop"
    destino.mkdir(parents=True, exist_ok=True)
    return destino


# --- Arquivos de entrada / saída ------------------------------------------
PLANILHA_CONTAS   = RAIZ / "contas.xlsx"          # entrada (fica na pasta do robô)
PASTA_DADOS       = RAIZ / "dados"
PASTA_DIAGNOSTICO = PASTA_DADOS / "diagnostico"   # dumps de DOM/print pra ajustar seletores
PASTA_EXTRACAO    = _area_trabalho() / NOME_PASTA_EXTRACAO
PASTA_FATURAS     = PASTA_EXTRACAO / "faturas"    # PDFs baixados
PASTA_SESSOES     = PASTA_DADOS / "sessoes"       # perfil do navegador por login
PASTA_SCREENSHOTS = PASTA_DADOS / "erros"         # prints de tela quando dá erro
PASTA_RESULTADOS  = PASTA_EXTRACAO                # relatórios .xlsx (raiz da extração)

# --- Rotina por PLANILHA (startplan): 1 login único + contas.xlsx ----------
# Aqui vai o acesso ÚNICO da rotina por planilha. Os dados das UCs (nome/uc/mês)
# você alimenta no contas.xlsx. (O modo API não usa isto — lá o login vem por fatura.)
PLAN_LOGIN = _LOCAL.get("plan_login", "")                 # painel > Conexão CRM
PLAN_SENHA = revelar(_LOCAL.get("plan_senha", ""))        # criptografada (DPAPI)

# --- COPEL / AVA (Agência Virtual de Atendimento) -------------------------
URL_LOGIN      = "https://www.copel.com/avaweb/paginaLogin/login.jsf"
URL_BASE       = "https://www.copel.com/avaweb/"
URL_SELECAO_UC    = URL_BASE + "paginas/listarUcsDoc.jsf"
URL_SEGUNDA_VIA   = URL_BASE + "paginas/segundaViaFatura.jsf"
URL_TODOS_SERVICOS = URL_BASE + "paginas/todosServicos.jsf"

# --- RGE / CPFL (Rio Grande Energia) — login Azure AD B2C (e-mail + senha) ---
URL_LOGIN_RGE = (
    "https://cpflb2cprd.b2clogin.com/cpflb2cprd.onmicrosoft.com/"
    "b2c_1a_signup_signin_mfa_front/oauth2/v2.0/authorize"
    "?p=B2C_1A_SIGNUP_SIGNIN_MFA_FRONT&client_id=17d5831d-6741-4670-8085-d1d34e37aec1"
    "&nonce=defaultNonce&redirect_uri=https%3A%2F%2Fwww.cpfl.com.br%2Fb2c-auth%2Freceive-token"
    "&scope=17d5831d-6741-4670-8085-d1d34e37aec1%20offline_access"
    "&response_type=code&prompt=login&response_mode=query"
)
URL_HOME_RGE = "https://www.cpfl.com.br/agencia-virtual/area-cliente"

# --- CELESC (Santa Catarina) — portal novo "Minha Celesc" (e-mail/CPF + senha, SEM captcha) ---
# Login em 2 passos: abre a tela -> clica "Entrar com e-mail" -> preenche e-mail/senha -> "Entrar".
URL_LOGIN_CELESC = "https://conecte.celesc.com.br/autenticacao/login"

# --- API de faturas (fonte de trabalho: login/senha/UC/mês por fatura) -----
# A base e o token podem vir por variável de ambiente (recomendado p/ o token):
#   setx API_BASE_URL   "https://app.suaempresa.com.br"
#   setx PCRM_API_TOKEN "<token>"
API_BASE_URL         = _LOCAL.get("api_base_url") or os.environ.get("API_BASE_URL", "http://localhost/plataforma-crm")
API_ROTA_PREPARACAO  = "/api/v1/invoices/preparation"            # GET (busca as faturas)
API_ROTA_READINGS    = "/api/v1/invoices/preparation/readings"   # POST (devolve o resultado)
# fonte por e-mail: POST por CHAVES (matrícula/uc_aneel), o CRM acha/gera o título.
# escopo do token: invoices:readings:write (e ucs:holder:read p/ o titular/senha do PDF).
API_ROTA_EMAIL_READINGS = "/api/v1/invoices/readings"
API_ROTA_TITULAR        = "/api/v1/ucs/titular"                   # GET (titular p/ senha do PDF)
API_ROTA_USINAS      = "/api/v1/farms/readings"                  # GET (fila usinas) e POST (retorno) — mesma URL
API_TOKEN            = revelar(_LOCAL.get("api_token", "")) or os.environ.get("PCRM_API_TOKEN", "")
CONCESSIONARIA_ALIAS = "CDI"     # COPEL DISTRIBUIDORA (alias 'CDI' no CRM). None = todas
API_TIMEOUT_S        = 30

# --- Fonte por E-MAIL (Microsoft Graph, app-only / Mail.Read) --------------
# Lê as caixas compartilhadas do M365 e baixa os PDFs de fatura anexados.
# tenant/client NÃO são segredo (ficam aqui como padrão). O SEGREDO nunca fica
# no código: vem do painel (criptografado DPAPI em config_local.json) ou da env
# GRAPH_SECRET. Sugestão: rotacionar o segredo no Entra após ligar tudo.
EMAIL_GRAPH_TENANT = (_LOCAL.get("email_tenant") or os.environ.get("GRAPH_TENANT")
                      or "7eca1a0f-7331-4254-9e11-17e16ac1de73")
EMAIL_GRAPH_CLIENT = (_LOCAL.get("email_client") or os.environ.get("GRAPH_CLIENT")
                      or "654ddff4-1e38-420d-86b3-8950dcd0e446")
EMAIL_GRAPH_SECRET = revelar(_LOCAL.get("email_secret", "")) or os.environ.get("GRAPH_SECRET", "")
# caixas a ler (as 2 liberadas; faturas.energia@ilumisol e matriz@tangisa entram
# quando o infra liberar o 403 da Application Access Policy)
EMAIL_CAIXAS = _LOCAL.get("email_caixas") or [
    "lider@tangisa.com.br",
    "matriz@tangisa.com.br",
    "administrativo@tangisa.com.br",
    "faturas.energia@ilumisol.com.br",
]
EMAIL_DIAS = 90                  # janela de busca (dias) na Caixa de Entrada
# PDFs em base64 são pesados: 50 por POST estoura o post_max_size/timeout do PHP.
# Mandar poucos por vez (cada PDF ~0,8 MB -> ~1 MB em base64).
EMAIL_LOTE       = 5             # faturas (com PDF) por POST no endpoint de e-mail
EMAIL_TIMEOUT_S  = 180           # timeout do POST (upload de vários PDFs demora)
# domínios/remetentes que mandam fatura (p/ filtrar o que é fatura do resto)
EMAIL_REMETENTES_FATURA = ["energisa.com.br", "copel.com", "celesc.com.br", "enel.com"]
# aliases do CRM cujas faturas chegam por E-MAIL (não por portal). EMS/EMT prontos.
EMAIL_ALIASES = ["EMS", "EMT"]

# --- Navegador ------------------------------------------------------------
# Usa o Google Chrome já instalado na máquina (não baixa o Chromium do Playwright).
# Alternativas: "msedge" (Microsoft Edge) ou None (usa o Chromium do Playwright).
CANAL_NAVEGADOR   = "chrome"
# False = navegador VISÍVEL. Precisa ficar visível pra você resolver o captcha na mão.
HEADLESS          = False
# "cdp"    = controla o Chrome NORMAL do robô (perfil dados/chrome-robo, COM as extensões
#            instaladas pela Web Store, ex.: Buster). O Chrome fica aberto entre os logins.
#            1ª vez: rode abrir_chrome_robo.bat e instale o Buster nessa janela.
# "launch" = modo antigo (Playwright abre um Chrome de automação por login, sem extensões).
MODO_NAVEGADOR    = "cdp"
CDP_PORTA         = 9222
PERFIL_CHROME_CDP = str(RAIZ / "dados" / "chrome-robo")
CHROME_EXE        = ""        # vazio = acha sozinho (Program Files / LocalAppData)

# --- Captcha ---------------------------------------------------------------
# O reCAPTCHA é resolvido pelo PRÓPRIO robô, no DOM (captcha_dom.py), pelo ÁUDIO: baixa o
# mp3 do desafio e manda pro servidor local (faster-whisper transcreve) — MESMA ideia do
# Buster, mas com o nosso whisper. Suba o servidor antes (o start.py já faz isso quando o
# método é "dom"):  captcha-solver\iniciar_servidor.bat   (fica em http://127.0.0.1:5000)
CAPTCHA_AUTO         = True                       # False = resolver na mão
# Qual solver usar quando CAPTCHA_AUTO=True:
#   "buster" = clica no botão da extensão Buster dentro do desafio (exige MODO_NAVEGADOR="cdp") — ATIVO
#   "dom"    = solver próprio (captcha_dom.py: áudio faster-whisper no servidor local) — PRONTO,
#              reservado pra quando o Buster parar. Trocar aqui (ou no painel: aba Configurações)
#              reativa; o start.py sobe o servidor sozinho. Precisa da pasta irmã captcha-solver.
CAPTCHA_METODO       = "buster"
CAPTCHA_BUSTER_TIMEOUT_S = 120                    # orçamento do Buster por login
CAPTCHA_AUDIO        = True                        # modo "dom": resolve pelo ÁUDIO (faster-whisper, grátis/local)
CAPTCHA_SERVIDOR     = "http://127.0.0.1:5000/"   # servidor local do captcha (faster-whisper) — usado no modo "dom"
CAPTCHA_SOLVER_DIR   = os.environ.get("CAPTCHA_SOLVER_DIR", str(RAIZ.parent / "captcha-solver"))  # pasta irmã (portável)
EXTENSAO_CAPTCHA     = ""      # não usado (extensão bloqueada pelo Chrome 150)
STEALTH              = True    # reduz sinais de automação (navigator.webdriver etc.)
PAUSA_ENTRE_LOGINS_S = 0       # pausa entre logins (concessionária SEM captcha, ex.: RGE)
# concessionária COM captcha (COPEL) sofre rate-limit ("Ocorreu um erro inesperado. Tente
# novamente mais tarde!!") ao logar muitas vezes seguidas do mesmo IP -> espaça os logins.
PAUSA_ENTRE_LOGINS_CAPTCHA_S = 10
# Google bloqueou o captcha ("Try again later") -> pausa a concessionária por X minutos
PAUSA_CAPTCHA_BLOQUEADO_MIN  = 45
TIMEOUT_MS        = 45_000    # espera padrão por elementos (45s)
# Tempo esperando o login concluir. No AUTOMÁTICO o solver de captcha já tem orçamento
# próprio (~240s) e roda antes desta espera -> 90s bastam (e o retry de login em erro
# transitório dispara rápido). No MANUAL, 5 min pra um humano resolver o captcha.
TIMEOUT_LOGIN_MS  = 90_000 if CAPTCHA_AUTO else 300_000
# quantas vezes re-tentar o login em erro TRANSITÓRIO (ex.: COPEL "erro inesperado") e a
# pausa entre as tentativas (reabre o navegador limpo e refaz login/senha/captcha).
MAX_TENTATIVAS_LOGIN = 3
PAUSA_RETRY_LOGIN_S  = 5
ESPERA_POS_NAVEGACAO_MS = 3_500   # pausa extra após troca de tela (PrimeFaces)
ESPERA_POS_AJAX_MS      = 2_000   # pausa extra após clique AJAX
ESPERA_FILTRO_UC_MS     = 18_000  # tempo máx. esperando filtro da UC na tabela

# --- Robustez -------------------------------------------------------------
MAX_TENTATIVAS            = 3   # tentativas por unidade antes de marcar como FALHA
ESPERA_ENTRE_TENTATIVAS  = 3   # segundos (base do backoff: 3s, 6s, 9s...)

# Vira True depois que a gente confirmar juntos os seletores da 2ª via
# (via 'python main.py descobrir'). Enquanto False, o download é marcado como
# pendente no relatório em vez de dar um erro cru.
FLUXO_FATURA_CONFIRMADO  = True


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def sanitizar(texto: str) -> str:
    """Transforma um documento/nome em algo seguro pra usar como nome de pasta/arquivo."""
    return re.sub(r"[^0-9A-Za-z]+", "_", str(texto)).strip("_") or "sem_nome"


def pasta_sessao(documento: str) -> Path:
    """Pasta do perfil do navegador para um login (guarda cookies/sessão)."""
    return PASTA_SESSOES / sanitizar(documento)


def pasta_faturas_de(concessionaria: str) -> Path:
    """Subpasta de faturas por concessionária (ex.: faturas/RGE), pra não misturar.
    Cria se não existir. main.executar/executar_planilha reatribuem PASTA_FATURAS a
    isto no início do run — os bots salvam em config.PASTA_FATURAS (não mexe no bot)."""
    p = PASTA_EXTRACAO / "faturas" / sanitizar(concessionaria)
    p.mkdir(parents=True, exist_ok=True)
    return p


def garantir_pastas() -> None:
    """Cria todas as pastas de trabalho se ainda não existirem."""
    for p in (PASTA_DADOS, PASTA_EXTRACAO, PASTA_FATURAS, PASTA_SESSOES, PASTA_SCREENSHOTS,
              PASTA_DIAGNOSTICO):
        p.mkdir(parents=True, exist_ok=True)


# cria as pastas assim que o config é importado
garantir_pastas()


# --- Modo 24/7 (rodar_24h.py) ----------------------------------------------
CONTINUO_CONCESSIONARIAS   = ["COPEL", "RGE", "CELESC"]   # quais rodar a cada ciclo (painel > Configurações)
CONTINUO_EMAIL             = True        # roda também a fonte por e-mail (Energisa) a cada ciclo
CONTINUO_EMAIL_TUDO        = True        # modo "manda tudo" (push puro) no 24/7; False = só pendentes
CONTINUO_PARALELO          = True        # roda as concessionárias ao mesmo tempo (cada uma no seu navegador)
CONTINUO_INTERVALO_MIN     = 30          # de quanto em quanto tempo consulta o CRM
CONTINUO_HORA_INICIO       = 0           # janela de funcionamento (0–24 = o dia todo)
CONTINUO_HORA_FIM          = 24
CONTINUO_ENVIAR_CRM        = True        # False = ensaio (não devolve pro CRM)
CONTINUO_TIMEOUT_CICLO_MIN = 360         # ciclo travado há mais que isso é encerrado à força
# horas de espera antes de tentar de novo a MESMA fatura, por status do último resultado
CONTINUO_ESPERA_H = {
    "COMPLETE":           24,   # já foi entregue — evita baixar 2x se o CRM ainda listar
    "FALHA_LOGIN":        24,   # senha errada: insistir pode BLOQUEAR a conta
    "PDF_NAO_ENCONTRADO":  6,   # fatura ainda não emitida
    "DADOS_INVALIDOS":    12,   # sem UC / mês inválido no CRM: espera alguém corrigir o cadastro
    "OUTROS":              1,   # portal fora / erro de leitura
}


# --- Limpeza automática (nucleo/limpeza.py; roda no início de cada execução, 1x a cada 6h) ---
# dias que cada coisa fica guardada antes de ser apagada. 0 = NUNCA apaga.
LIMPEZA_DIAS = {
    "prints_erro":  30,    # dados/erros/*.png (prints de tela quando dá erro)
    "diagnostico":  30,    # dados/diagnostico/ (dumps de DOM pra ajustar seletores)
    "relatorios":   90,    # Extração-copel/resultado_*.xlsx e .html
    "logs_24h":     15,    # Extração-copel/logs/
    "sessoes":      30,    # dados/sessoes/<login> sem uso (perfis antigos do Chrome de automação)
    "faturas_pdf":   0,    # Extração-copel/faturas/ — PDFs entregues: NÃO apaga
    "cache_chrome": True,  # caches do Chrome do robô (inclui o modelo de IA de ~4 GB); só com ele fechado
}


# --------------------------------------------------------------------------
# Ajustes feitos no PAINEL (aba "Configurações") — gravados em config_local.json,
# chave "config". Sobrepõem os valores padrão acima. Só as chaves desta lista.
# --------------------------------------------------------------------------
AJUSTAVEIS_PAINEL = (
    "MODO_NAVEGADOR", "CAPTCHA_AUTO", "CAPTCHA_METODO", "CAPTCHA_BUSTER_TIMEOUT_S",
    "PAUSA_ENTRE_LOGINS_CAPTCHA_S", "PAUSA_ENTRE_LOGINS_S",
    "MAX_TENTATIVAS_LOGIN", "PAUSA_RETRY_LOGIN_S", "MAX_TENTATIVAS", "PAUSA_CAPTCHA_BLOQUEADO_MIN",
    "CONTINUO_INTERVALO_MIN", "CONTINUO_HORA_INICIO", "CONTINUO_HORA_FIM",
    "CONTINUO_CONCESSIONARIAS", "CONTINUO_EMAIL", "CONTINUO_EMAIL_TUDO",
)
for _k, _v in (_LOCAL.get("config") or {}).items():
    if _k in AJUSTAVEIS_PAINEL:
        globals()[_k] = _v
TIMEOUT_LOGIN_MS = 90_000 if CAPTCHA_AUTO else 300_000   # recalcula (depende do CAPTCHA_AUTO)
ARQUIVO_CONSULTA_CRM = PASTA_EXTRACAO / "consulta_crm.txt"   # sobrescrito a cada consulta
