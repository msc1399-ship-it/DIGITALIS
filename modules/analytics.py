import pandas as pd

def analizar_factura_bidafarma(file):

    try:
        df = pd.read_excel(file)

        df.columns = [c.lower().strip() for c in df.columns]

        total_bruto = 0
        total_neto = 0

        for col in df.columns:

            if "bruto" in col:
                total_bruto = df[col].sum()

            if "neto" in col:
                total_neto = df[col].sum()

        cargo = 0

        if total_bruto > 0:
            cargo = ((total_bruto - total_neto) / total_bruto) * 100

        return {
            "total_bruto": total_bruto,
            "total_neto": total_neto,
            "cargo_detectado": cargo
        }

    except Exception as e:
        return {"error": str(e)}

    else:
        st.error(resultado_normal["error"])

