"""Ukrainian and European sources for the analytes of the connection audit.

Run last, after the other ``extend_*`` scripts and ``catalog_audit_blood_references``.
Every document below was retrieved and read on 2026-11-15; ``access_note`` says
what was read. No reference band is added: a figure quoted in a note is the
document's own wording about a diagnosis, never a target for the result.
An analyte this release added that no Ukrainian document discusses says so:
``ua_search`` holds the queries and the sites, and both notes carry the sentence.
Sources the library already holds (``iusti-syphilis-2020`` and the Ukrainian
guidelines) are cited by id and were read again for the analyte they now support.
``--all`` applies the whole sequence, which is how the library is rebuilt from
the previous release. No patient records are read. Idempotent.
"""
from __future__ import annotations

import argparse
import json
import runpy
from pathlib import Path

VERSION = "2026-11-15"
REVIEWED_AT = "2026-11-15"
DEC = "https://www.dec.gov.ua/files/"
NICE = "National Institute for Health and Care Excellence"
MOZ = "Міністерство охорони здоров'я України"

# The order in which the extensions rebuild the library; this script is last.
PIPELINE = (
    "extend_missing_reference_library.py",
    "extend_device_reference_library.py",
    "catalog_audit_blood_references.py",
    "extend_calculation_reference_library.py",
    "extend_round3_reference_library.py",
)


def _source(key, region, publisher, name, url, identifier, kind, note):
    return {
        "id": key, "region": region, "publisher": publisher, "name": name, "url": url,
        "identifier": identifier, "reviewed_at": REVIEWED_AT, "official": True,
        "kind": kind, "access_note": note,
    }


SOURCES = (
    _source("moz-nakaz-743-2023-syfilis", "UA", MOZ, "Стандарт медичної допомоги «Сифіліс»",
            DEC + "HfubzEKMGi/smd_743_18042023.pdf", "Наказ МОЗ України від 18.04.2023 № 743", "standard",
            "PDF read in Ukrainian. Two serological tests are required, a treponemal one and a non-treponemal one (RPR, VDRL). The first screening test is treponemal; a positive result is followed by a quantitative non-treponemal test with titres (annex 1)."),
    _source("moz-nakaz-787-2013-drt", "UA", MOZ, "Порядок застосування допоміжних репродуктивних технологій в Україні",
            "https://zakon.rada.gov.ua/laws/show/z1697-13",
            "Наказ МОЗ України від 09.09.2013 № 787, зареєстрований у Міністерстві юстиції України 02.10.2013 за № 1697/24229",
            "regulation",
            "Text read on the Verkhovna Rada site. Section II, point 2.1: the mandatory examination of a woman includes blood tests for anti-Mullerian hormone, prolactin, FSH, LH, progesterone and estradiol; cortisol is among the additional tests done on indication. The order gives no reference intervals."),
    _source("moz-nakaz-1730-2022-ektopichna-vagitnist", "UA", MOZ, "Стандарти медичної допомоги «Ектопічна вагітність»",
            DEC + "Kf5Rz6cUO2/40273-dn_1730_24092022_dod.pdf", "Наказ МОЗ України від 24.09.2022 № 1730", "standard",
            "PDF read in Ukrainian. The diagnosis rests on transvaginal ultrasound and the serum level of beta human chorionic gonadotropin. The order itself (same registry page) carries the date and number."),
    _source("moz-nakaz-1039-2022-menopauza", "UA", MOZ,
            "Уніфікований клінічний протокол первинної, вторинної (спеціалізованої), третинної (високоспеціалізованої) медичної допомоги «Менопаузальні порушення та інші розлади в перименопаузальному періоді»",
            DEC + "f58nH6PNWh/37474-dn_1039_17_06_2022_dod.pdf", "Наказ МОЗ України від 17.06.2022 № 1039", "clinical_protocol",
            "PDF read in Ukrainian. The menopausal transition is described by variable FSH and estradiol levels and falling progesterone, inhibin B and anti-Mullerian hormone (STRAW+10 stages). No interval for estradiol or AMH is given."),
    _source("moz-nakaz-760-2015-fenilketonuriya", "UA", MOZ,
            "Уніфікований клінічний протокол первинної, вторинної (спеціалізованої) та третинної (високоспеціалізованої) медичної допомоги «Фенілкетонурія та інші гіперфенілаланінемії»",
            DEC + "5Jo6K6fFUG/2015_760_ykpmd_fenilk.pdf", "Наказ МОЗ України від 19.11.2015 № 760", "clinical_protocol",
            "PDF read in Ukrainian. Hyperphenylalaninaemia is classified by the blood phenylalanine level (tables 3 and 4); newborns with confirmed hyperphenylalaninaemia have a quantitative amino-acid test for tyrosine and the phenylalanine-to-tyrosine ratio. These are disease categories, not reference intervals."),
    _source("moz-nakaz-1498-2026-zda", "UA", MOZ,
            "Клінічний протокол первинної та спеціалізованої медичної допомоги «Залізодефіцитна анемія у дітей та дорослих»",
            DEC + "Dl5F9Iug74/dn_1498_05102026_dod.pdf", "Наказ МОЗ України від 05.10.2026 № 1498", "clinical_protocol",
            "PDF read in Ukrainian. The baseline tests of a person with chronic kidney disease include the reticulocyte level; children with refractory or recurrent anaemia are screened for coeliac disease with tissue transglutaminase IgA or IgG antibodies and a total IgA level."),
    _source("moz-nakaz-1994-2023-zvid", "UA", MOZ, "Стандарт медичної допомоги «Загальний варіабельний імунодефіцит»",
            DEC + "w0LmlhEY4b/smd_1994_23112023.pdf", "Наказ МОЗ України від 23.11.2023 № 1994", "standard",
            "PDF read in Ukrainian. The basic work-up includes total IgM, IgG and IgA in serum. The published PDFs leave the date and number blank; they are taken from the State Expert Centre's registry entry (file nakaz_1994_23112023.pdf)."),
    _source("moz-nakaz-1496-2026-amk", "UA", MOZ, "Стандарт медичної допомоги «Аномальні маткові кровотечі»",
            DEC + "ruep7VpaCI/dn_1496_02102026_dod.pdf", "Наказ МОЗ України від 02.10.2026 № 1496", "standard",
            "PDF read in Ukrainian. When an ovulation disorder is suspected, prolactin and thyroid-stimulating hormone are measured. No interval is given."),
    _source("moz-nakaz-762-2020-covid-protokol", "UA", MOZ,
            "Протокол «Надання медичної допомоги для лікування коронавірусної хвороби (COVID-19)»",
            DEC + "6ihPPqdsFR/protokol-covid2023.pdf", "Наказ МОЗ України від 02.04.2020 № 762, у редакції 2023 року",
            "clinical_protocol",
            "PDF read in Ukrainian. Routinely adjusting anticoagulation by D-dimer levels is not recommended; a marked rise may indicate a high risk of venous thromboembolism and inform the decision to image. No cutoff is given."),
    _source("moz-nakaz-2142-2021-neonatalnyj-skryninh", "UA", MOZ, "Про забезпечення розширеного неонатального скринінгу в Україні",
            "https://zakon.rada.gov.ua/laws/show/z1403-21",
            "Наказ МОЗ України від 01.10.2021 № 2142, зареєстрований у Міністерстві юстиції України 29.10.2021 за № 1403/37025",
            "regulation",
            "Text read on the Verkhovna Rada site (edition amended by orders 2523, 991 and 1867). Section VIII: screening for inherited metabolic diseases rests on the quantitative measurement of amino acids and acylcarnitines in dried blood spots by tandem mass spectrometry. Annex 3 names the metabolites: leucine and valine for maple syrup urine disease, tyrosine for tyrosinaemia type I, phenylalanine for phenylketonuria. Its reference values are for newborn dried blood spots and are not imported."),
    _source("moz-nakaz-152-2024-mma-pa", "UA", MOZ,
            "Стандарт медичної допомоги «Діагностика та лікування метилмалонової та пропіонової ацидемій»",
            "https://moz.gov.ua/uploads/10/53105-dn_152_30012024_dod.pdf", "Наказ МОЗ України від 30.01.2024 № 152", "standard",
            "PDF read in Ukrainian. Annex 2: measuring amino acids in plasma shows a raised glycine level in methylmalonic and propionic acidaemia. Annex 5: quantitative plasma amino acids every 3 to 6 months, sampled after a 3 to 4 hour fast. The diet lowers the intake of the precursor amino acids methionine, threonine, valine and isoleucine. No interval is given. The PDF leaves the date and number blank; they are taken from the Ministry's page for the order."),
    _source("nice-ng20-coeliac", "EU", NICE, "Coeliac disease: recognition, assessment and management",
            "https://www.nice.org.uk/guidance/ng20/chapter/Recommendations",
            "NICE guideline NG20, recommendations 1.2.2 to 1.2.4; published 2 September 2015", "guideline",
            "Recommendations read. Total IgA and IgA tissue transglutaminase are the first choice; IgA endomysial antibodies are used when IgA tTG is weakly positive; IgG EMA, IgG deamidated gliadin peptide or IgG tTG are considered when IgA is deficient, defined as total IgA below 0.07 g/L."),
    _source("nice-ng126-ectopic-miscarriage", "EU", NICE, "Ectopic pregnancy and miscarriage: diagnosis and initial management",
            "https://www.nice.org.uk/guidance/ng126/chapter/Diagnosis-of-viable-intrauterine-pregnancy-and-of-tubal-ectopic-pregnancy",
            "NICE guideline NG126, section 1.7; published 17 April 2019, last updated 17 June 2026", "guideline",
            "Chapter read. Serum hCG levels are taken into account together with the ultrasound scan and the clinical presentation before a diagnosis is made."),
    _source("nice-ng257-fertility", "EU", NICE, "Fertility problems: assessment and treatment",
            "https://www.nice.org.uk/guidance/ng257/chapter/Investigation-of-fertility-problems-and-management-strategies",
            "NICE guideline NG257, recommendations 1.18.3, 1.18.4 and 1.18.11; published 31 March 2026", "guideline",
            "Chapter read. AMH or antral follicle count predicts the ovarian response to stimulation; AMH is not used to predict pregnancy by spontaneous conception. A prolactin test is offered only with an ovulatory disorder, galactorrhoea or a pituitary tumour."),
    _source("nice-ng23-menopause", "EU", NICE, "Menopause: identification and management",
            "https://www.nice.org.uk/guidance/ng23/chapter/Recommendations",
            "NICE guideline NG23, recommendation 1.3.4 [2015]; last updated 15 April 2026", "guideline",
            "Recommendations read. Anti-Mullerian hormone and oestradiol are among the tests not to be used to identify perimenopause or menopause in people aged 45 or over."),
    _source("nice-ng243-adrenal-insufficiency", "EU", NICE, "Adrenal insufficiency: identification and management",
            "https://www.nice.org.uk/guidance/ng243/chapter/Recommendations",
            "NICE guideline NG243, recommendation 1.2.9 and table 1; published 28 August 2024", "guideline",
            "Recommendations read. An 8 am to 9 am serum cortisol test is offered when adrenal insufficiency is suspected. Table 1 interprets that timed sample only; its thresholds are not imported."),
)

VYKYDEN = "dec-kn-spontannyj-vykyden-2025"
LUPUS = (
    (VYKYDEN,),
    "The Ukrainian guideline «Спонтанний викидень. Звичне невиношування вагітності» (2025) advises offering women with recurrent pregnancy loss testing for acquired thrombophilia, lupus anticoagulant and anticardiolipin antibodies, before a pregnancy. It gives no clotting-time cutoff.",
    "Українська клінічна настанова «Спонтанний викидень. Звичне невиношування вагітності» (2025) радить пропонувати жінкам зі звичним невиношуванням обстеження на набуту тромбофілію, зокрема на вовчаковий антикоагулянт та антикардіоліпінові антитіла, до вагітності. Порогу часу згортання вона не наводить.",
)
MTHFR = (
    (VYKYDEN,),
    "The Ukrainian guideline «Спонтанний викидень. Звичне невиношування вагітності» (2025) does not recommend routine testing for the MTHFR mutation in recurrent pregnancy loss.",
    "Українська клінічна настанова «Спонтанний викидень. Звичне невиношування вагітності» (2025) не рекомендує рутинного аналізу на мутацію MTHFR у разі звичного невиношування.",
)

SCREENING = "moz-nakaz-2142-2021-neonatalnyj-skryninh"
MMA = "moz-nakaz-152-2024-mma-pa"
SCREENING_EN = "In Ukraine, МОЗ order 2142 of 01.10.2021 on expanded newborn screening measures amino acids and acylcarnitines in dried blood spots by tandem mass spectrometry."
SCREENING_UK = "Наказ МОЗ від 01.10.2021 № 2142 про розширений неонатальний скринінг передбачає кількісне визначення амінокислот та ацилкарнітинів у сухих краплях крові методом тандемної мас-спектрометрії."
SCREENING_TAIL_EN = "Its reference values are for newborn dried blood spots; they are not carried over to a serum or plasma result."
SCREENING_TAIL_UK = "Його референсні значення стосуються сухих крапель крові новонароджених і не перенесені на результат у сироватці чи плазмі."


def _precursor_en(name: str) -> str:
    return ("The Ukrainian standard «Діагностика та лікування метилмалонової та пропіонової ацидемій» (МОЗ order 152 of 30.01.2024) "
            f"names {name} among the precursor amino acids whose intake the diet lowers in these two diseases, "
            "and asks for quantitative plasma amino acids every 3 to 6 months, sampled after a 3 to 4 hour fast. It gives no interval.")


def _precursor_uk(name: str) -> str:
    return ("Стандарт медичної допомоги «Діагностика та лікування метилмалонової та пропіонової ацидемій» (наказ МОЗ від 30.01.2024 № 152) "
            f"називає {name} серед амінокислот-попередників, споживання яких знижують дієтою за цих двох хвороб, "
            "і передбачає кількісне визначення амінокислот плазми кожні 3–6 місяців, після 3–4 годин голодування. Інтервалу він не наводить.")


# Analyte: (sources it is now also cited from, note, Ukrainian note).
ATTACH = {
    "syphilis-non-treponemal-screening-test": (
        ("moz-nakaz-743-2023-syfilis", "iusti-syphilis-2020"),
        "The Ukrainian standard of care «Сифіліс» (МОЗ order 743 of 18.04.2023) requires two serological tests, a treponemal one and a non-treponemal one (RPR, VDRL). Its algorithm screens with a treponemal test and follows a positive result with a quantitative non-treponemal test with titres. The 2020 European guideline describes the same order and notes that screening with a non-treponemal test is still recommended in some countries. In either order a reactive non-treponemal test is read together with a treponemal test.",
        "Стандарт медичної допомоги «Сифіліс» (наказ МОЗ від 18.04.2023 № 743) вимагає двох серологічних тестів: трепонемного та нетрепонемного (RPR, VDRL). Першим скринінговим тестом є трепонемний; після позитивного результату роблять кількісний нетрепонемний тест із визначенням титру. Європейська настанова 2020 року описує такий самий порядок і зазначає, що в деяких країнах скринінг досі починають з нетрепонемного тесту. За будь-якого порядку реактивний нетрепонемний тест оцінюють разом із трепонемним.",
    ),
    "anti-mullerian-hormone": (
        ("moz-nakaz-787-2013-drt", "moz-nakaz-1039-2022-menopauza", "nice-ng257-fertility", "nice-ng23-menopause"),
        "In Ukraine, МОЗ order 787 of 09.09.2013 on assisted reproductive technologies lists a blood test for anti-Mullerian hormone in the mandatory examination of a woman before treatment; it gives no reference interval. The Ukrainian menopause protocol (order 1039 of 17.06.2022) describes falling AMH in the menopausal transition. NICE NG257 uses AMH to predict the ovarian response to stimulation and says not to use it to predict pregnancy by natural conception; NICE NG23 says not to use it to identify menopause in people aged 45 or over.",
        "Наказ МОЗ від 09.09.2013 № 787 про допоміжні репродуктивні технології включає аналіз крові на антимюллерів гормон до обов’язкового обстеження жінки перед лікуванням; референтного інтервалу він не наводить. Український протокол щодо менопаузи (наказ МОЗ від 17.06.2022 № 1039) описує зниження АМГ у перехідному періоді. NICE NG257 використовує АМГ для прогнозу відповіді яєчників на стимуляцію і не радить прогнозувати за ним природне зачаття; NICE NG23 не радить визначати за ним менопаузу у віці від 45 років.",
    ),
    "estradiol": (
        ("moz-nakaz-787-2013-drt", "moz-nakaz-1039-2022-menopauza", "nice-ng23-menopause"),
        "In Ukraine, МОЗ order 787 of 09.09.2013 lists estradiol among the mandatory blood tests of a woman before assisted reproduction, without a reference interval. The Ukrainian menopause protocol (order 1039 of 17.06.2022) notes variable estradiol levels in the menopausal transition. NICE NG23 says not to use estradiol to identify menopause in people aged 45 or over.",
        "Наказ МОЗ від 09.09.2013 № 787 включає естрадіол до обов’язкових аналізів крові жінки перед допоміжними репродуктивними технологіями, без референтного інтервалу. Український протокол щодо менопаузи (наказ МОЗ від 17.06.2022 № 1039) зазначає, що в перехідному періоді рівень естрадіолу мінливий. NICE NG23 не радить визначати за естрадіолом менопаузу у віці від 45 років.",
    ),
    "prolactin": (
        ("moz-nakaz-787-2013-drt", "moz-nakaz-1496-2026-amk", "nice-ng257-fertility"),
        "In Ukraine, МОЗ order 787 of 09.09.2013 lists prolactin among the mandatory blood tests of a woman before assisted reproduction. The Ukrainian standard «Аномальні маткові кровотечі» (order 1496 of 02.10.2026) measures prolactin and thyroid-stimulating hormone when an ovulation disorder is suspected. NICE NG257 offers a prolactin test only with an ovulatory disorder, galactorrhoea or a pituitary tumour. None of them gives a universal interval.",
        "Наказ МОЗ від 09.09.2013 № 787 включає пролактин до обов’язкових аналізів крові жінки перед допоміжними репродуктивними технологіями. Стандарт медичної допомоги «Аномальні маткові кровотечі» (наказ МОЗ від 02.10.2026 № 1496) передбачає визначення пролактину й тиреотропного гормону за підозри на розлад овуляції. NICE NG257 пропонує аналіз на пролактин лише за розладу овуляції, галактореї або пухлини гіпофіза. Універсального інтервалу жоден із них не наводить.",
    ),
    "cortisol": (
        ("moz-nakaz-787-2013-drt", "nice-ng243-adrenal-insufficiency"),
        "In Ukraine, МОЗ order 787 of 09.09.2013 names blood cortisol among the additional tests done on indication before assisted reproduction, without an interval. NICE NG243 offers an 8 am to 9 am serum cortisol test when adrenal insufficiency is suspected; its interpretation table applies to that timed sample only and is not carried over as a general range.",
        "Наказ МОЗ від 09.09.2013 № 787 називає кортизол крові серед додаткових аналізів, які роблять за показаннями перед допоміжними репродуктивними технологіями, без інтервалу. NICE NG243 пропонує аналіз кортизолу сироватки між 8 і 9 годинами ранку за підозри на надниркову недостатність; її таблиця тлумачення стосується лише такої проби й не перенесена сюди як загальний інтервал.",
    ),
    "total-beta-hcg": (
        ("moz-nakaz-1730-2022-ektopichna-vagitnist", VYKYDEN, "nice-ng126-ectopic-miscarriage"),
        "The Ukrainian standards «Ектопічна вагітність» (МОЗ order 1730 of 24.09.2022) base the diagnosis on transvaginal ultrasound and the serum beta-hCG level. The Ukrainian guideline on miscarriage (2025) asks for an urgent quantitative beta-hCG when early pregnancy loss is suspected. NICE NG126 likewise reads serum hCG together with the ultrasound scan. None of them gives a single normal value.",
        "Стандарти медичної допомоги «Ектопічна вагітність» (наказ МОЗ від 24.09.2022 № 1730) ґрунтують діагноз на трансвагінальному ультразвуковому дослідженні та рівні бета-ХГЛ у сироватці крові. Українська клінічна настанова щодо викидня (2025) передбачає термінове кількісне визначення бета-ХГЛ за підозри на ранню втрату вагітності. NICE NG126 так само оцінює ХГЛ сироватки разом з ультразвуковим дослідженням. Єдиного нормального значення жоден із них не наводить.",
    ),
    "total-immunoglobulin-a": (
        ("moz-nakaz-1994-2023-zvid", "moz-kn-pid-2021", "moz-nakaz-1498-2026-zda", "nice-ng20-coeliac"),
        "The Ukrainian standard «Загальний варіабельний імунодефіцит» (МОЗ order 1994 of 23.11.2023) includes total IgM, IgG and IgA in the basic work-up. The Ukrainian guideline «Первинні імунодефіцити» (2021) describes selective IgA deficiency as an undetectable serum IgA, below 0.07 g/L by nephelometry, with normal IgG and IgM, diagnosed after the age of four; NICE NG20 defines IgA deficiency by the same figure. The Ukrainian iron-deficiency anaemia protocol (order 1498 of 05.10.2026) and NICE NG20 measure total IgA alongside coeliac antibodies. That figure defines a deficiency; it is not a reference interval.",
        "Стандарт медичної допомоги «Загальний варіабельний імунодефіцит» (наказ МОЗ від 23.11.2023 № 1994) включає загальні IgM, IgG та IgA до базового обстеження. Українська клінічна настанова «Первинні імунодефіцити» (2021) описує селективний дефіцит IgA як невизначуваний сироватковий IgA, менше 0,07 г/л за нефелометрії, за нормальних IgG та IgM, з діагнозом після четвертого року життя; NICE NG20 визначає дефіцит IgA тим самим числом. Український протокол щодо залізодефіцитної анемії (наказ МОЗ від 05.10.2026 № 1498) і NICE NG20 визначають загальний IgA разом з антитілами на целіакію. Це число визначає дефіцит і не є референтним інтервалом.",
    ),
    "tissue-transglutaminase-igg-antibodies": (
        ("moz-nakaz-1498-2026-zda", "dec-kn-diabet-2024", "nice-ng20-coeliac"),
        "The Ukrainian iron-deficiency anaemia protocol (МОЗ order 1498 of 05.10.2026) screens children with refractory or recurrent anaemia for coeliac disease with tissue transglutaminase IgA or IgG antibodies and a total IgA level. The Ukrainian diabetes guideline (2024) and NICE NG20 turn to the IgG test when IgA is deficient.",
        "Український протокол щодо залізодефіцитної анемії (наказ МОЗ від 05.10.2026 № 1498) передбачає скринінг на целіакію в дітей з рефрактерною або рецидивною анемією: антитіла IgA чи IgG до тканинної трансглутамінази та рівень загального IgA. Українська клінічна настанова «Цукровий діабет» (2024) і NICE NG20 звертаються до тесту IgG за дефіциту IgA.",
    ),
    "endomysial-iga-antibodies": (
        ("dec-kn-diabet-2024", "nice-ng20-coeliac"),
        "NICE NG20 uses IgA endomysial antibodies when IgA tissue transglutaminase is weakly positive. The Ukrainian diabetes guideline (2024) mentions confirming a high transglutaminase titre in a child with endomysial antibodies on a separate blood sample.",
        "NICE NG20 використовує антитіла IgA до ендомізію, коли IgA до тканинної трансглутамінази слабкопозитивні. Українська клінічна настанова «Цукровий діабет» (2024) згадує підтвердження високого титру антитіл до трансглутамінази в дитини антитілами до ендомізію в окремому зразку крові.",
    ),
    "pancreatic-amylase": (
        ("moz-ukpmd-pancreatitis-2023",),
        "The Ukrainian protocol «Хронічний панкреатит» (МОЗ order 1204 of 05.07.2023) lists amylase, pancreatic isoamylase and lipase among the blood tests of specialised care. It gives no interval.",
        "Український протокол «Хронічний панкреатит» (наказ МОЗ від 05.07.2023 № 1204) називає амілазу, панкреатичну ізоамілазу та ліпазу серед аналізів крові на рівні спеціалізованої допомоги. Інтервалу він не наводить.",
    ),
    "reticulocytes": (
        ("moz-nakaz-89-2016", "moz-nakaz-1498-2026-zda"),
        "Ukrainian documents use the reticulocyte count in the work-up of anaemia: the adapted guideline on chronic kidney disease treated with haemodialysis (МОЗ order 89 of 11.02.2016) lists it in the assessment of anaemia, and the iron-deficiency anaemia protocol (order 1498 of 05.10.2026) includes it in the baseline tests of people with chronic kidney disease. Neither gives an interval.",
        "Українські документи використовують кількість ретикулоцитів під час обстеження з приводу анемії: адаптована настанова щодо хронічної хвороби нирок у пацієнтів на гемодіалізі (наказ МОЗ від 11.02.2016 № 89) включає її до оцінки анемії, а протокол щодо залізодефіцитної анемії (наказ МОЗ від 05.10.2026 № 1498) до базового обстеження пацієнтів із хронічною хворобою нирок. Інтервалу жоден із них не наводить.",
    ),
    "reticulocytes-absolute": (
        ("moz-nakaz-89-2016",),
        "The Ukrainian adapted guideline on chronic kidney disease treated with haemodialysis (МОЗ order 89 of 11.02.2016) lists the absolute reticulocyte count among the laboratory tests for anaemia. It gives no interval.",
        "Українська адаптована настанова щодо хронічної хвороби нирок у пацієнтів на гемодіалізі (наказ МОЗ від 11.02.2016 № 89) включає абсолютну кількість ретикулоцитів до лабораторного обстеження з приводу анемії. Інтервалу вона не наводить.",
    ),
    "h-pylori-test-method-unspecified": (
        ("moz-1514-2023",),
        "The Ukrainian protocol on peptic ulcer (МОЗ order 1514 of 25.08.2023) names several methods: the stool antigen test, serology, the 13C-urea breath test and tests on a biopsy, each with its own conditions. A result with no named method cannot be assigned to one of them.",
        "Український протокол щодо пептичної виразки (наказ МОЗ від 25.08.2023 № 1514) називає кілька методів: тест на антиген у калі, серологічне дослідження, 13С-сечовинний дихальний тест і дослідження біоптату, кожен зі своїми умовами. Результат без зазначеного методу не можна віднести до жодного з них.",
    ),
    "homa-index-reported-model-unspecified": (
        ("moz-826-2014-nash",),
        "The sources disagree. The Ukrainian protocol «Неалкогольний стеатогепатит» (МОЗ order 826 of 06.11.2014) calculates HOMA as fasting glucose (mmol/L) × fasting insulin (µU/mL) ÷ 22.5 and regards a value above 1.64 as insulin resistance. The authors of the Oxford HOMA calculator state that there are no defined thresholds for normal and abnormal values, because these depend on the glucose and insulin assays. The threshold is not applied here: the model behind a reported index is unknown.",
        "Джерела розходяться. Український протокол «Неалкогольний стеатогепатит» (наказ МОЗ від 06.11.2014 № 826) розраховує HOMA як глюкоза натще (ммоль/л) × інсулін натще (мкОд/мл) ÷ 22,5 і вважає значення понад 1,64 ознакою інсулінорезистентності. Автори оксфордського калькулятора HOMA зазначають, що визначених порогів нормальних і патологічних значень немає, бо вони залежать від методів визначення глюкози та інсуліну. Тут цей поріг не застосовано: модель, за якою отримано повідомлений індекс, невідома.",
    ),
    "d-dimer": (
        ("moz-nakaz-762-2020-covid-protokol",),
        "The Ukrainian COVID-19 treatment protocol (МОЗ order 762 of 02.04.2020, 2023 edition) advises against routinely adjusting anticoagulation by D-dimer levels; a marked rise may indicate a high risk of venous thromboembolism and inform the decision to image. It gives no cutoff. NICE NG158 uses D-dimer inside a diagnostic pathway and allows an age-adjusted threshold for people aged over 50.",
        "Український протокол лікування COVID-19 (наказ МОЗ від 02.04.2020 № 762, редакція 2023 року) не рекомендує регулярно змінювати антикоагулянтну терапію за рівнем D-димера; значне підвищення може вказувати на високий ризик венозної тромбоемболії та вплинути на рішення про візуалізацію. Порогу він не наводить. NICE NG158 використовує D-димер у межах діагностичного алгоритму й допускає поріг із поправкою на вік для людей, старших за 50 років.",
    ),
    "phenylalanine-serum-or-plasma": (
        ("moz-nakaz-760-2015-fenilketonuriya",),
        "The Ukrainian protocol «Фенілкетонурія та інші гіперфенілаланінемії» (МОЗ order 760 of 19.11.2015) classifies hyperphenylalaninaemia by the blood phenylalanine level. Those categories serve the diagnosis and follow-up of phenylketonuria; they are not a general reference interval.",
        "Український протокол «Фенілкетонурія та інші гіперфенілаланінемії» (наказ МОЗ від 19.11.2015 № 760) класифікує гіперфенілаланінемію за рівнем фенілаланіну в крові. Ці категорії призначені для діагностики фенілкетонурії та спостереження за нею; це не загальний референтний інтервал.",
    ),
    "tyrosine-serum-or-plasma": (
        ("moz-nakaz-760-2015-fenilketonuriya",),
        "The Ukrainian protocol «Фенілкетонурія та інші гіперфенілаланінемії» (МОЗ order 760 of 19.11.2015) asks for a quantitative amino-acid test in newborns with confirmed hyperphenylalaninaemia, to measure tyrosine and the phenylalanine-to-tyrosine ratio. It gives no interval for tyrosine.",
        "Український протокол «Фенілкетонурія та інші гіперфенілаланінемії» (наказ МОЗ від 19.11.2015 № 760) передбачає кількісне дослідження амінокислот у новонароджених із підтвердженою гіперфенілаланінемією, щоб визначити рівень тирозину та співвідношення фенілаланіну до тирозину. Інтервалу для тирозину він не наводить.",
    ),
    "leucine-serum-or-plasma": (
        (SCREENING,),
        SCREENING_EN + " Annex 3 names leucine, with valine, as the metabolite measured for maple syrup urine disease. " + SCREENING_TAIL_EN,
        SCREENING_UK + " Додаток 3 називає лейцин разом із валіном метаболітом, який визначають для виявлення лейцинозу (хвороби «кленового сиропу»). " + SCREENING_TAIL_UK,
    ),
    "valine-serum-or-plasma": (
        (SCREENING, MMA),
        SCREENING_EN + " Annex 3 names valine, with leucine, as the metabolite measured for maple syrup urine disease. " + SCREENING_TAIL_EN + " " + _precursor_en("valine"),
        SCREENING_UK + " Додаток 3 називає валін разом із лейцином метаболітом, який визначають для виявлення лейцинозу (хвороби «кленового сиропу»). " + SCREENING_TAIL_UK + " " + _precursor_uk("валін"),
    ),
    "isoleucine-serum-or-plasma": ((MMA,), _precursor_en("isoleucine"), _precursor_uk("ізолейцин")),
    "methionine-serum-or-plasma": ((MMA,), _precursor_en("methionine"), _precursor_uk("метіонін")),
    "threonine-serum-or-plasma": ((MMA,), _precursor_en("threonine"), _precursor_uk("треонін")),
    "glycine-serum-or-plasma": (
        (MMA,),
        "The Ukrainian standard «Діагностика та лікування метилмалонової та пропіонової ацидемій» (МОЗ order 152 of 30.01.2024) notes that measuring amino acids in plasma shows a raised glycine level in these two diseases, and asks for quantitative plasma amino acids every 3 to 6 months in people who have them. It gives no interval.",
        "Стандарт медичної допомоги «Діагностика та лікування метилмалонової та пропіонової ацидемій» (наказ МОЗ від 30.01.2024 № 152) зазначає, що вимірювання амінокислот у плазмі показує підвищений рівень гліцину за цих двох хвороб, і передбачає кількісне визначення амінокислот плазми кожні 3–6 місяців у людей, які їх мають. Інтервалу він не наводить.",
    ),
    "lupus-anticoagulant-screening-time": LUPUS,
    "lupus-anticoagulant-confirmation-time": LUPUS,
    "lupus-anticoagulant-index": LUPUS,
    "mthfr-c677t-genotype": MTHFR,
    "mthfr-a1298c-genotype": MTHFR,
}

# Where the attached Ukrainian document states a threshold that another source rejects.
DIVERGENT = {"homa-index-reported-model-unspecified"}


# What was searched, in Ukrainian, for the analytes this release added and no Ukrainian
# document discusses. guidelines.moz.gov.ua answered HTTP 503 throughout and is listed apart.
SEARCHED_AT = "2026-11-15"
RADA, DEC, MOZ_SITE, PHC = "zakon.rada.gov.ua", "dec.gov.ua", "moz.gov.ua", "phc.org.ua"
UNREACHABLE = ["guidelines.moz.gov.ua"]
#: How the terms were used, so the record does not claim more than was done.
SEARCH_METHOD = (
    "Full-text search on zakon.rada.gov.ua; the terms matched against the titles in the dec.gov.ua "
    "registry of medical-technological documents (its own search was rate-limited); web search for "
    "pages on moz.gov.ua and phc.org.ua. guidelines.moz.gov.ua answered 503 and was not read."
)
NOT_FOUND = "No Ukrainian national document that discusses this test was found (searched 15 November 2026)."
NOT_FOUND_UK = "Українського національного документа, який описує цей показник, не знайдено (пошук 15 листопада 2026 року)."
VENDOR = "This is a value defined by the device maker; no national guideline covers it."
VENDOR_UK = "Це величина, яку визначає виробник пристрою; національні настанови її не описують."
AMINO_QUERIES = ["амінокислоти плазми", "тандемна мас-спектрометрія", "розширений неонатальний скринінг",
                 "спадкові хвороби обміну амінокислот гомоцистинурія цитрулінемія", "орфанні захворювання",
                 "тирозинемія", "лейциноз", "метилмалонова та пропіонова ацидемії"]
RETICULOCYTE_QUERIES = ["ретикулоцити", "ретикулоцитарний індекс", "індекс продукції ретикулоцитів",
                        "фракція незрілих ретикулоцитів", "гемолітична анемія ретикулоцити", "апластична анемія", "анемія"]
DEVICE_QUERIES = ["рекомендації фізична активність кроки сон якість сну",
                  "тривалість сну частота серцевих скорочень у спокої фітнес-трекер",
                  "варіабельність серцевого ритму", "фази сну", "стадії сну", "частота серцевих скорочень уві сні",
                  "кількість кроків", "фітнес-трекер", "рівень шуму навушники", "ожиріння", "фізична активність"]
# (analytes, queries run, sites searched, defined by a device maker)
UA_SEARCHES = (
    (("toxocara-igg-antibodies",),
     ["токсокароз", "токсокароз клінічний протокол наказ МОЗ ІФА антитіла IgG Toxocara canis", "гельмінтози діагностика",
      "ларвальні гельмінтози", "паразитарні хвороби"], [RADA, DEC, MOZ_SITE], False),
    (("roma-premenopausal", "roma-postmenopausal"),
     ["рак яєчників", "яєчник", "пухлини яєчника CA-125 HE4 ROMA", "онкомаркер НЕ4", "індекс ROMA"], [RADA, DEC, MOZ_SITE], False),
    (("reticulocyte-index", "immature-reticulocyte-fraction", "reticulocytes-low-fluorescence-fraction",
      "reticulocytes-medium-fluorescence-fraction", "reticulocytes-high-fluorescence-fraction"),
     RETICULOCYTE_QUERIES, [RADA, DEC, MOZ_SITE], False),
    (("globulin-calculated",),
     ["глобуліни розрахункові", "альбумін-глобуліновий", "диспротеїнемія загальний білок альбумін глобуліни",
      "множинна мієлома", "цироз печінки"], [RADA, DEC, MOZ_SITE], False),
    (("blood-count-comment",), ["гемограма", "загальний аналіз крові"], [RADA, DEC], False),
    (("alanine-serum-or-plasma", "arginine-serum-or-plasma", "asparagine-serum-or-plasma", "aspartic-acid-serum-or-plasma",
      "histidine-serum-or-plasma", "glutamine-serum-or-plasma", "glutamic-acid-serum-or-plasma",
      "homocitrulline-serum-or-plasma", "hydroxylysine-serum-or-plasma", "hydroxyproline-serum-or-plasma",
      "carnosine-serum-or-plasma", "lysine-serum-or-plasma", "ornithine-serum-or-plasma", "proline-serum-or-plasma",
      "sarcosine-serum-or-plasma", "serine-serum-or-plasma", "taurine-serum-or-plasma", "tryptophan-serum-or-plasma",
      "phosphoethanolamine-serum-or-plasma", "phosphoserine-serum-or-plasma", "cystathionine-serum-or-plasma",
      "cystine-serum-or-plasma", "citrulline-serum-or-plasma", "1-methylhistidine-serum-or-plasma",
      "3-methylhistidine-serum-or-plasma", "alpha-aminoadipic-acid-serum-or-plasma",
      "alpha-aminobutyric-acid-serum-or-plasma", "beta-alanine-serum-or-plasma",
      "beta-aminoisobutyric-acid-serum-or-plasma", "gamma-aminobutyric-acid-serum-or-plasma",
      "ethanolamine-serum-or-plasma"),
     AMINO_QUERIES, [RADA, DEC, MOZ_SITE], False),
    (("environmental_sound_reduction", "stair_ascent_speed", "stair_descent_speed", "swimming_distance", "stand_hours",
      "lowest_sleeping_heart_rate", "sleep_interruptions", "body_battery_score", "health_recovery_score",
      "recovery_score", "resilience_score", "strain_score", "stress_score"),
     DEVICE_QUERIES, [RADA, DEC, MOZ_SITE, PHC], True),
    (("weather_temperature", "weather_humidity"),
     ["погодні умови температура вологість здоров'я", "рекомендації температура повітря вологість спека здоров'я"],
     [RADA, MOZ_SITE, PHC], True),
)


def _record_searches(analytes: dict) -> int:
    """Say on the analyte itself that Ukrainian sources were searched and none discusses it."""
    recorded = 0
    for concept_ids, queries, sites, vendor in UA_SEARCHES:
        for concept_id in concept_ids:
            entry = analytes.get(concept_id)
            if entry is None or "UA" in entry["regions_covered"]:
                continue
            entry["ua_search"] = {"searched_at": SEARCHED_AT, "result": "none_found", "queries": list(queries),
                                  "sites": list(sites), "unreachable_sites": list(UNREACHABLE),
                                  "method": SEARCH_METHOD}
            recorded += 1
            notes = ((VENDOR, NOT_FOUND), (VENDOR_UK, NOT_FOUND_UK)) if vendor else ((NOT_FOUND,), (NOT_FOUND_UK,))
            for container, texts in zip((entry, entry.setdefault("uk", {})), notes):
                for text in texts:
                    existing = str(container.get("jurisdiction_note") or "")
                    if text not in existing:
                        container["jurisdiction_note"] = (existing + " " + text).strip()
    return recorded


def extend(library: dict) -> dict[str, int]:
    """Add the sources, cite them from the analytes they discuss, and stamp the version."""
    library["version"] = VERSION
    known = {item["id"]: item for item in library["sources"]}
    added = 0
    for source in SOURCES:
        if source["id"] not in known:
            library["sources"].append(dict(source))
            known[source["id"]] = source
            added += 1
    library["sources"].sort(key=lambda item: item["id"])
    analytes = {item["concept_id"]: item for item in library["analytes"]}
    attached = 0
    for concept_id, (source_ids, note, note_uk) in ATTACH.items():
        entry = analytes.get(concept_id)
        if entry is None:
            continue
        for source_id in source_ids:
            if source_id not in entry["source_ids"]:
                entry["source_ids"].append(source_id)
                attached += 1
            region = known[source_id]["region"]
            if region not in entry["regions_covered"]:
                entry["regions_covered"].append(region)
        for container, text in ((entry, note), (entry.setdefault("uk", {}), note_uk)):
            existing = str(container.get("jurisdiction_note") or "")
            if text not in existing:
                container["jurisdiction_note"] = (existing + " " + text).strip()
        if concept_id in DIVERGENT:
            entry["agreement"] = "divergent"
            entry["divergence_note"] = note
        elif entry.get("agreement") == "single_source" and len(entry["source_ids"]) > 1:
            entry["agreement"] = "concordant"
    return {"sources_added": added, "citations_added": attached, "searches_recorded": _record_searches(analytes)}


def extend_all(library: dict) -> dict[str, int]:
    """Apply every extension in order; this is how the library is rebuilt from the previous release."""
    for name in PIPELINE:
        runpy.run_path(str(Path(__file__).with_name(name)))["extend"](library)
    return extend(library)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, default=Path("data/reference_library.json"))
    parser.add_argument("--all", action="store_true", help="apply the earlier extensions first, in order")
    args = parser.parse_args()
    library = json.loads(args.library.read_text(encoding="utf-8"))
    counts = (extend_all if args.all else extend)(library)
    args.library.write_text(json.dumps(library, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
