# Monitor de Voos SSA → Espanha

Monitora preços de voos de Salvador (SSA) para Granada (GRX), Alicante (ALC) e Málaga (AGP)
via [SerpApi](https://serpapi.com/), toda segunda-feira, e publica um report estático.

**Report ao vivo:** https://mauricio1806.github.io/web-voos/

## Como funciona

- `monitor_voos.py` busca voos por companhia + classe via SerpApi, salva em `historico.db` (SQLite)
  e gera `report_voos.html` com abas por companhia.
- O workflow `.github/workflows/monitor.yml` roda toda segunda às 08:00 (BRT), comita o report
  e o banco atualizados, e publica o resultado no GitHub Pages.
- `dashboard.py` é um painel Streamlit opcional para explorar o histórico localmente.

## Rodar localmente

```powershell
pip install -r requirements.txt
python monitor_voos.py
# em outro terminal:
streamlit run dashboard.py
```

Crie um `.env` na raiz com:

```
SERPAPI_KEY=
EMAIL_REMETENTE=
EMAIL_SENHA=
EMAIL_DESTINATARIO=
PRECO_ALERTA=15000
```

## Configuração do GitHub Actions

Segredos necessários em **Settings → Secrets and variables → Actions**:

- `SERPAPI_KEY`
- `EMAIL_REMETENTE`
- `EMAIL_SENHA`
- `EMAIL_DESTINATARIO`
- `PRECO_ALERTA`

Veja `CLAUDE.md` para detalhes completos da estrutura do projeto.
