"""
E-mails do robô: relatório de cada execução, resumo diário e alertas.

Configurado no painel (aba "E-mail"), salvo em config_local.json, chave "email"
(a senha do SMTP fica criptografada). Quando enviar:
    cada_execucao  -> ao fim de cada execução (com o relatório HTML anexado)
    so_com_erro    -> só quando a execução teve erro
    resumo_diario  -> 1 e-mail por dia, no horário escolhido (modo 24/7)
    desligado
Alertas (independente do "quando"): CRM fora do ar, captcha falhando, taxa de sucesso
baixa, ciclo do 24/7 travado, disco cheio. Cada tipo de alerta vai no máximo 1x a cada 2h.
"""
import json
import mimetypes
import shutil
import smtplib
import ssl
import time
from datetime import datetime
from email.message import EmailMessage
from html import escape
from pathlib import Path

import config

PROVEDORES = {   # preenchimento rápido no painel
    "Gmail / Google Workspace": ("smtp.gmail.com", 587, "starttls"),
    "Outlook / Microsoft 365":  ("smtp.office365.com", 587, "starttls"),
    "Hostinger":                ("smtp.hostinger.com", 465, "ssl"),
    "Locaweb":                  ("email-ssl.com.br", 465, "ssl"),
    "Outro (preencher)":        ("", 587, "starttls"),
}
_ARQ_ALERTAS = Path(config.PASTA_DADOS) / "alertas_enviados.json"
_INTERVALO_ALERTA_S = 2 * 3600


def cfg() -> dict:
    """Config de e-mail do config_local.json (com a senha já descriptografada)."""
    try:
        local = json.loads((Path(config.RAIZ) / "config_local.json").read_text(encoding="utf-8"))
    except Exception:
        local = {}
    c = dict(local.get("email") or {})
    try:
        import segredos
        c["senha"] = segredos.revelar(c.get("senha", ""))
    except Exception:
        c["senha"] = ""
    c.setdefault("quando", "desligado")
    c.setdefault("alertas", True)
    c.setdefault("limite_taxa", 50)
    c.setdefault("hora_resumo", 18)
    c["destinatarios"] = [d.strip() for d in str(c.get("destinatarios", "")).replace(";", ",").split(",")
                          if d.strip()]
    return c


def configurado(c: dict | None = None) -> bool:
    c = c or cfg()
    return bool(c.get("smtp_host") and c.get("destinatarios") and (c.get("remetente") or c.get("usuario")))


def enviar(assunto: str, html: str, anexos: list | None = None, c: dict | None = None) -> bool:
    c = c or cfg()
    if not configurado(c):
        print("[email] não configurado (painel > E-mail) — não enviei.")
        return False
    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = c.get("remetente") or c.get("usuario")
    msg["To"] = ", ".join(c["destinatarios"])
    msg.set_content("Abra este e-mail num leitor com HTML pra ver o relatório.")
    msg.add_alternative(html, subtype="html")
    for a in anexos or []:
        try:
            p = Path(a)
            if not p.exists() or p.stat().st_size > 15_000_000:
                continue
            tipo = (mimetypes.guess_type(p.name)[0] or "application/octet-stream").split("/")
            msg.add_attachment(p.read_bytes(), maintype=tipo[0], subtype=tipo[1], filename=p.name)
        except Exception:
            pass
    host, porta = c["smtp_host"], int(c.get("smtp_porta") or 587)
    seg = c.get("seguranca", "starttls")
    try:
        if seg == "ssl":
            srv = smtplib.SMTP_SSL(host, porta, timeout=30, context=ssl.create_default_context())
        else:
            srv = smtplib.SMTP(host, porta, timeout=30)
            if seg == "starttls":
                srv.starttls(context=ssl.create_default_context())
        with srv:
            if c.get("usuario"):
                srv.login(c["usuario"], c.get("senha", ""))
            srv.send_message(msg)
        print(f"[email] enviado pra {msg['To']}: {assunto}")
        return True
    except Exception as e:
        print(f"[email] FALHA ao enviar ({type(e).__name__}: {e})")
        return False


# --------------------------------------------------------------------- corpo HTML
def _layout(titulo: str, subtitulo: str, corpo: str) -> str:
    return f"""<div style="font-family:Segoe UI,Arial,sans-serif;background:#f1f4f7;padding:20px">
<div style="max-width:640px;margin:0 auto;background:#fff;border-radius:10px;overflow:hidden;border:1px solid #e3e8ee">
<div style="background:#1e6a2b;color:#fff;padding:16px 22px">
<div style="font-size:18px;font-weight:600">{escape(titulo)}</div>
<div style="font-size:12px;color:#c8e6c9">{escape(subtitulo)}</div></div>
<div style="padding:18px 22px;color:#1f2937;font-size:14px">{corpo}</div>
<div style="padding:10px 22px;color:#6b7280;font-size:11px;border-top:1px solid #e3e8ee">
Robô de Faturas · enviado automaticamente</div></div></div>"""


def _kpis(pares) -> str:
    cel = "".join(
        f'<td style="padding:10px;text-align:center;border:1px solid #e3e8ee;border-radius:8px">'
        f'<div style="font-size:22px;font-weight:600;color:{cor}">{escape(str(v))}</div>'
        f'<div style="font-size:11px;color:#6b7280;text-transform:uppercase">{escape(r)}</div></td>'
        for r, v, cor in pares)
    return f'<table style="width:100%;border-collapse:separate;border-spacing:6px"><tr>{cel}</tr></table>'


def _corpo_execucao(itens: list[dict], resumo: dict) -> str:
    from resultado_log import CONCLUIDO
    k = _kpis([("faturas", resumo["total"], "#1f2937"), ("concluídas", resumo["ok"], "#2e7d32"),
               ("pendências", resumo["pendencias"], "#b54708"), ("erros", resumo["erros"], "#b42318"),
               ("sucesso", f"{resumo['taxa']:.0f}%", "#1f2937")])
    probs = [i for i in itens if i["status"] != CONCLUIDO][:25]
    linhas = "".join(
        f'<tr><td style="padding:6px;border-bottom:1px solid #eee">{escape(i.get("nome_cliente") or "")}</td>'
        f'<td style="padding:6px;border-bottom:1px solid #eee">{escape(str(i.get("uc", "")))}</td>'
        f'<td style="padding:6px;border-bottom:1px solid #eee">{escape(i["status"])}</td>'
        f'<td style="padding:6px;border-bottom:1px solid #eee;color:#6b7280">{escape((i.get("mensagem") or "")[:120])}</td></tr>'
        for i in probs)
    tabela = (f'<p style="margin:16px 0 6px;font-weight:600">Erros e pendências</p>'
              f'<table style="width:100%;border-collapse:collapse;font-size:12px">{linhas}</table>'
              if probs else '<p style="color:#2e7d32;font-weight:600">Tudo certo — nenhuma pendência.</p>')
    return k + tabela + '<p style="color:#6b7280;font-size:12px">O relatório completo (com log e prints) vai em anexo.</p>'


def ao_fim_execucao(itens: list[dict], resumo: dict, relatorio_html: str | None) -> None:
    """Chamado no fim de cada execução (main.py)."""
    try:
        c = cfg()
        quando = c.get("quando")
        if configurado(c) and (quando == "cada_execucao" or (quando == "so_com_erro" and resumo["erros"])):
            conc = resumo.get("concessionaria", "")
            sit = "com erros" if resumo["erros"] else "ok"
            enviar(f"[Robô de Faturas] {conc}: {resumo['ok']}/{resumo['total']} concluídas ({sit})",
                   _layout(f"Execução {conc}", f"{datetime.now():%d/%m/%Y %H:%M} · {resumo.get('fonte', '')}",
                           _corpo_execucao(itens, resumo)),
                   [relatorio_html] if relatorio_html else [], c)
        # alertas desta execução
        if c.get("alertas") and resumo["total"]:
            if resumo.get("falha_captcha", 0) >= 3:
                alerta("captcha", "Captcha falhando",
                       f"{resumo['falha_captcha']} logins falharam no captcha ({resumo.get('concessionaria')}). "
                       "Confira se o Buster está instalado/ativo no Chrome do robô.", c)
            if resumo["total"] >= 3 and resumo["taxa"] < float(c.get("limite_taxa", 50)):
                alerta(f"taxa_{resumo.get('concessionaria')}", "Taxa de sucesso baixa",
                       f"{resumo.get('concessionaria')}: só {resumo['taxa']:.0f}% concluídas "
                       f"({resumo['ok']}/{resumo['total']}).", c, [relatorio_html] if relatorio_html else [])
            if resumo.get("crm_falha", 0):
                alerta("crm_envio", "Falha ao devolver resultados pro CRM",
                       f"{resumo['crm_falha']} resultado(s) não foram aceitos pelo CRM e ficaram na fila "
                       "de reenvio (reenvia sozinho na próxima execução).", c)
    except Exception as e:
        print(f"[email] aviso: {type(e).__name__}: {e}")


def alerta(tipo: str, titulo: str, detalhe: str, c: dict | None = None, anexos=None) -> bool:
    """Envia um alerta (no máximo 1x a cada 2h por tipo)."""
    c = c or cfg()
    if not (c.get("alertas") and configurado(c)):
        return False
    try:
        enviados = json.loads(_ARQ_ALERTAS.read_text(encoding="utf-8"))
    except Exception:
        enviados = {}
    if time.time() - enviados.get(tipo, 0) < _INTERVALO_ALERTA_S:
        return False
    corpo = (f'<p style="font-size:15px;color:#b42318;font-weight:600">⚠ {escape(titulo)}</p>'
             f'<p>{escape(detalhe)}</p>')
    ok = enviar(f"[Robô de Faturas] ALERTA: {titulo}",
                _layout("Alerta do robô", f"{datetime.now():%d/%m/%Y %H:%M}", corpo), anexos, c)
    if ok:
        enviados[tipo] = time.time()
        try:
            _ARQ_ALERTAS.write_text(json.dumps(enviados), encoding="utf-8")
        except Exception:
            pass
    return ok


def verificar_disco(c: dict | None = None, minimo_gb: float = 5) -> None:
    try:
        livre = shutil.disk_usage(str(config.RAIZ)).free / 1e9
        if livre < minimo_gb:
            alerta("disco", "Pouco espaço em disco", f"Restam só {livre:.1f} GB livres no NUC.", c)
    except Exception:
        pass


def resumo_diario_se_for_hora(c: dict | None = None) -> None:
    """Modo 24/7: manda o resumo do dia 1x, a partir da hora configurada."""
    c = c or cfg()
    if c.get("quando") != "resumo_diario" or not configurado(c):
        return
    hoje = datetime.now()
    marca = Path(config.PASTA_DADOS) / f".resumo_{hoje:%Y%m%d}"
    if hoje.hour < int(c.get("hora_resumo", 18)) or marca.exists():
        return
    import historico
    dia = [e for e in historico.ler(2) if e["quando"][:10] == hoje.strftime("%Y-%m-%d")]
    tot = {k: sum(e.get(k, 0) for e in dia) for k in ("total", "ok", "pendencias", "erros")}
    taxa = (tot["ok"] / tot["total"] * 100) if tot["total"] else 0
    por_conc: dict = {}
    for e in dia:
        d = por_conc.setdefault(e.get("concessionaria", "?"), {"total": 0, "ok": 0, "erros": 0, "ciclos": 0})
        d["ciclos"] += 1
        for k in ("total", "ok", "erros"):
            d[k] += e.get(k, 0)
    linhas = "".join(
        f'<tr><td style="padding:6px;border-bottom:1px solid #eee">{escape(n)}</td>'
        f'<td style="padding:6px;border-bottom:1px solid #eee">{d["ciclos"]}</td>'
        f'<td style="padding:6px;border-bottom:1px solid #eee">{d["total"]}</td>'
        f'<td style="padding:6px;border-bottom:1px solid #eee;color:#2e7d32">{d["ok"]}</td>'
        f'<td style="padding:6px;border-bottom:1px solid #eee;color:#b42318">{d["erros"]}</td></tr>'
        for n, d in por_conc.items())
    corpo = _kpis([("faturas", tot["total"], "#1f2937"), ("concluídas", tot["ok"], "#2e7d32"),
                   ("pendências", tot["pendencias"], "#b54708"), ("erros", tot["erros"], "#b42318"),
                   ("sucesso", f"{taxa:.0f}%", "#1f2937")])
    corpo += ('<table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:12px">'
              '<tr style="color:#6b7280;text-align:left"><th>concessionária</th><th>execuções</th>'
              f'<th>faturas</th><th>ok</th><th>erros</th></tr>{linhas}</table>' if dia else
              '<p>Nenhuma execução com faturas hoje.</p>')
    hist = Path(config.PASTA_EXTRACAO) / "historico.html"
    if enviar(f"[Robô de Faturas] Resumo de {hoje:%d/%m}: {tot['ok']}/{tot['total']} concluídas",
              _layout("Resumo do dia", f"{hoje:%d/%m/%Y}", corpo), [hist] if hist.exists() else [], c):
        marca.touch()
