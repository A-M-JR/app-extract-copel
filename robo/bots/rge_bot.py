"""
RGE / CPFL (Rio Grande Energia) — herda a infra comum de bot_base.BotBase.

Fluxo (dos prints):
  1. Login Azure B2C com E-MAIL + senha (sem MFA -> confirmado). Base cuida.
  2. Home -> "Selecione outra instalação".
  3. Lista -> acha a UC (Nº Instalação) na tela -> marca o radio -> "Acessar".
  4. Home da instalação -> "Débito e segunda via".
  5. "Débitos e 2ª via de conta" -> expandir "MINHAS CONTAS PAGAS".
  6. Acha a linha do mês -> "Ver 2ª via de conta" -> "Ver conta completa"
     (abre o PDF numa NOVA ABA) -> baixa o PDF pela URL (cookies da sessão).
  7. Volta (Home -> "Selecione outra instalação") pra próxima UC.
"""
import re
import time

import config
from bot_base import BotBase, primeiro_visivel
from resultado_log import CONCLUIDO, NAO_ENCONTRADO, FATURA_NAO_EMITIDA

NAV = config.ESPERA_POS_NAVEGACAO_MS
AJAX = config.ESPERA_POS_AJAX_MS
URL_SELECAO_RGE = "https://www.cpfl.com.br/agencia/area-cliente/selecionar-perfil-instalacao"

# Observador injetado no navegador (roda em TODA página): fecha SOZINHO os modais que a RGE
# joga toda hora — "Seu código na conta de luz mudou" (Entendi) e "Deseja receber suas faturas
# por e-mail?" / "...velocidade do PIX!" (Não [desejo] me cadastrar). Some assim que aparecem.
_AUTO_FECHA_MODAIS_JS = r"""
(function () {
  const RX = [/^\s*entendi\s*$/i, /n[ãa]o\s+(desejo\s+)?me\s+cadastrar/i];
  const ok = t => { t = (t || '').trim(); return t && t.length <= 45 && RX.some(r => r.test(t)); };
  // Texto que identifica os modais INFORMATIVOS da RGE (podem ser ARRANCADOS do DOM sem dó):
  const MODAL_RX = /c[óo]digo.*mudou|norma aneel|velocidade do pix|receber suas (contas|faturas)|deseja receber suas/i;
  function clica(el) {
    // sequência completa (Angular às vezes só responde a pointer/mouse, não a .click())
    const o = { bubbles: true, cancelable: true, view: window };
    try { el.dispatchEvent(new PointerEvent('pointerdown', o)); } catch (e) {}
    try { el.dispatchEvent(new MouseEvent('mousedown', o)); } catch (e) {}
    try { el.dispatchEvent(new PointerEvent('pointerup', o)); } catch (e) {}
    try { el.dispatchEvent(new MouseEvent('mouseup', o)); } catch (e) {}
    try { el.click(); } catch (e) {}
  }
  function tenta() {
    // Escopa aos CONTAINERS de modal (dialog/modal/popup) quando existirem — assim NÃO
    // clicamos por engano num link solto de "não me cadastrar" da página (que navega e faz
    // a tela ficar "piscando"). Sem container visível, cai pro body (comportamento antigo).
    const conts = [...document.querySelectorAll('[role=dialog],[class*="modal" i],[class*="popup" i],ngb-modal-window,app-modal')]
      .filter(m => { const r = m.getBoundingClientRect(); return r.width > 200 && r.height > 120; });
    const scope = conts.length ? conts : [document.body];
    for (const root of scope) {
      for (const el of root.querySelectorAll('button,a,[role=button],[onclick],div,span,p,li')) {
        if (el.__rgeClk) continue;               // clica UMA vez por elemento -> sem loop de briga
        if (ok(el.innerText || el.textContent) && el.children.length <= 1) {
          const r = el.getBoundingClientRect();
          if (r.width && r.height) { el.__rgeClk = true; clica(el); }
        }
      }
    }
  }
  // Modal "Receba as suas contas de forma digital" (Conta Digital CPFL): fecha pelo X do
  // canto. Só clica se o X NÃO for <a href=""> (esses navegam e geram loop de F5); se o
  // modal continuar na tela 1,5s depois, arranca do DOM como os outros.
  const RX_X = /receba as suas contas|conta digital cpfl/i;
  function xDoModal(m) {
    const sel = 'button.close,.close,[aria-label*="fech" i],[aria-label*="close" i],' +
                '[class*="close" i],[class*="fechar" i],[title*="fech" i]';
    let x = m.querySelector(sel);
    if (!x) x = [...m.querySelectorAll('button,a,[role=button],span,i')]
                  .find(b => /^\s*[×xX✕]\s*$/.test(b.textContent || ''));
    return x;
  }
  function seguro(x) {
    const a = x.closest('a');
    if (!a) return true;
    const h = (a.getAttribute('href') || '').trim();
    return h && h !== '#' && !h.startsWith('javascript');
  }
  function fechaPeloX() {
    for (const m of document.querySelectorAll('[role=dialog],[class*="modal" i],[class*="popup" i],ngb-modal-window,app-modal,mat-dialog-container')) {
      const r = m.getBoundingClientRect();
      if (r.width < 150 || r.height < 80 || !RX_X.test(m.innerText || '')) continue;
      const x = xDoModal(m);
      if (x && !x.__rgeX && seguro(x)) { x.__rgeX = true; clica(x); }
      if (!m.__rgeXT) {
        m.__rgeXT = true;
        setTimeout(() => {
          if (document.contains(m) && m.getBoundingClientRect().height > 0) {
            try { m.remove(); } catch (e) {}
            for (const b of document.querySelectorAll('[class*="backdrop" i],.cdk-overlay-backdrop')) { try { b.remove(); } catch (e) {} }
            try { document.body.style.overflow = ''; document.body.classList.remove('modal-open'); } catch (e) {}
          }
        }, 1500);
      }
    }
  }
  function mataModais() {
    fechaPeloX();
    // A tela da RGE fica RECARREGANDO (F5) e o clique no botão não "pega" no meio da
    // navegação. Então ARRANCAMOS o modal informativo do DOM — o observer refaz isso a
    // cada reload, então mesmo piscando a tela fica utilizável.
    const cand = document.querySelectorAll(
      '[role=dialog],[class*="modal" i],[class*="popup" i],ngb-modal-window,app-modal,mat-dialog-container');
    let matou = false;
    for (const el of cand) {
      const r = el.getBoundingClientRect();
      if (r.width < 150 || r.height < 80) continue;
      if (MODAL_RX.test(el.innerText || '')) { try { el.remove(); matou = true; } catch (e) {} }
    }
    if (matou) {
      // tira o fundo escuro/blur e libera o scroll travado pelo modal
      for (const b of document.querySelectorAll(
          '[class*="backdrop" i],[class*="overlay" i],.modal-open,.cdk-overlay-backdrop')) {
        try { const c = (b.className || '') + ''; if (/backdrop|overlay/i.test(c)) b.remove(); } catch (e) {}
      }
      try {
        document.body.style.overflow = ''; document.documentElement.style.overflow = '';
        document.body.classList.remove('modal-open');
      } catch (e) {}
    }
  }
  // IMPORTANTE: NÃO clicamos no "Entendi"/"Não me cadastrar" — na RGE eles são <a href="">,
  // e clicar navega pra própria página (refresh). Isso criava um loop de F5 infinito
  // (o console mostra "CPFL Debug: Link clicked {href:''}"). Só ARRANCAMOS o modal do DOM.
  const roda = () => { mataModais(); };
  let pend = false;
  const agenda = () => { if (pend) return; pend = true; setTimeout(() => { pend = false; roda(); }, 350); };
  const start = () => {
    try { new MutationObserver(agenda).observe(document.documentElement, { childList: true, subtree: true }); } catch (e) {}
    roda();
    // reforço por tempo: a tela renavega mesmo sem mutação observável -> varre a cada 1s por ~40s
    let n = 0; const iv = setInterval(() => { roda(); if (++n > 40) clearInterval(iv); }, 1000);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
"""

# Removedor pontual (chamado do Python nos loops de espera): ARRANCA do DOM os modais
# informativos da RGE/CPFL ("código mudou" / "Deseja receber por e-mail" / "velocidade do
# PIX") + o fundo escuro, e libera o scroll. NÃO clica (o botão é <a href=''> e navegaria).
_NUKE_MODAIS_JS = r"""
() => {
  const RX = /c[óo]digo.*mudou|norma aneel|velocidade do pix|receber suas (contas|faturas)|deseja receber suas/i;
  let n = 0;
  // "Receba as suas contas de forma digital": clica no X (se não for <a href="">)
  const RX_X = /receba as suas contas|conta digital cpfl/i;
  for (const m of document.querySelectorAll('[role=dialog],[class*="modal" i],[class*="popup" i],ngb-modal-window,app-modal,mat-dialog-container')) {
    const r = m.getBoundingClientRect();
    if (r.width < 150 || r.height < 80 || !RX_X.test(m.innerText || '')) continue;
    let x = m.querySelector('button.close,.close,[aria-label*="fech" i],[aria-label*="close" i],[class*="close" i],[class*="fechar" i],[title*="fech" i]');
    if (!x) x = [...m.querySelectorAll('button,a,[role=button],span,i')].find(b => /^\s*[×xX✕]\s*$/.test(b.textContent || ''));
    const a = x && x.closest('a');
    const h = a ? (a.getAttribute('href') || '').trim() : 'ok';
    if (x && !x.__rgeX && h && h !== '#' && !h.startsWith('javascript')) { x.__rgeX = true; x.click(); n++; }
    else if (!x || !x.__rgeX) { try { m.remove(); n++; } catch (e) {} }
  }
  for (const el of document.querySelectorAll('[role=dialog],[class*="modal" i],[class*="popup" i],ngb-modal-window,app-modal,mat-dialog-container')) {
    const r = el.getBoundingClientRect();
    if (r.width >= 150 && r.height >= 80 && RX.test(el.innerText || '')) { try { el.remove(); n++; } catch(e){} }
  }
  if (n) {
    for (const b of document.querySelectorAll('[class*="backdrop" i],.cdk-overlay-backdrop')) { try { b.remove(); } catch(e){} }
    try { document.body.style.overflow=''; document.documentElement.style.overflow=''; document.body.classList.remove('modal-open'); } catch(e){}
  }
  return n;
}
"""


class RgeBot(BotBase):
    URL_LOGIN = config.URL_LOGIN_RGE

    def _remover_modais(self, rotulo="popup") -> bool:
        """Remove os modais informativos (email/PIX/código) da tela atual — usado nos loops
        da 2ª via (servicosonline), onde esses popups tapam a lista e geram 'não emitida'
        falso. Reforço ao observador (que às vezes expira antes do popup aparecer)."""
        try:
            if self.page.evaluate(_NUKE_MODAIS_JS):
                print(f"   [rge] removi {rotulo} (email/PIX/código) da tela.")
                return True
        except Exception:
            pass
        return False

    def __enter__(self):
        # RGE NÃO reaproveita sessão: cookies acumulados (Azure B2C + 3 domínios:
        # b2clogin -> cpfl.com.br -> servicosonline) causam ERR_TOO_MANY_REDIRECTS.
        # Começa sempre limpo — o login é barato aqui (sem captcha e sem MFA).
        import shutil, json
        sess = config.pasta_sessao(self.login)
        try:
            shutil.rmtree(sess, ignore_errors=True)
        except Exception:
            pass
        # desliga o gerenciador de senhas do Chrome via Preferences (reforço às flags):
        # mata os popups "Mude sua senha" e "Salvar senha?" do login B2C.
        try:
            default = sess / "Default"
            default.mkdir(parents=True, exist_ok=True)
            (default / "Preferences").write_text(json.dumps({
                "credentials_enable_service": False,
                "profile": {"password_manager_enabled": False,
                            "password_manager_leak_detection": False},
            }), encoding="utf-8")
        except Exception:
            pass
        ctx = super().__enter__()
        try:   # observador que fecha os modais da RGE sozinho, em QUALQUER página
            self.context.add_init_script(_AUTO_FECHA_MODAIS_JS)
        except Exception:
            pass
        return ctx

    def __exit__(self, *exc):
        # SAIR antes de fechar: a CPFL guarda a sessão no servidor e, se não sair, o próximo
        # cliente abre já logado na conta ANTERIOR.
        try:
            if self.page and not self.page.is_closed():
                self.sair()
        except Exception as e:
            print(f"   [rge] não consegui sair da conta: {type(e).__name__}: {e}")
        return super().__exit__(*exc)

    # -- logout (menu do nome no topo -> "Sair") ---------------------------
    def _menu_perfil(self):
        """O bloco do cliente no canto superior direito (avatar + nome + 'Residencial /
        Baixa tensão' + endereço). Clicar nele abre o menu com 'Sair'."""
        classe = re.compile(r"residencial|comercial|rural|industrial|poder p[úu]blico|"
                            r"baixa tens|m[ée]dia tens|alta tens", re.I)
        return primeiro_visivel([
            self.page.locator("header").get_by_text(classe),
            self.page.get_by_text(classe),
            self.page.locator("[class*='avatar' i], [class*='perfil' i] img, [class*='user' i] img"),
        ], timeout_ms=4000)

    def _perfil_visivel(self) -> bool:
        try:
            loc = self.page.get_by_text(re.compile(
                r"residencial|comercial|rural|industrial|poder p[úu]blico|baixa tens|m[ée]dia tens|alta tens", re.I))
            return any(loc.nth(i).is_visible() for i in range(min(loc.count(), 5)))
        except Exception:
            return True

    def _botao_sair(self, timeout_ms=3000):
        rx = re.compile(r"^\s*sair\s*$", re.I)
        return primeiro_visivel([
            self.page.get_by_role("menuitem", name=rx),
            self.page.get_by_role("link", name=rx),
            self.page.get_by_role("button", name=rx),
            self.page.get_by_text(rx),
        ], timeout_ms=timeout_ms)

    def sair(self) -> bool:
        """Clica no nome do cliente lá em cima -> 'Sair'. True se saiu."""
        if not self.esta_logado() and not self._perfil_visivel():
            return True
        print("   [rge] saindo da conta (menu do nome -> Sair)...")
        for _ in range(3):
            self._remover_modais("popup antes do Sair")
            perfil = self._menu_perfil()
            if perfil:
                try:
                    perfil.click(timeout=4000)
                except Exception:
                    pass
            sair = self._botao_sair()
            if sair:
                try:
                    sair.click(timeout=4000)
                except Exception:
                    continue
                fim = time.time() + 25
                while time.time() < fim:
                    # saiu = foi pro login B2C ou sumiu o bloco do cliente do topo (a home
                    # deslogada também mostra "Débito e segunda via", então não basta o esta_logado)
                    if "b2clogin" in (self.page.url or "").lower() or not self._perfil_visivel():
                        print("   [rge] saiu da conta [OK]")
                        return True
                    time.sleep(0.5)
            time.sleep(1)
        print("   [rge] AVISO: não achei o 'Sair' — limpando os cookies da sessão.")
        try:
            self.context.clear_cookies()
        except Exception:
            pass
        return False

    def _botao_entrar_home(self):
        """Link 'Entrar' do topo da home DESLOGADA da CPFL."""
        rx = re.compile(r"^\s*entrar\s*$", re.I)
        return primeiro_visivel([
            self.page.locator("header").get_by_role("link", name=rx),
            self.page.locator("header").get_by_role("button", name=rx),
            self.page.get_by_role("link", name=rx),
            self.page.get_by_role("button", name=rx),
            self.page.get_by_text(rx),
        ], timeout_ms=3000)

    def _campo_email_b2c(self) -> bool:
        try:
            loc = self.page.locator("#signInName, #email, input[type='email']")
            return loc.count() > 0 and loc.first.is_visible()
        except Exception:
            return False

    def _abrir_login(self):
        """Abre o login B2C. Casos da CPFL:
          - abre LOGADA numa sessão de outro cliente -> Sair primeiro;
          - cai na home deslogada (às vezes com 'Ocorreu um erro ao processar a sua
            solicitação') em vez do formulário -> clica no 'Entrar' do topo."""
        for tentativa in range(3):
            try:
                self.page.goto(self.URL_LOGIN, wait_until="domcontentloaded")
            except Exception:
                pass
            self._aguardar_carregamento()
            if self.esta_logado() or self._perfil_visivel():
                print("   [rge] abriu logado numa sessão anterior -> saindo antes de logar.")
                self.sair()
            if "b2clogin" in (self.page.url or "").lower():
                return                                   # formulário de login na tela
            entrar = self._botao_entrar_home()
            if entrar:
                print("   [rge] caiu na home deslogada -> clicando em 'Entrar'...")
                try:
                    entrar.click(timeout=5000)
                except Exception:
                    pass
                fim = time.time() + 30
                while time.time() < fim:
                    # NÃO usar _campo_doc aqui: ele aceita qualquer input de texto e pegaria a
                    # busca "Digite o que você está procurando" da home
                    if "b2clogin" in (self.page.url or "").lower() or self._campo_email_b2c():
                        self._aguardar_carregamento()
                        return
                    time.sleep(0.5)
            print(f"   [rge] tela de login não abriu (tentativa {tentativa + 1}/3)...")

    # -- login (Azure B2C: e-mail + senha, sem MFA) ------------------------
    def esta_logado(self) -> bool:
        try:
            url = (self.page.url or "").lower()
            if "b2clogin" in url:
                return False
            marc = self.page.get_by_text(re.compile(
                r"selecione outra instala|gerencie sua conta|alterar cidade|d[ée]bito e segunda", re.I))
            return marc.count() > 0
        except Exception:
            return False

    def _campo_doc(self):   # RGE loga por e-mail
        return primeiro_visivel([
            self.page.get_by_placeholder(re.compile(r"e-?mail|endere[çc]o", re.I)),
            self.page.locator("input[type='email']"),
            self.page.locator("#email, #signInName, input[name='email']"),
            self.page.locator("input[type='text']"),
        ])

    # -- (3) selecionar a instalação pela UC -------------------------------
    def _na_selecao_instalacao(self) -> bool:
        try:
            # exige o CONTEÚDO da seleção (heading/card) — NÃO o link de menu "Escolha a
            # instalação" (que está sempre no menu lateral e dava falso positivo).
            return self.page.get_by_text(re.compile(
                r"selecione sua instala|selecione seu perfil|n[º°o]\s*(da\s+)?instala[çc]",
                re.I)).count() > 0
        except Exception:
            return False

    def _ir_para_selecao_uc(self):
        if self._na_selecao_instalacao():
            self._fechar_cookies()
            return
        # vai DIRETO pra tela de seleção (mais confiável que clicar 'Home' — a URL antiga
        # do 'Home' entra em loop de redirect). É o equivalente a Home -> Selecione outra.
        print("   [rge] indo pra seleção de instalação...")
        try:
            self.page.goto(URL_SELECAO_RGE, wait_until="domcontentloaded")
        except Exception:
            pass
        self._aguardar_carregamento(NAV)
        self._fechar_cookies()
        fim = time.time() + 25
        while time.time() < fim and not self._na_selecao_instalacao():
            time.sleep(0.5)

    def _fechar_cookies(self):
        """Fecha o banner de cookies (OneTrust) — ele cobre o rodapé e bloqueia o 'Avançar'."""
        try:
            b = self.page.locator("#onetrust-accept-btn-handler")
            if b.count() > 0 and b.first.is_visible():
                b.first.click(timeout=3000)
                print("   [rge] banner de cookies fechado.")
                time.sleep(0.4)
        except Exception:
            pass

    def _fechar_popups(self):
        """Dispensa os modais informativos que a RGE joga após acessar a conta e tapam a tela:
          - 'Seu código na conta de luz mudou' (NORMA ANEEL)
          - 'Deseja receber suas faturas por e-mail?'
          - 'Receba as suas contas na velocidade do PIX!'
          - 'Receba as suas contas de forma digital' (Conta Digital CPFL) -> esse fecha pelo X
        NÃO CLICAMOS neles: o 'Entendi'/'Não me cadastrar' é <a href=''> e clicar NAVEGA pra
        própria página (refresh) -> loop de F5 infinito (o console mostra 'Link clicked
        {href:""}'). A solução é ARRANCAR o modal do DOM (é só informativo) + Escape. O
        observador injetado (_AUTO_FECHA_MODAIS_JS) refaz isso a cada reload."""
        print("   [rge] tratando modais pós-acesso (removendo do DOM, sem clicar)...")
        modal_txt = re.compile(r"c[óo]digo.*mudou|velocidade do pix|receber suas faturas|norma aneel|"
                               r"receba as suas contas|conta digital cpfl", re.I)

        def modal_na_tela() -> bool:
            # se o evaluate/consulta falhar (página navegando), assume que AINDA tem modal
            try:
                return self.page.get_by_text(modal_txt).count() > 0
            except Exception:
                return True

        fim = time.time() + 20
        removeu_algum = False
        while time.time() < fim:
            # sincroniza com um momento assentado (não evalua no meio da navegação)
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=4000)
            except Exception:
                pass
            if not modal_na_tela():
                break
            # ARRANCA o modal do DOM (nunca clica -> não dispara o refresh do href vazio)
            try:
                if self.page.evaluate(_NUKE_MODAIS_JS):
                    if not removeu_algum:
                        print("   [rge] removi modal informativo da RGE (DOM)")
                    removeu_algum = True
            except Exception:
                pass
            # Escape como reforço (harmless, não navega)
            try:
                self.page.keyboard.press("Escape")
            except Exception:
                pass
            time.sleep(0.8)

        if modal_na_tela():
            print("   [rge] modal AINDA na tela — salvando screenshot pra ajustar o seletor.")
            self._dump_modal_html()
        self._fechar_cookies()          # depois dos modais, aceita os cookies

    def _aguardar_carregamento(self, extra_ms=0):
        """Espera SPA-friendly (o portal da RGE é lento): DOM pronto + rede calma (curta)
        + assentar. Às vezes o SPA NUNCA fica 'networkidle' — por isso limitamos essa
        espera (senão travaria ~45s a cada passo) e SEMPRE deixamos a tela assentar.
        Também trata o 503 'Backend fetch failed' que a CPFL solta às vezes (transitório)."""
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        try:
            self.page.wait_for_load_state("networkidle", timeout=6000)
        except Exception:
            pass
        self._recuperar_erro_servidor()
        time.sleep((extra_ms or NAV) / 1000)

    def _pagina_com_erro(self) -> bool:
        """True se a CPFL devolveu página de erro/tela branca (transitório, um F5 resolve):
        503 'Backend fetch failed' OU 'The website encountered an unexpected error'
        (a home antiga /agencia-virtual/pagina-inicial que às vezes vem quebrada)."""
        try:
            url = (self.page.url or "").lower()
            txt = (self.page.locator("body").inner_text() or "").lower()
            if ("backend fetch failed" in txt or "error 503" in txt or "erro 503" in txt
                    or "experiencing technical problems" in txt
                    or "unexpected error" in txt or "please try again later" in txt
                    or "encountered an" in txt):
                return True
            # home antiga praticamente vazia (quebrou o render) -> também recarrega
            if "agencia-virtual/pagina-inicial" in url and len(txt.strip()) < 40:
                return True
            return False
        except Exception:
            return False

    def _recuperar_erro_servidor(self, tentativas=5):
        """Erro TRANSITÓRIO da CPFL (503 ou 'unexpected error'/tela branca) -> espera e
        recarrega (o F5 que resolve na mão). Se não voltar, segue (o retry do main pega)."""
        for i in range(tentativas):
            if not self._pagina_com_erro():
                return
            espera = 3 + i * 3   # backoff: 3s, 6s, 9s...
            print(f"   [rge] portal com erro/tela branca (CPFL instável) — {espera}s e recarregando (F5)...")
            time.sleep(espera)
            try:
                self.page.reload(wait_until="domcontentloaded")
            except Exception:
                pass
            try:
                self.page.wait_for_load_state("networkidle", timeout=6000)
            except Exception:
                pass

    def _clicar(self, loc, rotulo: str = "", pos_ms=None) -> bool:
        """Clique PACIENTE (portal lento): espera visível, rola até o elemento, deixa
        assentar e só então clica (com fallback 'force'). Evita clicar em tela meio
        renderizada — que é o que trava a RGE."""
        if rotulo:
            print(f"   [rge] {rotulo}")
        try:
            loc.wait_for(state="visible", timeout=12000)
        except Exception:
            pass
        try:
            loc.scroll_into_view_if_needed(timeout=6000)
        except Exception:
            pass
        time.sleep(0.8)   # deixa render/animação assentar antes de clicar
        try:
            loc.click(timeout=8000)
        except Exception:
            try:
                loc.click(timeout=5000, force=True)
            except Exception:
                return False
        self._aguardar_carregamento(pos_ms if pos_ms is not None else NAV)
        return True

    def _aguardar_historico(self) -> bool:
        """Espera o SPA servicosonline (integracao-agd -> /historico-contas) renderizar
        a tela de débitos/2ª via, fechando o cookie do novo domínio no caminho.
        Essa SPA às vezes abre EM BRANCO (instabilidade da migração CPFL) — nesse caso um
        F5 resolve (igual na mão), então detectamos a tela vazia e recarregamos."""
        marc = re.compile(
            r"minhas contas pagas|n[ãa]o possui d[ée]bitos|2[ªa]\s*via de conta|"
            r"d[ée]bitos de outras|d[ée]bitos e 2", re.I)
        # Estratégia = a mesma da mão: espera um tempo; se NÃO renderizou os marcadores,
        # dá F5; espera MAIS (o SPA precisa re-hidratar); repete. Não depende de "tela
        # totalmente branca" — reprova qualquer estado que não seja a tela de débitos.
        fim = time.time() + 100
        recarregou = 0
        prox_reload = time.time() + 12          # 12s de carinho antes do 1º F5
        while time.time() < fim:
            self._fechar_cookies()
            self._remover_modais("popup da 2ª via")   # email/PIX tapam a lista -> arranca
            try:
                corpo = (self.page.locator("body").inner_text() or "").strip()
            except Exception:
                corpo = ""
            if marc.search(corpo):
                print("   [rge] tela de débitos/2ª via carregada.")
                return True
            if time.time() >= prox_reload and recarregou < 4:
                recarregou += 1
                print(f"   [rge] histórico não renderizou — recarregando (F5) {recarregou}/4...")
                try:
                    self.page.reload(wait_until="domcontentloaded")
                except Exception:
                    pass
                try:
                    self.page.wait_for_load_state("networkidle", timeout=6000)
                except Exception:
                    pass
                prox_reload = time.time() + 15   # dá tempo do SPA re-hidratar antes do próximo F5
            time.sleep(1)
        print("   [rge] tela de débitos NÃO carregou a tempo (SPA servicosonline).")
        return False

    def _achar_uc_na_tela(self, uc: str):
        """Fallback: acha o texto da UC rolando a página; devolve o localizador."""
        padrao = re.compile(re.escape(str(uc)))
        fim = time.time() + 20
        while time.time() < fim:
            loc = self.page.get_by_text(padrao)
            if loc.count() > 0:
                return loc.first
            self.page.mouse.wheel(0, 1600)
            time.sleep(0.5)
        return None

    def _esperar_instalacao_carregar(self, uc: str, timeout=30) -> bool:
        """Espera o card/lista da instalação renderizar de fato — o SPA é lento e o card
        chega por AJAX DEPOIS do shell da página (senão a gente procura a UC cedo demais)."""
        padrao = re.compile(re.escape(str(uc)))
        id_ok = bool(re.fullmatch(r"[0-9A-Za-z_-]+", str(uc) or ""))   # nº com pontos quebra o CSS
        fim = time.time() + timeout
        while time.time() < fim:
            self._fechar_cookies()
            try:
                if ((id_ok and self.page.locator(f"#instalacao-{uc}").count() > 0)
                        or self.page.get_by_text(padrao).count() > 0
                        or self.page.locator("input[type=radio]:visible").count() > 0):
                    time.sleep(0.8)   # deixa assentar
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    # -- helpers de ENDEREÇO (RGE mudou o formato da UC -> localiza por endereço) ---------
    _UF_NOME = {
        "RS": "RIO GRANDE DO SUL", "SP": "SAO PAULO", "PR": "PARANA",
        "MG": "MINAS GERAIS", "SC": "SANTA CATARINA",
    }

    def _selecionar_estado(self, uf: str):
        if not uf:
            return
        nome = self._UF_NOME.get(uf.strip().upper(), uf.strip().upper())
        try:
            sel = self.page.locator("#edit-filtro-estado")
            if sel.count() > 0:
                sel.first.select_option(label=nome)
                self._aguardar_carregamento(AJAX)   # cidades carregam por AJAX após o estado
        except Exception:
            pass

    def _selecionar_cidade(self, cidade: str):
        if not cidade:
            return
        alvo = cidade.strip().upper()
        try:
            sel = self.page.locator("#edit-filtro-municipio")
            if sel.count() == 0:
                return
            fim = time.time() + 8                    # espera as opções carregarem (dep. do estado)
            while time.time() < fim and sel.locator("option").count() <= 1:
                time.sleep(0.4)
            try:
                sel.first.select_option(label=alvo)
                return
            except Exception:
                pass
            opts = sel.locator("option")             # casa parcial (acentos/variações)
            for i in range(opts.count()):
                t = (opts.nth(i).inner_text() or "").strip().upper()
                if t and (alvo in t or t in alvo):
                    v = opts.nth(i).get_attribute("value")
                    if v:
                        sel.first.select_option(value=v)
                        return
        except Exception:
            pass

    def _filtrar_por_endereco(self, conta: dict):
        rua = (conta.get("logradouro") or "").strip()
        cidade = (conta.get("cidade") or "").strip()
        uf = (conta.get("uf") or "").strip()
        print(f"   [rge] filtrando por endereço: '{rua}' nº {conta.get('numero','')} - {cidade}/{uf}")
        self._selecionar_estado(uf)
        self._selecionar_cidade(cidade)
        try:
            campo = self.page.locator("#edit-filtro-endereco")
            if campo.count() > 0:
                campo.first.fill("")
                campo.first.fill(rua)
        except Exception:
            pass
        pesq = self.page.locator("#edit-filtro-button")
        if pesq.count() > 0:
            self._clicar(pesq.first, "pesquisando pelo endereço...", pos_ms=AJAX)
        self._aguardar_carregamento(NAV)
        time.sleep(1.5)

    def _achar_endereco_na_tela(self, rua: str, numero: str):
        """Acha na lista filtrada o card cujo endereço bate com a rua (e o número, se der)."""
        core = re.sub(r"^\s*(r|rua|av|avenida|tr|travessa|al|alameda|rod|rodovia|"
                      r"pc|praca|praça|est|estrada|lin|linha)\b\.?\s*", "", rua.strip(), flags=re.I).strip()
        alvo = core[:22] if len(core) >= 4 else rua.strip()
        if not alvo:
            return None
        padrao = re.compile(re.escape(alvo), re.I)
        fim = time.time() + 15
        while time.time() < fim:
            loc = self.page.get_by_text(padrao)
            n = loc.count()
            if n > 0:
                if numero:                            # prefere o card que também tem o número
                    for i in range(min(n, 8)):
                        try:
                            card = loc.nth(i).locator("xpath=ancestor::*[.//input[@type='radio']][1]")
                            if card.count() > 0 and numero in (card.inner_text() or ""):
                                return loc.nth(i)
                        except Exception:
                            pass
                return loc.first
            self.page.mouse.wheel(0, 1200)
            time.sleep(0.5)
        return None

    def _selecionar_instalacao(self, conta: dict) -> bool:
        """Marca a instalação e avança. Localiza por ENDEREÇO (RGE mudou o formato da UC ->
        o número antigo não bate) OU pela UC (fallback / layout /cadastro antigo)."""
        uc = str(conta.get("uc") or "")
        uc_nova = str(conta.get("uc_aneel_api") or "").strip()   # NOVO número da UC (uc_secondary)
        rua = (conta.get("logradouro") or "").strip()
        numero = (conta.get("numero") or "").strip()
        numero_busca = uc_nova or uc            # prefere o NOVO número (o antigo não bate mais)
        self._fechar_cookies()
        self._esperar_instalacao_carregar(numero_busca)   # card chega por AJAX -> espera
        # prioridade: 1) novo número da UC (exato); 2) endereço; 3) número antigo
        por_endereco = bool(rua and not uc_nova and self.page.locator("#edit-filtro-endereco").count() > 0)
        print(f"   [rge] selecionando instalação (uc_nova='{uc_nova}', uc={uc}, "
              f"rua='{rua}', por_endereco={por_endereco})...")
        marcado = False

        # FILTRO (a tela /selecionar-perfil-instalacao é PAGINADA): por ENDEREÇO ou por número
        if por_endereco:
            self._filtrar_por_endereco(conta)
        else:
            filtro = self.page.locator("#edit-filtro-num-instalacao")
            if filtro.count() > 0:
                try:
                    filtro.first.fill("")
                    filtro.first.fill(numero_busca)
                    pesq = self.page.locator("#edit-filtro-button")
                    if pesq.count() > 0:
                        self._clicar(pesq.first, f"filtrando pela instalação {numero_busca}...", pos_ms=AJAX)
                    self._esperar_instalacao_carregar(numero_busca)
                except Exception:
                    pass
            # A) radio com id exato — SÓ pra número "limpo" (dígitos). O NOVO nº da UC tem
            #    pontos (83.208.001-31) que quebram o seletor CSS -> nesse caso pula pra busca por texto.
            if re.fullmatch(r"[0-9A-Za-z_-]+", numero_busca or ""):
                el = self.page.locator(f"#instalacao-{numero_busca}")
                if el.count() > 0:
                    try:
                        el.first.scroll_into_view_if_needed(timeout=5000)
                    except Exception:
                        pass
                    for acao in ("check", "click"):
                        try:
                            el.first.check(timeout=3000) if acao == "check" else el.first.click(timeout=3000, force=True)
                            marcado = True
                            break
                        except Exception:
                            continue

        # B) acha o card pelo texto (ENDEREÇO ou UC) -> marca o radio
        if not marcado:
            alvo = self._achar_endereco_na_tela(rua, numero) if por_endereco else self._achar_uc_na_tela(numero_busca)
            if alvo:
                try:
                    alvo.scroll_into_view_if_needed()
                except Exception:
                    pass
                radio = primeiro_visivel([
                    alvo.locator("xpath=ancestor::*[.//input[@type='radio']][1]//input[@type='radio']"),
                    alvo.locator("xpath=preceding::input[@type='radio'][1]"),
                ], timeout_ms=4000)
                for tentativa in ("radio_check", "radio_click", "card_click"):
                    try:
                        if tentativa == "radio_check" and radio:
                            radio.check(timeout=3000)
                        elif tentativa == "radio_click" and radio:
                            radio.click(timeout=3000, force=True)
                        elif tentativa == "card_click":
                            alvo.click(timeout=3000)
                        else:
                            continue
                        marcado = True
                        break
                    except Exception:
                        continue

        # C) só há 1 instalação -> marca o único radio visível
        if not marcado:
            try:
                radios = self.page.locator("input[type=radio]:visible")
                if radios.count() == 1:
                    radios.first.check(timeout=3000)
                    marcado = True
            except Exception:
                pass

        if not marcado:
            print(f"   [rge] não consegui marcar a instalação (uc={uc}, rua='{rua}').")
            return False
        self._aguardar_carregamento(AJAX)
        print("   [rge] instalação marcada; avançando...")
        self._fechar_cookies()
        # avanço: 'Avançar' (#btn-buscar) OU 'Acessar' (#goto-page-btn).
        # NUNCA 'Próximo'/'Anterior' (#edit-next/#edit-prev = paginação) nem 'Pesquisar'.
        botao = primeiro_visivel([
            self.page.locator("#btn-buscar"),
            self.page.locator("#goto-page-btn"),
            self.page.get_by_role("button", name=re.compile(r"^\s*(avan[çc]ar|acessar)\s*$", re.I)),
            self.page.locator("input[type=submit][value*='van' i]"),
            self.page.locator("input[type=submit][value*='cessar' i]"),
        ], timeout_ms=8000)
        if botao:
            self._clicar(botao, "clicando 'Avançar/Acessar'...")
        else:
            print("   [rge] botão 'Avançar/Acessar' NÃO encontrado.")
        self._fechar_popups()   # 'código mudou' / 'cadastrar e-mail' aparecem ao acessar
        return True

    # -- (4) abrir "Débito e segunda via" ----------------------------------
    def _abrir_debito_segunda_via(self) -> bool:
        self._fechar_cookies()   # modais já foram tratados no _selecionar_instalacao
        link = primeiro_visivel([
            self.page.get_by_role("link", name=re.compile(r"d[ée]bito e segunda via", re.I)),
            self.page.get_by_text(re.compile(r"d[ée]bito e segunda via", re.I)),
        ], timeout_ms=10000)
        if link:
            self._clicar(link, "abrindo 'Débito e segunda via'...")
            return True
        print("   [rge] link 'Débito e segunda via' NÃO encontrado.")
        return False

    def _esperar_contas_pagas(self, timeout=40) -> bool:
        """Espera a seção 'MINHAS CONTAS PAGAS' aparecer — ela carrega DEPOIS da tabela
        de abertos (AJAX separado). Rola até o rodapé pra forçar o render e fecha o
        cookie no caminho."""
        alvo = re.compile(r"minhas contas pagas", re.I)
        fim = time.time() + timeout
        while time.time() < fim:
            self._fechar_cookies()
            self._remover_modais("popup da 2ª via")   # email/PIX podem aparecer aqui também
            try:
                if self.page.get_by_text(alvo).count() > 0:
                    print("   [rge] 'Minhas contas pagas' apareceu.")
                    time.sleep(1.0)   # deixa as linhas assentarem
                    return True
            except Exception:
                pass
            try:
                self.page.mouse.wheel(0, 1200)   # desce (a seção fica embaixo) e força o render
            except Exception:
                pass
            time.sleep(1)
        return False

    def _expandir_contas_pagas(self):
        """Se a seção estiver recolhida (sem botões 'Ver 2ª via'), expande clicando no título."""
        try:
            ja = (self.page.get_by_role("link", name=re.compile(r"ver 2.?\s*via", re.I)).count() > 0
                  or self.page.get_by_role("button", name=re.compile(r"ver 2.?\s*via", re.I)).count() > 0)
        except Exception:
            ja = False
        if ja:
            return  # já expandida
        cab = self.page.get_by_text(re.compile(r"minhas contas pagas", re.I))
        if cab.count() > 0:
            self._clicar(cab.first, "expandindo 'Minhas contas pagas'...", pos_ms=AJAX)

    # -- (5,6) achar o mês (aberto OU pago) e baixar o PDF -----------------
    def _baixar_fatura_mes(self, conta: dict):
        self._aguardar_historico()   # espera o SPA servicosonline + fecha cookies do domínio
        variantes = {v.strip().lower() for v in conta.get("mes_variantes", [conta["mes_referencia"]])}

        # espera a página INTEIRA (a seção "pagas" carrega por último; se ela veio, o topo
        # também já está lá) -> aí dá pra validar EM CIMA (abertas/atrasadas) E EMBAIXO (pagas).
        self._esperar_contas_pagas()
        self._expandir_contas_pagas()

        linha = self._linha_do_mes(variantes)
        if linha is None:
            print(f"   [rge] mês {conta['mes_referencia']} não achado (aberto nem pago; "
                  f"variantes={sorted(variantes)}).")
            return None
        try:
            texto_linha = linha.inner_text().lower()
        except Exception:
            texto_linha = ""

        if re.search(r"ver 2.?\s*via", texto_linha):
            # linha PAGA — tem o botão "Ver 2º via de conta" nela mesma
            botao = primeiro_visivel([
                linha.get_by_role("button", name=re.compile(r"ver 2.?\s*via", re.I)),
                linha.get_by_role("link", name=re.compile(r"ver 2.?\s*via", re.I)),
                linha.get_by_text(re.compile(r"ver 2.?\s*via", re.I)),
            ], timeout_ms=8000)
            if not botao:
                print("   [rge] linha (paga) sem botão 'Ver 2ª via'.")
                return None
            self._clicar(botao, "mês (pago) encontrado; abrindo 'Ver 2ª via de conta'...")
        elif "pague sua conta" in texto_linha:
            # linha EM ABERTO/ATRASADA — dropdown "Pague sua conta" -> menu "Ver 2ª via de conta"
            dd = primeiro_visivel([
                linha.get_by_role("button", name=re.compile(r"pague sua conta", re.I)),
                linha.get_by_text(re.compile(r"pague sua conta", re.I)),
            ], timeout_ms=6000)
            if not dd:
                print("   [rge] dropdown 'Pague sua conta' não encontrado na linha.")
                return None
            self._clicar(dd, "mês (aberto/atrasado) encontrado; abrindo 'Pague sua conta'...", pos_ms=AJAX)
            # o item do menu é um <a> SEM href (get_by_role('link') não pega); as pagas são
            # <button>. Busca o <a> VISÍVEL pelo texto (dentro da linha) -> não colide.
            v2 = primeiro_visivel([
                linha.locator("a:visible").filter(has_text=re.compile(r"ver 2.?\s*via", re.I)),
                self.page.locator("a:visible").filter(has_text=re.compile(r"ver 2.?\s*via", re.I)),
                self.page.get_by_role("link", name=re.compile(r"ver 2.?\s*via", re.I)),
            ], timeout_ms=8000)
            if not v2:
                print("   [rge] 'Ver 2ª via de conta' não apareceu no menu 'Pague sua conta'.")
                self._dump(f"falha_menu_{config.sanitizar(conta.get('uc',''))}")
                return None
            self._clicar(v2, "abrindo 'Ver 2ª via de conta'...")
        else:
            print("   [rge] linha do mês sem botão conhecido (nem 2ª via nem pague sua conta).")
            self._dump(f"falha_linha_{config.sanitizar(conta.get('uc',''))}")
            return None

        return self._baixar_pdf_conta(conta, variantes)

    def _baixar_pdf_conta(self, conta: dict, variantes: set):
        """Tela 'Conta de <mês>': CONFERE o mês, lê valor/venc, clica no PDF
        ('Gerar/Ver conta completa'), pega a nova aba e baixa pela URL (cookies)."""
        texto = ""
        try:
            texto = self.page.locator("body").inner_text()
        except Exception:
            pass
        # confere que é a conta do mês certo (evita baixar fatura de outro mês)
        if variantes and texto and not any(v in texto.lower() for v in variantes):
            print("   [rge] a tela da conta NÃO confere com o mês alvo — abortando (evita fatura errada).")
            self._dump(f"falha_confere_{config.sanitizar(conta.get('uc',''))}")
            return None
        venc = re.search(r"(\d{2}/\d{2}/\d{4})", texto)
        # valor pode vir NEGATIVO (cliente GD com crédito) -> reporta "0,00" (regra do CRM)
        mvalor = re.search(r"(-?)\s*R\$\s*(-?)\s*([\d.]*\d,\d{2})", texto)
        valor_str = ""
        if mvalor:
            valor_str = "0,00" if "-" in (mvalor.group(1) + mvalor.group(2)) else mvalor.group(3)

        botao_pdf = primeiro_visivel([
            self.page.get_by_role("button", name=re.compile(r"(gerar|ver)\s+conta\s+completa", re.I)),
            self.page.get_by_role("link", name=re.compile(r"(gerar|ver)\s+conta\s+completa", re.I)),
            self.page.get_by_text(re.compile(r"(gerar|ver)\s+conta\s+completa", re.I)),
        ], timeout_ms=12000)
        if not botao_pdf:
            print("   [rge] botão 'Gerar/Ver conta completa' não encontrado.")
            self._dump(f"falha_conta_{config.sanitizar(conta.get('uc',''))}")
            return None
        try:
            botao_pdf.scroll_into_view_if_needed(timeout=6000)
        except Exception:
            pass
        time.sleep(0.8)   # deixa assentar antes de abrir a nova aba
        print("   [rge] gerando/abrindo o PDF (nova aba) e baixando...")
        with self.context.expect_page(timeout=config.TIMEOUT_MS) as nova:
            try:
                botao_pdf.click()
            except Exception:
                botao_pdf.click(force=True)
        pdf_page = nova.value
        try:
            pdf_page.wait_for_load_state("domcontentloaded", timeout=config.TIMEOUT_MS)
        except Exception:
            pass
        pdf_url = pdf_page.url

        arquivo = ""
        try:
            resp = self.context.request.get(pdf_url, timeout=config.TIMEOUT_MS)
            if resp.ok:
                arquivo = str(self._salvar_pdf(resp.body(), conta))
            else:
                print(f"   [rge] PDF HTTP {resp.status} em {pdf_url[:60]}")
        finally:
            try:
                pdf_page.close()
            except Exception:
                pass

        if not arquivo:
            raise RuntimeError("Não consegui baixar o PDF da conta completa.")
        return {"arquivo": arquivo,
                "vencimento": venc.group(1) if venc else "",
                "valor": valor_str}

    def _linha_do_mes(self, variantes: set):
        try:
            linhas = self.page.locator("tr")
            n = linhas.count()
        except Exception:
            return None
        for i in range(n):
            l = linhas.nth(i)
            try:
                texto = l.inner_text().strip().lower()
            except Exception:
                continue
            if any(v in texto for v in variantes):
                return l
        return None

    def _salvar_pdf(self, dados: bytes, conta: dict):
        base = config.sanitizar(conta.get("nome_cliente") or conta.get("uc") or "fatura")
        destino = config.PASTA_FATURAS / f"{base}.pdf"
        if destino.exists():
            destino = config.PASTA_FATURAS / f"{base}_{config.sanitizar(conta['mes_referencia'])}.pdf"
        destino.write_bytes(dados)
        print(f"   [pdf] Salvo: {destino}")
        return destino

    # -- orquestração -------------------------------------------------------
    def processar_uc(self, conta: dict) -> dict:
        uc = conta["uc"]
        tag = config.sanitizar(uc)
        # A RGE mudou o formato da UC -> só dá pra localizar com o NOVO número (uc_secondary).
        # Sem ele, não consulta o portal: retorna falha na hora (preencher no CRM).
        uc_nova = str(conta.get("uc_aneel_api") or "").strip()
        if not uc_nova:
            print("   [rge] sem 'uc_secondary' (novo número da UC) — pulando sem consultar o portal.")
            return {"status": NAO_ENCONTRADO, "uc_nova": "", "vencimento": "", "valor": "",
                    "arquivo": "", "mensagem": "Sem novo número da UC (uc_secondary) no CRM"}
        self._ir_para_selecao_uc()
        print(f"   [rge] URL atual: {self.page.url}")
        if not self._selecionar_instalacao(conta):
            self._dump(f"falha_selecao_{tag}")
            return {"status": NAO_ENCONTRADO, "uc_nova": "", "vencimento": "", "valor": "",
                    "arquivo": "", "mensagem": f"Instalação {uc} não localizada"}
        if not self._abrir_debito_segunda_via():
            self._dump(f"falha_debito_{tag}")
        r = self._baixar_fatura_mes(conta)
        if r is None:
            self._dump(f"falha_fatura_{tag}")
            return {"status": FATURA_NAO_EMITIDA, "uc_nova": "", "vencimento": "", "valor": "",
                    "arquivo": "", "mensagem": f"Sem fatura para {conta['mes_referencia']}"}
        return {"status": CONCLUIDO, "uc_nova": uc, "vencimento": r["vencimento"],
                "valor": r["valor"], "arquivo": r["arquivo"], "mensagem": "Fatura baixada"}

    def processar_faturas_uc(self, contas_uc: list[dict]):
        """Uma UC pode ter vários meses; processa cada fatura (re-navega por segurança)."""
        resultados = []
        for conta in contas_uc:
            try:
                resultados.append(self.processar_uc(conta))
            except Exception:
                resultados.append(None)   # main tenta de novo via caminho individual
        return resultados

    # -- descoberta (dump do DOM) -------------------------------------------
    def _dump_modal_html(self):
        """Salva SCREENSHOT + HTML do modal que NÃO fechou — pra achar o seletor exato do botão.
        O screenshot vem primeiro porque sobrevive à navegação (o evaluate morre com
        'context destroyed' quando a tela está 'piscando')."""
        try:
            shot = config.PASTA_DIAGNOSTICO / "descoberta_rge_modal.png"
            self.page.screenshot(path=str(shot))
            print(f"   [rge] screenshot do modal salvo em: {shot}")
        except Exception as e:
            print(f"   [rge] falha no screenshot do modal: {e}")
        try:
            html = self.page.evaluate(
                "() => { const all=[...document.querySelectorAll('div,section,dialog,[role=dialog],app-modal,ngb-modal-window')];"
                " const m=all.find(e => /c[óo]digo.*mudou|receber suas faturas|velocidade do pix|norma aneel/i"
                ".test(e.innerText||'') && e.getBoundingClientRect().width>250);"
                " return m ? m.outerHTML : '(modal nao encontrado)'; }")
            destino = config.PASTA_DIAGNOSTICO / "descoberta_rge_modal_html.txt"
            destino.write_text(f"URL: {self.page.url}\n{'=' * 60}\n{str(html)[:9000]}", encoding="utf-8")
            print(f"   [rge] HTML do modal salvo em: {destino}")
        except Exception as e:
            print(f"   [rge] falha ao dumpar o modal: {e}")

    def _dump(self, rotulo: str):
        destino = config.PASTA_DIAGNOSTICO / f"descoberta_rge_{rotulo}.txt"
        linhas = [f"URL: {self.page.url}", "-" * 60]
        js = ("() => [...document.querySelectorAll('a,button,input,select,label,tr,[role=button],[role=radio]')]"
              ".filter(e=>{const r=e.getBoundingClientRect();return r.width||r.height})"
              ".map(e=>{const t=(e.innerText||e.value||e.getAttribute('aria-label')||e.placeholder||e.name||e.id||'').trim();"
              "return t?`${e.tagName.toLowerCase()} type=${e.type||''} id=${e.id||''} | \"${t.slice(0,80)}\"`:null})"
              ".filter(Boolean)")
        try:
            linhas.extend(self.page.evaluate(js))
        except Exception as e:
            linhas.append(f"(falha ao coletar: {e})")
        destino.write_text("\n".join(linhas), encoding="utf-8")
        print(f"   [dump] elementos salvos em: {destino}")
