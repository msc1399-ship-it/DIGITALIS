import streamlit as st
import pandas as pd
import re

from modules.ingestion import load_excel
from modules.parser import parse_sections
from modules.classification import normalize_columns
from modules.analytics import analizar_factura_bidafarma, analizar_factura_transfer

# =========================
# NORMALIZADOR GLOBAL
# =========================

def normalizar_albaran(valor):
    valor = str(valor).lower().strip()
    match = re.match(r"^[a-z]{0,3}-?\d+$", valor)

    if match:
        return re.sub(r"[^\d]", "", valor)

    return valor

df = None
proveedores_detectados = []

st.set_page_config(layout="wide")
st.title("📊 Auditoría de Compras Farmacia")

# =========================
# 1. ALBARANES
# =========================

st.header("1️⃣ Subida de albaranes")

col1, col2 = st.columns(2)

with col1:
    uploaded_files = st.file_uploader(
        "📦 Albaranes BIDAFARMA (goteo)",
        type=["xlsx"],
        accept_multiple_files=True
    )

with col2:
    uploaded_transfer = st.file_uploader(
        "🚚 Albaranes TRANSFER",
        type=["xlsx"],
        accept_multiple_files=True,
        key="transfer"
    )

dfs = []

# GOTE0
if uploaded_files:
    for uploaded_file in uploaded_files:
        df_temp = normalize_columns(load_excel(uploaded_file))
        df_temp.columns = [c.lower().strip() for c in df_temp.columns]

        df_temp["proveedor"] = "bidafarma"
        df_temp["tipo_compra"] = "goteo"

        col_albaran = next((c for c in df_temp.columns if "albaran" in c), None)

        if col_albaran:
            df_temp["albaran"] = df_temp[col_albaran].apply(normalizar_albaran)

        df_temp = parse_sections(df_temp)
        dfs.append(df_temp)

# TRANSFER
if uploaded_transfer:
    for uploaded_file in uploaded_transfer:
        df_temp = normalize_columns(load_excel(uploaded_file))
        df_temp.columns = [c.lower().strip() for c in df_temp.columns]

        df_temp["proveedor"] = "bidafarma"
        df_temp["tipo_compra"] = "transfer"

        col_albaran = next((c for c in df_temp.columns if "albaran" in c), None)

        if col_albaran:
            df_temp["albaran"] = df_temp[col_albaran].apply(normalizar_albaran)

        df_temp = parse_sections(df_temp)
        dfs.append(df_temp)

if dfs:
    df = pd.concat(dfs, ignore_index=True)

# =========================
# VISTAS
# =========================

if df is not None:

    for tipo in ["goteo", "transfer"]:

        df_tipo = df[df["tipo_compra"] == tipo]

        if df_tipo.empty:
            continue

        titulo = "📦 Goteo" if tipo == "goteo" else "🚚 Transfer"
        st.header(f"{titulo}")

        st.dataframe(df_tipo)

        df_tipo["es_abono"] = df_tipo["neto"] < 0
        abonos = df_tipo[df_tipo["es_abono"]]

        total_bruto = df_tipo["bruto"].sum()
        total_neto = df_tipo["neto"].sum()
        total_abonos = abonos["neto"].sum()

        descuento = (total_bruto - total_neto) / total_bruto * 100 if total_bruto else 0

        c1, c2, c3, c4, c5, c6 = st.columns(6)

        c1.metric("Líneas", len(df_tipo))
        c2.metric("Unidades", int(df_tipo["unidades"].sum()))
        c3.metric("Bruto", f"{total_bruto:.1f} €")
        c4.metric("Neto", f"{total_neto:.1f} €")
        c5.metric("Desc %", round(descuento, 2))
        c6.metric("Abonos", f"{abs(total_abonos):.1f} €")

# =========================
# 2. FACTURAS
# =========================

if df is not None:

    st.header("2️⃣ Facturas")

    # -------------------------
    # FACTURA NORMAL
    # -------------------------
    factura_normal = st.file_uploader("Factura NORMAL", type=["xlsx"])

    resultado = None

    if factura_normal:

        resultado = analizar_factura_bidafarma(factura_normal)

        df_goteo = df[df["tipo_compra"] == "goteo"]

        albaranes_factura = set(resultado["albaranes"])
        albaranes_df = set(df_goteo["albaran"].apply(normalizar_albaran))

        faltan = albaranes_df - albaranes_factura
        sobran = albaranes_factura - albaranes_df

        if not faltan and not sobran:
            st.success("✅ Albaranes NORMAL conciliados")
        else:
            if faltan:
                st.error(f"Faltan: {faltan}")
            if sobran:
                st.warning(f"Sobran: {sobran}")

        st.subheader("💸 Gastos factura normal")
        st.dataframe(resultado["gastos"])

        resumen = resultado.get("resumen_costes")

        if resumen:
            st.subheader("💰 Coste total factura normal")

            col1, col2, col3 = st.columns(3)

            col1.metric("Base", f"{resumen['base']} €")
            col2.metric("IVA (21%)", f"{resumen['iva']} €")
            col3.metric("TOTAL", f"{resumen['total']} €")

        # BITRANSFER
        df_bida = df[df["proveedor"] == "bidafarma"]

        hay_bitransfer = False
        if "seccion_albaran" in df_bida.columns:
            hay_bitransfer = (df_bida["seccion_albaran"] == "bitransfer").any()

        hay_gestion = False
        if resultado and not resultado["gastos"].empty:
            hay_gestion = (resultado["gastos"]["tipo"] == "gestion").any()

        if hay_bitransfer and hay_gestion:

            st.subheader("🔍 Desglose gastos gestión Bitransfer")

            excel_bitransfer = st.file_uploader(
                "Excel Bitransfer",
                type=["xlsx"],
                key="bitransfer_excel"
            )

            if excel_bitransfer:
                df_bt = pd.read_excel(excel_bitransfer)
                st.dataframe(df_bt.head())

    # -------------------------
    # FACTURA TRANSFER
    # -------------------------
    factura_transfer = st.file_uploader("Factura TRANSFER", type=["xlsx"])

    if factura_transfer:

        resultado_transfer = analizar_factura_transfer(factura_transfer)

        df_transfer = df[df["tipo_compra"] == "transfer"]

        albaranes_factura = set(resultado_transfer["albaranes"])
        albaranes_df = set(df_transfer["albaran"].apply(normalizar_albaran))

        faltan = albaranes_df - albaranes_factura
        sobran = albaranes_factura - albaranes_df

        if not faltan and not sobran:
            st.success("✅ Albaranes TRANSFER conciliados")
        else:
            if faltan:
                st.error(f"Faltan en transfer: {faltan}")
            if sobran:
                st.warning(f"Sobran en transfer: {sobran}")

        st.subheader("🚚 Servicios logísticos")
        st.dataframe(resultado_transfer["gastos"])

        st.subheader("🏭 Abonos laboratorios")
        st.dataframe(resultado_transfer["abonos"])

        resumen = resultado_transfer.get("resumen_logistica")

        if resumen:
            st.subheader("💰 Coste total logística")

            col1, col2, col3 = st.columns(3)

            col1.metric("Base", f"{resumen['base']} €")
            col2.metric("IVA (21%)", f"{resumen['iva']} €")
            col3.metric("TOTAL", f"{resumen['total']} €")

# =========================
# INICIO
# =========================

if df is None:
    st.warning("Sube archivos")


