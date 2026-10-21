"""
Robô de faturas da COPEL — Rotina 1 (1 login, várias UCs).

Modos:
    python main.py modelo      -> cria a planilha modelo (contas.xlsx)
    python main.py descobrir   -> loga e ajuda a mapear os cliques da parte logada
    python main.py executar    -> processa todas as UCs e gera o relatório .xlsx

Opções:
    --planilha CAMINHO   usa outra planilha de contas
    --headless           roda com o navegador oculto (só quando NÃO precisar de captcha)
"""
import argparse
import os
import sys
from pathlib import Path
import time
from datetime import datetime

# No Windows o console costuma ser cp1252; força UTF-8 pra nenhum print derrubar o robô.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _titulo_console(texto: str):
    """Atualiza o título da janela do terminal (Windows)."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW(texto)
        except Exception:
            pass


def _banner_progresso(atual: int, total: int, conta: dict | None = None):
    faltam = total - atual
    print(f"\n{'=' * 60}")
    print(f"  PROGRESSO: {atual}/{total}  |  faltam {faltam}")
    if conta:
        print(f"  UC: {conta['uc']} — {conta['nome_cliente']}")
    print(f"{'=' * 60}")
    _titulo_console(f"Robo COPEL — {atual}/{total}")

import _caminhos  # noqa: F401  (subpastas de robo/)
import config
from planilha import ler_contas, atualizar_linha
from resultado_log import RegistroResultados, ERRO, NAO_ENCONTRADO, CONCLUIDO, ADIADO
# copel_bot (que carrega o Playwright) é importado só dentro de executar()/descobrir().


def _credenciais():
    """Login/senha da rotina por PLANILHA (do config.py; cai no credenciais.py se vazio)."""
    login = (getattr(config, "PLAN_LOGIN", "") or "").strip()
    senha = (getattr(config, "PLAN_SENHA", "") or "").strip()
    if not (login and senha):
        try:
            import credenciais
            login = login or (getattr(credenciais, "LOGIN", "") or "").strip()
            senha = senha or (getattr(credenciais, "SENHA", "") or "").strip()
        except Exception:
            pass
    if not (login and senha):
        raise SystemExit("Preencha PLAN_LOGIN e PLAN_SENHA no config.py (rotina por planilha).")
    return login, senha


def _gravar_planilha(caminho_planilha, conta: dict, status: str, uc_aneel: str = "",
                     vencimento: str = "", valor: str = ""):
    """Atualiza colunas de resultado na planilha de entrada (pulado quando a fonte é a API)."""
    if not caminho_planilha or "linha" not in conta:
        return
    try:
        atualizar_linha(caminho_planilha, conta["linha"], uc_aneel=uc_aneel,
                        status=status, vencimento=vencimento, valor=valor)
    except PermissionError as e:
        print(f"   [planilha] AVISO: {e}")


def _enum_status(status_interno: str, mensagem: str = "") -> str:
    """Mapeia o status interno do robô -> enum status_leitura da API."""
    from resultado_log import FATURA_NAO_EMITIDA
    from api_faturas import (STATUS_COMPLETE, STATUS_PDF_NAO_ENCONTRADO,
                             STATUS_PDF_ERRO_LEITURA, STATUS_PORTAL_OFFLINE)
    if status_interno == ERRO and mensagem.lower().startswith("portal"):
        return STATUS_PORTAL_OFFLINE      # portal da concessionária com erro (não é o PDF)
    return {
        CONCLUIDO:          STATUS_COMPLETE,
        FATURA_NAO_EMITIDA: STATUS_PDF_NAO_ENCONTRADO,
        NAO_ENCONTRADO:     STATUS_PDF_NAO_ENCONTRADO,   # UC não achada (confirmar enum)
    }.get(status_interno, STATUS_PDF_ERRO_LEITURA)


def _enviar_callback(conta: dict, status_enum: str, r: dict | None = None):
    """Devolve o resultado de uma fatura pra API (POST). Nunca derruba o lote.

    USINA vai pro mesmo corpo/enum, só muda a rota do POST (farms/readings)."""
    from api_faturas import (montar_item_resultado, enviar_resultados,
                             STATUS_COMPLETE, STATUS_DADOS_INCOMPLETOS)
    id_fatura = conta.get("id_fatura")
    if id_fatura is None:
        return
    usina = str(conta.get("fonte") or "").upper() == "USINA"
    rota = getattr(config, "API_ROTA_USINAS", None) if usina else None
    tag = "callback/usina" if usina else "callback"
    try:
        import memoria_tentativas
        memoria_tentativas.registrar(id_fatura, status_enum)
    except Exception:
        pass
    dados, uc_aneel, pdf = {}, "", None
    try:
        if status_enum == STATUS_COMPLETE and r:
            uc_aneel = r.get("uc_nova", "")
            pdf = r.get("arquivo") or None
            dados = {
                "uc_secondary":       uc_aneel,   # CRM renomeou uc_aneel -> uc_secondary
                "ano_mes_referencia": conta.get("mes_referencia", ""),
                "data_vencimento":    r.get("vencimento", ""),
                "valor_total":        r.get("valor", ""),
                "codigo_barras":      r.get("codigo_barras", ""),
            }
            # extrai do PDF os demais campos (nota_fiscal, leituras, kWh, saldo)
            if pdf:
                _rot = (f"id={id_fatura} | {conta.get('nome_cliente', '?')} | "
                        f"UC {conta.get('uc', '?')} | {conta.get('concessionaria', '?')}")
                try:
                    from fatura_pdf import extrair_dados
                    for k, v in extrair_dados(pdf).items():
                        if v:
                            dados[k] = v
                    # PDF abriu, mas pode ter faltado campo (o CRM REJEITA um COMPLETE incompleto)
                    _obrig = ("nota_fiscal", "data_vencimento", "valor_total", "leitura_anterior",
                              "leitura_atual", "proxima_leitura", "kwh_total_consumo")
                    _faltam = [k for k in _obrig if not dados.get(k)]
                    if _faltam:
                        print(f"   [callback] AVISO: PDF lido mas FALTARAM campos {_faltam} "
                              f"({_rot}) | arquivo: {pdf}")
                except Exception as e:
                    try:
                        _tam = os.path.getsize(pdf)
                    except Exception:
                        _tam = -1
                    print(f"   [callback] AVISO: FALHA ao LER o PDF ({_rot}): "
                          f"{type(e).__name__}: {e} | arquivo: {pdf} ({_tam} bytes)")
            # USINA: kwh_injetado é OBRIGATÓRIO (vira 'Resultado (kWh)'). Se o PDF não o
            # trouxe, não manda um COMPLETE furado (o CRM recusaria) -> marca
            # DADOS_INCOMPLETOS pra entrar na retentativa em vez de virar "lido errado".
            if usina and not str(dados.get("kwh_injetado") or "").strip():
                print(f"   [{tag}] AVISO: kwh_injetado vazio -> enviando DADOS_INCOMPLETOS "
                      f"(id={id_fatura}).")
                status_enum, dados, pdf = STATUS_DADOS_INCOMPLETOS, {}, None
        item = montar_item_resultado(id_fatura, status_enum, dados=dados,
                                     uc_aneel=uc_aneel, pdf_path=pdf)
        resp = enviar_resultados([item], rota=rota)
        res = (resp.get("data") or {}).get("resultados") or resp.get("resultados") or []
        if res:
            r0 = res[0]
            conta["_crm"] = f"{status_enum} -> {r0.get('return')} {r0.get('message', '')}".strip()
            print(f"   [{tag}] {status_enum} (id={id_fatura}) -> "
                  f"{r0.get('return')} {r0.get('message', '')}")
        else:
            conta["_crm"] = f"{status_enum} enviado"
            print(f"   [{tag}] {status_enum} enviado (id={id_fatura}).")
    except Exception as e:
        conta["_crm"] = f"falha no envio (na fila): {type(e).__name__}: {e}"
        print(f"   [{tag}] AVISO: falha ao enviar id_fatura={id_fatura}: "
              f"{type(e).__name__}: {e}")
        try:   # não perde o resultado: guarda e reenvia na próxima execução (com a rota certa)
            import fila_crm
            fila_crm.guardar(id_fatura, status_enum, dados, uc_aneel, pdf,
                             f"{type(e).__name__}: {e}", rota=rota)
        except Exception as e2:
            print(f"   [fila CRM] AVISO: não consegui guardar: {e2}")


def _processar_uc(bot, conta: dict, resultado: RegistroResultados, caminho_planilha=None,
                  enviar=False):
    """Processa uma UC com tentativas; registra o status no relatório."""
    from copel_bot import FluxoNaoConfirmado, PassoNaoImplementado
    rotulo = f"{conta['nome_cliente']} (UC {conta['uc']}, {conta['mes_referencia']})"
    inicio = datetime.now()
    ultimo_erro = ""
    for tentativa in range(1, config.MAX_TENTATIVAS + 1):
        try:
            print(f"   [UC] {rotulo} (tentativa {tentativa}/{config.MAX_TENTATIVAS})...")
            r = bot.processar_uc(conta)
            resultado.registrar(conta, r["status"], uc_nova=r.get("uc_nova", ""),
                                arquivo=r.get("arquivo", ""), mensagem=r.get("mensagem", ""),
                                vencimento=r.get("vencimento", ""), valor=r.get("valor", ""),
                                inicio=inicio)
            _gravar_planilha(caminho_planilha, conta, r["status"], r.get("uc_nova", ""),
                             r.get("vencimento", ""), r.get("valor", ""))
            if enviar:
                _enviar_callback(conta, _enum_status(r["status"], r.get("mensagem", "")),
                                 r if r["status"] == CONCLUIDO else None)
            print(f"   [UC] {r['status'].upper()} — {r.get('mensagem','')}")
            return
        except (FluxoNaoConfirmado, PassoNaoImplementado) as e:
            # determinístico: não adianta repetir. Registra como erro e segue.
            resultado.registrar(conta, ERRO, mensagem=str(e), inicio=inicio)
            _gravar_planilha(caminho_planilha, conta, ERRO)
            if enviar:
                _enviar_callback(conta, _enum_status(ERRO))
            print(f"   [UC] PENDENTE: {e}")
            return
        except Exception as e:
            ultimo_erro = f"{type(e).__name__}: {e}"
            print(f"   [UC] falhou: {ultimo_erro}")
            try:
                bot._ir_para_selecao_uc()
            except Exception:
                pass
            if tentativa < config.MAX_TENTATIVAS:
                time.sleep(config.ESPERA_ENTRE_TENTATIVAS * tentativa)  # backoff

    shot = bot.screenshot_erro(conta, "processar_uc")
    resultado.registrar(conta, ERRO, mensagem=ultimo_erro, screenshot=shot, inicio=inicio)
    _gravar_planilha(caminho_planilha, conta, ERRO)
    if enviar:
        _enviar_callback(conta, _enum_status(ERRO))


def _registrar_resultado(conta: dict, r: dict, resultado: RegistroResultados, enviar: bool,
                         caminho_planilha=None):
    """Registra no relatório (+ callback API e/ou grava na planilha) um resultado pronto."""
    resultado.registrar(conta, r["status"], uc_nova=r.get("uc_nova", ""),
                        arquivo=r.get("arquivo", ""), mensagem=r.get("mensagem", ""),
                        vencimento=r.get("vencimento", ""), valor=r.get("valor", ""))
    _gravar_planilha(caminho_planilha, conta, r["status"], r.get("uc_nova", ""),
                     r.get("vencimento", ""), r.get("valor", ""))
    if enviar:
        _enviar_callback(conta, _enum_status(r["status"], r.get("mensagem", "")),
                         r if r["status"] == CONCLUIDO else None)
    print(f"   [UC] {r['status'].upper()} — {r.get('mensagem', '')}")


def _em_pausa(concessionaria: str) -> bool:
    """True se a concessionária está pausada por bloqueio de captcha (e não mandaram ignorar)."""
    from concessionarias import usa_captcha
    if not usa_captcha(concessionaria) or os.environ.get("ROBO_IGNORAR_PAUSA") == "1":
        return False
    import pausa_captcha
    fim = pausa_captcha.ate(concessionaria)
    if not fim:
        return False
    print(f"\n[captcha] {concessionaria} em PAUSA até {fim:%H:%M} — o Google bloqueou o captcha e "
          "insistir aumenta o bloqueio. As faturas continuam pendentes no CRM.")
    print(f"RESUMO (0 UCs):  {concessionaria} em pausa até {fim:%H:%M} (captcha bloqueado pelo Google)")
    return True


def _pausar_por_bloqueio(concessionaria: str, motivo: str):
    import pausa_captcha
    fim = pausa_captcha.ativar(concessionaria, motivo=motivo)
    print(f"   [captcha] {concessionaria} PAUSADA até {fim:%H:%M}. As faturas que faltavam ficam "
          "pendentes (o próximo ciclo pega). Outras concessionárias seguem normais.")
    try:
        import notificacao
        notificacao.alerta(f"captcha_bloqueado_{concessionaria}", f"Captcha bloqueado pelo Google ({concessionaria})",
                           f"O Google respondeu 'Try again later' (consultas automáticas). Pausei a "
                           f"{concessionaria} até {fim:%H:%M}; as faturas que faltavam ficam pendentes e voltam "
                           "no próximo ciclo depois disso. Se repetir sempre, aumente a pausa entre logins.")
    except Exception:
        pass
    return fim


def _separar_problemas(faturas: list[dict]):
    """Tira da fila o que já se sabe que vai dar errado ANTES de abrir o navegador:
      - sem login/senha, sem UC ou com mês inválido -> 'invalidas' (registra o motivo, não loga)
      - mesma UC + mesmo mês repetida -> 'duplicadas' (baixa 1x e copia o resultado pras outras)
    Devolve (para_processar, invalidas[(conta, motivo)], duplicadas[(conta, original)])."""
    ok, invalidas, duplicadas, vistas = [], [], [], {}
    for f in faturas:
        if not f.get("login") or not f.get("senha"):
            invalidas.append((f, "sem login/senha no CRM"))
        elif not f.get("uc"):
            invalidas.append((f, "sem unidade consumidora no CRM"))
        elif not f.get("mes_num"):
            invalidas.append((f, f"mês de referência inválido no CRM ({f.get('mes_referencia')!r})"))
        else:
            chave = (f["uc"], f["mes_referencia"])
            if chave in vistas:
                duplicadas.append((f, vistas[chave]))
            else:
                vistas[chave] = f
                ok.append(f)
    if invalidas:
        print(f"[api] {len(invalidas)} fatura(s) com dado faltando no CRM — não vou logar pra elas:")
        for f, motivo in invalidas[:20]:
            print(f"      id={f.get('id_fatura')} UC={f.get('uc') or '-'} — {motivo}")
    if duplicadas:
        print(f"[api] {len(duplicadas)} fatura(s) duplicada(s) (mesma UC+mês) — baixo 1x e copio o resultado.")
    return ok, invalidas, duplicadas


def _registrar_invalidas(invalidas, resultado: RegistroResultados, enviar: bool):
    from api_faturas import STATUS_FALHA_LOGIN
    import memoria_tentativas
    for f, motivo in invalidas:
        resultado.registrar(f, ERRO, mensagem=f"dado inválido: {motivo}")
        if enviar and "login" in motivo:
            _enviar_callback(f, STATUS_FALHA_LOGIN)          # CRM fica sabendo que falta a credencial
        else:
            memoria_tentativas.registrar(f.get("id_fatura"), "DADOS_INVALIDOS")


def _resolver_duplicadas(duplicadas, resultado: RegistroResultados, enviar: bool):
    for dup, original in duplicadas:
        base = next((i for i in resultado.itens if i.get("_conta") is original), None)
        if not base:
            resultado.registrar(dup, ERRO, mensagem=f"duplicada da fatura id {original.get('id_fatura')} (sem resultado)")
            continue
        r = {"status": base["status"], "uc_nova": base.get("uc_nova", ""), "arquivo": base.get("arquivo", ""),
             "vencimento": base.get("vencimento", ""), "valor": base.get("valor", ""),
             "mensagem": f"mesmo resultado da fatura id {original.get('id_fatura')} (UC+mês repetidos no CRM)"}
        _registrar_resultado(dup, r, resultado, enviar)


def _pos_execucao(resultado: RegistroResultados, html_rel):
    """Histórico + e-mail/alertas + página de histórico. Nunca derruba a execução."""
    try:
        import historico
        import notificacao
        resumo = historico.resumo_execucao(resultado.itens, resultado.meta, str(html_rel or ""))
        historico.registrar(resumo)
        notificacao.ao_fim_execucao(resultado.itens, resumo, str(html_rel) if html_rel else None)
    except Exception as e:
        print(f"[pos-execucao] aviso: {type(e).__name__}: {e}")
    try:
        import relatorio_historico
        relatorio_historico.gerar()
    except Exception as e:
        print(f"[historico] aviso: {type(e).__name__}: {e}")


def executar(headless, limite=0, enviar=False, concessionaria="COPEL", incluir_usinas=True):
    """Produção: busca as faturas da concessionária na API, agrupa por login e processa.

    incluir_usinas: também puxa a fila de usinas (farms/readings) e processa junto — o
    mesmo portal/PDF/callback, cada conta marcada com fonte='USINA' decide a rota do POST."""
    from concessionarias import get_info, get_bot
    from api_faturas import buscar_faturas, buscar_usinas, STATUS_FALHA_LOGIN, STATUS_PORTAL_OFFLINE

    info = get_info(concessionaria)
    if not info["pronta"]:
        print(f"\n[erro] Concessionária {concessionaria} ainda não está pronta "
              f"(falta a receita do portal).\n")
        return
    Bot = get_bot(concessionaria)
    config.PASTA_FATURAS = config.pasta_faturas_de(concessionaria)  # faturas/<CONCESSIONARIA>

    if _em_pausa(concessionaria):
        return
    if enviar:   # primeiro, entrega o que ficou pendente de execuções anteriores
        try:
            import fila_crm
            fila_crm.reenviar()
        except Exception as e:
            print(f"[fila CRM] aviso: {type(e).__name__}: {e}")

    try:
        faturas = buscar_faturas(alias=info["alias_api"])
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        print(f"\n[api] ERRO ao buscar faturas em {config.API_BASE_URL}")
        print(f"      {msg}")
        print("[api] Confira a URL/token no painel (Configuração API) e se o CRM está no ar.")
        print(f"RESUMO (0 UCs):  ERRO na API — {msg[:180]}")   # aparece no painel
        try:
            import historico
            import notificacao
            historico.registrar({"concessionaria": concessionaria, "fonte": "API (CRM)", "total": 0,
                                 "ok": 0, "pendencias": 0, "erros": 0, "erro_api": msg[:300]})
            notificacao.alerta("crm_offline", "CRM fora do ar / sem resposta",
                               f"{concessionaria}: não consegui buscar as faturas em {config.API_BASE_URL}. {msg[:300]}")
        except Exception:
            pass
        return
    # Fila de usinas: mesma concessionária, mesmo portal. Se a chave não tiver o escopo
    # farms:readings:* (HTTP 403) ou der qualquer erro, loga e segue só com os títulos.
    if incluir_usinas:
        try:
            usinas = buscar_usinas(alias=info["alias_api"])
            if usinas:
                print(f"[api] +{len(usinas)} usina(s) na fila (farms/readings).")
            faturas = faturas + usinas
        except Exception as e:
            print(f"[api] AVISO: fila de usinas indisponível ({type(e).__name__}: {e}). "
                  f"Seguindo só com os títulos.")
    if os.environ.get("ROBO_CONTINUO") == "1":
        # modo 24/7: não re-tenta a cada ciclo o que acabou de falhar/concluir
        import memoria_tentativas
        faturas, puladas = memoria_tentativas.filtrar_pendentes(faturas)
        if puladas:
            print(f"[24h] {len(puladas)} fatura(s) puladas (tentadas há pouco):")
            for c, motivo in puladas[:30]:
                print(f"      id={c.get('id_fatura')} UC={c.get('uc')} — {motivo}")
    faturas, invalidas, duplicadas = _separar_problemas(faturas)
    if limite and limite > 0:
        faturas = faturas[:limite]
        print(f"[api] limite {limite}: processando só as {len(faturas)} primeira(s) fatura(s).")
    total = len(faturas)
    if total == 0 and not invalidas:
        print(f"\n[api] Nenhuma fatura pendente pra {concessionaria}. Nada a fazer.\n")
        return

    # login/senha vêm POR fatura -> agrupa por credencial (loga 1x por login)
    grupos: dict[tuple, list[dict]] = {}
    for f in faturas:
        grupos.setdefault((f["login"], f["senha"]), []).append(f)

    resultado = RegistroResultados()
    resultado.meta.update(concessionaria=concessionaria, fonte="API (CRM)", enviar=enviar,
                          continuo=os.environ.get("ROBO_CONTINUO") == "1",
                          consulta_html=str(__import__("relatorio_crm").caminho(info["alias_api"]).with_suffix(".html")))
    _registrar_invalidas(invalidas, resultado, enviar)
    print(f"\n{total} fatura(s) em {len(grupos)} login(s).")
    print(f"  PDFs:      {config.PASTA_FATURAS}")
    print(f"  Relatório: {config.PASTA_RESULTADOS}")
    print(f"  Retorno API (POST): {'LIGADO' if enviar else 'desligado (use --enviar)'}\n")
    _titulo_console(f"Robo COPEL — 0/{total}")

    # erro de credencial (senha errada) -> NÃO adianta re-tentar; qualquer outro erro de
    # login é tratado como transitório (ex.: COPEL "Ocorreu um erro inesperado. Tente
    # novamente mais tarde!!", que RESETA o form) -> reabre o navegador limpo e re-tenta.
    # CredencialInvalida existe em DOIS módulos (copel_bot tem a sua; bot_base tem outra, usada
    # por RGE/CELESC) -> captura AS DUAS, senão o erro de credencial vira "transitório" e o
    # robô re-tenta à toa (e marca PORTAL_OFFLINE em vez de FALHA_LOGIN).
    import importlib
    _cred = []
    for _m in ("copel_bot", "bot_base"):
        try:
            _cred.append(getattr(importlib.import_module(_m), "CredencialInvalida"))
        except Exception:
            pass
    class _CredNunca(Exception):
        pass
    CRED_EXC = tuple(_cred) if _cred else (_CredNunca,)
    MAX_LOGIN = getattr(config, "MAX_TENTATIVAS_LOGIN", 3)
    PAUSA_RETRY = getattr(config, "PAUSA_RETRY_LOGIN_S", 5)
    # portal COM captcha (COPEL) sofre rate-limit -> espaça os logins; sem captcha (RGE) = 0.
    from concessionarias import usa_captcha
    PAUSA_LOGINS = (getattr(config, "PAUSA_ENTRE_LOGINS_CAPTCHA_S", 15) if usa_captcha(concessionaria)
                    else getattr(config, "PAUSA_ENTRE_LOGINS_S", 0))

    idx = 0
    try:
        from captcha_buster import CaptchaBloqueado
    except Exception:
        class CaptchaBloqueado(Exception):
            pass
    lista_grupos = list(grupos.items())
    bloqueio = None             # Google bloqueou o captcha -> para a concessionária
    for grupo_i, ((login, senha), itens) in enumerate(lista_grupos):
        if bloqueio is not None:
            break
        if grupo_i > 0 and PAUSA_LOGINS > 0:
            print(f"   [pausa] {PAUSA_LOGINS}s antes do próximo login (evita rate-limit)...")
            time.sleep(PAUSA_LOGINS)
        print("=" * 60)
        print(f"LOGIN: {login}  ({len(itens)} fatura(s))")
        print("=" * 60)
        inicio_login = datetime.now()

        processou = False           # logou e processou o grupo (não precisa re-tentar)
        credencial_ruim = None      # exceção de senha inválida (não re-tenta)
        ultimo_erro = None          # último erro transitório (login/navegador)

        for tentativa in range(1, MAX_LOGIN + 1):
            try:
                with Bot(login, senha, headless=headless) as bot:
                    try:
                        bot.garantir_login()
                    except CRED_EXC as e:
                        credencial_ruim = e     # senha errada / cadastro -> não re-tenta
                    except CaptchaBloqueado as e:
                        bloqueio = e            # NÃO re-tenta: insistir aumenta o bloqueio
                        try:
                            bot.screenshot_erro({"uc": "login"}, "captcha_bloqueado")
                        except Exception:
                            pass
                    except Exception as e:
                        ultimo_erro = e         # transitório -> reabre e re-tenta
                        print(f"   [login] tentativa {tentativa}/{MAX_LOGIN} falhou: "
                              f"{type(e).__name__}: {e}")
                        try:
                            bot.screenshot_erro({"uc": "login"}, f"login_t{tentativa}")
                        except Exception:
                            pass
                    else:
                        # LOGOU: a partir daqui NÃO re-loga (erro de processamento não re-tenta)
                        processou = True
                        try:
                            # sub-agrupa por UC: mesma UC (vários meses) = seleciona 1x e troca o mês
                            por_uc: dict[str, list[dict]] = {}
                            for c in itens:
                                por_uc.setdefault(c["uc"], []).append(c)
                            for uc, contas_uc in por_uc.items():
                                try:
                                    resultados_uc = bot.processar_faturas_uc(contas_uc)
                                except Exception as e:
                                    print(f"   [UC {uc}] otimização falhou "
                                          f"({type(e).__name__}: {e}) -> modo individual.")
                                    resultados_uc = [None] * len(contas_uc)
                                for c, r in zip(contas_uc, resultados_uc):
                                    idx += 1
                                    _banner_progresso(idx, total, c)
                                    if r is not None:
                                        _registrar_resultado(c, r, resultado, enviar)
                                    else:
                                        _processar_uc(bot, c, resultado, enviar=enviar)
                        except Exception as e:
                            print(f"   [erro] processamento do grupo: {type(e).__name__}: {e}")
            except Exception as e:
                ultimo_erro = e   # erro ao abrir/fechar o navegador
                print(f"   [erro] navegador: {type(e).__name__}: {e}")

            if processou or credencial_ruim is not None or bloqueio is not None:
                break
            if tentativa < MAX_LOGIN:
                # backoff CRESCENTE: o "erro inesperado" da COPEL é rate-limit/sobrecarga
                # ("tente mais tarde") -> esperar mais a cada tentativa dá tempo do bloqueio abrir.
                espera = PAUSA_RETRY * tentativa      # 5s, 10s, 15s...
                print(f"   [login] reabrindo o navegador e tentando de novo em {espera}s "
                      f"({tentativa + 1}/{MAX_LOGIN})...")
                time.sleep(espera)

        if bloqueio is not None:
            fim = _pausar_por_bloqueio(concessionaria, str(bloqueio))
            restantes = [c for _, its in lista_grupos[grupo_i:] for c in its]
            for c in restantes:          # sem callback: continuam pendentes no CRM
                idx += 1
                resultado.registrar(c, ADIADO, inicio=inicio_login,
                                    mensagem=f"captcha bloqueado pelo Google — tenta de novo após {fim:%H:%M}")
            break

        # esgotou as tentativas sem processar -> registra a falha do grupo
        if not processou:
            if credencial_ruim is not None:
                status_enum, msg = STATUS_FALHA_LOGIN, f"login: {credencial_ruim}"
                print(f"   [login] FALHOU (credencial inválida): {credencial_ruim}")
            else:
                status_enum, msg = STATUS_PORTAL_OFFLINE, f"login/portal: {ultimo_erro}"
                print(f"   [login] FALHOU após {MAX_LOGIN} tentativa(s): {ultimo_erro}")
            for c in itens:
                idx += 1
                resultado.registrar(c, ERRO, mensagem=msg, inicio=inicio_login)
                if enviar:
                    _enviar_callback(c, status_enum)

    _resolver_duplicadas(duplicadas, resultado, enviar)
    _titulo_console(f"Robo COPEL — concluido {total}/{total}")
    caminho = resultado.salvar_excel()
    html_rel = resultado.salvar_html(caminho)
    _pos_execucao(resultado, html_rel)
    resultado.imprimir_resumo()
    if html_rel:
        print(f"Relatório HTML: {html_rel}")
    print(f"Relatório salvo em: {caminho}\n")


def executar_planilha(limite=0, concessionaria="COPEL"):
    """Rotina por PLANILHA: 1 login único (config) + contas.xlsx. Baixa os PDFs e gera
    o relatório na Área de Trabalho, e grava o resultado de volta na planilha. NÃO manda
    pro CRM (é a rotina local/standalone)."""
    if _em_pausa(concessionaria):
        return
    from concessionarias import get_info, get_bot
    if not get_info(concessionaria)["pronta"]:
        print(f"\n[erro] Concessionária {concessionaria} ainda não está pronta.\n")
        return
    Bot = get_bot(concessionaria)
    config.PASTA_FATURAS = config.pasta_faturas_de(concessionaria)  # faturas/<CONCESSIONARIA>

    if not config.PLANILHA_CONTAS.exists():
        from criar_modelo import criar_modelo
        criar_modelo()
        print("\n[plan] Criei o contas.xlsx. Preencha as UCs e o PLAN_LOGIN/PLAN_SENHA "
              "no config.py, e rode de novo.\n")
        return

    login, senha = _credenciais()
    contas = ler_contas(config.PLANILHA_CONTAS)
    if limite and limite > 0:
        contas = contas[:limite]
        print(f"[plan] limite {limite}: processando só as {len(contas)} primeira(s).")
    total = len(contas)
    caminho_planilha = config.PLANILHA_CONTAS
    resultado = RegistroResultados()
    resultado.meta.update(concessionaria=concessionaria, fonte="Planilha (local)", enviar=False)
    print(f"\nRotina PLANILHA — {total} UC(s), login {login}.")
    print(f"  PDFs:      {config.PASTA_FATURAS}")
    print(f"  Relatório: {config.PASTA_RESULTADOS}\n")
    _titulo_console(f"Robo COPEL [plan] — 0/{total}")

    inicio_login = datetime.now()
    try:
        with Bot(login, senha, headless=False) as bot:
            try:
                bot.garantir_login()
            except Exception as e:
                shot = bot.screenshot_erro({"uc": "login"}, "login")
                bloqueado = type(e).__name__ == "CaptchaBloqueado"
                fim = _pausar_por_bloqueio(concessionaria, str(e)) if bloqueado else None
                for c in contas:
                    if bloqueado:
                        resultado.registrar(c, ADIADO, screenshot=shot, inicio=inicio_login,
                                            mensagem=f"captcha bloqueado pelo Google — tenta de novo após {fim:%H:%M}")
                        continue
                    resultado.registrar(c, ERRO, mensagem=f"login: {type(e).__name__}: {e}",
                                        screenshot=shot, inicio=inicio_login)
                    _gravar_planilha(caminho_planilha, c, ERRO)
                print(f"   [login] FALHOU: {e}")
            else:
                por_uc: dict[str, list[dict]] = {}
                for c in contas:
                    por_uc.setdefault(c["uc"], []).append(c)
                idx = 0
                for uc, contas_uc in por_uc.items():
                    try:
                        resultados_uc = bot.processar_faturas_uc(contas_uc)
                    except Exception as e:
                        print(f"   [UC {uc}] otimização falhou ({type(e).__name__}) -> individual.")
                        resultados_uc = [None] * len(contas_uc)
                    for c, r in zip(contas_uc, resultados_uc):
                        idx += 1
                        _banner_progresso(idx, total, c)
                        if r is not None:
                            _registrar_resultado(c, r, resultado, enviar=False,
                                                 caminho_planilha=caminho_planilha)
                        else:
                            _processar_uc(bot, c, resultado, caminho_planilha=caminho_planilha,
                                          enviar=False)
    except Exception as e:
        for c in contas:
            resultado.registrar(c, ERRO, mensagem=f"navegador: {type(e).__name__}: {e}",
                                inicio=inicio_login)
        print(f"   [erro] {e}")

    _titulo_console(f"Robo COPEL [plan] — concluido {total}/{total}")
    caminho = resultado.salvar_excel()
    html_rel = resultado.salvar_html(caminho)
    _pos_execucao(resultado, html_rel)
    resultado.imprimir_resumo()
    if html_rel:
        print(f"Relatório HTML: {html_rel}")
    print(f"Relatório salvo em: {caminho}\n")


def descobrir(caminho_planilha):
    from copel_bot import CopelBot
    login, senha = _credenciais()
    ler_contas(caminho_planilha)  # valida a planilha antes de abrir o navegador
    print(f"\n[descoberta] Login único da Rotina 1.\n")
    with CopelBot(login, senha, headless=False) as bot:
        bot.descobrir()


def testar(caminho_planilha):
    """Roda fluxo completo por UC; grava planilha e segue em caso de não encontrado."""
    from copel_bot import CopelBot
    from resultado_log import FATURA_NAO_EMITIDA
    login, senha = _credenciais()
    contas = ler_contas(caminho_planilha)
    total = len(contas)
    print(f"\n[teste] {total} UC(s) na planilha.\n")
    _titulo_console(f"Robo COPEL [teste] — 0/{total}")
    with CopelBot(login, senha, headless=False) as bot:
        bot.garantir_login()
        for idx, conta in enumerate(contas, start=1):
            _banner_progresso(idx, total, conta)
            rotulo = f"{conta['uc']} ({conta['nome_cliente']})"
            print(f"   [teste] Processando {rotulo}...")
            r = bot.testar_ate_segunda_via(conta)
            _gravar_planilha(caminho_planilha, conta, r["status"], r.get("uc_nova", ""),
                             r.get("vencimento", ""), r.get("valor", ""))
            print(f"   [teste] {r['status'].upper()} — {r.get('mensagem', '')}")
            if r["status"] in (NAO_ENCONTRADO, FATURA_NAO_EMITIDA):
                continue
    _titulo_console(f"Robo COPEL [teste] — concluido {total}/{total}")
    print(f"\n[teste] Planilha atualizada: {caminho_planilha}\n")


def testar_api():
    """Só testa a conexão com a API e lista as faturas recebidas (sem navegador)."""
    from api_faturas import buscar_faturas, buscar_usinas
    faturas = buscar_faturas()
    print(f"\n[api] {len(faturas)} fatura(s) recebida(s) "
          f"(concessionária {config.CONCESSIONARIA_ALIAS or 'todas'}):")
    for c in faturas:
        print(f"   id={c['id_fatura']} | login={c['login']} | UC={c['uc']} "
              f"| mês={c['mes_referencia']} | uc_aneel(API)={c['uc_aneel_api']}")
    try:
        usinas = buscar_usinas()
        print(f"\n[api] {len(usinas)} usina(s) na fila (farms/readings):")
        for c in usinas:
            print(f"   id={c['id_fatura']} | tipo={c['fonte']} | login={c['login']} "
                  f"| UC={c['uc']} | mês={c['mes_referencia']} | uc_aneel(API)={c['uc_aneel_api']}")
    except Exception as e:
        print(f"\n[api] AVISO: fila de usinas indisponível ({type(e).__name__}: {e}).")


def main():
    parser = argparse.ArgumentParser(description="Robô de faturas da COPEL — Rotina 1")
    parser.add_argument("modo", nargs="?", default="executar",
                        choices=["modelo", "descobrir", "testar", "executar", "api", "plan",
                                 "email"])
    parser.add_argument("--planilha", default=config.PLANILHA_CONTAS)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--limite", type=int, default=0,
                        help="processa só as N primeiras faturas (0 = todas)")
    parser.add_argument("--enviar", action="store_true",
                        help="devolve o resultado de cada fatura pra API (POST)")
    parser.add_argument("--tudo", action="store_true",
                        help="modo e-mail: manda TODA fatura do e-mail (push puro), não só as pendentes")
    parser.add_argument("--sem-usinas", dest="sem_usinas", action="store_true",
                        help="não puxa a fila de usinas (farms/readings); só os títulos")
    args = parser.parse_args()

    if args.modo == "modelo":
        from criar_modelo import criar_modelo
        criar_modelo()
    elif args.modo == "descobrir":
        descobrir(args.planilha)
    elif args.modo == "testar":
        testar(args.planilha)
    elif args.modo == "api":
        testar_api()
    elif args.modo == "plan":
        executar_planilha(limite=args.limite)
    elif args.modo == "email":
        import email_faturas
        if getattr(args, "tudo", False):
            email_faturas.executar_tudo(enviar=args.enviar, limite=args.limite)
        else:
            email_faturas.executar(enviar=args.enviar, limite=args.limite)
    else:
        executar(headless=args.headless, limite=args.limite, enviar=args.enviar,
                 incluir_usinas=not args.sem_usinas)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[interrompido pelo usuário]")
        sys.exit(1)
