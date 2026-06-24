"""
Monitor de Voos: Salvador (SSA) → Granada / Alicante / Málaga (Nerja)
Roda semanalmente, busca por companhia + classe (econômica + executiva),
gera report HTML com abas por companhia, links diretos, envia email.
"""

import os, json, time, smtplib, sqlite3, logging, random, requests, schedule
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

# ─── Configurações ────────────────────────────────────────────────────────────
ORIGEM = "SSA"

DESTINOS = {
    "GRX": "Granada",
    "ALC": "Alicante",
    "AGP": "Málaga (Nerja)",
}

DATAS = [
    "2026-10-15","2026-10-16","2026-10-17","2026-10-18","2026-10-19",
    "2026-10-20","2026-10-21","2026-10-22","2026-10-23","2026-10-24",
    "2026-10-25","2026-10-26","2026-10-27","2026-10-28","2026-10-29",
    "2026-10-30","2026-10-31",
]

# travel_class do SerpApi: 1=Economy, 2=Premium economy, 3=Business, 4=First
CLASSES = [
    {"code": 1, "label": "Econômica"},
    {"code": 3, "label": "Executiva"},
]

# Companhias alvo + links diretos
COMPANHIAS = {
    "LATAM":        {"codes": ["LA", "JJ", "LATAM"],         "site": "https://www.latam.com/pt_br/"},
    "TAP":          {"codes": ["TP", "TAP"],                  "site": "https://www.flytap.com/pt-br"},
    "Iberia":       {"codes": ["IB", "Iberia"],               "site": "https://www.iberia.com/br/"},
    "Air Europa":   {"codes": ["UX", "Air Europa"],           "site": "https://www.aireuropa.com/br/pt"},
    "Lufthansa":    {"codes": ["LH", "Lufthansa"],            "site": "https://www.lufthansa.com/br/pt"},
    "Air France":   {"codes": ["AF", "Air France"],           "site": "https://www.airfrance.com.br"},
    "KLM":          {"codes": ["KL", "KLM"],                  "site": "https://www.klm.com.br"},
    "British":      {"codes": ["BA", "British Airways"],      "site": "https://www.britishairways.com/pt-br"},
    "Outras":       {"codes": [],                             "site": ""},
}

MOEDA          = "BRL"
PRECO_ALERTA   = float(os.getenv("PRECO_ALERTA", 15000))
MAX_PARADAS    = int(os.getenv("MAX_PARADAS", 2))
API_RETRIES    = 3
DB_FILE        = "historico.db"
REPORT_HTML    = "report_voos.html"
LOG_FILE       = "monitor_voos.log"

CHEGADA_MIN, CHEGADA_MAX = 8, 21
CHEGADA_IDEAL_MIN, CHEGADA_IDEAL_MAX = 10, 18

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


# ─── SQLite ───────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(voos)").fetchall()]
    if cols and "bagagem" in cols:
        log.info("Migrando schema: tabela antiga (bagagem) removida, recriando com classe/companhia")
        conn.execute("DROP TABLE IF EXISTS voos")
        conn.commit()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS voos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT NOT NULL,
            data_viagem TEXT NOT NULL,
            destino TEXT NOT NULL,
            classe TEXT NOT NULL,
            companhia TEXT NOT NULL,
            preco REAL NOT NULL,
            dur_min INTEGER NOT NULL,
            partida TEXT, chegada TEXT,
            paradas INTEGER, escalas TEXT,
            classif TEXT, score INTEGER,
            url_companhia TEXT, url_google TEXT, url_kayak TEXT
        )
    """)
    conn.commit()
    return conn

def salvar_voo(conn, run_date, v):
    conn.execute("""
        INSERT INTO voos
        (run_date, data_viagem, destino, classe, companhia, preco, dur_min,
         partida, chegada, paradas, escalas, classif, score,
         url_companhia, url_google, url_kayak)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        run_date, v["data"], v["destino"], v["classe"], v["companhia"],
        v["preco"], v["dur_min"], v["partida"], v["chegada"],
        v["paradas"], json.dumps(v["escalas"], ensure_ascii=False),
        v["classif"], v["score"],
        v["url_companhia"], v["url_google"], v["url_kayak"],
    ))
    conn.commit()


def buscar_run_anterior(conn, run_atual):
    cur = conn.execute(
        "SELECT DISTINCT run_date FROM voos WHERE run_date < ? ORDER BY run_date DESC LIMIT 1",
        (run_atual,)
    )
    row = cur.fetchone()
    if not row:
        return {}
    cur = conn.execute(
        "SELECT data_viagem, destino, classe, companhia, MIN(preco) FROM voos WHERE run_date = ? "
        "GROUP BY data_viagem, destino, classe, companhia",
        (row[0],)
    )
    return {(r[0], r[1], r[2], r[3]): r[4] for r in cur.fetchall()}


# ─── Utilitários ──────────────────────────────────────────────────────────────
def hora(dt):
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try: return datetime.strptime(dt, fmt).hour
        except: pass
    return -1

def dur_fmt(m): return f"{m//60}h{m%60:02d}min"

def classificar(h):
    if CHEGADA_IDEAL_MIN <= h < CHEGADA_IDEAL_MAX: return "IDEAL", 0
    elif CHEGADA_MIN <= h < CHEGADA_IDEAL_MIN:    return "OK manhã", 60
    elif CHEGADA_IDEAL_MAX <= h <= CHEGADA_MAX:   return "OK tarde", 60
    else: return "NOITE", 9999


def identificar_companhia(cia_nome):
    """Recebe o nome da cia retornado pela API e mapeia para uma das COMPANHIAS."""
    nome = (cia_nome or "").lower()
    for marca, info in COMPANHIAS.items():
        if marca == "Outras": continue
        for c in info["codes"]:
            if c.lower() in nome:
                return marca
    return "Outras"


def gerar_url_companhia(marca, origem, destino, data):
    """Gera deep link para o site da companhia já com a busca preenchida quando possível."""
    base = COMPANHIAS.get(marca, {}).get("site", "")
    if not base:
        return ""
    # Links diretos com query string quando suportado
    if marca == "LATAM":
        return f"https://www.latam.com/pt_br/apps/personas/booking?fecha1_dia={data[8:10]}&fecha1_anomes={data[:7]}&from_city1={origem}&to_city1={destino}&ida_vuelta=ida&cabina=Y"
    if marca == "TAP":
        return f"https://book.flytap.com/booking/flights?adults=1&children=0&infants=0&origin={origem}&destination={destino}&departureDate={data}&tripType=O"
    if marca == "Iberia":
        return f"https://www.iberia.com/br/?market=br&language=pt&fromCity={origem}&toCity={destino}&departureDate={data}&adults=1&trip=O"
    if marca == "Air Europa":
        return f"https://www.aireuropa.com/br/pt/agencias/booking.html?origin={origem}&destination={destino}&departureDate={data}&adults=1&trip=O"
    if marca == "Air France":
        return f"https://wwws.airfrance.com.br/search/offers?bookingFlow=LEISURE&pax=1.0.0.0.0.0.0.0&cabinClass=ECONOMY&activeConnection=0&connections=O*{origem}*{data.replace('-','')}*{destino}"
    if marca == "KLM":
        return f"https://www.klm.com.br/search/offers?bookingFlow=LEISURE&pax=1.0.0.0.0.0.0.0&cabinClass=ECONOMY&activeConnection=0&connections=O*{origem}*{data.replace('-','')}*{destino}"
    if marca == "Lufthansa":
        return f"https://www.lufthansa.com/br/pt/flight-search?travelers=ADT:1&cabinClass=E&flights=O,{origem},{destino},{data}"
    if marca == "British":
        return f"https://www.britishairways.com/travel/fx/public/pt_br?eId=106001&from={origem}&to={destino}&depDate={data}&adults=1"
    return base


# ─── Busca SerpApi ────────────────────────────────────────────────────────────
def buscar(destino, data, travel_class):
    key = os.getenv("SERPAPI_KEY")
    if not key:
        log.error("SERPAPI_KEY ausente")
        return []
    params = {
        "engine":        "google_flights",
        "departure_id":  ORIGEM,
        "arrival_id":    destino,
        "outbound_date": data,
        "currency":      MOEDA,
        "type":          "2",
        "travel_class":  travel_class,
        "api_key":       key,
    }
    for t in range(1, API_RETRIES + 1):
        try:
            r = requests.get("https://serpapi.com/search", params=params, timeout=20)
            d = r.json()
            if r.status_code != 200 or "error" in d:
                log.warning("Tentativa %d falhou: %s", t, d.get("error", "?"))
                if t == API_RETRIES: return []
            else:
                return d.get("best_flights", []) + d.get("other_flights", [])
        except Exception as e:
            log.warning("Erro tentativa %d: %s", t, e)
        if t < API_RETRIES:
            time.sleep(1.0 * (2 ** (t-1)) + random.random())
    return []


def processar(voo, destino, data, classe_label):
    try:
        segs = voo["flights"]
        preco = float(voo["price"])
        dur = int(voo["total_duration"])
        paradas = len(segs) - 1
        if paradas > MAX_PARADAS: return None

        partida = segs[0]["departure_airport"]["time"]
        chegada = segs[-1]["arrival_airport"]["time"]
        cia_raw = segs[0].get("airline", "")
        marca   = identificar_companhia(cia_raw)

        h = hora(chegada)
        cl, pen = classificar(h)
        score = dur + pen + (paradas * 120)

        escalas = [f"{l['name']} ({dur_fmt(l['duration'])})" for l in voo.get("layovers", [])]

        return {
            "data": data, "destino": destino, "classe": classe_label,
            "companhia": marca, "cia_raw": cia_raw,
            "preco": preco, "dur_min": dur, "dur_fmt": dur_fmt(dur),
            "partida": partida, "chegada": chegada,
            "paradas": paradas, "escalas": escalas,
            "classif": cl, "score": score,
            "descartado": pen >= 9999,
            "abaixo_limite": preco < PRECO_ALERTA,
            "url_companhia": gerar_url_companhia(marca, ORIGEM, destino, data),
            "url_google": f"https://www.google.com/travel/flights?q=Voos+SSA+para+{destino}+em+{data}&hl=pt-BR&curr=BRL",
            "url_kayak": f"https://www.kayak.com.br/flights/{ORIGEM}-{destino}/{data}?sort=duration_a",
        }
    except Exception as e:
        log.error("Erro processar: %s", e)
        return None


# ─── Comparativo ──────────────────────────────────────────────────────────────
def comparar(preco_atual, preco_anterior):
    if preco_anterior is None:
        return ("🆕 NOVO", "#6b7280", "—")
    diff = preco_atual - preco_anterior
    pct = (diff / preco_anterior) * 100
    if abs(pct) < 1:
        return ("= igual", "#6b7280", f"R$ {preco_anterior:,.0f}")
    elif diff < 0:
        return (f"▼ {abs(pct):.1f}%", "#22c55e", f"R$ {preco_anterior:,.0f}")
    else:
        return (f"▲ {pct:.1f}%", "#ef4444", f"R$ {preco_anterior:,.0f}")


# ─── Report HTML com ABAS ─────────────────────────────────────────────────────
def gerar_html(voos_por_companhia, comparativo):
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")

    def cor_classif(c):
        if c == "IDEAL": return "#22c55e"
        if "OK" in c: return "#f59e0b"
        return "#ef4444"

    # Melhor global
    todos = [v for vs in voos_por_companhia.values() for v in vs]
    melhor_global = min(todos, key=lambda x: (x["score"], x["preco"])) if todos else None

    # Botões das abas (uma por companhia que tem voos)
    abas_btns, abas_conteudo = "", ""
    companhias_ativas = [c for c in COMPANHIAS if voos_por_companhia.get(c)]

    for i, cia in enumerate(companhias_ativas):
        ativo = "active" if i == 0 else ""
        voos_cia = voos_por_companhia[cia]
        min_eco = min((v["preco"] for v in voos_cia if v["classe"] == "Econômica"), default=None)
        min_exe = min((v["preco"] for v in voos_cia if v["classe"] == "Executiva"), default=None)
        resumo = f"{len(voos_cia)} voos"
        if min_eco: resumo += f" · Eco R$ {min_eco:,.0f}"
        if min_exe: resumo += f" · Exec R$ {min_exe:,.0f}"

        abas_btns += f"""
        <button class="tab-btn {ativo}" onclick="showTab('tab-{i}')">
            <b>{cia}</b><br><span style="font-size:11px;color:#6b7280">{resumo}</span>
        </button>"""

        # Agrupa por data+destino, pegando econômica e executiva lado a lado
        chaves = {}
        for v in voos_cia:
            k = (v["data"], v["destino"])
            chaves.setdefault(k, {"data": v["data"], "destino": v["destino"], "voos": {}})
            chaves[k]["voos"][v["classe"]] = v

        linhas = ""
        for k in sorted(chaves.keys()):
            grupo = chaves[k]
            eco = grupo["voos"].get("Econômica")
            exe = grupo["voos"].get("Executiva")
            ref = eco or exe

            preco_eco_html = "—"
            if eco:
                cmp_txt, cmp_cor, cmp_ant = comparar(
                    eco["preco"], comparativo.get((eco["data"], eco["destino"], "Econômica", cia))
                )
                preco_eco_html = f"""
                <b style="color:#1d4ed8;font-size:16px">R$ {eco['preco']:,.2f}</b><br>
                <span style="color:{cmp_cor};font-weight:bold;font-size:11px">{cmp_txt}</span>
                <span style="color:#9ca3af;font-size:10px"> ant: {cmp_ant}</span><br>
                <a href="{eco['url_companhia']}" target="_blank" style="font-size:11px;color:#1a73e8">→ {cia}</a> ·
                <a href="{eco['url_google']}" target="_blank" style="font-size:11px;color:#6b7280">Google</a>
                """

            preco_exe_html = "—"
            if exe:
                cmp_txt, cmp_cor, cmp_ant = comparar(
                    exe["preco"], comparativo.get((exe["data"], exe["destino"], "Executiva", cia))
                )
                preco_exe_html = f"""
                <b style="color:#7c3aed;font-size:16px">R$ {exe['preco']:,.2f}</b><br>
                <span style="color:{cmp_cor};font-weight:bold;font-size:11px">{cmp_txt}</span>
                <span style="color:#9ca3af;font-size:10px"> ant: {cmp_ant}</span><br>
                <a href="{exe['url_companhia']}" target="_blank" style="font-size:11px;color:#1a73e8">→ {cia}</a> ·
                <a href="{exe['url_google']}" target="_blank" style="font-size:11px;color:#6b7280">Google</a>
                """

            escalas_str = "<br>".join(ref["escalas"]) if ref["escalas"] else "Direto"

            linhas += f"""
            <tr>
                <td><b>{ref['data']}</b></td>
                <td><b>{ref['destino']}</b><br><span style="font-size:11px;color:#6b7280">{DESTINOS[ref['destino']]}</span></td>
                <td>{preco_eco_html}</td>
                <td>{preco_exe_html}</td>
                <td>{ref['dur_fmt']}</td>
                <td>{ref['paradas']}</td>
                <td style="font-size:11px">{escalas_str}</td>
                <td>{ref['partida'][-5:]} →<br>{ref['chegada'][-5:]}<br>
                    <span style="color:{cor_classif(ref['classif'])};font-weight:bold;font-size:11px">{ref['classif']}</span>
                </td>
            </tr>"""

        site_btn = ""
        if COMPANHIAS[cia]["site"]:
            site_btn = f'<a href="{COMPANHIAS[cia]["site"]}" target="_blank" style="background:#1a73e8;color:white;padding:6px 14px;border-radius:6px;font-size:13px">🌐 Site oficial {cia}</a>'

        abas_conteudo += f"""
        <div id="tab-{i}" class="tab-content {ativo}">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
                <h2 style="color:#1e3a5f;margin:0">✈️ {cia}</h2>
                {site_btn}
            </div>
            <table style="width:100%;border-collapse:collapse;font-size:13px">
                <thead><tr style="background:#1e3a5f;color:white">
                    <th style="padding:10px;text-align:left">Data</th>
                    <th style="padding:10px;text-align:left">Destino</th>
                    <th style="padding:10px;text-align:left">Econômica</th>
                    <th style="padding:10px;text-align:left">Executiva</th>
                    <th style="padding:10px;text-align:left">Duração</th>
                    <th style="padding:10px;text-align:left">Paradas</th>
                    <th style="padding:10px;text-align:left">Conexões</th>
                    <th style="padding:10px;text-align:left">Horários</th>
                </tr></thead>
                <tbody>{linhas}</tbody>
            </table>
        </div>"""

    melhor_card = ""
    if melhor_global:
        m = melhor_global
        melhor_card = f"""
        <div style="background:#ecfccb;border:2px solid #84cc16;border-radius:8px;padding:16px;margin-bottom:24px">
            <h3 style="margin:0 0 8px 0">🏅 MELHOR OFERTA GLOBAL</h3>
            <b>{m['companhia']}</b> · SSA→{m['destino']} ({DESTINOS[m['destino']]}) ·
            <b>{m['classe']}</b> ·
            <b style="color:#1d4ed8;font-size:18px">R$ {m['preco']:,.2f}</b> ·
            {m['dur_fmt']} · {m['paradas']} parada(s) ·
            Chegada {m['chegada'][-5:]}
            <span style="color:{cor_classif(m['classif'])};font-weight:bold">[{m['classif']}]</span><br>
            <a href="{m['url_companhia']}" target="_blank" style="color:#1a73e8;font-weight:bold">→ Reservar direto na {m['companhia']}</a>
            &nbsp;·&nbsp;
            <a href="{m['url_google']}" target="_blank" style="color:#6b7280">Comparar no Google Flights</a>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8"><title>Monitor SSA → Espanha</title>
<style>
body {{ font-family:Arial,sans-serif;max-width:1500px;margin:0 auto;padding:20px;color:#111 }}
h1 {{ color:#1e3a5f }}
.tabs {{ display:flex;flex-wrap:wrap;gap:6px;border-bottom:2px solid #1e3a5f;margin-bottom:0 }}
.tab-btn {{ background:#f1f5f9;border:none;padding:12px 18px;cursor:pointer;border-radius:6px 6px 0 0;
           font-size:14px;text-align:left;line-height:1.4;transition:all 0.2s }}
.tab-btn:hover {{ background:#e2e8f0 }}
.tab-btn.active {{ background:#1e3a5f;color:white }}
.tab-btn.active span {{ color:#cbd5e1 !important }}
.tab-content {{ display:none;padding:20px 0 }}
.tab-content.active {{ display:block }}
tr:hover {{ background:#f1f5f9 }}
td,th {{ padding:10px;border-bottom:1px solid #e2e8f0;vertical-align:top }}
a {{ text-decoration:none }} a:hover {{ text-decoration:underline }}
</style></head><body>

<h1>✈️ Monitor SSA → Granada / Alicante / Málaga (Nerja)</h1>
<p style="color:#6b7280">Outubro 2026: {DATAS[0]} a {DATAS[-1]} | Atualizado: <b>{agora}</b> | Alerta: R$ {PRECO_ALERTA:,.2f}</p>

{melhor_card}

<div class="tabs">{abas_btns}</div>
{abas_conteudo}

<script>
function showTab(id) {{
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.getElementById(id).classList.add('active');
    event.currentTarget.classList.add('active');
}}
</script>

<p style="color:#9ca3af;font-size:11px;margin-top:24px">
Dados via SerpApi/Google Flights. Preços e disponibilidade na companhia podem diferir — confirme sempre antes de comprar.
</p>
</body></html>"""

    with open(REPORT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    log.info("Report HTML gerado: %s", REPORT_HTML)
    return html


# ─── Email ────────────────────────────────────────────────────────────────────
def enviar_email(html_body, resumo):
    rem = os.getenv("EMAIL_REMETENTE")
    sen = os.getenv("EMAIL_SENHA")
    dest = os.getenv("EMAIL_DESTINATARIO", rem)
    if not rem or not sen:
        log.warning("Email não configurado")
        print("    Email não configurado (EMAIL_SENHA vazio)")
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"✈️ Voos SSA→Espanha | {resumo}"
    msg["From"] = rem
    msg["To"] = dest
    msg.attach(MIMEText(html_body, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(rem, sen)
            s.sendmail(rem, dest, msg.as_string())
        log.info("Email enviado para %s", dest)
        print(f"    ✅ Email enviado para {dest}")
        return True
    except Exception as e:
        log.error("Erro email: %s", e)
        print(f"    ❌ Erro email: {e}")
        return False


# ─── Ciclo principal ──────────────────────────────────────────────────────────
def executar():
    run_atual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*60}")
    print(f"  RUN: {run_atual}")
    print(f"  Destinos: GRX, ALC, AGP | Classes: Eco + Exec | {len(DATAS)} datas")
    print(f"  Total chamadas: {len(DESTINOS) * len(DATAS) * len(CLASSES)}")
    print(f"{'='*60}")

    conn = init_db()
    comparativo = buscar_run_anterior(conn, run_atual)
    if comparativo:
        print(f"  Comparando com run anterior ({len(comparativo)} preços)")

    voos_por_companhia = {cia: [] for cia in COMPANHIAS}

    for cls in CLASSES:
        print(f"\n  [{cls['label']}]")
        for destino in DESTINOS:
            print(f"\n    SSA → {destino}")
            for data in DATAS:
                time.sleep(1.2)
                voos = buscar(destino, data, cls["code"])
                if not voos:
                    print(f"      {data} | sem resultados")
                    continue

                proc = [processar(v, destino, data, cls["label"]) for v in voos]
                proc = [v for v in proc if v and not v["descartado"]]

                # Salva o MELHOR voo de CADA companhia para essa (data, destino, classe)
                por_cia = {}
                for v in proc:
                    c = v["companhia"]
                    if c not in por_cia or v["score"] < por_cia[c]["score"]:
                        por_cia[c] = v

                if por_cia:
                    for c, v in por_cia.items():
                        voos_por_companhia[c].append(v)
                        salvar_voo(conn, run_atual, v)
                    melhor = min(por_cia.values(), key=lambda x: x["preco"])
                    print(f"      {data} | {len(por_cia)} cia(s) | menor: {melhor['companhia']} R$ {melhor['preco']:,.0f}")

    # Remove companhias vazias
    voos_por_companhia = {c: vs for c, vs in voos_por_companhia.items() if vs}

    todos = [v for vs in voos_por_companhia.values() for v in vs]
    if todos:
        melhor = min(todos, key=lambda x: (x["score"], x["preco"]))
        resumo = f"{len(todos)} ofertas | melhor: {melhor['companhia']} R$ {melhor['preco']:,.0f} {melhor['classe']}"
    else:
        resumo = "sem resultados"

    html = gerar_html(voos_por_companhia, comparativo)
    enviar_email(html, resumo)
    conn.close()
    print(f"\n  ✅ {resumo}")


if __name__ == "__main__":
    print(f"\n{'='*60}")
    print("  Monitor Semanal de Voos | SSA → Espanha")
    print(f"  Destinos: GRX + ALC + AGP")
    print(f"  Classes: Econômica + Executiva")
    print(f"  Período: {DATAS[0]} a {DATAS[-1]}")
    print(f"  Toda segunda às 08:00")
    print(f"{'='*60}\n")

    executar()

    if not os.getenv("ONE_SHOT"):
        schedule.every().monday.at("08:00").do(executar)
        print(f"\n  ⏰ Próxima execução: próxima segunda-feira às 08:00")
        while True:
            schedule.run_pending()
            time.sleep(60)
