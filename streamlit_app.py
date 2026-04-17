import streamlit as st
import pandas as pd
import re
import importlib

from modules.ingestion import load_excel
from modules.parser import parse_sections
from modules.classification import normalize_columns
from modules.analytics import analizar_factura_bidafarma, analizar_factura_transfer
import modules.bitransfer as bitransfer
import modules.servicios as servicios

bitransfer = importlib.reload(bitransfer)
servicios = importlib.reload(servicios)

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

        analisis_servicios = servicios.analizar_gastos_servicios(df, resultado["gastos"])

        if analisis_servicios and analisis_servicios["resumen"]["servicios_factura"] > 0:
            st.subheader("🧾 Imputación gastos por servicios")

            resumen_servicios = analisis_servicios["resumen"]

            s1, s2, s3, s4, s5, s6 = st.columns(6)
            s1.metric("Avantia", "Sí" if resumen_servicios["tiene_avantia"] else "No")
            s2.metric("Cargo Vida Natural", f"{resumen_servicios['cargo_pct_vida_natural']:.1f}%")
            s3.metric("Servicios factura", f"{resumen_servicios['servicios_factura']:.2f} €")
            s4.metric("Vida Natural", f"{resumen_servicios['cargo_vida_natural']:.2f} €")
            s5.metric("Dif. servicios", f"{resumen_servicios['diferencia_servicios']:.2f} €")
            s6.metric("Devoluciones", f"{resumen_servicios['cargo_devoluciones']:.2f} €")

            if abs(resumen_servicios["diferencia_servicios"]) <= 0.05:
                st.success("Los servicios de factura cuadran con el cargo calculado de Vida Natural.")
            elif resumen_servicios["diferencia_servicios"] > 0:
                st.warning(
                    "Hay importe de servicios no cubierto por Vida Natural. "
                    "Se imputa como posible cargo por devoluciones sobre abonos."
                )
            else:
                st.warning(
                    "El cargo calculado de Vida Natural supera el importe de servicios de factura. "
                    "Revisa las líneas con observación B o la condición Avantia."
                )

            if not analisis_servicios["resumen_cn"].empty:
                st.caption("Resumen de servicios imputados por código nacional")
                st.dataframe(analisis_servicios["resumen_cn"])

            if not analisis_servicios["detalle"].empty:
                st.caption("Detalle de líneas afectadas por servicios")
                st.dataframe(analisis_servicios["detalle"])

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

            col_consumos, col_compras = st.columns(2)

            with col_consumos:
                excel_consumos_bitransfer = st.file_uploader(
                    "Cuadro resumen de consumos",
                    type=["xlsx"],
                    key="bitransfer_consumos_excel"
                )

            with col_compras:
                excel_compras_bitransfer = st.file_uploader(
                    "Listado de compras BitTransfer",
                    type=["xlsx"],
                    key="bitransfer_compras_excel"
                )

            resumen_consumos = None
            df_bt_compras = None

            if excel_consumos_bitransfer:
                try:
                    resumen_consumos = bitransfer.leer_cuadro_resumen_consumos(excel_consumos_bitransfer)

                    st.subheader("📊 Cuadro resumen de consumos normalizado")

                    if not resumen_consumos["bitransfer"].empty:
                        st.caption("Bloque BitTransfer")
                        st.dataframe(resumen_consumos["bitransfer"])

                    if not resumen_consumos["plataformas"].empty:
                        st.caption("Bloque plataformas")
                        st.dataframe(resumen_consumos["plataformas"])

                except ValueError as error:
                    st.error(f"No se pudo leer el cuadro resumen de consumos: {error}")

            if excel_compras_bitransfer:
                try:
                    df_bt_compras = bitransfer.leer_listado_compras_bitransfer(excel_compras_bitransfer)

                    st.subheader("📋 Listado de compras BitTransfer normalizado")

                    c1, c2, c3 = st.columns(3)
                    c1.metric("Códigos nacionales", df_bt_compras["cn"].nunique())
                    c2.metric("Unidades", int(df_bt_compras["cantidad"].fillna(0).sum()))
                    c3.metric("Importe neto", f"{df_bt_compras['importe_neto'].sum():.2f} €")

                    st.dataframe(df_bt_compras)

                except ValueError as error:
                    st.error(f"No se pudo leer el listado de compras BitTransfer: {error}")

            if resumen_consumos is not None and df_bt_compras is not None:
                try:
                    df_bt_conciliado, resumen_conciliacion = bitransfer.conciliar_bitransfer_consumos(
                        df_bt_compras,
                        resumen_consumos
                    )

                    st.subheader("✅ Conciliación BitTransfer")

                    c1, c2, c3, c4, c5, c6 = st.columns(6)
                    c1.metric("Bruto resumen", f"{resumen_conciliacion['venta_bruta_resumen']:.2f} €")
                    c2.metric("Bruto compras", f"{resumen_conciliacion['venta_bruta_compras']:.2f} €")
                    c3.metric("Diferencia bruto", f"{resumen_conciliacion['diferencia_venta_bruta']:.2f} €")
                    c4.metric("Cargo resumen", f"{resumen_conciliacion['cargo_resumen']:.2f} €")
                    c5.metric("Cargo teórico", f"{resumen_conciliacion['cargo_teorico_compras']:.2f} €")
                    c6.metric("Dif. cargo", f"{resumen_conciliacion['diferencia_cargo']:.2f} €")

                    if abs(resumen_conciliacion["diferencia_venta_bruta"]) <= 0.05:
                        st.success("La venta bruta del resumen cuadra con el listado de compras BitTransfer.")
                    else:
                        st.warning(
                            "La venta bruta no cuadra todavía. "
                            "Revisa si el listado de compras contiene exactamente los productos del resumen."
                        )

                    st.caption(
                        "Detalle unitario: PBL, descuento, importe neto unitario, "
                        "cargo teórico unitario y coste real unitario."
                    )
                    st.dataframe(df_bt_conciliado)

                    plataformas = resumen_consumos["plataformas"]
                    if not plataformas.empty:
                        st.subheader("🧩 Listados de productos de plataformas")
                        st.info(
                            "El cuadro resumen contiene plataformas o grupos adicionales. "
                            "Sube aquí el Excel de productos de cada plataforma para poder prorratear cuotas "
                            "y aplicar su cargo específico en el siguiente paso."
                        )

                        for indice, plataforma in plataformas.iterrows():
                            nombre_plataforma = str(plataforma["plataforma"])
                            cargo_pct = plataforma.get("cargo_pct")
                            cuota = plataforma.get("cuota")

                            st.markdown(
                                f"**{nombre_plataforma}**"
                                f" · Cargo: {cargo_pct if pd.notna(cargo_pct) else 0:.2f}%"
                                f" · Cuota: {cuota if pd.notna(cuota) else 0:.2f} €"
                            )

                            excel_plataforma = st.file_uploader(
                                f"Listado de productos {nombre_plataforma}",
                                type=["xlsx"],
                                key=f"plataforma_{indice}_excel"
                            )

                            if excel_plataforma:
                                try:
                                    df_plataforma = bitransfer.leer_listado_compras_bitransfer(excel_plataforma)
                                    st.dataframe(df_plataforma)
                                except ValueError as error:
                                    st.error(
                                        f"No se pudo leer el listado de productos de {nombre_plataforma}: {error}"
                                    )

                except ValueError as error:
                    st.error(f"No se pudo conciliar BitTransfer: {error}")

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
