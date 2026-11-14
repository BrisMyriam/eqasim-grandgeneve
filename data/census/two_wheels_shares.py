import os
import pandas as pd
import polars as pl
import data.spatial.commune_passage as commune_passage

"""
Share of bicycles among the two-wheel commuters (bicycles and motorised
two-wheelers), from a MOBPRO file of RP2017 or later, where both are separated
(TRANS 3 bike, 4 motorised two-wheeler). Used to split the single two-wheel
modality of older censuses (census_two_wheels_mode: split, see
data.census.coding).

Shares are given per residence commune when it has at least
two_wheels_minimum_records two-wheel records, and per departement otherwise.
"""

def configure(context):
    context.config("data_path")
    context.config("two_wheels_reference_path", "rp_2017/RP2017_mobpro.parquet")
    context.config("two_wheels_minimum_records", 30)

    context.stage("data.spatial.codes")

    if context.config("apply_commune_passage", False):
        context.stage("data.spatial.commune_passage")


def execute(context):
    df_codes = context.stage("data.spatial.codes")
    requested_departements = set(df_codes["departement_id"].astype(str))

    df = pl.read_parquet("{}/{}".format(context.config("data_path"), context.config("two_wheels_reference_path")),
        columns = ["COMMUNE", "TRANS", "IPONDI"]).with_columns(
        pl.col(["COMMUNE", "TRANS"]).cast(pl.String), pl.col("IPONDI").cast(pl.Float64))

    df = df.filter(pl.col("TRANS").is_in(["3", "4"]))
    df = df.filter(pl.col("COMMUNE").str.slice(0, 2).is_in(requested_departements)).to_pandas()

    if context.config("apply_commune_passage"):
        df["COMMUNE"] = commune_passage.translate_communes(df["COMMUNE"], context.stage("data.spatial.commune_passage"))

    df["departement_id"] = df["COMMUNE"].str[:2]
    df["bike_weight"] = df["IPONDI"].where(df["TRANS"] == "3", 0.0)

    df_departements = df.groupby("departement_id")[["bike_weight", "IPONDI"]].sum()
    departement_shares = df_departements["bike_weight"] / df_departements["IPONDI"]

    df_communes = df.groupby("COMMUNE").agg(bike_weight = ("bike_weight", "sum"), weight = ("IPONDI", "sum"), records = ("IPONDI", "size"))
    df_communes = df_communes[df_communes["records"] >= context.config("two_wheels_minimum_records")]
    commune_shares = df_communes["bike_weight"] / df_communes["weight"]

    print("Two-wheels shares: bicycle share by departement %s, %d communes with their own share" % (
        departement_shares.round(3).to_dict(), len(commune_shares)))

    return commune_shares, departement_shares


def validate(context):
    path = "{}/{}".format(context.config("data_path"), context.config("two_wheels_reference_path"))
    if not os.path.exists(path):
        raise RuntimeError("Two-wheels reference data is not available at %s" % path)

    return os.path.getsize(path)
