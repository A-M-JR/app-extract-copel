"""
Guarda em memória tudo que o robô imprime nesta execução (com horário), pra o relatório
HTML mostrar o log junto dos resultados. A saída continua indo pro console/painel normal.

    import captura_log; captura_log.ligar()      # no começo (start.py)
    captura_log.linhas()                         # [(datetime, texto), ...]
"""
import sys
from datetime import datetime

_LINHAS: list[tuple[datetime, str]] = []
_LIMITE = 20_000          # não deixa um lote enorme estourar a memória


class _Tee:
    def __init__(self, original):
        self._orig = original
        self._buf = ""

    def write(self, s):
        try:
            self._buf += s
            while "\n" in self._buf:
                linha, self._buf = self._buf.split("\n", 1)
                if len(_LINHAS) < _LIMITE:
                    _LINHAS.append((datetime.now(), linha.rstrip("\r")))
        except Exception:
            pass
        return self._orig.write(s)

    def flush(self):
        return self._orig.flush()

    def __getattr__(self, nome):          # reconfigure, encoding, isatty...
        return getattr(self._orig, nome)


def ligar():
    if not isinstance(sys.stdout, _Tee):
        sys.stdout = _Tee(sys.stdout)


def linhas() -> list[tuple[datetime, str]]:
    return list(_LINHAS)
