import streamlit as st
import pandas as pd

# módulos
from modules.ingestion import load_excel
from modules.parser import parse_sections
from modules.classification import normalize_columns
from modules.analytics import analizar_factura_bidafarma
from modules.cost_engine import apply_costs


def normalizar_texto(valor):
    return str(valor).strip().lower()


def detectar_columna(df_temp, candidatos):
    for col in df_temp.columns:
        col_norm = normalizar_texto(col)
        if any(c in col_norm for c in candidatos):
            return col
    return None


def extraer_albaranes_y_neto_factura(df_factura):
    """
    Devuelve resumen por albarán con su neto para poder cruzar contra albaranes subidos.
    """
    df_aux = df_factura.copy()
    df_aux.columns = [c.lower().strip() for c in df_aux.columns]

    col_albaran = detectar_columna(df_aux, ["albaran", "albarán", "documento"])
    col_neto = detectar_columna(df_aux, ["neto", "importe", "base"])

    if not col_albaran or not col_neto:
        return pd.DataFrame(columns=["albaran", "neto"])

    df_aux["albaran"] = df_aux[col_albaran].astype(str).str.strip()
    df_aux["neto"] = pd.to_numeric(df_aux[col_neto], errors="coerce").fillna(0)

    df_aux = df_aux[df_aux["albaran"].str.len() > 0]

    if df_aux.empty:
        return pd.DataFrame(columns=["albaran", "neto"])

    return df_aux.groupby("albaran", as_index=False)["neto"].sum()


def detectar_cargos_factura(df_factura):
    """
    Detecta cargos de factura excluyendo líneas de IVA/recargo de equivalencia.
    """
    df_aux = df_factura.copy()
    df_aux.columns = [c.lower().strip() for c in df_aux.columns]

    col_desc = detectar_columna(df_aux, ["descripcion", "descripción", "concepto", "detalle", "texto"])
    col_importe = detectar_columna(df_aux, ["importe", "neto", "total"])

    if not col_desc or not col_importe:
        return pd.DataFrame(columns=["descripcion", "importe"])

    df_aux["descripcion"] = df_aux[col_desc].astype(str).str.strip()
    df_aux["importe"] = pd.to_numeric(df_aux[col_importe], errors="coerce").fillna(0)

    palabras_cargo = [
        "cargo",
        "portes",
        "servicio",
        "cuota",
        "ajuste",
        "regularizacion",
        "regularización",
        "financiero",
        "comision",
        "comisión",
    ]
    palabras_impuestos = ["iva", "recargo", "equivalencia", "igic"]

    df_aux["desc_norm"] = df_aux["descripcion"].str.lower()

    es_cargo = df_aux["desc_norm"].apply(lambda x: any(p in x for p in palabras_cargo))
    es_impuesto = df_aux["desc_norm"].apply(lambda x: any(p in x for p in palabras_impuestos))

    cargos_df = df_aux[es_cargo & ~es_impuesto & (df_aux["importe"] != 0)].copy()

    return cargos_df[["descripcion", "importe"]]


def leer_factura(file):
    if file is None:
        return pd.DataFrame()
    return pd.read_excel(file)


condiciones = {}
df = None
proveedores_detectados = []

st.set_page_config(layout="wide")
st.title("📊 Auditoría de Compras Farmacia")

# =========================
# 1. SUBIDA DE ALBARANES
# =========================

st.header("1️⃣ Subida de albaranes")

uploaded_files = st.file_uploader(
    "Sube uno o varios albaranes",
    type=["xlsx"],
    accept_multiple_files=True
)

if uploaded_files:

    dfs = []

    for uploaded_file in uploaded_files:

        try:
            df_temp = load_excel(uploaded_file)
            df_temp = normalize_columns(df_temp)

            df_temp.columns = [c.lower().strip() for c in df_temp.columns]

            nombre_archivo = uploaded_file.name.lower()

            proveedor = "desconocido"
            if "bidafarma" in nombre_archivo:
                proveedor = "bidafarma"
            elif "cofares" in nombre_archivo:
                proveedor = "cofares"

            df_temp["proveedor"] = proveedor

            # detectar albarán real
            col_albaran = None
            for col in df_temp.columns:
                if "albaran" in col:
                    col_albaran = col
                    break

            if col_albaran:
                df_temp["albaran"] = df_temp[col_albaran]
            else:
                df_temp["albaran"] = uploaded_file.name

            df_temp = parse_sections(df_temp)

            dfs.append(df_temp)

        except Exception as e:
            st.error(f"Error procesando archivo {uploaded_file.name}: {e}")

    if dfs:
        df = pd.concat(dfs, ignore_index=True)
        proveedores_detectados = df["proveedor"].dropna().unique().tolist()

        st.subheader("📍 Proveedores detectados")
        st.write(proveedores_detectados)

# =========================
# VISTA POR PROVEEDOR
# =========================

if df is not None and "proveedor" in df.columns:

    proveedores_detectados = df["proveedor"].dropna().unique().tolist()

    for proveedor in proveedores_detectados:

        df_prov = df[df["proveedor"] == proveedor].copy()

        if df_prov.empty:
            continue

        # =========================
        # COLUMNAS DERIVADAS
        # =========================

        df_prov["es_abono"] = df_prov["neto"] < 0

        df_prov["precio_unitario"] = df_prov["neto"] / df_prov["unidades"]
        df_prov["precio_unitario"] = df_prov["precio_unitario"].replace([float("inf"), -float("inf")], 0)

        df_prov["tiene_descuento"] = (df_prov["bruto"] - df_prov["neto"]) > 0

        # =========================
        # 👉 TIPO OPERACIÓN (OCULTO)
        # =========================

        df_prov["_tipo_operacion"] = "goteo"

        df_prov.loc[
            df_prov["seccion_albaran"] == "bitransfer",
            "_tipo_operacion"
        ] = "bitransfer"

        df_prov.loc[
            df_prov["descripcion"].str.contains("club", case=False, na=False),
            "_tipo_operacion"
        ] = "club"

        df_prov.loc[
            df_prov["neto"] < 0,
            "_tipo_operacion"
        ] = "abono"

        compras_df = df_prov[~df_prov["es_abono"]]
        abonos_df = df_prov[df_prov["es_abono"]]

        # =========================
        # UI
        # =========================

        st.header(f"📦 Compras - {proveedor.upper()}")

        st.subheader("📄 Vista consolidada")

        # 👉 ocultamos columnas internas
        df_display = df_prov.drop(columns=["_tipo_operacion"], errors="ignore")
        st.dataframe(df_display)

        st.subheader("📊 Resumen general")

        total_bruto = df_prov["bruto"].sum()
        total_neto = df_prov["neto"].sum()
        total_abonos = abonos_df["neto"].sum()

        descuento_medio = 0
        if total_bruto > 0:
            descuento_medio = (total_bruto - total_neto) / total_bruto * 100

        col1, col2, col3, col4, col5, col6 = st.columns(6)

        col1.metric("Nº líneas", len(df_prov))
        col2.metric("Unidades", int(df_prov["unidades"].sum()))
        col3.metric("Bruto (€)", round(total_bruto, 2))
        col4.metric("Neto (€)", round(total_neto, 2))
        col5.metric("Desc. medio (%)", round(descuento_medio, 2))
        col6.metric("Abonos (€)", round(abs(total_abonos), 2))

        # =========================
        # TIPOS DE LÍNEA
        # =========================

        st.subheader("📊 Tipos de línea")

        if proveedor == "bidafarma":

            categorias = {
                "bitransfer": df_prov["seccion_albaran"] == "bitransfer",
                "avantia": df_prov["seccion_albaran"] == "avantia",
                "especialidad": df_prov["iva"] <= 4,
                "parafarmacia": df_prov["iva"] > 4,
                "club": df_prov["descripcion"].str.contains("club", case=False, na=False)
            }

        elif proveedor == "cofares":

            categorias = {
                "nexo": df_prov["seccion_albaran"] == "nexo",
                "transfer_diferido": df_prov["seccion_albaran"] == "bitransfer",
                "seleccion_genericos": df_prov["seccion_albaran"] == "seleccion_genericos",
                "especialidad": df_prov["iva"] <= 4,
                "parafarmacia": df_prov["iva"] > 4
            }

        else:

            categorias = {
                "otros": df_prov["seccion_albaran"].notna()
            }

        filas = []

        for nombre, filtro in categorias.items():

            df_temp = df_prov[filtro]

            bruto = df_temp["bruto"].sum()
            neto = df_temp["neto"].sum()

            descuento = 0
            if bruto > 0:
                descuento = (bruto - neto) / bruto * 100

            filas.append({
                "categoria": nombre,
                "n_lineas": len(df_temp),
                "unidades": df_temp["unidades"].sum(),
                "bruto": round(bruto, 2),
                "neto": round(neto, 2),
                "descuento_pct": round(descuento, 2)
            })

        resumen_tipo = pd.DataFrame(filas)
        st.dataframe(resumen_tipo)

# =========================
# 2. CONDICIONES PROVEEDORES
# =========================

if proveedores_detectados and df is not None:

    st.header("2️⃣ Condiciones y ajustes por proveedor")

    for proveedor in proveedores_detectados:

        st.subheader(f"⚙️ {proveedor.upper()}")

        if proveedor == "bidafarma":

            col1, col2 = st.columns(2)

            with col1:
                factura_transfer = st.file_uploader("Factura TRANSFER", type=["xlsx"], key="transfer_bida")

            with col2:
                factura_normal = st.file_uploader("Factura NORMAL", type=["xlsx"], key="normal_bida")

            # 1) Cargar facturas y construir resumen de albaranes
            resumenes = []
            cargos_detectados = []

            if factura_transfer:
                df_transfer = leer_factura(factura_transfer)
                resumen_transfer = extraer_albaranes_y_neto_factura(df_transfer)
                resumen_transfer["origen"] = "transfer"
                resumenes.append(resumen_transfer)

                cargos_transfer = detectar_cargos_factura(df_transfer)
                cargos_transfer["origen"] = "transfer"
                cargos_detectados.append(cargos_transfer)

            if factura_normal:
                df_normal = leer_factura(factura_normal)
                resumen_normal = extraer_albaranes_y_neto_factura(df_normal)
                resumen_normal["origen"] = "normal"
                resumenes.append(resumen_normal)

                cargos_normal = detectar_cargos_factura(df_normal)
                cargos_normal["origen"] = "normal"
                cargos_detectados.append(cargos_normal)

            # 2) Cruce de albaranes factura vs albaranes subidos en bloque 1
            if resumenes:
                resumen_facturas = pd.concat(resumenes, ignore_index=True)
                albaranes_factura = set(resumen_facturas["albaran"].astype(str).str.strip())

                df_bida = df[df["proveedor"] == "bidafarma"].copy()
                albaranes_subidos = set(df_bida["albaran"].astype(str).str.strip())

                faltan_en_subida = sorted(albaranes_factura - albaranes_subidos)
                faltan_en_factura = sorted(albaranes_subidos - albaranes_factura)

                st.markdown("#### 🔎 Chequeo de albaranes")
                c1, c2, c3 = st.columns(3)
                c1.metric("Albaranes factura", len(albaranes_factura))
                c2.metric("Albaranes subidos", len(albaranes_subidos))
                c3.metric("Diferencias", len(faltan_en_subida) + len(faltan_en_factura))

                if faltan_en_subida:
                    st.error("❌ Albaranes en factura que NO están en los albaranes subidos")
                    st.write(faltan_en_subida)

                if faltan_en_factura:
                    st.warning("⚠️ Albaranes subidos que NO aparecen en factura")
                    st.write(faltan_en_factura)

                if not faltan_en_subida and not faltan_en_factura:
                    st.success("✅ Cruce correcto: todos los albaranes coinciden")

                neto_facturas = resumen_facturas["neto"].sum()
                neto_albaranes = df_bida["neto"].sum()
                diferencia = neto_facturas - neto_albaranes

                st.info(
                    f"Neto facturas: {round(neto_facturas, 2)} € | "
                    f"Neto albaranes: {round(neto_albaranes, 2)} € | "
                    f"Diferencia: {round(diferencia, 2)} €"
                )

                st.dataframe(resumen_facturas)
            else:
                st.info("Sube al menos una factura de Bidafarma para ejecutar el chequeo de albaranes.")

            # 3) Detectar cargos (sin inputs manuales)
            if cargos_detectados:
                cargos_df = pd.concat(cargos_detectados, ignore_index=True)
                total_cargos = cargos_df["importe"].sum()

                st.markdown("#### 💶 Cargos detectados en factura")
                st.metric("Total cargos detectados (€)", round(total_cargos, 2))
                st.dataframe(cargos_df)
            else:
                cargos_df = pd.DataFrame(columns=["descripcion", "importe", "origen"])
                total_cargos = 0
                st.info("No se detectaron cargos en las facturas cargadas.")

            # Guardamos condiciones Bidafarma sin campos manuales
            condiciones["bidafarma"] = {
                "cargos_detectados_total": float(total_cargos),
                "cargos_detectados_detalle": cargos_df.to_dict("records"),
            }

        elif proveedor == "cofares":

            icc_file = st.file_uploader("ICC Cofares", type=["xlsx"], key="icc_cofares")

            base_icc = 0
            pct_franquicia = 0

            if icc_file:
                icc_df = pd.read_excel(icc_file)
                icc_df.columns = [c.lower().strip() for c in icc_df.columns]

                try:
                    base_icc = float(icc_df.loc[icc_df["concepto"] == "base icc", "valor"].values[0])
                    pct_franquicia = float(icc_df.loc[icc_df["concepto"] == "% franquicia", "valor"].values[0])
                    st.success(f"Base ICC: {base_icc} | % Franquicia: {pct_franquicia}")
                except Exception:
                    st.error("Error leyendo ICC")

            condiciones["cofares"] = {
                "base_icc": base_icc,
                "pct_franquicia": pct_franquicia
            }

# =========================
# 3. MOTOR DE COSTES
# =========================

if condiciones and df is not None:

    df_resultado = apply_costs(df.copy(), condiciones)

    st.header("3️⃣ Resultado con costes ajustados")
    st.dataframe(df_resultado)

# =========================
# ESTADO INICIAL
# =========================

if df is None:
    st.warning("⚠️ Sube al menos un archivo para empezar")
