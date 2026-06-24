# Monitor de Voos SSA → Espanha

## Caminho
`C:\Users\mauri\Videos\data-engineering-workspace.code-workspace\Web Scraping Voos\`

## Arquivos
- `monitor_voos.py` — busca SerpApi por companhia + classe, salva SQLite, gera HTML, email
- `dashboard.py` — Streamlit (`streamlit run dashboard.py`)
- `historico.db` — SQLite, tabela `voos`
- `report_voos.html` — report estático da última run (com ABAS por companhia)
- `monitor_voos.log` — logs
- `.env` — credenciais

## Estrutura atual (CRÍTICO — não simplificar)
- **Abas por companhia** (LATAM, TAP, Iberia, Air Europa, Lufthansa, Air France, KLM, British, Outras)
- **Cada linha**: data + destino + preço Econômica + preço Executiva lado a lado
- **Links diretos** para o site da própria companhia já com a busca preenchida (deep links)
- **NÃO usar mais `checked_bags`** — não muda preço, só atrapalha (era bug antigo)
- Usa `travel_class=1` (Econômica) e `travel_class=3` (Executiva) do SerpApi
- Salva **melhor voo por companhia** (não só o global) — para preencher as abas

## Configuração
- Origem: SSA
- Destinos: GRX (Granada), ALC (Alicante), AGP (Málaga/Nerja)
- Período: 2026-10-15 a 2026-10-31 (17 datas)
- Classes: Econômica + Executiva
- MAX_PARADAS: 2
- Filtro chegada: 08h-21h (ideal 10h-18h)
- Score: `dur_min + penalidade_horario + (paradas × 120)`
- Agenda: toda segunda 08:00
- Total chamadas/run: 3 destinos × 17 datas × 2 classes = **102 chamadas**

## SQLite — schema `voos`
id, run_date, data_viagem, destino, **classe**, **companhia**, preco, dur_min,
partida, chegada, paradas, escalas (json), classif, score,
**url_companhia**, url_google, url_kayak

## Companhias mapeadas (keywords no nome da airline retornado pela SerpApi)
LATAM (latam/tam) · TAP (tap) · Iberia (iberia) · Air Europa (air europa) ·
Lufthansa (lufthansa) · Air France (air france) · KLM (klm) · British (british) · Outras (fallback)

## .env
```
SERPAPI_KEY=
EMAIL_REMETENTE=
EMAIL_SENHA=             # Gmail App Password (myaccount.google.com/apppasswords)
EMAIL_DESTINATARIO=
PRECO_ALERTA=15000
MAX_PARADAS=2
```

## Como rodar
```powershell
pip install requests schedule python-dotenv streamlit pandas plotly
python monitor_voos.py
# em outro terminal:
streamlit run dashboard.py
```

## Não fazer
- Não voltar para o esquema antigo de `checked_bags` (1 mala vs 2 malas) — foi removido
- Não unir abas em uma tabela única — usuário pediu **abas por companhia** explicitamente
- Não trocar SerpApi por outra API
- Não remover os deep links para o site das companhias

## Problemas conhecidos
1. Email Gmail nunca funcionou — precisa App Password válido no `.env`
2. Limite SerpApi 250/mês — 102 por run × 4 semanas = 408 (estoura). Decisão atual: aceitar
3. PC precisa estar ligado segunda 08:00 (sem deploy cloud ainda)

## Próximos passos sugeridos
1. Validar primeiro run com email funcionando
2. Deploy do dashboard no Streamlit Cloud
3. Notificação Telegram alternativa ao email
