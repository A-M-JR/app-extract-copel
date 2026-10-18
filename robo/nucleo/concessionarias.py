"""
Registro das concessionárias suportadas.

Cada uma é uma "receita": qual alias ela tem na API (concessionaria_alias) e qual
classe de robô (bot) sabe navegar no portal dela. Pra ativar uma nova:
  1. crie o bot dela (ex.: rge_bot.RgeBot, herdando bot_base.BotBase),
  2. aponte "bot" aqui e vire "pronta": True.

IMPORTANTE: a COPEL (copel_bot.CopelBot) está BLINDADA — não mexa nela ao adicionar
outras. Cada concessionária vive no seu próprio arquivo.
"""

CONCESSIONARIAS = {
    "COPEL": {
        "label": "COPEL — Paraná", "alias_api": "CDI",
        "bot": ("copel_bot", "CopelBot"), "pronta": True,
        "usa_captcha": True,   # reCAPTCHA -> precisa do servidor YOLO
    },
    "RGE": {
        "label": "RGE — Rio Grande Energia", "alias_api": "RGE",
        "bot": ("rge_bot", "RgeBot"), "pronta": True,   # 1ª versão — testar com --limite 1
        "usa_captcha": False,  # login Azure B2C (e-mail+senha), sem captcha
    },
    "CELESC": {
        "label": "CELESC — Santa Catarina", "alias_api": "CLC",
        "bot": ("celesc_bot", "CelescBot"), "pronta": True,   # 1ª versão — testar com --limite 1
        "usa_captcha": False,  # portal novo "Minha Celesc" (e-mail/senha), sem captcha
    },
    # --- descobertas na API, ainda sem receita (aparecem como "em breve") ---
    "ENERGISA_MT": {"label": "Energisa — MT",          "alias_api": "EMT", "bot": None, "pronta": False},
    "ENERGISA_MS": {"label": "Energisa — MS",          "alias_api": "EMS", "bot": None, "pronta": False},
    "ENEL_CE":    {"label": "Enel — CE",               "alias_api": "ECE", "bot": None, "pronta": False},
    "CPFL_PAULISTA": {"label": "CPFL Paulista",        "alias_api": "CPP", "bot": None, "pronta": False},
    "NEOENERGIA_COELBA": {"label": "Neoenergia Coelba", "alias_api": "NCB", "bot": None, "pronta": False},
    "EQUATORIAL_MA": {"label": "Equatorial — MA",      "alias_api": "ETM", "bot": None, "pronta": False},
    "CEEE":       {"label": "CEEE-D — RS",             "alias_api": "CEQ", "bot": None, "pronta": False},
}


def get_info(nome: str) -> dict:
    return CONCESSIONARIAS[nome]


def get_bot(nome: str):
    """Importa e devolve a classe de robô da concessionária."""
    import importlib
    info = CONCESSIONARIAS[nome]
    if not info.get("bot"):
        raise RuntimeError(f"Concessionária {nome} ainda não tem robô implementado.")
    mod, cls = info["bot"]
    return getattr(importlib.import_module(mod), cls)


def usa_captcha(nome: str) -> bool:
    """True se o portal tem reCAPTCHA (precisa do servidor YOLO). Default True (seguro)."""
    return CONCESSIONARIAS.get(nome, {}).get("usa_captcha", True)
