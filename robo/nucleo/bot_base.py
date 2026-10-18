"""
Base compartilhada dos robôs de concessionária (infra concessionária-AGNÓSTICA):
  - abrir o navegador (Chrome + stealth + extensão opcional + sessão persistente),
  - resolver o reCAPTCHA (captcha_dom + servidor YOLO),
  - login genérico (usuário/senha + captcha) e detecção de senha inválida,
  - screenshot de erro e esperas.

Cada concessionária herda esta base e implementa só o ESPECÍFICO do portal dela:
  - URL_LOGIN (atributo de classe),
  - opcional: _campo_doc / _campo_senha / _botao_entrar / esta_logado (se diferirem),
  - a navegação: processar_faturas_uc(contas_uc) e processar_uc(conta).

A COPEL (copel_bot.CopelBot) NÃO usa esta base — está blindada/intocada.
"""
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

import config


def primeiro_visivel(candidatos, timeout_ms=4000):
    """Devolve o primeiro localizador da lista que estiver visível."""
    fim = time.time() + timeout_ms / 1000
    while time.time() < fim:
        for loc in candidatos:
            try:
                if loc.count() > 0 and loc.first.is_visible():
                    return loc.first
            except Exception:
                pass
        time.sleep(0.2)
    return None


class CredencialInvalida(Exception):
    """Login recusado (senha inválida / conta bloqueada) -> FALHA_LOGIN."""


class BotBase:
    URL_LOGIN = ""   # cada concessionária define

    def __init__(self, login, senha, headless=config.HEADLESS):
        self.login = login
        self.senha = senha
        self.headless = headless
        self._pw = None
        self.context = None
        self.page = None
        self._ext_captcha = False

    # -- ciclo de vida (mesma receita testada do copel_bot) ----------------
    # Modo CDP (Chrome normal + extensões) só vale pra portal com captcha. RGE/CELESC não têm
    # captcha e precisam começar 100% limpos (vários domínios) -> ficam no modo antigo.
    USAR_CDP = False
    DOMINIO_SESSAO = ""   # modo CDP: cookies deste domínio são zerados a cada login

    def __enter__(self):
        self._pw = sync_playwright().start()
        self._cdp = self.USAR_CDP and getattr(config, "MODO_NAVEGADOR", "launch") == "cdp"
        if self._cdp:
            import navegador_cdp
            _, self.context, self.page = navegador_cdp.conectar(self._pw, self.DOMINIO_SESSAO)
            self.context.set_default_timeout(config.TIMEOUT_MS)
            return self
        args = ["--start-maximized",
                # desliga o gerenciador de senhas do Chrome — bloqueia os popups
                # "Mude sua senha" (leak) e "Salvar senha?" que travam a automação
                "--disable-features=PasswordLeakDetection,PasswordManagerOnboarding,AutofillServerCommunication",
                "--disable-save-password-bubble",
                "--password-store=basic"]
        if getattr(config, "STEALTH", False):
            args.append("--disable-blink-features=AutomationControlled")
        ext = getattr(config, "EXTENSAO_CAPTCHA", "") or ""
        self._ext_captcha = bool(ext) and Path(ext).is_dir()
        if self._ext_captcha:
            args += [f"--disable-extensions-except={ext}", f"--load-extension={ext}",
                     "--disable-features=DisableLoadExtensionCommandLineSwitch"]
        usar_headless = self.headless and not self._ext_captcha
        sess = config.pasta_sessao(self.login)
        # desliga o gerenciador de senhas do Chrome via Preferences (reforço às flags): mata
        # o popup "Mude sua senha / senha encontrada em vazamento" que trava a automação.
        try:
            import json
            default = Path(sess) / "Default"
            default.mkdir(parents=True, exist_ok=True)
            (default / "Preferences").write_text(json.dumps({
                "credentials_enable_service": False,
                "profile": {"password_manager_enabled": False,
                            "password_manager_leak_detection": False},
            }), encoding="utf-8")
        except Exception:
            pass
        opcoes = dict(user_data_dir=str(sess),
                      headless=usar_headless, accept_downloads=True, args=args, no_viewport=True)
        if getattr(config, "STEALTH", False):
            opcoes["ignore_default_args"] = ["--enable-automation"]
        if config.CANAL_NAVEGADOR:
            opcoes["channel"] = config.CANAL_NAVEGADOR
        self.context = self._pw.chromium.launch_persistent_context(**opcoes)
        if getattr(config, "STEALTH", False):
            try:
                self.context.add_init_script(
                    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
            except Exception:
                pass
        self.context.set_default_timeout(config.TIMEOUT_MS)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        return self

    def __exit__(self, *exc):
        try:
            if getattr(self, "_cdp", False):
                import navegador_cdp
                navegador_cdp.fechar(self.page)
            elif self.context:
                self.context.close()
        finally:
            if self._pw:
                self._pw.stop()

    # -- login / captcha (reutilizáveis) -----------------------------------
    def esta_logado(self) -> bool:
        try:
            url = (self.page.url or "").lower()
            fora = "login" not in url and "signin" not in url
            senha = self.page.locator("input[type='password']")
            return fora and not (senha.count() > 0 and senha.first.is_visible())
        except Exception:
            return False

    def _tem_recaptcha(self) -> bool:
        try:
            return (self.page.locator("iframe[src*='recaptcha']").count() > 0
                    or self.page.locator(".g-recaptcha").count() > 0)
        except Exception:
            return False

    def _captcha_resolvido(self) -> bool:
        try:
            return bool(self.page.evaluate(
                "() => { const t=document.getElementById('g-recaptcha-response');"
                " return !!(t && t.value && t.value.length>0); }"))
        except Exception:
            return False

    def _erro_login(self) -> bool:
        try:
            loc = self.page.get_by_text(re.compile(
                r"senha\s*inv[aá]lid|senha\s*incorret|(usu[aá]rio|cpf|cnpj|login|dados)"
                r".{0,25}(inv[aá]lid|incorret)|conta.{0,15}bloqu|bloquead", re.I))
            return loc.count() > 0 and loc.first.is_visible()
        except Exception:
            return False

    # subclasse pode sobrescrever se os campos do portal forem diferentes
    def _campo_doc(self):
        return primeiro_visivel([
            self.page.get_by_placeholder(re.compile(r"cnpj|cpf|usu|documento|e-?mail", re.I)),
            self.page.get_by_label(re.compile(r"cnpj|cpf|usu|documento", re.I)),
            self.page.locator("input[type='text']"),
            self.page.locator("input[type='email']"),
        ])

    def _campo_senha(self):
        return primeiro_visivel([
            self.page.get_by_placeholder(re.compile(r"senha", re.I)),
            self.page.locator("input[type='password']"),
        ])

    def _botao_entrar(self):
        return primeiro_visivel([
            self.page.get_by_role("button", name=re.compile(r"entrar|acessar|login", re.I)),
            self.page.locator("input[type='submit']"),
        ], timeout_ms=2000)

    def _marcar_nao_sou_robo(self) -> bool:
        frame = self.page.frame_locator(
            "iframe[src*='api2/anchor'], iframe[title*='reCAPTCHA'], iframe[title*='recaptcha']")
        box = frame.locator("#recaptcha-anchor, .recaptcha-checkbox")
        fim = time.time() + 15
        while time.time() < fim:
            try:
                if box.count() > 0:
                    box.first.click(timeout=4000)
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    def _abrir_login(self):
        """Abre a tela de login. Subclasse sobrescreve se o portal precisar de passos extras
        (ex.: RGE cai numa home com 'Entrar' em vez do formulário)."""
        self.page.goto(self.URL_LOGIN, wait_until="domcontentloaded")
        try:
            self.page.wait_for_load_state("networkidle", timeout=config.TIMEOUT_MS)
        except Exception:
            pass

    def garantir_login(self):
        """Loga (ou reaproveita sessão). Resolve o captcha e detecta senha inválida."""
        if not self.URL_LOGIN:
            raise RuntimeError("URL_LOGIN não definida para esta concessionária.")
        self._abrir_login()
        if self.esta_logado():
            print("   [sessao] ja logado [OK]")
            return

        doc = self._campo_doc()
        senha = self._campo_senha()
        if not doc or not senha:
            raise RuntimeError("Não encontrei os campos de login.")
        doc.click(); doc.fill(self.login); senha.fill(self.senha)
        print("   [login] usuario e senha preenchidos")
        botao = self._botao_entrar()

        if self._tem_recaptcha():
            if (getattr(config, "CAPTCHA_AUTO", True)
                    and getattr(config, "CAPTCHA_METODO", "dom") == "buster"):
                import captcha_buster
                if not captcha_buster.resolver_captcha(
                        self.page, getattr(config, "CAPTCHA_BUSTER_TIMEOUT_S", 120)):
                    raise RuntimeError("captcha: Buster não resolveu (retry reabre o login).")
            elif getattr(config, "CAPTCHA_AUTO", True):
                print("   [captcha] resolvendo no DOM via servidor YOLO...")
                try:
                    import captcha_dom
                    ok = captcha_dom.resolver_captcha(
                        self.page, self.context,
                        getattr(config, "CAPTCHA_SERVIDOR", "http://127.0.0.1:5000/"))
                    print(f"   [captcha] {'token gerado [OK]' if ok else 'não resolveu - resolva na mão'}")
                except Exception as e:
                    print(f"   [captcha] erro no solver: {type(e).__name__}: {e}")
            else:
                self._marcar_nao_sou_robo()
            limite = time.time() + config.TIMEOUT_LOGIN_MS / 1000
            while time.time() < limite:
                if self.esta_logado():
                    print("   [login] autenticado [OK]")
                    return
                if self._captcha_resolvido():
                    break
                time.sleep(1)
            if botao and not self.esta_logado():
                botao.click()
        elif botao:
            botao.click()

        limite = time.time() + config.TIMEOUT_LOGIN_MS / 1000
        while time.time() < limite:
            if self.esta_logado():
                print("   [login] autenticado [OK]")
                return
            if self._erro_login():
                raise CredencialInvalida("Login recusado (senha inválida / conta bloqueada).")
            time.sleep(1)
        raise TimeoutError("Tempo esgotado no login/captcha.")

    def _aguardar_carregamento(self, extra_ms=0):
        try:
            self.page.wait_for_load_state("domcontentloaded")
            self.page.wait_for_load_state("networkidle", timeout=config.TIMEOUT_MS)
        except Exception:
            pass
        if extra_ms:
            time.sleep(extra_ms / 1000)

    def screenshot_erro(self, conta, etapa) -> str:
        try:
            nome = f"erro_{config.sanitizar(conta.get('uc', 'x'))}_{config.sanitizar(etapa)}.png"
            caminho = config.PASTA_SCREENSHOTS / nome
            self.page.screenshot(path=str(caminho), full_page=True)
            return str(caminho)
        except Exception:
            return ""

    # -- navegação: cada concessionária implementa --------------------------
    def _ir_para_selecao_uc(self):
        pass

    def processar_faturas_uc(self, contas_uc):
        raise NotImplementedError

    def processar_uc(self, conta):
        raise NotImplementedError
