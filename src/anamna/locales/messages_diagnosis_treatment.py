"""Strings of the treatment part of a diagnosis: the medicines that belong to it, and why.

ATC group names follow the WHO ATC classification (see ``anamna.diagnosis_treatment.SOURCE_URL``).
"""

MESSAGES_DIAGNOSIS_TREATMENT: dict[str, dict[str, str]] = {
    "dx.treat.heading": {"en": "Treatment", "uk": "Лікування"},
    "dx.treat.lead": {
        "en": "Medicines and supplements from your Medicines page that belong to this diagnosis.",
        "uk": "Ліки та добавки зі сторінки «Ліки», що стосуються цього діагнозу.",
    },
    "dx.treat.none": {
        "en": "No medicine from your Medicines page is linked to this diagnosis.",
        "uk": "Жодні ліки зі сторінки «Ліки» не пов’язані з цим діагнозом.",
    },
    "dx.treat.basis_atc": {
        "en": "Shown because it belongs to the group “{group}” (ATC {code}). Medicines of this group are used for conditions like this one.",
        "uk": "Показано, бо належить до групи «{group}» (АТХ {code}). Ліки цієї групи застосовують при таких станах.",
    },
    "dx.treat.basis_linked": {
        "en": "You linked this medicine to this diagnosis.",
        "uk": "Ви пов’язали ці ліки з цим діагнозом.",
    },
    "dx.treat.remove": {"en": "Not for this diagnosis", "uk": "Не для цього діагнозу"},
    "dx.treat.add_label": {
        "en": "A medicine you take for this diagnosis",
        "uk": "Ліки, які ви приймаєте через цей діагноз",
    },
    "dx.treat.add": {"en": "Link to this diagnosis", "uk": "Пов’язати з діагнозом"},
    "dx.treat.open_medicines": {"en": "Open Medicines", "uk": "Відкрити «Ліки»"},
    "dx.treat.atc_explain": {
        "en": "Medicine groups are named after the Anatomical Therapeutic Chemical (ATC) classification of the World Health Organization, which groups medicines by what they treat and how they act. If you take a medicine for another reason, press “Not for this diagnosis”.",
        "uk": "Групи ліків названо за анатомо-терапевтично-хімічною класифікацією (АТХ) Всесвітньої організації охорони здоров’я. Вона групує ліки за тим, що вони лікують і як діють. Якщо ви приймаєте ліки з іншої причини, натисніть «Не для цього діагнозу».",
    },
    "dx.treat.source": {"en": "WHO ATC/DDD Index", "uk": "Індекс АТХ/DDD ВООЗ"},
    "dx.notice.medicine_linked": {
        "en": "The medicine is linked to the diagnosis.",
        "uk": "Ліки пов’язано з діагнозом.",
    },
    "dx.notice.medicine_unlinked": {
        "en": "The medicine is no longer shown for this diagnosis.",
        "uk": "Ліки більше не показано для цього діагнозу.",
    },
    "dx.error.medicine": {
        "en": "That medicine could not be linked. Open the diagnosis and try again.",
        "uk": "Ці ліки не вдалося пов’язати. Відкрийте діагноз і спробуйте ще раз.",
    },
    "ai.dx_treated_with": {"en": "treated with: {names}", "uk": "лікування: {names}"},
    "dx.atc.c02": {"en": "Antihypertensives", "uk": "Антигіпертензивні засоби"},
    "dx.atc.c03": {"en": "Diuretics", "uk": "Сечогінні препарати"},
    "dx.atc.c07": {"en": "Beta blocking agents", "uk": "Блокатори бета-адренорецепторів"},
    "dx.atc.c08": {"en": "Calcium channel blockers", "uk": "Антагоністи кальцію"},
    "dx.atc.c09": {
        "en": "Agents acting on the renin-angiotensin system",
        "uk": "Засоби, що діють на ренін-ангіотензинову систему",
    },
    "dx.atc.c10": {"en": "Lipid modifying agents", "uk": "Гіполіпідемічні засоби"},
    "dx.atc.a10": {"en": "Drugs used in diabetes", "uk": "Антидіабетичні препарати"},
    "dx.atc.h03a": {"en": "Thyroid preparations", "uk": "Тиреоїдні препарати"},
    "dx.atc.h03b": {"en": "Antithyroid preparations", "uk": "Антитиреоїдні препарати"},
    "dx.atc.m04": {"en": "Antigout preparations", "uk": "Засоби, що застосовуються при подагрі"},
    "dx.atc.b03a": {"en": "Iron preparations", "uk": "Препарати заліза"},
    "dx.atc.b03b": {"en": "Vitamin B12 and folic acid", "uk": "Вітамін B12 і фолієва кислота"},
    "dx.atc.a11cc": {"en": "Vitamin D and analogues", "uk": "Вітамін D та його аналоги"},
    "dx.atc.r03": {
        "en": "Drugs for obstructive airway diseases",
        "uk": "Засоби, що застосовуються при обструктивних захворюваннях дихальних шляхів",
    },
    "dx.atc.a02b": {
        "en": "Drugs for peptic ulcer and gastro-oesophageal reflux disease",
        "uk": "Засоби для лікування пептичної виразки та гастроезофагеальної рефлюксної хвороби",
    },
    "dx.atc.b01a": {"en": "Antithrombotic agents", "uk": "Антитромботичні засоби"},
    "dx.atc.m05b": {
        "en": "Drugs affecting bone structure and mineralization",
        "uk": "Засоби, що впливають на структуру та мінералізацію кісток",
    },
    "dx.atc.n06a": {"en": "Antidepressants", "uk": "Антидепресанти"},
    "dx.atc.n03a": {"en": "Antiepileptics", "uk": "Протиепілептичні засоби"},
    "dx.atc.g04c": {
        "en": "Drugs used in benign prostatic hypertrophy",
        "uk": "Засоби, що застосовуються при доброякісній гіпертрофії передміхурової залози",
    },
    "dx.atc.s01e": {
        "en": "Antiglaucoma preparations and miotics",
        "uk": "Протиглаукомні препарати та міотичні засоби",
    },
    "dx.atc.r06a": {
        "en": "Antihistamines for systemic use",
        "uk": "Антигістамінні засоби для системного застосування",
    },
    "dx.atc.a08a": {
        "en": "Antiobesity preparations, excluding diet products",
        "uk": "Засоби для лікування ожиріння, за винятком дієтичних продуктів",
    },
    "dx.atc.n02c": {"en": "Antimigraine preparations", "uk": "Засоби, що застосовуються при мігрені"},
    "dx.atc.n04": {"en": "Anti-parkinson drugs", "uk": "Протипаркінсонічні засоби"},
    "dx.atc.n06d": {"en": "Anti-dementia drugs", "uk": "Засоби, що застосовуються при деменції"},
}
