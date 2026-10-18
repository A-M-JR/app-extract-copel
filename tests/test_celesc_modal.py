"""
CELESC: modal 'Pagar conta' com o 'Gerar 2ª via' NA FRENTE e ~30 'Gerar 2ª via' das linhas do
histórico ATRÁS. O robô tem que clicar no do modal e pegar o PDF venha ele como download ou
como aba nova. Portal simulado num servidor local — não acessa a CELESC.
"""
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "robo"))
import _caminhos  # noqa: E402,F401
import config  # noqa: E402

PDF_CERTO = b"%PDF-1.4 fatura certa do modal"
PDF_ERRADO = b"%PDF-1.4 fatura ERRADA de outra linha"


def _pagina(modo_modal: str) -> str:
    acao = ("location.href='/pdf/certo?dl=1'" if modo_modal == "download"
            else "window.open('/pdf/certo')")
    linhas = "".join(f"<div class='linha'>Mês {i} <button onclick=\"location.href='/pdf/errado?dl=1'\">"
                     f"Gerar 2ª via</button></div>" for i in range(30))
    return f"""<html><body>
<div class='cdk-overlay-pane' role='dialog' style='position:fixed;inset:40px;background:#fff;z-index:10'>
  <h3>Pagar conta</h3><p>Detalhamento da conta</p>
  <button onclick="{acao}"><span>receipt</span> Gerar 2ª via</button>
  <button>Copiar código de barras</button><button onclick="this.closest('[role=dialog]').remove()">Fechar</button>
</div>
<div style='position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:5'></div>
<main>{linhas}</main></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/pdf/"):
            corpo = PDF_CERTO if "certo" in self.path else PDF_ERRADO
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            if "dl=1" in self.path:
                self.send_header("Content-Disposition", "attachment; filename=fatura.pdf")
            self.end_headers()
            self.wfile.write(corpo)
            return
        modo = "aba" if "aba" in self.path else "download"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_pagina(modo).encode("utf-8"))


class ModalCelesc(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), H)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def _rodar(self, rota):
        import celesc_bot
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(config, "PASTA_FATURAS", Path(tmp)), \
                sync_playwright() as pw:
            b = pw.chromium.launch(channel="chrome", headless=True)
            ctx = b.new_context(accept_downloads=True)
            pg = ctx.new_page()
            pg.goto(self.base + rota)
            bot = celesc_bot.CelescBot.__new__(celesc_bot.CelescBot)
            bot.page, bot.context = pg, ctx
            botao = bot._botao_gerar_do_modal()
            self.assertIsNotNone(botao)
            arq = bot._clicar_e_pegar_pdf(botao, {"nome_cliente": "TESTE", "mes_referencia": "09/2026"},
                                          timeout_s=15)
            dados = Path(arq).read_bytes() if arq else b""
            b.close()
        return dados

    def test_modal_com_download(self):
        self.assertEqual(self._rodar("/historico-download"), PDF_CERTO)

    def test_modal_abre_aba_nova(self):
        self.assertEqual(self._rodar("/historico-aba"), PDF_CERTO)

    def test_falha_de_download_nao_vira_nao_emitida(self):
        import celesc_bot
        import main
        from resultado_log import ERRO
        bot = celesc_bot.CelescBot.__new__(celesc_bot.CelescBot)
        for nome, valor in (("_na_selecao_parceiro", False), ("_na_selecao_imovel", False),
                            ("_aguardar_dashboard", True), ("_ir_para_historico", True)):
            setattr(bot, nome, mock.MagicMock(return_value=valor))
        for nome in ("_fechar_avisos", "_garantir_imovel", "_dump"):
            setattr(bot, nome, mock.MagicMock())
        bot._capturar_uc_nova = mock.MagicMock(return_value="188590701103")
        bot._achar_2via = mock.MagicMock(return_value=(0, "pagar", "13/10/2026", "148,00"))
        bot._baixar_por_indice = mock.MagicMock(return_value="")
        r = bot.processar_uc({"uc": "8210420", "mes_num": 9, "mes_ano": 2026, "mes_referencia": "09/2026"})
        self.assertEqual(r["status"], ERRO)
        self.assertEqual(main._enum_status(r["status"], r["mensagem"]), "PDF_ERRO_LEITURA")


if __name__ == "__main__":
    unittest.main(verbosity=2)
