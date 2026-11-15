"""Public reference metadata for the blood-catalogue connection audit.

``extend`` changes only the supplied library dictionary. It reads no patient
records, preserves existing entries, adds no reference bands, and is idempotent.
The sources identify the quantities and the limits of interpreting them; a
manufacturer's parameter documentation is not presented as clinical guidance.
"""

from __future__ import annotations

from anamna.ingest.concepts import stable_concept_id


REVIEWED_AT = "2026-11-15"


def _source(key, region, publisher, name, url, identifier, *, official=True, note=None):
    source = {
        "id": key, "region": region, "publisher": publisher, "name": name,
        "url": url, "identifier": identifier, "reviewed_at": REVIEWED_AT,
        "official": official,
        "kind": "publication" if official else "manufacturer_documentation",
    }
    if note:
        source["access_note"] = note
    return source


SOURCES = (
    _source(
        "mayo-amino-acids-plasma-aaqp", "US", "Mayo Clinic Laboratories",
        "AAQP: Amino Acids, Quantitative, Plasma",
        "https://www.mayocliniclabs.com/test-catalog/Overview/9265",
        "AAQP; order LOINC 35083-5",
        note="Catalogue and interpretation sections read. Its intervals are age-dependent, Mayo-derived and intended for fasting specimens; they are not imported as universal targets.",
    ),
    _source(
        "loinc-amino-acids-serum-plasma-35083-5", "US", "Regenstrief Institute, LOINC",
        "Amino acids panel [Moles/volume] - Serum or Plasma",
        "https://loinc.org/35083-5/panel", "LOINC 35083-5 and its observation terms",
        note="Used for the identity, serum/plasma specimen and concentration dimension of the named observations, including carnosine, phosphoserine and phosphoethanolamine. It is a terminology source, not a reference interval or a source of treatment advice.",
    ),
    _source(
        "medlineplus-reticulocyte-count", "US", "US National Library of Medicine, MedlinePlus",
        "Reticulocyte Count",
        "https://medlineplus.gov/lab-tests/reticulocyte-count/",
        "MedlinePlus Medical Test: Reticulocyte Count",
    ),
    _source(
        "nlm-mesh-reticulocyte-count", "US", "US National Library of Medicine",
        "Reticulocyte Count: MeSH descriptor",
        "https://www.ncbi.nlm.nih.gov/mesh/68017701", "MeSH D017701",
        note="The descriptor distinguishes a count per blood volume, a percentage of erythrocytes and a corrected index. These forms are not combined into one series.",
    ),
    _source(
        "sysmex-reticulocyte-parameters", "EU", "Sysmex Europe",
        "RET diagnostic parameters: reticulocyte count and fluorescence fractions",
        "https://www.sysmex.fr/fileadmin/media/f100/Business_Lines/Haematology/Cards/12_RET_Card_EN.pdf",
        "Sysmex RET diagnostic parameter card, 12_RET_Card_EN", official=False,
        note="Indexed manufacturer PDF read for the identities of reticulocyte count and the three fluorescence groups. Direct PDF retrieval returned HTTP 403; no clinical cutoff is taken from it.",
    ),
    _source(
        "sysmex-reticulocyte-irf-formula", "EU", "Sysmex",
        "RET channel: immature reticulocyte fraction",
        "https://www.sysmex.co.uk/education/knowledge-centre/technologies/fluorescence-flow-cytometry/ret-channel/",
        "RET channel; IRF = MFR + HFR", official=False,
        note="The indexed manufacturer publication states that immature reticulocyte fraction is the sum of the medium- and high-fluorescence fractions. Full-page automated retrieval returned HTTP 403; no reference interval is taken from it.",
    ),
    _source(
        "isth-lupus-anticoagulant-detection-2020", "INT",
        "International Society on Thrombosis and Haemostasis, Scientific and Standardization Committee",
        "Update of the guidelines for lupus anticoagulant detection and interpretation",
        "https://onlinelibrary.wiley.com/doi/10.1111/jth.15047",
        "Devreese KMJ et al. J Thromb Haemost 2020;18:2828-2839; doi:10.1111/jth.15047",
        note="Full guidance read for distinct screening, mixing and confirmation steps; laboratory-specific cutoffs; and anticoagulant interference. No global cutoff or automatic diagnosis is assigned.",
    ),
    _source(
        "mayo-lupus-anticoagulant-algorithm-2025", "US", "Mayo Clinic Laboratories",
        "Lupus Anticoagulant Profile Testing Algorithm",
        "https://www.mayocliniclabs.com/en/-/media/it-mmfiles/Special%20Instructions/D/6/3/Lupus_Anticoagulant_Profile_Testing_Algorithm",
        "ALUPP / Lupus Anticoagulant Profile, Plasma; August 2025 algorithm",
        note="Used to preserve the distinction between clotting times, confirmatory testing and laboratory interpretation. Its assay cutoffs are not imported.",
    ),
    _source(
        "moz-nastanova-00107", "UA", "МОЗ України, Реєстр медико-технологічних документів",
        "Настанова 00107. Лабораторна оцінка тромбофілії",
        "https://guidelines.moz.gov.ua/documents/3010", "ebm00107; document 3010",
        note="Ukrainian-language indexed text identifies lupus anticoagulant testing and assay-specific boundaries. Full-page automated retrieval returned HTTP 503; no numerical threshold or retest interval is extracted.",
    ),
    _source(
        "ash-d-dimer-assays-2020", "US", "American Society of Hematology",
        "D-dimer Assays and Outcome Studies",
        "https://www.hematology.org/-/media/hematology/files/covid-19/d-dimer-assays.pdf",
        "ASH D-dimer assays table, posted 20 April 2020",
        note="Indexed published table lists assay-dependent reporting in FEU and DDU. Direct PDF retrieval returned HTTP 404. Used for preserving the calibration label, not for adopting one assay's exclusion threshold universally; corroborated by the RCPA manual.",
    ),
    _source(
        "rcpa-d-dimer-manual-2024", "INT", "Royal College of Pathologists of Australasia",
        "RCPA Manual: D-Dimer",
        "https://www.rcpa.edu.au/Manuals/RCPA-Manual/Pathology-Tests/D/D-Dimer",
        "RCPA Manual, D-Dimer, reviewed 2 January 2024",
        note="Indexed official text states that FEU and DDU are different calibrations and that cutoffs are not transferable between methods. Full-page automated retrieval returned HTTP 403.",
    ),
    _source(
        "nice-ng158-d-dimer", "EU", "National Institute for Health and Care Excellence",
        "Venous thromboembolic diseases: diagnosis, management and thrombophilia testing",
        "https://www.nice.org.uk/guidance/NG158/chapter/recommendations",
        "NICE NG158, recommendations 1.1.13-1.1.14",
        note="D-dimer is interpreted in a diagnostic pathway and may use an age-adjusted test threshold. No isolated universal healthy range is inferred.",
    ),
    _source(
        "medlineplus-complete-blood-count", "US", "US National Library of Medicine, MedlinePlus",
        "Complete Blood Count (CBC)",
        "https://medlineplus.gov/lab-tests/complete-blood-count-cbc/",
        "MedlinePlus Medical Test: Complete Blood Count",
    ),
)


# Molecules and their Ukrainian names, independent of any person's record.
AMINO_ACIDS = (
    ("Alanine", "Аланін"), ("Arginine", "Аргінін"), ("Asparagine", "Аспарагін"),
    ("Aspartic acid", "Аспарагінова кислота"), ("Valine", "Валін"),
    ("Histidine", "Гістидин"), ("Glycine", "Гліцин"), ("Glutamine", "Глутамін"),
    ("Glutamic acid", "Глутамінова кислота"), ("Homocitrulline", "Гомоцитрулін"),
    ("Hydroxylysine", "Гідроксилізин"), ("Hydroxyproline", "Гідроксипролін"),
    ("Isoleucine", "Ізолейцин"), ("Carnosine", "Карнозин"), ("Leucine", "Лейцин"),
    ("Lysine", "Лізин"), ("Methionine", "Метіонін"), ("Ornithine", "Орнітин"),
    ("Proline", "Пролін"), ("Sarcosine", "Саркозин"), ("Serine", "Серин"),
    ("Taurine", "Таурин"), ("Threonine", "Треонін"), ("Tryptophan", "Триптофан"),
    ("Tyrosine", "Тирозин"), ("Phenylalanine", "Фенілаланін"),
    ("Phosphoethanolamine", "Фосфоетаноламін"), ("Phosphoserine", "Фосфосерин"),
    ("Cystathionine", "Цистатіонін"), ("Cystine", "Цистин"), ("Citrulline", "Цитрулін"),
    ("1-Methylhistidine", "1-Метилгістидин"), ("3-Methylhistidine", "3-Метилгістидин"),
    ("Alpha-aminoadipic acid", "α-Аміноадипінова кислота"),
    ("Alpha-aminobutyric acid", "α-Аміномасляна кислота"), ("Beta-alanine", "β-Аланін"),
    ("Beta-aminoisobutyric acid", "β-Аміноізомасляна кислота"),
    ("Gamma-aminobutyric acid", "γ-Аміномасляна кислота"), ("Ethanolamine", "Етаноламін"),
)


def _entry(name, uk_name, unit, source_ids, description, uk_description, why, uk_why, reason, uk_reason):
    regions = {source["id"]: source["region"] for source in SOURCES}
    return {
        "concept_id": stable_concept_id(name), "canonical_name": name, "unit": unit,
        "kind": "no_universal_target", "bands": [],
        "source_id": source_ids[0], "source_ids": list(source_ids),
        "regions_covered": sorted({regions[key] for key in source_ids}),
        "agreement": "no_universal_target",
        "short_description": description, "why_it_matters": why,
        "no_universal_target_reason": reason,
        "retest_interval_months": None, "retest_rationale": None,
        "uk": {
            "name": uk_name, "short_description": uk_description,
            "why_it_matters": uk_why, "no_universal_target_reason": uk_reason,
            "band_labels": {},
        },
    }


def additions():
    """Build published guidance for 39 amino-acid and 12 blood-report targets."""
    entries = []
    aa_reason = (
        "The performing laboratory's method, age group, specimen and sampling conditions determine the reference interval. "
        "Mayo's published plasma intervals are laboratory-derived and intended for fasting specimens; they are not a universal serum/plasma target."
    )
    aa_reason_uk = (
        "Референтний інтервал залежить від методу лабораторії, вікової групи, біоматеріалу й умов забору. "
        "Опубліковані Mayo інтервали для плазми встановлені цією лабораторією для проб натще; це не універсальна норма для сироватки чи плазми."
    )
    for molecule, uk_molecule in AMINO_ACIDS:
        sources = ("loinc-amino-acids-serum-plasma-35083-5",)
        if molecule not in {"Carnosine", "Phosphoethanolamine", "Phosphoserine"}:
            sources += ("mayo-amino-acids-plasma-aaqp",)
        entries.append(_entry(
            f"{molecule}, serum or plasma", f"{uk_molecule}, сироватка або плазма", "µmol/L", sources,
            f"The concentration of {molecule.lower()} in serum or plasma, reported as part of an amino-acid and related-metabolite profile.",
            f"Концентрація речовини «{uk_molecule}» у сироватці або плазмі, визначена в профілі амінокислот і споріднених метаболітів.",
            "Interpret the pattern with the other profile components and the original laboratory's specimen, method and reference interval. A single component does not establish a metabolic diagnosis.",
            "Оцінюйте показник разом з іншими складовими профілю, біоматеріалом, методом і референтним інтервалом лабораторії. Окремий компонент не встановлює метаболічного діагнозу.",
            aa_reason, aa_reason_uk,
        ))
    retic_sources = ("medlineplus-reticulocyte-count", "nlm-mesh-reticulocyte-count")
    retic_reason = "Interpretation depends on the laboratory method, age and the accompanying hemoglobin and hematocrit. A percentage, an absolute count and a corrected index are distinct quantities; no single interval is assigned to all three."
    retic_reason_uk = "Оцінка залежить від методу лабораторії, віку та супутніх значень гемоглобіну й гематокриту. Відсоток, абсолютна кількість і скоригований індекс — різні показники; спільного інтервалу для них немає."
    for name, uk_name, unit, description, uk_description in (
        ("Reticulocytes", "Ретикулоцити, відносна кількість", "%",
         "The proportion of circulating red blood cells that are still immature reticulocytes.",
         "Частка циркулюючих еритроцитів, які ще є незрілими клітинами — ретикулоцитами."),
        ("Reticulocytes, absolute", "Ретикулоцити, абсолютна кількість", "10^9/L",
         "The number of immature red blood cells per volume of blood. This is separate from their percentage among all red blood cells.",
         "Кількість незрілих еритроцитів в одиниці об’єму крові. Це окремий показник від їхнього відсотка серед усіх еритроцитів."),
        ("Reticulocyte index", "Ретикулоцитарний індекс", "ratio",
         "The reticulocyte index as reported by the laboratory. The source's correction method must be known before equating it with a corrected reticulocyte percentage or a reticulocyte production index.",
         "Ретикулоцитарний індекс, повідомлений лабораторією. Перш ніж прирівнювати його до скоригованого відсотка ретикулоцитів чи індексу їх продукції, треба знати використаний метод корекції."),
    ):
        entries.append(_entry(name, uk_name, unit, retic_sources, description, uk_description,
                              "Read alongside the blood count to understand the bone marrow's red-cell production response.",
                              "Розглядайте разом із загальним аналізом крові, щоб оцінити відповідь кісткового мозку на потребу в еритроцитах.",
                              retic_reason, retic_reason_uk))
    fraction_sources = ("sysmex-reticulocyte-parameters", "sysmex-reticulocyte-irf-formula")
    for name, uk_name, description, uk_description in (
        ("Immature reticulocyte fraction", "Фракція незрілих ретикулоцитів",
         "The proportion of reticulocytes in the medium- and high-fluorescence groups on the analyzer. These groups reflect less mature cells.",
         "Частка ретикулоцитів із середньою та високою флуоресценцією на аналізаторі. Ці групи відповідають менш зрілим клітинам."),
        ("Reticulocytes, low fluorescence fraction", "Фракція ретикулоцитів із низькою флуоресценцією",
         "The low-fluorescence reticulocyte fraction, the analyzer's more mature reticulocyte population.",
         "Частка ретикулоцитів із низькою флуоресценцією — більш зрілої популяції ретикулоцитів за класифікацією аналізатора."),
        ("Reticulocytes, medium fluorescence fraction", "Фракція ретикулоцитів із середньою флуоресценцією",
         "The medium-fluorescence reticulocyte fraction, one component of the analyzer's immature reticulocyte fraction.",
         "Частка ретикулоцитів із середньою флуоресценцією — одна зі складових фракції незрілих ретикулоцитів на аналізаторі."),
        ("Reticulocytes, high fluorescence fraction", "Фракція ретикулоцитів із високою флуоресценцією",
         "The high-fluorescence reticulocyte fraction, the analyzer's least mature reticulocyte group.",
         "Частка ретикулоцитів із високою флуоресценцією — найменш зрілої групи ретикулоцитів за класифікацією аналізатора."),
    ):
        entries.append(_entry(name, uk_name, "%", fraction_sources, description, uk_description,
                              "These analyzer fractions describe red-cell production and are read with the reticulocyte count and the rest of the blood count.",
                              "Ці фракції аналізатора характеризують утворення еритроцитів; їх оцінюють разом із кількістю ретикулоцитів і рештою показників крові.",
                              "The populations and intervals depend on analyzer methodology and local validation. Manufacturer definitions do not establish a universal clinical target.",
                              "Визначення популяцій та інтервали залежать від методики аналізатора й перевірки в лабораторії. Опис виробника не встановлює універсальної клінічної норми."))
    la_sources = ("isth-lupus-anticoagulant-detection-2020", "mayo-lupus-anticoagulant-algorithm-2025", "moz-nastanova-00107")
    for name, uk_name, unit, description, uk_description in (
        ("Lupus anticoagulant screening time", "Вовчаковий антикоагулянт: час скринінгового тесту", "s",
         "The clotting time of the laboratory's lupus-anticoagulant screening test. It is one stage of a multistep assessment, not a diagnosis by itself.",
         "Час згортання у скринінговому тесті на вовчаковий антикоагулянт. Це один з етапів багатоступеневого дослідження, а не самостійний діагноз."),
        ("Lupus anticoagulant confirmation time", "Вовчаковий антикоагулянт: час підтверджувального тесту", "s",
         "The clotting time in the laboratory's confirmatory lupus-anticoagulant test, assessed alongside the screening and mixing studies.",
         "Час згортання у підтверджувальному тесті на вовчаковий антикоагулянт; його оцінюють разом зі скринінговим тестом і тестами змішування."),
        ("Lupus anticoagulant index", "Індекс вовчакового антикоагулянту", "index",
         "The lupus-anticoagulant index reported by the laboratory. Its formula and normalization belong to that assay; it is not assumed to be the raw screening time divided by confirmation time.",
         "Індекс вовчакового антикоагулянту, повідомлений лабораторією. Формула й нормалізація залежать від тесту; не можна вважати його простим відношенням скринінгового часу до підтверджувального."),
    ):
        entries.append(_entry(name, uk_name, unit, la_sources, description, uk_description,
                              "Read the laboratory's combined interpretation and consider anticoagulant interference. An isolated stage does not establish lupus or antiphospholipid syndrome.",
                              "Враховуйте сукупний висновок лабораторії та можливий вплив антикоагулянтів. Окремий етап не встановлює діагнозу вовчака чи антифосфоліпідного синдрому.",
                              "ISTH guidance requires method-specific locally established cutoffs and interpretation of the testing sequence. A universal clotting time or index cutoff is not assigned.",
                              "Настанова ISTH вимагає локально встановлених порогів для конкретного методу та оцінки послідовності тестів. Універсальний поріг часу згортання чи індексу не встановлюється."))
    entries.append(_entry(
        "D-dimer", "D-димер", "ng/mL FEU",
        ("ash-d-dimer-assays-2020", "rcpa-d-dimer-manual-2024", "nice-ng158-d-dimer"),
        "A marker of cross-linked fibrin breakdown. The FEU label means fibrinogen-equivalent units and must remain distinct from D-dimer units (DDU).",
        "Маркер розщеплення зшитого фібрину. Позначення FEU означає фібриноген-еквівалентні одиниці; їх слід відрізняти від одиниць D-димера (DDU).",
        "This result is interpreted with symptoms, clinical probability and the assay's diagnostic pathway. An elevated value alone does not establish a blood clot.",
        "Результат оцінюють разом із симптомами, клінічною ймовірністю та діагностичним алгоритмом для конкретного тесту. Саме підвищення не встановлює наявності тромбу.",
        "Assay calibration, units and diagnostic context determine the cutoff, including when an age-adjusted threshold is appropriate. FEU and DDU cutoffs are not interchangeable; no universal isolated interval is assigned.",
        "Поріг залежить від калібрування, одиниць і діагностичного контексту, зокрема доречності вікової корекції. Пороги FEU та DDU не взаємозамінні; універсальний інтервал для окремого результату не встановлюється.",
    ))
    comment = _entry(
        "Blood count comment", "Примітка до загального аналізу крові", "",
        ("medlineplus-complete-blood-count",),
        "A laboratory comment accompanying the blood count, kept as the laboratory wrote it. It is text about the report, not a numerical blood-cell measurement.",
        "Коментар лабораторії до загального аналізу крові, збережений у первісному формулюванні. Це текст до звіту, а не числовий показник клітин крові.",
        "Read it with the source report and the measured blood-count values.",
        "Читайте разом із первинним звітом і виміряними показниками загального аналізу крові.",
        "A narrative report comment has no numerical reference interval and must never produce a high, low or abnormal verdict.",
        "Текстовий коментар до звіту не має числового референтного інтервалу й не повинен отримувати оцінку як підвищений, знижений чи патологічний показник.",
    )
    comment.update(never_verdict=True, render_as="fact", value_type="text")
    entries.append(comment)
    return entries


def extend(library: dict) -> dict[str, int]:
    """Add the public definitions without replacing existing clinical guidance."""
    source_ids = {source["id"] for source in library["sources"]}
    analyte_ids = {entry["concept_id"] for entry in library["analytes"]}
    sources_added = analytes_added = 0
    for source in SOURCES:
        if source["id"] not in source_ids:
            library["sources"].append(dict(source))
            source_ids.add(source["id"])
            sources_added += 1
    for entry in additions():
        if entry["concept_id"] not in analyte_ids:
            library["analytes"].append(entry)
            analyte_ids.add(entry["concept_id"])
            analytes_added += 1
    return {"sources_added": sources_added, "analytes_added": analytes_added}
