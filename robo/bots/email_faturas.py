"""
Fonte por E-MAIL — orquestração.

Casa as faturas PENDENTES no CRM (aliases que chegam por e-mail: EMS/EMT…) com os
PDFs que chegaram nas caixas do M365, extrai os campos e devolve pro CRM — igual
à rotina de portal, só que a origem do PDF é o e-mail (sem login/captcha).

Chave de casamento (Energisa, validada em 20/10/2026):
  matrícula do nome do anexo (ex.: ENERGISAMS-Fat-Matricula-0000364402-10-2026.PDF
  -> 364402) está CONTIDA na UC do CRM (EMS = "10"+matrícula+dígito; EMT = "6"+…)
  E o mês bate E o alias bate. A UC do CORPO do e-mail é a UC ANEEL (uc_secondary).

Uso:
    python main.py email            (ENSAIO: casa e mostra, NÃO envia pro CRM)
    python main.py email --enviar   (devolve o resultado de cada fatura pro CRM)
    python main.py email --limite 1 (processa só a 1ª casada)
"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))

import re

import _caminhos  # noqa: E402,F401  (permite rodar este arquivo direto)

import config
import email_graph
import memoria_email
from api_faturas import buscar_faturas, montar_item_email, enviar_leituras_email
from fatura_pdf import extrair_dados
from planilha import normalizar_mes


def _norm(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _strip_html(h: str) -> str:
    t = re.sub(r"<[^>]+>", " ", h or "").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", t).strip()


def _uc_aneel_do_corpo(corpo: str) -> str:
    """UC completa (ANEEL) que aparece no corpo: 'Unidade Consumidora: 1.530.093.051-68'."""
    m = re.search(r"Unidade Consumidora:?\s*([\d][\d.\-/ ]{6,})", _strip_html(corpo), re.I)
    return re.sub(r"\D", "", m.group(1)) if m else ""


_RX_NOME = re.compile(r"Matricula-0*(\d+)-(\d{2})-(\d{4})", re.I)


def _matricula_mes_do_nome(nome: str):
    """(matrícula, mes, ano) a partir de 'ENERGISA..-Fat-Matricula-0001402094-10-2026.PDF'."""
    m = _RX_NOME.search(nome or "")
    if not m:
        return ("", None, None)
    return (m.group(1), int(m.group(2)), int(m.group(3)))


def _alias_do_remetente(de: str) -> str:
    """faturasonlineems..@energisa -> EMS ; ...emt..-> EMT."""
    m = re.search(r"faturasonline(em[st]|[a-z]{2,4})\d*@", de.lower())
    return (m.group(1).upper() if m else "")


def coletar_emails(caixas, dias):
    """Lista os anexos de fatura (nome -> matrícula/mês/alias) das caixas LEGÍVEIS.
    Não baixa o PDF ainda (só os nomes). Caixa que der erro (ex.: 403) é pulada."""
    itens = []
    for caixa in caixas:
        try:
            msgs = email_graph.listar_mensagens(caixa, desde_dias=dias)
        except Exception as e:
            print(f"   [email] caixa {caixa} indisponível ({type(e).__name__}) — pulando.")
            continue
        n = 0
        for m in msgs:
            de = m["de"].lower()
            if not any(d in de for d in config.EMAIL_REMETENTES_FATURA):
                continue
            alias = _alias_do_remetente(de)
            try:
                nomes = email_graph.nomes_anexos(caixa, m["id"])
            except Exception:
                nomes = []
            for nome in nomes:
                mat, mes, ano = _matricula_mes_do_nome(nome)
                if not mat:
                    continue
                itens.append({
                    "caixa": caixa, "msg_id": m["id"], "de": de, "assunto": m["assunto"],
                    "nome": nome, "matricula": mat, "mes_num": mes, "mes_ano": ano,
                    "alias": alias, "corpo": m["corpo"],
                })
                n += 1
        print(f"   [email] {caixa}: {n} anexo(s) de fatura.")
    return itens


def _casa(fatura, item) -> bool:
    """Casa uma fatura do CRM com um anexo de e-mail: matrícula CONTIDA na UC do CRM,
    mesmo mês e mesmo alias (quando o alias do remetente é conhecido)."""
    uc = _norm(fatura.get("uc"))
    mat = item["matricula"]
    if not (uc and mat and mat in uc):
        return False
    if (item["mes_num"], item["mes_ano"]) != (fatura.get("mes_num"), fatura.get("mes_ano")):
        return False
    al_email, al_crm = item.get("alias", ""), str(fatura.get("concessionaria") or "").upper()
    if al_email and al_crm and al_email != al_crm:
        return False
    return True


def _dados_para_crm(pdf: dict, uc_aneel: str, mes_ref: str) -> dict:
    """Monta o dict de leitura_fatura (só campos preenchidos entram no payload)."""
    return {
        "uc_secondary": uc_aneel,
        "ano_mes_referencia": mes_ref,
        "data_vencimento": pdf.get("data_vencimento", ""),
        "valor_total": pdf.get("valor_total", ""),
        "nota_fiscal": pdf.get("nota_fiscal", ""),
        "leitura_anterior": pdf.get("leitura_anterior", ""),
        "leitura_atual": pdf.get("leitura_atual", ""),
        "proxima_leitura": pdf.get("proxima_leitura", ""),
        "saldo_credito_todos_periodos": pdf.get("saldo_credito_todos_periodos", ""),
        "kwh_injetado": pdf.get("kwh_injetado", ""),
        "kwh_total_consumo": pdf.get("kwh_total_consumo", ""),
        # codigo_barras não vem do PDF (é QR/imagem) -> fica vazio.
    }


def executar(enviar=False, limite=0, caixas=None, dias=None):
    caixas = caixas or getattr(config, "EMAIL_CAIXAS", [])
    dias = dias or getattr(config, "EMAIL_DIAS", 35)
    aliases = [a.upper() for a in getattr(config, "EMAIL_ALIASES", [])]

    print("=" * 64)
    print(f"FONTE POR E-MAIL — {'ENVIO LIGADO' if enviar else 'ENSAIO (não envia)'}")
    print(f"  caixas: {', '.join(caixas)}")
    print(f"  aliases e-mail: {', '.join(aliases)}   janela: {dias} dia(s)")
    print("=" * 64)

    pend = [f for f in buscar_faturas(alias="")
            if str(f.get("concessionaria") or "").upper() in aliases]
    print(f"[crm] {len(pend)} fatura(s) pendente(s) desses aliases.")
    emails = coletar_emails(caixas, dias)
    print(f"[email] {len(emails)} anexo(s) de fatura coletado(s).\n")

    casados, sem_email = [], []
    usados = set()
    for f in pend:
        cand = next((e for e in emails
                     if id(e) not in usados and _casa(f, e)), None)
        if cand:
            usados.add(id(cand))
            casados.append((f, cand))
        else:
            sem_email.append(f)

    print(f"[match] {len(casados)} casada(s) | {len(sem_email)} sem e-mail ainda.")
    if enviar:   # dedup: não reprocessa o que já foi enviado há pouco (ciclo 24/7)
        espera = [(f, e) for f, e in casados
                  if memoria_email.em_espera(
                      memoria_email.chave(e["alias"], e["matricula"], f.get("mes_referencia", "")))]
        if espera:
            casados = [c for c in casados if c not in espera]
            print(f"[dedup] {len(espera)} já processada(s) há pouco — pulada(s) neste ciclo.")
    print()
    if limite and limite > 0:
        casados = casados[:limite]
        print(f"[limite] processando só as {len(casados)} primeira(s).\n")

    pasta = config.pasta_faturas_de("ENERGISA_EMAIL")
    envios = []   # (matricula, rotulo, item) p/ POST em lote no endpoint de e-mail
    for f, e in casados:
        rotulo = f"id={f['id_fatura']} UC={f['uc']} {f['mes_referencia']} ({e['alias']})"
        try:
            pdfs = email_graph.baixar_pdfs(e["caixa"], e["msg_id"])
            alvo = next((p for p in pdfs if p[0] == e["nome"]), pdfs[0] if pdfs else None)
            if not alvo:
                print(f"  [sem anexo] {rotulo}")
                continue
            caminho = email_graph.salvar(alvo[1], pasta, alvo[0])
            pdf = extrair_dados(caminho)
            uc_aneel = _uc_aneel_do_corpo(e["corpo"])
            print(f"  [lido] {rotulo}")
            print(f"       anexo={e['nome']}  uc_aneel(corpo)={uc_aneel or '-'}")
            print(f"       venc={pdf['data_vencimento']} valor={pdf['valor_total']} "
                  f"consumo={pdf['kwh_total_consumo']} inj={pdf['kwh_injetado'] or '-'} "
                  f"NF={pdf['nota_fiscal']}")
            if enviar:
                chaves = {
                    "concessionaria_alias": e["alias"],
                    "matricula": e["matricula"],
                    "uc_aneel": uc_aneel,
                    "ano_mes_referencia": f.get("mes_referencia", ""),
                }
                dados = _dados_para_crm(pdf, uc_aneel, f.get("mes_referencia", ""))
                ch = memoria_email.chave(e["alias"], e["matricula"], f.get("mes_referencia", ""))
                envios.append((ch, e["matricula"],
                               rotulo,
                               montar_item_email(chaves, dados, pdf_path=caminho)))
        except Exception as ex:
            print(f"  [ERRO] {rotulo}: {type(ex).__name__}: {ex}")

    enviados = 0
    if enviar and envios:
        print(f"\n[crm] POST {len(envios)} leitura(s) em {config.API_ROTA_EMAIL_READINGS} ...")
        try:
            res = enviar_leituras_email([it for _, _, _, it in envios])
        except Exception as ex:
            print(f"  [CRM ERRO no POST] {type(ex).__name__}: {ex}")
            res = []
        por_mat = {}
        for r in res:
            por_mat.setdefault(str(r.get("matricula", "")), r)
        for ch, mat, rotulo, _ in envios:
            r = por_mat.get(str(mat), {})
            ret = r.get("return") or "SEM_RESPOSTA"
            if ret == "OK":
                enviados += 1
            memoria_email.registrar(ch, ret)       # dedup: lembra o resultado deste envio
            print(f"  [CRM] {rotulo} -> {ret} "
                  f"id={r.get('id_fatura', '-')} titulo_gerado={r.get('titulo_gerado', '-')} "
                  f"{r.get('message', '')}".rstrip())

    print(f"\nRESUMO: {len(casados)} casada(s)"
          f"{f', {enviados} OK no CRM' if enviar else ' (ensaio, nada enviado)'}.")
    if sem_email:
        print(f"        {len(sem_email)} fatura(s) do CRM ainda sem e-mail correspondente "
              "(ficam pendentes p/ o próximo ciclo).")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Fonte por e-mail (Energisa) — casa CRM x e-mail")
    ap.add_argument("--enviar", action="store_true", help="devolve o resultado pro CRM")
    ap.add_argument("--limite", type=int, default=0)
    executar(**vars(ap.parse_args()))
