# Robô de Faturas (COPEL · RGE · CELESC)

Baixa as faturas de energia nos portais das concessionárias, lê os dados do PDF e devolve
pro CRM. Roda pelo painel ou sozinho no modo 24/7, e manda o relatório por e-mail.

**Guia completo (instalação, uso, e-mail, 24/7, manutenção): [GUIA-NUC.html](GUIA-NUC.html)**

## Começo rápido

1. `instalacao\INSTALAR.bat`: dependências, atalho, Chrome do robô (Buster) e 24/7, passo a passo.
2. Abra o painel (atalho ou `painel.bat`) e preencha as abas **Conexão CRM** e **E-mail**.
3. **▶ Rodar**, ou deixe o 24/7 trabalhar.

## Pastas

| Pasta | Conteúdo |
|---|---|
| `robo/` | código: `start.py` (entrada), `main.py` (orquestra), `painel.py`, `rodar_24h.py` |
| `robo/nucleo` | config, navegador, base dos bots, e-mail, histórico, limpeza, segredos |
| `robo/bots` | um robô por concessionária + leitor do PDF (`fatura_pdf.py`) |
| `robo/captcha` · `robo/crm` · `robo/relatorios` | Buster · API do CRM + fila de reenvio · relatórios HTML |
| `instalacao/` | instaladores |
| `scripts/` | testes (`rodar_testes.bat`) e diagnóstico |
| `tests/` | testes automáticos |
| `dados/` | gerado pelo robô (fora do git, limpa sozinho) |

## Manutenção

- Testes: `scripts\rodar_testes.bat` (ou `.venv\Scripts\python.exe -m unittest discover -s tests -v`).
- Segredos (token, senhas) ficam criptografados no `config_local.json` (DPAPI do Windows). Nunca no código.
