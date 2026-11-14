import os
import polars as pl
import data.spatial.commune_passage as commune_passage


"""
This stage loads the raw data from the French service registry.
"""

def configure(context):
    context.config("data_path")
    context.config("bpe_path", "bpe_2024/BPE24.parquet")
    context.stage("data.spatial.codes")

    if context.config("apply_commune_passage", False):
        context.stage("data.spatial.commune_passage")


def execute(context):
    df_codes = context.stage("data.spatial.codes").copy()
    df_codes = df_codes[df_codes["iris_id"]!="CH"]

    requested_departements = df_codes["departement_id"].unique()

    with context.progress(label = "Reading BPE ...") as progress:
        parquet = pl.read_parquet("{}/{}".format(context.config("data_path"), context.config("bpe_path")), columns = [ "CAPACITE",
                        "DCIRIS", "LAMBERT_X", "LAMBERT_Y",
                        "TYPEQU", "DEPCOM", "DEP", "SIRET"
                    ],
                )

        parquet  = parquet.cast( dict(DEPCOM = str, DEP = str, DCIRIS = str, SIRET = str))
        dpts_str = [str(dep) for dep in requested_departements]
        parquet  = parquet.filter(pl.col("DEP").cast(pl.Utf8).is_in(dpts_str))

        progress.update(len(parquet))

    df = parquet.to_pandas()

    if context.config("apply_commune_passage"):
        # Older BPE edition in an older geography: translate communes and the
        # commune part of the IRIS codes; IRIS that do not exist anymore are
        # made undefined in data.bpe.cleaned
        passage = context.stage("data.spatial.commune_passage")
        df["DEPCOM"] = commune_passage.translate_communes(df["DEPCOM"], passage)
        df["DCIRIS"] = commune_passage.translate_iris(df["DCIRIS"], passage)

    return df


def validate(context):
    if not os.path.exists("%s/%s" % (context.config("data_path"), context.config("bpe_path"))):
        raise RuntimeError("BPE data is not available")

    return os.path.getsize("%s/%s" % (context.config("data_path"), context.config("bpe_path")))
