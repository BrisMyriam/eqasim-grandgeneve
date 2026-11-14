import os
import numpy as np
import pandas as pd
import polars as pl
import zipfile
import data.spatial.commune_passage as commune_passage


"""
Loads aggregate population data.

Two formats are supported:
- the "base infracommunale" CSV inside a zip (base-ic-evol-struct-pop-YYYY,
  column P{population_year}_POP), up to the 2022 census;
- the INSEE Melodi table DS_RP_POPULATION_PRINC_IRIS as parquet (from the
  2023 census), when population_path ends with .parquet. Communes without
  IRIS are given there at commune level and get the IRIS code
  <commune>0000, as in the CSV.
"""

# Dimensions of DS_RP_POPULATION_PRINC_IRIS that must be at their total
MELODI_TOTAL_DIMENSIONS = ["AGE", "SEX", "IMMI", "NATIONALITY_TYPE", "HAR"]


def configure(context):
    context.config("data_path")
    context.stage("data.spatial.codes")
    context.config("population_path", "rp_2022/base-ic-evol-struct-pop-2022_csv.zip")
    context.config("population_csv", "base-ic-evol-struct-pop-2022.CSV")
    context.config("population_year", 22)

    if context.config("apply_commune_passage", False):
        context.stage("data.spatial.commune_passage")


def apply_commune_passage(df_population, passage, df_codes):
    """
    Translates population data of an older geography to the configured one.
    Merged communes without IRIS get the IRIS of their new commune; the
    population of IRIS that still do not exist (redrawn IRIS, or absorbed
    communes now part of a commune with IRIS) is spread over the IRIS of the
    commune that have no population yet, or else over all of its IRIS in
    proportion to their population.
    """
    df_population = df_population.copy()
    df_population["commune_id"] = commune_passage.translate_communes(df_population["commune_id"], passage)
    df_population["iris_id"] = commune_passage.translate_iris(df_population["iris_id"], passage)

    codes_iris = df_codes[["iris_id", "commune_id"]].astype(str).drop_duplicates()
    f_unknown = ~df_population["iris_id"].isin(set(codes_iris["iris_id"]))
    f_requested = df_population["commune_id"].isin(set(codes_iris["commune_id"]))

    df_known = df_population[~f_unknown]
    df_unknown = df_population[f_unknown & f_requested]

    df_spread = []
    for commune_id, population in df_unknown.groupby("commune_id")["population"].sum().items():
        df_targets = codes_iris[codes_iris["commune_id"] == commune_id][["iris_id"]].copy()
        df_targets["existing"] = df_targets["iris_id"].map(df_known.groupby("iris_id")["population"].sum())

        f_empty = df_targets["existing"].isna()
        if f_empty.any():
            df_targets = df_targets[f_empty]
            shares = np.ones(len(df_targets))
        else:
            shares = df_targets["existing"].values.astype(float)
            if shares.sum() == 0: shares = np.ones(len(df_targets))

        df_targets["population"] = population * shares / shares.sum()
        df_targets["commune_id"] = commune_id
        df_spread.append(df_targets[["iris_id", "commune_id", "population"]])

    print("Population: %d IRIS (%.0f inhabitants) of the requested communes unknown to the configured geography, spread over %d IRIS of their commune" % (
        len(df_unknown), df_unknown["population"].sum(), sum(len(df) for df in df_spread)))

    df_population = pd.concat([df_known[["iris_id", "commune_id", "population"]]] + df_spread)
    return df_population.groupby(["iris_id", "commune_id"], as_index = False)["population"].sum()


def read_melodi(path):
    df = pl.read_parquet(path)

    selector = pl.col("RP_MEASURE").cast(pl.String) == "POP"
    for dimension in MELODI_TOTAL_DIMENSIONS:
        if dimension in df.columns:
            selector = selector & (pl.col(dimension).cast(pl.String) == "_T")

    df = df.filter(selector).select(
        pl.col("GEO").cast(pl.String), pl.col("GEO_OBJECT").cast(pl.String), pl.col("OBS_VALUE").alias("population")
    ).to_pandas()

    df_iris = df[df["GEO_OBJECT"] == "IRIS"]
    df_communes = df[(df["GEO_OBJECT"] == "COM") & ~df["GEO"].isin(df_iris["GEO"].str[:5])]

    df = pd.concat([
        pd.DataFrame({ "iris_id": df_iris["GEO"].values, "commune_id": df_iris["GEO"].str[:5].values, "population": df_iris["population"].values }),
        pd.DataFrame({ "iris_id": (df_communes["GEO"] + "0000").values, "commune_id": df_communes["GEO"].values, "population": df_communes["population"].values }),
    ])

    assert not df["iris_id"].duplicated().any()
    return df


def execute(context):
    year = str(context.config("population_year"))
    path = "{}/{}".format(context.config("data_path"), context.config("population_path"))

    if path.endswith(".parquet"):
        df_population = read_melodi(path)

    else:
        with zipfile.ZipFile(path) as archive:
            with archive.open(context.config("population_csv")) as f:
                df_population = pd.read_csv(
                    f,
                    sep = ";",  usecols = ["IRIS", "COM", "P%s_POP" % year],dtype={"IRIS":str,"COM":str}
                ).rename(columns = {
                    "IRIS": "iris_id", "COM": "commune_id",
                    "P%s_POP" % year: "population"
                })

    if context.config("apply_commune_passage"):
        df_population = apply_commune_passage(df_population,
            context.stage("data.spatial.commune_passage"), context.stage("data.spatial.codes"))

    df_population["iris_id"] = df_population["iris_id"].astype("category")
    df_population["commune_id"] = df_population["commune_id"].astype("category")

    # Merge into code data and verify integrity
    df_codes = context.stage("data.spatial.codes").copy()
    df_codes = df_codes[df_codes["iris_id"]!="CH"]
    df_population = pd.merge(df_population, df_codes, on = ["iris_id", "commune_id"])

    return df_population[["region_id", "departement_id", "commune_id", "iris_id", "population"]]


def validate(context):
    if not os.path.exists("{}/{}".format(context.config("data_path"), context.config("population_path"))):
        raise RuntimeError("Aggregated census data is not available")

    return os.path.getsize("{}/{}".format(context.config("data_path"), context.config("population_path")))
     