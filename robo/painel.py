"""
Painel do robô de faturas — GUI moderna em CustomTkinter.

- Aba "Executar": concessionária, modo (API/planilha), limite -> Rodar.
    * modo API      -> "Ensaio" (não envia pro CRM) + "Incluir usinas"
    * modo Planilha -> "Abrir planilha" (edita o contas.xlsx)
    * "Rodar e-mail" -> lê as faturas que chegam por e-mail (Energisa/CELESC/COPEL)
- Aba "Conexão CRM": URL + token da API + login do modo planilha (config_local.json).
- Aba "Configurações": captcha, pausas/tentativas (avançado) e modo 24/7.
- Aba "E-mail": SMTP de notificação (quem recebe / quando / servidor).
- Aba "Faturas (e-mail)": credenciais do Microsoft Graph (app-only, Mail.Read).
- Roda SILENCIOSO (sem CMD) e mostra o progresso (X/Y + barra) + resultados aqui.

Janela redimensionável e responsiva (abas roláveis). Segredos criptografados (DPAPI).

Rode pelo  painel.bat  (ou: pythonw robo/painel.py)
"""
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

ROBO = Path(__file__).resolve().parent          # extract_copel/robo
RAIZ = ROBO.parent                              # extract_copel/
LOCAL_JSON = RAIZ / "config_local.json"

import _caminhos  # noqa: E402,F401  (subpastas de robo/)
import config
from concessionarias import CONCESSIONARIAS

# ---- identidade visual Ilumisol (cores que funcionam no claro e no escuro) ----
# cores como tupla (claro, escuro); cor única = igual nos dois temas.
GREEN    = "#2E7D32"                 # verde Ilumisol (ação principal)
GREEN_D  = "#256628"                 # hover do verde
HEAD     = "#1E6A2B"                 # faixa verde do topo
HEAD_SUB = "#C8E6C9"                 # subtítulo na faixa
RED      = "#C0392B"                 # parar
RED_D    = "#A5342A"
MUTED    = ("#6B7280", "#9AA4B2")    # texto secundário
SEC_FG   = ("#FFFFFF", "#2B2F36")    # fundo dos cartões de seção
BTN_SEC  = ("#E8ECF1", "#343A42")    # botão secundário
BTN_SECD = ("#D7DEE6", "#3E444D")    # hover do secundário
BTN_SECT = ("#1F2937", "#E5E7EB")    # texto do botão secundário
ENTRY_FG = ("#FFFFFF", "#23272E")
ASSETS   = RAIZ / "assets"

ctk.set_appearance_mode("light")
ctk.set_widget_scaling(1.0)


def carregar_local() -> dict:
    if LOCAL_JSON.exists():
        try:
            return json.loads(LOCAL_JSON.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def salvar_local(d: dict):
    LOCAL_JSON.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")


class _Tip:
    """Tooltip simples (balão escuro ao passar o mouse) — ajuda pros campos técnicos."""
    def __init__(self, widget, texto: str):
        self.widget = widget
        self.texto = texto
        self.tip = None
        widget.bind("<Enter>", self._mostrar)
        widget.bind("<Leave>", self._esconder)

    def _mostrar(self, _=None):
        if self.tip or not self.texto:
            return
        x = self.widget.winfo_rootx() + 18
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.texto, bg="#111827", fg="white",
                 font=("Segoe UI", 9), justify="left", padx=10, pady=6,
                 wraplength=340, bd=0).pack()

    def _esconder(self, _=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class Painel(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Robô de Faturas")
        self._icones()
        self.local = carregar_local()
        self._proc = None
        self._parado = False
        self._total = 0
        self._ultimo_relatorio = None
        self._log_fh = None
        self._log_path = Path(config.PASTA_EXTRACAO) / "ultimo_log.txt"

        # fontes
        self.f_titulo = ctk.CTkFont(size=19, weight="bold")
        self.f_sub    = ctk.CTkFont(size=12)
        self.f_sec    = ctk.CTkFont(size=15, weight="bold")
        self.f_field  = ctk.CTkFont(size=11, weight="bold")
        self.f_small  = ctk.CTkFont(size=12)
        self.f_big    = ctk.CTkFont(size=16, weight="bold")

        self._cabecalho()

        # abas (CTkTabview) — mesmas abas de sempre
        self.A_EXEC = "▶  Executar"
        self.A_CRM  = "🔑  Conexão CRM"
        self.A_CFG  = "⚙  Configurações"
        self.A_MAIL = "✉  E-mail"
        self.A_FAT  = "📥  Faturas (e-mail)"
        self.tabs = ctk.CTkTabview(self, corner_radius=12, fg_color=SEC_FG,
                                   segmented_button_selected_color=GREEN,
                                   segmented_button_selected_hover_color=GREEN_D)
        self.tabs.pack(fill="both", expand=True, padx=16, pady=(6, 16))
        for nome in (self.A_EXEC, self.A_CRM, self.A_CFG, self.A_MAIL, self.A_FAT):
            self.tabs.add(nome)
        try:
            self.tabs._segmented_button.configure(font=ctk.CTkFont(size=13, weight="bold"))
        except Exception:
            pass

        self._aba_executar()
        self._aba_config()
        self._aba_ajustes()
        self._aba_email()
        self._aba_faturas_email()

        self._ajustar_tamanho()
        self._atualizar_status_24h()

    # ---------- infra visual ----------
    def _icones(self):
        """Ícone da janela/barra de tarefas (assets/icone.ico) + logo do cabeçalho."""
        self._logo = None
        try:   # sem isso o Windows agrupa na barra de tarefas com o ícone do Python
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Ilumisol.RoboFaturas")
        except Exception:
            pass
        try:
            self.iconbitmap(default=str(ASSETS / "icone.ico"))
        except Exception:
            pass
        try:
            self._logo = tk.PhotoImage(file=str(ASSETS / "icone_44.png"))
        except Exception:
            self._logo = None

    def _cabecalho(self):
        """Faixa verde do topo: logo + título + selo do 24/7 + alternar claro/escuro."""
        head = ctk.CTkFrame(self, corner_radius=0, fg_color=HEAD)
        head.pack(fill="x")
        dentro = ctk.CTkFrame(head, fg_color="transparent")
        dentro.pack(fill="x", padx=24, pady=14)
        if self._logo:
            tk.Label(dentro, image=self._logo, bg=HEAD, bd=0).pack(side="left", padx=(0, 14))
        txt = ctk.CTkFrame(dentro, fg_color="transparent")
        txt.pack(side="left")
        ctk.CTkLabel(txt, text="Robô de Faturas", font=self.f_titulo,
                     text_color="white").pack(anchor="w")
        ctk.CTkLabel(txt, text="Baixa as faturas das concessionárias e devolve pro CRM",
                     font=self.f_sub, text_color=HEAD_SUB).pack(anchor="w")

        direita = ctk.CTkFrame(dentro, fg_color="transparent")
        direita.pack(side="right")
        self.st24_var = tk.StringVar(value="")
        self.st24 = ctk.CTkLabel(direita, textvariable=self.st24_var, font=ctk.CTkFont(size=11, weight="bold"),
                                 text_color="white", fg_color=GREEN, corner_radius=9,
                                 width=190, height=26)
        self.st24.pack(side="top")
        self._modo_claro = True
        self.btn_tema = ctk.CTkButton(direita, text="🌙  Escuro", width=110, height=26,
                                      fg_color="#2A7D33", hover_color="#236329",
                                      font=ctk.CTkFont(size=11), command=self._alternar_tema)
        self.btn_tema.pack(side="top", pady=(8, 0))

    def _alternar_tema(self):
        self._modo_claro = not self._modo_claro
        ctk.set_appearance_mode("light" if self._modo_claro else "dark")
        self.btn_tema.configure(text="🌙  Escuro" if self._modo_claro else "☀  Claro")

    def _atualizar_status_24h(self):
        """Selo no topo: 24/7 ligado (com o próximo ciclo) ou desligado. Atualiza a cada 30s."""
        st = Path(config.PASTA_EXTRACAO) / "status_24h.txt"
        texto, cor = "24/7 desligado", "#5F7F64"
        try:
            if st.exists() and (time.time() - st.stat().st_mtime) < 6 * 3600:
                linha = st.read_text(encoding="utf-8").strip()
                if "desligado" not in linha:
                    m = re.search(r"pr[óo]ximo ciclo [àa]s (\d{2}:\d{2})", linha)
                    texto = ("● 24/7 ligado · próximo " + m.group(1)) if m else "● 24/7 rodando agora"
                    cor = GREEN
        except Exception:
            pass
        self.st24_var.set(texto)
        self.st24.configure(fg_color=cor)
        self.after(30_000, self._atualizar_status_24h)

    def _ajustar_tamanho(self):
        """Tamanho inicial que cabe o conteúdo, centralizado; janela redimensionável."""
        self.update_idletasks()
        w = 780
        h = min(900, max(640, self.winfo_screenheight() - 140))
        x = (self.winfo_screenwidth() - w) // 2
        y = max(0, (self.winfo_screenheight() - h) // 2 - 20)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(560, 520)

    # --- helpers de layout ---
    def _scroll(self, aba) -> ctk.CTkScrollableFrame:
        s = ctk.CTkScrollableFrame(self.tabs.tab(aba), fg_color="transparent")
        s.pack(fill="both", expand=True)
        s.columnconfigure(0, weight=1)
        return s

    def _ajuda_aba(self, pai, texto):
        ctk.CTkLabel(pai, text=texto, font=self.f_small, text_color=MUTED,
                     anchor="w", justify="left", wraplength=680).pack(fill="x", padx=6, pady=(0, 10))

    def _card(self, pai, titulo=None, desc=None, cols=1) -> ctk.CTkFrame:
        card = ctk.CTkFrame(pai, corner_radius=14, fg_color=SEC_FG)
        card.pack(fill="x", padx=4, pady=(0, 14))
        for c in range(cols):
            card.columnconfigure(c, weight=1)
        self._row = 0
        if titulo:
            ctk.CTkLabel(card, text=titulo, font=self.f_sec, anchor="w").grid(
                row=0, column=0, columnspan=max(cols, 1), sticky="w", padx=18, pady=(16, 0))
            self._row = 1
        if desc:
            ctk.CTkLabel(card, text=desc, font=self.f_small, text_color=MUTED,
                         anchor="w", justify="left", wraplength=640).grid(
                row=self._row, column=0, columnspan=max(cols, 1), sticky="w", padx=18, pady=(2, 2))
            self._row += 1
        return card

    def _rotulo(self, card, texto, row, col=0, span=1, tip=None):
        lb = ctk.CTkLabel(card, text=texto, font=self.f_field, text_color=MUTED, anchor="w")
        lb.grid(row=row, column=col, columnspan=span, sticky="w",
                padx=(18 if col == 0 else 8, 8), pady=(10, 3))
        if tip:
            _Tip(lb, tip)
        return lb

    def _entry(self, card, var, row, col=0, span=1, show=None):
        e = ctk.CTkEntry(card, textvariable=var, font=self.f_small, height=34,
                         fg_color=ENTRY_FG, **({"show": show} if show else {}))
        e.grid(row=row, column=col, columnspan=span, sticky="ew",
               padx=(18 if col == 0 else 8, 18 if col + span == card.grid_size()[0] or span > 1 else 8),
               pady=(0, 6))
        return e

    def _spin(self, card, var, row, col=0, lo=0, hi=99999, width=120):
        fr = ctk.CTkFrame(card, fg_color="transparent")
        fr.grid(row=row, column=col, sticky="w", padx=(18 if col == 0 else 8, 8), pady=(0, 10))

        def passo(d):
            try:
                v = int((var.get() or "0").strip())
            except ValueError:
                v = lo
            var.set(str(max(lo, min(hi, v + d))))
        ctk.CTkButton(fr, text="–", width=34, height=34, fg_color=BTN_SEC, hover_color=BTN_SECD,
                      text_color=BTN_SECT, command=lambda: passo(-1)).pack(side="left")
        ctk.CTkEntry(fr, textvariable=var, width=width - 68, height=34, justify="center",
                     fg_color=ENTRY_FG).pack(side="left", padx=4)
        ctk.CTkButton(fr, text="+", width=34, height=34, fg_color=BTN_SEC, hover_color=BTN_SECD,
                      text_color=BTN_SECT, command=lambda: passo(1)).pack(side="left")
        return fr

    def _optionmenu(self, card, valores, row, col=0, span=1, command=None, width=200):
        om = ctk.CTkOptionMenu(card, values=list(valores), command=command, height=34,
                               fg_color=ENTRY_FG, text_color=BTN_SECT, button_color=GREEN,
                               button_hover_color=GREEN_D, dropdown_hover_color=BTN_SECD)
        om.grid(row=row, column=col, columnspan=span, sticky="ew",
                padx=(18 if col == 0 else 8, 18), pady=(0, 6))
        return om

    def _btn_sec(self, pai, texto, cmd):
        return ctk.CTkButton(pai, text=texto, command=cmd, height=36, font=self.f_small,
                             fg_color=BTN_SEC, hover_color=BTN_SECD, text_color=BTN_SECT)

    def _btn_salvar(self, pai, cmd):
        return ctk.CTkButton(pai, text="✔  Salvar", command=cmd, height=38, font=self.f_big,
                             fg_color=GREEN, hover_color=GREEN_D)

    def _grade_botoes(self, pai, itens, cols=3):
        """Dispõe botões (texto, cmd) numa grade de N colunas (reflui / responsivo)."""
        gr = ctk.CTkFrame(pai, fg_color="transparent")
        for c in range(cols):
            gr.columnconfigure(c, weight=1)
        for i, (txt, cmd) in enumerate(itens):
            self._btn_sec(gr, txt, cmd).grid(row=i // cols, column=i % cols,
                                             sticky="ew", padx=5, pady=5)
        return gr

    # ---------- aba Executar ----------
    def _aba_executar(self):
        s = self._scroll(self.A_EXEC)
        self._ajuda_aba(s, "Baixa as faturas e devolve pro CRM. Escolha a concessionária e "
                           "clique em Rodar — ou leia as faturas que já chegaram por e-mail.")

        c = self._card(s, "O que rodar")
        c.columnconfigure(0, weight=1)
        self._rotulo(c, "CONCESSIONÁRIA", 2)
        self._labels = {
            (CONCESSIONARIAS[n]["label"] + ("" if CONCESSIONARIAS[n]["pronta"] else "  (em breve)")): n
            for n in CONCESSIONARIAS
        }
        self.conc_cb = self._optionmenu(c, list(self._labels), 3)
        self.conc_cb.set(list(self._labels)[0])

        self._rotulo(c, "MODO", 4, tip="API (CRM): pega as pendências direto do CRM e devolve. "
                                       "Planilha (local): usa o contas.xlsx que você edita à mão.")
        self.modo_var = tk.StringVar(value="api")
        mf = ctk.CTkFrame(c, fg_color="transparent")
        mf.grid(row=5, column=0, sticky="w", padx=14, pady=(0, 6))
        ctk.CTkRadioButton(mf, text="API (CRM)", variable=self.modo_var, value="api",
                           fg_color=GREEN, hover_color=GREEN_D,
                           command=self._atualizar_modo).pack(side="left", padx=(4, 0))
        ctk.CTkRadioButton(mf, text="Planilha (local)", variable=self.modo_var, value="plan",
                           fg_color=GREEN, hover_color=GREEN_D,
                           command=self._atualizar_modo).pack(side="left", padx=(22, 0))

        self._rotulo(c, "QUANTAS PROCESSAR   (0 = TODAS)", 6)
        self.limite_var = tk.StringVar(value="10")
        self._spin(c, self.limite_var, 7, lo=0, hi=99999)

        self.area = ctk.CTkFrame(c, fg_color="transparent")
        self.area.grid(row=8, column=0, sticky="w", padx=14, pady=(0, 14))
        self.sem_enviar = tk.BooleanVar(value=False)
        self._api_box = ctk.CTkCheckBox(self.area, text="Ensaio — só teste, NÃO envia pro CRM",
                                        variable=self.sem_enviar, onvalue=True, offvalue=False,
                                        fg_color=GREEN, hover_color=GREEN_D)
        self.incluir_usinas = tk.BooleanVar(value=True)
        self._api_usinas_box = ctk.CTkCheckBox(self.area, text="Incluir faturas das usinas (fila farms/readings)",
                                               variable=self.incluir_usinas, onvalue=True, offvalue=False,
                                               fg_color=GREEN, hover_color=GREEN_D)
        self._plan_box = ctk.CTkFrame(self.area, fg_color="transparent")
        self._btn_sec(self._plan_box, "📄  Abrir planilha (contas.xlsx)",
                      self._abrir_planilha).pack(side="left")
        ctk.CTkLabel(self._plan_box, text="   edite os dados e salve",
                     font=self.f_small, text_color=MUTED).pack(side="left")

        # ações principais — bem visíveis e centralizadas
        acao = self._card(s, "Ação")
        linha = ctk.CTkFrame(acao, fg_color="transparent")
        linha.grid(row=1, column=0, pady=(6, 4))
        self.btn_rodar = ctk.CTkButton(linha, text="▶   Rodar", font=self.f_big, height=48, width=170,
                                       fg_color=GREEN, hover_color=GREEN_D, command=self._rodar)
        self.btn_rodar.pack(side="left", padx=(0, 10))
        self.btn_email = ctk.CTkButton(linha, text="📧  Rodar e-mail", font=self.f_small, height=48, width=150,
                                       fg_color=BTN_SEC, hover_color=BTN_SECD, text_color=BTN_SECT,
                                       command=self._rodar_email)
        self.btn_email.pack(side="left", padx=(0, 10))
        self.btn_parar = ctk.CTkButton(linha, text="■  Parar", font=self.f_big, height=48, width=130,
                                       fg_color=RED, hover_color=RED_D, command=self._parar)
        self.btn_parar.pack(side="left")
        self.btn_parar.configure(state="disabled")
        ctk.CTkLabel(acao, text="“Rodar” usa o portal da concessionária escolhida acima.   "
                                "“Rodar e-mail” lê as faturas que chegam por e-mail (Energisa, CELESC, COPEL).",
                     font=self.f_small, text_color=MUTED, wraplength=640, justify="center").grid(
            row=2, column=0, pady=(2, 8), padx=18)

        # progresso
        prog = ctk.CTkFrame(acao, fg_color="transparent")
        prog.grid(row=3, column=0, sticky="ew", padx=18, pady=(6, 14))
        prog.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(value="Pronto.")
        ctk.CTkLabel(prog, textvariable=self.status_var, font=self.f_small,
                     text_color=MUTED, anchor="w").grid(row=0, column=0, sticky="w")
        self.cont_var = tk.StringVar(value="")
        ctk.CTkLabel(prog, textvariable=self.cont_var, font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=GREEN).grid(row=0, column=1, sticky="e")
        self.barra = ctk.CTkProgressBar(prog, height=12, corner_radius=6,
                                        progress_color=GREEN, mode="determinate")
        self.barra.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.barra.set(0)

        # resultados
        res = self._card(s, "Resultados")
        self.resumo_var = tk.StringVar(value="")
        ctk.CTkLabel(res, textvariable=self.resumo_var, font=self.f_small,
                     text_color=MUTED, wraplength=640, justify="left").grid(
            row=1, column=0, sticky="w", padx=18, pady=(2, 8))
        self._grade_botoes(res, [
            ("📊  Abrir relatório", self._abrir_relatorio),
            ("📁  Abrir pasta", self._abrir_pasta),
            ("🧾  Ver log", self._abrir_log_arquivo),
            ("🔎  Consulta CRM", self._abrir_consulta_crm),
            ("📈  Histórico", self._abrir_historico),
        ], cols=3).grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 14))

        self._atualizar_modo()

    def _atualizar_modo(self):
        self._plan_box.pack_forget()
        self._api_box.pack_forget()
        self._api_usinas_box.pack_forget()
        if self.modo_var.get() == "api":
            self._api_box.pack(anchor="w", pady=(2, 0))
            self._api_usinas_box.pack(anchor="w", pady=(8, 0))
        else:
            self._plan_box.pack(anchor="w", pady=(2, 0))

    # ---------- aba Conexão CRM ----------
    def _aba_config(self):
        s = self._scroll(self.A_CRM)
        self._ajuda_aba(s, "Endereço e token do CRM (modo API) e o login da agência virtual "
                           "(modo Planilha). Token e senhas ficam criptografados nesta máquina.")

        c = self._card(s, "CRM (modo API)")
        self._rotulo(c, "URL DA API", 1, tip="Endereço base da API do CRM, ex.: https://seu-crm/api")
        self.url_var = tk.StringVar(value=self.local.get("api_base_url", config.API_BASE_URL))
        self._entry(c, self.url_var, 2)
        self._rotulo(c, "TOKEN", 3, tip="Chave de acesso da API. Fica criptografada (DPAPI) — só abre neste usuário/PC.")
        self.token_var = tk.StringVar(value=config.API_TOKEN)      # já descriptografado
        self.token_entry = self._entry(c, self.token_var, 4, show="•")
        self.mostrar = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(c, text="mostrar token", variable=self.mostrar, onvalue=True, offvalue=False,
                        fg_color=GREEN, hover_color=GREEN_D, command=self._toggle_token).grid(
            row=5, column=0, sticky="w", padx=18, pady=(2, 14))

        c2 = self._card(s, "Login do modo planilha", cols=2)
        self._rotulo(c2, "CPF / CNPJ DA AGÊNCIA VIRTUAL", 1, col=0)
        self._rotulo(c2, "SENHA", 1, col=1)
        self.plan_login_var = tk.StringVar(value=config.PLAN_LOGIN)
        self.plan_senha_var = tk.StringVar(value=config.PLAN_SENHA)
        self._entry(c2, self.plan_login_var, 2, col=0)
        self._entry(c2, self.plan_senha_var, 2, col=1, show="•")
        ctk.CTkLabel(c2, text="🔒 Token e senhas ficam criptografados (só abrem neste usuário/computador).",
                     font=self.f_small, text_color=MUTED).grid(
            row=3, column=0, columnspan=2, sticky="w", padx=18, pady=(6, 14))

        bf = ctk.CTkFrame(s, fg_color="transparent")
        bf.pack(pady=(2, 10))
        self._btn_salvar(bf, self._salvar_config).pack(side="left", padx=6)
        self._btn_sec(bf, "Testar conexão", self._testar_api).pack(side="left", padx=6)

    # ---------- aba Configurações (robô) ----------
    _CAPTCHA_OPCOES = {
        "Extensão Buster (Chrome do robô)":           ("cdp", True, "buster"),
        "Solver próprio (áudio, faster-whisper)":     ("launch", True, "dom"),
        "Manual (eu resolvo na tela)":                ("cdp", False, "buster"),
    }

    def _aba_ajustes(self):
        s = self._scroll(self.A_CFG)
        self._ajuda_aba(s, "Como o robô resolve o captcha, quanto ele espera entre tentativas "
                           "e o modo 24/7 (rodar sozinho em horários fixos).")

        # Captcha
        c = self._card(s, "Captcha", "Como o robô resolve o “não sou robô” que a COPEL pede no login.")
        atual = (config.MODO_NAVEGADOR, bool(config.CAPTCHA_AUTO), config.CAPTCHA_METODO)
        rotulo = next((r for r, v in self._CAPTCHA_OPCOES.items() if v == atual),
                      next(iter(self._CAPTCHA_OPCOES)))
        self.captcha_cb = self._optionmenu(c, list(self._CAPTCHA_OPCOES), self._row,
                                           command=self._captcha_ajuda)
        self.captcha_cb.set(rotulo)
        self.cap_ajuda = ctk.CTkLabel(c, text="", font=self.f_small, text_color=MUTED,
                                      anchor="w", justify="left", wraplength=640)
        self.cap_ajuda.grid(row=self._row + 1, column=0, sticky="w", padx=18, pady=(2, 6))
        self._captcha_ajuda(rotulo)
        bx = ctk.CTkFrame(c, fg_color="transparent")
        bx.grid(row=self._row + 2, column=0, sticky="w", padx=14, pady=(2, 14))
        self._btn_sec(bx, "🌐  Abrir Chrome do robô", self._abrir_chrome_robo).pack(side="left")
        ctk.CTkLabel(bx, text="   só p/ Buster — 1ª vez: instale a extensão nessa janela",
                     font=self.f_small, text_color=MUTED).pack(side="left")

        self.ajuste_vars = {}

        # Tempos e tentativas — avançado (escondido por padrão)
        self.adv_card = self._card(s, None)
        topo = ctk.CTkFrame(self.adv_card, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        topo.columnconfigure(0, weight=1)
        ctk.CTkLabel(topo, text="Tempos e tentativas  (avançado)", font=self.f_sec,
                     anchor="w").grid(row=0, column=0, sticky="w")
        self._adv_aberto = False
        self.btn_adv = ctk.CTkButton(topo, text="Mostrar", width=90, height=30,
                                     fg_color=BTN_SEC, hover_color=BTN_SECD, text_color=BTN_SECT,
                                     command=self._toggle_avancado)
        self.btn_adv.grid(row=0, column=1, sticky="e")
        self.adv_body = ctk.CTkFrame(self.adv_card, fg_color="transparent")
        for cc in range(3):
            self.adv_body.columnconfigure(cc, weight=1)

        for i, (rot, chave) in enumerate([
            ("PAUSA ENTRE LOGINS COPEL (s)",   "PAUSA_ENTRE_LOGINS_CAPTCHA_S"),
            ("PAUSA RGE / CELESC (s)",         "PAUSA_ENTRE_LOGINS_S"),
            ("TEMPO MÁX. DO BUSTER (s)",       "CAPTCHA_BUSTER_TIMEOUT_S"),
            ("TENTATIVAS DE LOGIN",            "MAX_TENTATIVAS_LOGIN"),
            ("PAUSA ENTRE TENTATIVAS (s)",     "PAUSA_RETRY_LOGIN_S"),
            ("TENTATIVAS POR FATURA",          "MAX_TENTATIVAS"),
            ("PAUSA SE O GOOGLE BLOQUEAR (min)", "PAUSA_CAPTCHA_BLOQUEADO_MIN"),
        ]):
            r0 = (i // 3) * 2
            col = i % 3
            var = tk.StringVar(value=str(getattr(config, chave, 0)))
            ctk.CTkLabel(self.adv_body, text=rot, font=self.f_field, text_color=MUTED,
                         anchor="w").grid(row=r0, column=col, sticky="w", padx=(8, 12), pady=(6, 2))
            self._spin(self.adv_body, var, r0 + 1, col=col, lo=0, hi=9999)
            self.ajuste_vars[chave] = var

        # Modo 24/7
        c3 = self._card(s, "Modo 24/7", "Deixa o robô rodando sozinho dentro de um horário.", cols=3)
        self.conc_24h_vars = {}
        for col, (rot, chave) in enumerate([
            ("CONSULTAR O CRM A CADA (min)", "CONTINUO_INTERVALO_MIN"),
            ("FUNCIONA DAS (h)",             "CONTINUO_HORA_INICIO"),
            ("ATÉ AS (h) · 24 = dia todo",   "CONTINUO_HORA_FIM"),
        ]):
            var = tk.StringVar(value=str(getattr(config, chave, 0)))
            ctk.CTkLabel(c3, text=rot, font=self.f_field, text_color=MUTED, anchor="w").grid(
                row=self._row, column=col, sticky="w", padx=(18 if col == 0 else 8, 8), pady=(8, 2))
            self._spin(c3, var, self._row + 1, col=col, lo=0, hi=9999)
            self.ajuste_vars[chave] = var

        self._rotulo(c3, "CONCESSIONÁRIAS A CADA CICLO", self._row + 2, span=3)
        cf = ctk.CTkFrame(c3, fg_color="transparent")
        cf.grid(row=self._row + 3, column=0, columnspan=3, sticky="w", padx=14, pady=(0, 10))
        ativas = set(getattr(config, "CONTINUO_CONCESSIONARIAS", ["COPEL"]))
        for nome, info in CONCESSIONARIAS.items():
            if not info.get("pronta"):
                continue
            var = tk.BooleanVar(value=nome in ativas)
            ctk.CTkCheckBox(cf, text=nome, variable=var, onvalue=True, offvalue=False,
                            fg_color=GREEN, hover_color=GREEN_D).pack(side="left", padx=(4, 20))
            self.conc_24h_vars[nome] = var
        self.email_24h_var = tk.BooleanVar(value=bool(getattr(config, "CONTINUO_EMAIL", True)))
        ctk.CTkCheckBox(c3, text="✉  Também ler as faturas que chegam por E-MAIL (Energisa, CELESC, COPEL)",
                        variable=self.email_24h_var, onvalue=True, offvalue=False,
                        fg_color=GREEN, hover_color=GREEN_D).grid(
            row=self._row + 4, column=0, columnspan=3, sticky="w", padx=18, pady=(2, 10))

        # ligar/desligar o 24/7 pelo painel (cria/remove a tarefa automática do Windows)
        ctk.CTkLabel(c3, text="LIGAR / DESLIGAR O 24/7 NESTE COMPUTADOR", font=self.f_field,
                     text_color=MUTED, anchor="w").grid(
            row=self._row + 5, column=0, columnspan=3, sticky="w", padx=18, pady=(6, 2))
        lig = ctk.CTkFrame(c3, fg_color="transparent")
        lig.grid(row=self._row + 6, column=0, columnspan=3, sticky="w", padx=14, pady=(0, 14))
        self.btn_24h_on = ctk.CTkButton(lig, text="🟢  Ativar 24/7", height=38, font=self.f_small,
                                        fg_color=GREEN, hover_color=GREEN_D, command=self._ativar_24h)
        self.btn_24h_on.pack(side="left", padx=(4, 8))
        self.btn_24h_off = ctk.CTkButton(lig, text="⏹  Desativar 24/7", height=38, font=self.f_small,
                                         fg_color=BTN_SEC, hover_color=BTN_SECD, text_color=BTN_SECT,
                                         command=self._desativar_24h)
        self.btn_24h_off.pack(side="left")
        self.lbl_24h_estado = ctk.CTkLabel(lig, text="", font=self.f_small, text_color=MUTED)
        self.lbl_24h_estado.pack(side="left", padx=(14, 0))

        bs = ctk.CTkFrame(s, fg_color="transparent")
        bs.pack(pady=(2, 10))
        self._btn_salvar(bs, self._salvar_ajustes).pack(side="left", padx=6)
        self._btn_sec(bs, "📡  Status 24/7", self._ver_status_24h).pack(side="left", padx=6)
        self._btn_sec(bs, "📘  Guia", self._abrir_guia).pack(side="left", padx=6)
        self._atualizar_estado_24h()

    def _toggle_avancado(self):
        self._adv_aberto = not self._adv_aberto
        if self._adv_aberto:
            self.adv_body.grid(row=1, column=0, sticky="ew", padx=8, pady=(6, 12))
            self.btn_adv.configure(text="Esconder")
        else:
            self.adv_body.grid_forget()
            self.btn_adv.configure(text="Mostrar")

    _CAPTCHA_AJUDA = {
        "Extensão Buster (Chrome do robô)":
            "ℹ  O “Buster” é uma extensão do Chrome que resolve o captcha “não sou robô” ouvindo "
            "o áudio. Instala só na 1ª vez (botão “Abrir Chrome do robô” abaixo). É a opção padrão.",
        "Solver próprio (áudio, faster-whisper)":
            "ℹ  O robô resolve o captcha sozinho, pelo áudio (faster-whisper) — sem extensão. "
            "Não precisa instalar nada no Chrome.",
        "Manual (eu resolvo na tela)":
            "ℹ  O robô abre a janela e PARA no captcha pra você resolver na mão. Use só se as "
            "opções automáticas falharem.",
    }

    def _captcha_ajuda(self, escolha=None):
        if hasattr(self, "cap_ajuda"):
            self.cap_ajuda.configure(text=self._CAPTCHA_AJUDA.get(
                escolha or self.captcha_cb.get(), ""))

    # ---------- ligar/desligar o modo 24/7 (tarefa do Windows) ----------
    def _tarefa_24h_ativa(self) -> bool:
        try:
            out = subprocess.run(["schtasks", "/query", "/tn", "RoboFaturas24h"],
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
                                 capture_output=True, text=True, timeout=10)
            return out.returncode == 0
        except Exception:
            return False

    def _atualizar_estado_24h(self):
        if not hasattr(self, "lbl_24h_estado"):
            return
        if self._tarefa_24h_ativa():
            self.lbl_24h_estado.configure(text="● está ATIVO neste PC", text_color=GREEN)
        else:
            self.lbl_24h_estado.configure(text="○ está desligado", text_color=MUTED)

    def _rodar_ps_24h(self, remover: bool):
        ps1 = RAIZ / "instalacao" / "instalar_24h.ps1"
        if not ps1.exists():
            messagebox.showerror("24/7", f"Não achei o script:\n{ps1}")
            return None
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)]
        if remover:
            cmd.append("-Remover")
        try:
            self.configure(cursor="watch")
            self.update()
        except Exception:
            pass
        out = None
        try:
            out = subprocess.run(cmd, cwd=str(RAIZ),
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
                                 capture_output=True, text=True, timeout=90)
        except Exception as e:
            messagebox.showerror("24/7", str(e))
        try:
            self.configure(cursor="")
        except Exception:
            pass
        self._atualizar_estado_24h()
        return out

    def _ativar_24h(self):
        out = self._rodar_ps_24h(remover=False)
        if out is None:
            return
        if out.returncode == 0:
            if messagebox.askyesno(
                    "24/7 ativado",
                    "Modo 24/7 LIGADO: o robô sobe sozinho a cada logon e roda nos horários "
                    "definidos acima.\n\nDesligar a suspensão/hibernação do PC na tomada "
                    "(recomendado, pra ele não dormir)?"):
                falhou = False
                for args in (["standby-timeout-ac", "0"], ["hibernate-timeout-ac", "0"]):
                    try:
                        r = subprocess.run(["powercfg", "/change"] + args,
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
                                           capture_output=True, text=True, timeout=15)
                        falhou = falhou or r.returncode != 0
                    except Exception:
                        falhou = True
                if falhou:
                    messagebox.showinfo("Suspensão", "Não consegui mudar a energia automaticamente "
                                        "(pode precisar de administrador). Ajuste em Configurações do "
                                        "Windows › Sistema › Energia: “Suspensão” = Nunca (na tomada).")
        else:
            messagebox.showerror("24/7", "Não consegui ligar o 24/7.\n\n"
                                 + ((out.stderr or out.stdout).strip()[-600:] or "falhou"))

    def _desativar_24h(self):
        if not messagebox.askyesno("Desativar 24/7", "Desligar o modo 24/7 e remover a tarefa "
                                   "automática deste computador?"):
            return
        out = self._rodar_ps_24h(remover=True)
        if out is None:
            return
        if out.returncode == 0:
            messagebox.showinfo("24/7", "Modo 24/7 desligado.")
        else:
            messagebox.showerror("24/7", (out.stderr or out.stdout).strip()[-600:] or "falhou")

    # ---------- aba E-mail ----------
    _QUANDO = {
        "A cada execução (com o relatório anexado)": "cada_execucao",
        "Só quando der erro":                        "so_com_erro",
        "Resumo diário (1 e-mail por dia)":          "resumo_diario",
        "Desligado":                                 "desligado",
    }

    def _aba_email(self):
        import notificacao
        c = notificacao.cfg()
        s = self._scroll(self.A_MAIL)
        self._ajuda_aba(s, "E-mails de aviso do robô (não é a leitura de faturas — essa fica na aba "
                           "“Faturas (e-mail)”). Defina quem recebe, quando, e o servidor de envio.")

        q = self._card(s, "Quem recebe", cols=3)
        self._rotulo(q, "DESTINATÁRIOS  (separe por vírgula)", 1, span=3)
        self.em_dest = tk.StringVar(value=", ".join(c["destinatarios"]))
        self._entry(q, self.em_dest, 2, span=3)
        self._rotulo(q, "QUANDO ENVIAR", 3, span=2)
        self._rotulo(q, "HORA DO RESUMO DIÁRIO", 3, col=2)
        self.em_quando = self._optionmenu(q, list(self._QUANDO), 4, span=2)
        self.em_quando.set(next((k for k, v in self._QUANDO.items() if v == c["quando"]), "Desligado"))
        self.em_hora = tk.StringVar(value=str(c.get("hora_resumo", 18)))
        self._spin(q, self.em_hora, 4, col=2, lo=0, hi=23)
        al = ctk.CTkFrame(q, fg_color="transparent")
        al.grid(row=5, column=0, columnspan=3, sticky="w", padx=14, pady=(2, 14))
        self.em_alertas = tk.BooleanVar(value=bool(c.get("alertas", True)))
        ctk.CTkCheckBox(al, text="Alertas (CRM fora, captcha falhando, ciclo travado, disco cheio, sucesso abaixo de",
                        variable=self.em_alertas, onvalue=True, offvalue=False,
                        fg_color=GREEN, hover_color=GREEN_D).pack(side="left")
        self.em_limite = tk.StringVar(value=str(c.get("limite_taxa", 50)))
        ctk.CTkEntry(al, textvariable=self.em_limite, width=52, height=30, justify="center",
                     fg_color=ENTRY_FG).pack(side="left", padx=6)
        ctk.CTkLabel(al, text="%)", font=self.f_small).pack(side="left")

        srv = self._card(s, "Servidor de envio (SMTP)", cols=3)
        self._rotulo(srv, "PROVEDOR", 1, col=0)
        self._rotulo(srv, "SERVIDOR", 1, col=1)
        self._rotulo(srv, "PORTA / SEGURANÇA", 1, col=2)
        self.em_prov = self._optionmenu(srv, list(notificacao.PROVEDORES), 2, col=0,
                                        command=self._email_provedor)
        self.em_prov.set(next((n for n, v in notificacao.PROVEDORES.items() if v[0] and v[0] == c.get("smtp_host")),
                              "Outro (preencher)"))
        self.em_host = tk.StringVar(value=c.get("smtp_host", ""))
        self._entry(srv, self.em_host, 2, col=1)
        ps = ctk.CTkFrame(srv, fg_color="transparent")
        ps.grid(row=2, column=2, sticky="w", padx=8, pady=(0, 6))
        self.em_porta = tk.StringVar(value=str(c.get("smtp_porta", 587)))
        ctk.CTkEntry(ps, textvariable=self.em_porta, width=66, height=34, justify="center",
                     fg_color=ENTRY_FG).pack(side="left")
        self.em_seg = ctk.CTkOptionMenu(ps, values=["starttls", "ssl", "nenhuma"], width=110, height=34,
                                        fg_color=ENTRY_FG, text_color=BTN_SECT, button_color=GREEN,
                                        button_hover_color=GREEN_D)
        self.em_seg.set(c.get("seguranca", "starttls"))
        self.em_seg.pack(side="left", padx=(6, 0))
        self._rotulo(srv, "USUÁRIO (e-mail que envia)", 3, col=0)
        self._rotulo(srv, "SENHA  (Gmail: senha de app)", 3, col=1)
        self._rotulo(srv, "REMETENTE  (se diferente)", 3, col=2)
        self.em_user = tk.StringVar(value=c.get("usuario", ""))
        self.em_senha = tk.StringVar(value=c.get("senha", ""))
        self.em_rem = tk.StringVar(value=c.get("remetente", ""))
        self._entry(srv, self.em_user, 4, col=0)
        self._entry(srv, self.em_senha, 4, col=1, show="•")
        self._entry(srv, self.em_rem, 4, col=2)

        bs = ctk.CTkFrame(s, fg_color="transparent")
        bs.pack(pady=(2, 10))
        self._btn_salvar(bs, self._salvar_email).pack(side="left", padx=6)
        self._btn_sec(bs, "✉  Enviar e-mail de teste", self._testar_email).pack(side="left", padx=6)

    def _email_provedor(self, _evt=None):
        import notificacao
        host, porta, seg = notificacao.PROVEDORES[self.em_prov.get()]
        if host:
            self.em_host.set(host)
        self.em_porta.set(str(porta))
        self.em_seg.set(seg)

    def _salvar_email(self, avisar=True) -> bool:
        import segredos
        dest = [d.strip() for d in self.em_dest.get().replace(";", ",").split(",") if d.strip()]
        ruins = [d for d in dest if "@" not in d or "." not in d.split("@")[-1]]
        if ruins:
            messagebox.showerror("E-mail", f"Destinatário inválido: {', '.join(ruins)}")
            return False
        try:
            porta, hora, limite = int(self.em_porta.get()), int(self.em_hora.get()), int(self.em_limite.get())
        except ValueError:
            messagebox.showerror("E-mail", "Porta, hora e limite precisam ser números.")
            return False
        self.local["email"] = {
            "destinatarios": ", ".join(dest), "quando": self._QUANDO[self.em_quando.get()],
            "hora_resumo": hora, "alertas": bool(self.em_alertas.get()), "limite_taxa": limite,
            "smtp_host": self.em_host.get().strip(), "smtp_porta": porta, "seguranca": self.em_seg.get(),
            "usuario": self.em_user.get().strip(), "senha": segredos.proteger(self.em_senha.get()),
            "remetente": self.em_rem.get().strip(),
        }
        salvar_local(self.local)
        if avisar:
            messagebox.showinfo("Salvo", "Configuração de e-mail salva.")
        return True

    def _testar_email(self):
        if not self._salvar_email(avisar=False):
            return
        import notificacao
        c = notificacao.cfg()
        if not notificacao.configurado(c):
            messagebox.showwarning("E-mail", "Preencha destinatários, servidor e usuário/remetente.")
            return
        try:
            self.configure(cursor="watch")
            self.update()
        except Exception:
            pass
        corpo = notificacao._layout("E-mail de teste", "Robô de Faturas",
                                    "<p>Se você recebeu este e-mail, o envio está funcionando. ✅</p>")
        ok = notificacao.enviar("[Robô de Faturas] Teste de e-mail", corpo, c=c)
        try:
            self.configure(cursor="")
        except Exception:
            pass
        if ok:
            messagebox.showinfo("E-mail", f"Enviado para: {', '.join(c['destinatarios'])}")
        else:
            messagebox.showerror("E-mail", "Não consegui enviar. Confira servidor, porta, usuário e senha.\n"
                                 "Gmail: use uma 'senha de app' (precisa da verificação em 2 etapas).")

    def _abrir_historico(self):
        try:
            import relatorio_historico
            os.startfile(str(relatorio_historico.gerar()))
        except Exception as e:
            messagebox.showerror("Erro", str(e))

    def _abrir_guia(self):
        try:
            os.startfile(str(RAIZ / "GUIA-NUC.html"))
        except Exception as e:
            messagebox.showerror("Erro", str(e))

    def _ver_status_24h(self):
        st = Path(config.PASTA_EXTRACAO) / "status_24h.txt"
        texto = (st.read_text(encoding="utf-8").strip() if st.exists() else
                 "Modo 24/7 nunca rodou nesta máquina.\nPra ligar: instalar_24h.bat")
        if messagebox.askyesno("Status 24/7", texto + "\n\nAbrir a pasta de logs?"):
            p = Path(config.PASTA_EXTRACAO) / "logs"
            p.mkdir(parents=True, exist_ok=True)
            os.startfile(str(p))

    def _salvar_ajustes(self):
        modo, auto, metodo = self._CAPTCHA_OPCOES[self.captcha_cb.get()]
        cfg = {"MODO_NAVEGADOR": modo, "CAPTCHA_AUTO": auto, "CAPTCHA_METODO": metodo}
        for chave, var in self.ajuste_vars.items():
            txt = (var.get() or "").strip()
            if not txt.isdigit():
                messagebox.showerror("Valor inválido", f"{chave}: use só números inteiros.")
                return
            cfg[chave] = int(txt)
        if not (0 <= cfg["CONTINUO_HORA_INICIO"] <= 23 and 1 <= cfg["CONTINUO_HORA_FIM"] <= 24):
            messagebox.showerror("Valor inválido", "Horário 24/7: início de 0 a 23, fim de 1 a 24.")
            return
        cfg["CONTINUO_INTERVALO_MIN"] = max(1, cfg["CONTINUO_INTERVALO_MIN"])
        cfg["CONTINUO_CONCESSIONARIAS"] = [n for n, v in self.conc_24h_vars.items() if v.get()]
        cfg["CONTINUO_EMAIL"] = bool(self.email_24h_var.get())
        if not cfg["CONTINUO_CONCESSIONARIAS"] and not cfg["CONTINUO_EMAIL"]:
            messagebox.showerror("24/7", "Marque pelo menos uma concessionária ou o e-mail pro modo 24/7.")
            return
        self.local["config"] = cfg
        salvar_local(self.local)
        messagebox.showinfo("Salvo", "Configurações salvas (valem na próxima execução).")

    def _abrir_chrome_robo(self):
        try:
            subprocess.Popen([sys.executable, str(ROBO / "start.py"), "chrome"], cwd=str(RAIZ),
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
        except Exception as e:
            messagebox.showerror("Erro", str(e))

    def _abrir_consulta_crm(self):
        pasta = Path(config.PASTA_EXTRACAO)      # a consulta mais recente (uma por concessionária)
        arqs = sorted(pasta.glob("consulta_crm*.html"), key=lambda a: a.stat().st_mtime, reverse=True)
        p = arqs[0] if arqs else Path(config.ARQUIVO_CONSULTA_CRM)
        if not p.exists():
            messagebox.showinfo("Sem consulta", "Ainda não há consulta gravada — rode no modo API.")
            return
        try:
            os.startfile(str(p))
        except Exception as e:
            messagebox.showerror("Erro", str(e))

    def _toggle_token(self):
        self.token_entry.configure(show="" if self.mostrar.get() else "•")

    # ---------- ações ----------
    def _conc(self) -> str:
        return self._labels.get(self.conc_cb.get(), "COPEL")

    def _abrir_planilha(self):
        p = config.PLANILHA_CONTAS
        if not p.exists():
            try:
                from criar_modelo import criar_modelo
                criar_modelo()
            except Exception as e:
                messagebox.showerror("Erro", f"Não consegui criar o modelo: {e}")
                return
        try:
            os.startfile(str(p))
        except Exception as e:
            messagebox.showerror("Erro", str(e))

    def _relatorio_recente(self):
        """Prefere o relatório HTML (completo, com log); cai no .xlsx se não houver."""
        def preferir_html(caminho):
            h = Path(caminho).with_suffix(".html")
            return str(h) if h.exists() else str(caminho)
        if self._ultimo_relatorio and Path(self._ultimo_relatorio).exists():
            return preferir_html(self._ultimo_relatorio)
        try:
            arqs = sorted(Path(config.PASTA_RESULTADOS).glob("resultado_*.xlsx"),
                          key=lambda p: p.stat().st_mtime, reverse=True)
            return preferir_html(arqs[0]) if arqs else None
        except Exception:
            return None

    def _abrir_relatorio(self):
        r = self._relatorio_recente()
        if not r:
            messagebox.showinfo("Sem relatório", "Ainda não há relatório gerado.")
            return
        try:
            os.startfile(r)
        except Exception as e:
            messagebox.showerror("Erro", str(e))

    def _abrir_pasta(self):
        try:
            p = Path(config.PASTA_EXTRACAO)
            p.mkdir(parents=True, exist_ok=True)
            os.startfile(str(p))
        except Exception as e:
            messagebox.showerror("Erro", str(e))

    def _rodar(self):
        conc = self._conc()
        if not CONCESSIONARIAS[conc]["pronta"]:
            messagebox.showwarning("Em breve", f"A {conc} ainda não está pronta.\n"
                                   "Falta a receita do portal dela (os prints do fluxo).")
            return
        if self._proc and self._proc.poll() is None:
            messagebox.showinfo("Aguarde", "Já tem uma execução rodando.")
            return
        fonte = self.modo_var.get()
        limite = (self.limite_var.get() or "0").strip()
        cmd = [sys.executable, "-u", str(ROBO / "start.py"), fonte, limite, "--conc", conc, "--silencioso"]
        try:
            import pausa_captcha
            fim = pausa_captcha.ate(conc)
        except Exception:
            fim = None
        if fim:
            if not messagebox.askyesno(
                    "Captcha bloqueado",
                    f"A {conc} está em pausa até {fim:%H:%M} porque o Google bloqueou o captcha "
                    "(\"Try again later\").\n\nInsistir agora costuma AUMENTAR o bloqueio.\n\n"
                    "Rodar mesmo assim?", icon="warning", default="no"):
                return
            cmd.append("--ignorar-pausa")
        if fonte == "api" and self.sem_enviar.get():
            cmd.append("--sem-enviar")
        if fonte == "api" and not self.incluir_usinas.get():
            cmd.append("--sem-usinas")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        try:
            self._proc = subprocess.Popen(
                cmd, cwd=str(RAIZ), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=flags)
        except Exception as e:
            messagebox.showerror("Erro", str(e))
            return
        self.fila = queue.Queue()
        self._total = 0
        self._parado = False
        self.resumo_var.set("")
        self._abrir_log(conc, fonte, limite)
        self._set_rodando(True)
        self.status_var.set("Iniciando…")
        self.cont_var.set("")
        self.barra.configure(mode="determinate")
        self.barra.set(0)
        threading.Thread(target=self._ler_saida, args=(self._proc,), daemon=True).start()
        self.after(150, self._poll_fila)

    def _rodar_email(self):
        """Lê as faturas que chegam por e-mail (Energisa/CELESC/COPEL) e manda pro CRM.
        Não usa portal/captcha. Respeita o 'Ensaio' (não envia)."""
        if self._proc and self._proc.poll() is None:
            messagebox.showinfo("Aguarde", "Já tem uma execução rodando.")
            return
        cmd = [sys.executable, "-u", str(ROBO / "main.py"), "email", "--tudo"]
        if not self.sem_enviar.get():
            cmd.append("--enviar")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        try:
            self._proc = subprocess.Popen(
                cmd, cwd=str(RAIZ), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=flags)
        except Exception as e:
            messagebox.showerror("Erro", str(e))
            return
        self.fila = queue.Queue()
        self._total = 0
        self._parado = False
        self.resumo_var.set("")
        self._abrir_log("E-mail", "email", "0")
        self._set_rodando(True)
        self.status_var.set("Lendo os e-mails…")
        self.cont_var.set("")
        self.barra.configure(mode="indeterminate")
        self.barra.start()
        threading.Thread(target=self._ler_saida, args=(self._proc,), daemon=True).start()
        self.after(150, self._poll_fila)

    def _ler_saida(self, proc):
        try:
            for linha in proc.stdout:
                s = linha.rstrip()
                self._escrever_log(s)
                self.fila.put(("linha", s))
        except Exception:
            pass
        try:
            proc.wait()
        except Exception:
            pass
        self._fechar_log()
        self.fila.put(("fim", proc.returncode))

    # ---------- log em arquivo ----------
    def _abrir_log(self, conc, fonte, limite):
        try:
            Path(config.PASTA_EXTRACAO).mkdir(parents=True, exist_ok=True)
            self._log_fh = open(self._log_path, "w", encoding="utf-8")
            self._log_fh.write(f"# {conc} | modo={fonte} | limite={limite}\n\n")
            self._log_fh.flush()
        except Exception:
            self._log_fh = None

    def _escrever_log(self, texto: str):
        if self._log_fh:
            try:
                self._log_fh.write(texto + "\n")
                self._log_fh.flush()
            except Exception:
                pass

    def _fechar_log(self):
        if self._log_fh:
            try:
                self._log_fh.close()
            except Exception:
                pass
            self._log_fh = None

    def _abrir_log_arquivo(self):
        if not self._log_path.exists():
            messagebox.showinfo("Sem log", "Ainda não há log — rode uma vez primeiro.")
            return
        try:
            os.startfile(str(self._log_path))
        except Exception as e:
            messagebox.showerror("Erro", str(e))

    def _poll_fila(self):
        try:
            while True:
                tipo, val = self.fila.get_nowait()
                if tipo == "fim":
                    self._set_rodando(False)
                    if self._parado:
                        self.status_var.set("Parado pelo usuário.")
                    elif val == 0:
                        self.status_var.set("Concluído.")
                        if self._total:
                            self.barra.set(1)
                            self.cont_var.set(f"{self._total} / {self._total}")
                    else:
                        self.status_var.set(f"Encerrado (código {val}).")
                    return
                self._processar_linha(val)
        except queue.Empty:
            pass
        if self._proc and self._proc.poll() is None:
            self.after(150, self._poll_fila)

    def _processar_linha(self, linha: str):
        m = re.search(r"PROGRESSO:\s*(\d+)\s*/\s*(\d+)", linha)
        if m:
            atual, total = int(m.group(1)), int(m.group(2))
            self._total = total
            self.cont_var.set(f"{atual} / {total}")
            self.barra.set((atual / total) if total else 0)
            self.status_var.set("Processando faturas…")
            return
        r = re.search(r"RESUMO\s*\([^)]*\):\s*(.+)", linha)
        if r:
            self.resumo_var.set("Resultado:  " + r.group(1).strip())
            return
        r = re.search(r"[Rr]elat[óo]rio salvo em:\s*(.+)", linha)
        if r:
            self._ultimo_relatorio = r.group(1).strip()
            return
        low = linha.lower()
        if "[captcha]" in low:
            self.status_var.set("Resolvendo o captcha…")
        elif "usuario e senha preenchidos" in low or "autenticado" in low:
            self.status_var.set("Fazendo login…")
        elif "servidor pronto" in low or "iniciando o servidor" in low:
            self.status_var.set("Preparando o servidor de captcha…")
        elif linha.startswith("LOGIN:"):
            self.status_var.set("Entrando na conta…")
        elif "relat" in low and "salvo" in low:
            self.status_var.set("Gerando o relatório…")

    def _set_rodando(self, rodando: bool):
        self.btn_rodar.configure(state="disabled" if rodando else "normal")
        self.btn_email.configure(state="disabled" if rodando else "normal")
        self.btn_parar.configure(state="normal" if rodando else "disabled")
        if not rodando:                     # para a barra indeterminada (modo e-mail)
            try:
                self.barra.stop()
                self.barra.configure(mode="determinate")
            except Exception:
                pass

    def _parar(self):
        """Aborta a execução: mata o processo e TODA a árvore de filhos (navegador, etc.)."""
        proc = self._proc
        if not proc or proc.poll() is not None:
            return
        self._parado = True
        self.btn_parar.configure(state="disabled")
        self.status_var.set("Parando… (fechando o navegador)")
        try:
            # taskkill /T mata o start.py + filhos (Chrome/Playwright); /F força
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
                           capture_output=True, timeout=15)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        # o _ler_saida detecta o fim e o _poll_fila mostra "Parado pelo usuário"

    # ---------- aba Faturas por e-mail (Microsoft Graph) ----------
    def _aba_faturas_email(self):
        s = self._scroll(self.A_FAT)
        self._ajuda_aba(s, "Leitura das faturas que chegam por e-mail, via Microsoft Graph "
                           "(app-only, somente leitura). O segredo fica criptografado nesta máquina.")

        c = self._card(s, "Microsoft Graph (app-only, Mail.Read)")
        self._rotulo(c, "DIRECTORY (TENANT) ID", self._row,
                     tip="ID do diretório (tenant) do Azure AD da sua organização.")
        self.fe_tenant = tk.StringVar(value=getattr(config, "EMAIL_GRAPH_TENANT", ""))
        self._entry(c, self.fe_tenant, self._row + 1)
        self._rotulo(c, "APPLICATION (CLIENT) ID", self._row + 2,
                     tip="ID do aplicativo registrado no Azure (App registration).")
        self.fe_client = tk.StringVar(value=getattr(config, "EMAIL_GRAPH_CLIENT", ""))
        self._entry(c, self.fe_client, self._row + 3)

        tem_seg = bool((self.local.get("email_secret") or "").strip())
        self._rotulo(c, "SEGREDO (VALOR)" + ("   — já salvo; deixe em branco pra manter" if tem_seg
                                             else "   — cole o Valor do segredo do app"), self._row + 4,
                     tip="O 'Valor' do client secret do App registration. Criptografado (DPAPI).")
        self.fe_secret = tk.StringVar(value="")
        self._entry(c, self.fe_secret, self._row + 5, show="•")
        self._rotulo(c, "CAIXAS A LER  (separe por vírgula)", self._row + 6,
                     tip="E-mails das caixas que o robô vai ler, ex.: faturas@empresa.com, matriz@empresa.com")
        self.fe_caixas = tk.StringVar(value=", ".join(getattr(config, "EMAIL_CAIXAS", []) or []))
        self._entry(c, self.fe_caixas, self._row + 7)

        bs = ctk.CTkFrame(s, fg_color="transparent")
        bs.pack(pady=(2, 10))
        self._btn_salvar(bs, self._salvar_faturas_email).pack(side="left", padx=6)
        self._btn_sec(bs, "🔌  Testar leitura", self._testar_faturas_email).pack(side="left", padx=6)

    def _salvar_faturas_email(self, avisar=True) -> bool:
        import segredos
        self.local["email_tenant"] = self.fe_tenant.get().strip()
        self.local["email_client"] = self.fe_client.get().strip()
        self.local["email_caixas"] = [c.strip() for c in
                                      self.fe_caixas.get().replace(";", ",").split(",") if c.strip()]
        novo = self.fe_secret.get().strip()
        if novo:                                  # vazio = mantém o segredo já salvo
            self.local["email_secret"] = segredos.proteger(novo)
        salvar_local(self.local)
        self.fe_secret.set("")                    # não deixa o segredo em claro na tela
        if avisar:
            messagebox.showinfo("Salvo", "Configuração de faturas por e-mail salva.")
        return True

    def _testar_faturas_email(self):
        if not self._salvar_faturas_email(avisar=False):
            return
        import importlib
        importlib.reload(config)
        import email_graph
        importlib.reload(email_graph)
        caixas = getattr(config, "EMAIL_CAIXAS", []) or []
        if not caixas:
            messagebox.showwarning("Faturas por e-mail", "Preencha ao menos uma caixa.")
            return
        linhas = []
        for c in caixas:
            try:
                m = email_graph.listar_mensagens(c, desde_dias=7)
                linhas.append(f"✔  {c}: {len(m)} msg(s) com anexo (7d)")
            except Exception as e:
                linhas.append(f"✖  {c}: {type(e).__name__}")
        messagebox.showinfo("Teste de leitura", "\n".join(linhas))

    def _salvar_config(self):
        import segredos
        self.local["api_base_url"] = self.url_var.get().strip()
        self.local["api_token"] = segredos.proteger(self.token_var.get().strip())
        self.local["plan_login"] = self.plan_login_var.get().strip()
        self.local["plan_senha"] = segredos.proteger(self.plan_senha_var.get().strip())
        salvar_local(self.local)
        messagebox.showinfo("Salvo", "Configuração salva (vale nas próximas execuções).")

    def _testar_api(self):
        self._salvar_config()
        try:
            out = subprocess.run(
                [sys.executable, "-c",
                 "import _caminhos, api_faturas; print(len(api_faturas.buscar_faturas(alias='')))"],
                cwd=str(ROBO), capture_output=True, text=True, timeout=40)
            if out.returncode == 0 and out.stdout.strip().isdigit():
                messagebox.showinfo("Conexão OK",
                                    f"A API respondeu: {out.stdout.strip()} fatura(s) no total.")
            else:
                messagebox.showerror("Erro", (out.stderr or out.stdout).strip()[-500:] or "falhou")
        except Exception as e:
            messagebox.showerror("Erro", str(e))


if __name__ == "__main__":
    Painel().mainloop()
