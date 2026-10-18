"""
Modo CDP: o robô controla o GOOGLE CHROME NORMAL (com as extensões instaladas, ex.: Buster)
em vez de abrir um Chrome "de automação" pelo Playwright.

Por quê: o Chrome 137+ ignora o --load-extension, então extensão só funciona num perfil
onde ela foi instalada pela Chrome Web Store. Aqui:
  1) abrimos o Chrome com --remote-debugging-port num perfil PRÓPRIO do robô
     (dados/chrome-robo — o Chrome 136+ bloqueia depuração no perfil padrão);
  2) o Playwright se conecta via connect_over_cdp e trabalha numa aba nova;
  3) o Chrome fica aberto entre os logins (não reabre a cada conta).

Primeira vez (instalar o Buster no perfil do robô):
    python navegador_cdp.py          (ou abrir_chrome_robo.bat)
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

import config

BUSTER_URL = "https://chromewebstore.google.com/detail/mpbjkejclgfgadiemmefgebjfooflfhl"


def _url_cdp() -> str:
    return f"http://127.0.0.1:{config.CDP_PORTA}"


def chrome_no_ar() -> bool:
    try:
        return requests.get(_url_cdp() + "/json/version", timeout=2).ok
    except Exception:
        return False


def _achar_chrome() -> str:
    if getattr(config, "CHROME_EXE", ""):
        return config.CHROME_EXE
    for base in (os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                 os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                 os.environ.get("LOCALAPPDATA", "")):
        p = Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
        if base and p.exists():
            return str(p)
    raise FileNotFoundError("Não achei o chrome.exe. Defina CHROME_EXE no config.py.")


_PASTAS_IA = ("OptGuideOnDeviceModel", "optimization_guide_model_store")


def _bloquear_modelo_ia(perfil: Path):
    """O Chrome baixa sozinho um modelo de IA local (Gemini Nano, ~4 GB) que o robô não usa,
    e a flag --disable-features não segura sempre. Trava: apaga a pasta e cria no lugar um
    ARQUIVO somente-leitura com o mesmo nome -> o Chrome não consegue recriar a pasta e não
    baixa. Roda a cada abertura (com o Chrome do robô fechado)."""
    import shutil
    import stat
    for nome in _PASTAS_IA:
        p = perfil / nome
        try:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
                print(f"[chrome] removido {nome} (modelo de IA do Chrome, não usado pelo robô)")
            if not p.exists():
                perfil.mkdir(parents=True, exist_ok=True)
                p.write_text("bloqueado pelo robô: não baixar o modelo de IA do Chrome\n", encoding="utf-8")
                p.chmod(stat.S_IREAD)
        except Exception as e:
            print(f"[chrome] aviso: não consegui bloquear {nome}: {e}")


def _preparar_perfil(perfil: Path):
    """Bloqueia o modelo de IA do Chrome e, na 1ª vez, desliga o gerenciador de senhas
    (popups 'Salvar senha?' / 'senha vazada' travam a automação). As Preferences só são
    escritas se o perfil ainda não existe (não pisa nas configs das extensões depois)."""
    _bloquear_modelo_ia(perfil)
    prefs = perfil / "Default" / "Preferences"
    if prefs.exists():
        return
    prefs.parent.mkdir(parents=True, exist_ok=True)
    prefs.write_text(json.dumps({
        "credentials_enable_service": False,
        "profile": {"password_manager_enabled": False,
                    "password_manager_leak_detection": False},
        "download": {"prompt_for_download": False},
        "plugins": {"always_open_pdf_externally": True},
    }), encoding="utf-8")


def garantir_chrome(url_inicial: str = "") -> None:
    """Sobe o Chrome do robô (com porta de depuração) se ainda não estiver no ar."""
    if chrome_no_ar():
        return
    perfil = Path(config.PERFIL_CHROME_CDP)
    _preparar_perfil(perfil)
    args = [_achar_chrome(),
            f"--remote-debugging-port={config.CDP_PORTA}",
            f"--user-data-dir={perfil}",
            "--no-first-run", "--no-default-browser-check", "--start-maximized",
            # sem gerenciador de senhas e sem o modelo de IA local do Chrome (~4 GB, inútil aqui)
            "--disable-features=PasswordLeakDetection,PasswordManagerOnboarding,"
            "OptimizationGuideModelDownloading,OptimizationHintsFetching,"
            "OptimizationTargetPrediction,OptimizationHints,OptimizationGuideOnDeviceModel,"
            "OnDeviceModelPerformanceParams,AIPromptAPI,AISummarizationAPI,AIWriterAPI,AIRewriterAPI",
            "--disable-save-password-bubble"]
    if url_inicial:
        args.append(url_inicial)
    print(f"[chrome] abrindo o Chrome do robô (porta {config.CDP_PORTA})...")
    subprocess.Popen(args, close_fds=True,
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    for _ in range(30):
        if chrome_no_ar():
            print("[chrome] pronto.")
            return
        time.sleep(1)
    raise RuntimeError(
        f"O Chrome não abriu a porta {config.CDP_PORTA}. Feche TODAS as janelas do Chrome "
        f"que usam o perfil {perfil} e tente de novo.")


def conectar(pw, dominio_sessao: str = ""):
    """Conecta no Chrome do robô e abre uma ABA NOVA. Devolve (browser, context, page).
    `dominio_sessao` (ex.: 'copel.com'): apaga os cookies SÓ desse portal antes de começar,
    pra cada login entrar limpo (o perfil é compartilhado entre as contas). Os cookies do
    Google ficam — ajudam o reCAPTCHA a confiar no navegador."""
    garantir_chrome()
    browser = pw.chromium.connect_over_cdp(_url_cdp())
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    if dominio_sessao:
        try:
            context.clear_cookies(domain=re.compile(re.escape(dominio_sessao)))
        except Exception as e:
            print(f"   [chrome] não consegui limpar cookies de {dominio_sessao}: {e}")
    page = context.new_page()
    try:
        page.bring_to_front()
    except Exception:
        pass
    return browser, context, page


def limpar_storage(page) -> None:
    """Apaga localStorage/sessionStorage da origem atual (complementa a limpeza de cookies)."""
    try:
        page.evaluate("() => { try { localStorage.clear(); sessionStorage.clear(); } catch (e) {} }")
    except Exception:
        pass


def fechar(page) -> None:
    """Fecha só a ABA do robô. O Chrome continua aberto pro próximo login."""
    try:
        if page and not page.is_closed():
            page.close()
    except Exception:
        pass


if __name__ == "__main__":
    # Abre o Chrome do robô na página do Buster, pra instalar a extensão 1x.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if chrome_no_ar():
        print("[chrome] o Chrome do robô já está aberto — instale o Buster nele, se faltar:")
        print("        " + BUSTER_URL)
    else:
        garantir_chrome(BUSTER_URL)
        print("Instale o 'Buster: Captcha Solver for Humans' nessa janela (Usar no Chrome).")
        print("Depois pode deixar o Chrome aberto — o robô reaproveita.")
