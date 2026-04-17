import pandas as pd


COLUMN_MAPPING = {
    "cn": ["cn", "codigo", "cod_nacional", "codigo nacional"],
    "descripcion": ["descripcion", "articulo", "producto"],
    "bruto": ["bruto", "importe bruto", "precio bruto"],
    "neto": ["neto", "importe neto", "precio"],
    "iva": ["iva", "tipo iva"],
    "unidades": ["unidades", "cantidad"],
    "observaciones": ["observaciones", "observacion", "obs", "observ."]
}


def normalize_columns(df):

    mapping = {}

    for standard, options in COLUMN_MAPPING.items():

        for col in df.columns:

            if col.lower() in options:

                mapping[col] = standard

    df = df.rename(columns=mapping)

    return df

# ==========================
# DETECTOR DE SECCIONES
# ==========================

def parse_sections(df):

    secciones = []

    for _, row in df.iterrows():

        descripcion = str(row.get("descripcion", "")).lower()
        iva = row.get("iva", None)

        if "bitransfer" in descripcion:
            secciones.append("bitransfer")

        elif "club" in descripcion:
            secciones.append("club")

        elif iva == 4:
            secciones.append("especialidad")

        elif iva in [10, 21]:
            secciones.append("parafarmacia")

        else:
            secciones.append("desconocido")

    df["seccion_albaran"] = secciones

    return df
