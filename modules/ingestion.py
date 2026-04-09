import pandas as pd


def load_excel(file):

    df = pd.read_excel(file)

    df.columns = (
        df.columns
        .str.lower()
        .str.strip()
    )

    return df
