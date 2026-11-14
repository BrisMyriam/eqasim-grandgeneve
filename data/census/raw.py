import os
import polars as pl
import data.census.coding as coding

"""
This stage loads the raw data from the French population census.
"""

def configure(context):
    context.stage("data.spatial.codes")

    context.config("data_path")
    context.config("census_path", "rp_2022/RP2022_indcvi.parquet")
    context.config("census_year", 2022)


COLUMNS_DTYPES = {
    "CANTVILLE": "str",
    "NUMMI":     "str",
    "AGED":      "str",
    "COUPLE":    "str",
    "DEPT":      "str",
    "ETUD":      "str",
    "IPONDI":    "str", 
    "IRIS":      "str",
    "REGION":    "str", 
    "SEXE":      "str",
    "TACT":      "str",
    "ILT":       "str",
    "ILETUD":    "str",
    "TP":        "str",
    "TRANS":     "str",
    "VOIT":      "str", 
    "DEROU":     "str"
}

# Socioprofessional category: CS1 up to RP2021, GS and STAT_GSEC from RP2022 (see data.census.coding)
CSP_COLUMNS_CS1 = ["CS1"]
CSP_COLUMNS_GS = ["GS", "STAT_GSEC"]


def execute(context):
    df_codes = context.stage("data.spatial.codes").copy()
    df_codes = df_codes[df_codes["iris_id"] != "CH"]

    requested_departements = df_codes["departement_id"].unique()

    columns = list(COLUMNS_DTYPES.keys())
    columns += CSP_COLUMNS_CS1 if coding.uses_cs1(context.config("census_year")) else CSP_COLUMNS_GS

    with context.progress(label = "Reading census ...") as progress:
        parquet = pl.read_parquet( "{}/{}".format(context.config("data_path"), context.config("census_path")),
                        columns=  columns)
        
        parquet  = parquet.cast(pl.String)
        dpts_str = [str(dep) for dep in requested_departements]
        parquet  = parquet.filter(pl.col("DEPT").is_in(dpts_str))

        progress.update(len(parquet))                    

    return parquet.to_pandas()


def validate(context):
    if not os.path.exists("{}/{}".format(context.config("data_path"), context.config("census_path"))):
        raise RuntimeError("Census data is not available at %s" % context.config("census_path"))

    return os.path.getsize("{}/{}".format(context.config("data_path"), context.config("census_path")))
