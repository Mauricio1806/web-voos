"""
Dashboard Streamlit — abas por companhia, econômica + executiva, comparativo semanal.
Roda com:  streamlit run dashboard.py
"""

import sqlite3
import pandas as pd
import streamlit as st
import plotly.express as px

DB_FILE = "historico.db"

DESTINOS = {
    "GRX": "Granada",
    "ALC": "Alicante",
    "AGP": "Málaga (Nerja)",
}

st.set_page_config(page_title="Voos SSA → Espanha", page_icon="✈️", layout="wide")

st.title("✈️ Monitor de Voos: Salvador → Espanha")
st.caption("Granada · Alicante · Málaga/Nerja — Outubro 2026")

# ─── Carregar dados ───────────────────────────────────────────────────────────
@st.cache_data(ttl=60)
def carregar_dados():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM voos ORDER BY run_date DESC, score ASC", conn)
    conn.close()
    if df.empty: return df
    df["run_date"] = pd.to_datetime(df["run_date"])
    df["data_viagem"] = pd.to_datetime(df["data_viagem"])
    return df

try:
    df = carregar_dados()
except Exception as e:
    st.error(f"Erro ao carregar banco: {e}")
    st.info("Rode primeiro o `monitor_voos.py` para popular o banco.")
    st.stop()

if df.empty:
    st.warning("Nenhum dado ainda. Rode primeiro `python monitor_voos.py`.")
    st.stop()

if "classe" not in df.columns:
    st.error("Schema antigo detectado (coluna 'bagagem'). Rode `python monitor_voos.py` uma vez para migrar o banco.")
    st.stop()

# ─── Sidebar ──────────────────────────────────────────────────────────────────
runs = sorted(df["run_date"].dt.strftime("%Y-%m-%d %H:%M").unique(), reverse=True)
run_sel = st.sidebar.selectbox("📅 Run atual", runs, index=0)
df_run = df[df["run_date"].dt.strftime("%Y-%m-%d %H:%M") == run_sel]

run_ant = None
if len(runs) > 1:
    idx = runs.index(run_sel)
    if idx + 1 < len(runs):
        run_ant = runs[idx + 1]
df_ant = df[df["run_date"].dt.strftime("%Y-%m-%d %H:%M") == run_ant] if run_ant else pd.DataFrame()

st.sidebar.header("🔍 Filtros")
destinos_sel = st.sidebar.multiselect("Destinos", list(DESTINOS.keys()),
                                       default=list(DESTINOS.keys()),
                                       format_func=lambda x: f"{x} — {DESTINOS[x]}")
classes_sel = st.sidebar.multiselect("Classes", df_run["classe"].unique().tolist(),
                                      default=df_run["classe"].unique().tolist())
max_paradas = st.sidebar.slider("Máximo de paradas", 0, 3, 2)
classif_sel = st.sidebar.multiselect("Classificação chegada",
                                      df_run["classif"].unique().tolist(),
                                      default=df_run["classif"].unique().tolist())

filtrado = df_run[
    df_run["destino"].isin(destinos_sel) &
    df_run["classe"].isin(classes_sel) &
    (df_run["paradas"] <= max_paradas) &
    df_run["classif"].isin(classif_sel)
]

# ─── KPIs ─────────────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
if not filtrado.empty:
    melhor = filtrado.loc[filtrado["score"].idxmin()]
    c1.metric("🏆 Melhor oferta", f"R$ {melhor['preco']:,.0f}",
              delta=f"{melhor['companhia']} · {melhor['destino']}", delta_color="off")
    eco = filtrado[filtrado["classe"] == "Econômica"]
    exe = filtrado[filtrado["classe"] == "Executiva"]
    c2.metric("💰 Menor Econômica", f"R$ {eco['preco'].min():,.0f}" if not eco.empty else "—")
    c3.metric("💎 Menor Executiva", f"R$ {exe['preco'].min():,.0f}" if not exe.empty else "—")
    c4.metric("📊 Total ofertas", len(filtrado))

# ─── Comparativo ──────────────────────────────────────────────────────────────
st.subheader("📊 Comparativo com a Semana Anterior")
if df_ant.empty:
    st.info("Sem run anterior para comparar.")
else:
    merge_cols = ["data_viagem", "destino", "classe", "companhia"]
    df_cmp = filtrado.merge(
        df_ant.groupby(merge_cols)["preco"].min().reset_index().rename(columns={"preco": "preco_ant"}),
        on=merge_cols, how="left"
    )
    df_cmp["diff_pct"] = ((df_cmp["preco"] - df_cmp["preco_ant"]) / df_cmp["preco_ant"]) * 100

    def status(row):
        if pd.isna(row["preco_ant"]): return "🆕 NOVO"
        if abs(row["diff_pct"]) < 1: return "= igual"
        if row["diff_pct"] < 0: return f"▼ {abs(row['diff_pct']):.1f}%"
        return f"▲ {row['diff_pct']:.1f}%"

    df_cmp["variação"] = df_cmp.apply(status, axis=1)

    sub = (df_cmp["preco"] > df_cmp["preco_ant"]).sum()
    desc = (df_cmp["preco"] < df_cmp["preco_ant"]).sum()
    igu = ((df_cmp["preco"] - df_cmp["preco_ant"]).abs() < 1).sum()
    novos = df_cmp["preco_ant"].isna().sum()

    cc1, cc2, cc3, cc4 = st.columns(4)
    cc1.metric("▲ Subiram", int(sub))
    cc2.metric("▼ Desceram", int(desc))
    cc3.metric("= Iguais", int(igu))
    cc4.metric("🆕 Novos", int(novos))

# ─── Abas por companhia ───────────────────────────────────────────────────────
st.subheader("✈️ Ofertas por companhia")

companhias = sorted(filtrado["companhia"].unique().tolist())
if not companhias:
    st.warning("Nenhum voo nos filtros.")
else:
    abas = st.tabs([f"{c} ({len(filtrado[filtrado['companhia']==c])})" for c in companhias])

    for tab, cia in zip(abas, companhias):
        with tab:
            df_cia = filtrado[filtrado["companhia"] == cia].copy()

            # Métricas da companhia
            mc1, mc2, mc3 = st.columns(3)
            eco_cia = df_cia[df_cia["classe"] == "Econômica"]
            exe_cia = df_cia[df_cia["classe"] == "Executiva"]
            mc1.metric(f"Econômica ({len(eco_cia)} voos)",
                       f"R$ {eco_cia['preco'].min():,.0f}" if not eco_cia.empty else "—")
            mc2.metric(f"Executiva ({len(exe_cia)} voos)",
                       f"R$ {exe_cia['preco'].min():,.0f}" if not exe_cia.empty else "—")
            mc3.metric("Duração média",
                       f"{int(df_cia['dur_min'].mean())//60}h{int(df_cia['dur_min'].mean())%60:02d}min")

            # Tabela pivotada: data+destino com Eco e Exec lado a lado
            df_cia["partida_h"] = df_cia["partida"].str[-5:]
            df_cia["chegada_h"] = df_cia["chegada"].str[-5:]
            df_cia["dur"] = df_cia["dur_min"].apply(lambda m: f"{m//60}h{m%60:02d}")
            df_cia["data_str"] = df_cia["data_viagem"].dt.strftime("%d/%m")

            # Pivot
            pivot = df_cia.pivot_table(
                index=["data_str", "destino", "dur", "paradas", "partida_h", "chegada_h", "classif"],
                columns="classe", values="preco", aggfunc="min"
            ).reset_index()

            # Link da companhia (pega o primeiro url_companhia disponível)
            link_cia = df_cia["url_companhia"].iloc[0] if not df_cia["url_companhia"].empty else ""

            cols_show = ["data_str", "destino", "Econômica", "Executiva",
                          "dur", "paradas", "partida_h", "chegada_h", "classif"]
            cols_show = [c for c in cols_show if c in pivot.columns]
            pivot = pivot[cols_show].rename(columns={
                "data_str": "Data", "destino": "Dest.",
                "dur": "Duração", "paradas": "Paradas",
                "partida_h": "Partida", "chegada_h": "Chegada",
                "classif": "Classif.",
            })

            col_cfg = {}
            if "Econômica" in pivot.columns:
                col_cfg["Econômica"] = st.column_config.NumberColumn(format="R$ %.2f")
            if "Executiva" in pivot.columns:
                col_cfg["Executiva"] = st.column_config.NumberColumn(format="R$ %.2f")

            st.dataframe(pivot, use_container_width=True, hide_index=True, column_config=col_cfg)

            if link_cia:
                st.markdown(f"🌐 **[Abrir site oficial da {cia} com busca preenchida]({link_cia})**")

# ─── Histórico ────────────────────────────────────────────────────────────────
st.subheader("📈 Histórico semanal")
hist = df.groupby([df["run_date"].dt.strftime("%Y-%m-%d"), "destino", "classe"])["preco"].min().reset_index()
hist.columns = ["run", "destino", "classe", "menor_preco"]
fig = px.line(hist, x="run", y="menor_preco", color="destino", line_dash="classe",
               markers=True, title="Menor preço por destino e classe ao longo das runs",
               labels={"menor_preco": "Menor preço (R$)", "run": "Run"})
st.plotly_chart(fig, use_container_width=True)

st.caption(f"💾 Banco: {DB_FILE} | Run atual: {run_sel}")
