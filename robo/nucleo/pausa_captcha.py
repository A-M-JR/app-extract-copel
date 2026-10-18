"""
Pausa da concessionária quando o Google bloqueia o captcha ("Try again later").

Insistir depois do bloqueio só aumenta o tempo dele. Então, ao detectar o bloqueio, o robô
para a concessionária por config.PAUSA_CAPTCHA_BLOQUEADO_MIN minutos: as faturas que
faltavam ficam pendentes (o próximo ciclo pega) e as outras concessionárias seguem normais.
Estado em dados/pausa_captcha.json.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

import config

ARQ = Path(config.PASTA_DADOS) / "pausa_captcha.json"


def _ler() -> dict:
    try:
        return json.loads(ARQ.read_text(encoding="utf-8"))
    except Exception:
        return {}


def ativar(conc: str, minutos: int | None = None, motivo: str = "") -> datetime:
    minutos = minutos if minutos is not None else int(getattr(config, "PAUSA_CAPTCHA_BLOQUEADO_MIN", 45))
    ate = datetime.now() + timedelta(minutes=minutos)
    d = _ler()
    d[conc] = {"ate": ate.isoformat(timespec="seconds"), "motivo": motivo,
               "desde": datetime.now().isoformat(timespec="seconds")}
    ARQ.parent.mkdir(parents=True, exist_ok=True)
    ARQ.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return ate


def ate(conc: str) -> datetime | None:
    """Até quando a concessionária está em pausa (None = liberada)."""
    item = _ler().get(conc)
    if not item:
        return None
    try:
        fim = datetime.fromisoformat(item["ate"])
    except Exception:
        return None
    return fim if fim > datetime.now() else None


def limpar(conc: str) -> None:
    d = _ler()
    if d.pop(conc, None) is not None:
        ARQ.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
