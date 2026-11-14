"""
Census year dependent coding of the French census (RP) detail files.

- TRANS (commute mode): up to RP2016, INSEE codes five modalities (1 no
  transport, 2 walk, 3 two-wheelers, 4 car, 5 public transport). From RP2017 on,
  bicycles and motorised two-wheelers are separated (3 bike, 4 motorcycle,
  5 car, 6 public transport). For the old coding, census_two_wheels_mode decides
  what two-wheelers become:
    - "bike", "motorcycle" or "car": all of them;
    - "split": bike or car, with the share of bicycles among two-wheelers of a
      more recent census (data.census.two_wheels_shares). Motorised two-wheelers
      become car, as in the OD flows.
- Socioprofessional category: up to RP2021, CS1 (PCS2003, 8 classes) is given
  directly. From RP2022 on, it is rebuilt from GS and STAT_GSEC (see
  data.census.cleaned).
"""

LAST_YEAR_OLD_TRANS = 2016
LAST_YEAR_CS1 = 2021

TWO_WHEELS_MODES = ("bike", "motorcycle", "car", "split")

# Temporary commute mode of two-wheelers to be split into bike and car
TWO_WHEELS = "two_wheels"


def uses_old_trans(census_year):
    return int(census_year) <= LAST_YEAR_OLD_TRANS


def uses_cs1(census_year):
    return int(census_year) <= LAST_YEAR_CS1


def splits_two_wheels(census_year, two_wheels_mode):
    return uses_old_trans(census_year) and two_wheels_mode == "split"


def check_two_wheels_mode(two_wheels_mode):
    if two_wheels_mode not in TWO_WHEELS_MODES:
        raise RuntimeError("census_two_wheels_mode must be one of %s, got %s" % (TWO_WHEELS_MODES, two_wheels_mode))


def census_commute_modes(census_year, two_wheels_mode = "bike"):
    """ Census (INDCVI) TRANS as string -> commute_mode; other codes (1, Z) mean no commute. """
    check_two_wheels_mode(two_wheels_mode)

    if uses_old_trans(census_year):
        two_wheels = TWO_WHEELS if two_wheels_mode == "split" else two_wheels_mode
        return { "2": "walk", "3": two_wheels, "4": "car", "5": "pt" }

    return { "2": "walk", "3": "bike", "4": "motorcycle", "5": "car", "6": "pt" }


def od_commute_modes(census_year, two_wheels_mode = "bike"):
    """ MOBPRO TRANS as integer -> commute_mode of the OD flows, where motorcycles count as car. """
    check_two_wheels_mode(two_wheels_mode)

    if uses_old_trans(census_year):
        two_wheels = { "bike": "bike", "split": TWO_WHEELS }.get(two_wheels_mode, "car")
        return { 1: "no transport", 2: "walk", 3: two_wheels, 4: "car", 5: "pt" }

    return { 1: "no transport", 2: "walk", 3: "bike", 4: "car", 5: "car", 6: "pt" }


def bike_shares(df, shares):
    """
    Share of bicycles among two-wheelers for each row of df (columns commune_id
    and departement_id): that of the commune if known, else of the departement.
    shares is the output of data.census.two_wheels_shares.
    """
    commune_shares, departement_shares = shares
    result = df["commune_id"].astype(str).map(commune_shares)
    result = result.fillna(df["departement_id"].astype(str).map(departement_shares))
    return result.fillna(departement_shares.mean()).values
