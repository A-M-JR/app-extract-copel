"""
Modo 24/7: fica rodando no NUC e, a cada X minutos, consulta o CRM e processa o que
estiver pendente — sem ninguém clicar em nada.

- Cada ciclo roda o start.py num processo SEPARADO (se travar/cair, o loop continua).
- Respeita a janela de horário e o intervalo (aba "Configurações" do painel; relê a cada
  ciclo, então mudar no painel vale sem reiniciar).
- Log diário em  Extração-copel\\logs\\24h_AAAA-MM-DD.log  (guarda 15 dias).
- Status atual em  Extração-copel\\status_24h.txt.
- Só 1 instância por vez (trava em dados\\rodar_24h.lock).

Ligar no boot: instalar_24h.bat (Agendador de Tarefas, ao fazer logon).
Rodar na mão:  python rodar_24h.py        (Ctrl+C pra parar)
"""
import importlib
import msvcrt
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import _caminhos  # noqa: F401  (subpastas de robo/)
import config

RAIZ = config.RAIZ
ROBO = config.ROBO
PASTA_LOGS = Path(config.PASTA_EXTRACAO) / "logs"
ARQ_STATUS = Path(config.PASTA_EXTRACAO) / "status_24h.txt"


def _log(msg: str):
    linha = f"[{datetime.now():%d/%m %H:%M:%S}] {msg}"
    try:
        print(linha, flush=True)
    except Exception:
        pass
    try:
        PASTA_LOGS.mkdir(parents=True, exist_ok=True)
        with open(PASTA_LOGS / f"24h_{datetime.now():%Y-%m-%d}.log", "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except Exception:
        pass


def _status(texto: str):
    try:
        ARQ_STATUS.write_text(f"{datetime.now():%d/%m/%Y %H:%M:%S}  {texto}\n", encoding="utf-8")
    except Exception:
        pass


def _limpar_logs_antigos(dias=15):
    limite = time.time() - dias * 86400
    for p in PASTA_LOGS.glob("24h_*.log"):
        try:
            if p.stat().st_mtime < limite:
                p.unlink()
        except Exception:
            pass


def _na_janela() -> bool:
    ini = int(getattr(config, "CONTINUO_HORA_INICIO", 0))
    fim = int(getattr(config, "CONTINUO_HORA_FIM", 24))
    h = datetime.now().hour
    return ini <= h < fim if ini <= fim else (h >= ini or h < fim)   # aceita virar a noite


def _python() -> str:
    """Python com console (não pythonw) pro filho — a saída vai pro log por pipe."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").exists():
        return str(exe.parent / "python.exe")
    return str(exe)


def _rodar_concessionaria(conc: str):
    cmd = [_python(), "-u", str(ROBO / "start.py"), "api", "0", "--conc", conc, "--silencioso"]
    if not getattr(config, "CONTINUO_ENVIAR_CRM", True):
        cmd.append("--sem-enviar")
    env = dict(os.environ, ROBO_CONTINUO="1", PYTHONIOENCODING="utf-8")
    limite_s = int(getattr(config, "CONTINUO_TIMEOUT_CICLO_MIN", 360)) * 60
    _log(f"--- {conc}: iniciando ciclo ---")
    _status(f"rodando {conc}...")
    proc = subprocess.Popen(cmd, cwd=str(RAIZ), env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace", bufsize=1,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    inicio = time.time()
    estourou = []

    def _matar():                      # vigia: mata o ciclo travado mesmo sem saída no log
        if proc.poll() is None:
            estourou.append(1)
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    vigia = threading.Timer(limite_s, _matar)
    vigia.daemon = True
    vigia.start()
    try:
        for linha in proc.stdout:
            _log(f"   [{conc}] {linha.rstrip()}")
    except Exception:
        pass
    vigia.cancel()
    if estourou:
        _log(f"!!! {conc}: passou de {limite_s // 60} min — ciclo encerrado à força (e o Chrome).")
    proc.wait()
    if estourou or proc.returncode not in (0, 3):    # 3 = outra execução em andamento (normal)
        try:
            import notificacao
            notificacao.alerta(f"ciclo_{conc}", f"Ciclo do 24/7 falhou ({conc})",
                               "Ciclo encerrado à força por passar do tempo limite." if estourou else
                               f"O ciclo terminou com código {proc.returncode}. Veja o log em Extração-copel\\logs.")
        except Exception:
            pass
    _log(f"--- {conc}: fim do ciclo (código {proc.returncode}, "
         f"{(time.time() - inicio) / 60:.1f} min) ---")


def _rodar_email():
    """Fonte por e-mail (Energisa): lê as caixas e manda as leituras pro CRM. Não usa
    navegador/captcha, então roda direto o main.py (sem a parafernália do start.py)."""
    cmd = [_python(), "-u", str(ROBO / "main.py"), "email"]
    if getattr(config, "CONTINUO_EMAIL_TUDO", True):
        cmd.append("--tudo")           # manda toda fatura do e-mail (push puro)
    if getattr(config, "CONTINUO_ENVIAR_CRM", True):
        cmd.append("--enviar")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    limite_s = int(getattr(config, "CONTINUO_TIMEOUT_CICLO_MIN", 360)) * 60
    _log("--- E-MAIL: iniciando ciclo ---")
    _status("rodando e-mail...")
    proc = subprocess.Popen(cmd, cwd=str(RAIZ), env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace", bufsize=1,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    estourou = []

    def _matar():
        if proc.poll() is None:
            estourou.append(1)
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    vigia = threading.Timer(limite_s, _matar)
    vigia.daemon = True
    vigia.start()
    try:
        for linha in proc.stdout:
            _log(f"   [email] {linha.rstrip()}")
    except Exception:
        pass
    vigia.cancel()
    proc.wait()
    if estourou:
        _log("!!! E-MAIL: passou do tempo limite — ciclo encerrado à força.")
    _log(f"--- E-MAIL: fim do ciclo (código {proc.returncode}) ---")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    trava_path = RAIZ / "dados" / "rodar_24h.lock"
    trava_path.parent.mkdir(parents=True, exist_ok=True)
    trava = open(trava_path, "a+")
    try:
        msvcrt.locking(trava.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        print("O modo 24/7 já está rodando nesta máquina.")
        return

    _log("=== MODO 24/7 LIGADO ===")
    while True:
        try:
            importlib.reload(config)          # pega mudanças feitas no painel
            _limpar_logs_antigos()
            intervalo = max(1, int(getattr(config, "CONTINUO_INTERVALO_MIN", 30)))
            if _na_janela():
                concs = list(getattr(config, "CONTINUO_CONCESSIONARIAS", ["COPEL"]))

                def _um(conc):
                    try:
                        _rodar_concessionaria(conc)
                    except Exception as e:
                        _log(f"!!! {conc}: erro no ciclo: {type(e).__name__}: {e}")

                if getattr(config, "CONTINUO_PARALELO", True) and len(concs) > 1:
                    # cada concessionária no seu processo e navegador, ao mesmo tempo
                    _status("rodando " + ", ".join(concs) + " (em paralelo)...")
                    fios = [threading.Thread(target=_um, args=(c,), daemon=True) for c in concs]
                    for t in fios:
                        t.start()
                    for t in fios:
                        t.join()
                else:
                    for conc in concs:
                        _um(conc)
                if getattr(config, "CONTINUO_EMAIL", True):
                    try:
                        _rodar_email()
                    except Exception as e:
                        _log(f"!!! E-MAIL: erro no ciclo: {type(e).__name__}: {e}")
            else:
                _log(f"fora da janela ({config.CONTINUO_HORA_INICIO}h–"
                     f"{config.CONTINUO_HORA_FIM}h) — aguardando.")
            try:                              # resumo diário por e-mail + alerta de disco
                import notificacao
                notificacao.verificar_disco()
                notificacao.resumo_diario_se_for_hora()
            except Exception as e:
                _log(f"!!! e-mail: {type(e).__name__}: {e}")
            prox = datetime.now() + timedelta(minutes=intervalo)
            _status(f"aguardando — próximo ciclo às {prox:%H:%M} (a cada {intervalo} min)")
            _log(f"próximo ciclo às {prox:%H:%M}")
            time.sleep(intervalo * 60)
        except KeyboardInterrupt:
            _log("=== MODO 24/7 DESLIGADO (Ctrl+C) ===")
            _status("desligado")
            return
        except Exception as e:                # nunca morre: loga e tenta de novo em 5 min
            _log(f"!!! erro inesperado no loop: {type(e).__name__}: {e}")
            time.sleep(300)


if __name__ == "__main__":
    main()
