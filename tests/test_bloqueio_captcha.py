"""
Bloqueio do captcha pelo Google ("Try again later"): o robô tem que PARAR a concessionária
(sem re-tentar o login), adiar o resto sem mandar nada pro CRM e respeitar a pausa depois.
Robô e CRM simulados — não abre navegador.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "robo"))
import _caminhos  # noqa: E402,F401
import config  # noqa: E402


def _conta(i, login):
    return {"id_fatura": i, "login": login, "senha": "s", "uc": str(100 + i), "mes_num": 9,
            "mes_ano": 2026, "mes_referencia": "09/2026", "nome_cliente": f"CLIENTE {i}",
            "mes_variantes": ["09/2026"]}


class BloqueioCaptcha(unittest.TestCase):
    def test_buster_levanta_bloqueio(self):
        import captcha_buster
        with mock.patch.object(captcha_buster, "_frame", return_value=mock.MagicMock()), \
                mock.patch.object(captcha_buster, "_token_ok", return_value=False), \
                mock.patch.object(captcha_buster, "_desafio_visivel", return_value=True), \
                mock.patch.object(captcha_buster, "_bloqueado", return_value=True):
            with self.assertRaises(captcha_buster.CaptchaBloqueado):
                captcha_buster.resolver_captcha(mock.MagicMock(), timeout_s=5)

    def test_executar_pausa_e_adia(self):
        import main
        import pausa_captcha
        from captcha_buster import CaptchaBloqueado
        from resultado_log import CONCLUIDO, ADIADO

        logins_tentados = []

        class BotFalso:
            def __init__(self, login, senha, headless=False):
                self.login = login

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def garantir_login(self):
                logins_tentados.append(self.login)
                if self.login == "login_B":
                    raise CaptchaBloqueado("Try again later")

            def processar_faturas_uc(self, contas):
                return [{"status": CONCLUIDO, "mensagem": "ok"} for _ in contas]

            def screenshot_erro(self, *a):
                return ""

        faturas = [_conta(1, "login_A"), _conta(2, "login_B"), _conta(3, "login_C"), _conta(4, "login_C")]
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            with mock.patch.object(config, "PASTA_DADOS", tmp), \
                    mock.patch.object(config, "PASTA_EXTRACAO", tmp), \
                    mock.patch.object(config, "PASTA_RESULTADOS", tmp), \
                    mock.patch.object(config, "PAUSA_ENTRE_LOGINS_CAPTCHA_S", 0), \
                    mock.patch.object(pausa_captcha, "ARQ", tmp / "pausa.json"), \
                    mock.patch("concessionarias.get_bot", return_value=BotFalso), \
                    mock.patch("api_faturas.buscar_faturas", return_value=faturas), \
                    mock.patch("notificacao.alerta") as alerta, \
                    mock.patch.object(main, "_pos_execucao"), \
                    mock.patch.object(main, "_enviar_callback") as callback, \
                    mock.patch("resultado_log.RegistroResultados.salvar_excel", return_value=tmp / "r.xlsx"), \
                    mock.patch("resultado_log.RegistroResultados.salvar_html", return_value=None), \
                    mock.patch.dict(os.environ, {"ROBO_IGNORAR_PAUSA": ""}):
                capturado = {}
                orig = main.RegistroResultados

                class Reg(orig):
                    def __init__(self):
                        super().__init__()
                        capturado["r"] = self

                with mock.patch.object(main, "RegistroResultados", Reg):
                    main.executar(headless=False, enviar=False, concessionaria="COPEL")
                    st = {i["id_fatura"]: i["status"] for i in capturado["r"].itens}

                    # login_B bloqueou: tentou UMA vez só e não chegou no login_C
                    self.assertEqual(logins_tentados, ["login_A", "login_B"])
                    self.assertEqual(st, {1: CONCLUIDO, 2: ADIADO, 3: ADIADO, 4: ADIADO})
                    self.assertIsNotNone(pausa_captcha.ate("COPEL"))
                    alerta.assert_called_once()
                    callback.assert_not_called()          # enviar=False e adiadas nunca mandam

                    # próxima execução respeita a pausa (nem consulta o CRM)
                    logins_tentados.clear()
                    capturado.clear()
                    main.executar(headless=False, enviar=False, concessionaria="COPEL")
                    self.assertEqual(logins_tentados, [])
                    self.assertNotIn("r", capturado)

                    # "rodar mesmo assim" (painel) ignora a pausa
                    with mock.patch.dict(os.environ, {"ROBO_IGNORAR_PAUSA": "1"}):
                        main.executar(headless=False, enviar=False, concessionaria="COPEL")
                    self.assertIn("login_A", logins_tentados)

    def test_rge_nao_pausa(self):
        import main
        import pausa_captcha
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(pausa_captcha, "ARQ", Path(tmp) / "p.json"):
            pausa_captcha.ativar("RGE", 30)
            self.assertFalse(main._em_pausa("RGE"))      # RGE não tem captcha -> nunca pausa


if __name__ == "__main__":
    unittest.main(verbosity=2)
