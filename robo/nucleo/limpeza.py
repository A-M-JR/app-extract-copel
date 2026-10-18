"""
Limpeza automática do que o robô gera e não precisa guardar pra sempre.

Roda sozinha no começo de cada execução (start.py), no máximo 1x a cada 6h.
Prazos em config.LIMPEZA_DIAS (0 = nunca apaga). Rodar na mão:
    python robo\\nucleo\\limpeza.py          (mostra o que apagou e quanto liberou)

NUNCA apaga: PDFs de fatura (a não ser que configure), config, planilha, extensões do
Chrome do robô (Buster) nem a sessão dele.
"""
import shutil
import time
from pathlib import Path

import config

_MARCA = config.PASTA_DADOS / ".ultima_limpeza"
_INTERVALO_H = 6

# caches do Chrome do robô que podem ser apagados (ele recria). O maior é o modelo de IA
# local do Chrome (OptGuideOnDeviceModel, ~4 GB), que o robô não usa.
_CACHES_CHROME = (   # (o modelo de IA é bloqueado no navegador_cdp; aqui só se escapar)
    "component_crx_cache",
    "GrShaderCache", "ShaderCache", "GraphiteDawnCache",
    "Default/Cache", "Default/Code Cache", "Default/GPUCache", "Default/DawnGraphiteCache",
    "Default/DawnWebGPUCache",
)


def _tamanho(p: Path) -> int:
    try:
        if p.is_file():
            return p.stat().st_size
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    except Exception:
        return 0


def _apagar(p: Path) -> int:
    t = _tamanho(p)
    try:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return t
    except Exception:
        return 0


def _velhos(pasta: Path, padroes, dias: int):
    """Arquivos/pastas em `pasta` (padrões glob) sem modificação há mais de `dias`."""
    if not dias or not pasta.exists():
        return []
    corte = time.time() - dias * 86400
    achados = []
    for pad in padroes:
        for p in pasta.glob(pad):
            try:
                if p.stat().st_mtime < corte:
                    achados.append(p)
            except Exception:
                pass
    return achados


def limpar(forcar: bool = False, verbose: bool = False) -> int:
    """Apaga o que passou do prazo. Devolve quantos bytes liberou."""
    if not forcar and _MARCA.exists() and time.time() - _MARCA.stat().st_mtime < _INTERVALO_H * 3600:
        return 0
    dias = getattr(config, "LIMPEZA_DIAS", {})
    extracao = Path(config.PASTA_EXTRACAO)
    alvos = []
    alvos += _velhos(Path(config.PASTA_SCREENSHOTS), ["*.png"], dias.get("prints_erro", 30))
    alvos += _velhos(Path(config.PASTA_DIAGNOSTICO), ["*"], dias.get("diagnostico", 30))
    alvos += _velhos(extracao, ["resultado_*.xlsx", "resultado_*.html"], dias.get("relatorios", 90))
    alvos += _velhos(config.PASTA_DADOS / "resultados", ["*.xlsx"], dias.get("relatorios", 90))
    alvos += _velhos(extracao / "logs", ["*.log"], dias.get("logs_24h", 15))
    alvos += _velhos(Path(config.PASTA_SESSOES), ["*"], dias.get("sessoes", 30))
    if dias.get("faturas_pdf", 0):
        alvos += _velhos(extracao / "faturas", ["**/*.pdf"], dias["faturas_pdf"])

    liberado = 0
    for p in alvos:
        b = _apagar(p)
        liberado += b
        if verbose and b:
            print(f"   apagado: {p}  ({b / 1e6:.1f} MB)")

    # caches do Chrome do robô — só com ele FECHADO (arquivos em uso não apagam)
    if dias.get("cache_chrome", True):
        try:
            import navegador_cdp
            aberto = navegador_cdp.chrome_no_ar()
        except Exception:
            aberto = True
        perfil = Path(config.PERFIL_CHROME_CDP)
        if not aberto and perfil.exists():
            try:                       # modelo de IA do Chrome (~4 GB): apaga e trava
                navegador_cdp._bloquear_modelo_ia(perfil)
            except Exception:
                pass
            for rel in _CACHES_CHROME:
                p = perfil / rel
                if p.exists():
                    b = _apagar(p)
                    liberado += b
                    if verbose and b:
                        print(f"   cache do Chrome: {rel}  ({b / 1e6:.1f} MB)")

    try:
        import historico
        historico.podar()
    except Exception:
        pass
    try:
        _MARCA.parent.mkdir(parents=True, exist_ok=True)
        _MARCA.touch()
    except Exception:
        pass
    if liberado:
        print(f"[limpeza] {liberado / 1e6:.0f} MB liberados (arquivos antigos e caches).")
    return liberado


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    total = limpar(forcar=True, verbose=True)
    print(f"Total liberado: {total / 1e6:.1f} MB")
