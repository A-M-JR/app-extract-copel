"""
Histórico de execuções (dados/historico.jsonl — uma linha JSON por execução).

Alimenta o resumo diário por e-mail, os alertas e a página de histórico
(Extração-copel/historico.html). Guarda só números e caminhos, nunca senha.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

import config

ARQ = Path(config.PASTA_DADOS) / "historico.jsonl"
GUARDA_DIAS = 180


def registrar(entrada: dict) -> None:
    entrada = {"quando": datetime.now().isoformat(timespec="seconds"), **entrada}
    try:
        ARQ.parent.mkdir(parents=True, exist_ok=True)
        with open(ARQ, "a", encoding="utf-8") as f:
            f.write(json.dumps(entrada, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        print(f"[historico] aviso: {e}")


def ler(dias: int = 30) -> list[dict]:
    if not ARQ.exists():
        return []
    corte = datetime.now() - timedelta(days=dias)
    saida = []
    for linha in ARQ.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(linha)
            if datetime.fromisoformat(e["quando"]) >= corte:
                saida.append(e)
        except Exception:
            pass
    return saida


def podar() -> None:
    """Mantém só os últimos GUARDA_DIAS dias (chamado pela limpeza)."""
    if not ARQ.exists():
        return
    manter = ler(GUARDA_DIAS)
    ARQ.write_text("".join(json.dumps(e, ensure_ascii=False, default=str) + "\n" for e in manter),
                   encoding="utf-8")


def resumo_execucao(itens: list[dict], meta: dict, relatorio: str = "") -> dict:
    """Monta a entrada do histórico a partir dos itens do RegistroResultados."""
    from resultado_log import CONCLUIDO, NAO_ENCONTRADO, FATURA_NAO_EMITIDA, ERRO, ADIADO
    total = len(itens)
    ok = sum(1 for i in itens if i["status"] == CONCLUIDO)
    pend = sum(1 for i in itens if i["status"] in (NAO_ENCONTRADO, FATURA_NAO_EMITIDA, ADIADO))
    adiadas = sum(1 for i in itens if i["status"] == ADIADO)
    erros = sum(1 for i in itens if i["status"] == ERRO)
    captcha = sum(1 for i in itens if i["status"] == ERRO and "captcha" in (i.get("mensagem") or "").lower())
    falha_login = sum(1 for i in itens if i["status"] == ERRO and "login" in (i.get("mensagem") or "").lower())
    crm_falha = sum(1 for i in itens if "falha" in ((i.get("_conta") or {}).get("_crm", "") or "").lower())
    inicio = meta.get("inicio") or datetime.now()
    return {
        "concessionaria": meta.get("concessionaria", ""), "fonte": meta.get("fonte", ""),
        "continuo": bool(meta.get("continuo")), "total": total, "ok": ok, "pendencias": pend,
        "erros": erros, "adiadas": adiadas, "falha_captcha": captcha, "falha_login": falha_login, "crm_falha": crm_falha,
        # taxa só sobre o que foi TENTADO (adiada por captcha bloqueado não conta como falha)
        "taxa": round(ok / (total - adiadas) * 100, 1) if total - adiadas else 0.0,
        "tentadas": total - adiadas,
        "duracao_s": round((datetime.now() - inicio).total_seconds()),
        "relatorio": relatorio,
    }
