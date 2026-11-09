"""The allergy overview (/allergy): one person's allergen-specific IgE
results, grouped by where each allergen comes from, with what each protein
family means and what the test cannot say.

Nothing here judges a value: the route hands :func:`overview` a ``judge``
that runs the reference engine (``reference.evaluate`` through the app's
``_reading_verdict``), and the page only groups, grades and explains.

The grading scale follows the assay.  A result whose laboratory printed the
ALEX cut-off (0.3 kUA/L) is graded on the ALEX report's five levels; every
other kUA/L result on the ImmunoCAP class scale read from the curated library.
The two are different instruments: an ALEX value is never given an ImmunoCAP
class, which is what the panel page used to do.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from .health import display_unit
from .i18n import format_date_localized, format_number_localized, plural_form, t
from .panels import ATTENTION_INTERPRETATIONS, BORDERLINE_INTERPRETATIONS
from .reference import range_text

TOTAL_IGE = "total-immunoglobulin-e"
#: The reference set the library applies to results printed with the ALEX cut-off.
ALEX_SOURCE_ID = "madx-alex2-ifu"
ALEX_CUTOFF = 0.3
PLAN_URL = "/plan-tests?special=1&topic=allergy"

# --- sources ----------------------------------------------------------------
#
# Everything the page explains is traced to one of these.  Ids shared with
# data/reference_library.json name the same document there.
CITATIONS: dict[str, dict[str, str]] = {
    "eaaci-maug-2023": {
        "region": "EU", "publisher": "European Academy of Allergy and Clinical Immunology (EAACI)",
        "name": "EAACI Molecular Allergology User's Guide 2.0 (Dramburg S et al.)",
        "identifier": "Pediatr Allergy Immunol 2023;34 Suppl 28:e13854; doi:10.1111/pai.13854; PMID 37186333",
        "url": "https://pubmed.ncbi.nlm.nih.gov/37186333/",
    },
    "eaaci-food-allergy-2023": {
        "region": "EU", "publisher": "European Academy of Allergy and Clinical Immunology (EAACI)",
        "name": "EAACI guidelines on the diagnosis of IgE-mediated food allergy (Santos AF et al.)",
        "identifier": "Allergy 2023;78:3057-3076; doi:10.1111/all.15902; PMID 37815205",
        "url": "https://pubmed.ncbi.nlm.nih.gov/37815205/",
    },
    "aaaai-pfas-2024": {
        "region": "US", "publisher": "American Academy of Allergy, Asthma & Immunology (AAAAI)",
        "name": "An International Delphi Consensus on the Management of Pollen-Food Allergy Syndrome: "
                "a Work Group Report of the AAAAI Adverse Reactions to Foods Committee (Al-Shaikhly T et al.)",
        "identifier": "J Allergy Clin Immunol Pract 2024;12:3242-9; doi:10.1016/j.jaip.2024.09.037",
        "url": "https://doi.org/10.1016/j.jaip.2024.09.037",
    },
    "nih-niaid-food-allergy-2010": {
        "region": "US", "publisher": "National Institutes of Health / National Institute of Allergy and Infectious Diseases",
        "name": "Guidelines for the Diagnosis and Management of Food Allergy in the United States: "
                "NIAID-sponsored Expert Panel Report",
        "identifier": "J Allergy Clin Immunol 2010;126(6 Suppl):S1-58; doi:10.1016/j.jaci.2010.10.007; PMC4241958",
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC4241958/",
    },
    "moz-ukpmd-asthma-2026": {
        "region": "UA", "publisher": "Міністерство охорони здоров’я України / ДП «Державний експертний центр МОЗ України»",
        "name": "Уніфікований клінічний протокол первинної, спеціалізованої та екстреної медичної допомоги "
                "«Бронхіальна астма у дорослих»",
        "identifier": "Наказ МОЗ України від 30.09.2026 № 1451; реєстр МТД ДЕЦ, ГС 2026-1451",
        "url": "https://www.dec.gov.ua/files/ypTNWUEis6/dn_1451_30092026_dod.pdf",
    },
    "moz-916-2015": {
        "region": "UA", "publisher": "Міністерство охорони здоров’я України / ДЕЦ",
        "name": "Наказ МОЗ України від 30.12.2015 № 916: УКПМД «Медикаментозна алергія, включаючи анафілаксію»",
        "identifier": "Наказ МОЗ України № 916 від 30.12.2015",
        "url": "https://www.dec.gov.ua/wp-content/uploads/images/dodatki/2015_916_MA/2015_916_YKPMD_MA.pdf",
    },
    "madx-alex2-ifu": {
        "region": "INT", "publisher": "MacroArray Diagnostics (MADx), Vienna - manufacturer",
        "name": "ALEX² Allergy Xplorer - Instrucciones de uso",
        "identifier": "02-IFU-01-ES-04",
        "url": "https://a.storyblok.com/f/164899/x/fb679f3c5a/02-ifu-01-es-04-alex.pdf",
    },
    "alex-levels-2022": {
        "region": "EU", "publisher": "Clinical and Molecular Allergy (peer-reviewed; Sonneveld LJH et al.)",
        "name": "ALEX versus ISAC multiplex array in analyzing food allergy in atopic children",
        "identifier": "Clin Mol Allergy 2022;20:10; doi:10.1186/s12948-022-00177-w; PMC9419344",
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC9419344/",
    },
    "sige-class-2018": {
        "region": "US", "publisher": "Ann Allergy Asthma Immunol (peer-reviewed review, PMC6275558)",
        "name": "Precision medicine allergy immunoassay methods for assessing IgE sensitization to aeroallergen "
                "molecules (specific-IgE class 0-6 definitions)",
        "identifier": "Ann Allergy Asthma Immunol 2018; PMC6275558",
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC6275558/",
    },
    "who-iuis-nomenclature-2018": {
        "region": "INT", "publisher": "WHO/IUIS Allergen Nomenclature Sub-Committee (Pomés A et al.)",
        "name": "WHO/IUIS Allergen Nomenclature: Providing a common language",
        "identifier": "Mol Immunol 2018;100:3-13; doi:10.1016/j.molimm.2018.03.003; PMC6019191",
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC6019191/",
    },
}

#: Which sources stand behind each explanation block on the page.
BLOCK_SOURCES: dict[str, tuple[str, ...]] = {
    "caveat": ("nih-niaid-food-allergy-2010", "eaaci-food-allergy-2023", "moz-ukpmd-asthma-2026",
               "moz-916-2015", "madx-alex2-ifu"),
    "total_ige": ("nih-niaid-food-allergy-2010", "madx-alex2-ifu"),
    "scale_alex": ("madx-alex2-ifu", "alex-levels-2022"),
    "scale_immunocap": ("sige-class-2018",),
    "codes": ("who-iuis-nomenclature-2018", "eaaci-maug-2023"),
    "next": ("nih-niaid-food-allergy-2010", "eaaci-food-allergy-2023", "moz-ukpmd-asthma-2026"),
}

# --- where each allergen comes from ----------------------------------------
#
# Group order is the order a person scans: what they breathe, then what they
# eat, then the rest.  The grouping is taxonomic and makes no clinical claim.
GROUPS = (
    "grass_pollen", "tree_pollen", "weed_pollen", "mites", "animals", "moulds", "insects",
    "legumes", "cereals", "spices", "fruits", "vegetables", "nuts_seeds", "milk", "egg",
    "fish_seafood", "meat", "latex", "other",
)

# ``codes|group|source``: the WHO/IUIS genus-species code (with a component
# number or a printed ``_suffix`` where one species is several sources), the
# group, and the source key whose name lives in messages_allergy.py as
# ``allergen.<source>``.  The most specific code wins: ``Cor a 1.0401`` is
# hazelnut, ``Cor a 1.0103`` hazel pollen.
_SOURCE_TABLE = """
Cyn d|grass_pollen|cyn_d
Lol p|grass_pollen|lol_p
Pas n|grass_pollen|pas_n
Phl p|grass_pollen|phl_p
Phr c|grass_pollen|phr_c
Sec c_pollen|grass_pollen|sec_c_pollen
Aca m|tree_pollen|aca_m
Ail a|tree_pollen|ail_a
Aln g|tree_pollen|aln_g
Bet v|tree_pollen|bet_v
Bro pa|tree_pollen|bro_pa
Cor a_pollen,Cor a 1.0101,Cor a 1.0103,Cor a 1.0104|tree_pollen|cor_a_pollen
Cry j|tree_pollen|cry_j
Cup a|tree_pollen|cup_a
Cup s|tree_pollen|cup_s
Fag s|tree_pollen|fag_s
Fra e|tree_pollen|fra_e
Jug r_pollen|tree_pollen|jug_r_pollen
Jun a|tree_pollen|jun_a
Mor r|tree_pollen|mor_r
Ole e|tree_pollen|ole_e
Pho d|tree_pollen|pho_d
Pla a|tree_pollen|pla_a
Pop n|tree_pollen|pop_n
Ulm c|tree_pollen|ulm_c
Ama r|weed_pollen|ama_r
Amb a|weed_pollen|amb_a
Art v|weed_pollen|art_v
Can s|weed_pollen|can_s
Che a|weed_pollen|che_a
Mer a|weed_pollen|mer_a
Par j|weed_pollen|par_j
Pla l|weed_pollen|pla_l
Sal k|weed_pollen|sal_k
Urt d|weed_pollen|urt_d
Der f|mites|der_f
Der p|mites|der_p
Aca s|mites|aca_s
Blo t|mites|blo_t
Gly d|mites|gly_d
Lep d|mites|lep_d
Tyr p|mites|tyr_p
Can f,Can f_Fd1,Can f_male|animals|can_f
Cav p|animals|cav_p
Fel d|animals|fel_d
Mus m|animals|mus_m
Ory c|animals|ory_c
Phod s|animals|phod_s
Rat n|animals|rat_n
Bos d 2,Bos d_epithelia|animals|bos_d_dander
Cap h_epithelia|animals|cap_h_dander
Equ c,Equ c_epithelia|animals|equ_c
Ovi a_epithelia|animals|ovi_a_dander
Sus d_epithelia|animals|sus_d_dander
Mala s|moulds|mala_s
Sac c|moulds|sac_c
Alt a|moulds|alt_a
Asp f|moulds|asp_f
Cla h|moulds|cla_h
Pen ch|moulds|pen_ch
Api m|insects|api_m
Dol spp|insects|dol_spp
Pol d|insects|pol_d
Ves v|insects|ves_v
Sol spp|insects|sol_spp
Bla g|insects|bla_g
Per a|insects|per_a
Ara h|legumes|ara_h
Cic a|legumes|cic_a
Gly m|legumes|gly_m
Len c|legumes|len_c
Pha v|legumes|pha_v
Pis s|legumes|pis_s
Lup a|legumes|lup_a
Ave s|cereals|ave_s
Che q|cereals|che_q
Fag e|cereals|fag_e
Hor v|cereals|hor_v
Ory s|cereals|ory_s
Pan m|cereals|pan_m
Sec c,Sec c_flour|cereals|sec_c_flour
Tri a|cereals|tri_a
Tri s|cereals|tri_s
Zea m|cereals|zea_m
Cap a|spices|cap_a
Car c|spices|car_c
Ori v|spices|ori_v
Pet c|spices|pet_c
Pim a|spices|pim_a
Sin,Sin a|spices|sin_a
Tri fo|spices|tri_fo
Act d|fruits|act_d
Car p|fruits|car_p
Cit s|fruits|cit_s
Cuc m|fruits|cuc_m
Fic c|fruits|fic_c
Fra a|fruits|fra_a
Mal d|fruits|mal_d
Man i|fruits|man_i
Mus a|fruits|mus_a
Pers a|fruits|pers_a
Pru av|fruits|pru_av
Pru p|fruits|pru_p
Pyr c|fruits|pyr_c
Vac m|fruits|vac_m
Vit v|fruits|vit_v
All c|vegetables|all_c
All s|vegetables|all_s
Api g|vegetables|api_g
Dau c|vegetables|dau_c
Sol t|vegetables|sol_t
Sola l|vegetables|sola_l
Ana o|nuts_seeds|ana_o
Ber e|nuts_seeds|ber_e
Car i|nuts_seeds|car_i
Cor a|nuts_seeds|cor_a
Jug r|nuts_seeds|jug_r
Mac i,Mac inte|nuts_seeds|mac_i
Pis v|nuts_seeds|pis_v
Pru du|nuts_seeds|pru_du
Cuc p|nuts_seeds|cuc_p
Hel a|nuts_seeds|hel_a
Pap s|nuts_seeds|pap_s
Ses i|nuts_seeds|ses_i
Bos d,Bos d_milk,Bos d 4,Bos d 5,Bos d 8|milk|bos_d_milk
Cam d|milk|cam_d
Cap h_milk|milk|cap_h_milk
Equ c_milk|milk|equ_c_milk
Ovi a_milk|milk|ovi_a_milk
Gal d,Gal d_white,Gal d 1,Gal d 2,Gal d 3,Gal d 4|egg|gal_d_white
Gal d_yolk,Gal d 5|egg|gal_d_yolk
Ani s|fish_seafood|ani_s
Chi spp|fish_seafood|chi_spp
Clu h|fish_seafood|clu_h
Cra c|fish_seafood|cra_c
Cyp c|fish_seafood|cyp_c
Gad c,Gad m|fish_seafood|gad_m
Hom g|fish_seafood|hom_g
Lit s|fish_seafood|lit_s
Lol spp|fish_seafood|lol_spp
Myt e|fish_seafood|myt_e
Ost e|fish_seafood|ost_e
Pan b|fish_seafood|pan_b
Pec spp|fish_seafood|pec_spp
Pen m|fish_seafood|pen_m
Raj c|fish_seafood|raj_c
Rud spp|fish_seafood|rud_spp
Sal s|fish_seafood|sal_s
Sco s|fish_seafood|sco_s
Thu a|fish_seafood|thu_a
Xip g|fish_seafood|xip_g
Bos d_meat,Bos d 6|meat|bos_d_meat
Equ c_meat|meat|equ_c_meat
Gal d_meat|meat|gal_d_meat
Mel g|meat|mel_g
Ory_meat|meat|ory_meat
Ovi a_meat|meat|ovi_a_meat
Sus d,Sus d_meat,Sus d 1|meat|sus_d_meat
Ach d|meat|ach_d
Loc m|meat|loc_m
Ten m|meat|ten_m
Hev b|latex|hev_b
Fic b|other|fic_b
Hom s|other|hom_s
Arg r|other|arg_r
"""
SOURCES: dict[str, tuple[str, str]] = {}
SOURCE_GROUP: dict[str, str] = {}
for _line in _SOURCE_TABLE.strip().splitlines():
    _codes, _group, _source = _line.split("|")
    SOURCE_GROUP[_source] = _group
    for _code in _codes.split(","):
        SOURCES[_code] = (_group, _source)
del _line, _codes, _group, _source, _code

#: A WHO/IUIS code as printed: genus, species, then a component number or a
#: ``_suffix`` naming which part of the species (``Bos d_milk``).  The species
#: may be absent (``Ory_meat``, ``Sin``) or ``spp``.
CODE_RE = re.compile(
    r"\b([A-Z][a-z]{1,3})(?: ([a-z]{1,4})\.?)?(?:_([A-Za-z][A-Za-z0-9]*))?(?: (\d+(?:\.\d+)?(?:\+\d+)?))?(?=[\s,;)]|$)"
)


def _code_keys(match: re.Match) -> list[str]:
    genus, species, suffix, number = match.groups()
    base = f"{genus} {species}" if species else genus
    keys = []
    if number:
        keys.append(f"{base} {number}")
        if "." in number:  # an isoform: Cor a 1.0401
            keys.append(f"{base} {number.split('.')[0]}")
    if suffix:
        keys.append(f"{base}_{suffix}")
    keys.append(base)
    return keys


def parse_name(name: str) -> dict[str, object]:
    """Split a printed allergen name into the code text to show verbatim, the
    allergen source and whether it is a single molecule (a component)."""
    matches = list(CODE_RE.finditer(name))
    # A printed suffix names the row itself; an earlier code is usually a note
    # inside it («Сеча собаки (вкл. Can f 5) Can f_male urine»).
    chosen = next((m for m in matches if m.group(3)), matches[0] if matches else None)
    source = None
    if chosen:
        for key in _code_keys(chosen):
            if key in SOURCES:
                source = SOURCES[key][1]
                break
    if source is None:
        source = _source_by_name(name)
    if matches:
        start = matches[0].start()
        # Keep a bracket the code sits in, so no printed code is dropped.
        opening = name.rfind("(", 0, start)
        if opening != -1 and name.find(")", opening) > start:
            start = opening
        code_text = name[start:].strip()
    else:
        code_text = ""
    # A number marks a single protein; so does a printed protein name after
    # the code, unless the code's suffix already names a part of the source
    # («Can f_male urine» is an extract, «Can f_Fd1 Uteroglobin» a protein).
    suffix = (chosen.group(3) or "") if chosen else ""
    component = bool(chosen and (chosen.group(4) or (
        name[chosen.end():].strip() and (not suffix or any(ch.isdigit() for ch in suffix)))))
    return {"code_text": code_text, "source": source, "component": component}


def _source_by_name(name: str) -> str | None:
    """A row printed without a code («Подорожник ланцетолистий») is matched by
    its own words against the source names in both languages."""
    from .locales.messages_allergy import MESSAGES

    folded = _fold(name)
    for source in SOURCE_GROUP:
        entry = MESSAGES.get(f"allergen.{source}") or {}
        for text in entry.values():
            head = _fold(text.split(" (")[0])
            if head and (folded.startswith(head) or head.startswith(folded)):
                return source
    return None


def _fold(text: str) -> str:
    return re.sub(r"[’ʼ`']", "'", str(text or "")).casefold().strip()


# --- protein families -------------------------------------------------------
#
# Matched on the family the laboratory printed after the code, or on the
# component code itself for main (marker) allergens whose printed family
# («Cysteine protease») is shared with unrelated proteins (kiwi Act d 1).
FAMILIES: dict[str, dict[str, tuple[str, ...]]] = {
    "pr10": {"words": ("PR-10",), "sources": ("eaaci-maug-2023", "aaaai-pfas-2024")},
    "ltp": {"words": ("LTP",), "sources": ("eaaci-maug-2023", "aaaai-pfas-2024")},
    "profilin": {"words": ("Profilin",), "sources": ("eaaci-maug-2023", "aaaai-pfas-2024")},
    "polcalcin": {"words": ("Polcalcin",), "sources": ("eaaci-maug-2023",)},
    "storage": {"words": ("2S Albumin", "7/8S Globulin", "11S Globulin", "7S Globulin"),
                "sources": ("eaaci-maug-2023", "eaaci-food-allergy-2023")},
    "tropomyosin": {"words": ("Tropomyosin",), "sources": ("eaaci-maug-2023",)},
    "parvalbumin": {"words": ("Parvalbumin",), "sources": ("eaaci-maug-2023",)},
    "serum_albumin": {"words": ("Serum Albumin",), "sources": ("eaaci-maug-2023",)},
    "lipocalin": {"words": ("Lipocalin",), "sources": ("eaaci-maug-2023",)},
    "secretoglobin": {"words": ("Uteroglobin",), "sources": ("eaaci-maug-2023",)},
    "milk": {"words": ("Casein", "Lactoglobulin", "Lactalbumin"),
             "sources": ("eaaci-maug-2023", "eaaci-food-allergy-2023")},
    "egg": {"words": ("Ovomucoid", "Ovalbumin", "Ovotransferrin", "Lysozym"),
            "sources": ("eaaci-maug-2023", "eaaci-food-allergy-2023")},
    "omega5": {"words": ("Omega-5",), "sources": ("eaaci-maug-2023",)},
    "venom": {"words": ("Phospholipase", "Antigen 5", "Icarapin"), "sources": ("eaaci-maug-2023", "madx-alex2-ifu")},
    "marker": {"words": ("Expansin", "Grass Group", "Pectate Lyase", "Ole e 1-Family", "Plant Defensin",
                         "Pectin Methylesterase", "Alt a 1-Family"),
               "codes": ("Der p 1", "Der p 2", "Der f 1", "Der f 2", "Der p 23", "Blo t 5"),
               "sources": ("eaaci-maug-2023",)},
    "ccd": {"words": ("CCD",), "sources": ("eaaci-maug-2023", "madx-alex2-ifu")},
}


def families_of(code_text: str) -> list[str]:
    found = []
    for key, family in FAMILIES.items():
        if any(word.casefold() in code_text.casefold() for word in family["words"]) or any(
            re.match(re.escape(code) + r"(?!\d)", code_text) for code in family.get("codes", ())
        ):
            found.append(key)
    return found


# --- grading scales ---------------------------------------------------------

#: The five levels the ALEX report prints under its results («< 0,3 kUA/L
#: Негативний або невизначений ... > 15 kUA/L Дуже високий рівень IgE»),
#: restated by Sonneveld et al. 2022.  Lower bounds are inclusive.
ALEX_LEVELS = ((None, 0.3), (0.3, 1.0), (1.0, 5.0), (5.0, 15.0), (15.0, None))


def alex_legend() -> list[dict[str, object]]:
    """The ALEX levels in the shape of the app's class legend."""
    return [
        {"class": index, "lower": low, "upper": high, "key": f"alex_{index}",
         "range_text": range_text(low, high, "kUA/L", high_inclusive=False), "label": t(f"allergy.cap_alex_{index}")}
        for index, (low, high) in enumerate(ALEX_LEVELS)
    ]


def immunocap_legend(connection) -> list[dict[str, object]]:
    """The ImmunoCAP classes, read from the curated library, never typed."""
    legend = []
    for row in connection.execute(
        """SELECT DISTINCT label, lower_bound, upper_bound, unit FROM curated_reference_rules
           WHERE label LIKE 'Class %' ORDER BY COALESCE(lower_bound, -1)"""
    ):
        match = re.match(r"Class (\d)", str(row["label"]))
        if match:
            number = int(match.group(1))
            legend.append({"class": number, "lower": row["lower_bound"], "upper": row["upper_bound"],
                           "key": str(number),
                           "range_text": range_text(row["lower_bound"], row["upper_bound"], row["unit"], high_inclusive=False),
                           "label": t(f"allergy.cap_{number}")})
    return legend


def level_of(value: float | None, legend: list[dict[str, object]]) -> dict[str, object] | None:
    if value is None:
        return None
    for entry in legend:
        low, high = entry["lower"], entry["upper"]
        if (low is None or value >= float(low)) and (high is None or value < float(high)):
            return entry
    return None


def is_alex(vendor_high: float | None) -> bool:
    """The same signal the reference library uses to apply the ALEX cut-off."""
    return vendor_high is not None and abs(float(vendor_high) - ALEX_CUTOFF) < 1e-9


def _status(verdict: dict[str, object]) -> str:
    reading = str(verdict.get("interpretation") or "unjudged")
    if reading in ATTENTION_INTERPRETATIONS:
        return "positive"
    if reading in BORDERLINE_INTERPRETATIONS:
        return "uncertain"
    if reading in {"negative", "normal", "optimal"}:
        return "negative"
    return "unjudged"


# --- the page ---------------------------------------------------------------

_ROWS_SQL = """
SELECT o.*, o.rowid AS row_order, c.canonical_name, c.preferred_unit, d.title AS document_title, v.canonical_name AS vendor
FROM observations o
JOIN concepts c ON c.id = o.concept_id
LEFT JOIN documents d ON d.id = o.document_id
LEFT JOIN vendors v ON v.id = d.vendor_id
WHERE o.owner_user_id = ? AND c.category = 'allergy' AND o.verification_status <> 'rejected'
ORDER BY o.observed_at, o.document_id, o.page_number, o.rowid
"""


def _citations(ids) -> list[dict[str, str]]:
    return [{"id": key, **CITATIONS[key]} for key in dict.fromkeys(ids)]


def _test_name(title: str, alex: bool) -> str:
    match = re.search(r"ALEX\s*([²³23])?", title or "")
    if match:
        return t("allergy.page.test_alex", name="ALEX" + {"2": "²", "3": "³"}.get(match.group(1) or "", match.group(1) or ""))
    return t("allergy.page.test_alex", name="ALEX") if alex else t("allergy.page.test_generic")


def _value_text(row, reading: Callable) -> str:
    unit = display_unit(row["unit_canonical"] or row["unit_raw"])
    return f"{reading(row)} {unit}".strip()


def overview(connection, owner_id: str, *, judge: Callable, reading: Callable, query: str = "") -> dict[str, object]:
    """Everything /allergy shows for one record.

    ``judge(row)`` returns the reference engine's verdict for an observation
    row; ``reading(row)`` the value as printed (comparator kept).
    """
    rows = [dict(row) for row in connection.execute(_ROWS_SQL, (owner_id,))]
    cap_legend = immunocap_legend(connection)
    tests: dict[tuple, dict[str, object]] = {}
    by_concept: dict[str, list[dict[str, object]]] = {}
    total_ige: list[dict[str, object]] = []

    for row in rows:
        verdict = judge(row)
        key = (row["document_id"] or row["report_id"] or "manual", row["observed_at"])
        alex = is_alex(row["vendor_reference_high"])
        test = tests.setdefault(key, {
            "date": row["observed_at"], "date_text": format_date_localized(row["observed_at"]),
            "vendor": row["vendor"] or "", "document_url": f"/documents/{row['document_id']}" if row["document_id"] else "",
            "title": row["document_title"] or "", "alex": False, "allergens": 0, "positive": 0, "uncertain": 0,
            "highest": None, "highest_text": "",
        })
        entry = {
            "row": row, "verdict": verdict, "status": _status(verdict), "test": test,
            "value_text": _value_text(row, reading), "date_text": test["date_text"],
        }
        if row["concept_id"] == TOTAL_IGE:
            total_ige.append(entry)
            continue
        legend = alex_legend() if alex else cap_legend if (row["unit_canonical"] or "").casefold() == "kua/l" else []
        level = level_of(row["value_numeric"], legend)
        entry["level"] = level["label"] if level else ""
        entry["level_rank"] = level["class"] if level else -1
        test["alex"] = test["alex"] or alex
        test["allergens"] += 1
        test["positive"] += entry["status"] == "positive"
        test["uncertain"] += entry["status"] == "uncertain"
        if row["value_numeric"] is not None and not str(row["comparator"] or "").startswith("<") and (
            test["highest"] is None or row["value_numeric"] > test["highest"]
        ):
            test["highest"], test["highest_text"] = row["value_numeric"], entry["value_text"]
        by_concept.setdefault(row["concept_id"], []).append(entry)

    ordered_tests = sorted(tests.values(), key=lambda item: str(item["date"] or ""), reverse=True)
    for test in ordered_tests:
        test["name"] = _test_name(str(test["title"]), bool(test["alex"]))
    allergen_tests = [test for test in ordered_tests if test["allergens"]]
    latest_test = allergen_tests[0] if allergen_tests else None

    items = []
    for concept_id, entries in by_concept.items():
        current = entries[-1]
        row = current["row"]
        parsed = parse_name(str(row["canonical_name"] or row["raw_name"] or ""))
        source = parsed["source"]
        group = SOURCE_GROUP.get(source or "", "other")
        families = families_of(str(parsed["code_text"]))
        items.append({
            "concept_id": concept_id, "url": f"/metrics/{concept_id}",
            "code_text": parsed["code_text"] or str(row["raw_name"] or row["canonical_name"]),
            "printed": str(row["raw_name"] or row["canonical_name"] or ""),
            "component": parsed["component"], "source": source, "group": group,
            "source_name": t(f"allergen.{source}") if source else str(row["raw_name"] or row["canonical_name"]),
            "families": families, "family_names": [t(f"allergy.family.{key}.name") for key in families],
            "value_text": current["value_text"], "value": row["value_numeric"], "status": current["status"],
            "level": current["level"], "level_rank": current["level_rank"],
            "unverified": row["verification_status"] == "extracted",
            "date_text": current["date_text"], "latest": current["test"] is latest_test,
            "history": [{"date_text": e["date_text"], "value_text": e["value_text"], "status": e["status"]}
                        for e in reversed(entries[:-1])],
            "order": row["row_order"],
        })

    groups = _groups(items)
    positives = [item for item in items if item["status"] in ("positive", "uncertain")]
    positives.sort(key=lambda item: (item["status"] != "positive", -item["level_rank"], -(item["value"] or 0)))
    family_view = _families(items)
    total = _total_ige(total_ige)
    scale_alex = any(test["alex"] for test in allergen_tests)
    scale_cap = any(not test["alex"] for test in allergen_tests)
    used = [*BLOCK_SOURCES["caveat"], *BLOCK_SOURCES["codes"], *BLOCK_SOURCES["next"]]
    if total:
        used += BLOCK_SOURCES["total_ige"]
    if scale_alex:
        used += BLOCK_SOURCES["scale_alex"]
    if scale_cap:
        used += BLOCK_SOURCES["scale_immunocap"]
    used += [source for family in family_view for source in FAMILIES[family["key"]]["sources"]]
    return {
        "has_results": bool(items) or bool(total),
        "tests": ordered_tests,
        "latest": latest_test,
        "several_tests": len(allergen_tests) > 1,
        "items_count": len(items),
        "groups": groups,
        "positives": positives,
        "families": family_view,
        "total_ige": total,
        "scales": ([{"key": "alex", "levels": alex_legend(), "sources": _citations(BLOCK_SOURCES["scale_alex"])}]
                   if scale_alex else [])
        + ([{"key": "immunocap", "levels": cap_legend, "sources": _citations(BLOCK_SOURCES["scale_immunocap"])}]
           if scale_cap and cap_legend else []),
        "search": _search(items, query),
        "block_sources": {key: _citations(ids) for key, ids in BLOCK_SOURCES.items()},
        "sources": _citations(used),
        "plan_url": PLAN_URL,
        "cutoff_text": f"{format_number_localized(ALEX_CUTOFF)} {display_unit('kUA/L')}" if scale_alex else "",
    }


def _groups(items: list[dict[str, object]]) -> list[dict[str, object]]:
    by_group: dict[str, dict[str, list]] = {}
    for item in items:
        by_group.setdefault(item["group"], {}).setdefault(item["source"] or item["printed"], []).append(item)
    groups = []
    for key in GROUPS:
        sources = by_group.get(key)
        if not sources:
            continue
        cards = []
        for members in sources.values():
            members.sort(key=lambda item: (item["component"], item["order"]))
            positive = sum(item["status"] == "positive" for item in members)
            uncertain = sum(item["status"] == "uncertain" for item in members)
            cards.append({"name": members[0]["source_name"], "items": members, "positive": positive,
                          "uncertain": uncertain, "status": "positive" if positive else "uncertain" if uncertain else
                          "negative" if all(item["status"] == "negative" for item in members) else "unjudged"})
        cards.sort(key=lambda card: (card["status"] not in ("positive", "uncertain"), min(i["order"] for i in card["items"])))
        tested = sum(len(card["items"]) for card in cards)
        positive = sum(card["positive"] for card in cards)
        groups.append({"key": key, "name": t(f"allergy.page.group.{key}"), "sources": cards,
                       "source_count": len(cards), "tested": tested, "positive": positive,
                       "uncertain": sum(card["uncertain"] for card in cards)})
    groups.sort(key=lambda group: not (group["positive"] or group["uncertain"]))
    return groups


def _families(items: list[dict[str, object]]) -> list[dict[str, object]]:
    view = []
    for key in FAMILIES:
        members = [item for item in items if key in item["families"]]
        if not members:
            continue
        positive = [item for item in members if item["status"] in ("positive", "uncertain")]
        view.append({
            "key": key, "name": t(f"allergy.family.{key}.name"), "what": t(f"allergy.family.{key}.what"),
            "means": t(f"allergy.family.{key}.means"), "tested": len(members), "positive": len(positive),
            "codes": [item["code_text"] for item in members],
            "positive_codes": [item["code_text"] for item in positive],
            "sources": _citations(FAMILIES[key]["sources"]),
        })
    view.sort(key=lambda family: not family["positive"])
    return view


def _total_ige(entries: list[dict[str, object]]) -> dict[str, object] | None:
    if not entries:
        return None
    current = entries[-1]
    row, verdict = current["row"], current["verdict"]
    return {
        "value_text": current["value_text"], "date_text": current["date_text"], "status": current["status"],
        "interpretation": str(verdict.get("interpretation") or "unjudged"),
        "label": str(verdict.get("label") or ""), "reference_text": _printed_range(row) or str(verdict.get("range_text") or ""),
        "url": f"/metrics/{TOTAL_IGE}",
        "history": [{"date_text": e["date_text"], "value_text": e["value_text"]} for e in reversed(entries[:-1])],
        "sources": _citations(BLOCK_SOURCES["total_ige"]),
    }


def _printed_range(row) -> str:
    """The laboratory's interval with the comparator it printed («< 100»)."""
    low, high = row["vendor_reference_low"], row["vendor_reference_high"]
    if low is None and high is None:
        return ""
    def inclusive(flag):
        return True if flag is None else bool(flag)
    return range_text(low, high, row["unit_canonical"] or row["unit_raw"],
                      inclusive(row["vendor_reference_low_inclusive"]), inclusive(row["vendor_reference_high_inclusive"]))


def _search(items: list[dict[str, object]], query: str) -> dict[str, object] | None:
    """"Was I tested for cat?": source names in both languages, the printed
    name, the codes and the group name all answer, whatever the page locale."""
    from .locales.messages_allergy import MESSAGES

    needle = _fold(query)[:80]
    if not needle:
        return None
    found: dict[str, dict[str, object]] = {}
    for item in items:
        names = MESSAGES.get(f"allergen.{item['source']}", {}) if item["source"] else {}
        group = MESSAGES.get(f"allergy.page.group.{item['group']}", {})
        haystack = " | ".join([*names.values(), *group.values(), item["printed"], item["code_text"]])
        if needle in _fold(haystack):
            card = found.setdefault(item["source"] or item["printed"], {
                "name": item["source_name"], "group": t(f"allergy.page.group.{item['group']}"), "items": []})
            card["items"].append(item)
    results = list(found.values())
    for card in results:
        statuses = {item["status"] for item in card["items"]}
        card["status"] = "positive" if "positive" in statuses else "uncertain" if "uncertain" in statuses else (
            "negative" if statuses == {"negative"} else "unjudged")
    results.sort(key=lambda card: card["status"] not in ("positive", "uncertain"))
    return {"query": query.strip()[:80], "results": results,
            "summary": _plural("allergy.page.search_found", len(results), query=query.strip()[:80])}


def _plural(key: str, count: int, **values) -> str:
    """A plural message with the count shown localised (``1 000``), not raw."""
    return t(f"{key}_{plural_form(count)}", **{"count": format_number_localized(count, 0), **values})


def headline(view: dict[str, object]) -> dict[str, str]:
    """The answer in one sentence, for the latest allergen test."""
    test = view.get("latest")
    if not test:
        return {}
    count = int(test["allergens"])
    if test["positive"] or test["uncertain"]:
        kind, number = ("positive", int(test["positive"])) if test["positive"] else ("uncertain", int(test["uncertain"]))
        title = _plural(f"allergy.page.headline_{kind}", number)
        body = _plural("allergy.page.headline_some_body", count)
        tone = kind
    else:
        title, tone = t("allergy.page.headline_none"), "negative"
        body = (_plural("allergy.page.headline_none_body", count, cutoff=view["cutoff_text"])
                if view.get("cutoff_text") else _plural("allergy.page.headline_none_body_lab", count))
    highest = (t("allergy.page.highest", value=test["highest_text"]) if test["highest_text"]
               else t("allergy.page.highest_none"))
    return {"title": title, "body": body, "highest": highest, "tone": tone}
