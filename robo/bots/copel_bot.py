"""
Robô da Agência Virtual da COPEL (AVA) — Rotina 1, com Playwright.

Rotina 1: 1 login/senha (em credenciais.py) com várias UCs. Para cada UC:
  1) pesquisa a UC (pela "Unidade consumidora antiga") e clica em Selecione;
  2) captura a "Unidade consumidora ANEEL" (a UC nova) pro log;
  3) abre "Segunda via online";
  4) acha a fatura do mês de referência, baixa e renomeia p/ o nome do cliente.

Tudo por DOM (texto/rótulo real), nada de reconhecimento de imagem.
Login com pausa pro reCAPTCHA + reuso de sessão (perfil persistente por login).

Passos ainda aguardando print:  (nenhum — fluxo 2ª via confirmado).
"""
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, Locator

import config
from resultado_log import CONCLUIDO, NAO_ENCONTRADO, FATURA_NAO_EMITIDA


class FluxoNaoConfirmado(Exception):
    """Levantada enquanto o fluxo completo (com download) não foi confirmado."""


class PassoNaoImplementado(Exception):
    """Um passo da parte logada ainda aguarda o print da tela correspondente."""


class CredencialInvalida(Exception):
    """Login recusado pela COPEL (senha inválida / conta bloqueada) -> FALHA_LOGIN."""


def _primeiro_visivel(candidatos: list[Locator], timeout_ms: int = 4000) -> Locator | None:
    """Devolve o primeiro localizador da lista que estiver visível na tela."""
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


class CopelBot:
    def __init__(self, login: str, senha: str, headless: bool = config.HEADLESS):
        self.login = login
        self.senha = senha
        self.headless = headless
        self._pw = None
        self.context = None
        self.page: Page | None = None

    def _aguardar_carregamento(self, extra_ms: int = 0):
        """Espera DOM + rede + spinner PrimeFaces sumir."""
        self.page.wait_for_load_state("domcontentloaded")
        try:
            self.page.wait_for_load_state("networkidle", timeout=config.TIMEOUT_MS)
        except Exception:
            pass
        for sel in ("#statusDialog", ".modalAguarde", "#j_idt228"):
            try:
                self.page.locator(sel).wait_for(state="hidden", timeout=8000)
            except Exception:
                pass
        if extra_ms > 0:
            time.sleep(extra_ms / 1000)

    def _aguardar_pos_selecao_uc(self):
        """Após clicar Selecione, espera tela de serviços da UC carregar."""
        self._aguardar_carregamento(config.ESPERA_POS_NAVEGACAO_MS)
        limite = time.time() + 25
        while time.time() < limite:
            url = (self.page.url or "").lower()
            if self.page.get_by_text(
                re.compile(r"Unidade consumidora ANEEL", re.I)
            ).count() > 0:
                self._dispensar_modais_iniciais()
                return
            if any(x in url for x in ("inicio.jsf", "todosservicos", "segundaviafatura")):
                self._dispensar_modais_iniciais()
                return
            time.sleep(0.3)
        self._dispensar_modais_iniciais()

    def _dispensar_modais_iniciais(self):
        """Fecha modais que bloqueiam após selecionar UC (ex.: Fatura Digital)."""
        limite = time.time() + 15
        while time.time() < limite:
            achou = False
            modais = self.page.locator(".ui-dialog:visible")
            for i in range(modais.count()):
                modal = modais.nth(i)
                try:
                    texto = modal.inner_text()
                except Exception:
                    continue
                if not re.search(
                    r"fatura\s*digital|fatura enviada por e-mail|cadastrar a fatura",
                    texto, re.I,
                ):
                    continue
                nao = _primeiro_visivel([
                    modal.get_by_role("button", name=re.compile(r"^n[aã]o$", re.I)),
                    modal.locator("button").filter(
                        has_text=re.compile(r"^n[aã]o$", re.I)),
                    modal.locator(".btnSecundario"),
                ], timeout_ms=3000)
                if nao:
                    print("   [modal] Fatura digital — clicando Não...")
                    nao.click()
                    self._aguardar_carregamento(config.ESPERA_POS_AJAX_MS)
                    achou = True
                    break
            if not achou:
                return

    # -- ciclo de vida ------------------------------------------------------
    def __enter__(self):
        self._pw = sync_playwright().start()
        self._cdp = getattr(config, "MODO_NAVEGADOR", "launch") == "cdp"
        if self._cdp:
            # Chrome normal do robô (com Buster). Aba nova, cookies da COPEL zerados.
            import navegador_cdp
            _, self.context, self.page = navegador_cdp.conectar(self._pw, "copel.com")
            self.context.set_default_timeout(config.TIMEOUT_MS)
            return self
        args = ["--start-maximized"]
        if getattr(config, "STEALTH", False):
            args.append("--disable-blink-features=AutomationControlled")

        # extensão do captcha (unpacked). Só funciona com navegador VISÍVEL.
        ext = getattr(config, "EXTENSAO_CAPTCHA", "") or ""
        self._ext_captcha = bool(ext) and Path(ext).is_dir()
        if self._ext_captcha:
            args += [
                f"--disable-extensions-except={ext}",
                f"--load-extension={ext}",
                "--disable-features=DisableLoadExtensionCommandLineSwitch",
            ]

        usar_headless = self.headless and not self._ext_captcha  # extensão exige headed
        opcoes = dict(
            user_data_dir=str(config.pasta_sessao(self.login)),
            headless=usar_headless,
            accept_downloads=True,
            args=args,
            no_viewport=True,
        )
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
        if self._ext_captcha:
            print("   [captcha] extensão carregada (precisa do servidor YOLO em 127.0.0.1:5000).")
        return self

    def __exit__(self, *exc):
        try:
            if getattr(self, "_cdp", False):
                import navegador_cdp
                navegador_cdp.fechar(self.page)   # fecha só a aba; o Chrome fica aberto
            elif self.context:
                self.context.close()
        finally:
            if self._pw:
                self._pw.stop()

    # ======================================================================
    #  LOGIN
    # ======================================================================
    def esta_logado(self) -> bool:
        try:
            url = (self.page.url or "").lower()
            fora_do_login = "login" not in url and "paginalogin" not in url
            campo_senha = self.page.locator("input[type='password']")
            senha_visivel = campo_senha.count() > 0 and campo_senha.first.is_visible()
            return fora_do_login and not senha_visivel
        except Exception:
            return False

    def _tem_recaptcha(self) -> bool:
        try:
            return (self.page.locator("iframe[src*='recaptcha']").count() > 0
                    or self.page.locator(".g-recaptcha").count() > 0)
        except Exception:
            return False

    def _erro_transitorio(self) -> bool:
        """True se a COPEL mostrou erro TRANSITÓRIO de servidor ('Ocorreu um erro inesperado.
        Tente novamente mais tarde') — rate-limit/instabilidade, NÃO é credencial. Serve pra
        falhar RÁPIDO (o retry do main reabre e tenta de novo, sem esperar o timeout todo)."""
        try:
            loc = self.page.get_by_text(re.compile(
                r"erro\s+inesperado|tente\s+novamente\s+mais\s+tarde", re.I))
            return loc.count() > 0 and loc.first.is_visible()
        except Exception:
            return False

    def _banner_erro_sem_texto(self) -> bool:
        """True se há um BANNER DE ERRO visível SEM mensagem (só o ícone vermelho + horário) ->
        FALHA_LOGIN. EXIGE o HORÁRIO (HH:MM:SS) que a COPEL carimba nos erros — assim NÃO
        confunde com o container de mensagem VAZIO do PrimeFaces (que existe sempre e daria
        falso positivo, fechando o login cedo). E não confunde com 'erro inesperado' (tem texto)."""
        try:
            cont = self.page.locator(
                ".ui-messages-error, .ui-message-error, .ui-growl-item, .ui-growl-message, "
                "[class*='alert'][class*='danger' i], [class*='message'][class*='error' i], "
                "[class*='toast'][class*='error' i]")
            for i in range(min(cont.count(), 6)):
                el = cont.nth(i)
                try:
                    if not el.first.is_visible():
                        continue
                    txt = el.inner_text() or ""
                except Exception:
                    continue
                # só é banner de erro DE VERDADE se tiver o horário HH:MM:SS (senão é container vazio)
                if not re.search(r"\b\d{1,2}:\d{2}:\d{2}\b", txt):
                    continue
                resto = re.sub(r"\d{1,2}:\d{2}:\d{2}", "", txt)   # tira o horário -> sobra a mensagem?
                if len(re.sub(r"\s+", "", resto)) < 3:            # sem mensagem -> banner de erro vazio
                    return True
            return False
        except Exception:
            return False

    def _captcha_resolvido(self) -> bool:
        """True quando o reCAPTCHA já gerou o token (você marcou o 'não sou robô')."""
        try:
            return bool(self.page.evaluate(
                "() => { const t = document.getElementById('g-recaptcha-response');"
                " return !!(t && t.value && t.value.length > 0); }"
            ))
        except Exception:
            return False

    def _erro_login(self) -> bool:
        """True se a COPEL mostrou erro que impede o login -> FALHA_LOGIN (não re-tenta):
        senha inválida / conta bloqueada, OU o erro de servidor 'Exception ao consultar
        situação da senha: NullPointerException' (a conta não loga, então segue pro próximo)."""
        try:
            loc = self.page.get_by_text(re.compile(
                r"senha\s*inv[aá]lid|senha\s*incorret|(usu[aá]rio|cpf|cnpj|login|dados)"
                r".{0,25}(inv[aá]lid|incorret)|conta.{0,15}bloqu|bloquead|"
                r"exception ao consultar situa[çc][ãa]o da senha|nullpointerexception", re.I))
            return loc.count() > 0 and loc.first.is_visible()
        except Exception:
            return False

    def _marcar_nao_sou_robo(self) -> bool:
        """Clica o checkbox 'não sou robô' (dentro do iframe do reCAPTCHA), pra disparar
        o desafio que o screen_watcher vai resolver. Espera o iframe carregar."""
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

    def garantir_login(self):
        """Loga (ou reaproveita a sessão). Se cair no captcha, espera você resolver."""
        self.page.goto(config.URL_LOGIN, wait_until="domcontentloaded")
        self.page.wait_for_load_state("networkidle")

        if self.esta_logado():
            print("   [sessao] ja logado (sem captcha) [OK]")
            return

        campo_doc = _primeiro_visivel([
            self.page.locator('[id="formulario:numDoc"]'),
            self.page.get_by_placeholder(re.compile(r"cnpj|cpf", re.I)),
            self.page.locator("input[type='text']"),
        ])
        campo_senha = _primeiro_visivel([
            self.page.locator('[id="formulario:pass"]'),
            self.page.get_by_placeholder(re.compile(r"senha", re.I)),
            self.page.locator("input[type='password']"),
        ])
        if not campo_doc or not campo_senha:
            raise RuntimeError("Não encontrei os campos de login. Rode 'python main.py descobrir'.")

        campo_doc.click()
        campo_doc.fill(self.login)
        campo_senha.fill(self.senha)
        print("   [login] usuario e senha preenchidos")

        botao = _primeiro_visivel([
            self.page.get_by_role("button", name=re.compile(r"entrar|acessar", re.I)),
            self.page.locator("input[type='submit']"),
        ], timeout_ms=2000)

        if self._tem_recaptcha():
            if (getattr(config, "CAPTCHA_AUTO", True)
                    and getattr(config, "CAPTCHA_METODO", "dom") == "buster"):
                import captcha_buster
                ok = captcha_buster.resolver_captcha(
                    self.page, getattr(config, "CAPTCHA_BUSTER_TIMEOUT_S", 120))
                if not ok:
                    raise RuntimeError("captcha: Buster não resolveu (retry reabre o login).")
            elif getattr(config, "CAPTCHA_AUTO", True):
                print("   [captcha] resolvendo no DOM via servidor YOLO...")
                try:
                    import captcha_dom
                    ok = captcha_dom.resolver_captcha(
                        self.page, self.context,
                        getattr(config, "CAPTCHA_SERVIDOR", "http://127.0.0.1:5000/"))
                    print(f"   [captcha] {'token gerado [OK]' if ok else 'não resolveu — resolva na mão'}")
                except Exception as e:
                    print(f"   [captcha] erro no solver: {type(e).__name__}: {e}")
            else:
                self._marcar_nao_sou_robo()
                print("   >>> Resolva o captcha manualmente. Aguardando o token...")
            # aguarda o token (do solver ou manual) e clica Entrar
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

        # espera final do login
        limite = time.time() + config.TIMEOUT_LOGIN_MS / 1000
        while time.time() < limite:
            if self.esta_logado():
                print("   [login] autenticado [OK]")
                return
            if self._erro_login():
                raise CredencialInvalida("Login recusado pela COPEL (senha inválida / conta bloqueada).")
            if self._erro_transitorio():
                # erro de SERVIDOR (rate-limit/instabilidade) -> falha rápido; o retry do main
                # reabre o navegador e tenta de novo (com backoff), sem esperar o timeout todo.
                raise RuntimeError("COPEL: 'Ocorreu um erro inesperado. Tente novamente mais "
                                   "tarde!!' (servidor instável / rate-limit).")
            if self._banner_erro_sem_texto():
                # banner de erro SEM mensagem (só ícone + horário) -> não loga -> FALHA_LOGIN
                raise CredencialInvalida("COPEL: erro no login (banner de erro sem mensagem).")
            time.sleep(1)
        raise TimeoutError("Tempo esgotado esperando o login/captcha.")

    # ======================================================================
    #  ROTINA 1 — processar uma UC
    # ======================================================================
    def processar_uc(self, conta: dict) -> dict:
        uc = conta["uc"]
        mes = conta["mes_referencia"]
        nome_cliente = conta["nome_cliente"]

        self._ir_para_selecao_uc()
        if not self._pesquisar_e_selecionar_uc(uc):
            return {"status": NAO_ENCONTRADO, "uc_nova": "", "vencimento": "", "valor": "",
                    "arquivo": "", "mensagem": f"UC {uc} não localizada"}

        uc_aneel = self._capturar_uc_nova()
        self._dispensar_modais_iniciais()
        self._abrir_segunda_via()

        fatura = self._processar_segunda_via(conta, nome_cliente)
        if fatura is None:
            return {"status": FATURA_NAO_EMITIDA, "uc_nova": uc_aneel,
                    "vencimento": "", "valor": "", "arquivo": "",
                    "mensagem": f"Sem fatura para {mes}"}

        return {
            "status": CONCLUIDO,
            "uc_nova": fatura.get("uc_aneel") or uc_aneel,
            "vencimento": fatura.get("vencimento", ""),
            "valor": fatura.get("valor", ""),
            "arquivo": str(fatura.get("arquivo", "")),
            "mensagem": "Fatura baixada",
        }

    # -- tela "Selecione uma unidade consumidora" ---------------------------
    def _na_selecao_uc(self) -> bool:
        try:
            if self.page.get_by_text(
                    re.compile(r"Selecione uma unidade consumidora", re.I)).count() > 0:
                return True
            # variante "Consultar Débitos no CPF/CNPJ": MESMA tabela (colunas ANEEL/antiga/…),
            # só o título muda -> reconhece pela coluna/filtro "Unidade consumidora antiga".
            th = self.page.locator("th").filter(has_text=re.compile(r"antiga", re.I))
            return th.count() > 0 and th.locator("input").count() > 0
        except Exception:
            return False

    def _esperar_selecao_uc(self, timeout_ms=None) -> bool:
        """Espera chegar à tela de seleção de UC (título OU a coluna 'antiga')."""
        limite = time.time() + (timeout_ms or config.TIMEOUT_MS) / 1000
        while time.time() < limite:
            if self._na_selecao_uc():
                return True
            time.sleep(0.5)
        return False

    def _ir_para_selecao_uc(self):
        """Garante que estamos na tela de seleção de UC (pra próxima UC do lote)."""
        if self._na_selecao_uc():
            return
        # ícone ⇄ (fa-exchange) ao lado da UC antiga no cabeçalho
        trocar = _primeiro_visivel([
            self.page.locator("a:has(i.fa-exchange)"),
            self.page.locator("a:has(i.fa-exchange-alt)"),
            self.page.locator("i.fa-exchange, i.fa-exchange-alt").locator("xpath=ancestor::a[1]"),
            self.page.get_by_role("button", name=re.compile(r"trocar|alterar|unidade", re.I)),
            self.page.locator("a[title*='troca' i], a[title*='unidade' i]"),
        ], timeout_ms=5000)
        if trocar:
            trocar.click()
            self._aguardar_carregamento(config.ESPERA_POS_NAVEGACAO_MS)
            self._esperar_selecao_uc()
            return
        self.page.goto(config.URL_SELECAO_UC, wait_until="domcontentloaded")
        self._aguardar_carregamento(config.ESPERA_POS_NAVEGACAO_MS)

    def _campo_filtro_antiga(self) -> Locator:
        """Campo de filtro da coluna 'Unidade consumidora antiga'."""
        th = self.page.locator("th").filter(has_text=re.compile(r"antiga", re.I))
        if th.count() and th.locator("input").count():
            return th.locator("input").first
        # fallback: a 2ª coluna de filtros do cabeçalho (ANEEL, ANTIGA, ...)
        inputs = self.page.locator("thead input")
        if inputs.count() >= 2:
            return inputs.nth(1)
        raise RuntimeError("Não achei o campo de filtro da 'Unidade consumidora antiga'.")

    def _pesquisar_e_selecionar_uc(self, uc: str) -> bool:
        """Filtra pela UC antiga, e se achar, clica em Selecione. False = não encontrado."""
        if not self._esperar_selecao_uc():
            raise RuntimeError("Não cheguei à tela de seleção de UC "
                               "(nem 'Selecione uma unidade consumidora' nem a coluna 'antiga').")

        campo = self._campo_filtro_antiga()
        campo.click()
        campo.fill("")
        campo.press_sequentially(uc, delay=60)
        time.sleep(0.8)
        campo.press("Enter")
        self._aguardar_carregamento(config.ESPERA_POS_AJAX_MS)

        limite = time.time() + config.ESPERA_FILTRO_UC_MS / 1000
        while time.time() < limite:
            linhas = self.page.locator("tbody tr")
            for i in range(linhas.count()):
                linha = linhas.nth(i)
                try:
                    if uc not in linha.inner_text():
                        continue
                except Exception:
                    continue
                alvo = linha.locator("a, button")
                if alvo.count() == 0:
                    continue
                print(f"   [uc] UC {uc} encontrada — selecionando...")
                alvo.last.click()
                self._aguardar_pos_selecao_uc()
                return True
            if self.page.get_by_text(
                re.compile(r"nenhum registro|não encontr|sem registros", re.I)).count() > 0:
                return False
            time.sleep(0.5)
        return False

    # -- tela de informações da UC ------------------------------------------
    def _capturar_uc_nova(self) -> str:
        """Lê a 'Unidade consumidora ANEEL' no cabeçalho (a UC nova)."""
        try:
            self.page.get_by_text(
                re.compile(r"Unidade consumidora ANEEL", re.I)
            ).first.wait_for(timeout=config.TIMEOUT_MS)
        except Exception:
            pass
        texto = ""
        try:
            texto = self.page.locator("body").inner_text()
        except Exception:
            pass
        m = re.search(r"ANEEL[^0-9]{0,15}(\d{6,})", texto)
        return m.group(1) if m else ""

    def _na_segunda_via(self) -> bool:
        try:
            url = (self.page.url or "").lower()
            if "segundaviafatura" in url:
                return True
            campo = self.page.locator('[id="formSegundaViaFatura:mesRefencia2"]')
            return campo.count() > 0 and campo.first.is_visible()
        except Exception:
            return False

    def _abrir_segunda_via(self):
        """Abre a tela 'Segunda via de fatura' da UC já selecionada."""
        if self._na_segunda_via():
            self._aguardar_tela_segunda_via()
            return

        self._aguardar_carregamento(config.ESPERA_POS_NAVEGACAO_MS)
        print("   [2via] Abrindo Segunda via de fatura...")

        # tile visível em inicio.jsf (Serviços +) — sem expandir "todos os serviços"
        link = _primeiro_visivel([
            self.page.locator('li.linkImagens a[href*="segundaViaFatura"]'),
            self.page.locator('a[href*="segundaViaFatura"]'),
            self.page.locator("li.linkImagens").filter(
                has_text=re.compile(r"segunda\s*via", re.I)).locator("a"),
        ], timeout_ms=8000)
        if link:
            print("   [2via] Clicando Segunda via online...")
            link.click()
            self._aguardar_carregamento(config.ESPERA_POS_NAVEGACAO_MS)
        else:
            print("   [2via] Tile não achado — indo direto pela URL...")
            self.page.goto(config.URL_SEGUNDA_VIA, wait_until="domcontentloaded")
            self._aguardar_carregamento(config.ESPERA_POS_NAVEGACAO_MS)

        self._aguardar_tela_segunda_via()
        print("   [2via] Tela carregada [OK]")

    # -- Segunda via de fatura ------------------------------------------------
    def _aguardar_tela_segunda_via(self):
        limite = time.time() + config.TIMEOUT_MS / 1000
        while time.time() < limite:
            for sel in (
                '[id="formSegundaViaFatura:mesRefencia2"]',
                '[name="formSegundaViaFatura:mesRefencia2"]',
                'input[id*="mesRefencia"]',
            ):
                campo = self.page.locator(sel)
                try:
                    if campo.count() > 0 and campo.first.is_visible():
                        return
                except Exception:
                    pass
            if "segundaviafatura" in (self.page.url or "").lower():
                self._aguardar_carregamento(500)
            time.sleep(0.3)
        raise TimeoutError(
            "Tela 'Segunda via de fatura' não carregou (campo mês não encontrado)."
        )

    def _campo_mes_referencia(self) -> Locator:
        for sel in (
            '[id="formSegundaViaFatura:mesRefencia2"]',
            '[name="formSegundaViaFatura:mesRefencia2"]',
            'input[id*="mesRefencia"]',
        ):
            campo = self.page.locator(sel)
            if campo.count() and campo.first.is_visible():
                return campo.first
        raise RuntimeError("Campo 'Mês de referência' não encontrado.")

    def _digitar_mes(self, campo: Locator, mes: str):
        """Preenche o campo de mês (input mascarado MM/AAAA) de um jeito que a máscara aceite."""
        alvo = mes.strip()
        for _ in range(3):
            campo.click()
            campo.press("Control+a")
            campo.press("Delete")
            campo.press_sequentially(alvo, delay=80)   # digita char a char -> dispara a máscara
            try:
                atual = (campo.input_value() or "").strip()
            except Exception:
                atual = ""
            if atual.replace(" ", "") == alvo.replace(" ", ""):
                return
        # fallback: seta o valor via JS e dispara os eventos
        campo.evaluate(
            "(el, v) => { el.value = v;"
            " el.dispatchEvent(new Event('input', {bubbles: true}));"
            " el.dispatchEvent(new Event('change', {bubbles: true})); }", alvo)

    def _preencher_mes_e_listar(self, mes: str):
        self._aguardar_tela_segunda_via()
        campo = self._campo_mes_referencia()
        self._digitar_mes(campo, mes)
        print(f"   [2via] Mês de referência preenchido = {mes}")
        botao = _primeiro_visivel([
            self.page.locator('[id="formSegundaViaFatura:btnsegundaViaFaturaSegundaVia"]'),
            self.page.get_by_role("button", name=re.compile(r"listar\s*fatura", re.I)),
        ])
        if not botao:
            raise RuntimeError("Não achei o botão 'Listar fatura'.")
        botao.click()
        self._aguardar_carregamento(config.ESPERA_POS_AJAX_MS)

    def _linha_fatura_mes(self, mes_variantes: list[str]) -> Locator | None:
        """Devolve a linha da tabela da fatura do mês, ou None."""
        tabela = self.page.locator(
            '[id="formSegundaViaFatura:dtListaSegundaViaFaturaSegundaVia_data"] tr')
        limite = time.time() + 12
        while time.time() < limite:
            if tabela.count() > 0:
                break
            if self.page.get_by_text(
                re.compile(r"nenhum registro|não encontr|sem fatura|não h[aá]", re.I)
            ).count() > 0:
                return None
            time.sleep(0.4)

        if tabela.count() == 0:
            return None

        variantes = {v.strip().lower() for v in mes_variantes}
        for i in range(tabela.count()):
            linha = tabela.nth(i)
            mes_ref = linha.locator("td").nth(0).inner_text().strip().lower()
            if mes_ref in variantes or any(v in mes_ref or mes_ref in v for v in variantes):
                return linha

        return tabela.first if tabela.count() == 1 else None

    def _extrair_dados_linha(self, linha: Locator) -> dict:
        celulas = linha.locator("td")
        return {
            "mes_ref":    celulas.nth(0).inner_text().strip(),
            "vencimento": celulas.nth(1).inner_text().strip(),
            "valor":      celulas.nth(3).inner_text().strip(),
            "via_link":   celulas.nth(4).locator("a").first,
        }

    def _extrair_dados_modal(self, texto: str) -> dict:
        uc = re.search(r"ANEEL[^\d]*(\d{10,})", texto, re.I)
        venc = re.search(r"Vencimento[^\d]*(\d{2}/\d{2}/\d{4})", texto, re.I)
        valor = re.search(r"Valor[^\d]*([\d.,]+)", texto, re.I)
        return {
            "uc_aneel":   uc.group(1) if uc else "",
            "vencimento": venc.group(1) if venc else "",
            "valor":      valor.group(1) if valor else "",
        }

    def _extrair_campo_modal(self, texto: str, rotulo: str) -> str:
        m = re.search(
            rf"{rotulo}\s*:?\s*([\d.,/]+)",
            texto, re.I,
        )
        return m.group(1).strip() if m else ""

    def _modal_visivel(self) -> Locator | None:
        for sel in (
            '#frmModalSegundaVia\\:modalSegundaVia',
            '#modalAceitePrimeiraVia',
            '#modalDadosPrimeiraViaConsultaDebitos\\:dadosPrimeiraVia',
        ):
            modal = self.page.locator(sel)
            try:
                if modal.count() and modal.first.is_visible():
                    return modal.first
            except Exception:
                pass
        titulo = self.page.locator(".ui-dialog:visible").filter(
            has_text=re.compile(r"1[aª]\s*via|2[aª]\s*via", re.I))
        if titulo.count():
            return titulo.first
        return None

    def _fechar_modal(self):
        modal = self._modal_visivel()
        if not modal:
            return
        fechar = modal.locator(".ui-dialog-titlebar-close").first
        if fechar.count() and fechar.is_visible():
            fechar.click()
            time.sleep(0.5)
            return
        ok = _primeiro_visivel([
            modal.get_by_role("button", name=re.compile(r"fechar|cancelar|ok|sair", re.I)),
        ], timeout_ms=2000)
        if ok:
            ok.click()

    def _eh_primeira_via(self, texto: str) -> bool:
        """True se link da tabela for 1ª via (não 2ª)."""
        t = texto.strip().lower().replace("ª", "a").replace("º", "o")
        return bool(re.search(r"^1\s*a?\s*via", t))

    def _baixar_primeira_via(self) -> None:
        """Fluxo do modal de 1ª via: marca aceite -> Emitir -> download."""
        aceite = self.page.locator("#modalAceitePrimeiraVia")
        aceite.wait_for(state="visible", timeout=config.TIMEOUT_MS)
        print("   [1via] Modal 1ª via — marcando aceite...")

        chk_input = aceite.locator("input[type='checkbox']").first
        chk_box = aceite.locator(".ui-chkbox-box").first
        if chk_box.count():
            chk_box.click()
        elif chk_input.count():
            chk_input.check(force=True)
        else:
            aceite.get_by_text(re.compile(r"li e concordo", re.I)).click()

        self._aguardar_carregamento(config.ESPERA_POS_AJAX_MS)

        emitir = self.page.locator("#btnGerarPrimeiraVia")
        limite = time.time() + 15
        while time.time() < limite:
            try:
                if emitir.count() and emitir.is_enabled() and emitir.is_visible():
                    if "ui-state-disabled" not in (emitir.get_attribute("class") or ""):
                        break
            except Exception:
                pass
            time.sleep(0.3)

        if not emitir.count() or not emitir.is_enabled():
            emitir = _primeiro_visivel([
                aceite.get_by_role("button", name=re.compile(r"emitir", re.I)),
                self.page.locator("#btnGerarPrimeiraVia"),
            ], timeout_ms=5000)
        if not emitir:
            raise RuntimeError("Não achei o botão 'Emitir' da 1ª via.")

        print("   [1via] Clicando Emitir...")
        emitir.click()
        self._aguardar_carregamento(config.ESPERA_POS_AJAX_MS)

        dados = self.page.locator("#modalDadosPrimeiraViaConsultaDebitos\\:dadosPrimeiraVia")
        limite = time.time() + 20
        while time.time() < limite:
            try:
                if dados.count() > 0 and dados.first.is_visible():
                    break
            except Exception:
                pass
            alt = self.page.locator(".ui-dialog:visible").filter(
                has_text=re.compile(r"download da 1", re.I))
            if alt.count() > 0:
                dados = alt.first
                break
            time.sleep(0.3)
        else:
            raise RuntimeError("Modal 'Download da 1ª via' não abriu após Emitir.")

        print("   [1via] Modal download — clicando Download...")
        download_btn = _primeiro_visivel([
            dados.locator('[id="modalDadosPrimeiraViaConsultaDebitos:j_idt152"]'),
            dados.locator("button").filter(has_text=re.compile(r"download", re.I)),
            dados.get_by_role("button", name=re.compile(r"download", re.I)),
        ], timeout_ms=10000)
        if not download_btn:
            raise RuntimeError("Não achei o botão 'Download' da 1ª via.")

        with self.page.expect_download(timeout=config.TIMEOUT_MS) as dl_info:
            download_btn.click()
        download = dl_info.value
        destino = self._destino_pdf(self._nome_download_atual, self._mes_download_atual)
        download.save_as(str(destino))
        print(f"   [pdf] Salvo: {destino}")
        self._arquivo_baixado = destino

        print("   [1via] Clicando OK...")
        ok = _primeiro_visivel([
            dados.locator('[id="modalDadosPrimeiraViaConsultaDebitos:j_idt155"]'),
            dados.get_by_role("button", name=re.compile(r"^ok$", re.I)),
            dados.locator("button").filter(has_text=re.compile(r"^ok$", re.I)),
        ], timeout_ms=8000)
        if not ok:
            raise RuntimeError("Não achei o botão 'OK' do modal de download.")
        ok.click()
        self._aguardar_carregamento(config.ESPERA_POS_AJAX_MS)
        try:
            dados.wait_for(state="hidden", timeout=10000)
        except Exception:
            pass

    def _baixar_segunda_via_modal(self) -> dict:
        """Abre modal da 2ª via, extrai dados e baixa o PDF."""
        modal = self.page.locator('#frmModalSegundaVia\\:modalSegundaVia')
        modal.wait_for(state="visible", timeout=config.TIMEOUT_MS)
        limite = time.time() + 15
        texto = ""
        while time.time() < limite:
            texto = modal.inner_text()
            if re.search(r"ANEEL|Vencimento|download", texto, re.I):
                break
            time.sleep(0.3)
        # dump do texto do modal (pra investigar o código de barras / linha digitável)
        try:
            (config.PASTA_DIAGNOSTICO / "descoberta_modal_2via.txt").write_text(texto, encoding="utf-8")
        except Exception:
            pass
        dados = self._extrair_dados_modal(texto)
        if not dados["uc_aneel"]:
            dados["uc_aneel"] = self._capturar_uc_nova()
        if not dados["vencimento"]:
            dados["vencimento"] = self._extrair_campo_modal(texto, r"Vencimento")
        if not dados["valor"]:
            dados["valor"] = self._extrair_campo_modal(texto, r"Valor\s*\(R\$\)")

        download_btn = _primeiro_visivel([
            modal.get_by_role("button", name=re.compile(r"fazer download|download", re.I)),
            self.page.locator("#frmModalSegundaVia button").filter(
                has_text=re.compile(r"download", re.I)),
        ], timeout_ms=8000)
        if not download_btn:
            raise RuntimeError("Não achei o botão de download no modal da 2ª via.")

        with self.page.expect_download(timeout=config.TIMEOUT_MS) as dl_info:
            download_btn.click()
        download = dl_info.value
        destino = self._destino_pdf(self._nome_download_atual, self._mes_download_atual)
        download.save_as(str(destino))
        dados["arquivo"] = destino
        print(f"   [pdf] Salvo: {destino}")
        return dados

    def _voltar_da_segunda_via(self):
        """Fecha o modal e vai DIRETO pra seleção de UC (sem passar por 'Todos os Serviços')."""
        self._fechar_modal()
        self._ir_para_selecao_uc()   # usa o ícone ⇄ do cabeçalho ou a URL direta

    def _baixar_fatura_do_mes(self, conta: dict, nome_cliente: str) -> dict | None:
        """Baixa a fatura de UM mês na tela de 2ª via já aberta. NÃO volta pra seleção
        (fecha só o modal), pra permitir baixar vários meses da mesma UC em sequência."""
        mes = conta["mes_referencia"]
        self._nome_download_atual = nome_cliente
        self._mes_download_atual = mes
        self._arquivo_baixado = None

        if not self._na_segunda_via():
            self._abrir_segunda_via()

        self._preencher_mes_e_listar(mes)
        linha = self._linha_fatura_mes(conta.get("mes_variantes", [mes]))
        if linha is None:
            return None

        dados_linha = self._extrair_dados_linha(linha)
        via_txt = dados_linha["via_link"].inner_text().strip().lower()
        dados_linha["via_link"].click()
        self._aguardar_carregamento(config.ESPERA_POS_AJAX_MS)

        if self._eh_primeira_via(via_txt):
            print(f"   [fatura] Tipo: 1ª via ({via_txt!r})")
            self._baixar_primeira_via()
            resultado = {
                "uc_aneel":   self._capturar_uc_nova(),
                "vencimento": dados_linha["vencimento"],
                "valor":      dados_linha["valor"],
                "arquivo":    self._arquivo_baixado,
            }
        else:
            print(f"   [fatura] Tipo: 2ª via ({via_txt!r})")
            resultado = self._baixar_segunda_via_modal()
            if not resultado.get("vencimento"):
                resultado["vencimento"] = dados_linha["vencimento"]
            if not resultado.get("valor"):
                resultado["valor"] = dados_linha["valor"]

        self._fechar_modal()   # fecha o modal mas FICA na 2ª via (pro próximo mês)
        return resultado

    def _processar_segunda_via(self, conta: dict, nome_cliente: str) -> dict | None:
        """Uma fatura e volta pra seleção de UC (usado no fluxo de fatura única)."""
        resultado = self._baixar_fatura_do_mes(conta, nome_cliente)
        self._voltar_da_segunda_via()
        return resultado

    def processar_faturas_uc(self, contas_uc: list[dict]) -> list[dict | None]:
        """Otimização: baixa TODAS as faturas de uma MESMA UC selecionando a UC e abrindo
        a 2ª via só 1 vez, trocando apenas o mês. Retorna a lista de resultados alinhada
        com contas_uc. Um mês que der erro vira None -> o main tenta o caminho individual."""
        uc = contas_uc[0]["uc"]
        n = len(contas_uc)
        resultados: list[dict | None] = [None] * n

        self._ir_para_selecao_uc()
        if not self._pesquisar_e_selecionar_uc(uc):
            for i in range(n):
                resultados[i] = {"status": NAO_ENCONTRADO, "uc_nova": "", "vencimento": "",
                                 "valor": "", "arquivo": "", "mensagem": f"UC {uc} não localizada"}
            return resultados

        uc_aneel = self._capturar_uc_nova()
        self._dispensar_modais_iniciais()
        self._abrir_segunda_via()

        for i, conta in enumerate(contas_uc):
            mes = conta["mes_referencia"]
            print(f"   [UC {uc}] mês {mes} ({i + 1}/{n})...")
            try:
                fatura = self._baixar_fatura_do_mes(conta, conta["nome_cliente"])
                if fatura is None:
                    resultados[i] = {"status": FATURA_NAO_EMITIDA, "uc_nova": uc_aneel,
                                     "vencimento": "", "valor": "", "arquivo": "",
                                     "mensagem": f"Sem fatura para {mes}"}
                else:
                    resultados[i] = {
                        "status": CONCLUIDO,
                        "uc_nova": fatura.get("uc_aneel") or uc_aneel,
                        "vencimento": fatura.get("vencimento", ""),
                        "valor": fatura.get("valor", ""),
                        "arquivo": str(fatura.get("arquivo", "")),
                        "mensagem": "Fatura baixada",
                    }
            except Exception as e:
                print(f"   [UC {uc}] mês {mes} falhou ({type(e).__name__}) -> modo individual.")
                resultados[i] = None   # sinaliza pro main tentar o caminho robusto
                try:
                    self._fechar_modal()   # tenta limpar o estado pro próximo mês
                except Exception:
                    pass

        self._voltar_da_segunda_via()
        return resultados

    def _destino_pdf(self, nome_cliente: str, mes: str) -> Path:
        base = config.sanitizar(nome_cliente)
        destino = config.PASTA_FATURAS / f"{base}.pdf"
        if destino.exists():
            destino = config.PASTA_FATURAS / f"{base}_{config.sanitizar(mes)}.pdf"
        return destino

    # ======================================================================
    #  MODOS DE APOIO (teste / descoberta)
    # ======================================================================
    def testar_ate_segunda_via(self, conta: dict) -> dict:
        """Roda fluxo completo até baixar a fatura (ou marcar não encontrado)."""
        uc = conta["uc"]
        self._ir_para_selecao_uc()
        achou = self._pesquisar_e_selecionar_uc(uc)
        print(f"   [teste] UC antiga {uc} encontrada? {achou}")
        if not achou:
            return {"status": NAO_ENCONTRADO, "uc_nova": "", "vencimento": "", "valor": "",
                    "arquivo": "", "mensagem": f"UC {uc} não localizada"}

        uc_aneel = self._capturar_uc_nova()
        print(f"   [teste] UC nova (ANEEL) capturada: {uc_aneel!r}")
        self._dispensar_modais_iniciais()
        self._abrir_segunda_via()

        fatura = self._processar_segunda_via(conta, conta["nome_cliente"])
        if fatura is None:
            return {"status": FATURA_NAO_EMITIDA, "uc_nova": uc_aneel,
                    "vencimento": "", "valor": "", "arquivo": "",
                    "mensagem": f"Sem fatura para {conta['mes_referencia']}"}

        print(f"   [teste] vencimento={fatura.get('vencimento')!r} "
              f"valor={fatura.get('valor')!r}")
        return {
            "status": CONCLUIDO,
            "uc_nova": fatura.get("uc_aneel") or uc_aneel,
            "vencimento": fatura.get("vencimento", ""),
            "valor": fatura.get("valor", ""),
            "arquivo": str(fatura.get("arquivo", "")),
            "mensagem": "Fatura baixada (teste)",
        }

    def descobrir(self):
        self.garantir_login()
        self._dump_interativos("apos_login")
        print("\n   [descoberta] Inspector aberto. Navegue pelas telas e me diga os textos.")
        try:
            self.page.pause()
        except Exception:
            input("   [descoberta] Inspector indisponível. Navegue e tecle ENTER aqui...")
        self._dump_interativos("tela_final")

    def _dump_interativos(self, rotulo: str):
        destino = config.PASTA_DIAGNOSTICO / f"descoberta_{rotulo}.txt"
        linhas = [f"URL: {self.page.url}", "-" * 60]
        js = ("() => [...document.querySelectorAll('a,button,input,select,th,[role=button],[role=link]')]"
              ".filter(e=>{const r=e.getBoundingClientRect();return r.width||r.height})"
              ".map(e=>{const t=(e.innerText||e.value||e.getAttribute('aria-label')||e.name||e.id||'').trim();"
              "return t?`${e.tagName.toLowerCase()} | id=${e.id||''} name=${e.name||''} | \"${t.slice(0,70)}\"`:null})"
              ".filter(Boolean)")
        try:
            linhas.extend(self.page.evaluate(js))
        except Exception as e:
            linhas.append(f"(falha ao coletar: {e})")
        destino.write_text("\n".join(linhas), encoding="utf-8")
        print(f"   [dump] elementos salvos em: {destino}")

    def screenshot_erro(self, conta: dict, etapa: str) -> str:
        try:
            nome = f"erro_{config.sanitizar(conta.get('uc', 'x'))}_{config.sanitizar(etapa)}.png"
            caminho = config.PASTA_SCREENSHOTS / nome
            self.page.screenshot(path=str(caminho), full_page=True)
            return str(caminho)
        except Exception:
            return ""
