"""
Cliente de e-mail via Microsoft Graph (app-only / client credentials).

É a "fonte por e-mail" do robô: lê as caixas compartilhadas do M365 e baixa os
PDFs de fatura anexados — SEM senha de caixa, SEM navegador, SEM captcha. Só
LEITURA (permissão Mail.Read); nunca envia, marca como lido ou apaga nada.

Credenciais (do config.py; caem em variável de ambiente p/ teste):
    EMAIL_GRAPH_TENANT / EMAIL_GRAPH_CLIENT / EMAIL_GRAPH_SECRET
    EMAIL_CAIXAS  -> lista de e-mails a ler

Teste rápido:
    python email_graph.py            (lista as faturas recentes das caixas do config)
"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import _caminhos  # noqa: E402,F401  (permite rodar este arquivo direto)

import base64
import datetime as _dt
import time

import requests

import config

GRAPH = "https://graph.microsoft.com/v1.0"
_AUTORIDADE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"


class GraphError(Exception):
    pass


# --- cache simples de token (expira em ~1h; renova sozinho) ----------------
_token_cache = {"valor": "", "expira": 0.0}


def _tenant() -> str:
    t = (getattr(config, "EMAIL_GRAPH_TENANT", "") or "").strip()
    if not t:
        raise GraphError("EMAIL_GRAPH_TENANT ausente (painel > E-mail, ou env GRAPH_TENANT).")
    return t


def token() -> str:
    """Token app-only (client credentials). Reaproveita enquanto válido."""
    if _token_cache["valor"] and time.time() < _token_cache["expira"] - 60:
        return _token_cache["valor"]
    cid = (getattr(config, "EMAIL_GRAPH_CLIENT", "") or "").strip()
    sec = (getattr(config, "EMAIL_GRAPH_SECRET", "") or "").strip()
    if not (cid and sec):
        raise GraphError("EMAIL_GRAPH_CLIENT/SECRET ausentes (painel > E-mail, ou env).")
    data = {
        "client_id": cid,
        "client_secret": sec,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }
    r = requests.post(_AUTORIDADE.format(tenant=_tenant()), data=data, timeout=30)
    if not r.ok:
        raise GraphError(f"falha ao obter token (HTTP {r.status_code}): {r.text[:300]}")
    j = r.json()
    _token_cache["valor"] = j["access_token"]
    _token_cache["expira"] = time.time() + int(j.get("expires_in", 3600))
    return _token_cache["valor"]


def _headers() -> dict:
    return {"Authorization": f"Bearer {token()}", "Accept": "application/json"}


def _get(url: str, timeout: int = 30) -> dict:
    r = requests.get(url, headers=_headers(), timeout=timeout)
    if not r.ok:
        raise GraphError(f"GET {url.split('?')[0]} -> HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def listar_mensagens(caixa: str, desde_dias: int = 30, so_com_anexo: bool = True,
                     max_msgs: int = 200) -> list[dict]:
    """Mensagens da Caixa de Entrada da `caixa`, mais recentes primeiro.
    Devolve dicts com id, de, assunto, recebido, tem_anexo e corpo (texto/HTML)."""
    desde = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=desde_dias)) \
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    campos = "id,subject,from,receivedDateTime,hasAttachments,bodyPreview,body"
    filtro = f"receivedDateTime ge {desde}"
    if so_com_anexo:
        filtro = "hasAttachments eq true and " + filtro
    url = (f"{GRAPH}/users/{caixa}/mailFolders/Inbox/messages"
           f"?$select={campos}&$top=50&$filter={filtro}&$orderby=receivedDateTime desc")

    msgs: list[dict] = []
    try:
        pagina = _get(url)
    except GraphError:
        # alguns tenants reclamam de $orderby junto do $filter -> tenta sem ordenar
        url_sem = (f"{GRAPH}/users/{caixa}/mailFolders/Inbox/messages"
                   f"?$select={campos}&$top=50&$filter={filtro}")
        pagina = _get(url_sem)
    while True:
        for m in pagina.get("value", []):
            msgs.append({
                "id": m.get("id"),
                "de": (m.get("from") or {}).get("emailAddress", {}).get("address", ""),
                "assunto": m.get("subject") or "",
                "recebido": m.get("receivedDateTime") or "",
                "tem_anexo": bool(m.get("hasAttachments")),
                "corpo": (m.get("body") or {}).get("content", "") or m.get("bodyPreview", ""),
            })
            if len(msgs) >= max_msgs:
                return msgs
        prox = pagina.get("@odata.nextLink")
        if not prox:
            break
        pagina = _get(prox)
    return msgs


def nomes_anexos(caixa: str, msg_id: str) -> list[str]:
    """Só os NOMES dos anexos (sem baixar o conteúdo) — barato, p/ casar antes de baixar.
    'name'/'contentType' existem no tipo base do anexo (contentBytes não)."""
    url = (f"{GRAPH}/users/{caixa}/messages/{msg_id}/attachments"
           "?$select=name,contentType")
    nomes = []
    for a in _get(url).get("value", []):
        nome = (a.get("name") or "").strip()
        tipo = (a.get("contentType") or "").lower()
        if nome.lower().endswith(".pdf") or "pdf" in tipo:
            nomes.append(nome)
    return nomes


def baixar_pdfs(caixa: str, msg_id: str) -> list[tuple[str, bytes]]:
    """Baixa os anexos PDF de uma mensagem. Devolve [(nome_arquivo, bytes), ...]."""
    # sem $select: 'contentBytes' só existe no tipo derivado fileAttachment, e selecioná-lo
    # no tipo base dá HTTP 400. O GET puro já traz name/contentType/contentBytes.
    url = f"{GRAPH}/users/{caixa}/messages/{msg_id}/attachments"
    saida: list[tuple[str, bytes]] = []
    for a in _get(url).get("value", []):
        if a.get("@odata.type") != "#microsoft.graph.fileAttachment":
            continue
        nome = (a.get("name") or "").strip()
        tipo = (a.get("contentType") or "").lower()
        if not (nome.lower().endswith(".pdf") or "pdf" in tipo):
            continue
        conteudo = a.get("contentBytes")
        if not conteudo:
            continue
        saida.append((nome, base64.b64decode(conteudo)))
    return saida


def pdf_sem_senha(conteudo: bytes, senha: str | None) -> bytes:
    """Devolve o PDF SEM senha. Se não estiver protegido (ou senha vazia), devolve igual.
    Usado pra COPEL/Enel (PDF protegido pelos 4 primeiros dígitos do CPF/CNPJ) — o CRM
    recebe o PDF já aberto."""
    import io
    try:
        from pypdf import PdfReader, PdfWriter
    except Exception:
        return conteudo
    try:
        r = PdfReader(io.BytesIO(conteudo))
        if not r.is_encrypted:
            return conteudo
        if not senha or r.decrypt(senha) == 0:
            raise GraphError("senha do PDF incorreta ou ausente")
        w = PdfWriter()
        for pg in r.pages:
            w.add_page(pg)
        buf = io.BytesIO()
        w.write(buf)
        return buf.getvalue()
    except GraphError:
        raise
    except Exception as e:
        raise GraphError(f"falha ao abrir o PDF protegido: {type(e).__name__}: {e}")


def salvar(conteudo: bytes, pasta, nome: str) -> str:
    """Grava o PDF numa pasta e devolve o caminho."""
    pasta = _Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / config.sanitizar(_Path(nome).stem)
    destino = destino.with_suffix(".pdf")
    destino.write_bytes(conteudo)
    return str(destino)


if __name__ == "__main__":
    caixas = getattr(config, "EMAIL_CAIXAS", []) or []
    dias = getattr(config, "EMAIL_DIAS", 30)
    print(f"[graph] lendo {len(caixas)} caixa(s), últimos {dias} dia(s)...\n")
    for caixa in caixas:
        try:
            msgs = listar_mensagens(caixa, desde_dias=dias)
        except Exception as e:
            print(f"===== {caixa} =====\n  [ERRO] {type(e).__name__}: {e}\n")
            continue
        print(f"===== {caixa} — {len(msgs)} mensagem(ns) com anexo =====")
        for m in msgs[:15]:
            print(f"   {m['recebido'][:16]}  {m['de']:<38} {m['assunto'][:55]}")
        print()
