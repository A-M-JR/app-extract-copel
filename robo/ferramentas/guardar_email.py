r"""
Guarda as credenciais da fonte por E-MAIL (Microsoft Graph) no config_local.json,
com o SEGREDO criptografado por DPAPI (segredos.proteger) — igual ao token do CRM.

Uso (o segredo entra por variável de ambiente, nunca como argumento visível):
    # PowerShell
    $env:GRAPH_SECRET = "<cole-o-segredo-aqui>"
    .\.venv\Scripts\python.exe robo\ferramentas\guardar_email.py

Opcionais (se não vierem, usa os padrões já no config.py):
    $env:GRAPH_TENANT = "..."      # Directory (tenant) ID
    $env:GRAPH_CLIENT = "..."      # Application (client) ID

Depois disso o robô lê tudo do config_local.json; o segredo não precisa mais
ficar em variável de ambiente. Este arquivo NÃO imprime o segredo.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _caminhos  # noqa: E402,F401
from segredos import proteger  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
ARQ = RAIZ / "config_local.json"


def main() -> int:
    segredo = (os.environ.get("GRAPH_SECRET") or "").strip()
    if not segredo:
        print("[erro] defina a variável de ambiente GRAPH_SECRET com o segredo do app.\n"
              '       PowerShell:  $env:GRAPH_SECRET = "<segredo>"')
        return 1

    dados = {}
    if ARQ.exists():
        try:
            dados = json.loads(ARQ.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[erro] não consegui ler o config_local.json existente: {e}")
            return 1

    dados["email_secret"] = proteger(segredo)              # criptografado (DPAPI)
    tenant = (os.environ.get("GRAPH_TENANT") or "").strip()
    client = (os.environ.get("GRAPH_CLIENT") or "").strip()
    if tenant:
        dados["email_tenant"] = tenant
    if client:
        dados["email_client"] = client

    ARQ.write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[ok] credenciais de e-mail gravadas em {ARQ}")
    print(f"     email_secret: criptografado (DPAPI){'' if not tenant else '  | tenant atualizado'}"
          f"{'' if not client else '  | client atualizado'}")
    print("     Pronto. O segredo não precisa mais ficar na variável de ambiente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
