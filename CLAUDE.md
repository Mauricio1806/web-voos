# Monitor de Voos SSA → Espanha

## Caminho
`C:\Users\mauri\Videos\data-engineering-workspace.code-workspace\Web Scraping Voos\`

## Arquivos
- `monitor_voos.py` — busca via fast-flights (Google Flights via Protobuf, sem API key/quota) por companhia + classe, salva SQLite, gera HTML, email
- `dashboard.py` — Streamlit (`streamlit run dashboard.py`)
- `historico.db` — SQLite, tabela `voos`
- `report_voos.html` — report estático da última run (com ABAS por companhia)
- `monitor_voos.log` — logs
- `.env` — credenciais

## Estrutura atual (CRÍTICO — não simplificar)
- **Abas por companhia** (LATAM, TAP, Iberia, Air Europa, Lufthansa, Air France, KLM, British, Turkish, Emirates, Qatar, Avianca, Copa, Swiss, ITA Airways, Outras)
- **Cada linha**: data + destino + preço Econômica + preço Executiva lado a lado
- **Links diretos** para o site da própria companhia já com a busca preenchida (deep links)
- **NÃO usar mais `checked_bags`** — não muda preço, só atrapalha (era bug antigo)
- Usa seat `"economy"` (Econômica) e `"business"` (Executiva) do fast-flights (internamente ainda mapeado via travel_class_code 1/3)
- Salva **melhor voo por companhia** (não só o global) — para preencher as abas

## Configuração
- Origem: SSA
- Destinos: GRX (Granada), ALC (Alicante), AGP (Málaga/Nerja)
- Período: 2026-10-15 a 2026-10-31 (17 datas)
- Classes: Econômica + Executiva
- MAX_PARADAS: 2
- DURACAO_MAX_HORAS: 24 (voos acima de 24h são descartados)
- Filtro chegada: 08h-21h (ideal 10h-18h)
- PENALIDADE_TERRESTRE por aeroporto (min de deslocamento até o destino final): GRX 0 · ALC 0 · AGP 75 (ônibus até Nerja)
- Score: `dur_min + penalidade_horario + (paradas × 120) + penalidade_terrestre`
- Agenda: toda segunda 08:00
- Total chamadas/run: 3 destinos × 17 datas × 2 classes = **102 chamadas**

## Margem de bagagem despachada (23kg)
fast-flights (Google Flights) retorna apenas a tarifa Light (sem bagagem). Para estimar o preço final com bagagem, adicionamos uma margem por companhia em MARGEM_BAGAGEM_ECO. Executiva normalmente já inclui bagagem, então margem = 0.

## SQLite — schema `voos`
id, run_date, data_viagem, destino, **classe**, **companhia**, preco, dur_min,
partida, chegada, paradas, escalas (json), classif, score,
**url_companhia**, url_google, url_kayak

## Companhias mapeadas (16, keywords no nome da airline retornado pelo fast-flights)
LATAM (latam/tam) · TAP (tap) · Iberia (iberia) · Air Europa (air europa) ·
Lufthansa (lufthansa) · Air France (air france) · KLM (klm) · British (british) ·
Turkish (turkish) · Emirates (emirates) · Qatar (qatar) · Avianca (avianca) ·
Copa (copa) · Swiss (swiss) · ITA Airways (ita/alitalia) · Outras (fallback)

## .env
```
EMAIL_REMETENTE=
EMAIL_SENHA=             # Gmail App Password (myaccount.google.com/apppasswords)
EMAIL_DESTINATARIO=
PRECO_ALERTA=15000
MAX_PARADAS=2
```

## Como rodar
```powershell
pip install fast-flights==2.1 requests schedule python-dotenv streamlit pandas plotly
python monitor_voos.py
# em outro terminal:
streamlit run dashboard.py
```

## Não fazer
- Não voltar para o esquema antigo de `checked_bags` (1 mala vs 2 malas) — foi removido
- Não unir abas em uma tabela única — usuário pediu **abas por companhia** explicitamente
- Não voltar para SerpApi — tinha quota de 250 buscas/mês (102/run estourava em 3 semanas); migrado para fast-flights (sem API key, sem quota)
- Não remover os deep links para o site das companhias

## Problemas conhecidos
1. Email Gmail nunca funcionou — precisa App Password válido no `.env`
2. fast-flights faz scraping do Google Flights (sem API oficial) — pode quebrar se o Google mudar o HTML/Protobuf; sem SLA de disponibilidade
3. fast-flights **precisa ficar travado em `==2.1`** — a partir da 2.2 (e na 3.x) a lib foi reescrita com uma API incompatível (`FlightQuery`/`Query` em vez de `FlightData`/`create_filter`/`get_flights_from_filter`); a 2.0 nem builda (erro de packaging no flit_core)
4. PC precisa estar ligado segunda 08:00 (sem deploy cloud ainda) — parcialmente mitigado pelo workflow do GitHub Actions

## Próximos passos sugeridos
1. Validar primeiro run com email funcionando
2. Deploy do dashboard no Streamlit Cloud
3. Notificação Telegram alternativa ao email
