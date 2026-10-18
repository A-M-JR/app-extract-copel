"""
Memória das últimas tentativas por id_fatura (dados/memoria_tentativas.json).

No modo 24/7 o CRM pode continuar devolvendo a mesma fatura a cada consulta (senha errada,
fatura ainda não emitida...). Sem memória, o robô tentaria de novo a cada ciclo — gastando
captcha e arriscando BLOQUEAR a conta na COPEL. Aqui cada status tem um tempo de espera
antes de tentar de novo (config.CONTINUO_ESPERA_H).
"""
import json
from datetime import datetime, timedelta

import config

_ARQ = config.PASTA_DADOS / "memoria_tentativas.json"


def _carregar() -> dict:
    try:
        return json.loads(_ARQ.read_text(encoding="utf-8"))
    except Exception:
        return {}


def registrar(id_fatura, status_enum: str) -> None:
    if id_fatura is None:
        return
    mem = _carregar()
    mem[str(id_fatura)] = {"status": status_enum, "quando": datetime.now().isoformat(timespec="seconds")}
    corte = datetime.now() - timedelta(days=7)          # esquece o que tem mais de 7 dias
    mem = {k: v for k, v in mem.items() if datetime.fromisoformat(v["quando"]) > corte}
    try:
        _ARQ.parent.mkdir(parents=True, exist_ok=True)
        _ARQ.write_text(json.dumps(mem, indent=1), encoding="utf-8")
    except Exception:
        pass


def filtrar_pendentes(faturas: list[dict]) -> tuple[list[dict], list[tuple[dict, str]]]:
    """Separa (para_processar, puladas[(conta, motivo)]) conforme o tempo de espera."""
    esperas = getattr(config, "CONTINUO_ESPERA_H", {})
    padrao = esperas.get("OUTROS", 1)
    mem = _carregar()
    agora = datetime.now()
    ok, puladas = [], []
    for f in faturas:
        m = mem.get(str(f.get("id_fatura")))
        if m:
            horas = esperas.get(m["status"], padrao)
            libera = datetime.fromisoformat(m["quando"]) + timedelta(hours=horas)
            if agora < libera:
                puladas.append((f, f"{m['status']} às {m['quando'][11:16]} — "
                                   f"tenta de novo após {libera:%d/%m %H:%M}"))
                continue
        ok.append(f)
    return ok, puladas
