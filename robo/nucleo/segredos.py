"""
Guarda token e senhas CRIPTOGRAFADOS no config_local.json, usando a proteção de dados do
próprio Windows (DPAPI): só o MESMO usuário, na MESMA máquina, consegue abrir.

    proteger("minha-senha")  -> "dpapi:AQAAANCMnd8BFdERjHoAwE..."
    revelar("dpapi:...")     -> "minha-senha"      (texto sem "dpapi:" volta igual)

Consequência: ao copiar a pasta pra OUTRA máquina (ex.: o NUC), os segredos não abrem lá —
é só preencher de novo no painel (aba Conexão CRM / E-mail).
"""
import base64
import ctypes
from ctypes import wintypes

_PREFIXO = "dpapi:"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(dados: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(dados, len(dados))
    return _Blob(len(dados), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _ler(blob: _Blob) -> bytes:
    dados = ctypes.string_at(blob.pbData, blob.cbData)
    ctypes.windll.kernel32.LocalFree(blob.pbData)
    return dados


def proteger(texto: str) -> str:
    if not texto or texto.startswith(_PREFIXO):
        return texto or ""
    entrada, saida = _blob(texto.encode("utf-8")), _Blob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(entrada), "robo-faturas", None,
                                                  None, None, 0x01, ctypes.byref(saida)):
        raise OSError("CryptProtectData falhou")
    return _PREFIXO + base64.b64encode(_ler(saida)).decode("ascii")


def revelar(valor: str) -> str:
    """Devolve o texto puro. Vazio se não conseguir abrir (ex.: veio de outra máquina)."""
    if not valor or not str(valor).startswith(_PREFIXO):
        return valor or ""
    try:
        entrada, saida = _blob(base64.b64decode(valor[len(_PREFIXO):])), _Blob()
        if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(entrada), None, None, None,
                                                        None, 0x01, ctypes.byref(saida)):
            return ""
        return _ler(saida).decode("utf-8")
    except Exception:
        return ""


def protegido(valor: str) -> bool:
    return bool(valor) and str(valor).startswith(_PREFIXO)
