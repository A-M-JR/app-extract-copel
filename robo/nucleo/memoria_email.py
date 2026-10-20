"""
Memória do que já foi enviado pela FONTE DE E-MAIL (dados/memoria_email.json).

No ciclo 24/7 as mesmas faturas ficam chegando na caixa; sem memória, o robô baixaria
e reenviaria o mesmo PDF a cada volta. Aqui cada fatura (alias + matrícula + mês) guarda
o resultado do último envio e um tempo de espera antes de mexer nela de novo.

(O endpoint do CRM também é idempotente — responde DUPLICADA —, isto é só pra não
gastar download/POST à toa.)
"""
import json
from datetime import datetime, timedelta

import config

_ARQ = config.PASTA_DADOS / "memoria_email.json"

# horas de espera antes de processar de novo a MESMA fatura, por resultado do último envio
_ESPERA_H = {
    "OK":            72,   # já foi lida/gravada no CRM — não reenvia
    "DUPLICADA":     72,   # o CRM já tinha a leitura
    "NAO_ENCONTRADO": 6,   # ainda não há título/contrato — tenta de novo mais tarde
    "ERRO":           1,   # erro de validação/processamento
    "SEM_RESPOSTA":   1,   # POST não voltou com retorno pra essa fatura
}


def chave(alias, matricula, mes_ref) -> str:
    return f"{str(alias).upper()}:{matricula}:{mes_ref}"


def _carregar() -> dict:
    try:
        return json.loads(_ARQ.read_text(encoding="utf-8"))
    except Exception:
        return {}


def registrar(ch: str, status: str) -> None:
    mem = _carregar()
    mem[ch] = {"status": status, "quando": datetime.now().isoformat(timespec="seconds")}
    corte = datetime.now() - timedelta(days=30)                 # esquece > 30 dias
    mem = {k: v for k, v in mem.items()
           if datetime.fromisoformat(v["quando"]) > corte}
    try:
        _ARQ.parent.mkdir(parents=True, exist_ok=True)
        _ARQ.write_text(json.dumps(mem, indent=1, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def em_espera(ch: str) -> bool:
    """True se essa fatura foi mexida há pouco e ainda está no tempo de espera."""
    m = _carregar().get(ch)
    if not m:
        return False
    horas = _ESPERA_H.get(m["status"], 1)
    return datetime.now() < datetime.fromisoformat(m["quando"]) + timedelta(hours=horas)
