import numpy as np
import pandas as pd
import data.census.coding as coding

"""
Cleans OD data to arrive at OD flows between municipalities for work
and education.
"""

def configure(context):
    context.stage("data.od.raw")
    context.stage("data.spatial.codes")
    context.stage("data.od.part_time")

    context.config("random_seed")
    context.config("census_year", 2022)
    context.config("census_two_wheels_mode", "bike")

    if coding.splits_two_wheels(context.config("census_year"), context.config("census_two_wheels_mode")):
        context.stage("data.census.two_wheels_shares")

# TP (work time) codes of part-time workers: 2 in the RP2022 release, 12 in RP2023
PART_TIME_CODES = [2, 12]

RENAME = { "COMMUNE" : "origin_id", "DCLT" : "destination_id", "IPONDI" : "weight", "DCETUF" : "destination_id" }

def execute(context):
    
    # Load data
    df_work, df_education = context.stage("data.od.raw")

    # Renaming
    df_work = df_work.rename(RENAME, axis = 1)
    df_education = df_education.rename(RENAME, axis = 1)

    # Fix arrondissements
    df_work.loc[~df_work["ARM"].str.contains("Z"), "origin_id"] = df_work["ARM"]
    df_education.loc[~df_education["ARM"].str.contains("Z"), "origin_id"] = df_education["ARM"]

    # Verify spatial data for work
    df_codes = context.stage("data.spatial.codes").copy()

    df_work["origin_id"] = df_work["origin_id"].astype("category")
    df_work["destination_id"] = df_work["destination_id"].astype("category")

    excess_communes = (set(df_work["origin_id"].unique()) | set(df_work["destination_id"].unique())) - set(df_codes["commune_id"].unique())
    if len(excess_communes) > 0:
        raise RuntimeError("Found additional communes: %s" % excess_communes)

    # Verify spatial data for education
    df_codes = context.stage("data.spatial.codes").copy()

    df_education["origin_id"] = df_education["origin_id"].astype("category")
    df_education["destination_id"] = df_education["destination_id"].astype("category")

    excess_communes = (set(df_education["origin_id"].unique()) | set(df_education["destination_id"].unique())) - set(df_codes["commune_id"].unique())
    if len(excess_communes) > 0:
        raise RuntimeError("Found additional communes: %s" % excess_communes)

    # Clean commute mode for work (coding depends on the census year, see data.census.coding)
    commute_modes = coding.od_commute_modes(context.config("census_year"), context.config("census_two_wheels_mode"))
    df_work["commute_mode"] = df_work["TRANS"].map(commute_modes)
    assert not np.any(df_work["commute_mode"].isna())

    if coding.splits_two_wheels(context.config("census_year"), context.config("census_two_wheels_mode")):
        # Old single two-wheel modality: split the weight into bike and car with
        # the share of bicycles of the origin commune (or departement)
        f = df_work["commute_mode"] == coding.TWO_WHEELS
        df_bike = df_work[f].copy()
        df_car = df_work[f].copy()

        df_origins = pd.DataFrame({ "commune_id": df_bike["origin_id"].astype(str), "departement_id": df_bike["origin_id"].astype(str).str[:2] })
        shares = coding.bike_shares(df_origins, context.stage("data.census.two_wheels_shares"))

        df_bike["commute_mode"], df_bike["weight"] = "bike", df_bike["weight"] * shares
        df_car["commute_mode"], df_car["weight"] = "car", df_car["weight"] * (1.0 - shares)
        df_work = pd.concat([df_work[~f], df_bike, df_car], ignore_index = True)

        for column in ["origin_id", "destination_id"]:
            df_work[column] = df_work[column].astype("category")
    df_work["commute_mode"] = df_work["commute_mode"].astype("category")

    # Employment time: 1.0 for full-time workers; for each part-time record,
    # one draw from the part-time distribution of the labour force survey
    random = np.random.default_rng(context.config("random_seed"))
    distribution = context.stage("data.od.part_time")
    is_part_time = df_work["TP"].isin(PART_TIME_CODES).values

    df_work["employment_time"] = 1.0
    df_work.loc[is_part_time, "employment_time"] = random.choice(
        distribution.index.values, size = np.count_nonzero(is_part_time), p = distribution.values)

    # Weight in full-time equivalents (weight * employment time)
    df_work["fte_weight"] = df_work["weight"] * df_work["employment_time"]

    # Clean age range for education
    df_education["AGEREV10"] = df_education["AGEREV10"].astype(int)
    df_education["age_range"] = ""
    df_education.loc[df_education["AGEREV10"] <= 6, "age_range"] = "primary_school"
    df_education.loc[df_education["AGEREV10"] == 11, "age_range"] = "middle_school"
    df_education.loc[df_education["AGEREV10"] == 15, "age_range"] = "high_school"
    df_education.loc[df_education["AGEREV10"] >= 18, "age_range"] = "higher_education"
    assert not np.any(df_education["age_range"] == "")
    df_education["age_range"] = df_education["age_range"].astype("category")

    # Aggregate the flows
    print("Aggregating work ...")
    df_work = df_work.groupby(["origin_id", "destination_id", "commute_mode"],observed=False)[["weight", "fte_weight"]].sum().reset_index()

    print("Aggregating education ...")
    df_education = df_education.groupby(["origin_id", "destination_id","age_range"],observed=False)["weight"].sum().reset_index()

    df_work["weight"] = df_work["weight"].fillna(0.0)
    df_work["fte_weight"] = df_work["fte_weight"].fillna(0.0)
    df_education["weight"] = df_education["weight"].fillna(0.0)

    return df_work, df_education
