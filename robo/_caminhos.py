"""
Deixa os módulos das subpastas de robo/ importáveis pelo nome (import config, import rge_bot...).
Os pontos de entrada (start.py, main.py, painel.py, rodar_24h.py) importam isto primeiro.

    robo/nucleo      config, navegador, base dos bots, planilha, log, memória
    robo/bots        um robô por concessionária + leitor de PDF da fatura
    robo/captcha     Buster (atual) e solver próprio (desativado)
    robo/crm         cliente da API do CRM
    robo/relatorios  relatórios HTML (execução e consulta ao CRM)
    robo/ferramentas scripts de diagnóstico (descobrir seletores)
"""
import sys
from pathlib import Path

ROBO = Path(__file__).resolve().parent
for _sub in ("nucleo", "bots", "captcha", "crm", "relatorios", "ferramentas"):
    _p = str(ROBO / _sub)
    if _p not in sys.path:
        sys.path.insert(1, _p)
