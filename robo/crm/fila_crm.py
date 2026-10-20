"""
Fila de reenvio pro CRM (dados/fila_crm/<id_fatura>.json).

Se o POST do resultado falhar (CRM fora do ar, timeout...), o resultado NÃO se perde:
fica guardado aqui (status + campos lidos + caminho do PDF) e é reenviado no começo da
próxima execução, antes de processar faturas novas.
"""
import json
from datetime import datetime
from pathlib import Path

import config

PASTA = Path(config.PASTA_DADOS) / "fila_crm"
DESISTE_APOS_DIAS = 15     # item que não consegue ser enviado por 15 dias é descartado (com aviso)


def guardar(id_fatura, status_enum: str, dados: dict | None, uc_aneel: str, pdf: str | None,
            erro: str = "", rota: str | None = None) -> None:
    if id_fatura is None:
        return
    PASTA.mkdir(parents=True, exist_ok=True)
    arq = PASTA / f"{id_fatura}.json"
    antigo = {}
    try:
        antigo = json.loads(arq.read_text(encoding="utf-8"))
    except Exception:
        pass
    arq.write_text(json.dumps({
        "id_fatura": id_fatura, "status": status_enum, "dados": dados or {},
        "uc_aneel": uc_aneel or "", "pdf": pdf or "",
        "rota": rota or "",   # rota do POST (usinas = farms/readings); vazio = títulos
        "criado": antigo.get("criado") or datetime.now().isoformat(timespec="seconds"),
        "tentativas": int(antigo.get("tentativas", 0)) + 1, "ultimo_erro": erro,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"   [fila CRM] id={id_fatura} guardado pra reenviar na próxima execução.")


def pendentes() -> list[Path]:
    return sorted(PASTA.glob("*.json")) if PASTA.exists() else []


def reenviar() -> tuple[int, int]:
    """Tenta reenviar tudo que está na fila. Devolve (enviados, ainda_pendentes)."""
    arqs = pendentes()
    if not arqs:
        return 0, 0
    from api_faturas import montar_item_resultado, enviar_resultados, STATUS_COMPLETE
    print(f"[fila CRM] {len(arqs)} resultado(s) pendente(s) de envio — reenviando...")
    ok = falhou = 0
    for arq in arqs:
        try:
            it = json.loads(arq.read_text(encoding="utf-8"))
        except Exception:
            arq.unlink(missing_ok=True)
            continue
        pdf = it.get("pdf") or None
        if it["status"] == STATUS_COMPLETE and pdf and not Path(pdf).exists():
            print(f"   [fila CRM] id={it['id_fatura']}: PDF sumiu ({pdf}) — descartado.")
            arq.unlink(missing_ok=True)
            continue
        rota = it.get("rota") or None   # usina = farms/readings; vazio = títulos
        try:
            item = montar_item_resultado(it["id_fatura"], it["status"], dados=it.get("dados"),
                                         uc_aneel=it.get("uc_aneel", ""), pdf_path=pdf)
            enviar_resultados([item], rota=rota)
            arq.unlink(missing_ok=True)
            ok += 1
            print(f"   [fila CRM] id={it['id_fatura']} {it['status']} reenviado [OK]")
        except Exception as e:
            falhou += 1
            idade = (datetime.now() - datetime.fromisoformat(it.get("criado"))).days
            if idade >= DESISTE_APOS_DIAS:
                print(f"   [fila CRM] id={it['id_fatura']}: {idade} dias sem conseguir enviar — descartado.")
                arq.unlink(missing_ok=True)
            else:
                guardar(it["id_fatura"], it["status"], it.get("dados"), it.get("uc_aneel"), pdf,
                        f"{type(e).__name__}: {e}", rota=rota)
    print(f"[fila CRM] reenviados: {ok} | ainda pendentes: {falhou}")
    return ok, falhou
