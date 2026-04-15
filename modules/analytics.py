import pandas as pd
import re

# =========================
# UTILIDADES
# =========================

def extraer_numero_albaran(texto):
    texto = str(texto).lower().strip()

    # admite: 123, VA-123, ML-123, ZV-123
    match = re.match(r"^[a-z]{0,3}-?\d+$", texto)

    if match:
        return re.sub(r"[^\d]", "", texto)

    return None


def limpiar_texto(texto):
    texto = re.sub(r"\d+(\.\d+)?", "", texto)
    return texto.strip()


def limpiar_concepto_abono(texto):
    texto = re.sub(r"-?\d+(\.\d+)?", "", texto)
    texto = texto.replace("  ", " ")
    return texto.strip()


# =========================
# FACTURA NORMAL
# =========================

def analizar_factura_bidafarma(file):

    df = pd.read_excel(file)
    df.columns = [c.lower().strip() for c in df.columns]

    albaranes = []
    gastos = []

    # detectar columna albarán
    col_albaran = None
    for col in df.columns:
        if "albaran" in col:
            col_albaran = col
            break

    leyendo_albaranes = True

    for _, row in df.iterrows():

        valores = [str(x).strip() for x in row.values if pd.notna(x)]
        if not valores:
            continue

        texto = " ".join(valores).lower()

        # cortar cuando empiezan gastos
        if any(x in texto for x in ["servicio", "gestion", "gestión", "avantia"]):
            leyendo_albaranes = False

        # =========================
        # ALBARANES
        # =========================
        if leyendo_albaranes and col_albaran:

            valor = str(row[col_albaran]).strip()
            num = extraer_numero_albaran(valor)

            if num:
                albaranes.append(num)

        # =========================
        # IGNORAR IVA / TOTALES
        # =========================
        if any(x in texto for x in ["iva", "recargo", "total"]):
            continue

        # =========================
        # IMPORTE
        # =========================
        importe = None

        if "importe" in df.columns:
            try:
                importe = float(row["importe"])
            except:
                pass

        if importe is None:
            for v in valores:
                try:
                    importe = float(v)
                    break
                except:
                    continue

        if importe is None:
            continue

        texto_limpio = limpiar_texto(texto)

        # =========================
        # GASTOS
        # =========================
        if "servicio" in texto:
            gastos.append({
                "tipo": "servicios",
                "concepto": texto_limpio,
                "importe": round(float(importe), 2)
            })

        elif "gestion" in texto or "gestión" in texto:
            gastos.append({
                "tipo": "gestion",
                "concepto": "gastos de gestión",
                "importe": round(float(importe), 2)
            })

        elif "avantia" in texto:
            gastos.append({
                "tipo": "avantia",
                "concepto": "cuota avantia",
                "importe": round(float(importe), 2)
            })

    # =========================
    # RESUMEN COSTES NORMAL
    # =========================

    total_gastos = sum([g["importe"] for g in gastos])

    iva = total_gastos * 0.21
    total_final = total_gastos + iva

    return {
        "albaranes": list(set(albaranes)),
        "gastos": pd.DataFrame(gastos),
        "resumen_costes": {
            "base": round(total_gastos, 2),
            "iva": round(iva, 2),
            "total": round(total_final, 2)
        }
    }


# =========================
# FACTURA TRANSFER
# =========================

def analizar_factura_transfer(file):

    df = pd.read_excel(file)
    df.columns = [c.lower().strip() for c in df.columns]

    albaranes = []
    gastos = []
    abonos = []

    # detectar columna albarán
    col_albaran = None
    for col in df.columns:
        if "albaran" in col:
            col_albaran = col
            break

    leyendo_albaranes = True

    for _, row in df.iterrows():

        valores = [str(x).strip() for x in row.values if pd.notna(x)]
        if not valores:
            continue

        texto = " ".join(valores).lower()

        # cortar cuando empiezan gastos transfer
        if any(x in texto for x in ["log", "abono", "laboratorio"]):
            leyendo_albaranes = False

        # =========================
        # ALBARANES
        # =========================
        if leyendo_albaranes and col_albaran:

            valor = str(row[col_albaran]).strip()
            num = extraer_numero_albaran(valor)

            if num:
                albaranes.append(num)

        # =========================
        # IGNORAR IVA
        # =========================
        if any(x in texto for x in ["iva", "recargo", "total"]):
            continue

        # =========================
        # IMPORTE
        # =========================
        importe = None

        if "importe" in df.columns:
            try:
                importe = float(row["importe"])
            except:
                pass

        if importe is None:
            for v in valores:
                try:
                    importe = float(v)
                    break
                except:
                    continue

        if importe is None:
            continue

        # =========================
        # LOGÍSTICA
        # =========================
        if "log" in texto:
            gastos.append({
                "tipo": "logistica",
                "concepto": "servicios logisticos",
                "importe": round(float(importe), 2)
            })

        # =========================
        # ABONOS (LIMPIOS)
        # =========================
        elif "abono" in texto or "laboratorio" in texto:
            abonos.append({
                "tipo": "abono",
                "concepto": limpiar_concepto_abono(texto),
                "importe": round(float(importe), 2)
            })

    # =========================
    # RESUMEN LOGÍSTICA
    # =========================

    total_logistica = sum([g["importe"] for g in gastos])
    total_abonos = sum([a["importe"] for a in abonos])

    base = total_logistica + total_abonos
    iva = base * 0.21
    total_final = base + iva

    return {
        "albaranes": list(set(albaranes)),
        "gastos": pd.DataFrame(gastos),
        "abonos": pd.DataFrame(abonos),
        "resumen_logistica": {
            "base": round(base, 2),
            "iva": round(iva, 2),
            "total": round(total_final, 2)
        }
    }

