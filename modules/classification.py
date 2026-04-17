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


