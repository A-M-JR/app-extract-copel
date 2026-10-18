r"""
Resolve o reCAPTCHA v2 (imagens) DENTRO do navegador, via Playwright, usando o
servidor YOLO local (127.0.0.1:5000) como cérebro — igual a extensão fazia, mas:
  - clica no DOM (NÃO mexe no mouse físico),
  - não sofre com escala de monitor,
  - não precisa de extensão (o Chrome 150 removeu o --load-extension).

Porta a lógica do content.js da extensão. Precisa do servidor no ar:
  captcha-solver\iniciar_servidor.bat
"""
import base64
import time

import requests

import config


# -- helpers de DOM ---------------------------------------------------------
def _token_ok(page) -> bool:
    """True quando o reCAPTCHA já gerou o token (desafio aprovado)."""
    try:
        return bool(page.evaluate(
            "() => { const t = document.getElementById('g-recaptcha-response');"
            " return !!(t && t.value && t.value.length > 0); }"))
    except Exception:
        return False


def _frame(page, marca: str):
    """Devolve o Frame cujo URL contém `marca` (ex.: 'api2/anchor' ou 'api2/bframe')."""
    for f in page.frames:
        if marca in (f.url or ""):
            return f
    return None


def _clicar(frame, seletor: str) -> bool:
    try:
        loc = frame.locator(seletor)
        if loc.count() > 0:
            loc.first.click(timeout=3000)
            return True
    except Exception:
        pass
    return False


def _texto_desafio(bframe) -> str:
    for sel in (".rc-imageselect-desc-no-canonical", ".rc-imageselect-desc"):
        try:
            loc = bframe.locator(sel)
            if loc.count() > 0:
                return loc.first.inner_text().strip()
        except Exception:
            pass
    return ""


def _tem_erro(bframe) -> bool:
    """True se o reCAPTCHA mostrou um aviso de erro: resposta errada, 'selecione mais',
    'selecione todas as imagens correspondentes', etc. -> melhor recarregar do que insistir
    (é o que travava o solver quando faltava selecionar imagens)."""
    seletores = (
        ".rc-imageselect-error-select-more",       # "Selecione todas as imagens correspondentes"
        ".rc-imageselect-incorrect-response",       # "Tente novamente" (errou)
        ".rc-imageselect-error-dynamic-more",       # dinâmico: continue selecionando
        ".rc-imageselect-error-select-something",    # selecione algo
    )
    for sel in seletores:
        try:
            loc = bframe.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                return True
        except Exception:
            pass
    return False


def _imagem_grade_b64(context, bframe):
    """Base64 (dataURL) da imagem grande da grade. Busca a URL do maior <img> e
    baixa via request do contexto (cookies, sem CORS); se falhar, screenshot."""
    src = None
    try:
        src = bframe.evaluate(
            "() => { let u=null,m=0;"
            " for (const im of document.querySelectorAll('.rc-imageselect-tile img'))"
            "   { if (im.src && im.naturalWidth > m) { m = im.naturalWidth; u = im.src; } }"
            " return u; }")
    except Exception:
        pass
    if src and src.startswith("data:"):
        return src
    if src:
        try:
            resp = context.request.get(src)
            if resp.ok:
                return "data:image/png;base64," + base64.b64encode(resp.body()).decode("ascii")
        except Exception:
            pass
    try:  # fallback: screenshot do alvo da grade
        png = bframe.locator("#rc-imageselect-target").first.screenshot()
        return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    except Exception:
        return None


def _clicar_tiles(bframe, cells):
    """Clica os quadrados indicados (pula os já selecionados: clicar de novo desmarca)."""
    tiles = bframe.locator(".rc-imageselect-tile")
    for i in cells:
        try:
            t = tiles.nth(i)
            if "selected" not in (t.get_attribute("class") or ""):
                t.click(timeout=3000)
                time.sleep(0.35)
        except Exception:
            pass


def _post(servidor, payload, timeout=30):
    r = requests.post(servidor, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


# -- desafio por ÁUDIO (faster-whisper no servidor) -------------------------
def _audio_url(bframe):
    """URL do mp3 do desafio de áudio (link de download ou o <audio> source)."""
    for sel, attr in ((".rc-audiochallenge-tdownload-link", "href"), ("#audio-source", "src")):
        try:
            loc = bframe.locator(sel)
            if loc.count() > 0:
                u = loc.first.get_attribute(attr)
                if u:
                    return u
        except Exception:
            pass
    return None


def _audio_bloqueado(bframe) -> bool:
    """reCAPTCHA às vezes bloqueia o áudio ('consultas automatizadas' / doscaptcha)."""
    try:
        if bframe.locator(".rc-doscaptcha-body, .rc-doscaptcha-header").count() > 0:
            return True
        txt = (bframe.locator("body").inner_text() or "").lower()
        return "automated queries" in txt or "consultas automatizadas" in txt
    except Exception:
        return False


class ServidorForaDoAr(Exception):
    """O servidor de captcha (áudio) não respondeu — não adianta insistir; suba o servidor."""


def _resolver_audio(page, context, bframe, servidor, tentativas=4) -> bool:
    """Resolve o captcha pelo ÁUDIO: entra no modo áudio, baixa o mp3, manda pro servidor
    (faster-whisper transcreve) e digita a resposta. True se gerou o token; False se
    bloqueado/recusado (o chamador recarrega e tenta de novo). Se o SERVIDOR estiver fora do
    ar, levanta ServidorForaDoAr (o chamador desiste). Verboso pra diagnóstico."""
    print("   [captcha] tentando resolver por ÁUDIO...")
    # 1) espera e clica o botão de áudio (fone) — pode não estar pronto de cara
    clicou = False
    for _ in range(8):
        if _clicar(bframe, "#recaptcha-audio-button"):
            clicou = True
            break
        time.sleep(0.5)
        bframe = _frame(page, "api2/bframe") or bframe
    if not clicou:
        print("   [captcha] botão de áudio (fone) NÃO encontrado -> recarrego e tento de novo")
        return False
    print("   [captcha] entrei no modo áudio; aguardando o mp3...")
    time.sleep(2.0)
    bframe = _frame(page, "api2/bframe") or bframe

    for tent in range(tentativas):
        if _token_ok(page):
            return True
        if _audio_bloqueado(bframe):
            print("   [captcha] áudio BLOQUEADO pelo reCAPTCHA ('consultas automatizadas') -> recarrego")
            return False
        # 2) espera o mp3 aparecer (link de download ou <audio> source)
        url = None
        for _ in range(10):
            url = _audio_url(bframe)
            if url:
                break
            time.sleep(0.6)
            bframe = _frame(page, "api2/bframe") or bframe
        if not url:
            print("   [captcha] não achei o mp3 do áudio -> recarrego e tento de novo")
            return False
        # 3) baixa o mp3 (cookies da sessão, sem CORS)
        print("   [captcha] baixando o áudio e transcrevendo...")
        try:
            resp = context.request.get(url, timeout=config.TIMEOUT_MS)
            if not resp.ok:
                print(f"   [captcha] download do áudio falhou (HTTP {resp.status})")
                return False
            mp3_b64 = "data:audio/mp3;base64," + base64.b64encode(resp.body()).decode("ascii")
        except Exception as e:
            print(f"   [captcha] erro ao baixar o áudio ({e})")
            return False
        # 4) transcreve no servidor (timeout alto: a 1ª vez baixa o modelo do whisper)
        try:
            r = _post(servidor, {"audio": mp3_b64}, timeout=300)
        except Exception as e:
            print(f"   [captcha] servidor de áudio FORA DO AR ({e}) — suba o servidor do captcha!")
            raise ServidorForaDoAr(str(e))
        texto = (r.get("texto") or "").strip()
        print(f"   [captcha] transcrição: '{texto}'  (bruto: {str(r.get('bruto',''))[:45]})")
        if not texto:
            print("   [captcha] transcrição vazia (servidor atualizado/reiniciado?) -> outro áudio")
            _clicar(bframe, "#recaptcha-reload-button")
            time.sleep(1.3)
            continue
        # 5) digita e verifica
        try:
            bframe.locator("#audio-response").first.fill(texto)
        except Exception as e:
            print(f"   [captcha] não consegui digitar a resposta ({e})")
            return False
        _clicar(bframe, "#recaptcha-verify-button")
        time.sleep(2.5)
        if _token_ok(page):
            return True
        print("   [captcha] áudio recusado -> tento outro")
        _clicar(bframe, "#recaptcha-reload-button")
        time.sleep(1.3)
    return _token_ok(page)


# -- fluxo principal --------------------------------------------------------
def resolver_captcha(page, context, servidor="http://127.0.0.1:5000/",
                     timeout_s=240, max_reloads=20) -> bool:
    """
    Resolve o reCAPTCHA da página em modo ÁUDIO-ONLY: clica no 'não sou robô', entra no
    desafio de áudio, manda o mp3 pro servidor (faster-whisper transcreve) e digita a
    resposta. Sem reconhecimento por imagem. Retorna True se gerou o token.
    """
    # 1) marca o "não sou robô" (dispara o desafio, ou passa direto)
    anchor = _frame(page, "api2/anchor")
    if anchor:
        _clicar(anchor, "#recaptcha-anchor")
    for _ in range(6):
        if _token_ok(page):
            return True
        if _frame(page, "api2/bframe"):
            break
        time.sleep(0.5)

    # 2) ÁUDIO-ONLY — NÃO usamos reconhecimento por IMAGEM (YOLO). Tenta pelo áudio; se o
    #    desafio bloquear/recusar, recarrega e tenta de novo até o timeout/limite. Se o
    #    SERVIDOR estiver fora do ar, desiste na hora (não adianta insistir sem servidor).
    fim = time.time() + timeout_s
    tentativas = 0
    while time.time() < fim and tentativas <= max_reloads:
        if _token_ok(page):
            return True
        bframe = _frame(page, "api2/bframe")
        if bframe is None:
            time.sleep(1)
            continue
        try:
            if _resolver_audio(page, context, bframe, servidor):
                print("   [captcha] resolvido pelo ÁUDIO [OK]")
                return True
        except ServidorForaDoAr as e:
            print(f"   [captcha] servidor de áudio FORA DO AR ({e}) -> desisto. "
                  f"Suba o servidor (start.py / startapi) e rode de novo.")
            return False
        except Exception as e:
            print(f"   [captcha] áudio falhou ({e})")
        # não resolveu (bloqueado/recusado/sem mp3) -> recarrega o desafio e tenta o áudio de novo
        b = _frame(page, "api2/bframe")
        if b:
            _clicar(b, "#recaptcha-reload-button")
        tentativas += 1
        time.sleep(1.5)

    return _token_ok(page)
