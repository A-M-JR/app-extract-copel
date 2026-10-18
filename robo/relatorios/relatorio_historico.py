"""
Página de histórico (Extração-copel/historico.html): como o robô foi nos últimos 30 dias,
por dia e por concessionária. Regerada no fim de cada execução; botão "Histórico" no painel.
"""
import html
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import config
import historico

_CSS = """
:root{--bg:#f4f6f8;--card:#fff;--txt:#1f2937;--muted:#6b7280;--line:#e5e7eb;--ok:#2e7d32;
--av:#b54708;--erro:#b42318;--chip:#eef1f4;--barra:#2e7d32}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#111418;--card:#1a1f25;
--txt:#e5e7eb;--muted:#9aa3ae;--line:#2b323a;--ok:#66bb6a;--av:#fdb022;--erro:#f97066;--chip:#232a32;--barra:#66bb6a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font:15px/1.5 "Segoe UI",system-ui,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:28px 16px 60px}
h1{font-size:25px;margin:0}h2{font-size:14px;margin:0 0 14px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.sub{color:var(--muted);font-size:13px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:22px 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.kpi .n{font-size:28px;font-weight:600;line-height:1.1}.kpi .l{font-size:12px;color:var(--muted);text-transform:uppercase}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin-bottom:16px}
.barras{display:flex;align-items:flex-end;gap:4px;height:160px;border-bottom:1px solid var(--line);padding-top:8px}
.barras div{flex:1;min-width:6px;background:var(--barra);border-radius:4px 4px 0 0;position:relative}
.barras div:hover{opacity:.8}
.eixo{display:flex;gap:4px;font-size:10px;color:var(--muted);margin-top:4px}.eixo span{flex:1;text-align:center;min-width:6px;overflow:hidden}
.tbl{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--muted);font-size:12px;text-transform:uppercase}
.ok{color:var(--ok)}.erro{color:var(--erro)}.av{color:var(--av)}
a{color:inherit}
"""


def _e(v):
    return html.escape(str(v))


def gerar(dias: int = 30) -> Path:
    ent = historico.ler(dias)
    hoje = datetime.now().date()
    datas = [hoje - timedelta(days=i) for i in range(dias - 1, -1, -1)]
    por_dia = defaultdict(lambda: {"total": 0, "ok": 0, "erros": 0, "pend": 0})
    por_conc = defaultdict(lambda: {"total": 0, "ok": 0, "erros": 0, "exec": 0, "crm_off": 0})
    for e in ent:
        d = datetime.fromisoformat(e["quando"]).date()
        dd, cc = por_dia[d], por_conc[e.get("concessionaria") or "?"]
        for k_src, k in (("total", "total"), ("ok", "ok"), ("erros", "erros"), ("pendencias", "pend")):
            dd[k] += e.get(k_src, 0)
        cc["exec"] += 1
        cc["total"] += e.get("total", 0)
        cc["ok"] += e.get("ok", 0)
        cc["erros"] += e.get("erros", 0)
        cc["crm_off"] += 1 if e.get("erro_api") else 0

    sete = [por_dia[d] for d in datas[-7:]]
    t7 = sum(x["total"] for x in sete)
    ok7 = sum(x["ok"] for x in sete)
    er7 = sum(x["erros"] for x in sete)
    taxa7 = ok7 / t7 * 100 if t7 else 0

    barras, eixo = [], []
    for d in datas:
        x = por_dia[d]
        taxa = x["ok"] / x["total"] * 100 if x["total"] else 0
        cor = "var(--barra)" if taxa >= 80 else ("var(--av)" if taxa >= 50 else "var(--erro)")
        barras.append(f'<div title="{d:%d/%m}: {x["ok"]}/{x["total"]} concluídas ({taxa:.0f}%)" '
                      f'style="height:{max(2, taxa):.0f}%;background:{cor if x["total"] else "var(--chip)"}"></div>')
        eixo.append(f"<span>{d:%d}</span>")

    linhas_conc = "".join(
        f"<tr><td>{_e(n)}</td><td>{c['exec']}</td><td>{c['total']}</td><td class='ok'>{c['ok']}</td>"
        f"<td class='erro'>{c['erros']}</td><td>{(c['ok'] / c['total'] * 100 if c['total'] else 0):.0f}%</td>"
        f"<td class='{'erro' if c['crm_off'] else ''}'>{c['crm_off']}</td></tr>"
        for n, c in sorted(por_conc.items()))
    linhas_exec = "".join(
        f"<tr><td>{_e(e['quando'][8:10])}/{_e(e['quando'][5:7])} {_e(e['quando'][11:16])}</td>"
        f"<td>{_e(e.get('concessionaria', ''))}</td><td>{'24/7' if e.get('continuo') else 'manual'}</td>"
        f"<td>{e.get('total', 0)}</td><td class='ok'>{e.get('ok', 0)}</td><td class='erro'>{e.get('erros', 0)}</td>"
        f"<td>{_e(e.get('taxa', 0))}%</td><td>"
        + (f"<a href='{Path(e['relatorio']).resolve().as_uri()}'>abrir</a>"
           if e.get("relatorio") and Path(e["relatorio"]).exists() else
           ("<span class='erro'>CRM fora</span>" if e.get("erro_api") else "—"))
        + "</td></tr>"
        for e in reversed(ent[-60:]))

    pagina = f"""<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Histórico do Robô</title>
<style>{_CSS}</style></head><body><div class="wrap">
<h1>Histórico do robô</h1><div class="sub">Últimos {dias} dias · atualizado em {datetime.now():%d/%m/%Y %H:%M}</div>
<div class="kpis">
 <div class="kpi"><div class="n">{t7}</div><div class="l">faturas (7 dias)</div></div>
 <div class="kpi"><div class="n ok">{ok7}</div><div class="l">concluídas (7 dias)</div></div>
 <div class="kpi"><div class="n erro">{er7}</div><div class="l">erros (7 dias)</div></div>
 <div class="kpi"><div class="n">{taxa7:.0f}%</div><div class="l">taxa de sucesso (7 dias)</div></div>
 <div class="kpi"><div class="n">{len(ent)}</div><div class="l">execuções ({dias} dias)</div></div>
</div>
<div class="card"><h2>Taxa de sucesso por dia</h2><div class="barras">{''.join(barras)}</div>
<div class="eixo">{''.join(eixo)}</div></div>
<div class="card"><h2>Por concessionária</h2><div class="tbl"><table><thead><tr><th>concessionária</th>
<th>execuções</th><th>faturas</th><th>ok</th><th>erros</th><th>sucesso</th><th>CRM fora</th></tr></thead>
<tbody>{linhas_conc or '<tr><td colspan=7>Sem execuções no período.</td></tr>'}</tbody></table></div></div>
<div class="card"><h2>Últimas execuções</h2><div class="tbl"><table><thead><tr><th>quando</th><th>concessionária</th>
<th>origem</th><th>faturas</th><th>ok</th><th>erros</th><th>sucesso</th><th>relatório</th></tr></thead>
<tbody>{linhas_exec or '<tr><td colspan=8>Sem execuções no período.</td></tr>'}</tbody></table></div></div>
</div></body></html>"""
    destino = Path(config.PASTA_EXTRACAO) / "historico.html"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(pagina, encoding="utf-8")
    return destino
