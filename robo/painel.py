"""
Painel do robô de faturas (janela Windows, Tkinter — sem dependências extras).

- Aba "Executar": concessionária, modo (API/planilha), limite -> Rodar.
    * modo API      -> "Ensaio" (não envia pro CRM)
    * modo Planilha -> "Abrir planilha" (edita o contas.xlsx)
- Aba "Configuração API": URL + token (salvos em config_local.json).
- Aba "Configurações": captcha (Buster / solver próprio / manual), pausas e tentativas
  (salvos em config_local.json, chave "config" — valem na próxima execução).
- Roda SILENCIOSO (sem CMD) e mostra o progresso (X/Y + barra) + resultados aqui.

Rode pelo  painel.bat  (ou: python robo/painel.py)
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
from tkinter import ttk, messagebox

ROBO = Path(__file__).resolve().parent          # extract_copel/robo
RAIZ = ROBO.parent                              # extract_copel/
LOCAL_JSON = RAIZ / "config_local.json"

import _caminhos  # noqa: E402,F401  (subpastas de robo/)
import config
from concessionarias import CONCESSIONARIAS

# paleta
BG      = "#F1F4F7"
CARD    = "#FFFFFF"
TXT     = "#1F2937"
MUTED   = "#6B7280"
FIELDLB = "#7C8794"
LINHA   = "#E3E8EE"
ACCENT  = "#2E7D32"
ACCENT2 = "#256628"
HEAD    = "#1E6A2B"     # faixa do topo
HEAD2   = "#C8E6C9"     # subtítulo na faixa
BTN     = "#F1F4F7"
BTN2    = "#E3E8EE"
TAB_OFF = "#E4E9EE"
TROUGH  = "#E6EAEE"
ASSETS  = RAIZ / "assets"


def carregar_local() -> dict:
    if LOCAL_JSON.exists():
        try:
            return json.loads(LOCAL_JSON.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def salvar_local(d: dict):
    LOCAL_JSON.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")


class Painel(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Robô de Faturas")
        self.configure(bg=BG)
        self._icones()
        self.resizable(False, False)
        self.local = carregar_local()
        self._proc = None
        self._parado = False
        self._total = 0
        self._ultimo_relatorio = None
        self._log_fh = None
        self._log_path = Path(config.PASTA_EXTRACAO) / "ultimo_log.txt"
        self._estilos()

        # faixa verde do topo: ícone + título + selo do 24/7
        head = tk.Frame(self, bg=HEAD)
        head.pack(fill="x")
        dentro = tk.Frame(head, bg=HEAD)
        dentro.pack(fill="x", padx=26, pady=16)
        if self._logo:
            tk.Label(dentro, image=self._logo, bg=HEAD).pack(side="left", padx=(0, 14))
        txt = tk.Frame(dentro, bg=HEAD)
        txt.pack(side="left")
        tk.Label(txt, text="Robô de Faturas", bg=HEAD, fg="white",
                 font=("Segoe UI Semibold", 18)).pack(anchor="w")
        tk.Label(txt, text="Baixa as faturas das concessionárias e devolve pro CRM",
                 bg=HEAD, fg=HEAD2, font=("Segoe UI", 9)).pack(anchor="w")
        self.st24_var = tk.StringVar(value="")
        self.st24 = tk.Label(dentro, textvariable=self.st24_var, bg=ACCENT, fg="white",
                             font=("Segoe UI Semibold", 8), padx=10, pady=3)
        self.st24.pack(side="right")
        self._atualizar_status_24h()

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=22, pady=(16, 22))
        nb.add(self._aba_executar(nb), text="▶  Executar")
        nb.add(self._aba_config(nb), text="🔑  Conexão CRM")
        nb.add(self._aba_ajustes(nb), text="⚙  Configurações")
        nb.add(self._aba_email(nb), text="✉  E-mail")
        self._ajustar_tamanho()

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
                    cor = ACCENT
        except Exception:
            pass
        self.st24_var.set(texto)
        self.st24.config(bg=cor)
        self.after(30_000, self._atualizar_status_24h)

    def _ajustar_tamanho(self):
        """Dimensiona a janela pra caber TODO o conteúdo (sem cortar) e centraliza."""
        self.update_idletasks()
        w = max(580, self.winfo_reqwidth())
        h = self.winfo_reqheight() + 6
        x = (self.winfo_screenwidth() - w) // 2
        y = max(0, (self.winfo_screenheight() - h) // 2 - 20)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(w, h)

    def _estilos(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except Exception:
            pass
        # notebook — abas planas
        st.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0),
                     bordercolor=LINHA, lightcolor=CARD, darkcolor=CARD)
        st.configure("TNotebook.Tab", background=TAB_OFF, foreground=MUTED,
                     font=("Segoe UI", 10), padding=(22, 9), borderwidth=0,
                     lightcolor=TAB_OFF, bordercolor=BG)
        st.map("TNotebook.Tab", background=[("selected", CARD), ("active", "#EDF1F4")],
               foreground=[("selected", ACCENT)], font=[("selected", ("Segoe UI Semibold", 10))],
               lightcolor=[("selected", CARD)], expand=[("selected", (0, 0, 0, 0))])
        st.layout("TNotebook.Tab", [("Notebook.tab", {"sticky": "nswe", "children": [
            ("Notebook.padding", {"side": "top", "sticky": "nswe", "children": [
                ("Notebook.label", {"side": "top", "sticky": ""})]})]})])   # sem retângulo de foco
        # frames / labels
        st.configure("Card.TFrame", background=CARD)
        st.configure("TLabel", background=CARD, foreground=TXT, font=("Segoe UI", 10))
        st.configure("Field.TLabel", background=CARD, foreground=FIELDLB,
                     font=("Segoe UI Semibold", 8))
        st.configure("Muted.TLabel", background=CARD, foreground=MUTED, font=("Segoe UI", 9))
        st.configure("Secao.TLabel", background=CARD, foreground=TXT, font=("Segoe UI Semibold", 11))
        st.configure("Save.TButton", font=("Segoe UI Semibold", 10), padding=(20, 9),
                     foreground="white", background=ACCENT, borderwidth=0,
                     lightcolor=ACCENT, darkcolor=ACCENT, focuscolor=ACCENT)
        st.map("Save.TButton", background=[("active", ACCENT2)])
        st.configure("Cont.TLabel", background=CARD, foreground=ACCENT, font=("Segoe UI Semibold", 15))
        st.configure("TRadiobutton", background=CARD, foreground=TXT, font=("Segoe UI", 10))
        st.configure("TCheckbutton", background=CARD, foreground=TXT, font=("Segoe UI", 10))
        # campos brancos
        st.configure("TCombobox", fieldbackground="white", foreground=TXT, padding=6, arrowsize=15)
        st.map("TCombobox", fieldbackground=[("readonly", "white")],
               foreground=[("readonly", TXT)],
               selectbackground=[("readonly", "white")], selectforeground=[("readonly", TXT)])
        for w in ("TSpinbox", "TEntry", "TCombobox"):
            st.configure(w, bordercolor=LINHA, lightcolor="white", darkcolor="white")
            st.map(w, bordercolor=[("focus", ACCENT)], lightcolor=[("focus", "white")])
        st.configure("TSpinbox", fieldbackground="white", padding=6, arrowsize=13,
                     background="white", arrowcolor=MUTED)
        st.configure("TEntry", fieldbackground="white", padding=7)
        st.configure("TCombobox", background=BTN, arrowcolor=MUTED)
        st.configure("TSeparator", background=LINHA)
        st.map("TRadiobutton", indicatorcolor=[("selected", ACCENT), ("!selected", "white")],
               background=[("active", CARD)])
        st.map("TCheckbutton", indicatorcolor=[("selected", ACCENT), ("!selected", "white")],
               background=[("active", CARD)])
        # botões
        st.configure("TButton", font=("Segoe UI", 10), padding=(16, 9),
                     background=BTN, foreground=TXT, borderwidth=1, bordercolor=LINHA,
                     lightcolor=BTN, darkcolor=BTN, focuscolor=BTN)
        st.map("TButton", background=[("active", BTN2)], bordercolor=[("active", "#CDD5DE")])
        st.configure("Accent.TButton", font=("Segoe UI Semibold", 12), padding=(34, 13),
                     foreground="white", background=ACCENT, borderwidth=0,
                     lightcolor=ACCENT, darkcolor=ACCENT, focuscolor=ACCENT)
        st.map("Accent.TButton", background=[("active", ACCENT2), ("disabled", "#AEBFAE")])
        st.configure("Stop.TButton", font=("Segoe UI Semibold", 12), padding=(26, 13),
                     foreground="white", background="#C0392B", borderwidth=0,
                     lightcolor="#C0392B", darkcolor="#C0392B", focuscolor="#C0392B")
        st.map("Stop.TButton", background=[("active", "#A5342A"), ("disabled", "#D9AAA4")])
        st.configure("Barra.Horizontal.TProgressbar", background=ACCENT, lightcolor=ACCENT,
                     darkcolor=ACCENT, bordercolor=TROUGH, troughcolor=TROUGH, borderwidth=0,
                     thickness=10)

    # ---------- aba Executar ----------
    def _aba_executar(self, parent):
        f = ttk.Frame(parent, style="Card.TFrame", padding=(28, 24))
        f.columnconfigure(0, weight=1)

        ttk.Label(f, text="CONCESSIONÁRIA", style="Field.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 5))
        self._labels = {
            (CONCESSIONARIAS[n]["label"] + ("" if CONCESSIONARIAS[n]["pronta"] else "  (em breve)")): n
            for n in CONCESSIONARIAS
        }
        self.conc_cb = ttk.Combobox(f, values=list(self._labels), state="readonly", font=("Segoe UI", 10))
        self.conc_cb.grid(row=1, column=0, sticky="ew", ipady=3, pady=(0, 16))
        self.conc_cb.current(0)

        ttk.Label(f, text="MODO", style="Field.TLabel").grid(row=2, column=0, sticky="w", pady=(0, 5))
        self.modo_var = tk.StringVar(value="api")
        mf = ttk.Frame(f, style="Card.TFrame")
        mf.grid(row=3, column=0, sticky="w", pady=(0, 16))
        ttk.Radiobutton(mf, text="API (CRM)", variable=self.modo_var, value="api",
                        command=self._atualizar_modo).pack(side="left")
        ttk.Radiobutton(mf, text="Planilha (local)", variable=self.modo_var, value="plan",
                        command=self._atualizar_modo).pack(side="left", padx=(20, 0))

        ttk.Label(f, text="QUANTAS PROCESSAR   (0 = TODAS)", style="Field.TLabel").grid(
            row=4, column=0, sticky="w", pady=(0, 5))
        self.limite_var = tk.StringVar(value="10")
        ttk.Spinbox(f, from_=0, to=99999, textvariable=self.limite_var, width=10).grid(
            row=5, column=0, sticky="w", pady=(0, 12))

        self.area = ttk.Frame(f, style="Card.TFrame")
        self.area.grid(row=6, column=0, sticky="w", pady=(0, 4))
        self.sem_enviar = tk.BooleanVar(value=False)
        self._api_box = ttk.Checkbutton(
            self.area, text="Ensaio — só teste, NÃO envia pro CRM", variable=self.sem_enviar)
        self.incluir_usinas = tk.BooleanVar(value=True)
        self._api_usinas_box = ttk.Checkbutton(
            self.area, text="Incluir faturas das usinas (fila farms/readings)",
            variable=self.incluir_usinas)
        self._plan_box = ttk.Frame(self.area, style="Card.TFrame")
        ttk.Button(self._plan_box, text="📄  Abrir planilha (contas.xlsx)",
                   command=self._abrir_planilha).pack(side="left")
        ttk.Label(self._plan_box, text="   edite os dados e salve", style="Muted.TLabel").pack(side="left")

        # botões Rodar / Parar — CENTRALIZADOS
        acoes = ttk.Frame(f, style="Card.TFrame")
        acoes.grid(row=7, column=0, pady=(18, 4))
        self.btn_rodar = ttk.Button(acoes, text="▶   Rodar", style="Accent.TButton", command=self._rodar)
        self.btn_rodar.pack(side="left", padx=(0, 10))
        self.btn_parar = ttk.Button(acoes, text="■  Parar", style="Stop.TButton", command=self._parar)
        self.btn_parar.pack(side="left")
        self.btn_parar.config(state="disabled")

        # progresso
        prog = ttk.Frame(f, style="Card.TFrame")
        prog.grid(row=8, column=0, sticky="ew", pady=(14, 0))
        prog.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(value="Pronto.")
        ttk.Label(prog, textvariable=self.status_var, style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.cont_var = tk.StringVar(value="")
        ttk.Label(prog, textvariable=self.cont_var, style="Cont.TLabel").grid(row=0, column=1, sticky="e")
        self.barra = ttk.Progressbar(prog, style="Barra.Horizontal.TProgressbar",
                                     mode="determinate", maximum=100)
        self.barra.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(7, 0))

        ttk.Separator(f).grid(row=9, column=0, sticky="ew", pady=(18, 14))

        # resultados — CENTRALIZADOS
        res = ttk.Frame(f, style="Card.TFrame")
        res.grid(row=10, column=0)
        self.resumo_var = tk.StringVar(value="")
        ttk.Label(res, textvariable=self.resumo_var, style="Muted.TLabel").pack(pady=(0, 10))
        bf = ttk.Frame(res, style="Card.TFrame")
        bf.pack()
        ttk.Button(bf, text="📊  Abrir relatório", command=self._abrir_relatorio).pack(side="left", padx=6)
        ttk.Button(bf, text="📁  Abrir pasta", command=self._abrir_pasta).pack(side="left", padx=6)
        ttk.Button(bf, text="🧾  Ver log", command=self._abrir_log_arquivo).pack(side="left", padx=6)
        ttk.Button(bf, text="🔎  Consulta CRM", command=self._abrir_consulta_crm).pack(side="left", padx=6)
        ttk.Button(bf, text="📈  Histórico", command=self._abrir_historico).pack(side="left", padx=6)

        self._atualizar_modo()
        return f

    def _atualizar_modo(self):
        self._plan_box.pack_forget()
        self._api_box.pack_forget()
        self._api_usinas_box.pack_forget()
        if self.modo_var.get() == "api":
            self._api_box.pack(anchor="w")
            self._api_usinas_box.pack(anchor="w", pady=(4, 0))
        else:
            self._plan_box.pack(anchor="w")

    # ---------- aba Configuração ----------
    def _aba_config(self, parent):
        f = ttk.Frame(parent, style="Card.TFrame", padding=(28, 20))
        f.columnconfigure(0, weight=1)
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="CRM (modo API)", style="Secao.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Separator(f).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 12))
        ttk.Label(f, text="URL DA API", style="Field.TLabel").grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 5))
        self.url_var = tk.StringVar(value=self.local.get("api_base_url", config.API_BASE_URL))
        ttk.Entry(f, textvariable=self.url_var, font=("Segoe UI", 10)).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(0, 14))

        ttk.Label(f, text="TOKEN", style="Field.TLabel").grid(row=4, column=0, columnspan=2, sticky="w", pady=(0, 5))
        self.token_var = tk.StringVar(value=config.API_TOKEN)      # já descriptografado
        self.token_entry = ttk.Entry(f, textvariable=self.token_var, show="•", font=("Segoe UI", 10))
        self.token_entry.grid(row=5, column=0, columnspan=2, sticky="ew")
        self.mostrar = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="mostrar token", variable=self.mostrar,
                        command=self._toggle_token).grid(row=6, column=0, sticky="w", pady=(6, 14))

        ttk.Label(f, text="Login do modo planilha", style="Secao.TLabel").grid(
            row=7, column=0, columnspan=2, sticky="w")
        ttk.Separator(f).grid(row=8, column=0, columnspan=2, sticky="ew", pady=(2, 12))
        ttk.Label(f, text="CPF / CNPJ DA AGÊNCIA VIRTUAL", style="Field.TLabel").grid(
            row=9, column=0, sticky="w", pady=(0, 5))
        ttk.Label(f, text="SENHA", style="Field.TLabel").grid(row=9, column=1, sticky="w", pady=(0, 5), padx=(16, 0))
        self.plan_login_var = tk.StringVar(value=config.PLAN_LOGIN)
        self.plan_senha_var = tk.StringVar(value=config.PLAN_SENHA)
        ttk.Entry(f, textvariable=self.plan_login_var, font=("Segoe UI", 10)).grid(
            row=10, column=0, sticky="ew", pady=(0, 6))
        ttk.Entry(f, textvariable=self.plan_senha_var, show="•", font=("Segoe UI", 10)).grid(
            row=10, column=1, sticky="ew", pady=(0, 6), padx=(16, 0))
        ttk.Label(f, text="🔒 Token e senhas ficam criptografados (só abrem neste usuário/computador).",
                  style="Muted.TLabel").grid(row=11, column=0, columnspan=2, sticky="w", pady=(4, 16))

        bf = ttk.Frame(f, style="Card.TFrame")
        bf.grid(row=12, column=0, columnspan=2)
        ttk.Button(bf, text="✔  Salvar", style="Save.TButton", command=self._salvar_config).pack(side="left", padx=6)
        ttk.Button(bf, text="Testar conexão", command=self._testar_api).pack(side="left", padx=6)
        return f

    # ---------- aba Configurações (robô) ----------
    _CAPTCHA_OPCOES = {
        "Extensão Buster (Chrome do robô)":           ("cdp", True, "buster"),
        "Solver próprio (áudio, faster-whisper)":     ("launch", True, "dom"),
        "Manual (eu resolvo na tela)":                ("cdp", False, "buster"),
    }

    def _aba_ajustes(self, parent):
        f = ttk.Frame(parent, style="Card.TFrame", padding=(28, 20))
        for c in range(3):
            f.columnconfigure(c, weight=1)

        ttk.Label(f, text="Captcha", style="Secao.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        atual = (config.MODO_NAVEGADOR, bool(config.CAPTCHA_AUTO), config.CAPTCHA_METODO)
        rotulo = next((r for r, v in self._CAPTCHA_OPCOES.items() if v == atual),
                      next(iter(self._CAPTCHA_OPCOES)))
        self.captcha_cb = ttk.Combobox(f, values=list(self._CAPTCHA_OPCOES), state="readonly",
                                       font=("Segoe UI", 10))
        self.captcha_cb.set(rotulo)
        self.captcha_cb.grid(row=1, column=0, columnspan=3, sticky="ew", ipady=3, pady=(0, 8))
        bx = ttk.Frame(f, style="Card.TFrame")
        bx.grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, 14))
        ttk.Button(bx, text="🌐  Abrir Chrome do robô", command=self._abrir_chrome_robo).pack(side="left")
        ttk.Label(bx, text="   1ª vez: instale o Buster nessa janela", style="Muted.TLabel").pack(side="left")

        self.ajuste_vars = {}

        def secao(linha, titulo):
            ttk.Label(f, text=titulo, style="Secao.TLabel").grid(
                row=linha, column=0, columnspan=3, sticky="w", pady=(6, 2))
            ttk.Separator(f).grid(row=linha + 1, column=0, columnspan=3, sticky="ew", pady=(0, 12))

        def campo(linha, col, rot, chave):
            ttk.Label(f, text=rot, style="Field.TLabel").grid(
                row=linha, column=col, sticky="w", pady=(0, 5), padx=(0, 16))
            var = tk.StringVar(value=str(getattr(config, chave, 0)))
            ttk.Spinbox(f, from_=0, to=9999, textvariable=var, width=9).grid(
                row=linha + 1, column=col, sticky="w", pady=(0, 14))
            self.ajuste_vars[chave] = var

        secao(3, "Tempos e tentativas")
        for i, (rot, chave) in enumerate([
            ("PAUSA ENTRE LOGINS COPEL (s)",   "PAUSA_ENTRE_LOGINS_CAPTCHA_S"),
            ("PAUSA RGE / CELESC (s)",         "PAUSA_ENTRE_LOGINS_S"),
            ("TEMPO MÁX. DO BUSTER (s)",       "CAPTCHA_BUSTER_TIMEOUT_S"),
            ("TENTATIVAS DE LOGIN",            "MAX_TENTATIVAS_LOGIN"),
            ("PAUSA ENTRE TENTATIVAS (s)",     "PAUSA_RETRY_LOGIN_S"),
            ("TENTATIVAS POR FATURA",          "MAX_TENTATIVAS"),
            ("PAUSA SE O GOOGLE BLOQUEAR (min)", "PAUSA_CAPTCHA_BLOQUEADO_MIN"),
        ]):
            campo(5 + (i // 3) * 2, i % 3, rot, chave)

        secao(11, "Modo 24/7")
        campo(13, 0, "CONSULTAR O CRM A CADA (min)", "CONTINUO_INTERVALO_MIN")
        campo(13, 1, "FUNCIONA DAS (h)",             "CONTINUO_HORA_INICIO")
        campo(13, 2, "ATÉ AS (h) · 24 = dia todo",   "CONTINUO_HORA_FIM")
        ttk.Label(f, text="CONCESSIONÁRIAS A CADA CICLO", style="Field.TLabel").grid(
            row=15, column=0, columnspan=3, sticky="w", pady=(0, 5))
        cf = ttk.Frame(f, style="Card.TFrame")
        cf.grid(row=16, column=0, columnspan=3, sticky="w", pady=(0, 14))
        ativas = set(getattr(config, "CONTINUO_CONCESSIONARIAS", ["COPEL"]))
        self.conc_24h_vars = {}
        for nome, info in CONCESSIONARIAS.items():
            if not info.get("pronta"):
                continue
            var = tk.BooleanVar(value=nome in ativas)
            ttk.Checkbutton(cf, text=nome, variable=var).pack(side="left", padx=(0, 22))
            self.conc_24h_vars[nome] = var

        bs = ttk.Frame(f, style="Card.TFrame")
        bs.grid(row=20, column=0, columnspan=3, pady=(10, 0))
        ttk.Button(bs, text="✔  Salvar", style="Save.TButton",
                   command=self._salvar_ajustes).pack(side="left", padx=6)
        ttk.Button(bs, text="📡  Status 24/7", command=self._ver_status_24h).pack(side="left", padx=6)
        ttk.Button(bs, text="📘  Guia", command=self._abrir_guia).pack(side="left", padx=6)
        return f

    # ---------- aba E-mail ----------
    _QUANDO = {
        "A cada execução (com o relatório anexado)": "cada_execucao",
        "Só quando der erro":                        "so_com_erro",
        "Resumo diário (1 e-mail por dia)":          "resumo_diario",
        "Desligado":                                 "desligado",
    }

    def _aba_email(self, parent):
        import notificacao
        c = notificacao.cfg()
        f = ttk.Frame(parent, style="Card.TFrame", padding=(28, 20))
        for col in range(3):
            f.columnconfigure(col, weight=1)

        def rot(linha, col, texto, span=1):
            ttk.Label(f, text=texto, style="Field.TLabel").grid(
                row=linha, column=col, columnspan=span, sticky="w", pady=(0, 5), padx=(0, 12))

        ttk.Label(f, text="Quem recebe", style="Secao.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Separator(f).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(2, 12))
        rot(2, 0, "DESTINATÁRIOS  (separe por vírgula)", 3)
        self.em_dest = tk.StringVar(value=", ".join(c["destinatarios"]))
        ttk.Entry(f, textvariable=self.em_dest, font=("Segoe UI", 10)).grid(
            row=3, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        rot(4, 0, "QUANDO ENVIAR", 2)
        rot(4, 2, "HORA DO RESUMO DIÁRIO")
        self.em_quando = ttk.Combobox(f, values=list(self._QUANDO), state="readonly", font=("Segoe UI", 10))
        self.em_quando.set(next((k for k, v in self._QUANDO.items() if v == c["quando"]), "Desligado"))
        self.em_quando.grid(row=5, column=0, columnspan=2, sticky="ew", ipady=2, pady=(0, 10), padx=(0, 12))
        self.em_hora = tk.StringVar(value=str(c.get("hora_resumo", 18)))
        ttk.Spinbox(f, from_=0, to=23, textvariable=self.em_hora, width=9).grid(
            row=5, column=2, sticky="w", pady=(0, 10))
        al = ttk.Frame(f, style="Card.TFrame")
        al.grid(row=6, column=0, columnspan=3, sticky="w", pady=(0, 14))
        self.em_alertas = tk.BooleanVar(value=bool(c.get("alertas", True)))
        ttk.Checkbutton(al, text="Alertas (CRM fora, captcha falhando, ciclo travado, disco cheio, sucesso abaixo de",
                        variable=self.em_alertas).pack(side="left")
        self.em_limite = tk.StringVar(value=str(c.get("limite_taxa", 50)))
        ttk.Spinbox(al, from_=0, to=100, textvariable=self.em_limite, width=4).pack(side="left", padx=4)
        ttk.Label(al, text="%)", style="TLabel").pack(side="left")

        ttk.Label(f, text="Servidor de envio (SMTP)", style="Secao.TLabel").grid(row=7, column=0, columnspan=3, sticky="w")
        ttk.Separator(f).grid(row=8, column=0, columnspan=3, sticky="ew", pady=(2, 12))
        rot(9, 0, "PROVEDOR")
        rot(9, 1, "SERVIDOR")
        rot(9, 2, "PORTA / SEGURANÇA")
        self.em_prov = ttk.Combobox(f, values=list(notificacao.PROVEDORES), state="readonly", font=("Segoe UI", 10))
        self.em_prov.set(next((n for n, v in notificacao.PROVEDORES.items() if v[0] and v[0] == c.get("smtp_host")),
                              "Outro (preencher)"))
        self.em_prov.grid(row=10, column=0, sticky="ew", ipady=2, pady=(0, 10), padx=(0, 12))
        self.em_prov.bind("<<ComboboxSelected>>", self._email_provedor)
        self.em_host = tk.StringVar(value=c.get("smtp_host", ""))
        ttk.Entry(f, textvariable=self.em_host, font=("Segoe UI", 10)).grid(
            row=10, column=1, sticky="ew", pady=(0, 10), padx=(0, 12))
        ps = ttk.Frame(f, style="Card.TFrame")
        ps.grid(row=10, column=2, sticky="w", pady=(0, 10))
        self.em_porta = tk.StringVar(value=str(c.get("smtp_porta", 587)))
        ttk.Spinbox(ps, from_=1, to=65535, textvariable=self.em_porta, width=6).pack(side="left")
        self.em_seg = ttk.Combobox(ps, values=["starttls", "ssl", "nenhuma"], state="readonly", width=9)
        self.em_seg.set(c.get("seguranca", "starttls"))
        self.em_seg.pack(side="left", padx=(6, 0))
        rot(11, 0, "USUÁRIO (e-mail que envia)")
        rot(11, 1, "SENHA  (Gmail: senha de app)")
        rot(11, 2, "REMETENTE  (se diferente)")
        self.em_user = tk.StringVar(value=c.get("usuario", ""))
        self.em_senha = tk.StringVar(value=c.get("senha", ""))
        self.em_rem = tk.StringVar(value=c.get("remetente", ""))
        ttk.Entry(f, textvariable=self.em_user, font=("Segoe UI", 10)).grid(row=12, column=0, sticky="ew", padx=(0, 12))
        ttk.Entry(f, textvariable=self.em_senha, show="•", font=("Segoe UI", 10)).grid(
            row=12, column=1, sticky="ew", padx=(0, 12))
        ttk.Entry(f, textvariable=self.em_rem, font=("Segoe UI", 10)).grid(row=12, column=2, sticky="ew")

        bs = ttk.Frame(f, style="Card.TFrame")
        bs.grid(row=20, column=0, columnspan=3, pady=(18, 0))
        ttk.Button(bs, text="✔  Salvar", style="Save.TButton", command=self._salvar_email).pack(side="left", padx=6)
        ttk.Button(bs, text="✉  Enviar e-mail de teste", command=self._testar_email).pack(side="left", padx=6)
        return f

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
        self.config(cursor="watch")
        self.update()
        corpo = notificacao._layout("E-mail de teste", "Robô de Faturas",
                                    "<p>Se você recebeu este e-mail, o envio está funcionando. ✅</p>")
        ok = notificacao.enviar("[Robô de Faturas] Teste de e-mail", corpo, c=c)
        self.config(cursor="")
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
        if not cfg["CONTINUO_CONCESSIONARIAS"]:
            messagebox.showerror("24/7", "Marque pelo menos uma concessionária pro modo 24/7.")
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
        self.token_entry.config(show="" if self.mostrar.get() else "•")

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
        self.barra.config(value=0)
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
                            self.barra.config(value=100)
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
            self.barra.config(value=(atual / total * 100) if total else 0)
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
        self.btn_rodar.config(state="disabled" if rodando else "normal")
        self.btn_parar.config(state="normal" if rodando else "disabled")

    def _parar(self):
        """Aborta a execução: mata o processo e TODA a árvore de filhos (navegador, etc.)."""
        proc = self._proc
        if not proc or proc.poll() is not None:
            return
        self._parado = True
        self.btn_parar.config(state="disabled")
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
