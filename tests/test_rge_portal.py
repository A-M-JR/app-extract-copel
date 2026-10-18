"""
RGE/CPFL: tela de erro do portal ("Ocorreu um erro ao processar a sua solicitação") ao abrir
a 2ª via. Tem que: sair rápido (sem F5 em loop), recuperar re-selecionando a instalação /
relogando e, se não der, virar ERRO -> PORTAL_OFFLINE (NUNCA "fatura não emitida").
"""
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "robo"))
import _caminhos  # noqa: E402,F401
import config  # noqa: E402

CONTA = {"uc": "3080596929", "uc_aneel_api": "76.084.001-10", "mes_referencia": "10/2026",
         "mes_variantes": ["10/2026"], "nome_cliente": "X"}


def _bot():
    import rge_bot
    bot = rge_bot.RgeBot.__new__(rge_bot.RgeBot)
    bot.page = mock.MagicMock()
    bot.context = mock.MagicMock()
    for nome in ("_ir_para_selecao_uc", "_dump", "garantir_login", "_limpar_sessao_cpfl"):
        setattr(bot, nome, mock.MagicMock())
    bot._selecionar_instalacao = mock.MagicMock(return_value=True)
    bot._abrir_debito_segunda_via = mock.MagicMock(return_value=True)
    bot._baixar_fatura_mes = mock.MagicMock(return_value={"vencimento": "20/10/2026", "valor": "10,00",
                                                          "arquivo": "x.pdf"})
    return bot


class PortalCpfl(unittest.TestCase):
    def test_recupera_na_segunda_tentativa(self):
        from resultado_log import CONCLUIDO
        bot = _bot()
        bot._aguardar_historico = mock.MagicMock(side_effect=[False, True])
        with mock.patch("time.sleep"):
            r = bot.processar_uc(CONTA)
        self.assertEqual(r["status"], CONCLUIDO)
        self.assertEqual(bot._selecionar_instalacao.call_count, 2)    # re-selecionou 1x
        bot.garantir_login.assert_not_called()

    def test_reloga_na_terceira_e_vira_erro_se_nao_abrir(self):
        import main
        from resultado_log import ERRO
        bot = _bot()
        bot._aguardar_historico = mock.MagicMock(return_value=False)
        with mock.patch("time.sleep"):
            r = bot.processar_uc(CONTA)
        self.assertEqual(r["status"], ERRO)                  # NÃO "fatura não emitida"
        self.assertTrue(r["mensagem"].startswith("portal"))
        bot.garantir_login.assert_called_once()              # 3ª tentativa reloga
        bot._baixar_fatura_mes.assert_not_called()
        self.assertEqual(main._enum_status(r["status"], r["mensagem"]), "PORTAL_OFFLINE")

    def test_aguardar_historico_sai_rapido_na_tela_de_erro(self):
        import rge_bot
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch(channel="chrome", headless=True)
            pg = b.new_page()
            pg.set_content("<div>Ocorreu um erro ao processar a sua solicitação. Por favor, tente novamente!</div>")
            bot = rge_bot.RgeBot.__new__(rge_bot.RgeBot)
            bot.page, bot.context = pg, pg.context
            t0 = time.time()
            self.assertFalse(bot._aguardar_historico())
            self.assertLess(time.time() - t0, 10)            # antes: ~100s de F5 em loop
            b.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
