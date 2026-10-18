"""
Resolve o reCAPTCHA v2 usando a extensão BUSTER (instalada no Chrome do robô — modo CDP).

Fluxo: marca o "não sou robô"; se abrir o desafio, clica no botão do Buster (o bonequinho
que ele injeta no rodapé do desafio) e espera o token. Se pedir mais de uma solução,
clica de novo. Se o Google bloquear ("tente mais tarde"), desiste rápido pro retry do main.

O solver antigo (captcha_dom.py) continua no projeto — ver CAPTCHA_METODO no config.py.
"""
import time


class CaptchaBloqueado(Exception):
    """Google bloqueou o desafio ("Try again later" / consultas automáticas). Insistir piora:
    quem chama deve PAUSAR a concessionária em vez de re-tentar o login."""

# marca o botão do Buster no rodapé do desafio. Procura o #solver-button; se ele estiver
# num shadow root fechado, marca o "host" — o único item do rodapé que NÃO é botão nativo
# do reCAPTCHA (recarregar / áudio / imagem / ajuda).
_JS_MARCAR_BUSTER = """
() => {
  document.querySelectorAll('[data-robo-buster]').forEach(e => e.removeAttribute('data-robo-buster'));
  let alvo = document.querySelector('#solver-button');
  if (!alvo) {
    const nativos = ['recaptcha-reload-button', 'recaptcha-audio-button',
                     'recaptcha-image-button', 'recaptcha-help-button'];
    const itens = document.querySelectorAll('.rc-buttons > *, .rc-footer .button-holder');
    for (const el of itens) {
      if (nativos.some(id => el.id === id || el.querySelector('#' + id))) continue;
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) { alvo = el; break; }
    }
  }
  if (!alvo) return false;
  alvo.setAttribute('data-robo-buster', '1');
  return true;
}
"""


def _token_ok(page) -> bool:
    try:
        return bool(page.evaluate(
            "() => { const t = document.getElementById('g-recaptcha-response');"
            " return !!(t && t.value && t.value.length > 0); }"))
    except Exception:
        return False


def _frame(page, marca: str):
    for f in page.frames:
        if marca in (f.url or ""):
            return f
    return None


def _desafio_visivel(page) -> bool:
    try:
        loc = page.locator("iframe[src*='api2/bframe']")
        return loc.count() > 0 and loc.first.is_visible()
    except Exception:
        return False


def _bloqueado(bframe) -> bool:
    """Google recusou o áudio ('Seu computador ou rede pode estar enviando consultas
    automáticas' / 'Tente novamente mais tarde')."""
    try:
        loc = bframe.locator(".rc-doscaptcha-header, .rc-doscaptcha-body")
        return loc.count() > 0 and loc.first.is_visible()
    except Exception:
        return False


def _clicar_buster(bframe) -> bool:
    try:
        if not bframe.evaluate(_JS_MARCAR_BUSTER):
            return False
        bframe.locator("[data-robo-buster]").first.click(timeout=3000)
        return True
    except Exception:
        return False


def resolver_captcha(page, timeout_s: int = 120, espera_por_clique_s: int = 25) -> bool:
    """True se o reCAPTCHA gerou o token."""
    anchor = _frame(page, "api2/anchor")
    if anchor:
        try:
            anchor.locator("#recaptcha-anchor").first.click(timeout=5000)
        except Exception:
            pass

    fim = time.time() + timeout_s
    avisou_sem_botao = False
    while time.time() < fim:
        if _token_ok(page):
            return True
        if not _desafio_visivel(page):
            time.sleep(0.5)          # passou direto ou o desafio ainda está abrindo
            continue
        bframe = _frame(page, "api2/bframe")
        if bframe is None:
            time.sleep(0.5)
            continue
        if _bloqueado(bframe):
            print("   [captcha] Google BLOQUEOU o captcha ('Try again later') -> pausando a concessionária.")
            raise CaptchaBloqueado("Google bloqueou o captcha (Try again later / consultas automáticas)")
        if not _clicar_buster(bframe):
            if not avisou_sem_botao:
                print("   [captcha] botão do Buster não apareceu — a extensão está instalada "
                      "no Chrome do robô? (abrir_chrome_robo.bat)")
                avisou_sem_botao = True
            time.sleep(1)
            continue
        print("   [captcha] Buster acionado, aguardando...")
        limite = min(fim, time.time() + espera_por_clique_s)
        while time.time() < limite:
            if _token_ok(page):
                print("   [captcha] resolvido pelo Buster [OK]")
                return True
            if _bloqueado(bframe):
                break
            time.sleep(0.7)
        time.sleep(1)   # sem token: pediu outra solução ou errou -> clica de novo
    return _token_ok(page)
