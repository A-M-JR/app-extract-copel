"""
Relatório HTML de uma execução (gerado junto do resultado_*.xlsx, mesmo nome).

Mostra num lugar só: resumo (números + barra de status), o que deu errado (com print de
tela e motivo), a lista de todas as faturas com filtro, o retorno do CRM, o desempenho
por login e o log completo da execução (colorido e filtrável).
Abre pelo botão "Abrir relatório" do painel.
"""
import html
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from resultado_log import CONCLUIDO, NAO_ENCONTRADO, FATURA_NAO_EMITIDA, ERRO

_ROTULO = {CONCLUIDO: "Concluída", FATURA_NAO_EMITIDA: "Não emitida",
           NAO_ENCONTRADO: "UC não encontrada", ERRO: "Erro"}
_CLASSE = {CONCLUIDO: "ok", FATURA_NAO_EMITIDA: "av", NAO_ENCONTRADO: "av", ERRO: "erro"}

_CSS = """
:root{--bg:#f4f6f8;--card:#fff;--txt:#1f2937;--muted:#6b7280;--line:#e5e7eb;--accent:#2e7d32;
--ok:#2e7d32;--ok-bg:#e8f3e9;--erro:#b42318;--erro-bg:#fef3f2;--av:#b54708;--av-bg:#fffaeb;
--info:#175cd3;--info-bg:#eff8ff;--code:#f8fafc;--chip:#eef1f4}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#111418;--card:#1a1f25;
--txt:#e5e7eb;--muted:#9aa3ae;--line:#2b323a;--accent:#66bb6a;--ok:#66bb6a;--ok-bg:#1d2b1f;
--erro:#f97066;--erro-bg:#2a1615;--av:#fdb022;--av-bg:#2a2112;--info:#53b1fd;--info-bg:#132233;
--code:#14181d;--chip:#232a32}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);font:15px/1.5 "Segoe UI",system-ui,sans-serif}
a{color:var(--info)}
.wrap{max-width:1180px;margin:0 auto;padding:28px 16px 60px}
h1{font-size:25px;margin:0 0 2px}
h2{font-size:14px;margin:0 0 14px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.sub{color:var(--muted);font-size:13px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.chip{background:var(--card);border:1px solid var(--line);border-radius:999px;padding:3px 12px;font-size:13px}
.chip b{font-weight:600}
nav.atalhos{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 0}
nav.atalhos a{background:var(--chip);border-radius:8px;padding:5px 12px;font-size:13px;color:var(--txt);text-decoration:none}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:22px 0 12px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.kpi .n{font-size:28px;font-weight:600;line-height:1.1}
.kpi .l{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.stack{display:flex;height:12px;border-radius:6px;overflow:hidden;background:var(--chip);margin-bottom:22px}
.stack span{display:block;height:100%}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin-bottom:16px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media (max-width:820px){.grid2{grid-template-columns:1fr}}
.prob{display:grid;grid-template-columns:1fr auto;gap:14px;border-left:4px solid var(--erro);
background:var(--erro-bg);border-radius:8px;padding:12px 14px;margin-bottom:10px}
.prob.av{border-color:var(--av);background:var(--av-bg)}
.prob b{display:block}.prob .m{font-size:13px;word-break:break-word;margin-top:2px}
.prob img{width:150px;max-height:96px;object-fit:cover;object-position:top;border-radius:6px;border:1px solid var(--line)}
@media (max-width:600px){.prob{grid-template-columns:1fr}.prob img{width:100%;max-height:none}}
.badge{display:inline-block;border-radius:999px;padding:1px 10px;font-size:12px;font-weight:600;white-space:nowrap}
.badge.ok{background:var(--ok-bg);color:var(--ok)}.badge.av{background:var(--av-bg);color:var(--av)}
.badge.erro{background:var(--erro-bg);color:var(--erro)}.badge.info{background:var(--info-bg);color:var(--info)}
.filtros{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px}
.filtros button{font:inherit;font-size:13px;border:1px solid var(--line);background:var(--card);color:var(--txt);
border-radius:999px;padding:4px 12px;cursor:pointer}
.filtros button.on{background:var(--txt);color:var(--card);border-color:var(--txt)}
input{width:100%;padding:9px 12px;border:1px solid var(--line);border-radius:8px;background:var(--bg);
color:var(--txt);font:inherit;margin-bottom:12px}
.tbl{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;white-space:nowrap}
td.n{white-space:nowrap}td.vazio{color:var(--muted)}td.msg{min-width:220px;color:var(--muted)}
.log{background:var(--code);border:1px solid var(--line);border-radius:8px;max-height:620px;overflow:auto;
font:12px/1.55 Consolas,monospace;padding:10px 0}
.log div{padding:0 12px;white-space:pre-wrap;word-break:break-word}
.log .h{color:var(--muted);user-select:none;margin-right:10px}
.log .e{color:var(--erro);background:var(--erro-bg)}.log .w{color:var(--av)}
.log .c{color:var(--info)}.log .s{color:var(--ok)}.log .p{font-weight:700}
.vazio-log{color:var(--muted);font-size:13px}
footer{color:var(--muted);font-size:12px;margin-top:20px}
"""

_JS = """
const rows=[...document.querySelectorAll('#lista tbody tr')];
let filtro='todos';
function aplica(){const t=(document.getElementById('busca').value||'').toLowerCase();
rows.forEach(r=>{const okS=filtro==='todos'||r.dataset.s===filtro;
r.style.display=okS&&r.textContent.toLowerCase().includes(t)?'':'none'})}
document.querySelectorAll('.filtros button').forEach(b=>b.addEventListener('click',()=>{
document.querySelectorAll('.filtros button').forEach(x=>x.classList.remove('on'));
b.classList.add('on');filtro=b.dataset.f;aplica()}));
document.getElementById('busca').addEventListener('input',aplica);
const lb=document.getElementById('logbusca'),le=document.getElementById('logerros');
function logf(){const t=(lb.value||'').toLowerCase(),so=le.checked;
document.querySelectorAll('.log div').forEach(d=>{const okE=!so||d.classList.contains('e')||d.classList.contains('w');
d.style.display=okE&&d.textContent.toLowerCase().includes(t)?'':'none'})}
lb&&lb.addEventListener('input',logf);le&&le.addEventListener('change',logf);
"""

_RX_ERRO = re.compile(r"\berro\b|falhou|falha|exception|traceback|error|!!!|tempo esgotado", re.I)
_RX_AVISO = re.compile(r"aviso|tentativa \d|reabrindo|pulad|ainda na tela", re.I)
_RX_CAPTCHA = re.compile(r"\[captcha\]", re.I)
_RX_OK = re.compile(r"\[ok\]|conclu[íi]d|autenticado|saiu da conta", re.I)


def _e(v) -> str:
    return html.escape(str(v))


def _uri(caminho: str) -> str:
    try:
        return Path(caminho).resolve().as_uri()
    except Exception:
        return ""


def _fmt_dur(seg: float) -> str:
    seg = int(seg or 0)
    if seg < 60:
        return f"{seg}s"
    m, s = divmod(seg, 60)
    if m < 60:
        return f"{m}min {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}min"


def _classe_log(t: str) -> str:
    if "PROGRESSO:" in t:
        return "p"
    if _RX_ERRO.search(t):
        return "e"
    if _RX_AVISO.search(t):
        return "w"
    if _RX_CAPTCHA.search(t):
        return "c"
    if _RX_OK.search(t):
        return "s"
    return ""


def render(itens: list[dict], meta: dict, log: list, xlsx: Path | None) -> str:
    total = len(itens)
    cont = Counter(i["status"] for i in itens)
    ok, nao_emit = cont.get(CONCLUIDO, 0), cont.get(FATURA_NAO_EMITIDA, 0)
    nao_enc, erros = cont.get(NAO_ENCONTRADO, 0), cont.get(ERRO, 0)
    taxa = (ok / total * 100) if total else 0
    duracoes = [i["duracao_s"] for i in itens if isinstance(i.get("duracao_s"), (int, float))]
    media = sum(duracoes) / len(duracoes) if duracoes else 0
    inicio = meta.get("inicio") or datetime.now()
    fim = datetime.now()

    # barra empilhada
    stack = "".join(
        f'<span title="{_e(_ROTULO[s])}: {n}" style="width:{n / total * 100:.2f}%;'
        f'background:var(--{_CLASSE[s]})"></span>'
        for s, n in ((CONCLUIDO, ok), (FATURA_NAO_EMITIDA, nao_emit), (NAO_ENCONTRADO, nao_enc),
                     (ERRO, erros)) if n) if total else ""

    # problemas (erros primeiro, depois pendências)
    probs = []
    for i in sorted((x for x in itens if x["status"] != CONCLUIDO),
                    key=lambda x: x["status"] != ERRO):
        img = ""
        if i.get("screenshot") and Path(i["screenshot"]).exists():
            u = _uri(i["screenshot"])
            img = f'<a href="{u}" target="_blank"><img src="{u}" alt="print do erro"></a>'
        cls = "" if i["status"] == ERRO else " av"
        probs.append(
            f'<div class="prob{cls}"><div><b>{_e(i["nome_cliente"] or "(sem nome)")} · UC {_e(i["uc"])}'
            f' · {_e(i["mes_referencia"])}</b><span class="badge {_CLASSE[i["status"]]}">'
            f'{_e(_ROTULO.get(i["status"], i["status"]))}</span>'
            f'<div class="m">{_e(i.get("mensagem") or "—")}</div>'
            + (f'<div class="m">login: {_e(i["login"])}</div>' if i.get("login") else "")
            + f'</div>{img}</div>')
    probs_html = "".join(probs) or \
        '<div class="prob" style="border-color:var(--ok);background:var(--ok-bg)"><div>' \
        '<b style="color:var(--ok)">Tudo certo</b><div class="m">Nenhum erro ou pendência nesta execução.</div></div></div>'

    # por login
    por_login = defaultdict(lambda: Counter())
    tempo_login = defaultdict(float)
    for i in itens:
        lg = i.get("login") or "—"
        por_login[lg][i["status"]] += 1
        if isinstance(i.get("duracao_s"), (int, float)):
            tempo_login[lg] += i["duracao_s"]
    linhas_login = "".join(
        f'<tr><td>{_e(lg)}</td><td class="n">{sum(c.values())}</td>'
        f'<td class="n" style="color:var(--ok)">{c.get(CONCLUIDO, 0)}</td>'
        f'<td class="n" style="color:var(--av)">{c.get(FATURA_NAO_EMITIDA, 0) + c.get(NAO_ENCONTRADO, 0)}</td>'
        f'<td class="n" style="color:var(--erro)">{c.get(ERRO, 0)}</td>'
        f'<td class="n">{_fmt_dur(tempo_login[lg])}</td></tr>'
        for lg, c in sorted(por_login.items(), key=lambda kv: -sum(kv[1].values())))

    # CRM
    crm_cont = Counter()
    for i in itens:
        c = i.get("crm") or ""
        crm_cont["enviado" if c and "falha" not in c.lower() else ("falha" if c else "não enviado")] += 1

    # lista completa
    def cel(v, cls=""):
        if v in (None, ""):
            return '<td class="vazio">—</td>'
        return f'<td class="{cls}">{_e(v)}</td>' if cls else f"<td>{_e(v)}</td>"

    linhas = []
    for i in itens:
        pdf = (f'<a href="{_uri(i["arquivo"])}" target="_blank">PDF</a>'
               if i.get("arquivo") and Path(i["arquivo"]).exists() else "")
        shot = (f'<a href="{_uri(i["screenshot"])}" target="_blank">print</a>'
                if i.get("screenshot") and Path(i["screenshot"]).exists() else "")
        links = " · ".join(x for x in (pdf, shot) if x)
        crm = i.get("crm") or ""
        crm_badge = (f'<span class="badge {"erro" if "falha" in crm.lower() else "info"}" '
                     f'title="{_e(crm)}">{_e(crm.split(" ")[0] if crm else "")}</span>' if crm else "")
        dur = _fmt_dur(i["duracao_s"]) if isinstance(i.get("duracao_s"), (int, float)) else ""
        linhas.append(
            f'<tr data-s="{_CLASSE.get(i["status"], "")}">'
            + cel(i["nome_cliente"]) + cel(i["uc"], "n") + cel(i.get("uc_nova"), "n")
            + cel(i["mes_referencia"], "n") + cel(i.get("vencimento"), "n") + cel(i.get("valor"), "n")
            + f'<td><span class="badge {_CLASSE.get(i["status"], "")}">'
              f'{_e(_ROTULO.get(i["status"], i["status"]))}</span></td>'
            + (f"<td>{crm_badge}</td>" if crm else '<td class="vazio">—</td>')
            + cel(dur, "n") + (f"<td class='n'>{links}</td>" if links else '<td class="vazio">—</td>')
            + cel(i.get("mensagem"), "msg") + "</tr>")

    # log
    if log:
        log_html = "".join(
            f'<div class="{_classe_log(t)}"><span class="h">{h:%H:%M:%S}</span>{_e(t)}</div>'
            for h, t in log if t.strip() and not re.fullmatch(r"[\s=\-]+", t))   # sem as linhas "====="
        log_bloco = (
            '<input id="logbusca" placeholder="Procurar no log…">'
            '<label class="sub" style="display:block;margin:-4px 0 10px">'
            '<input type="checkbox" id="logerros" style="width:auto;margin:0 6px 0 0">só erros e avisos</label>'
            f'<div class="log">{log_html}</div>')
    else:
        log_bloco = '<p class="vazio-log">Log não capturado nesta execução (rode pelo painel ou pelo start.py).</p>'

    xlsx_link = (f'<a href="{_uri(str(xlsx))}">planilha .xlsx</a>' if xlsx else "")
    consulta = meta.get("consulta_html")
    consulta_link = (f' · <a href="{_uri(consulta)}">consulta ao CRM</a>'
                     if consulta and Path(consulta).exists() else "")
    cor_taxa = "--ok" if taxa >= 80 else ("--av" if taxa >= 50 else "--erro")

    return f"""<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Relatório da Execução</title><style>{_CSS}</style></head>
<body><div class="wrap">
<h1>Relatório da execução</h1>
<div class="sub">{_e(meta.get("concessionaria", ""))} · {inicio:%d/%m/%Y} das {inicio:%H:%M} às {fim:%H:%M}
 · duração {_fmt_dur((fim - inicio).total_seconds())}</div>
<div class="chips">
  <span class="chip">Fonte <b>{_e(meta.get("fonte", "—"))}</b></span>
  <span class="chip">Retorno pro CRM <b>{"ligado" if meta.get("enviar") else "desligado"}</b></span>
  <span class="chip">Logins <b>{len(por_login)}</b></span>
  {"<span class='chip'>Modo <b>24/7</b></span>" if meta.get("continuo") else ""}
</div>
<nav class="atalhos"><a href="#problemas">Problemas</a><a href="#faturas">Faturas</a>
<a href="#logins">Por login</a><a href="#log">Log</a></nav>

<div class="kpis">
  <div class="kpi"><div class="n">{total}</div><div class="l">faturas processadas</div></div>
  <div class="kpi"><div class="n" style="color:var(--ok)">{ok}</div><div class="l">concluídas</div></div>
  <div class="kpi"><div class="n" style="color:var(--av)">{nao_emit + nao_enc}</div><div class="l">não emitidas / UC não achada</div></div>
  <div class="kpi"><div class="n" style="color:var(--erro)">{erros}</div><div class="l">erros</div></div>
  <div class="kpi"><div class="n" style="color:var({cor_taxa})">{taxa:.0f}%</div><div class="l">taxa de sucesso</div></div>
  <div class="kpi"><div class="n">{_fmt_dur(media)}</div><div class="l">tempo médio / fatura</div></div>
</div>
<div class="stack">{stack}</div>

<div class="grid2">
  <div class="card" id="problemas"><h2>Erros e pendências ({total - ok})</h2>{probs_html}</div>
  <div>
    <div class="card" id="logins"><h2>Por login</h2><div class="tbl"><table>
      <thead><tr><th>login</th><th>faturas</th><th>ok</th><th>pend.</th><th>erro</th><th>tempo</th></tr></thead>
      <tbody>{linhas_login}</tbody></table></div></div>
    <div class="card"><h2>Retorno pro CRM</h2><div class="chips" style="margin-top:0">
      <span class="chip">enviados <b>{crm_cont.get("enviado", 0)}</b></span>
      <span class="chip">falha no envio <b>{crm_cont.get("falha", 0)}</b></span>
      <span class="chip">não enviados <b>{crm_cont.get("não enviado", 0)}</b></span></div></div>
  </div>
</div>

<div class="card" id="faturas"><h2>Todas as faturas</h2>
  <div class="filtros">
    <button class="on" data-f="todos">Todas ({total})</button>
    <button data-f="ok">Concluídas ({ok})</button>
    <button data-f="av">Pendências ({nao_emit + nao_enc})</button>
    <button data-f="erro">Erros ({erros})</button>
  </div>
  <input id="busca" placeholder="Procurar por cliente, UC, mês, mensagem…">
  <div class="tbl"><table id="lista"><thead><tr><th>cliente</th><th>UC</th><th>UC nova</th><th>mês</th>
  <th>vencimento</th><th>valor</th><th>status</th><th>CRM</th><th>tempo</th><th>arquivos</th><th>mensagem</th>
  </tr></thead><tbody>{"".join(linhas)}</tbody></table></div>
</div>

<div class="card" id="log"><h2>Log da execução</h2>{log_bloco}</div>

<footer>Gerado em {fim:%d/%m/%Y %H:%M:%S} · {xlsx_link}{consulta_link}</footer>
</div><script>{_JS}</script></body></html>
"""


def salvar(itens: list[dict], meta: dict, log: list, xlsx: Path) -> Path:
    destino = Path(xlsx).with_suffix(".html")
    destino.write_text(render(itens, meta, log, xlsx), encoding="utf-8")
    return destino
