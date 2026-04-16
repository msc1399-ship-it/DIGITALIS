import re
import unicodedata

import pandas as pd


def _normalizar_texto(valor):
    texto = str(valor).strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"\s+", " ", texto)
    return texto


def _normalizar_numero(valor):
    if pd.isna(valor):
        return None

    if isinstance(valor, (int, float)):
        return float(valor)

    texto = str(valor).strip()
    if not texto:
        return None

    texto = texto.replace("€", "").replace("%", "").replace(" ", "")

    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    else:
        texto = texto.replace(",", ".")

    try:
        return float(texto)
    except ValueError:
        return None


def _normalizar_cn(valor):
    if pd.isna(valor):
        return None

    texto = str(valor).strip()
    if not texto:
        return None

    if re.match(r"^\d+\.0$", texto):
        texto = texto[:-2]

    cn = re.sub(r"\D", "", texto)
    return cn or None


def _buscar_columna(columnas, opciones):
    columnas_normalizadas = {_normalizar_texto(col): col for col in columnas}

    for opcion in opciones:
        opcion_normalizada = _normalizar_texto(opcion)
        if opcion_normalizada in columnas_normalizadas:
            return columnas_normalizadas[opcion_normalizada]

    for col_normalizada, col_original in columnas_normalizadas.items():
        if any(_normalizar_texto(opcion) in col_normalizada for opcion in opciones):
            return col_original

    return None


def leer_listado_compras_bitransfer(file):
    df = pd.read_excel(file)
    df.columns = [str(c).strip() for c in df.columns]

    columnas = {
        "cn": _buscar_columna(df.columns, ["codigo nacional", "codigo", "cn"]),
        "descripcion": _buscar_columna(df.columns, ["descripcion", "producto", "articulo"]),
        "cantidad": _buscar_columna(df.columns, ["cant.", "cantidad", "unidades"]),
        "pvl": _buscar_columna(df.columns, ["pvl", "importe", "importe bruto", "bruto"]),
        "cantidad_total": _buscar_columna(df.columns, ["cant. total", "cantidad total"]),
        "descuento": _buscar_columna(df.columns, ["desc.", "descuento"]),
        "cargo": _buscar_columna(df.columns, ["gast.", "gasto", "cargo", "recargo"]),
        "importe_neto": _buscar_columna(df.columns, ["total", "importe neto", "neto"]),
    }

    obligatorias = ["cn", "descripcion", "pvl", "cargo", "importe_neto"]
    faltantes = [nombre for nombre in obligatorias if columnas[nombre] is None]

    if faltantes:
        raise ValueError(
            "No se han encontrado estas columnas obligatorias: "
            + ", ".join(faltantes)
        )

    resultado = pd.DataFrame()
    resultado["cn"] = df[columnas["cn"]].apply(_normalizar_cn)
    resultado["descripcion"] = df[columnas["descripcion"]].astype(str).str.strip()

    if columnas["cantidad"]:
        resultado["cantidad"] = df[columnas["cantidad"]].apply(_normalizar_numero)
    else:
        resultado["cantidad"] = None

    resultado["pvl"] = df[columnas["pvl"]].apply(_normalizar_numero)

    if columnas["cantidad_total"]:
        resultado["cantidad_total"] = df[columnas["cantidad_total"]].apply(_normalizar_numero)
    else:
        resultado["cantidad_total"] = None

    if columnas["descuento"]:
        resultado["descuento_pct"] = df[columnas["descuento"]].apply(_normalizar_numero)
    else:
        resultado["descuento_pct"] = None

    resultado["cargo_pct"] = df[columnas["cargo"]].apply(_normalizar_numero)
    resultado["importe_neto"] = df[columnas["importe_neto"]].apply(_normalizar_numero)

    resultado = resultado.dropna(subset=["cn", "descripcion", "pvl", "cargo_pct", "importe_neto"])
    resultado = resultado[resultado["cn"].str.len() > 0]

    return resultado.reset_index(drop=True)
