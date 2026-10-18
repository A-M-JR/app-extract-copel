"""
Descoberta da CELESC: loga no portal "Minha Celesc" e abre o Inspector pra você navegar
até a 2ª via da fatura — salvando o DOM de cada tela em dados/diagnostico/descoberta_celesc_*.txt,
pra a gente fechar os seletores da navegação (achar a UC, baixar a 2ª via).

Uso:  python celesc_descobrir.py
(Pega o login/senha da 1ª fatura CELESC da API. Sem captcha, não precisa do servidor YOLO.)
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
from celesc_bot import CelescBot


def main():
    fs = buscar_faturas(alias="CLC")
    if not fs:
        print("Nenhuma fatura da CELESC (alias CLC) na API. Nada a descobrir.")
        return
    c = fs[0]
    print(f"[celesc] login: {c['login']}  |  UC de exemplo: {c['uc']}  |  mês: {c['mes_referencia']}")
    print("[celesc] Vou logar. Sem captcha; se pedir algo a mais, resolva na janela.\n")

    with CelescBot(c["login"], c["senha"], headless=False) as bot:
        try:
            bot.garantir_login()
            print("[celesc] LOGIN OK.")
        except Exception as e:
            print(f"[celesc] login falhou: {type(e).__name__}: {e}")
            bot._dump("login_falhou")
            return
        bot._dump("apos_login")

        print("\n[celesc] Agora navegue MANUALMENTE até a 2ª via da fatura:")
        print("  - ache a Unidade Consumidora / imóvel,")
        print("  - abra a 2ª via / débitos,")
        print("  - chegue na tela de baixar o PDF.")
        print("[celesc] Vou abrir o Inspector; quando terminar, feche/continue que eu dumpo a tela.")
        try:
            bot.page.pause()
        except Exception:
            input("[celesc] Inspector indisponível. Navegue e tecle ENTER aqui...")
        bot._dump("tela_2via")
        print("[celesc] Dumps salvos em dados/diagnostico/descoberta_celesc_*.txt — me manda eles + prints.")


if __name__ == "__main__":
    main()
