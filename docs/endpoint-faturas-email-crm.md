# Endpoint de ingestão de faturas por e-mail (CRM)

**Para:** time do CRM / plataforma
**De:** TI / Ademir (robô de faturas)
**Objetivo:** o robô lê as faturas que chegam por **e-mail**, extrai os dados + o PDF e **envia pro CRM**. O CRM casa com a fatura que ele já tem (pelas chaves abaixo) e grava a leitura — ou responde **não encontrado**.

> Isto é o modelo **push** (e-mail → CRM), diferente do fluxo atual de portal (pull por `id_fatura`). Os dois convivem: portais continuam como estão; só a origem "e-mail" usa este endpoint.

---

## 1. Por que push (e não casar pelo `id_fatura` da fila)

No pull atual, o robô teria que **adivinhar** a UC interna do CRM a partir do e-mail. Hoje já sabemos que, na Energisa, a UC interna embute a matrícula (EMS = `"10"+matrícula+dígito`, ex. `103644028`; EMT = `"6"+matrícula+dígito`, ex. `640955338`), mas isso é engenharia reversa e muda por concessionária.

No push, o robô manda as **chaves que consegue ler com segurança** e o **CRM** (que tem o mapeamento real) faz o casamento. Mais robusto e, de quebra, o robô fica sabendo quais e-mails **não** têm fatura correspondente.

---

## 2. Requisição

```
POST {API_BASE_URL}/api/v1/invoices/email-readings      (nome a definir pelo CRM)
Authorization: Bearer <token>
Content-Type: application/json
```

Corpo (lote de faturas):

```json
{
  "faturas": [
    {
      "chaves": {
        "concessionaria_alias": "EMS",
        "matricula": "364402",
        "uc_aneel": "27298605183",
        "ano_mes_referencia": "10/2026"
      },
      "leitura_fatura": {
        "status_leitura": "COMPLETE",
        "data_vencimento": "16/10/2026",
        "valor_total": "128,97",
        "nota_fiscal": "019196980",
        "leitura_anterior": "04/09/2026",
        "leitura_atual": "06/10/2026",
        "proxima_leitura": "05/11/2026",
        "kwh_total_consumo": "470",
        "kwh_injetado": "420",
        "saldo_credito_todos_periodos": "",
        "codigo_barras": ""
      },
      "pdf_base64": "JVBERi0xLjQ..."
    }
  ]
}
```

### Chaves (como o CRM casa)
O robô manda **todas** as que consegue extrair; o CRM casa pela(s) que preferir:

| Campo | De onde o robô tira | Observação |
|---|---|---|
| `concessionaria_alias` | remetente do e-mail | `EMS`, `EMT`, … |
| `matricula` | nome do anexo (`...-Fat-Matricula-0000364402-...`) | **chave forte** — é o que a UC interna do CRM embute |
| `uc_aneel` | corpo do e-mail ("Unidade Consumidora: …") | é a UC ANEEL (hoje chamada `uc_secondary`) |
| `ano_mes_referencia` | anexo/corpo | `MM/AAAA` |

> A **UC interna** do CRM (ex. `103644028`) o robô **não** envia — ele não a tem direto. Casem por **matrícula** (contida na UC interna) e/ou **uc_aneel**, sempre com **alias + mês**.

### `leitura_fatura`
Mesmos campos do retorno atual do portal. `codigo_barras` vai **vazio** (é QR/imagem, não sai do PDF). `pdf_base64` é o PDF da fatura.

---

## 3. Resposta esperada

```json
{
  "success": true,
  "data": {
    "resultados": [
      {
        "matricula": "364402",
        "uc_aneel": "27298605183",
        "return": "OK",                 // OK | NAO_ENCONTRADO | DUPLICADA | ERRO
        "id_fatura": 25269,             // o id que casou (quando OK)
        "message": "leitura gravada"
      }
    ]
  }
}
```

- **OK** → casou e gravou. (Se possível, devolver o `id_fatura` que casou.)
- **NAO_ENCONTRADO** → o CRM não tem fatura pra essas chaves. O robô **registra e segue** (não falha). Isso também serve de relatório: "chegou por e-mail mas não existe no CRM".
- **DUPLICADA** (opcional) → já tinha leitura pra essa fatura. O robô pula.
- **ERRO** → erro de validação/gravação. O robô guarda pra reenviar depois.

---

## 4. Perguntas pro time do CRM

1. **Nome/rota** do endpoint e se usa o **mesmo token/escopo** do fluxo atual.
2. Casar por **matrícula** (mais forte, p/ Energisa) e/ou **uc_aneel**? Confirmar que o CRM guarda esses campos por fatura.
3. Querem receber **só o que casa**, ou **tudo** (pra o próprio CRM registrar as faturas "não encontradas")?
4. Aceita **lote** (vários por POST) ou **um por requisição**?
5. Deduplicação: o robô deve evitar reenviar a mesma fatura, mas é bom o CRM também ser **idempotente** (mesma matrícula+mês não duplica).

---

## 5. O que o robô já faz (pronto)

- Lê as caixas por Microsoft Graph (somente leitura).
- Baixa o PDF anexado e extrai: vencimento, valor, nota fiscal, leituras, próxima leitura, consumo, injeção (Energisa MS/MT). `uc_aneel` vem do corpo.
- Só falta trocar o "casar por id_fatura" por "POST neste endpoint" assim que ele existir.
