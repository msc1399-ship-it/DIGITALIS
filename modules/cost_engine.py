def apply_costs(df, condiciones):

    df["coste_ajustado"] = df["neto"]

    for proveedor, config in condiciones.items():

        if proveedor == "bidafarma":

            pct = config.get("bitransfer_pct", 0)

            mask = (df["proveedor"] == "bidafarma") & (df["seccion_albaran"] == "bitransfer")

            df.loc[mask, "coste_ajustado"] = (
                df.loc[mask, "bruto"] * (1 + pct / 100)
            )

        elif proveedor == "cofares":

            base_icc = config.get("base_icc", 0)
            pct_franq = config.get("pct_franquicia", 0)

            mask = (df["proveedor"] == "cofares") & (df["iva"] == 4)

            base_real = df.loc[mask, "neto"].sum()

            franquicia = max(base_real - base_icc, 0)

            if base_real > 0:

                df.loc[mask, "coste_ajustado"] += (
                    df.loc[mask, "neto"] / base_real
                ) * franquicia * (pct_franq / 100)

    return df

