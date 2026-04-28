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
import modules.avantia as avantia
import modules.faceta as faceta
import modules.condiciones_bidafarma as condiciones_bidafarma

bitransfer = importlib.reload(bitransfer)
servicios = importlib.reload(servicios)
avantia = importlib.reload(avantia)
faceta = importlib.reload(faceta)
condiciones_bidafarma = importlib.reload(condiciones_bidafarma)

PROVEEDORES_BASE = {
    "cofares": "cofares",
    "alliance": "alliance",
    "hefame": "hefame",
}

SECCIONES = [
    "bidafarma",
    "cofares",
    "alliance",
    "hefame",
    "Facturas laboratorios",
    "Ventas farmacia",
    "Resumen",
]


# =========================
# NORMALIZADOR GLOBAL
# =========================

def normalizar_albaran(valor):
    valor = str(valor).lower().strip()
    match = re.match(r"^[a-z]{0,3}-?\d+$", valor)

    if match:
        return re.sub(r"[^\d]", "", valor)

    return valor


def _guardar_dataset(clave, df):
    st.session_state[clave] = df


def _leer_albaranes_genericos(uploaded_files, proveedor, tipo_compra):
    dfs = []

    if not uploaded_files:
        return dfs

    for uploaded_file in uploaded_files:
        df_temp = normalize_columns(load_excel(uploaded_file))
        df_temp.columns = [c.lower().strip() for c in df_temp.columns]
        df_temp["proveedor"] = proveedor
        df_temp["tipo_compra"] = tipo_compra

        col_albaran = next((c for c in df_temp.columns if "albaran" in c), None)
        if col_albaran:
            df_temp["albaran"] = df_temp[col_albaran].apply(normalizar_albaran)

        df_temp = parse_sections(df_temp)
        dfs.append(df_temp)

    return dfs


def _mostrar_vistas_albaranes(df):
    if df is None:
        return

    for tipo in ["goteo", "transfer"]:
        df_tipo = df[df["tipo_compra"] == tipo].copy()

        if df_tipo.empty:
            continue

        titulo = "📦 Goteo" if tipo == "goteo" else "🚚 Transfer"
        st.header(f"{titulo}")

        st.dataframe(df_tipo)

        if "tipo" in df_tipo.columns:
            mask_faceta = df_tipo.apply(
                lambda row: faceta.es_linea_faceta(row.get("tipo"), row.get("descripcion")),
                axis=1,
            )
            df_tipo = df_tipo[~mask_faceta].copy()

        df_tipo["bruto"] = pd.to_numeric(df_tipo["bruto"], errors="coerce").fillna(0.0)
        df_tipo["neto"] = pd.to_numeric(df_tipo["neto"], errors="coerce").fillna(0.0)
        df_tipo["unidades"] = pd.to_numeric(df_tipo["unidades"], errors="coerce").fillna(0.0)
        df_tipo["es_abono"] = df_tipo["neto"] < 0
        abonos = df_tipo[df_tipo["es_abono"]]
        compras = df_tipo[~df_tipo["es_abono"]]

        total_bruto = compras["bruto"].sum()
        total_neto = compras["neto"].sum()
        total_abonos = abonos["neto"].sum()

        descuento = (total_bruto - total_neto) / total_bruto * 100 if total_bruto else 0

        c1, c2, c3, c4, c5, c6 = st.columns(6)

        c1.metric("Líneas", len(df_tipo))
        c2.metric("Unidades", int(df_tipo["unidades"].sum()))
        c3.metric("Bruto", f"{total_bruto:.1f} €")
        c4.metric("Neto", f"{total_neto:.1f} €")
        c5.metric("Desc %", round(descuento, 2))
        c6.metric("Abonos", f"{abs(total_abonos):.1f} €")


def _serie_numerica(df, columna):
    if df is None or columna not in df.columns:
        return pd.Series([0.0] * len(df), index=df.index if df is not None else None)
    return pd.to_numeric(df[columna], errors="coerce").fillna(0.0)


def _descuento_pct(bruto_total, coste_total):
    if bruto_total <= 0:
        return 0.0
    return round((1 - (coste_total / bruto_total)) * 100, 2)


def _lineas_elegibles_goteo_puro(df):
    if df is None or df.empty:
        return pd.DataFrame()

    detalle = df.copy()
    detalle["bruto"] = _serie_numerica(detalle, "bruto")
    detalle["neto"] = _serie_numerica(detalle, "neto")
    detalle["iva"] = _serie_numerica(detalle, "iva")
    detalle["descripcion"] = detalle.get("descripcion", "").astype(str)
    descripcion_norm = detalle["descripcion"].str.lower()

    mask = (
        detalle["tipo_compra"].eq("goteo")
        & detalle["seccion_albaran"].isin(["especialidad", "parafarmacia"])
        & ~detalle["neto"].lt(0)
        & ~descripcion_norm.str.contains("club", na=False)
        & ~descripcion_norm.str.contains("avantia", na=False)
        & ~descripcion_norm.str.contains("bitransfer|bittransfer", na=False)
    )

    return detalle[mask].copy()


def _analisis_ajuste_comercial_bidafarma(df, ajustes_comerciales, df_faceta=None):
    if df is None or df.empty or ajustes_comerciales is None or ajustes_comerciales.empty:
        return None

    if faceta.hay_cargo_tarifa(df_faceta):
        return None

    df_base = df.copy()
    df_base["bruto"] = _serie_numerica(df_base, "bruto")
    df_base["neto"] = _serie_numerica(df_base, "neto")
    df_base["iva"] = _serie_numerica(df_base, "iva")
    descripcion_norm = df_base.get("descripcion", "").astype(str).str.lower()

    mask_elegible = (
        df_base["tipo_compra"].eq("goteo")
        & df_base["iva"].eq(4)
        & df_base["seccion_albaran"].eq("especialidad")
        & (df_base["bruto"].abs() <= 96)
        & df_base["bruto"].ne(0)
        & ~descripcion_norm.str.contains("club", na=False)
        & ~descripcion_norm.str.contains("avantia", na=False)
        & ~descripcion_norm.str.contains("bitransfer|bittransfer", na=False)
    )

    elegibles = df_base[mask_elegible].copy()
    if elegibles.empty:
        return None

    base_compras = float(elegibles.loc[elegibles["bruto"] > 0, "bruto"].sum())
    base_abonos = float(elegibles.loc[elegibles["bruto"] < 0, "bruto"].sum())
    base_aplicacion = base_compras + base_abonos
    if base_aplicacion <= 0:
        return None

    descuento_total = abs(float(ajustes_comerciales["importe"].sum()))
    if descuento_total <= 0:
        return None

    descuento_pct = (descuento_total / base_aplicacion) * 100
    detalle = elegibles[elegibles["bruto"] > 0].copy()
    if detalle.empty:
        return None

    detalle["descuento_ajuste_comercial"] = detalle["bruto"] * (descuento_pct / 100)
    detalle["neto_con_ajuste_comercial"] = (
        detalle["neto"] - detalle["descuento_ajuste_comercial"]
    )
    detalle["descuento_ajuste_comercial"] = detalle["descuento_ajuste_comercial"].round(4)
    detalle["neto_con_ajuste_comercial"] = detalle["neto_con_ajuste_comercial"].round(4)

    return {
        "detalle": detalle,
        "resumen": {
            "descuento_total": round(descuento_total, 2),
            "base_aplicacion": round(base_aplicacion, 2),
            "base_compras": round(base_compras, 2),
            "base_abonos": round(base_abonos, 2),
            "descuento_pct": round(descuento_pct, 2),
            "lineas_afectadas": len(detalle),
        },
    }


def _analisis_cargo_adicional_gestion(df, importe_cargo):
    if df is None or df.empty or importe_cargo is None or abs(float(importe_cargo)) <= 0.05:
        return None

    detalle = _lineas_elegibles_goteo_puro(df)
    if detalle.empty:
        return None

    base_aplicacion = float(detalle["bruto"].abs().sum())
    if base_aplicacion <= 0:
        return None

    cargo_total = abs(float(importe_cargo))
    detalle["cargo_gestion_adicional"] = (
        detalle["bruto"].abs() / base_aplicacion
    ) * cargo_total
    detalle["neto_con_gestion_adicional"] = (
        detalle["neto"] + detalle["cargo_gestion_adicional"]
    )
    detalle["cargo_gestion_adicional"] = detalle["cargo_gestion_adicional"].round(4)
    detalle["neto_con_gestion_adicional"] = detalle["neto_con_gestion_adicional"].round(4)

    return {
        "detalle": detalle,
        "resumen": {
            "cargo_total": round(cargo_total, 2),
            "base_cargo": round(cargo_total * 0.076, 2),
            "base_aplicacion": round(base_aplicacion, 2),
            "lineas_afectadas": len(detalle),
        },
    }


def _resumen_bidafarma(
    df,
    analisis_faceta=None,
    resumen_bitransfer=None,
    analisis_avantia=None,
    analisis_ajuste=None,
    analisis_cargo_adicional=None,
):
    if df is None or df.empty:
        return None

    df_resumen = df.copy()
    if "tipo" in df_resumen.columns:
        mask_faceta = df_resumen.apply(
            lambda row: faceta.es_linea_faceta(row.get("tipo"), row.get("descripcion")),
            axis=1,
        )
        df_resumen = df_resumen[~mask_faceta].copy()

    df_resumen["bruto"] = _serie_numerica(df_resumen, "bruto")
    df_resumen["neto"] = _serie_numerica(df_resumen, "neto")
    df_resumen["unidades"] = _serie_numerica(df_resumen, "unidades")

    compras = df_resumen[df_resumen["neto"] >= 0].copy()
    if compras.empty:
        return None

    descripcion_norm = compras.get("descripcion", "").astype(str).str.lower()

    mask_bitransfer = compras["seccion_albaran"].eq("bitransfer")
    mask_club = compras["seccion_albaran"].eq("club")
    mask_avantia = compras["seccion_albaran"].eq("avantia") | descripcion_norm.str.contains("avantia", na=False)
    mask_goteo_puro = (
        compras["tipo_compra"].eq("goteo")
        & compras["seccion_albaran"].isin(["especialidad", "parafarmacia"])
        & ~mask_bitransfer
        & ~mask_club
        & ~mask_avantia
    )
    mask_especialidad_normal = (
        mask_goteo_puro
        & compras["seccion_albaran"].eq("especialidad")
        & compras["bruto"].abs().le(96)
    )
    mask_transfer = compras["tipo_compra"].eq("transfer")

    resumen_bloques = []

    def agregar_bloque(nombre, mask, coste_extra=0.0):
        bloque = compras[mask].copy()
        if bloque.empty:
            return None

        bruto = float(bloque["bruto"].sum())
        neto = float(bloque["neto"].sum())
        coste_real = neto + coste_extra
        descuento = _descuento_pct(bruto, coste_real)
        resumen_bloques.append({
            "bloque": nombre,
            "bruto_compra": round(bruto, 2),
            "neto_inicial": round(neto, 2),
            "coste_ajustado": round(coste_real, 2),
            "descuento_medio_pct": descuento,
        })
        return {"bruto": bruto, "neto": neto, "coste": coste_real, "descuento": descuento}

    bloque_goteo_puro = agregar_bloque(
        "Goteo puro",
        mask_goteo_puro,
        coste_extra=(
            (0.0 if not analisis_faceta else analisis_faceta["resumen"]["margen_tramo_fijo_total"])
            + (0.0 if not analisis_cargo_adicional else analisis_cargo_adicional["resumen"]["cargo_total"])
            - (0.0 if not analisis_ajuste else analisis_ajuste["resumen"]["descuento_total"])
        ),
    )
    bloque_especialidad = agregar_bloque(
        "Especialidad normal",
        mask_especialidad_normal,
        coste_extra=(
            (0.0 if not analisis_faceta else float(
                analisis_faceta["detalle_tramo_fijo"]
                .loc[analisis_faceta["detalle_tramo_fijo"]["seccion_albaran"] == "especialidad", "cargo_faceta_tramo_fijo"]
                .sum()
            ))
            + (0.0 if not analisis_cargo_adicional else float(
                analisis_cargo_adicional["detalle"]
                .loc[analisis_cargo_adicional["detalle"]["seccion_albaran"] == "especialidad", "cargo_gestion_adicional"]
                .sum()
            ))
            - (0.0 if not analisis_ajuste else analisis_ajuste["resumen"]["descuento_total"])
        ),
    )
    bloque_parafarmacia = agregar_bloque(
        "Parafarmacia normal",
        mask_goteo_puro & compras["seccion_albaran"].eq("parafarmacia"),
        coste_extra=(
            (0.0 if not analisis_faceta else float(
                analisis_faceta["detalle_tramo_fijo"]
                .loc[analisis_faceta["detalle_tramo_fijo"]["seccion_albaran"] == "parafarmacia", "cargo_faceta_tramo_fijo"]
                .sum()
            ))
            + (0.0 if not analisis_cargo_adicional else float(
                analisis_cargo_adicional["detalle"]
                .loc[analisis_cargo_adicional["detalle"]["seccion_albaran"] == "parafarmacia", "cargo_gestion_adicional"]
                .sum()
            ))
        ),
    )
    bloque_bitransfer = agregar_bloque(
        "Bitransfer",
        mask_bitransfer,
        coste_extra=0.0 if not resumen_bitransfer else (
            resumen_bitransfer["coste_real_total_compras"] - resumen_bitransfer["importe_neto_compras"]
        ),
    )
    bloque_transfer = agregar_bloque("Transfer", mask_transfer)
    bloque_club = agregar_bloque(
        "Clubes",
        mask_club,
        coste_extra=0.0 if not analisis_faceta or analisis_faceta["detalle_liquidaciones"].empty else float(
            analisis_faceta["detalle_liquidaciones"]["liquidacion_faceta_linea"].sum()
        ),
    )
    bloque_avantia = agregar_bloque(
        "Avantia",
        mask_avantia,
        coste_extra=0.0 if not analisis_avantia else float(analisis_avantia["resumen"]["coste_total_avantia"] - analisis_avantia["resumen"]["cuota_avantia"] - compras[mask_avantia]["neto"].sum()),
    )

    total_bidafarma_bruto = float(compras["bruto"].sum())

    resumen_textual = []
    if bloque_goteo_puro:
        descuento_inicial_goteo = _descuento_pct(bloque_goteo_puro["bruto"], bloque_goteo_puro["neto"])
        if analisis_faceta and analisis_faceta["resumen"]["margen_tramo_fijo_total"] > 0:
            resumen_textual.append(
                f"Hay un cargo de tramo fijo de {analisis_faceta['resumen']['margen_tramo_fijo_total']:.2f} € "
                f"que reduce el descuento medio del goteo puro desde {descuento_inicial_goteo:.2f}% "
                f"hasta {bloque_goteo_puro['descuento']:.2f}%."
            )
        if analisis_ajuste:
            resumen_textual.append(
                f"Se ha aplicado un ajuste comercial de {analisis_ajuste['resumen']['descuento_total']:.2f} € "
                f"sobre una base elegible de {analisis_ajuste['resumen']['base_aplicacion']:.2f} €, "
                f"equivalente a un {analisis_ajuste['resumen']['descuento_pct']:.2f}%."
            )
        if analisis_cargo_adicional:
            resumen_textual.append(
                f"Hay un gasto adicional de gestión de {analisis_cargo_adicional['resumen']['cargo_total']:.2f} € "
                f"repartido sobre una base elegible de {analisis_cargo_adicional['resumen']['base_aplicacion']:.2f} €."
            )

    if analisis_faceta and not analisis_faceta["resumen_liquidaciones"].empty:
        for _, fila in analisis_faceta["resumen_liquidaciones"].iterrows():
            resumen_textual.append(
                f"Se ha detectado {fila['concepto']} por {fila['importe_liquidacion']:.2f} €, "
                f"equivalente a un {fila['pct_liquidacion']:.2f}% sobre una base de {fila['base_liquidacion']:.2f} €."
            )

    return {
        "tabla": pd.DataFrame(resumen_bloques),
        "resumen_textual": resumen_textual,
        "metricas": {
            "total_bidafarma_bruto": round(total_bidafarma_bruto, 2),
            "goteo_puro_descuento_real": None if not bloque_goteo_puro else bloque_goteo_puro["descuento"],
            "bitransfer_descuento_real": None if not bloque_bitransfer else bloque_bitransfer["descuento"],
            "transfer_descuento_real": None if not bloque_transfer else bloque_transfer["descuento"],
            "club_descuento_real": None if not bloque_club else bloque_club["descuento"],
            "avantia_descuento_real": None if not bloque_avantia else bloque_avantia["descuento"],
        },
    }


def _render_subida_albaranes_base(nombre_proveedor, proveedor_id):
    st.header("1️⃣ Subida de albaranes")

    col1, col2 = st.columns(2)

    with col1:
        uploaded_files = st.file_uploader(
            f"📦 Albaranes {nombre_proveedor} (goteo)",
            type=["xlsx"],
            accept_multiple_files=True,
            key=f"{proveedor_id}_albaranes_goteo",
        )

    with col2:
        uploaded_transfer = st.file_uploader(
            f"🚚 Albaranes {nombre_proveedor} TRANSFER",
            type=["xlsx"],
            accept_multiple_files=True,
            key=f"{proveedor_id}_albaranes_transfer",
        )

    dfs = []
    dfs.extend(_leer_albaranes_genericos(uploaded_files, proveedor_id, "goteo"))
    dfs.extend(_leer_albaranes_genericos(uploaded_transfer, proveedor_id, "transfer"))

    df = pd.concat(dfs, ignore_index=True) if dfs else None
    _guardar_dataset(f"df_{proveedor_id}", df)
    _mostrar_vistas_albaranes(df)

    return df


def render_proveedor_base(nombre_proveedor, proveedor_id):
    df = _render_subida_albaranes_base(nombre_proveedor, proveedor_id)

    st.header("2️⃣ Facturas")

    factura_normal = st.file_uploader(
        "Factura NORMAL",
        type=["xlsx"],
        key=f"{proveedor_id}_factura_normal",
    )
    factura_transfer = st.file_uploader(
        "Factura TRANSFER",
        type=["xlsx"],
        key=f"{proveedor_id}_factura_transfer",
    )

    st.session_state[f"factura_normal_{proveedor_id}"] = factura_normal.name if factura_normal else None
    st.session_state[f"factura_transfer_{proveedor_id}"] = factura_transfer.name if factura_transfer else None

    if factura_normal:
        st.success(f"Factura NORMAL de {nombre_proveedor} cargada: {factura_normal.name}")
    if factura_transfer:
        st.success(f"Factura TRANSFER de {nombre_proveedor} cargada: {factura_transfer.name}")

    if df is None:
        st.warning("Sube archivos")


def render_facturas_laboratorios():
    st.header("Facturas de laboratorios")
    archivos = st.file_uploader(
        "Sube facturas de laboratorios",
        type=["xlsx"],
        accept_multiple_files=True,
        key="facturas_laboratorios_excel",
    )
    st.session_state["facturas_laboratorios"] = [archivo.name for archivo in archivos] if archivos else []

    if archivos:
        st.success(f"{len(archivos)} archivo(s) de laboratorios cargado(s).")
        st.dataframe(pd.DataFrame({"archivo": [archivo.name for archivo in archivos]}))
    else:
        st.info("Sube aquí los Excel de facturas de laboratorios. Más adelante añadiremos su lectura específica.")


def render_ventas_farmacia():
    st.header("Ventas farmacia")
    archivos = st.file_uploader(
        "Sube ventas de la farmacia",
        type=["xlsx"],
        accept_multiple_files=True,
        key="ventas_farmacia_excel",
    )
    st.session_state["ventas_farmacia"] = [archivo.name for archivo in archivos] if archivos else []

    if archivos:
        st.success(f"{len(archivos)} archivo(s) de ventas cargado(s).")
        st.dataframe(pd.DataFrame({"archivo": [archivo.name for archivo in archivos]}))
    else:
        st.info("Sube aquí los Excel de ventas de la farmacia. Más adelante añadiremos su normalización.")


def render_resumen():
    st.header("Resumen")

    filas = []
    for nombre, proveedor_id in {"bidafarma": "bidafarma", **PROVEEDORES_BASE}.items():
        df_proveedor = st.session_state.get(f"df_{proveedor_id}")
        filas.append({
            "seccion": nombre,
            "lineas_albaranes": 0 if df_proveedor is None else len(df_proveedor),
            "factura_normal": st.session_state.get(f"factura_normal_{proveedor_id}") or "",
            "factura_transfer": st.session_state.get(f"factura_transfer_{proveedor_id}") or "",
        })

    filas.append({
        "seccion": "Facturas laboratorios",
        "lineas_albaranes": len(st.session_state.get("facturas_laboratorios", [])),
        "factura_normal": "",
        "factura_transfer": "",
    })
    filas.append({
        "seccion": "Ventas farmacia",
        "lineas_albaranes": len(st.session_state.get("ventas_farmacia", [])),
        "factura_normal": "",
        "factura_transfer": "",
    })

    st.dataframe(pd.DataFrame(filas))
    st.info("Este resumen queda preparado como punto de salida. En los siguientes pasos añadiremos los indicadores y la descarga Excel final.")


def render_vida_pharma():
    df = None
    faceta_frames = []
    analisis_faceta = None
    analisis_avantia = None
    analisis_ajuste = None
    analisis_cargo_adicional = None
    resumen_conciliacion_bitransfer = None
    condicion_detectada = None

    # =========================
    # 1. ALBARANES
    # =========================

    st.header("1️⃣ Subida de albaranes")

    col1, col2 = st.columns(2)

    with col1:
        uploaded_files = st.file_uploader(
            "📦 Albaranes BIDAFARMA (goteo)",
            type=["xlsx"],
            accept_multiple_files=True,
            key="bidafarma_albaranes_goteo"
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
            df_faceta_temp = faceta.leer_albaran_faceta_v(uploaded_file)
            if df_faceta_temp is not None:
                faceta_frames.append(df_faceta_temp)
                continue

            if hasattr(uploaded_file, "seek"):
                uploaded_file.seek(0)

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

    _guardar_dataset("df_bidafarma", df)
    df_faceta_bidafarma = pd.concat(faceta_frames, ignore_index=True) if faceta_frames else pd.DataFrame()
    if df is not None:
        df_faceta_lineas = faceta.extraer_faceta_desde_lineas(df)
        if not df_faceta_lineas.empty:
            df_faceta_bidafarma = pd.concat([df_faceta_bidafarma, df_faceta_lineas], ignore_index=True)
            df_faceta_bidafarma = df_faceta_bidafarma.drop_duplicates(subset=["concepto", "importe"], keep="last")
    _guardar_dataset("df_faceta_bidafarma", df_faceta_bidafarma)
    condicion_detectada = condiciones_bidafarma.detectar_condicion(df, df_faceta_bidafarma)

    # =========================
    # VISTAS
    # =========================

    if df is not None:
        _mostrar_vistas_albaranes(df)

    if condicion_detectada:
        st.subheader("🧭 Condición detectada")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Nombre", condicion_detectada["nombre"])
        c2.metric("Acrónimo", condicion_detectada["acronimo"])
        c3.metric(
            "Albarán 74",
            "Sí" if condicion_detectada["albaran_74"] == "si" else condicion_detectada["albaran_74"].replace("_", " "),
        )
        c4.metric(
            "Ajuste comercial",
            "Sí" if condicion_detectada["ajuste_comercial_factura"] else "No",
        )

    if not df_faceta_bidafarma.empty:
        titulo_tarifa = "Albarán TP 74"
        if condicion_detectada:
            solo_liquidaciones = (
                condicion_detectada["albaran_74"] == "solo_liquidaciones"
                and not faceta.hay_cargo_tarifa(df_faceta_bidafarma)
            )
            if solo_liquidaciones:
                titulo_tarifa = f"Liquidaciones TP 74 · {condicion_detectada['nombre']} ({condicion_detectada['acronimo']})"
            else:
                titulo_tarifa = f"Tarifa {condicion_detectada['acronimo']} · {condicion_detectada['nombre']}"
        st.header(f"🧾 {titulo_tarifa}")

        analisis_faceta = faceta.analizar_faceta_v(df, df_faceta_bidafarma) if df is not None else None

        if analisis_faceta:
            resumen_faceta = analisis_faceta["resumen"]

            f1, f2, f3, f4, f5, f6 = st.columns(6)
            f1.metric(
                "Tipo albarán 74",
                condiciones_bidafarma.nombre_tipo_74(resumen_faceta.get("tipo_albaran_74")) or "-",
            )
            f2.metric("Cargo tarifa", f"{resumen_faceta['margen_tramo_fijo_total']:.2f} €")
            f3.metric("Base tramo fijo", f"{resumen_faceta['base_tramo_fijo']:.2f} €")
            f4.metric("Base de aplicación", f"{resumen_faceta['base_aplicacion']:.2f} €")
            f5.metric("Liquidaciones", f"{resumen_faceta['liquidaciones_total']:.2f} €")
            f6.metric("Líneas afectadas", resumen_faceta["lineas_tramo_fijo"] + resumen_faceta["lineas_liquidaciones"])

            st.caption("Conceptos detectados en albaranes TP 74")
            st.dataframe(
                analisis_faceta["conceptos"][
                    [col for col in ["fecha", "hora", "tp", "concepto", "importe"] if col in analisis_faceta["conceptos"].columns]
                ]
            )

            if not analisis_faceta["detalle_tramo_fijo"].empty:
                st.caption("Imputación margen tramo fijo sobre goteo elegible")
                st.dataframe(
                    analisis_faceta["detalle_tramo_fijo"][
                        [
                            col for col in [
                                "cn",
                                "descripcion",
                                "seccion_albaran",
                                "unidades",
                                "bruto",
                                "neto",
                                "cargo_faceta_tramo_fijo",
                                "neto_con_faceta_tramo_fijo",
                            ]
                            if col in analisis_faceta["detalle_tramo_fijo"].columns
                        ]
                    ]
                )

            if not analisis_faceta["resumen_liquidaciones"].empty:
                st.caption("Resumen de liquidaciones detectadas")
                st.dataframe(analisis_faceta["resumen_liquidaciones"])

            if not analisis_faceta["detalle_liquidaciones"].empty:
                st.caption("Imputación de liquidaciones por club/laboratorio")
                st.dataframe(
                    analisis_faceta["detalle_liquidaciones"][
                        [
                            col for col in [
                                "grupo_liquidacion",
                                "cn",
                                "descripcion",
                                "unidades",
                                "bruto",
                                "neto",
                                "pct_liquidacion",
                                "liquidacion_faceta_linea",
                                "neto_con_liquidacion",
                            ]
                            if col in analisis_faceta["detalle_liquidaciones"].columns
                        ]
                    ]
                )
        else:
            st.dataframe(df_faceta_bidafarma)
            st.info("Se ha detectado un albarán TP 74, pero todavía no hay líneas de compra goteo sobre las que imputar cargos o liquidaciones.")

    # =========================
    # 2. FACTURAS
    # =========================

    if df is not None:

        st.header("2️⃣ Facturas")

        # -------------------------
        # FACTURA NORMAL
        # -------------------------
        factura_normal = st.file_uploader("Factura NORMAL", type=["xlsx"], key="bidafarma_factura_normal")
        st.session_state["factura_normal_bidafarma"] = factura_normal.name if factura_normal else None

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

            ajustes_comerciales = resultado.get("ajustes_comerciales", pd.DataFrame())
            permite_ajuste = condicion_detectada is None or condicion_detectada["ajuste_comercial_factura"]
            analisis_ajuste = (
                _analisis_ajuste_comercial_bidafarma(df, ajustes_comerciales, df_faceta_bidafarma)
                if permite_ajuste else None
            )

            if analisis_ajuste:
                resumen_ajuste = analisis_ajuste["resumen"]
                st.subheader("📉 Ajuste comercial en factura")

                ac1, ac2, ac3, ac4 = st.columns(4)
                ac1.metric("Descuento factura", f"{resumen_ajuste['descuento_total']:.2f} €")
                ac2.metric("Base aplicación", f"{resumen_ajuste['base_aplicacion']:.2f} €")
                ac3.metric("Descuento %", f"{resumen_ajuste['descuento_pct']:.2f}%")
                ac4.metric("Líneas afectadas", resumen_ajuste["lineas_afectadas"])

                st.caption("Imputación del ajuste comercial sobre especialidad IVA 4 elegible")
                st.dataframe(
                    analisis_ajuste["detalle"][
                        [
                            col for col in [
                                "cn",
                                "descripcion",
                                "bruto",
                                "neto",
                                "descuento_ajuste_comercial",
                                "neto_con_ajuste_comercial",
                            ]
                            if col in analisis_ajuste["detalle"].columns
                        ]
                    ]
                )

            analisis_servicios = servicios.analizar_gastos_servicios(df, resultado["gastos"])

            if analisis_servicios and analisis_servicios["resumen"]["servicios_factura"] > 0:
                st.subheader("🧾 Imputación gastos por servicios")

                resumen_servicios = analisis_servicios["resumen"]

                s1, s2, s3, s4, s5, s6 = st.columns(6)
                s1.metric("Avantia", "Sí" if resumen_servicios["tiene_avantia"] else "No")
                s2.metric("Cargo bidanatural", f"{resumen_servicios['cargo_pct_vida_natural']:.1f}%")
                s3.metric("Servicios factura", f"{resumen_servicios['servicios_factura']:.2f} €")
                s4.metric("bidanatural", f"{resumen_servicios['cargo_vida_natural']:.2f} €")
                s5.metric("Dif. servicios", f"{resumen_servicios['diferencia_servicios']:.2f} €")
                s6.metric("Devoluciones", f"{resumen_servicios['cargo_devoluciones']:.2f} €")

                if abs(resumen_servicios["diferencia_servicios"]) <= 0.05:
                    st.success("Los servicios de factura cuadran con el cargo calculado de bidanatural.")
                elif resumen_servicios["diferencia_servicios"] > 0:
                    st.warning(
                        "Hay importe de servicios no cubierto por bidanatural. "
                        "Se imputa como posible cargo por devoluciones sobre abonos."
                    )
                    if resumen_servicios.get("devoluciones_cuadran"):
                        st.success(
                            "La diferencia de servicios coincide exactamente con el cargo calculado "
                            "por devoluciones/abonos."
                        )
                else:
                    st.warning(
                        "El cargo calculado de bidanatural supera el importe de servicios de factura. "
                        "Revisa las líneas con observación B o la condición Avantia."
                    )

                if not analisis_servicios["detalle"].empty:
                    st.caption("Resumen detallado de líneas afectadas por servicios")
                    st.dataframe(analisis_servicios["detalle"])

                if not analisis_servicios["imputacion_devoluciones"].empty:
                    st.caption("Imputación de devoluciones a compras del mismo código nacional")
                    st.dataframe(analisis_servicios["imputacion_devoluciones"])

                if not analisis_servicios["pendiente_otros_gastos"].empty:
                    st.caption("Devoluciones pendientes para imputar más adelante como otros gastos")
                    st.dataframe(analisis_servicios["pendiente_otros_gastos"])

            resumen = resultado.get("resumen_costes")

            if resumen:
                st.subheader("💰 Coste total factura normal")

                col1, col2, col3 = st.columns(3)

                col1.metric("Base", f"{resumen['base']} €")
                col2.metric("IVA (21%)", f"{resumen['iva']} €")
                col3.metric("TOTAL", f"{resumen['total']} €")

            hay_avantia_detectada = avantia.hay_avantia(df, resultado["gastos"])

            if hay_avantia_detectada:
                st.subheader("🧾 Desglose Avantia")

                excel_avantia = st.file_uploader(
                    "Cuadro rentabilidad Avantia",
                    type=["xlsx"],
                    key="avantia_rentabilidad_excel"
                )

                if excel_avantia:
                    try:
                        cargos_avantia = avantia.leer_cuadro_rentabilidad_avantia(excel_avantia)
                        analisis_avantia = avantia.analizar_avantia(df, resultado["gastos"], cargos_avantia)

                        if analisis_avantia:
                            resumen_avantia = analisis_avantia["resumen"]

                            a1, a2, a3, a4, a5, a6 = st.columns(6)
                            a1.metric("Gasto esp.", f"{resumen_avantia['cargo_especialidad']:.2f} €")
                            a2.metric("Gasto paraf.", f"{resumen_avantia['cargo_parafarmacia']:.2f} €")
                            a3.metric("Bonif. esp.", f"{resumen_avantia['bonificacion_especialidad']:.2f} €")
                            a4.metric("Bonif. paraf.", f"{resumen_avantia['bonificacion_parafarmacia']:.2f} €")
                            a5.metric("Cuota Avantia", f"{resumen_avantia['cuota_avantia']:.2f} €")
                            a6.metric("Coste total", f"{resumen_avantia['coste_total_avantia']:.2f} €")

                            if not analisis_avantia["cargos"].empty:
                                st.caption("Cargos detectados en cuadro rentabilidad Avantia")
                                st.dataframe(analisis_avantia["cargos"])

                            if not analisis_avantia["detalle"].empty:
                                st.caption("Resumen detallado de artículos Avantia")
                                st.dataframe(analisis_avantia["detalle"])
                            else:
                                st.info(
                                    "Se ha detectado Avantia, pero no hay líneas de albarán con Avantia "
                                    "en la descripción para imputar cargos."
                                )

                    except ValueError as error:
                        st.error(f"No se pudo leer el cuadro rentabilidad Avantia: {error}")
                else:
                    st.info(
                        "Se ha detectado Avantia por factura o albaranes. "
                        "Sube el cuadro rentabilidad Avantia para calcular los gastos de especialidad/parafarmacia "
                        "y prorratear la cuota."
                    )

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
                        resumen_conciliacion_bitransfer = resumen_conciliacion

                        st.subheader("✅ Conciliación BitTransfer")

                        c1, c2, c3, c4, c5, c6 = st.columns(6)
                        c1.metric("Bruto resumen", f"{resumen_conciliacion['venta_bruta_resumen']:.2f} €")
                        c2.metric("Bruto compras", f"{resumen_conciliacion['venta_bruta_compras']:.2f} €")
                        c3.metric("Diferencia bruto", f"{resumen_conciliacion['diferencia_venta_bruta']:.2f} €")
                        c4.metric("Cargo resumen", f"{resumen_conciliacion['cargo_resumen']:.2f} €")
                        c5.metric("Cargo teórico", f"{resumen_conciliacion['cargo_teorico_compras']:.2f} €")
                        c6.metric("Dif. cargo", f"{resumen_conciliacion['diferencia_cargo']:.2f} €")

                        if analisis_avantia:
                            gestion_factura = float(resultado["gastos"].loc[
                                resultado["gastos"]["tipo"] == "gestion",
                                "importe"
                            ].sum())
                            cargo_bitransfer = resumen_conciliacion["cargo_resumen"]
                            cargo_avantia = analisis_avantia["resumen"]["cargo_total"]
                            gestion_calculada = cargo_bitransfer + cargo_avantia
                            diferencia_gestion = gestion_factura - gestion_calculada

                            st.subheader("🧮 Conciliación gastos de gestión")

                            g1, g2, g3, g4 = st.columns(4)
                            g1.metric("Gestión factura", f"{gestion_factura:.2f} €")
                            g2.metric("BitTransfer", f"{cargo_bitransfer:.2f} €")
                            g3.metric("Avantia", f"{cargo_avantia:.2f} €")
                            g4.metric("Diferencia", f"{diferencia_gestion:.2f} €")

                            if abs(diferencia_gestion) > 0.05:
                                st.warning(
                                    "Los gastos de gestión no cuadran exactamente con BitTransfer + Avantia. "
                                    "Revisa que el cuadro de consumos y el cuadro rentabilidad Avantia correspondan al mismo periodo."
                                )

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

            if resultado is not None and not resultado["gastos"].empty:
                gestion_factura = float(resultado["gastos"].loc[
                    resultado["gastos"]["tipo"] == "gestion",
                    "importe"
                ].sum())
                cargo_bitransfer = (
                    0.0 if not resumen_conciliacion_bitransfer else resumen_conciliacion_bitransfer["cargo_resumen"]
                )
                cargo_avantia = 0.0 if not analisis_avantia else analisis_avantia["resumen"]["cargo_total"]
                gestion_calculada = cargo_bitransfer + cargo_avantia
                diferencia_gestion = gestion_factura - gestion_calculada

                if gestion_factura > 0 and (cargo_bitransfer > 0 or cargo_avantia > 0 or condicion_detectada):
                    st.subheader("🧮 Conciliación global gastos de gestión")

                    g1, g2, g3, g4 = st.columns(4)
                    g1.metric("Gestión factura", f"{gestion_factura:.2f} €")
                    g2.metric("BitTransfer", f"{cargo_bitransfer:.2f} €")
                    g3.metric("Avantia", f"{cargo_avantia:.2f} €")
                    g4.metric("Diferencia", f"{diferencia_gestion:.2f} €")

                if (
                    condicion_detectada
                    and condicion_detectada["cargo_adicional_gestion"]
                    and diferencia_gestion > 0.05
                ):
                    analisis_cargo_adicional = _analisis_cargo_adicional_gestion(df, diferencia_gestion)

                    if analisis_cargo_adicional:
                        st.warning(
                            "Los gastos de gestión incluyen un cargo adicional no explicado por BitTransfer/Avantia. "
                            "Se reparte como franquicia sobre el goteo elegible."
                        )
                        resumen_cargo_adicional = analisis_cargo_adicional["resumen"]
                        ca1, ca2, ca3, ca4 = st.columns(4)
                        ca1.metric("Cargo adicional", f"{resumen_cargo_adicional['cargo_total']:.2f} €")
                        ca2.metric("Base tramo fijo", f"{resumen_cargo_adicional['base_cargo']:.2f} €")
                        ca3.metric("Base de aplicación", f"{resumen_cargo_adicional['base_aplicacion']:.2f} €")
                        ca4.metric("Líneas afectadas", resumen_cargo_adicional["lineas_afectadas"])

                        st.caption("Imputación del cargo adicional de gestión")
                        st.dataframe(
                            analisis_cargo_adicional["detalle"][
                                [
                                    col for col in [
                                        "cn",
                                        "descripcion",
                                        "seccion_albaran",
                                        "bruto",
                                        "neto",
                                        "cargo_gestion_adicional",
                                        "neto_con_gestion_adicional",
                                    ]
                                    if col in analisis_cargo_adicional["detalle"].columns
                                ]
                            ]
                        )

        # -------------------------
        # FACTURA TRANSFER
        # -------------------------
        factura_transfer = st.file_uploader("Factura TRANSFER", type=["xlsx"], key="bidafarma_factura_transfer")
        st.session_state["factura_transfer_bidafarma"] = factura_transfer.name if factura_transfer else None

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
        return

    st.header("📌 Resumen Bidafarma")
    analisis_faceta_final = faceta.analizar_faceta_v(df, df_faceta_bidafarma) if not df_faceta_bidafarma.empty else None
    resumen_final = _resumen_bidafarma(
        df,
        analisis_faceta=analisis_faceta_final,
        resumen_bitransfer=resumen_conciliacion_bitransfer,
        analisis_avantia=analisis_avantia,
        analisis_ajuste=analisis_ajuste,
        analisis_cargo_adicional=analisis_cargo_adicional,
    )

    if resumen_final:
        metricas = resumen_final["metricas"]
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Compra total Bidafarma", f"{metricas['total_bidafarma_bruto']:.2f} €")
        r2.metric(
            "Desc. real goteo puro",
            "-" if metricas["goteo_puro_descuento_real"] is None else f"{metricas['goteo_puro_descuento_real']:.2f}%",
        )
        r3.metric(
            "Desc. real Bitransfer",
            "-" if metricas["bitransfer_descuento_real"] is None else f"{metricas['bitransfer_descuento_real']:.2f}%",
        )
        r4.metric(
            "Desc. real Transfer",
            "-" if metricas["transfer_descuento_real"] is None else f"{metricas['transfer_descuento_real']:.2f}%",
        )

        if resumen_final["resumen_textual"]:
            for texto in resumen_final["resumen_textual"]:
                st.info(texto)

        if not resumen_final["tabla"].empty:
            st.caption("Resumen de compras y descuentos reales por bloque")
            st.dataframe(resumen_final["tabla"])


st.set_page_config(layout="wide")
st.title("📊 Auditoría de Compras Farmacia")

seccion_activa = st.radio(
    "Selecciona el apartado de trabajo",
    SECCIONES,
    horizontal=True,
    label_visibility="collapsed",
)

st.divider()

if seccion_activa == "bidafarma":
    render_vida_pharma()
elif seccion_activa in PROVEEDORES_BASE:
    render_proveedor_base(seccion_activa, PROVEEDORES_BASE[seccion_activa])
elif seccion_activa == "Facturas laboratorios":
    render_facturas_laboratorios()
elif seccion_activa == "Ventas farmacia":
    render_ventas_farmacia()
elif seccion_activa == "Resumen":
    render_resumen()
