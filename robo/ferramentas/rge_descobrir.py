"""
Descoberta da RGE: loga (você resolve o MFA na janela, se aparecer), navega e salva
o DOM de cada tela em dados/diagnostico/descoberta_rge_*.txt — pra a gente fechar os seletores
da navegação (selecionar instalação, 2ª via, baixar).

Uso:  python rge_descobrir.py
(Precisa de pelo menos 1 fatura da RGE na API — ele pega o login/senha de lá.
 Não precisa do servidor YOLO: o login da RGE é Azure B2C, sem reCAPTCHA.)
"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import _caminhos  # noqa: E402,F401  (permite rodar este arquivo direto)

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from api_faturas import buscar_faturas
from rge_bot import RgeBot


def main():
    fs = buscar_faturas(alias="RGE")
    if not fs:
        print("Nenhuma fatura da RGE na API. Nada a descobrir.")
        return
    c = fs[0]
    print(f"[rge] login: {c['login']}  |  UC de exemplo: {c['uc']}")
    print("[rge] Vou logar. Se pedir código (MFA), digite na janela do navegador.\n")

    with RgeBot(c["login"], c["senha"], headless=False) as bot:
        try:
            bot.garantir_login()
        except Exception as e:
            print(f"[rge] login falhou: {type(e).__name__}: {e}")
            bot._dump("login_falhou")
            return
        bot._dump("apos_login")

        try:
            bot._ir_para_selecao_uc()
            bot._dump("selecao_instalacao")
            ok = bot._selecionar_instalacao(c)
            print(f"[rge] achou/selecionou a UC {c['uc']}? {ok}")
            bot._dump("apos_selecionar")
        except Exception as e:
            print(f"[rge] navegação: {type(e).__name__}: {e}")

        print("\n[rge] Agora navegue MANUALMENTE até 'Débito e segunda via' -> baixar a fatura.")
        print("[rge] Vou abrir o Inspector; quando estiver na tela da fatura, feche/continue.")
        try:
            bot.page.pause()
        except Exception:
            input("[rge] Inspector indisponível. Navegue e tecle ENTER aqui...")
        bot._dump("tela_fatura")
        print("[rge] Dumps salvos em dados/diagnostico/descoberta_rge_*.txt — me manda eles.")


if __name__ == "__main__":
    main()
