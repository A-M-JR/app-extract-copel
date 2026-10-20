"""
Cliente da API de faturas — fonte de trabalho do robô (login/senha/UC/mês por fatura).

    GET {API_BASE_URL}/api/v1/invoices/preparation
    Header: Authorization: Bearer <token>   (escopo invoices:preparation:read)

Resposta esperada:
    {
      "success": true,
      "data": [
        {
          "id_fatura": 123,
          "concessionaria_alias": "COPEL",
          "login": "usuario.portal",
          "senha": "senha-do-portal",
          "unidade_consumidora": "103214445",
          "uc_aneel": "567749203180",
          "ano_mes_referencia": "01/2026"
        }
      ]
    }

Cada item vira um "conta" no mesmo formato que o resto do robô usa, só que com
login/senha e id_fatura embutidos (a credencial é POR FATURA).

Teste rápido da conexão:
    python api_faturas.py
"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import _caminhos  # noqa: E402,F401  (permite rodar este arquivo direto)

import base64
import os
import time

import requests

import config
from planilha import normalizar_mes, variantes_mes


class ApiError(Exception):
    pass


# --- status_leitura (enum aceito pela API no retorno) ----------------------
STATUS_COMPLETE          = "COMPLETE"            # sucesso: exige campos + PDF
STATUS_PORTAL_OFFLINE    = "PORTAL_OFFLINE"      # portal fora do ar / navegação falhou
STATUS_FALHA_LOGIN       = "FALHA_LOGIN"         # não conseguiu logar
STATUS_PDF_NAO_ENCONTRADO = "PDF_NAO_ENCONTRADO" # UC/fatura do mês não encontrada
STATUS_PDF_ERRO_LEITURA  = "PDF_ERRO_LEITURA"    # achou mas deu erro ao baixar/ler
STATUS_DADOS_INCOMPLETOS = "DADOS_INCOMPLETOS"   # baixou mas faltou dado obrigatório

# campos que compõem o leitura_fatura num COMPLETE (ordem só cosmética)
CAMPOS_LEITURA = [
    "uc_secondary", "nota_fiscal", "ano_mes_referencia", "data_vencimento",
    "valor_total", "leitura_anterior", "leitura_atual", "proxima_leitura",
    "saldo_credito_todos_periodos", "codigo_barras", "kwh_injetado",
    "kwh_total_consumo",
]


def _token() -> str:
    # config.API_TOKEN já resolve: config_local.json (painel) -> env PCRM_API_TOKEN -> default.
    # Usar direto o config torna o PAINEL a fonte única (env não sobrepõe o painel).
    tok = (getattr(config, "API_TOKEN", "") or "").strip()
    if not tok:
        raise ApiError("Token da API ausente. Preencha no painel (aba 'Configuração API').")
    return tok


def _base_url() -> str:
    # config.API_BASE_URL já resolve: config_local.json (painel) -> env API_BASE_URL -> default.
    # Assim o PAINEL é o único lugar pra trocar prod <-> localhost.
    base = (getattr(config, "API_BASE_URL", "") or "").strip()
    if not base:
        raise ApiError("URL da API ausente. Preencha no painel (aba 'Configuração API').")
    return base.rstrip("/")


def buscar_faturas(alias: str | None = None, timeout: int | None = None,
                   rota: str | None = None, fonte: str = "FATURA",
                   gravar: bool = True) -> list[dict]:
    """Chama a API e devolve a lista de faturas a processar (já filtrada por concessionária).

    `rota`/`fonte` permitem reaproveitar a mesma função para a fila de USINAS
    (GET /api/v1/farms/readings) — o corpo de resposta é o mesmo, só muda a URL.
    `gravar=False` não sobrescreve o relatório consulta_crm (usinas não mexe no de títulos)."""
    alias = getattr(config, "CONCESSIONARIA_ALIAS", None) if alias is None else alias
    timeout = getattr(config, "API_TIMEOUT_S", 30) if timeout is None else timeout
    rota = rota or getattr(config, "API_ROTA_PREPARACAO", "/api/v1/invoices/preparation")

    url = _base_url() + rota
    headers = {"Authorization": f"Bearer {_token()}", "Accept": "application/json"}

    t0 = time.time()
    resp = requests.get(url, headers=headers, timeout=timeout)
    duracao = time.time() - t0
    if not resp.ok:
        corpo = (resp.text or "").strip()[:400].replace("\n", " | ")
        raise ApiError(f"GET {url} falhou (HTTP {resp.status_code}). Resposta: {corpo!r}")
    try:
        payload = resp.json()
    except ValueError:
        corpo = (resp.text or "").strip()[:400].replace("\n", " | ")
        raise ApiError(f"GET {url} respondeu NÃO-JSON (HTTP {resp.status_code}). Início: {corpo!r}")

    if not payload.get("success", False):
        raise ApiError(f"API retornou success=false ou formato inesperado: {payload}")

    itens = payload.get("data") or []
    contas: list[dict] = []
    for it in itens:
        al = str(it.get("concessionaria_alias") or "").strip()
        if alias and al.upper() != str(alias).upper():
            continue
        contas.append(_mapear(it, fonte=fonte))
    if gravar:
        try:
            gravar_consulta(url, alias, resp.status_code, duracao, itens, contas)
        except Exception as e:
            print(f"[api] aviso: não gravei o consulta_crm.txt ({e})")
    return contas


def buscar_usinas(alias: str | None = None, timeout: int | None = None) -> list[dict]:
    """Fila de leitura das USINAS (GET /api/v1/farms/readings). Mesmo formato de conta
    que buscar_faturas, só que cada conta vem marcada com fonte='USINA' (define a rota
    do POST no callback e diferencia no log). Não mexe no relatório consulta_crm."""
    return buscar_faturas(alias=alias, timeout=timeout,
                          rota=getattr(config, "API_ROTA_USINAS", "/api/v1/farms/readings"),
                          fonte="USINA", gravar=False)


def gravar_consulta(url, alias, http_status, duracao_s, itens, contas) -> None:
    """Sobrescreve consulta_crm.html/.txt (Extração-copel) com o que a API devolveu."""
    import relatorio_crm
    relatorio_crm.gravar(url, alias, http_status, duracao_s, itens, contas)


def _mapear(it: dict, fonte: str = "FATURA") -> dict:
    """Converte um item da API no dicionário 'conta' usado pelo robô."""
    uc = str(it.get("unidade_consumidora") or "").strip()
    uc_aneel_api = str(it.get("uc_secondary") or it.get("uc_aneel") or "").strip()
    mes_raw = it.get("ano_mes_referencia") or ""
    mes_num, mes_ano = normalizar_mes(mes_raw)

    # nome_cliente vira o nome do PDF (a API já manda esse campo).
    nome_cliente = (str(it.get("nome_cliente") or "").strip()
                    or uc or str(it.get("id_fatura") or "sem_nome"))

    # endereço (p/ RGE: a UC mudou de formato, então localiza a instalação pelo endereço).
    # Aceita um objeto 'endereco' aninhado OU campos no nível de cima, com nomes variados.
    e = it.get("endereco") if isinstance(it.get("endereco"), dict) else {}

    def _end(*chaves) -> str:
        for src in (e, it):
            for k in chaves:
                v = src.get(k)
                if v not in (None, ""):
                    return str(v).strip()
        return ""

    return {
        "id_fatura":     it.get("id_fatura"),
        "fonte":         str(it.get("tipo") or fonte or "FATURA").strip().upper(),  # FATURA | USINA
        "login":         str(it.get("login") or "").strip(),
        "senha":         str(it.get("senha") or "").strip(),
        "concessionaria": it.get("concessionaria_alias"),
        "cnpj":          str(it.get("cnpj") or "").strip(),
        "uc":            uc,
        "uc_aneel_api":  uc_aneel_api,           # UC nova (vem vazia -> capturamos no portal)
        "nome_cliente":  nome_cliente,
        "mes_referencia": f"{mes_num:02d}/{mes_ano}" if mes_num else str(mes_raw).strip(),
        "mes_num":       mes_num,
        "mes_ano":       mes_ano,
        "mes_variantes": variantes_mes(mes_num, mes_ano) if mes_num else [],
        # --- endereço (RGE localiza a instalação por aqui) ---
        "logradouro":    _end("logradouro", "rua", "endereco", "endereço", "address"),
        "numero":        _end("numero", "número", "num", "numero_endereco"),
        "bairro":        _end("bairro"),
        "cidade":        _end("cidade", "municipio", "município", "city"),
        "uf":            _end("uf", "estado", "state"),
        "cep":           _end("cep", "zip", "zipcode"),
    }


def _pdf_para_base64(caminho: str) -> str:
    with open(caminho, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def montar_item_resultado(id_fatura, status_leitura: str, dados: dict | None = None,
                          uc_aneel: str = "", pdf_path: str | None = None) -> dict:
    """
    Monta um item do payload de retorno.
      - Falha (qualquer status != COMPLETE): manda só o status.
      - COMPLETE: manda os campos preenchidos (não vazios) + pdf_base64.
    """
    leitura = {"status_leitura": status_leitura}
    item = {"id_fatura": id_fatura, "leitura_fatura": leitura}
    if uc_aneel:
        item["uc_secondary"] = uc_aneel          # CRM renomeou uc_aneel -> uc_secondary

    if status_leitura == STATUS_COMPLETE:
        if uc_aneel:
            leitura["uc_secondary"] = uc_aneel
        for campo in CAMPOS_LEITURA:
            valor = (dados or {}).get(campo)
            if valor not in (None, ""):
                leitura[campo] = valor
        if pdf_path:
            leitura["pdf_base64"] = _pdf_para_base64(pdf_path)
    return item


def enviar_resultados(itens: list[dict], timeout: int | None = None,
                      rota: str | None = None) -> dict:
    """POST dos resultados. Retorna o JSON da API (data.resultados[]).

    `rota` permite postar na fila de USINAS (/api/v1/farms/readings); default = títulos."""
    if not itens:
        return {"success": True, "data": {"resultados": []}}
    timeout = getattr(config, "API_TIMEOUT_S", 60) if timeout is None else timeout
    url = _base_url() + (rota or getattr(config, "API_ROTA_READINGS",
                                         "/api/v1/invoices/preparation/readings"))
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_token()}",
    }
    resp = requests.post(url, headers=headers, json={"faturas": itens}, timeout=timeout)
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError:
        # resposta não-JSON (HTML/erro/redirect) -> mostra o que veio, pra diagnosticar o prod
        corpo = (resp.text or "").strip()[:400].replace("\n", " | ")
        raise ApiError(
            f"resposta NÃO-JSON do POST (HTTP {resp.status_code}) em {resp.url} "
            f"[pedido: {url}]. Confira se a rota de retorno existe nesse ambiente. "
            f"Início da resposta: {corpo!r}")


if __name__ == "__main__":
    try:
        faturas = buscar_faturas()
        print(f"[ok] {len(faturas)} fatura(s) da concessionária "
              f"{getattr(config, 'CONCESSIONARIA_ALIAS', '(todas)')}:")
        for c in faturas:
            print(f"   id={c['id_fatura']} | login={c['login']} | UC={c['uc']} "
                  f"| mês={c['mes_referencia']} | uc_aneel(API)={c['uc_aneel_api']}")
    except Exception as e:
        print(f"[ERRO] {type(e).__name__}: {e}")
