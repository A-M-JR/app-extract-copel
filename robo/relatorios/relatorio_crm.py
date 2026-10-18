"""
Relatório da consulta ao CRM — sobrescrito a cada consulta (api_faturas.buscar_faturas).

Gera dois arquivos em Extração-copel:
  - consulta_crm.html  -> o relatório "bonito" (abre no navegador; botão no painel)
  - consulta_crm.txt   -> a mesma informação em texto puro (pra grep / anexar em chamado)

Mostra o que o robô recebeu pra coletar, os pontos de atenção (dados faltando, duplicados,
campos não usados) e o JSON bruto da API com senhas/tokens mascarados.
"""
import html
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

import config

# campos que o robô lê de cada item (o resto que vier da API é listado como "não usado")
CAMPOS_USADOS = {
    "id_fatura", "concessionaria_alias", "login", "senha", "unidade_consumidora",
    "uc_secondary", "uc_aneel", "ano_mes_referencia", "nome_cliente", "cnpj", "endereco",
    "logradouro", "rua", "address", "numero", "num", "numero_endereco", "bairro", "cidade",
    "municipio", "city", "uf", "estado", "state", "cep", "zip", "zipcode",
}
_SENSIVEIS = ("senha", "password", "token", "secret")


def mascarar(obj):
    if isinstance(obj, dict):
        return {k: ("***" if any(x in k.lower() for x in _SENSIVEIS) and v else mascarar(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [mascarar(v) for v in obj]
    return obj


def analisar(url, alias, http_status, duracao_s, itens, contas) -> dict:
    """Tudo que os dois relatórios mostram, calculado uma vez só."""
    logins = Counter(c["login"] for c in contas)
    ids = lambda lst: [c["id_fatura"] for c in lst][:20]
    sem_cred = [c for c in contas if not c["login"] or not c["senha"]]
    sem_uc = [c for c in contas if not c["uc"]]
    sem_mes = [c for c in contas if not c["mes_num"]]
    dup = [k for k, n in Counter((c["uc"], c["mes_referencia"]) for c in contas).items() if n > 1]
    com_aneel = [c for c in contas if c["uc_aneel_api"]]
    sem_nome = [c for c in contas if c["nome_cliente"] in (c["uc"], str(c["id_fatura"]))]
    extras = sorted({k for it in itens for k in it} - CAMPOS_USADOS)

    # (nível, título, detalhe) — nível: erro | aviso | info
    avisos = []
    if sem_cred:
        avisos.append(("erro", f"{len(sem_cred)} fatura(s) sem login/senha",
                       f"Vão falhar no login. ids: {ids(sem_cred)}"))
    if sem_uc:
        avisos.append(("erro", f"{len(sem_uc)} fatura(s) sem unidade consumidora",
                       f"ids: {ids(sem_uc)}"))
    if sem_mes:
        avisos.append(("erro", f"{len(sem_mes)} fatura(s) com mês de referência inválido",
                       f"Campo ano_mes_referencia vazio ou fora do padrão. ids: {ids(sem_mes)}"))
    if dup:
        avisos.append(("erro", f"{len(dup)} UC + mês duplicados",
                       "O robô baixaria a mesma fatura 2x: "
                       + ", ".join(f"{u} ({m})" for u, m in dup[:10])))
    if sem_nome:
        avisos.append(("aviso", f"{len(sem_nome)} fatura(s) sem nome do cliente",
                       "O PDF fica salvo com o número da UC em vez do nome."))
    if len(logins) > 1:
        avisos.append(("aviso", f"{len(logins)} logins = {len(logins)} captchas",
                       "Agrupar UCs no mesmo login no CRM reduz captcha e tempo de execução."))
    if com_aneel:
        avisos.append(("info", f"{len(com_aneel)} fatura(s) já vêm com a UC ANEEL",
                       "Campo uc_secondary preenchido pelo CRM."))
    if extras:
        avisos.append(("info", "Campos que a API manda e o robô não usa",
                       ", ".join(extras)))

    return {
        "quando": datetime.now(),
        "url": url, "alias": alias or "(todas)",
        "http_status": http_status, "duracao_s": duracao_s,
        "total_api": len(itens), "contas": contas,
        "por_conc": Counter(str(it.get("concessionaria_alias") or "?") for it in itens).most_common(),
        "logins": logins.most_common(),
        "ucs": len({c["uc"] for c in contas}),
        "meses": sorted(Counter(c["mes_referencia"] for c in contas).items()),
        "avisos": avisos,
        "json": json.dumps(mascarar(itens), indent=2, ensure_ascii=False),
    }


# --------------------------------------------------------------------------- TXT
def render_txt(d: dict) -> str:
    L = []
    w = L.append
    w("CONSULTA AO CRM — o que o robô recebeu pra coletar")
    w("=" * 70)
    w(f"Data/hora:      {d['quando']:%d/%m/%Y %H:%M:%S}")
    w(f"Endpoint:       GET {d['url']}")
    w(f"Filtro:         concessionária = {d['alias']}")
    w(f"Resposta:       HTTP {d['http_status']} em {d['duracao_s']:.1f}s")
    w(f"Itens na API:   {d['total_api']} (todas as concessionárias)")
    w(f"Após filtro:    {len(d['contas'])} fatura(s)")
    w("Por concessionária (API inteira): "
      + (", ".join(f"{k}={v}" for k, v in d["por_conc"]) or "-"))
    w("")
    w("RESUMO DO QUE PRECISA COLETAR")
    w("-" * 70)
    w(f"Faturas: {len(d['contas'])}   Logins distintos: {len(d['logins'])}   "
      f"UCs distintas: {d['ucs']}")
    w("Meses:   " + (", ".join(f"{m} ({n})" for m, n in d["meses"]) or "-"))
    w("Faturas por login (cada login = 1 captcha na COPEL):")
    for lg, n in d["logins"]:
        w(f"   {lg or '(sem login)':<30} {n}")
    w("")
    w("PONTOS DE ATENÇÃO / O QUE DÁ PRA MELHORAR")
    w("-" * 70)
    for nivel, titulo, det in d["avisos"] or [("ok", "nenhum — consulta limpa.", "")]:
        w(f" - [{nivel.upper()}] {titulo}" + (f": {det}" if det else ""))
    w("")
    w("LISTA (na ordem que o robô vai processar)")
    w("-" * 70)
    w(f"{'id_fatura':<10} {'login':<22} {'UC':<14} {'UC ANEEL':<14} {'mês':<8} nome_cliente")
    for c in d["contas"]:
        w(f"{str(c['id_fatura']):<10} {c['login'][:22]:<22} {c['uc'][:14]:<14} "
          f"{c['uc_aneel_api'][:14]:<14} {c['mes_referencia']:<8} {c['nome_cliente']}")
    w("")
    w("JSON BRUTO DA API (senhas/tokens mascarados)")
    w("-" * 70)
    w(d["json"])
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- HTML
_CSS = """
:root{--bg:#f4f6f8;--card:#fff;--txt:#1f2937;--muted:#6b7280;--line:#e5e7eb;--accent:#2e7d32;
--accent-soft:#e8f3e9;--erro:#b42318;--erro-bg:#fef3f2;--aviso:#b54708;--aviso-bg:#fffaeb;
--info:#175cd3;--info-bg:#eff8ff;--code:#f8fafc}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#111418;--card:#1a1f25;
--txt:#e5e7eb;--muted:#9aa3ae;--line:#2b323a;--accent:#66bb6a;--accent-soft:#1d2b1f;--erro:#f97066;
--erro-bg:#2a1615;--aviso:#fdb022;--aviso-bg:#2a2112;--info:#53b1fd;--info-bg:#132233;--code:#14181d}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);
font:15px/1.5 "Segoe UI",system-ui,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:28px 16px 60px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:15px;margin:0 0 14px;text-transform:uppercase;
letter-spacing:.05em;color:var(--muted)}
.sub{color:var(--muted);font-size:13px;word-break:break-all}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.chip{background:var(--card);border:1px solid var(--line);border-radius:999px;padding:3px 12px;font-size:13px}
.chip b{font-weight:600}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:22px 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.kpi .n{font-size:28px;font-weight:600;color:var(--accent);line-height:1.1}
.kpi .l{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin-bottom:16px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media (max-width:760px){.grid2{grid-template-columns:1fr}}
.aviso{border-left:4px solid;border-radius:8px;padding:10px 14px;margin-bottom:10px}
.aviso b{display:block}.aviso span{font-size:13px;word-break:break-word}
.erro{border-color:var(--erro);background:var(--erro-bg)}.erro b{color:var(--erro)}
.av{border-color:var(--aviso);background:var(--aviso-bg)}.av b{color:var(--aviso)}
.info{border-color:var(--info);background:var(--info-bg)}.info b{color:var(--info)}
.ok{border-color:var(--accent);background:var(--accent-soft)}.ok b{color:var(--accent)}
.bar{display:grid;grid-template-columns:minmax(90px,38%) 1fr 34px;gap:10px;align-items:center;
font-size:13px;margin-bottom:6px}
.bar .t{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar .f{height:8px;border-radius:4px;background:var(--accent)}
.bar .v{text-align:right;color:var(--muted)}
input{width:100%;padding:9px 12px;border:1px solid var(--line);border-radius:8px;
background:var(--bg);color:var(--txt);font:inherit;margin-bottom:12px}
.tbl{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase}
td.vazio{color:var(--muted)}
details summary{cursor:pointer;font-weight:600}
pre{background:var(--code);border:1px solid var(--line);border-radius:8px;padding:14px;
overflow:auto;max-height:520px;font-size:12px}
footer{color:var(--muted);font-size:12px;margin-top:20px}
"""

_JS = """
const q=document.getElementById('busca');
q&&q.addEventListener('input',()=>{const t=q.value.toLowerCase();
document.querySelectorAll('#lista tbody tr').forEach(r=>{
r.style.display=r.textContent.toLowerCase().includes(t)?'':'none'})});
"""


def render_html(d: dict) -> str:
    e = lambda v: html.escape(str(v))
    classe = {"erro": "erro", "aviso": "av", "info": "info"}
    avisos = "".join(
        f'<div class="aviso {classe[n]}"><b>{e(t)}</b><span>{e(det)}</span></div>'
        for n, t, det in d["avisos"]) or \
        '<div class="aviso ok"><b>Nenhum ponto de atenção</b><span>Consulta limpa.</span></div>'
    n_erros = sum(1 for a in d["avisos"] if a[0] == "erro")

    maior = max([n for _, n in d["logins"]] or [1])
    barras = "".join(
        f'<div class="bar"><span class="t" title="{e(lg)}">{e(lg or "(sem login)")}</span>'
        f'<span class="f" style="width:{max(4, n / maior * 100):.0f}%"></span>'
        f'<span class="v">{n}</span></div>' for lg, n in d["logins"]) or \
        '<span class="sub">—</span>'
    meses = "".join(f'<span class="chip"><b>{e(m)}</b> · {n}</span>' for m, n in d["meses"]) \
        or '<span class="sub">—</span>'
    concs = "".join(f'<span class="chip">{e(k)} <b>{n}</b></span>' for k, n in d["por_conc"])

    def cel(v):
        return f"<td>{e(v)}</td>" if v not in (None, "") else '<td class="vazio">—</td>'
    linhas = "".join(
        "<tr>" + cel(c["id_fatura"]) + cel(c["login"]) + cel(c["uc"]) + cel(c["uc_aneel_api"])
        + cel(c["mes_referencia"]) + cel(c["nome_cliente"]) + "</tr>" for c in d["contas"])

    return f"""<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Consulta ao CRM</title><style>{_CSS}</style></head>
<body><div class="wrap">
<h1>Consulta ao CRM</h1>
<div class="sub">O que o robô recebeu pra coletar · {d['quando']:%d/%m/%Y às %H:%M:%S}</div>
<div class="chips">
  <span class="chip">Filtro <b>{e(d['alias'])}</b></span>
  <span class="chip">HTTP <b>{e(d['http_status'])}</b> em <b>{d['duracao_s']:.1f}s</b></span>
  <span class="chip">Itens na API <b>{d['total_api']}</b></span>{concs}
</div>
<div class="sub" style="margin-top:8px">GET {e(d['url'])}</div>

<div class="kpis">
  <div class="kpi"><div class="n">{len(d['contas'])}</div><div class="l">faturas pra coletar</div></div>
  <div class="kpi"><div class="n">{len(d['logins'])}</div><div class="l">logins (captchas)</div></div>
  <div class="kpi"><div class="n">{d['ucs']}</div><div class="l">UCs distintas</div></div>
  <div class="kpi"><div class="n" style="color:var({'--erro' if n_erros else '--accent'})">{n_erros}</div>
    <div class="l">problemas no cadastro</div></div>
</div>

<div class="grid2">
  <div class="card"><h2>Pontos de atenção</h2>{avisos}</div>
  <div class="card"><h2>Faturas por login</h2>{barras}
    <h2 style="margin-top:20px">Meses de referência</h2><div class="chips">{meses}</div></div>
</div>

<div class="card"><h2>Lista — na ordem que o robô vai processar</h2>
  <input id="busca" placeholder="Filtrar por login, UC, cliente, mês…">
  <div class="tbl"><table id="lista"><thead><tr><th>id_fatura</th><th>login</th><th>UC</th>
  <th>UC ANEEL</th><th>mês</th><th>cliente</th></tr></thead><tbody>{linhas}</tbody></table></div>
</div>

<div class="card"><details><summary>JSON bruto da API (senhas e tokens mascarados)</summary>
<pre>{e(d['json'])}</pre></details></div>

<footer>Arquivo sobrescrito a cada consulta ao CRM · versão em texto: consulta_crm.txt</footer>
</div><script>{_JS}</script></body></html>
"""


def caminho(alias) -> Path:
    """consulta_crm_<ALIAS>.txt — um por concessionária (rodam em paralelo no 24/7)."""
    base = Path(config.ARQUIVO_CONSULTA_CRM)
    return base.with_name(f"{base.stem}_{config.sanitizar(alias or 'todas')}{base.suffix}")


def gravar(url, alias, http_status, duracao_s, itens, contas) -> None:
    if not getattr(config, "ARQUIVO_CONSULTA_CRM", None):
        return
    d = analisar(url, alias, http_status, duracao_s, itens, contas)
    txt = caminho(alias)
    txt.parent.mkdir(parents=True, exist_ok=True)
    txt.write_text(render_txt(d), encoding="utf-8")
    txt.with_suffix(".html").write_text(render_html(d), encoding="utf-8")
