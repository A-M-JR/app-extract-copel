"""
Testes automáticos do robô (sem abrir navegador, sem falar com o CRM de verdade).

Rodar (na raiz do projeto):
    .venv\\Scripts\\python.exe -m unittest discover -s tests -v
ou pelo  rodar_testes.bat .

O que cobre:
  - leitor de PDF: as faturas de tests/faturas/ têm que continuar dando os MESMOS valores
    de tests/referencia_pdfs.json (pega mudança de layout da concessionária ou regressão);
  - formato dos campos que vão pro CRM (kWh número puro, datas, valor);
  - fila de reenvio, separação de faturas inválidas/duplicadas, criptografia, relatórios.

Fatura nova pra entrar no teste: copie o PDF pra tests/faturas/ e rode
    .venv\\Scripts\\python.exe tests\\test_robo.py --gerar-referencia
(confira os valores no JSON gerado antes de confiar nele).
"""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "robo"))
import _caminhos  # noqa: E402,F401
import config  # noqa: E402

FATURAS = AQUI / "faturas"
REFERENCIA = AQUI / "referencia_pdfs.json"
DATA = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def _ler_pdfs() -> dict:
    import fatura_pdf
    return {p.name: fatura_pdf.extrair_dados(str(p)) for p in sorted(FATURAS.glob("*.pdf"))}


class LeitorPdf(unittest.TestCase):
    def test_bate_com_referencia(self):
        if not REFERENCIA.exists() or not any(FATURAS.glob("*.pdf")):
            self.skipTest("sem PDFs/referência em tests/ (rode --gerar-referencia)")
        ref = json.loads(REFERENCIA.read_text(encoding="utf-8"))
        atual = _ler_pdfs()
        for nome, esperado in ref.items():
            if nome not in atual:
                continue
            with self.subTest(pdf=nome):
                self.assertEqual(esperado, atual[nome])

    def test_formatos_pro_crm(self):
        for nome, d in _ler_pdfs().items():
            with self.subTest(pdf=nome):
                for campo in ("kwh_injetado", "kwh_total_consumo"):
                    v = d.get(campo, "")
                    self.assertRegex(v, r"^(\d+(\.\d+)?)?$", f"{campo}={v!r} deveria ser número puro")
                for campo in ("leitura_anterior", "leitura_atual", "proxima_leitura", "data_vencimento"):
                    v = d.get(campo, "")
                    if v:
                        self.assertRegex(v, DATA, f"{campo}={v!r}")
                if d.get("valor_total"):
                    self.assertRegex(d["valor_total"], r"^\d{1,3}(\.\d{3})*,\d{2}$")

    def test_fmt_kwh(self):
        import fatura_pdf
        self.assertEqual([fatura_pdf._fmt_kwh(x) for x in (1416.0, 82.5, 0.0, 2551.59)],
                         ["1416", "82.5", "0", "2551.59"])

    def test_rge_milhar(self):
        import fatura_pdf
        d = fatura_pdf._extrair_rge("Energia Ativa-kWh único 31385 32801 1,00 1.416 x "
                                    "Energ Atv Inj. oUC mPT - TUSD ABR/26 kWh 1.122,5000")
        self.assertEqual((d["kwh_total_consumo"], d["kwh_injetado"]), ("1416", "1122.5"))


class Crm(unittest.TestCase):
    def test_item_complete_sem_campos_vazios(self):
        import api_faturas
        item = api_faturas.montar_item_resultado(1, "COMPLETE", {"valor_total": "10,00", "codigo_barras": ""},
                                                 uc_aneel="123")
        self.assertEqual(item["leitura_fatura"]["valor_total"], "10,00")
        self.assertNotIn("codigo_barras", item["leitura_fatura"])
        self.assertEqual(item["uc_secondary"], "123")

    def test_fila_reenvio(self):
        import fila_crm
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(fila_crm, "PASTA", Path(tmp)):
            fila_crm.guardar(77, "PDF_NAO_ENCONTRADO", {}, "", None, "timeout")
            self.assertEqual(len(fila_crm.pendentes()), 1)
            with mock.patch("api_faturas.enviar_resultados", side_effect=OSError("fora")):
                self.assertEqual(fila_crm.reenviar(), (0, 1))
            self.assertEqual(len(fila_crm.pendentes()), 1)          # continua na fila
            with mock.patch("api_faturas.enviar_resultados", return_value={}):
                self.assertEqual(fila_crm.reenviar(), (1, 0))
            self.assertEqual(fila_crm.pendentes(), [])

    def test_separar_invalidas_e_duplicadas(self):
        import main
        base = {"login": "x", "senha": "y", "uc": "1", "mes_num": 9, "mes_referencia": "09/2026"}
        fats = [dict(base, id_fatura=1), dict(base, id_fatura=2), dict(base, id_fatura=3, senha=""),
                dict(base, id_fatura=4, uc=""), dict(base, id_fatura=5, uc="2", mes_num=0)]
        ok, inval, dup = main._separar_problemas(fats)
        self.assertEqual([f["id_fatura"] for f in ok], [1])
        self.assertEqual(sorted(f["id_fatura"] for f, _ in inval), [3, 4, 5])
        self.assertEqual([(d["id_fatura"], o["id_fatura"]) for d, o in dup], [(2, 1)])


class Infra(unittest.TestCase):
    def test_segredos(self):
        import segredos
        c = segredos.proteger("senha-123")
        self.assertTrue(c.startswith("dpapi:"))
        self.assertEqual(segredos.revelar(c), "senha-123")
        self.assertEqual(segredos.revelar("dpapi:lixo"), "")

    def test_relatorio_execucao_renderiza(self):
        import relatorio_execucao
        from resultado_log import CONCLUIDO, ERRO
        itens = [{"nome_cliente": "A <b>", "uc": "1", "mes_referencia": "09/2026", "status": CONCLUIDO,
                  "duracao_s": 30, "login": "l"},
                 {"nome_cliente": "B", "uc": "2", "mes_referencia": "09/2026", "status": ERRO,
                  "mensagem": "timeout", "duracao_s": 50, "login": "l"}]
        html = relatorio_execucao.render(itens, {"concessionaria": "COPEL"}, [], None)
        self.assertIn("A &lt;b&gt;", html)
        self.assertIn("50%", html)

    def test_config_sem_token_no_codigo(self):
        codigo = (Path(config.ROBO) / "nucleo" / "config.py").read_text(encoding="utf-8")
        self.assertNotIn("pcrm_live_", codigo)


if __name__ == "__main__":
    if "--gerar-referencia" in sys.argv:
        dados = _ler_pdfs()
        REFERENCIA.write_text(json.dumps(dados, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"referência gerada com {len(dados)} PDF(s): {REFERENCIA}")
    else:
        unittest.main(verbosity=2)
