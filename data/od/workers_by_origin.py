import pandas as pd
import polars as pl
import data.census.coding as coding
import data.spatial.commune_passage as commune_passage

"""
Counts MOBPRO workers per residence commune, place of work (as in the census
ILT: home commune, elsewhere in France, abroad) and commute mode, over all
destinations. Unlike data.od.raw, destinations outside the requested area are
kept, so that these counts describe every worker living in a commune. Used to
place census households whose commune is unknown
(synthesis.population.spatial.home.zones, home_zone_method = "ilt").
"""

def configure(context):
    context.config("data_path")
    context.config("od_pro_path", "rp_2022/RP2023_mobpro.parquet")

    context.stage("data.spatial.codes")

    context.config("census_year", 2022)
    context.config("census_two_wheels_mode", "bike")

    if coding.splits_two_wheels(context.config("census_year"), context.config("census_two_wheels_mode")):
        context.stage("data.census.two_wheels_shares")

    if context.config("apply_commune_passage", False):
        context.stage("data.spatial.commune_passage")


def execute(context):
    df_codes = context.stage("data.spatial.codes")
    requested_communes = [str(commune_id) for commune_id in df_codes["commune_id"].unique()]

    # MOBPRO TRANS -> commute_mode, as in data.od.cleaned
    commute_modes = coding.od_commute_modes(context.config("census_year"), context.config("census_two_wheels_mode"))

    df = pl.read_parquet("{}/{}".format(context.config("data_path"), context.config("od_pro_path")),
        columns = ["COMMUNE", "ARM", "DCLT", "TRANS", "IPONDI"])

    df = df.with_columns(
        pl.col(["COMMUNE", "ARM", "DCLT"]).cast(pl.String),
        pl.col("TRANS").cast(pl.Int32), pl.col("IPONDI").cast(pl.Float64))

    if context.config("apply_commune_passage"):
        passage = context.stage("data.spatial.commune_passage")
        df = df.with_columns([commune_passage.translate_communes_expression(column, passage) for column in ["COMMUNE", "DCLT"]])

    # Arrondissements, as in data.od.cleaned
    df = df.with_columns(pl.when(pl.col("ARM").str.contains("Z")).then(pl.col("COMMUNE")).otherwise(pl.col("ARM")).alias("origin_id"))
    df = df.filter(pl.col("origin_id").is_in(requested_communes))

    df = df.with_columns(
        pl.when(pl.col("DCLT") == pl.col("origin_id")).then(pl.lit("home_commune"))
            .when(pl.col("DCLT") == "99999").then(pl.lit("abroad"))
            .otherwise(pl.lit("france")).alias("place_of_work"),
        pl.col("TRANS").replace_strict(commute_modes, default = None).alias("commute_mode"))

    df = df.group_by(["origin_id", "place_of_work", "commute_mode"]).agg(pl.col("IPONDI").sum().alias("weight"))
    df = df.to_pandas()

    if coding.splits_two_wheels(context.config("census_year"), context.config("census_two_wheels_mode")):
        # Old single two-wheel modality: split the weight into bike and car, as in data.od.cleaned
        f = df["commute_mode"] == coding.TWO_WHEELS
        df_bike, df_car = df[f].copy(), df[f].copy()

        df_origins = pd.DataFrame({ "commune_id": df_bike["origin_id"], "departement_id": df_bike["origin_id"].str[:2] })
        shares = coding.bike_shares(df_origins, context.stage("data.census.two_wheels_shares"))

        df_bike["commute_mode"], df_bike["weight"] = "bike", df_bike["weight"] * shares
        df_car["commute_mode"], df_car["weight"] = "car", df_car["weight"] * (1.0 - shares)
        df = pd.concat([df[~f], df_bike, df_car], ignore_index = True)
        df = df.groupby(["origin_id", "place_of_work", "commute_mode"], as_index = False)["weight"].sum()

    return df
