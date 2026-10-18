"""
Robô da CELESC (Santa Catarina) — portal novo "Minha Celesc" (conecte.celesc.com.br).

Login em 2 passos, SEM captcha:
  1. abre a tela de login,
  2. clica "Entrar com e-mail" (os campos só aparecem depois disso),
  3. preenche e-mail/CPF + senha,
  4. clica "Entrar".

A navegação (achar a UC -> 2ª via -> baixar o PDF) ainda NÃO está mapeada — os métodos
processar_uc/processar_faturas_uc são stubs que dumpam o DOM pra a gente montar a receita
(rode `celesc_descobrir.py`). A COPEL segue BLINDADA (não herda esta base).
"""
import re
import time
import unicodedata

import config
from bot_base import BotBase, CredencialInvalida, primeiro_visivel


def _norm(s: str) -> str:
    """minúsculas + sem acento (pra casar 'Clóvis' com 'CLOVIS' etc.)."""
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


class CelescBot(BotBase):
    URL_LOGIN = config.URL_LOGIN_CELESC

    # -- login (e-mail/CPF + senha, 2 passos, sem captcha) -----------------
    def esta_logado(self) -> bool:
        try:
            url = (self.page.url or "").lower()
            if "autenticacao/login" in url or "/login" in url:
                return False
            # logado = saiu do login e não há campo de senha visível
            senha = self.page.locator("input[type='password']")
            return not (senha.count() > 0 and senha.first.is_visible())
        except Exception:
            return False

    def _erro_login(self) -> bool:
        """CELESC mostra 'Preenchimento incorreto! / Não foi possível realizar a sua
        autenticação com os dados informados' quando e-mail/senha não batem OU o cliente
        não migrou pro novo cadastro. Nos dois casos -> FALHA_LOGIN (não adianta re-tentar)."""
        try:
            loc = self.page.get_by_text(re.compile(
                r"preenchimento\s+incorreto|n[ãa]o foi poss[íi]vel realizar a sua autentica|"
                r"dados\s+informados", re.I))
            return loc.count() > 0 and loc.first.is_visible()
        except Exception:
            return False

    def _ja_tenho_cadastro(self):
        """A tela inicial oferece 'Fazer novo cadastro' / 'Já tenho o novo cadastro'.
        Clica em 'Já tenho o novo cadastro' pra ir pro login (se essa tela aparecer)."""
        link = primeiro_visivel([
            self.page.get_by_role("button", name=re.compile(r"j[áa]\s+tenho\s+o\s+novo\s+cadastro", re.I)),
            self.page.get_by_role("link", name=re.compile(r"j[áa]\s+tenho\s+o\s+novo\s+cadastro", re.I)),
            self.page.get_by_text(re.compile(r"j[áa]\s+tenho\s+o\s+novo\s+cadastro", re.I)),
        ], timeout_ms=6000)
        if link:
            try:
                link.click()
            except Exception:
                try:
                    link.click(force=True)
                except Exception:
                    pass
            self._aguardar_carregamento(config.ESPERA_POS_NAVEGACAO_MS)

    def _clicar_entrar_com_email(self):
        """Passo 1: abre o formulário de e-mail (os campos só surgem após esse clique)."""
        btn = primeiro_visivel([
            self.page.get_by_role("button", name=re.compile(r"entrar\s+com\s+e-?mail", re.I)),
            self.page.get_by_text(re.compile(r"entrar\s+com\s+e-?mail", re.I)),
        ], timeout_ms=10000)
        if btn:
            try:
                btn.click()
            except Exception:
                try:
                    btn.click(force=True)
                except Exception:
                    pass
            self._aguardar_carregamento(config.ESPERA_POS_NAVEGACAO_MS)

    def _campo_doc(self):
        return primeiro_visivel([
            self.page.locator("input[type='email']"),
            self.page.get_by_placeholder(re.compile(r"e-?mail|cpf|usu|documento", re.I)),
            self.page.locator("input[type='text']"),
        ])

    def _campo_senha(self):
        return primeiro_visivel([
            self.page.locator("input[type='password']"),
            self.page.get_by_placeholder(re.compile(r"senha", re.I)),
        ])

    def _botao_entrar(self):
        # "Entrar" (submit) — NÃO "Entrar com e-mail" (esse é o passo 1). Casa o texto exato.
        return primeiro_visivel([
            self.page.get_by_role("button", name=re.compile(r"^\s*entrar\s*$", re.I)),
            self.page.locator("button[type='submit']"),
        ], timeout_ms=8000)

    def garantir_login(self):
        if not self.URL_LOGIN:
            raise RuntimeError("URL_LOGIN_CELESC não definida.")
        self.page.goto(self.URL_LOGIN, wait_until="domcontentloaded")
        self._aguardar_carregamento(config.ESPERA_POS_NAVEGACAO_MS)
        if self.esta_logado():
            print("   [sessao] ja logado [OK]")
            return

        self._ja_tenho_cadastro()                # dispensa a tela "Novo cadastro", se aparecer
        self._clicar_entrar_com_email()          # passo 1: abre os campos
        doc = self._campo_doc()
        senha = self._campo_senha()
        if not doc or not senha:
            self._dump("login_sem_campos")
            raise RuntimeError("CELESC: não encontrei os campos de e-mail/senha.")
        # preenche COM CALMA (Angular precisa dos eventos): digita, dá blur e confere o valor
        doc.click(); doc.fill(self.login)
        senha.click(); senha.fill(self.senha)
        try:
            self.page.keyboard.press("Tab")        # blur -> dispara a validação do form
        except Exception:
            pass
        time.sleep(1.0)
        # garante que os valores REALMENTE entraram (senão o form dá 'Preenchimento incorreto')
        try:
            if (doc.input_value() or "").strip() != self.login.strip():
                doc.fill(self.login)
            if not (senha.input_value() or ""):
                senha.fill(self.senha)
        except Exception:
            pass
        print("   [login] usuario e senha preenchidos")

        # espera o botão 'Entrar' habilitar (some do disabled quando o form fica válido)
        botao = self._botao_entrar()
        fim_btn = time.time() + 8
        while botao and time.time() < fim_btn:
            try:
                if botao.is_enabled():
                    break
            except Exception:
                break
            time.sleep(0.4)
        if botao:
            try:
                botao.click()
            except Exception:
                botao.click(force=True)
        else:
            print("   [login] botão 'Entrar' não encontrado.")

        # ESPERA o carregamento pós-clique antes de decidir (tem tela que fica com spinner)
        self._aguardar_carregamento(config.ESPERA_POS_NAVEGACAO_MS)
        time.sleep(1.5)

        limite = time.time() + config.TIMEOUT_LOGIN_MS / 1000
        erros_seguidos = 0
        while time.time() < limite:
            if self.esta_logado():
                print("   [login] autenticado [OK]")
                return
            # só declara falha se o erro PERSISTIR (evita pegar um flash durante o carregamento)
            if self._erro_login():
                erros_seguidos += 1
                if erros_seguidos >= 2:
                    raise CredencialInvalida(
                        "CELESC: autenticação recusada ('Preenchimento incorreto' — "
                        "senha errada ou cliente sem o novo cadastro).")
            else:
                erros_seguidos = 0
            time.sleep(1.5)
        raise TimeoutError("CELESC: tempo esgotado esperando o login.")

    # -- navegação: dashboard -> histórico -> 2ª via do mês -----------------
    _MES_NOME = {1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril", 5: "maio",
                 6: "junho", 7: "julho", 8: "agosto", 9: "setembro", 10: "outubro",
                 11: "novembro", 12: "dezembro"}

    def _aguardar_dashboard(self, timeout=45) -> bool:
        """Espera o dashboard "Olá" / botão de histórico renderizar (SPA carrega devagar)."""
        marc = re.compile(r"hist[óo]rico de (contas|faturas)|2[ªa]\s*via de conta|trocar im[óo]vel", re.I)
        fim = time.time() + timeout
        while time.time() < fim:
            try:
                if self.page.get_by_text(marc).count() > 0:
                    time.sleep(1.0)
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def _fechar_avisos(self):
        """Dispensa os avisos da CELESC que tapam a tela:
          - modal 'Simplifique sua vida / Deseja receber sua fatura por e-mail?' -> 'Agora não'
          - banner 'Novo número da sua Unidade Consumidora'
        Clica 'Agora não' (dispensa de verdade) e remove o que sobrar + o fundo escuro."""
        try:
            btn = primeiro_visivel([
                self.page.get_by_role("button", name=re.compile(r"agora\s+n[ãa]o", re.I)),
                self.page.get_by_role("link", name=re.compile(r"agora\s+n[ãa]o", re.I)),
                self.page.get_by_text(re.compile(r"^\s*agora\s+n[ãa]o\s*$", re.I)),
            ], timeout_ms=3000)
            if btn:
                try:
                    btn.click()
                except Exception:
                    try:
                        btn.click(force=True)
                    except Exception:
                        pass
                time.sleep(0.5)
        except Exception:
            pass
        # remove (fallback) os avisos informativos + backdrop, libera o scroll
        try:
            js = """
            () => {
              const RX = /novo n[úu]mero da sua unidade|simplifique sua vida|receber sua fatura por e-?mail/i;
              let n = 0;
              for (const el of document.querySelectorAll('[class*="banner" i],[class*="alert" i],[role=dialog],[class*="modal" i],[class*="popup" i]')) {
                if (RX.test(el.innerText||'')) { try { el.remove(); n++; } catch(e){} }
              }
              if (n) {
                for (const b of document.querySelectorAll('[class*="backdrop" i],[class*="overlay" i],.cdk-overlay-backdrop')) { try { b.remove(); } catch(e){} }
                try { document.body.style.overflow=''; document.documentElement.style.overflow=''; } catch(e){}
              }
              return n;
            }
            """
            self.page.evaluate(js)
        except Exception:
            pass

    # -- seleção de imóvel (só quando o login tem 2+ UCs e o exibido não bate) ---
    def _tokens_chave(self, conta: dict) -> list[str]:
        """Tokens que identificam o imóvel da fatura (nome de rua + número + complemento
        tipo 'cx1'/'ap501'). O complemento é o que DESEMPATA 2 UCs no mesmo endereço."""
        txt = _norm(" ".join(str(conta.get(k) or "") for k in
                             ("logradouro", "numero", "complemento", "bairro")))
        toks = re.findall(r"[a-z0-9]{2,}", txt)
        stop = {"rua", "av", "avenida", "dos", "das", "de", "da", "do", "cx", "apto",
                "ap", "bl", "ed", "lt", "qd", "casa", "sala", "and", "na", "no"}
        # mantém números (595, 1859) e complementos colados (cx1, cx2, ap501)
        return [t for t in toks if t not in stop and t != "n/a" and len(t) >= 2]

    def _texto_topo_imovel(self) -> str:
        try:
            alvo = self.page.get_by_text(re.compile(r"trocar\s+im[óo]vel", re.I))
            if alvo.count() > 0:
                cont = alvo.first.locator(
                    "xpath=ancestor::*[self::div or self::header or self::button][1]")
                return _norm(cont.inner_text() or "")
        except Exception:
            pass
        return ""

    def _na_selecao_parceiro(self) -> bool:
        """True na tela 'Agora, escolha um parceiro de negócio' (login com acesso a mais de um
        titular: CPF pessoal + CNPJ do negócio). Vem ANTES da seleção de imóvel."""
        try:
            return self.page.get_by_text(re.compile(
                r"parceiro\s+de\s+neg[óo]cio", re.I)).count() > 0
        except Exception:
            return False

    def _selecionar_parceiro(self, conta: dict) -> bool:
        """Escolhe o parceiro cujo CPF/CNPJ == o `cnpj` da API (o card mostra o doc formatado).
        Sem cnpj / sem casar -> pega o 1º ('Para você'/pessoal)."""
        alvo = re.sub(r"\D", "", conta.get("cnpj") or "")
        # espera os cards
        fim = time.time() + 25
        while time.time() < fim:
            try:
                if self.page.get_by_role("button", name=re.compile(r"^\s*selecionar", re.I)).count() > 0:
                    break
            except Exception:
                pass
            time.sleep(1)
        js = r"""
        (alvo) => {
          const cand = [...document.querySelectorAll('button,a,[role=button]')]
            .filter(b => /selecionar/i.test(b.innerText||'') && !/unidade/i.test(b.innerText||''));
          let bi = -1;
          cand.forEach((b,i) => {
            let el=b, card=b;
            for (let k=0;k<7 && el;k++){ el=el.parentElement; if(el && (el.innerText||'').length>25) card=el; }
            const dig=(card.innerText||'').replace(/\D/g,'');
            if (alvo && dig.includes(alvo)) bi=i;
          });
          if (bi < 0 && cand.length) bi = 0;   // fallback: 1º parceiro (pessoal)
          if (bi >= 0) { cand[bi].scrollIntoView({block:'center'}); cand[bi].click(); }
          return { bi, count: cand.length };
        }
        """
        try:
            r = self.page.evaluate(js, alvo)
        except Exception:
            r = {"bi": -1, "count": 0}
        print(f"   [celesc] parceiro de negócio: {r.get('count')} opção(ões), "
              f"escolhido idx={r.get('bi')} (cnpj-alvo={alvo or '(nenhum)'})")
        self._aguardar_carregamento(config.ESPERA_POS_NAVEGACAO_MS)
        return r.get("bi", -1) >= 0

    def _na_selecao_imovel(self) -> bool:
        """True se estamos na tela 'Você deseja acessar ... qual imóvel?' (cards + 'Selecionar
        unidade') — a CELESC mostra isso LOGO APÓS o login quando há 2+ imóveis."""
        try:
            return self.page.get_by_text(re.compile(
                r"qual\s+im[óo]vel|selecionar\s+unidade|instala[çc][õo]es?\s+ativa", re.I)).count() > 0
        except Exception:
            return False

    def _garantir_imovel(self, conta: dict):
        """Garante que estamos no imóvel da fatura (casado por ENDEREÇO). Só age quando há
        2+ imóveis: se já estamos na tela de seleção -> escolhe o card certo; se estamos num
        dashboard cujo topo não bate -> clica 'Trocar imóvel' e escolhe."""
        toks = self._tokens_chave(conta)
        if self._na_selecao_imovel():
            self._selecionar_card_imovel(conta)   # login caiu direto na seleção (multi-imóvel)
            return
        if not toks:
            return  # sem endereço -> usa o exibido
        topo = self._texto_topo_imovel()
        if topo and all(t in topo for t in toks):
            return  # já é o imóvel certo
        self._trocar_imovel(conta)

    def _trocar_imovel(self, conta: dict) -> bool:
        btn = primeiro_visivel([
            self.page.get_by_role("button", name=re.compile(r"trocar\s+im[óo]vel", re.I)),
            self.page.get_by_text(re.compile(r"trocar\s+im[óo]vel", re.I)),
        ], timeout_ms=8000)
        if not btn:
            return False
        try:
            btn.click()
        except Exception:
            btn.click(force=True)
        self._aguardar_carregamento(config.ESPERA_POS_NAVEGACAO_MS)
        return self._selecionar_card_imovel(conta)

    def _selecionar_card_imovel(self, conta: dict) -> bool:
        """Na tela 'qual imóvel?': pontua os cards por ENDEREÇO (os cards mostram só o nº NOVO
        + endereço completo, não o antigo da API -> casa por endereço; desempata ap/cx/número)
        e clica 'Selecionar unidade' do melhor. Se nada casar, pega o 1º (evita travar)."""
        toks = self._tokens_chave(conta)
        # espera os cards renderizarem
        fim = time.time() + 30
        while time.time() < fim:
            try:
                if self.page.get_by_role("button", name=re.compile(r"selecionar\s+unidade", re.I)).count() > 0:
                    break
            except Exception:
                pass
            time.sleep(1)
        js = """
        (toks) => {
          const btns = [...document.querySelectorAll('button,[role=button]')]
            .filter(b => /selecionar\\s+unidade/i.test(b.innerText||''));
          let bi=-1, best=-1;
          btns.forEach((b,i) => {
            let el=b, card=b;
            for (let k=0;k<6 && el;k++){ el=el.parentElement; if(el && (el.innerText||'').length>40) card=el; }
            const txt=(card.innerText||'').normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').toLowerCase();
            const score=toks.reduce((s,t)=> s+(txt.includes(t)?1:0),0);
            if(score>best){best=score; bi=i;}
          });
          return {bi, best, count: btns.length};
        }
        """
        try:
            r = self.page.evaluate(js, toks)
        except Exception:
            r = {"bi": -1, "count": 0}
        idx, count, best = r.get("bi", -1), r.get("count", 0), r.get("best", -1)
        print(f"   [celesc] seleção de imóvel: {count} card(s), match idx={idx} (score={best})")
        if count <= 0:
            self._dump(f"selecao_imovel_{config.sanitizar(conta.get('uc',''))}")
            return False
        if idx < 0 or best <= 0:
            print("   [celesc] endereço não casou nenhum card — pegando o 1º (confira o resultado).")
            idx = 0
        botoes = self.page.get_by_role("button", name=re.compile(r"selecionar\s+unidade", re.I))
        try:
            botoes.nth(idx).scroll_into_view_if_needed(timeout=5000)
        except Exception:
            pass
        try:
            botoes.nth(idx).click()
        except Exception:
            botoes.nth(idx).click(force=True)
        self._aguardar_carregamento(config.ESPERA_POS_NAVEGACAO_MS)
        self._aguardar_dashboard()
        self._fechar_avisos()
        return True

    def _capturar_uc_nova(self) -> str:
        """Pega o NOVO número da UC do seletor de imóvel no topo:
        '281907201178 - CLOVIS LOCATELLI, 1859 - ...' -> 281907201178."""
        # 1) container do "Trocar imóvel" (o nº fica junto)
        try:
            alvo = self.page.get_by_text(re.compile(r"trocar\s+im[óo]vel", re.I))
            if alvo.count() > 0:
                cont = alvo.first.locator(
                    "xpath=ancestor::*[self::div or self::header or self::button][1]")
                m = re.search(r"\b(\d{9,15})\b", cont.inner_text() or "")
                if m:
                    return m.group(1)
        except Exception:
            pass
        # 2) fallback: primeiro nº longo do topo da página
        try:
            m = re.search(r"\b(\d{9,15})\b", self.page.locator("body").inner_text() or "")
            return m.group(1) if m else ""
        except Exception:
            return ""

    def _ir_para_historico(self) -> bool:
        self._fechar_avisos()   # o modal 'receber por e-mail' pode aparecer atrasado e tapar o botão
        alvo = primeiro_visivel([
            self.page.get_by_role("button", name=re.compile(r"hist[óo]rico de (contas|faturas)", re.I)),
            self.page.get_by_role("link", name=re.compile(r"hist[óo]rico de (contas|faturas)", re.I)),
            self.page.get_by_text(re.compile(r"hist[óo]rico de (contas|faturas)", re.I)),
        ], timeout_ms=12000)
        if not alvo:
            print("   [celesc] botão 'Histórico de contas' não encontrado.")
            return False
        try:
            alvo.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            pass
        alvo.click()
        self._aguardar_carregamento(config.ESPERA_POS_NAVEGACAO_MS)
        # espera a tabela "Últimos débitos" renderizar DE VERDADE (com botões 'Gerar 2ª via'
        # ou linhas de fatura), não só o cabeçalho — o SPA carrega as linhas por AJAX, atrasado.
        fim = time.time() + 60
        while time.time() < fim:
            try:
                tem_botao = self.page.get_by_role("button", name=re.compile(
                    r"gerar\s+2[ªa]\s*via", re.I)).count() > 0
                tem_tabela = self.page.get_by_text(re.compile(
                    r"[úu]ltimos d[ée]bitos|m[êe]s de refer[êe]ncia", re.I)).count() > 0
                if tem_botao or (tem_tabela and self.page.get_by_text(
                        re.compile(r"vencimento", re.I)).count() > 0):
                    time.sleep(1.0)
                    return True
            except Exception:
                pass
            self.page.mouse.wheel(0, 1000)   # a tabela fica embaixo
            time.sleep(1.5)
        return False

    # JS: ancora nos botões "Gerar 2ª via" (a linha é <ui-celesc-table-row>, não <tr>),
    # sobe até o CARD da linha e casa o NOME DO MÊS (coluna "Mês de referência") + o ANO
    # (validado pelo ano da data de vencimento). Tudo normalizado (sem acento).
    _JS_ACHAR_2VIA = r"""
    (args) => {
      const nome = args[0], vencAno = args[1];   // nome já minúsculo/sem acento; vencAno = "AAAA"
      const norm = s => (s||'').normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase();
      // ancora nas AÇÕES da linha: 'Gerar 2ª via' (paga) OU 'Pagar' (aberta -> abre modal)
      const btns = [...document.querySelectorAll('button,a,[role=button]')]
        .filter(b => { const t=(b.innerText||'').replace(/\s+/g,' ').trim();
                       return /gerar\s*2[ªa]?\s*via/i.test(t) || /^pagar$/i.test(t); });
      let bi = -1, tipo = "", venc = "", valor = "";
      const amostra = [];
      const MESES = /janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro/;
      for (let i = 0; i < btns.length; i++) {
        let el = btns[i], card = btns[i];
        for (let k = 0; k < 9 && el; k++) {
          el = el.parentElement; if (!el) break;
          const len = (el.innerText || '').length;
          if (len >= 20 && len <= 600) card = el;
          if (len > 600) break;
        }
        const raw = card.innerText || '', txt = norm(raw);
        const anos = (raw.match(/\b\d{2}\/\d{2}\/(\d{4})\b/g) || []).map(s => s.slice(-4));
        const temNome = new RegExp('\\b' + nome + '\\b').test(txt) || txt.includes(nome);
        const anoOk = anos.includes(vencAno);
        if (i < 20) amostra.push(((txt.match(MESES) || ['?'])[0]) + ':' + (anos.join(',') || '-'));
        if (temNome && anoOk) {
          bi = i;
          tipo = /^pagar$/i.test((btns[i].innerText||'').replace(/\s+/g,' ').trim()) ? 'pagar' : 'gerar';
          try { document.querySelectorAll('[data-celesc-alvo]').forEach(e=>e.removeAttribute('data-celesc-alvo')); } catch(e){}
          try { btns[i].setAttribute('data-celesc-alvo','1'); } catch(e){}   // Playwright clica nele
          const d = raw.match(/(\d{2}\/\d{2}\/\d{4})/);  venc = d ? d[1] : "";
          const v = raw.match(/R\$\s*([\d.]*\d,\d{2})/);  valor = v ? v[1] : "";
          break;
        }
      }
      return { bi, tipo, count: btns.length, venc, valor, amostra };
    }
    """

    def _achar_2via(self, nome: str, venc_ano: str, timeout=45):
        """Acha o índice do botão 'Gerar 2ª via' da fatura do MÊS `nome` (ex.: 'junho') cujo
        vencimento cai no ano `venc_ano`. Rola pra carregar o histórico. Devolve (i, venc, valor)."""
        if not nome or not venc_ano:
            return -1, "", ""
        print(f"   [celesc] procurando no histórico: mês='{nome}' ano-venc={venc_ano}...")
        fim = time.time() + timeout
        ultimo_count = -1
        r = {"bi": -1, "count": 0}
        while time.time() < fim:
            try:
                r = self.page.evaluate(self._JS_ACHAR_2VIA, [nome, venc_ano])
            except Exception:
                r = {"bi": -1, "count": 0}
            if r.get("bi", -1) >= 0:
                return r["bi"], r.get("tipo", "gerar"), r.get("venc", ""), r.get("valor", "")
            self.page.mouse.wheel(0, 1400)   # carrega mais linhas do histórico
            time.sleep(1.2)
            c = r.get("count", 0)
            if c == ultimo_count and c > 0:   # nº de botões estabilizou -> chegou no fim
                self.page.mouse.wheel(0, 2000); time.sleep(1.2)
                try:
                    r = self.page.evaluate(self._JS_ACHAR_2VIA, [nome, venc_ano])
                    if r.get("bi", -1) >= 0:
                        return r["bi"], r.get("tipo", "gerar"), r.get("venc", ""), r.get("valor", "")
                except Exception:
                    pass
                break
            ultimo_count = c
        print(f"   [celesc] NÃO achei. Ações (2ªvia/pagar)={r.get('count', 0)}. "
              f"Amostra (mês:venc-anos): {r.get('amostra', [])}")
        return -1, "", "", ""

    def _clicar_pw(self, loc):
        """Clique Playwright (trusted) — necessário pro Angular disparar o download."""
        loc.scroll_into_view_if_needed(timeout=6000)
        try:
            loc.click(timeout=8000)
        except Exception:
            loc.click(timeout=6000, force=True)

    def _baixar_por_indice(self, tipo: str, conta: dict) -> str:
        """Baixa a 2ª via clicando (Playwright/trusted) o botão que o _achar_2via MARCOU
        ([data-celesc-alvo]). 'gerar' baixa direto; 'pagar' abre o modal 'Pagar conta' e o
        'Gerar 2ª via' de dentro dele baixa."""
        tag = config.sanitizar(conta.get('uc', ''))
        alvo = self.page.locator("[data-celesc-alvo='1']").first
        try:
            if tipo == "pagar":
                print("   [celesc] fatura aberta — abrindo modal 'Pagar conta'...")
                self._clicar_pw(alvo)   # clica 'Pagar' -> abre o modal
                # espera o modal 'Pagar conta' com o 'Gerar 2ª via'
                fim = time.time() + 20
                while time.time() < fim:
                    try:
                        if self.page.get_by_text(re.compile(
                                r"detalhamento da conta|pagar conta", re.I)).count() > 0:
                            break
                    except Exception:
                        pass
                    time.sleep(0.5)
                time.sleep(1.0)
                # o 'Gerar 2ª via' do MODAL é o último no DOM (a overlay é anexada por último)
                botao = self.page.get_by_role("button", name=re.compile(r"gerar\s*2[ªa]\s*via", re.I))
                print("   [celesc] modal aberto — clicando 'Gerar 2ª via'...")
                with self.page.expect_download(timeout=config.TIMEOUT_MS) as dl_info:
                    self._clicar_pw(botao.last)
            else:
                print("   [celesc] gerando 2ª via (download direto)...")
                with self.page.expect_download(timeout=config.TIMEOUT_MS) as dl_info:
                    self._clicar_pw(alvo)
            download = dl_info.value
        except Exception as e:
            print(f"   [celesc] download não iniciou ({tipo}): {type(e).__name__}: {e}")
            self._dump(f"falha_download_{tag}")
            return ""
        return self._salvar_download(download, conta)

    def _salvar_download(self, download, conta: dict) -> str:
        base = config.sanitizar(conta.get("nome_cliente") or conta.get("uc") or "fatura")
        destino = config.PASTA_FATURAS / f"{base}_{config.sanitizar(conta['mes_referencia'])}.pdf"
        try:
            config.PASTA_FATURAS.mkdir(parents=True, exist_ok=True)
            download.save_as(str(destino))
            print(f"   [pdf] Salvo: {destino}")
            return str(destino)
        except Exception as e:
            print(f"   [celesc] falha ao salvar o PDF: {type(e).__name__}: {e}")
            return ""

    def _venc_dashboard(self) -> str:
        """Vencimento da fatura ATUAL exibida no dashboard ('Vence em DD/MM/AAAA') -> 'MM/AAAA'."""
        try:
            m = re.search(r"vence\s+em\s+\d{2}/(\d{2})/(\d{4})",
                          self.page.locator("body").inner_text() or "", re.I)
            return f"{m.group(1)}/{m.group(2)}" if m else ""
        except Exception:
            return ""

    def _baixar_2via_dashboard(self, conta: dict) -> str:
        """Baixa a 2ª via da fatura ABERTA (mês atual) pelo botão '2ª via de conta' do dashboard
        — a aberta NÃO tem 'Gerar 2ª via' no histórico (só 'Pagar')."""
        print("   [celesc] fatura ABERTA (mês atual) -> baixando pelo botão '2ª via de conta'...")
        botao = primeiro_visivel([
            self.page.get_by_role("button", name=re.compile(r"2[ªa]\s*via de conta", re.I)),
            self.page.get_by_role("link", name=re.compile(r"2[ªa]\s*via de conta", re.I)),
            self.page.get_by_text(re.compile(r"2[ªa]\s*via de conta", re.I)),
        ], timeout_ms=10000)
        if not botao:
            print("   [celesc] botão '2ª via de conta' não encontrado no dashboard.")
            self._dump(f"falha_2via_aberta_{config.sanitizar(conta.get('uc',''))}")
            return ""
        try:
            botao.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            pass
        try:
            with self.page.expect_download(timeout=config.TIMEOUT_MS) as dl_info:
                botao.click()
            return self._salvar_download(dl_info.value, conta)
        except Exception as e:
            print(f"   [celesc] '2ª via de conta' não baixou direto: {type(e).__name__}: {e}")
            self._dump(f"falha_2via_aberta_{config.sanitizar(conta.get('uc',''))}")
            return ""

    def processar_uc(self, conta: dict) -> dict:
        from resultado_log import CONCLUIDO, NAO_ENCONTRADO, FATURA_NAO_EMITIDA
        uc = conta.get("uc", "")
        # o login pode encadear telas antes do dashboard:
        #   1) 'escolha um parceiro de negócio' (CPF pessoal vs CNPJ do negócio) -> casa por cnpj
        #   2) 'qual imóvel?' (2+ imóveis do parceiro) -> casa por endereço
        if self._na_selecao_parceiro():
            print("   [celesc] login com múltiplos parceiros — escolhendo pelo CPF/CNPJ...")
            self._selecionar_parceiro(conta)
        if self._na_selecao_imovel():
            print("   [celesc] login com múltiplos imóveis — selecionando por endereço...")
            self._selecionar_card_imovel(conta)
        if not self._aguardar_dashboard():
            self._dump(f"sem_dashboard_{config.sanitizar(uc)}")
            return {"status": NAO_ENCONTRADO, "uc_nova": "", "vencimento": "", "valor": "",
                    "arquivo": "", "mensagem": "CELESC: dashboard não carregou"}
        self._fechar_avisos()
        self._garantir_imovel(conta)   # se caiu num imóvel errado (single default), troca
        uc_nova = self._capturar_uc_nova()
        print(f"   [celesc] novo nº da UC (topo): {uc_nova or '(não achei)'}")

        # alvo: NOME do mês (coluna "Mês de referência") + ANO validado pelo vencimento
        # (dez vence no ano seguinte). O vencimento varia por cliente (não é sempre mês+1),
        # então NÃO dá pra detectar a aberta pelo dashboard — busco no histórico as duas ações
        # ('Gerar 2ª via' p/ paga, 'Pagar' p/ aberta).
        mes_num = conta.get("mes_num") or 0
        mes_ano = int(conta.get("mes_ano") or 0)
        nome = _norm(self._MES_NOME.get(mes_num, ""))
        venc_ano = str(mes_ano + (1 if mes_num == 12 else 0)) if mes_ano else ""
        alvo = conta.get("mes_referencia") or f"{mes_num:02d}/{mes_ano}"

        # Histórico -> acha a linha do mês (paga = 'Gerar 2ª via'; aberta = 'Pagar' -> modal)
        if not self._ir_para_historico():
            self._dump(f"sem_historico_{config.sanitizar(uc)}")
            return {"status": NAO_ENCONTRADO, "uc_nova": uc_nova, "vencimento": "", "valor": "",
                    "arquivo": "", "mensagem": "CELESC: histórico não carregou"}
        bi, tipo, venc, valor = self._achar_2via(nome, venc_ano)
        if bi < 0:
            print(f"   [celesc] fatura de {nome or '?'}/{mes_ano or '?'} não achada no histórico.")
            self._dump(f"falha_mes_{config.sanitizar(uc)}")
            return {"status": FATURA_NAO_EMITIDA, "uc_nova": uc_nova, "vencimento": "", "valor": "",
                    "arquivo": "", "mensagem": f"CELESC: sem 2ª via ({nome}/{mes_ano})"}
        print(f"   [celesc] achei a fatura ({tipo}) — venc {venc or alvo}, valor {valor or '?'}.")
        arquivo = self._baixar_por_indice(tipo, conta)
        if not arquivo:
            return {"status": FATURA_NAO_EMITIDA, "uc_nova": uc_nova, "vencimento": venc, "valor": valor,
                    "arquivo": "", "mensagem": f"CELESC: 2ª via não baixou (venc {alvo})"}
        return {"status": CONCLUIDO, "uc_nova": uc_nova, "vencimento": venc, "valor": valor,
                "arquivo": arquivo, "mensagem": "Fatura baixada"}

    def processar_faturas_uc(self, contas_uc: list[dict]):
        """Uma UC pode ter vários meses; processa cada fatura (re-navega por segurança)."""
        resultados = []
        for conta in contas_uc:
            try:
                resultados.append(self.processar_uc(conta))
            except Exception:
                resultados.append(None)
        return resultados

    # -- dump do DOM (pra montar a receita) --------------------------------
    def _dump(self, rotulo: str):
        destino = config.PASTA_DIAGNOSTICO / f"descoberta_celesc_{rotulo}.txt"
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
