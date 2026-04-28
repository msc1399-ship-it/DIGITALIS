import re
import unicodedata
from collections import Counter

import pandas as pd


TIPOS_ALBARAN_74 = {
    1: "desglose",
    2: "tramo fijo",
    3: "tramo 0",
}


CONDICIONES_BIDAFARMA = {
    "X8": {
        "nombre": "Diane Vida",
        "albaran_74": "puede_aparecer",
        "tipo_albaran_74": 1,
        "ajuste_comercial_factura": False,
        "cargo_adicional_gestion": False,
    },
    "NN": {
        "nombre": "Diane Cecofar",
        "albaran_74": "solo_liquidaciones",
        "tipo_albaran_74": None,
        "ajuste_comercial_factura": True,
        "cargo_adicional_gestion": False,
    },
    "XP": {
        "nombre": "Vida Volumen",
        "albaran_74": "si",
        "tipo_albaran_74": 3,
        "ajuste_comercial_factura": False,
        "cargo_adicional_gestion": False,
    },
    "XR": {
        "nombre": "Vida Línea",
        "albaran_74": "solo_liquidaciones",
        "tipo_albaran_74": None,
        "ajuste_comercial_factura": False,
        "cargo_adicional_gestion": True,
    },
    "NJ": {
        "nombre": "Pruébame 4",
        "albaran_74": "solo_bruto",
        "tipo_albaran_74": 1,
        "ajuste_comercial_factura": False,
        "cargo_adicional_gestion": False,
    },
    "X4": {
        "nombre": "Pruébame 5",
        "albaran_74": "solo_bruto",
        "tipo_albaran_74": 1,
        "ajuste_comercial_factura": False,
        "cargo_adicional_gestion": False,
    },
    "ND": {
        "nombre": "Pruébame 6",
        "albaran_74": "solo_bruto",
        "tipo_albaran_74": 1,
        "ajuste_comercial_factura": False,
        "cargo_adicional_gestion": False,
    },
    "ZV": {
        "nombre": "Zacofarva",
        "albaran_74": "si",
        "tipo_albaran_74": 2,
        "ajuste_comercial_factura": False,
        "cargo_adicional_gestion": False,
    },
    "GS": {
        "nombre": "Socofasa",
        "albaran_74": "solo_liquidaciones",
        "tipo_albaran_74": None,
        "ajuste_comercial_factura": False,
        "cargo_adicional_gestion": True,
    },
}


def _normalizar_texto(valor):
    texto = str(valor).strip().upper()
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c))


def _series_texto(df, columnas):
    for columna in columnas:
        if columna in df.columns:
            yield df[columna].astype(str)


def _extraer_acronimos_directos(df, columnas):
    contador = Counter()

    if df is None or df.empty:
        return contador

    for columna in columnas:
        if columna not in df.columns:
            continue

        for valor in df[columna].astype(str):
            acronimo = _normalizar_texto(valor)
            if acronimo in CONDICIONES_BIDAFARMA:
                contador[acronimo] += 1

    return contador


def extraer_acronimos(df):
    if df is None or df.empty:
        return Counter()

    candidatos = [
        "tipo",
        "tarifa",
        "condicion",
        "condición",
        "acronimo",
        "acrónimo",
        "observaciones",
        "descripcion",
    ]

    contador = Counter()
    patron = re.compile(r"\b(" + "|".join(CONDICIONES_BIDAFARMA.keys()) + r")\b", re.IGNORECASE)

    for serie in _series_texto(df, candidatos):
        for valor in serie:
            for match in patron.findall(str(valor)):
                acronimo = _normalizar_texto(match)
                if acronimo in CONDICIONES_BIDAFARMA:
                    contador[acronimo] += 1

    if contador:
        return contador

    for columna in df.columns:
        if pd.api.types.is_numeric_dtype(df[columna]):
            continue
        for valor in df[columna].astype(str):
            for match in patron.findall(valor):
                acronimo = _normalizar_texto(match)
                if acronimo in CONDICIONES_BIDAFARMA:
                    contador[acronimo] += 1

    return contador


def detectar_condicion(df=None, df_faceta=None):
    columnas_prioritarias = ["tipo", "tarifa", "condicion", "condición", "acronimo", "acrónimo"]
    contador_directo = _extraer_acronimos_directos(df, columnas_prioritarias)

    if contador_directo:
        acronimo, apariciones = contador_directo.most_common(1)[0]
        config = CONDICIONES_BIDAFARMA[acronimo].copy()
        config["acronimo"] = acronimo
        config["apariciones"] = apariciones
        config["origen"] = "directo"
        return config

    contador = extraer_acronimos(df)
    if df_faceta is not None and not df_faceta.empty:
        contador.update(extraer_acronimos(df_faceta))

    if contador:
        acronimo, apariciones = contador.most_common(1)[0]
        config = CONDICIONES_BIDAFARMA[acronimo].copy()
        config["acronimo"] = acronimo
        config["apariciones"] = apariciones
        config["origen"] = "texto"
        return config

    return None


def nombre_tipo_74(tipo_codigo):
    return TIPOS_ALBARAN_74.get(tipo_codigo, "-")
