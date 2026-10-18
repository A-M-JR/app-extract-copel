"""
Registro de resultados da Rotina 1: acumula o desfecho de cada UC e, no fim,
salva um relatório .xlsx e imprime um resumo no terminal.

Status possíveis:
    concluído            -> fatura do mês baixada e renomeada
    não encontrado       -> UC não localizada no portal
    fatura não emitida   -> UC ok, mas sem fatura no mês de referência
    erro                 -> falha inesperada (com print de tela)
"""
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

import config

CONCLUIDO           = "concluído"
NAO_ENCONTRADO      = "não encontrado"
FATURA_NAO_EMITIDA  = "fatura não emitida"
ERRO                = "erro"
ADIADO              = "adiado"               # não tentou: captcha bloqueado -> próximo ciclo

COLUNAS = [
    "nome_cliente", "uc", "uc_nova", "mes_referencia", "vencimento", "valor",
    "status", "arquivo", "mensagem", "screenshot", "inicio", "fim", "duracao_s",
]

_CORES = {
    CONCLUIDO:          "C6EFCE",  # verde
    NAO_ENCONTRADO:     "FFF2CC",  # amarelo
    FATURA_NAO_EMITIDA: "FFF2CC",  # amarelo
    ERRO:               "FFC7CE",  # vermelho
    ADIADO:             "DDEBF7",  # azul claro
}


class RegistroResultados:
    def __init__(self):
        self.itens: list[dict] = []
        # dados da execução pro relatório HTML (concessionária, fonte, envio CRM...)
        self.meta: dict = {"inicio": datetime.now()}

    def registrar(self, conta: dict, status: str, uc_nova: str = "", arquivo: str = "",
                  mensagem: str = "", screenshot: str = "", inicio: datetime | None = None,
                  vencimento: str = "", valor: str = ""):
        fim = datetime.now()
        duracao = round((fim - inicio).total_seconds(), 1) if inicio else ""
        self.itens.append({
            "nome_cliente":   conta.get("nome_cliente", ""),
            "uc":             conta.get("uc", ""),
            "uc_nova":        uc_nova,
            "mes_referencia": conta.get("mes_referencia", ""),
            "vencimento":     vencimento,
            "valor":          valor,
            "status":         status,
            "arquivo":        arquivo,
            "mensagem":       mensagem,
            "screenshot":     screenshot,
            "inicio":         inicio.strftime("%Y-%m-%d %H:%M:%S") if inicio else "",
            "fim":            fim.strftime("%Y-%m-%d %H:%M:%S"),
            "duracao_s":      duracao,
            "login":          conta.get("login", ""),
            "id_fatura":      conta.get("id_fatura", ""),
            "_conta":         conta,   # o retorno do CRM é anotado nela depois (_crm)
        })

    # -- saída --------------------------------------------------------------
    def salvar_excel(self, pasta: Path = config.PASTA_RESULTADOS) -> Path:
        carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
        conc = config.sanitizar(self.meta.get("concessionaria") or "")
        caminho = Path(pasta) / (f"resultado_{conc}_{carimbo}.xlsx" if conc else f"resultado_{carimbo}.xlsx")

        wb = Workbook()
        ws = wb.active
        ws.title = "resultado"
        ws.append(COLUNAS)

        azul = PatternFill("solid", fgColor="1F6FC4")
        for celula in ws[1]:
            celula.font = Font(bold=True, color="FFFFFF")
            celula.fill = azul
            celula.alignment = Alignment(horizontal="center")

        col_status = COLUNAS.index("status") + 1
        for item in self.itens:
            ws.append([item[c] for c in COLUNAS])
            cor = _CORES.get(item["status"])
            if cor:
                ws.cell(row=ws.max_row, column=col_status).fill = PatternFill("solid", fgColor=cor)

        larguras = [34, 14, 14, 14, 14, 12, 18, 40, 40, 40, 20, 20, 10]
        for i, larg in enumerate(larguras, start=1):
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = larg
        ws.freeze_panes = "A2"

        wb.save(caminho)
        return caminho

    def salvar_html(self, caminho_xlsx: Path) -> Path | None:
        """Relatório HTML completo (resumo, problemas, faturas, CRM, log) ao lado do .xlsx."""
        try:
            import captura_log
            import relatorio_execucao
            itens = []
            for i in self.itens:
                d = {k: v for k, v in i.items() if k != "_conta"}
                d["crm"] = (i.get("_conta") or {}).get("_crm", "")
                itens.append(d)
            return relatorio_execucao.salvar(itens, self.meta, captura_log.linhas(), caminho_xlsx)
        except Exception as e:
            print(f"   [relatorio] AVISO: não gerei o HTML ({type(e).__name__}: {e})")
            return None

    def imprimir_resumo(self):
        total = len(self.itens)
        contagem: dict[str, int] = {}
        for i in self.itens:
            contagem[i["status"]] = contagem.get(i["status"], 0) + 1

        print("\n" + "=" * 60)
        partes = "  |  ".join(f"{v} {k}" for k, v in contagem.items())
        print(f"  RESUMO ({total} UCs):  {partes}")
        print("=" * 60)
        for status in (CONCLUIDO, NAO_ENCONTRADO, FATURA_NAO_EMITIDA, ADIADO, ERRO):
            itens = [i for i in self.itens if i["status"] == status]
            if not itens:
                continue
            print(f"\n  [{status.upper()}]")
            for i in itens:
                extra = Path(i["arquivo"]).name if i["arquivo"] else (i["mensagem"] or "")
                print(f"     - {i['nome_cliente']} (UC {i['uc']}): {extra}")
        print()
