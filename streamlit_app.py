from __future__ import annotations

import re
from typing import Iterable

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Auditoría de Compras Farmacia", page_icon="💊", layout="wide")

REQUIRED_COLUMNS = [
    "cn",
    "descripcion",
    "unidades",
    "bruto",
    "neto",
    "iva",
    "descuento",
    "proveedor",
    "seccion_albaran",
    "albaran",
]

COLUMN_ALIASES = {
    "cn": ["cn", "codigo nacional", "cod_nacional", "codigo", "c.n."],
    "descripcion": ["descripcion", "descripción", "producto", "articulo", "artículo"],
    "unidades": ["unidades", "uds", "cantidad", "cant"],
    "bruto": ["bruto", "importe_bruto", "pvb", "total_bruto"],
    "neto": ["neto", "importe_neto", "pvp_neto", "total_neto"],
    "iva": ["iva", "tipo_iva", "impuesto", "impuestos"],
    "descuento": ["descuento", "dto", "%dto", "descuento_%"],
    "proveedor": ["proveedor", "almacen", "mayorista", "distribuidor"],
    "seccion_albaran": ["seccion_albaran", "seccion", "sección", "linea", "línea", "familia"],
    "albaran": ["albaran", "albarán", "num_albaran", "numero_albaran", "documento"],
}


BIDAFARMA_RULES = {
    "bitransfer": ["bitransfer", "bi transfer", "transfer bi"],
    "avantia": ["avantia"],
    "especialidad": ["especialidad", "esp", "receta"],
    "parafarmacia": ["parafarmacia", "parafarma", "cosmetica", "cosmética"],
    "club": ["club", "fidelizacion", "fidelización"],
}

COFARES_RULES = {
    "nexo": ["nexo"],
    "transfer_diferido": ["transfer_diferido", "transfer diferido", "diferido"],
    "especialidad": ["especialidad", "esp", "receta"],
    "parafarmacia": ["parafarmacia", "parafarma", "cosmetica", "cosmética"],
}

CHARGE_KEYWORDS = [
    "cargo",
    "portes",
    "servicio",
    "cuota",
    "ajuste",
    "regularizacion",
    "financiero",
    "comision",
    "comisión",
]

TAX_KEYWORDS = ["iva", "recargo", "equivalencia", "igic"]


def normalize_text(value: object) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
    return re.sub(r"\s+", " ", text)


def to_number(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.replace("€", "", regex=False)
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
        .str.replace(" ", "", regex=False)
    )
    return pd.to_numeric(cleaned, errors="coerce").fillna(0.0)


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    renamed = df.copy()
    column_map: dict[str, str] = {}
    normalized_source = {normalize_text(c): c for c in renamed.columns}

    for target, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            alias_norm = normalize_text(alias)
            if alias_norm in normalized_source:
                column_map[normalized_source[alias_norm]] = target
                break

    renamed = renamed.rename(columns=column_map)

    for col in REQUIRED_COLUMNS:
        if col not in renamed.columns:
            renamed[col] = ""

    for num_col in ["unidades", "bruto", "neto", "iva", "descuento"]:
        renamed[num_col] = to_number(renamed[num_col])

    for txt_col in ["cn", "descripcion", "proveedor", "seccion_albaran", "albaran"]:
        renamed[txt_col] = renamed[txt_col].astype(str).str.strip()

    return renamed[REQUIRED_COLUMNS + [c for c in renamed.columns if c not in REQUIRED_COLUMNS]]


def detect_provider(df: pd.DataFrame, filename: str) -> str:
    filename_norm = normalize_text(filename)
    if "bidafarma" in filename_norm:
        return "Bidafarma"
    if "cofares" in filename_norm:
        return "Cofares"

    provider_values = " ".join(df.get("proveedor", pd.Series(dtype=str)).astype(str).tolist())
    text = normalize_text(provider_values)
    if "bidafarma" in text:
        return "Bidafarma"
    if "cofares" in text:
        return "Cofares"
    return "Desconocido"


def classify_line(provider: str, seccion: str, descripcion: str) -> str:
    text = f"{normalize_text(seccion)} {normalize_text(descripcion)}"

    rules = BIDAFARMA_RULES if provider == "Bidafarma" else COFARES_RULES if provider == "Cofares" else {}

    for line_type, keywords in rules.items():
        if any(keyword in text for keyword in keywords):
            return line_type

    if any(k in text for k in ["parafarma", "parafarmacia", "cosmetica", "cosmetica"]):
        return "parafarmacia"
    return "especialidad"


def derive_operation_type(row: pd.Series) -> str:
    if row["neto"] < 0:
        return "abono"
    if row["tipo_linea"] == "bitransfer":
        return "bitransfer"
    if row["tipo_linea"] == "club":
        return "club"
    return "goteo"


def load_condition_file(file) -> pd.DataFrame:
    if file.name.endswith((".xlsx", ".xls")):
        conditions = pd.read_excel(file)
    else:
        conditions = pd.read_csv(file)

    conditions.columns = [normalize_text(c) for c in conditions.columns]
    expected = {"proveedor", "concepto", "porcentaje", "importe"}
    missing = expected - set(conditions.columns)
    for col in missing:
        conditions[col] = 0 if col in {"porcentaje", "importe"} else ""

    conditions["proveedor"] = conditions["proveedor"].astype(str).str.strip().replace("", "Global")
    conditions["concepto"] = conditions["concepto"].astype(str).str.strip().replace("", "Cargo")
    conditions["porcentaje"] = to_number(conditions["porcentaje"])
    conditions["importe"] = to_number(conditions["importe"])
    return conditions[["proveedor", "concepto", "porcentaje", "importe"]]


def compute_base_metrics(df: pd.DataFrame) -> dict[str, float]:
    total_bruto = df["bruto"].sum()
    total_neto = df["neto"].sum()
    total_unidades = df["unidades"].sum()
    total_descuento = df["descuento"].sum()
    abonos = abs(df.loc[df["es_abono"], "neto"].sum())
    unit_price = total_neto / total_unidades if total_unidades else 0.0

    return {
        "Bruto (€)": total_bruto,
        "Neto (€)": total_neto,
        "Descuento": total_descuento,
        "Unidades": total_unidades,
        "Precio unitario neto": unit_price,
        "Abonos (€)": abonos,
    }


def apply_cost_engine(df: pd.DataFrame, conditions: pd.DataFrame) -> pd.DataFrame:
    provider_summary = (
        df.groupby("proveedor", as_index=False)
        .agg(neto=("neto", "sum"), bruto=("bruto", "sum"), unidades=("unidades", "sum"))
        .sort_values("neto", ascending=False)
    )

    rows: list[dict[str, object]] = []
    for _, provider_row in provider_summary.iterrows():
        provider = provider_row["proveedor"]
        neto = float(provider_row["neto"])

        provider_conditions = conditions[
            (conditions["proveedor"].str.lower() == str(provider).lower()) | (conditions["proveedor"].str.lower() == "global")
        ]

        if provider_conditions.empty:
            rows.append(
                {
                    "proveedor": provider,
                    "neto_base": neto,
                    "cargos_estimados": 0.0,
                    "coste_real_estimado": neto,
                }
            )
            continue

        cargos = 0.0
        for _, cond in provider_conditions.iterrows():
            cargos += neto * (float(cond["porcentaje"]) / 100.0)
            cargos += float(cond["importe"])

        rows.append(
            {
                "proveedor": provider,
                "neto_base": neto,
                "cargos_estimados": cargos,
                "coste_real_estimado": neto + cargos,
            }
        )

    return pd.DataFrame(rows)


def iter_excel_sheets(uploaded_file) -> Iterable[pd.DataFrame]:
    workbook = pd.read_excel(uploaded_file, sheet_name=None)
    return workbook.values()


def load_any_table(file) -> pd.DataFrame:
    if file.name.endswith((".xlsx", ".xls")):
        sheets = pd.read_excel(file, sheet_name=None)
        frames = [df for df in sheets.values() if df is not None and not df.empty]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return pd.read_csv(file)


def invoice_albaran_summary(invoice_df: pd.DataFrame) -> pd.DataFrame:
    normalized = normalize_columns(invoice_df)
    normalized = normalized[normalized["albaran"].astype(str).str.strip() != ""].copy()
    if normalized.empty:
        return pd.DataFrame(columns=["albaran", "neto"])

    summary = normalized.groupby("albaran", as_index=False).agg(neto=("neto", "sum"))
    return summary


def extract_invoice_charges(invoice_df: pd.DataFrame) -> pd.DataFrame:
    raw = invoice_df.copy()
    raw.columns = [normalize_text(c) for c in raw.columns]
    desc_col = None
    amount_col = None

    for c in ["descripcion", "descripción", "concepto", "detalle", "texto"]:
        if c in raw.columns:
            desc_col = c
            break
    for c in ["importe", "neto", "total", "bruto", "cantidad"]:
        if c in raw.columns:
            amount_col = c
            break

    if desc_col is None or amount_col is None:
        return pd.DataFrame(columns=["descripcion", "importe"])

    charges = raw[[desc_col, amount_col]].copy()
    charges.columns = ["descripcion", "importe"]
    charges["descripcion"] = charges["descripcion"].astype(str).str.strip()
    charges["importe"] = to_number(charges["importe"])

    desc_norm = charges["descripcion"].map(normalize_text)
    has_charge_word = desc_norm.apply(lambda txt: any(k in txt for k in CHARGE_KEYWORDS))
    has_tax_word = desc_norm.apply(lambda txt: any(k in txt for k in TAX_KEYWORDS))
    charges = charges[has_charge_word & ~has_tax_word & (charges["importe"] != 0)].copy()
    return charges.reset_index(drop=True)


def allocate_charges_to_bidafarma_products(df: pd.DataFrame, charges_total: float) -> pd.DataFrame:
    bidafarma = df[df["proveedor"].str.lower() == "bidafarma"].copy()
    bidafarma = bidafarma[~bidafarma["es_abono"]].copy()
    if bidafarma.empty or charges_total == 0:
        return pd.DataFrame(columns=["cn", "descripcion", "neto", "prorrateo_cargos", "neto_ajustado"])

    positive_neto = bidafarma["neto"].clip(lower=0)
    base = positive_neto.sum()
    if base == 0:
        bidafarma["prorrateo_cargos"] = 0.0
    else:
        bidafarma["prorrateo_cargos"] = (positive_neto / base) * charges_total
    bidafarma["neto_ajustado"] = bidafarma["neto"] + bidafarma["prorrateo_cargos"]
    return bidafarma[["cn", "descripcion", "neto", "prorrateo_cargos", "neto_ajustado"]]


def main() -> None:
    st.title("💊 Auditoría de Compras Farmacia")
    st.caption(
        "Analiza albaranes de Bidafarma/Cofares, normaliza líneas y calcula métricas con soporte de motor de costes."
    )

    with st.sidebar:
        st.header("Configuración")
        st.markdown("1) Sube albaranes en Excel.  2) (Opcional) carga condiciones de facturas/ICC.")

    uploaded_files = st.file_uploader(
        "Sube uno o varios albaranes (.xlsx/.xls)",
        type=["xlsx", "xls"],
        accept_multiple_files=True,
    )

    if not uploaded_files:
        st.info("Sube al menos un albarán para comenzar la auditoría.")
        return

    all_frames: list[pd.DataFrame] = []
    parse_errors: list[str] = []

    for file in uploaded_files:
        try:
            file_frames = []
            for sheet_df in iter_excel_sheets(file):
                if sheet_df is None or sheet_df.empty:
                    continue
                normalized = normalize_columns(sheet_df)
                normalized["proveedor"] = normalized["proveedor"].replace("", pd.NA)
                detected_provider = detect_provider(normalized, file.name)
                normalized["proveedor"] = normalized["proveedor"].fillna(detected_provider)
                normalized["proveedor"] = normalized["proveedor"].replace("", detected_provider)
                normalized["archivo_origen"] = file.name
                file_frames.append(normalized)

            if file_frames:
                all_frames.append(pd.concat(file_frames, ignore_index=True))
            else:
                parse_errors.append(f"{file.name}: no se encontraron hojas con datos.")
        except Exception as exc:
            parse_errors.append(f"{file.name}: error al leer archivo ({exc}).")

    if parse_errors:
        st.warning("\n".join(parse_errors))

    if not all_frames:
        st.error("No se pudo procesar ningún albarán válido.")
        return

    data = pd.concat(all_frames, ignore_index=True)

    data["tipo_linea"] = data.apply(
        lambda r: classify_line(
            provider=str(r.get("proveedor", "")),
            seccion=str(r.get("seccion_albaran", "")),
            descripcion=str(r.get("descripcion", "")),
        ),
        axis=1,
    )
    data["es_abono"] = data["neto"] < 0
    data["tipo_operacion"] = data.apply(derive_operation_type, axis=1)
    data["precio_unitario"] = data["neto"].div(data["unidades"].replace(0, pd.NA)).fillna(0.0)

    base_metrics = compute_base_metrics(data)

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    for col, (label, value) in zip([c1, c2, c3, c4, c5, c6], base_metrics.items()):
        if label == "Unidades":
            col.metric(label, f"{value:,.0f}")
        else:
            col.metric(label, f"{value:,.2f}")

    tab1, tab2, tab3, tab4 = st.tabs(
        ["Detalle normalizado", "Resumen por proveedor", "Segmentación", "Motor de costes"]
    )

    with tab1:
        st.subheader("Líneas normalizadas")
        visible_cols = REQUIRED_COLUMNS + ["tipo_linea", "tipo_operacion", "es_abono", "precio_unitario", "archivo_origen"]
        st.dataframe(data[visible_cols], use_container_width=True, hide_index=True)

    with tab2:
        st.subheader("Resumen por proveedor")
        provider_summary = (
            data.groupby("proveedor", as_index=False)
            .agg(
                lineas=("cn", "count"),
                unidades=("unidades", "sum"),
                bruto=("bruto", "sum"),
                neto=("neto", "sum"),
                descuento=("descuento", "sum"),
                abonos=("es_abono", "sum"),
            )
            .sort_values("neto", ascending=False)
        )
        st.dataframe(provider_summary, use_container_width=True, hide_index=True)

    with tab3:
        st.subheader("Segmentación por tipo de línea")
        segment = (
            data.groupby(["proveedor", "tipo_linea"], as_index=False)
            .agg(lineas=("cn", "count"), unidades=("unidades", "sum"), neto=("neto", "sum"))
            .sort_values(["proveedor", "neto"], ascending=[True, False])
        )
        st.dataframe(segment, use_container_width=True, hide_index=True)

        st.subheader("Abonos")
        abonos_df = data[data["es_abono"]].copy()
        if abonos_df.empty:
            st.success("No se detectaron líneas de abono.")
        else:
            st.dataframe(
                abonos_df[["proveedor", "albaran", "cn", "descripcion", "neto", "tipo_linea", "archivo_origen"]],
                use_container_width=True,
                hide_index=True,
            )

    with tab4:
        st.subheader("Condiciones (facturas / ICC)")
        st.caption("Bloque 2: conciliación de facturas y detección de cargos por proveedor (foco actual: Bidafarma).")

        st.markdown("#### Facturas Bidafarma")
        col_a, col_b = st.columns(2)
        with col_a:
            factura_normal = st.file_uploader(
                "Sube factura normal Bidafarma (.xlsx/.xls/.csv)",
                type=["xlsx", "xls", "csv"],
                accept_multiple_files=False,
                key="bidafarma_factura_normal",
            )
        with col_b:
            factura_transfer = st.file_uploader(
                "Sube factura transfer Bidafarma (.xlsx/.xls/.csv)",
                type=["xlsx", "xls", "csv"],
                accept_multiple_files=False,
                key="bidafarma_factura_transfer",
            )

        bidafarma_lines = data[data["proveedor"].str.lower() == "bidafarma"].copy()
        uploaded_bidafarma_albaranes = set(
            bidafarma_lines["albaran"].astype(str).str.strip().replace("nan", "").replace("", pd.NA).dropna().tolist()
        )

        invoice_albaranes_frames: list[pd.DataFrame] = []
        invoice_charges_frames: list[pd.DataFrame] = []

        for file, source_name in [
            (factura_normal, "Factura normal"),
            (factura_transfer, "Factura transfer"),
        ]:
            if file is None:
                continue
            try:
                table = load_any_table(file)
                if table.empty:
                    st.warning(f"{source_name}: archivo sin datos.")
                    continue

                albaran_summary = invoice_albaran_summary(table)
                albaran_summary["origen_factura"] = source_name
                invoice_albaranes_frames.append(albaran_summary)

                charges = extract_invoice_charges(table)
                charges["origen_factura"] = source_name
                invoice_charges_frames.append(charges)
            except Exception as exc:
                st.error(f"{source_name}: no se pudo procesar el archivo ({exc}).")

        if invoice_albaranes_frames:
            st.markdown("#### Chequeo de albaranes facturados vs albaranes subidos")
            invoice_albaranes = pd.concat(invoice_albaranes_frames, ignore_index=True)
            invoice_set = set(invoice_albaranes["albaran"].astype(str).str.strip().tolist())

            missing_in_upload = sorted(invoice_set - uploaded_bidafarma_albaranes)
            missing_in_invoice = sorted(uploaded_bidafarma_albaranes - invoice_set)

            f1, f2, f3 = st.columns(3)
            f1.metric("Albaranes Bidafarma subidos", len(uploaded_bidafarma_albaranes))
            f2.metric("Albaranes detectados en facturas", len(invoice_set))
            f3.metric("Diferencias detectadas", len(missing_in_upload) + len(missing_in_invoice))

            if missing_in_upload:
                st.error(
                    "Hay albaranes en factura no presentes en los albaranes cargados: "
                    + ", ".join(missing_in_upload[:20])
                    + (" ..." if len(missing_in_upload) > 20 else "")
                )
            if missing_in_invoice:
                st.warning(
                    "Hay albaranes cargados sin reflejo en factura: "
                    + ", ".join(missing_in_invoice[:20])
                    + (" ..." if len(missing_in_invoice) > 20 else "")
                )
            if not missing_in_upload and not missing_in_invoice:
                st.success("Conciliación OK: los albaranes de factura y los cargados coinciden.")

            invoice_neto = invoice_albaranes["neto"].sum()
            upload_neto = bidafarma_lines["neto"].sum()
            delta = invoice_neto - upload_neto
            st.info(
                f"Comparativa neto Bidafarma -> Facturas: {invoice_neto:,.2f} € | "
                f"Albaranes subidos: {upload_neto:,.2f} € | Diferencia: {delta:,.2f} €"
            )
            st.dataframe(invoice_albaranes, use_container_width=True, hide_index=True)
        else:
            st.info("Sube al menos una factura Bidafarma (normal o transfer) para ejecutar el chequeo.")

        if invoice_charges_frames:
            st.markdown("#### Cargos detectados tras IVA/recargo")
            charges_all = pd.concat(invoice_charges_frames, ignore_index=True)
            total_charges = charges_all["importe"].sum()
            st.metric("Total cargos detectados (€)", f"{total_charges:,.2f}")
            st.dataframe(charges_all, use_container_width=True, hide_index=True)

            st.markdown("#### Prorrateo inicial de cargos en líneas Bidafarma")
            allocation = allocate_charges_to_bidafarma_products(data, total_charges)
            if allocation.empty:
                st.info("No hay líneas Bidafarma positivas disponibles para prorratear cargos.")
            else:
                st.dataframe(allocation, use_container_width=True, hide_index=True)
        else:
            st.info("No se detectaron cargos en las facturas cargadas.")

        st.markdown("---")
        st.markdown("#### Condiciones generales (opcional)")
        st.caption("Formato esperado: proveedor, concepto, porcentaje, importe")
        conditions_file = st.file_uploader(
            "Sube condiciones de coste generales (.xlsx, .xls, .csv)",
            type=["xlsx", "xls", "csv"],
            accept_multiple_files=False,
            key="conditions_upload",
        )
        if conditions_file is None:
            empty_conditions = pd.DataFrame(columns=["proveedor", "concepto", "porcentaje", "importe"])
            cost_table = apply_cost_engine(data, empty_conditions)
        else:
            try:
                conditions = load_condition_file(conditions_file)
                st.dataframe(conditions, use_container_width=True, hide_index=True)
                cost_table = apply_cost_engine(data, conditions)
            except Exception as exc:
                st.error(f"No se pudo procesar el archivo de condiciones: {exc}")
                empty_conditions = pd.DataFrame(columns=["proveedor", "concepto", "porcentaje", "importe"])
                cost_table = apply_cost_engine(data, empty_conditions)
        st.subheader("Coste real estimado por proveedor")
        st.dataframe(cost_table, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
