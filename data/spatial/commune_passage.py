import os
import pandas as pd
import polars as pl

"""
Translates commune (and IRIS) codes of data sets published in an older
geography, e.g. the 2015 census (geography of 2017) or the 2016 BPE, to the
geography of data.spatial.codes (IRIS 2024 by default).

The translation table is built from the INSEE table of commune changes of the
code officiel géographique (v_mvt_commune_YYYY.csv): every commune code that
does not exist anymore is followed through its mergers to the commune it
belongs to now. Only used when apply_commune_passage is true.

IRIS codes are translated by replacing their commune part. IRIS that do not
exist in the target geography (e.g. redrawn ones) are handled by each stage.
"""

def configure(context):
    context.config("data_path")
    context.config("commune_passage_path", "cog_2024/v_mvt_commune_2024.csv")

    context.stage("data.spatial.codes")


def execute(context):
    df = pd.read_csv("{}/{}".format(context.config("data_path"), context.config("commune_passage_path")),
        dtype = str, usecols = ["DATE_EFF", "TYPECOM_AV", "COM_AV", "TYPECOM_AP", "COM_AP"])

    df = df[(df["TYPECOM_AV"] == "COM") & (df["TYPECOM_AP"] == "COM") & (df["COM_AV"] != df["COM_AP"])]
    df = df.sort_values("DATE_EFF")

    # Later changes of a code override earlier ones
    successor = dict(zip(df["COM_AV"], df["COM_AP"]))

    def resolve(commune_id):
        visited = set()
        while commune_id in successor and not commune_id in visited:
            visited.add(commune_id)
            commune_id = successor[commune_id]
        return commune_id

    df_codes = context.stage("data.spatial.codes")
    current_communes = set(df_codes["commune_id"].astype(str))

    # Codes that still exist are never translated (e.g. restored communes)
    passage = { commune_id: resolve(commune_id) for commune_id in successor if not commune_id in current_communes }
    passage = { old: new for old, new in passage.items() if new in current_communes }

    print("Commune passage: %d former communes translated to the configured geography" % len(passage))
    return passage


def validate(context):
    path = "{}/{}".format(context.config("data_path"), context.config("commune_passage_path"))
    if not os.path.exists(path):
        raise RuntimeError("Commune passage table is not available at %s" % path)

    return os.path.getsize(path)


def translate_communes(series, passage):
    """ Translates a pandas series of commune codes (missing values are kept). """
    result = series.astype(object).copy()
    f = result.notna()
    result[f] = result[f].astype(str).replace(passage)
    return result


def translate_iris(series, passage):
    """ Translates the commune part of a pandas series of IRIS codes (missing values are kept). """
    result = series.astype(object).copy()
    f = result.notna()
    codes = result[f].astype(str)
    translated = codes.str[:5].map(passage)
    result[f] = codes.where(translated.isna(), translated + codes.str[5:])
    return result


def translate_communes_expression(column, passage):
    """ Polars expression translating a column of commune codes. """
    return pl.col(column).replace(passage).alias(column)
