"""
Parser da fatura (DANF3E) — extrai os campos de `leitura_fatura` do PDF.

Detecta a concessionária pelo próprio texto do PDF e roteia:
  - COPEL  -> _extrair_copel  (layout original, intocado)
  - RGE/CPFL -> _extrair_rge  (layout DANF3E da RGE)

Usa extract_words agrupado por linha (o extract_text embaralha os números;
agrupar por posição resolve isso).

Extrai: nota_fiscal, data_vencimento, valor_total, leitura_anterior, leitura_atual,
proxima_leitura, saldo_credito_todos_periodos, kwh_injetado, kwh_total_consumo,
+ debito_automatico. (codigo_barras NÃO vem do PDF — é imagem.)
"""
import re
from collections import defaultdict

import pdfplumber


def _linhas(page) -> list[str]:
    """Reconstrói as linhas visuais da página (ordena por y, depois por x)."""
    linhas = defaultdict(list)
    for w in page.extract_words():
        linhas[round(w["top"])].append((w["x0"], w["text"]))
    saida = []
    for top in sorted(linhas):
        partes = [t for _, t in sorted(linhas[top])]
        saida.append(" ".join(partes))
    return saida


def _busca(padrao: str, texto: str, grupo: int = 1) -> str:
    m = re.search(padrao, texto, re.I)
    return m.group(grupo).strip() if m else ""


def _num_br(s: str) -> float:
    """Número no formato BR -> float (valor absoluto). '-1.142'->1142.0 ; '-950,59'->950.59"""
    s = s.strip().replace(".", "").replace(",", ".")
    try:
        return abs(float(s))
    except ValueError:
        return 0.0


def _fmt_br(x: float) -> str:
    """float -> BR. 2551.59 -> '2.551,59' ; 148.33 -> '148,33'"""
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_kwh(x: float) -> str:
    """kWh é QUANTIDADE (não dinheiro) e vai pro CRM como NÚMERO PURO: sem ponto de milhar,
    decimal com ponto ('1416', '82.5'). O CRM lê o texto como número — '1.416' viraria 1,416."""
    if x == int(x):
        return str(int(x))
    return f"{x:.4f}".rstrip("0").rstrip(".")


def _vazio() -> dict:
    return {
        "nota_fiscal": "", "data_vencimento": "", "valor_total": "",
        "leitura_anterior": "", "leitura_atual": "", "proxima_leitura": "",
        "saldo_credito_todos_periodos": "", "kwh_injetado": "", "kwh_total_consumo": "",
    }


# --------------------------------------------------------------------------
# COPEL (layout original — NÃO mexer)
# --------------------------------------------------------------------------
def _extrair_copel(full: str) -> dict:
    dados = _vazio()

    # Nota fiscal: "NOTA FISCAL No. 228911916"
    dados["nota_fiscal"] = _busca(r"NOTA FISCAL\s*N[o°.\s]*?(\d{5,})", full)

    # Leituras: "24/03/2026 23/04/2026 30 22/05/2026" (anterior, atual, nº dias, próxima)
    m = re.search(
        r"(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+\d{1,3}\s+(\d{2}/\d{2}/\d{4})", full)
    if m:
        dados["leitura_anterior"] = m.group(1)
        dados["leitura_atual"] = m.group(2)
        dados["proxima_leitura"] = m.group(3)

    # Referência/venc/valor: "04/2026 15/05/2026 R$254,04"
    m = re.search(r"\b\d{2}/\d{4}\s+(\d{2}/\d{2}/\d{4})\s+R?\$?\s*([\d.]*\d,\d{2})", full)
    if m:
        dados["data_vencimento"] = m.group(1)
        dados["valor_total"] = m.group(2)

    # kWh injetado/consumo (GD): soma o valor ABSOLUTO das linhas "ENERGIA INJ ... TE ...".
    # TE e TUSD da MESMA referência são iguais -> conta só o TE (a TUSD é duplicata);
    # inclui "ENERGIA INJ. BAND. AMARELA TE".  Ex.: 459 + 1.142 + 950,59 = 2.551,59
    inj_total, achou_inj = 0.0, False
    for m in re.finditer(r"ENERGIA\s+INJ\.?.*?kWh\s+(-?[\d.]*\d(?:,\d+)?)", full, re.I):
        seg = m.group(0)
        if re.search(r"\bTUSD\b", seg, re.I):
            continue                      # TUSD = duplicata do TE -> ignora
        if not re.search(r"\bTE\b", seg, re.I):
            continue                      # só as linhas TE
        inj_total += _num_br(m.group(1))
        achou_inj = True

    # CONSUMO = SEMPRE a linha "ENERGIA ELET CONSUMO" (o consumo REAL — é DIFERENTE da
    # injeção; GD ou não). Parseia número BR pra não cortar no ponto de milhar ("1.416"->1416).
    # Se não houver essa linha (cliente 100% compensado), manda "0" (NÃO vazio — decisão do
    # usuário 2026-07-28). São QUANTIDADES em kWh (via _fmt_kwh, número puro), NÃO valores em R$.
    # INJETADO (só GD) = soma do |TE| das linhas "ENERGIA INJ ... TE ..."
    # (TUSD = duplicata, ignorada). Ex. desta fatura: consumo 296 ; injetado 41+41 = 82.
    consumo = _busca(r"ENERGIA ELET CONSUMO\s+kWh\s+(-?[\d.]*\d(?:,\d+)?)", full)
    dados["kwh_total_consumo"] = _fmt_kwh(_num_br(consumo)) if consumo else "0"
    dados["kwh_injetado"] = _fmt_kwh(inj_total) if achou_inj else ""

    # Saldo de crédito (SCEE): "... Todos os Períodos 786 ..." (primeiro = acumulado)
    dados["saldo_credito_todos_periodos"] = _busca(r"Todos os Per\S*\s+(\d+)", full)

    # Débito automático: boleto "NÃO RECEBER - FATURA ARRECADADA" (sem código de barras)
    dados["debito_automatico"] = bool(
        re.search(r"FATURA ARRECADADA|N\S?O RECEBER|D[EÉ]BITO AUTOM", full, re.I))
    return dados


# --------------------------------------------------------------------------
# RGE / CPFL (layout DANF3E da RGE)
# --------------------------------------------------------------------------
_MESES = r"JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ"


def _extrair_rge(full: str) -> dict:
    dados = _vazio()

    # Nota fiscal: "NOTA FISCAL Nº 161049027 - SÉRIE 0"
    dados["nota_fiscal"] = _busca(r"NOTA FISCAL\s*N[^\d]*(\d{5,})", full)

    # Ref/venc/valor: "MAI/2026 06/08/2026 R$ 81,28" (mês por extenso + ano de 4 dígitos).
    # Cliente GD com crédito pode vir NEGATIVO ("R$ -152,17" / "-R$ 152,17"): nesse caso
    # não há nada a pagar -> reporta valor_total = "0,00" (regra combinada com o CRM).
    m = re.search(
        rf"(?:{_MESES})/\d{{4}}\s+(\d{{2}}/\d{{2}}/\d{{4}})\s+(-?)\s*R\$\s*(-?)\s*([\d.]*\d,\d{{2}})",
        full, re.I)
    if m:
        dados["data_vencimento"] = m.group(1)
        negativo = "-" in (m.group(2) + m.group(3))
        dados["valor_total"] = "0,00" if negativo else m.group(4)

    # Leituras: ordem = ATUAL, ANTERIOR, nº de dias (INVERTIDA em relação à COPEL).
    # Pode vir com o nº da instalação na frente ("3095221938 20/05/2026 20/04/2026 30")
    # OU só as duas datas + nº de dias, em linha própria ("21/07/2026 18/06/2026 33").
    # O nº de dias NÃO pode ser seguido de dígito/'/' — senão casaria com o par
    # próxima/vencimento ("... 20/08/2026 13/08/2026 ..." tratando o "13" como dias).
    m = re.search(r"(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+\d{1,3}(?![\d/])", full)
    if m:
        dados["leitura_atual"] = m.group(1)
        dados["leitura_anterior"] = m.group(2)

    # Próxima leitura: "Próxima leitura 18/06/2026"
    dados["proxima_leitura"] = _busca(r"Pr[óo]xima leitura\s+(\d{2}/\d{2}/\d{4})", full)

    # kWh consumo: linha do medidor "... Energia Ativa-kWh único 31385 31537 1,00 152 ..."
    # (aceita milhar com ponto "1.416" e normaliza pra número puro via _fmt_kwh)
    consumo = _busca(
        r"Energia Ativa-kWh\s+\S+\s+\d+\s+\d+\s+[\d,]+\s+([\d.]*\d)", full)
    if not consumo:   # fallback: "Consumo Uso Sistema [KWh]-TUSD MAI/26 kWh 152,0000"
        consumo = _busca(r"Consumo Uso Sistema[^k]*kWh\s+([\d.]*\d(?:,\d+)?)", full)
    dados["kwh_total_consumo"] = _fmt_kwh(_num_br(consumo)) if consumo else ""

    # kWh injetado: "Energ Atv Inj. oUC mPT - TUSD ABR/26 kWh 122,0000 ..."
    inj = _busca(r"Energ\s*Atv\s*Inj[^k]*kWh\s+([\d.]*\d(?:,\d+)?)", full)
    dados["kwh_injetado"] = _fmt_kwh(_num_br(inj)) if inj else ""

    # Saldo de crédito: "Saldo em Energia da Instalação: Convencional 130,6000000000 kWh"
    dados["saldo_credito_todos_periodos"] = _busca(
        r"Saldo em Energia da Instala\S+:\s*\S+\s+(\d+)", full)

    # Débito automático: "DÉBITO AUTOMÁTICO" / "NÃO RECEBER"
    dados["debito_automatico"] = bool(
        re.search(r"D[EÉ]BITO AUTOM|FATURA ARRECADADA|N\s*[ÃA]\s*O\s*R\s*E\s*C\s*E\s*B\s*E\s*R",
                  full, re.I))
    return dados


# --------------------------------------------------------------------------
# CELESC (Santa Catarina) — DANF3E "Celesc Distribuição"
# --------------------------------------------------------------------------
def _extrair_celesc(full: str) -> dict:
    dados = _vazio()

    # Nota fiscal: "NOTA FISCAL N°095965500 SERIE:001 ..."
    dados["nota_fiscal"] = _busca(r"NOTA FISCAL\s*N[^\d]*(\d{5,})", full)

    # Venc: "06/2026 10/07/2026" (referência MM/AAAA + data de vencimento)
    m = re.search(r"\b\d{2}/\d{4}\s+(\d{2}/\d{2}/\d{4})", full)
    if m:
        dados["data_vencimento"] = m.group(1)
    # Valor: "TOTAL 99,39" (ou "R$ 99,39")
    mv = (re.search(r"\bTOTAL\s+(\d[\d.]*,\d{2})", full)
          or re.search(r"R\$\s*(\d[\d.]*,\d{2})", full))
    if mv:
        dados["valor_total"] = mv.group(1)

    # Leituras: "21/05/2026 19/06/2026 29 Lida 21/07/2026" (anterior, atual, dias, ..., próxima)
    m = re.search(r"(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+\d{1,3}\s+Lida", full, re.I)
    if m:
        dados["leitura_anterior"] = m.group(1)
        dados["leitura_atual"] = m.group(2)
    dados["proxima_leitura"] = _busca(r"Lida\s+(\d{2}/\d{2}/\d{4})", full)

    # Consumo MEDIDO (kWh) = 1ª coluna (mês atual) da TABELA mensal
    # "Consumo 910 0 566 503 ...". NÃO usar "Consumo TE KWH 150,000": isso é só UMA
    # faixa de tarifa (posto 0P) e subestima o total quando a conta tem vários postos.
    consumo = _busca(r"\bConsumo\s+(\d+)(?:\s+\d+){6,}", full)           # tabela mensal
    if not consumo:   # fallback: cabeçalho "Consumo Faturado Dias Faturados OUT/26 910 30"
        consumo = _busca(r"Consumo Faturado\s+Dias Faturados\s+\w+/\d+\s+(\d+)", full)
    if not consumo:   # fallback antigo (PDF sem a tabela / 1 posto só)
        consumo = _busca(r"Consumo\s+TE\s+KWH\s+([\d.]+(?:,\d+)?)", full)
    dados["kwh_total_consumo"] = _fmt_kwh(_num_br(consumo)) if consumo else "0"

    # Injeção (GD): soma das qtes "En Injetad TE ... KWH <num>" (as linhas TUSD duplicam a TE).
    # A "Band ... Injetad KWH <num>" costuma trazer o TOTAL injetado -> usa como reforço.
    inj, achou = 0.0, False
    for m in re.finditer(r"Injetad\s+TE\s+KWH\s+([\d.]+(?:,\d+)?)", full, re.I):
        inj += _num_br(m.group(1)); achou = True
    band_inj = _busca(r"Injetad\s+KWH\s+([\d.]+(?:,\d+)?)", full)   # (76) Band AM Injetad
    if band_inj and _num_br(band_inj) > inj:
        inj = _num_br(band_inj); achou = True
    dados["kwh_injetado"] = _fmt_kwh(inj) if achou else ""

    # Saldo de crédito (SCEE, pág. 2): "Saldo de créditos atualizados 584 707 ..." (1º = mês atual)
    dados["saldo_credito_todos_periodos"] = _busca(
        r"Saldo de cr[ée]ditos atualizados\s+(\d+)", full)

    # Débito automático: "em Débito Automático:"
    dados["debito_automatico"] = bool(re.search(r"D[ÉE]BITO\s+AUTOM[ÁA]TICO", full, re.I))
    return dados


# --------------------------------------------------------------------------
# Dispatcher: detecta a concessionária pelo texto e roteia
# --------------------------------------------------------------------------
def extrair_dados(pdf_path: str) -> dict:
    with pdfplumber.open(pdf_path) as pdf:
        pg0 = " ".join(_linhas(pdf.pages[0]))
        # CELESC guarda o saldo de crédito na PÁGINA 2 -> junta todas as páginas p/ ela.
        todas = " ".join(" ".join(_linhas(pg)) for pg in pdf.pages)
    if re.search(r"\bcelesc\b", pg0, re.I):
        return _extrair_celesc(todas)
    if re.search(r"\bRGE\b|rge-rs", pg0, re.I):   # COPEL/RGE seguem só a pág. 1 (validado)
        return _extrair_rge(pg0)
    return _extrair_copel(pg0)


if __name__ == "__main__":
    import sys
    caminho = sys.argv[1] if len(sys.argv) > 1 else ""
    for k, v in extrair_dados(caminho).items():
        print(f"{k:32} = {v!r}")
