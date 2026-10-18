"""
Start único do robô COPEL.

Sobe o servidor YOLO do captcha-solver (se ainda não estiver no ar), espera ele
ficar pronto e roda o robô. Você só passa quantas faturas processar naquele momento.

Uso (via rodar.bat):
    rodar 10               -> processa as 10 primeiras faturas e manda pro CRM
    rodar                  -> processa TODAS
    rodar 10 --sem-enviar  -> baixa mas NÃO manda pro CRM (ensaio)
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

import _caminhos  # noqa: F401  (subpastas de robo/)
import config

try:   # console do Windows costuma ser cp1252 -> evita � no log
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_DIR = Path(getattr(config, "CAPTCHA_SOLVER_DIR", ""))
_SERVER = _DIR / "server" / "server.py"


def _python_servidor() -> str:
    """Python que roda o servidor de visão (precisa de Torch/YOLO): prefere a venv
    unificada (.venv do robô, no NUC); senão a venv do captcha-solver (dev)."""
    for c in (Path(config.RAIZ) / ".venv" / "Scripts" / "python.exe",
              _DIR / "venv" / "Scripts" / "python.exe"):
        if c.exists():
            return str(c)
    return sys.executable


def _servidor_no_ar() -> bool:
    try:
        return requests.get(config.CAPTCHA_SERVIDOR, timeout=2).ok
    except Exception:
        return False


def garantir_servidor(silencioso=False):
    """Garante o servidor YOLO no ar (janela própria; ou oculto no modo silencioso)."""
    if not getattr(config, "CAPTCHA_AUTO", True):
        return  # captcha manual: não precisa do servidor
    if _servidor_no_ar():
        print("[start] servidor YOLO já está no ar.")
        return
    if not _SERVER.exists():
        print(f"[start] AVISO: não achei o servidor do captcha em {_DIR}")
        print("        Ajuste CAPTCHA_SOLVER_DIR no config.py (ou suba o servidor na mão).")
        return
    print("[start] iniciando o servidor YOLO (carrega o modelo, ~20s)...")
    flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0) if silencioso
             else getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
    subprocess.Popen([_python_servidor(), str(_SERVER)], cwd=str(_DIR), creationflags=flags)
    for _ in range(90):
        if _servidor_no_ar():
            print("[start] servidor pronto.\n")
            return
        time.sleep(1)
    print("[start] AVISO: o servidor não respondeu a tempo; seguindo mesmo assim.\n")


def _travar_execucao(conc: str):
    """Não deixa 2 execuções brigarem pelo MESMO navegador (painel x modo 24/7).
    COPEL usa o Chrome do robô (compartilhado) -> 1 por vez. RGE/CELESC abrem navegador
    próprio -> cada uma tem sua trava e podem rodar AO MESMO TEMPO que a COPEL.
    A trava some sozinha quando o processo termina."""
    import msvcrt
    from concessionarias import usa_captcha
    recurso = "chrome_robo" if (usa_captcha(conc) and getattr(config, "MODO_NAVEGADOR", "") == "cdp") else conc
    p = Path(config.PASTA_DADOS) / f"execucao_{recurso}.lock"
    p.parent.mkdir(parents=True, exist_ok=True)
    fh = open(p, "a+")
    try:
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        print(f"[start] Já existe uma execução de {conc} em andamento (painel ou modo 24/7). "
              "Aguarde ela terminar.")
        print("RESUMO (0 UCs):  outra execução em andamento — tente de novo depois.")
        sys.exit(3)
    return fh


def main():
    if sys.argv[1:2] == ["chrome"]:          # abrir_chrome_robo.bat / botão do painel
        import runpy
        runpy.run_path(str(Path(config.ROBO) / "nucleo" / "navegador_cdp.py"), run_name="__main__")
        return
    import captura_log
    captura_log.ligar()           # guarda o log desta execução pro relatório HTML
    try:                          # apaga prints/logs/relatórios velhos e caches (1x a cada 6h)
        import limpeza
        limpeza.limpar()
    except Exception as e:
        print(f"[limpeza] aviso: {type(e).__name__}: {e}")
    args = sys.argv[1:]
    fonte = "api"
    if args and args[0] in ("api", "plan"):
        fonte, args = args[0], args[1:]
    conc = "COPEL"
    if "--conc" in args:
        i = args.index("--conc")
        if i + 1 < len(args):
            conc = args[i + 1]
        del args[i:i + 2]
    silencioso = "--silencioso" in args
    args = [a for a in args if a != "--silencioso"]
    if "--ignorar-pausa" in args:          # painel: "rodar mesmo assim?"
        os.environ["ROBO_IGNORAR_PAUSA"] = "1"
        args = [a for a in args if a != "--ignorar-pausa"]
    enviar = "--sem-enviar" not in args
    args = [a for a in args if a != "--sem-enviar"]
    limite = int(args[0]) if args and args[0].isdigit() else 0
    _trava = _travar_execucao(conc)   # mantém a referência viva até o fim

    from concessionarias import usa_captcha
    if usa_captcha(conc):
        if getattr(config, "MODO_NAVEGADOR", "launch") == "cdp":
            import navegador_cdp
            navegador_cdp.garantir_chrome()     # Chrome do robô (com Buster) aberto e reaproveitado
        if getattr(config, "CAPTCHA_METODO", "dom") == "buster":
            print("[start] captcha pelo Buster — não preciso do servidor YOLO/áudio.")
        else:
            garantir_servidor(silencioso=silencioso)
    else:
        print(f"[start] {conc}: login sem captcha — não preciso do servidor YOLO.")
    if fonte == "plan":
        from main import executar_planilha
        executar_planilha(limite=limite, concessionaria=conc)
    else:
        from main import executar
        executar(headless=False, limite=limite, enviar=enviar, concessionaria=conc)


if __name__ == "__main__":
    main()
