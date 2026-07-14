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
- **Abas por companhia** (LATAM, TAP, Iberia, Air Europa, Lufthansa, Air France, KLM, British, Turkish, Emirates, Qatar, Avianca, Copa, Swiss, ITA Airways, Outras)
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
- DURACAO_MAX_HORAS: 24 (voos acima de 24h são descartados)
- Filtro chegada: 08h-21h (ideal 10h-18h)
- PENALIDADE_TERRESTRE por aeroporto (min de deslocamento até o destino final): GRX 0 · ALC 0 · AGP 75 (ônibus até Nerja)
- Score: `dur_min + penalidade_horario + (paradas × 120) + penalidade_terrestre`
- Agenda: dia 1 e dia 15 de cada mês, 08:00 (BRT) — ver "Problemas conhecidos" #2
- Total chamadas/run: 3 destinos × 17 datas × 2 classes = **102 chamadas** (≈204/mês com 2 runs, dentro da quota gratuita SerpApi de 250)

## Margem de bagagem despachada (23kg)
SerpApi retorna apenas a tarifa Light (sem bagagem). Para estimar o preço final com bagagem, adicionamos uma margem por companhia em MARGEM_BAGAGEM_ECO. Executiva normalmente já inclui bagagem, então margem = 0.

## SQLite — schema `voos`
id, run_date, data_viagem, destino, **classe**, **companhia**, preco, dur_min,
partida, chegada, paradas, escalas (json), classif, score,
**url_companhia**, url_google, url_kayak

## Companhias mapeadas (16, keywords no nome da airline retornado pela SerpApi)
LATAM (latam/tam) · TAP (tap) · Iberia (iberia) · Air Europa (air europa) ·
Lufthansa (lufthansa) · Air France (air france) · KLM (klm) · British (british) ·
Turkish (turkish) · Emirates (emirates) · Qatar (qatar) · Avianca (avianca) ·
Copa (copa) · Swiss (swiss) · ITA Airways (ita/alitalia) · Outras (fallback)

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
- Não trocar SerpApi por `fast-flights` (scraping direto do Google Flights) — **já tentado e revertido** (2026-07-14). Funciona bem numa máquina local isolada, mas quebra sob o volume real do projeto (102 chamadas/run): rotas menos comuns (GRX/ALC/AGP) demoram demais e retornam vazio via HTTP simples; mesmo com Chromium real (Playwright) fazendo polling, uma rajada de ~20 requisições em poucos minutos já é o suficiente para o Google começar a bloquear/limitar (taxa de sucesso caiu a 0%). Com delay de 30s+jitter e user-agent rotativo a taxa de sucesso subiu para ~60%, mas ainda não é confiável o bastante para susbtituir o SerpApi. Não tentar de novo sem repensar a abordagem (ex.: proxies residenciais, ou aceitar rodar bem mais devagar que um run de 102 chamadas permite)
- Não remover os deep links para o site das companhias

## Problemas conhecidos
1. Email Gmail nunca funcionou — precisa App Password válido no `.env`
2. Limite SerpApi 250/mês — 102 por run inviabiliza rodar toda semana (102×4=408, estoura). Decisão atual: rodar **dia 1 e dia 15 de cada mês** (~204/mês, dentro da quota gratuita) em vez de semanalmente
3. PC precisa estar ligado no dia do run se rodando localmente (mitigado pelo workflow do GitHub Actions, que roda na nuvem independente do PC)

## Próximos passos sugeridos
1. Validar primeiro run com email funcionando
2. Deploy do dashboard no Streamlit Cloud
3. Notificação Telegram alternativa ao email
