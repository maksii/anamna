from __future__ import annotations

import re
import uuid

from .text import normalized_key


CONCEPT_DEFINITIONS: list[dict[str, object]] = [
    {"name": "Systolic blood pressure", "category": "cardiovascular", "unit": "mmHg", "aliases": ["systolic blood pressure", "систолічний артеріальний тиск"]},
    {"name": "Diastolic blood pressure", "category": "cardiovascular", "unit": "mmHg", "aliases": ["diastolic blood pressure", "діастолічний артеріальний тиск"]},
    # «ЧСС» on a visit note is the rate the clinician counted at rest -- the
    # same spot reading a cuff reports, judged by the same resting bands.  An
    # ECG's own «ЧСС» column is re-labelled «ЧСС (ЕКГ)» by the parser and
    # lands on "ECG heart rate" below.
    {"name": "Pulse rate", "category": "cardiovascular", "unit": "bpm", "aliases": ["pulse rate", "частота пульсу", "пульс", "чсс", "частота серцевих скорочень"]},
    # The rate a Kardia ECG computes from its R-R intervals, kept apart from the
    # cuff's pulse: one is the electrical beat over thirty seconds, the other a
    # pressure wave counted during an inflation, and one series holding both
    # mixes two methods under one trend.  The Kardia parser names it "Pulse
    # rate"; ``refine_definition`` re-files it by the report's clinical type.
    {"name": "ECG heart rate", "category": "cardiovascular", "unit": "bpm", "aliases": ["ecg heart rate", "heart rate (ecg)", "чсс за екг", "чсс (екг)", "частота серцевих скорочень за екг"]},
    {"name": "Blood pressure category", "category": "cardiovascular", "unit": None, "value_type": "text", "aliases": ["blood pressure category", "категорія артеріального тиску"]},
    {"name": "Heart rhythm", "category": "cardiovascular", "unit": None, "value_type": "text", "aliases": ["heart rhythm", "kardia advanced determination", "серцевий ритм"]},
    {"name": "ECG recording duration", "category": "cardiovascular", "unit": "s", "aliases": ["ecg recording duration", "ekg recording duration", "тривалість запису екг"]},
    {"name": "Weekly systolic blood pressure minimum", "category": "cardiovascular", "unit": "mmHg", "aliases": ["weekly systolic blood pressure minimum"]},
    {"name": "Weekly systolic blood pressure maximum", "category": "cardiovascular", "unit": "mmHg", "aliases": ["weekly systolic blood pressure maximum"]},
    {"name": "Weekly diastolic blood pressure minimum", "category": "cardiovascular", "unit": "mmHg", "aliases": ["weekly diastolic blood pressure minimum"]},
    {"name": "Weekly diastolic blood pressure maximum", "category": "cardiovascular", "unit": "mmHg", "aliases": ["weekly diastolic blood pressure maximum"]},
    {"name": "Weekly blood pressure reading count", "category": "cardiovascular", "unit": "count", "aliases": ["weekly blood pressure reading count"]},
    {"name": "White blood cell count", "category": "hematology", "unit": "10^9/L", "aliases": ["лейкоцити (wbc)", "лейкоцити", "wbc"]},
    {"name": "Red blood cell count", "category": "hematology", "unit": "10^12/L", "aliases": ["еритроцити (rbc)", "еритроцити", "rbc"]},
    {"name": "Hemoglobin", "category": "hematology", "unit": "g/L", "aliases": ["гемоглобін (hgb)", "гемоглобін", "hgb"]},
    {"name": "Hematocrit", "category": "hematology", "unit": "%", "aliases": ["гематокрит (hct)", "гематокрит (нст)", "гематокрит", "hct"]},
    {"name": "Mean corpuscular volume", "category": "hematology", "unit": "fL", "aliases": ["середній об'єм еритроцита (mcv)", "mcv"]},
    # «(МСН)» and «(МСНС)» are Cyrillic homoglyphs of MCH and MCHC, identical on
    # the page and different to every string comparison.  Synevo prints the
    # Cyrillic pair, so both spellings have to be listed.
    {"name": "Mean corpuscular hemoglobin", "category": "hematology", "unit": "pg", "aliases": ["середній вміст гемоглобіну в еритроциті (mch)", "середній вміст гемоглобіну в еритроциті (мсн)", "mch"]},
    {"name": "Mean corpuscular hemoglobin concentration", "category": "hematology", "unit": "g/L", "aliases": ["середня концентрація гемоглобіну в еритроциті (mchc)", "середня концентрація гемоглобіну в еритроциті (мснс)", "середня концентрація hb в еритроцитах (мснс)", "мснс", "mchc"]},
    {"name": "Platelet count", "category": "hematology", "unit": "10^9/L", "aliases": ["тромбоцити (plt)", "тромбоцити", "plt"]},
    {"name": "Mean platelet volume", "category": "hematology", "unit": "fL", "aliases": ["середній об'єм тромбоцитів (mpv)", "mpv"]},
    {"name": "Erythrocyte sedimentation rate", "category": "inflammation", "unit": "mm/h", "aliases": ["шое", "аналіз крові: швидкість осідання еритроцитів (шое, esr)", "шое за вестергреном (швидкість осідання еритроцитів)", "esr", "шое (ser)"]},
    {"name": "Blood glucose", "category": "metabolic", "unit": "mmol/L", "aliases": ["глюкоза", "глюкоза (сироватка)", "глюкоза (сироватка крові)", "глюкоза (плазма крові)", "glucose", "blood glucose"]},
    {"name": "Hemoglobin A1c", "category": "metabolic", "unit": "%", "aliases": ["глікований гемоглобін (hba1c)", "глікований гемоглобін (hba1c)цільна кров", "hba1c", "hb a1c"]},
    {"name": "Albumin", "category": "liver", "unit": "g/L", "aliases": ["альбумін", "albumin"]},
    {"name": "Total protein", "category": "liver", "unit": "g/L", "aliases": ["білок загальний", "загальний білок", "total protein"]},
    {"name": "Urea", "category": "renal", "unit": "mmol/L", "aliases": ["сечовина", "urea"]},
    {"name": "Creatinine", "category": "renal", "unit": "µmol/L", "aliases": ["креатинін", "creatinine"]},
    # Calculated by ``anamna.derived`` from each creatinine reading
    # (CKD-EPI 2021, race-free) and also the concept a laboratory-printed eGFR
    # resolves to; the calculation steps aside where the report printed one.
    {"name": "Estimated glomerular filtration rate (CKD-EPI 2021)", "category": "renal", "unit": "mL/min/1.73m²", "aliases": ["estimated glomerular filtration rate (ckd-epi 2021)", "estimated glomerular filtration rate", "egfr (ckd-epi 2021)", "egfr", "ckd-epi", "швидкість клубочкової фільтрації", "розрахункова швидкість клубочкової фільтрації", "швидкість клубочкової фільтрації (ckd-epi)", "ршкф", "шкф", "ршкф (ckd-epi)", "шкф (ckd-epi)", "рскф", "скф"]},
    {"name": "Uric acid", "category": "metabolic", "unit": "µmol/L", "aliases": ["сечова кислота", "uric acid"]},
    {"name": "Total bilirubin", "category": "liver", "unit": "µmol/L", "aliases": ["білірубін загальний", "total bilirubin"]},
    {"name": "Direct bilirubin", "category": "liver", "unit": "µmol/L", "aliases": ["білірубін прямий", "direct bilirubin"]},
    {"name": "Indirect bilirubin", "category": "liver", "unit": "µmol/L", "aliases": ["білірубін не прямий", "білірубін непрямий", "indirect bilirubin"]},
    {"name": "Alanine aminotransferase", "category": "liver", "unit": "U/L", "aliases": ["аланінамінотрансфераза (алт, alt)", "алат(алт)", "алат (алт)", "алт", "alt"]},
    {"name": "Aspartate aminotransferase", "category": "liver", "unit": "U/L", "aliases": ["аспартатамінотрансфераза (аст, ast)", "асат(аст)", "асат (аст)", "аст", "ast"]},
    {"name": "Gamma-glutamyl transferase", "category": "liver", "unit": "U/L", "aliases": ["γ-глутаматтрансфераза (ггт, ggt)", "ггт", "ggt"]},
    {"name": "Alkaline phosphatase", "category": "liver", "unit": "U/L", "aliases": ["лужна фосфатаза (лф, alp)", "лужна фосфатаза(лф)", "лужна фосфатаза", "alp"]},
    {"name": "Total cholesterol", "category": "lipids", "unit": "mmol/L", "aliases": ["холестерин загальний", "холестерин", "total cholesterol"]},
    {"name": "LDL cholesterol", "category": "lipids", "unit": "mmol/L", "aliases": ["ліпопротеїди низької щільності (лпнщ", "ліпопротеїди низької щільності (лпнщ, ldl)", "ліпопротеїди низької щільності", "лпнщ", "ldl"]},
    {"name": "HDL cholesterol", "category": "lipids", "unit": "mmol/L", "aliases": ["ліпопротеїди високої щільності (лпвщ", "ліпопротеїди високої щільності (лпвщ, hdl)", "ліпопротеїди високої щільності", "лпвщ", "hdl"]},
    {"name": "VLDL cholesterol", "category": "lipids", "unit": "mmol/L", "aliases": ["ліпопротеїди дуже низької щільності", "ліпопротеїди дуже низької щільності (лпднщ)", "лпднщ", "vldl"]},
    {"name": "Triglycerides", "category": "lipids", "unit": "mmol/L", "aliases": ["тригліцериди", "triglycerides"]},
    {"name": "Atherogenic coefficient", "category": "lipids", "unit": "ratio", "aliases": ["коефіцієнт атерогенності", "коефіцієнт атерогенності (ка)", "atherogenic coefficient", "atherogenic index"]},
    {"name": "Thyroid stimulating hormone", "category": "thyroid", "unit": "mIU/L", "aliases": ["тиреотропний гормон (tsh)", "тиреотропний гормон. високочутливий, біотин-незалежний", "тиреотропний гормон", "ттг", "tsh"]},
    {"name": "Free triiodothyronine", "category": "thyroid", "unit": "pmol/L", "aliases": ["трийодтиронін вільний (ft3)", "ft3"]},
    {"name": "Free thyroxine", "category": "thyroid", "unit": "pmol/L", "aliases": ["тироксин вільний (ft4)", "тироксин вільний (t4 вільний)", "ft4"]},
    {"name": "Ferritin", "category": "iron", "unit": "ng/mL", "aliases": ["феритин", "ferritin"]},
    {"name": "Serum iron", "category": "iron", "unit": "µmol/L", "aliases": ["залізо", "залізо (сироватка крові)", "iron", "залізо сироваткове"]},
    {"name": "25-hydroxyvitamin D", "category": "vitamins", "unit": "ng/mL", "aliases": ["total 25-hydroxyvitamin d", "вітамін д (25-гідроксивітамін d, 25", "вітамін д (25-гідроксивітамін d, 25-(oh)d)", "загальний вітамін d (25-гідроксивітамін d)", "25-гідроксивітамін d (вітамін d загальний)", "25-oh vitamin d", "vitamin d", "вітамін d загальний"]},
    {"name": "Vitamin B12", "category": "vitamins", "unit": "pg/mL", "aliases": ["ціанокобаламін (вітамін b12)", "вітамін b12", "вітамін в12 (ціанокобаламін)", "vitamin b12"]},
    {"name": "Folate, serum", "category": "vitamins", "unit": "ng/mL", "aliases": ["фолієва кислота (сироватка)", "фолієва кислота", "folate"]},
    {"name": "Homocysteine", "category": "vitamins", "unit": "µmol/L", "aliases": ["гомоцистеїн", "homocysteine"]},
    {"name": "Magnesium", "category": "electrolytes", "unit": "mmol/L", "aliases": ["магній", "magnesium"]},
    {"name": "Potassium", "category": "electrolytes", "unit": "mmol/L", "aliases": ["калій", "калій (іонізований) (k), сироватка крові", "калій (іонізований) (к)", "potassium", "k"]},
    {"name": "Sodium", "category": "electrolytes", "unit": "mmol/L", "aliases": ["натрій", "натрій (іонізований) (na), сироватка крові", "натрій (іонізований) (na)", "sodium", "na"]},
    {"name": "Calcium, total", "category": "electrolytes", "unit": "mmol/L", "aliases": ["кальцій загальний (сироватка)", "кальцій загальний", "total calcium"]},
    {"name": "Calcium, ionized", "category": "electrolytes", "unit": "mmol/L", "aliases": ["кальцій іонізований (сироватка)", "кальцій іонізований", "ionized calcium"]},
    {"name": "INR", "category": "coagulation", "unit": "ratio", "aliases": ["мнг", "мнв", "inr", "international normalized ratio", "міжнародне нормалізоване відношення", "міжнародне нормалізоване відношення(мнв/inr)", "міжнародне нормалізоване відношення (мнв/inr)"]},
    {"name": "Fibrinogen", "category": "coagulation", "unit": "g/L", "aliases": ["фібриноген", "fibrinogen", "фібриноген по клаусу"]},
    {"name": "Total immunoglobulin E", "category": "allergy", "unit": "kU/L", "aliases": ["загальний ige", "total ige", "загальний ig e"]},
    {"name": "HLA-B27", "category": "immunogenetics", "unit": None, "value_type": "mixed", "aliases": ["виявлення носійства гену hla b-27", "hla-b27"]},
    {"name": "Aerobic and facultative anaerobic microbiota growth", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["ріст аеробної та факультативно-анаеробної мікробіоти"]},
    {"name": "Yeast and mould growth", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["дріжджові та плісняві гриби"]},
    {"name": "Normal site microbiota", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["нормальна мікрофлора даного локусу"]},
    {"name": "Amikacin susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["амікацин"]},
    {"name": "Cefepime susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["цефепім"]},
    {"name": "Ceftazidime susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["цефтазидим"]},
    {"name": "Ceftazidime-avibactam susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["цефтазидим-авіабактам"]},
    {"name": "Ceftolozane-tazobactam susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["цефтолозан-тазобактам"]},
    {"name": "Ciprofloxacin susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["ципрофлоксацин"]},
    {"name": "Imipenem susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["іміпенем", "imipenem",
        # OCR of «Іміпенем» on culture c6cb9f0c: every glyph read as its
        # nearest Latin shape (і→i, п→n, н→H).  A *resistant* result was filed
        # under a nameless concept the antibiogram never showed.
        "iminehem"]},
    {"name": "Levofloxacin susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["левофлоксацин"]},
    {"name": "Meropenem susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["меропенем"]},
    {"name": "Piperacillin-tazobactam susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["піперацилін-тазобактам"]},
    {"name": "Tobramycin susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["тобраміцин"]},
    # An EskuLab throat-culture antibiogram names 33
    # antibiotics; every one needs a definition here or its verdict lands on a
    # learned Ukrainian-only concept.
    {"name": "Azithromycin susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["азитроміцин"]},
    {"name": "Amoxicillin susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["амоксицилін"]},
    {"name": "Amoxicillin-clavulanate susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["амоксицилін-клавуланова кислота"]},
    {"name": "Ampicillin susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["ампіцилін"]},
    {"name": "Ampicillin-sulbactam susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["ампіцилін-сульбактам"]},
    {"name": "Benzylpenicillin susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["бензилпеніцилін"]},
    {"name": "Doxycycline susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["доксициклін"]},
    {"name": "Erythromycin susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["еритроміцин"]},
    {"name": "Ertapenem susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["ертапенем"]},
    {"name": "Clarithromycin susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["кларитроміцин"]},
    {"name": "Clindamycin susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["кліндаміцин"]},
    {"name": "Linezolid susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["лінезолід"]},
    {"name": "Moxifloxacin susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["моксифлоксацин"]},
    {"name": "Minocycline susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["міноциклін"]},
    {"name": "Piperacillin susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["піперацилін"]},
    {"name": "Roxithromycin susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["рокситроміцин"]},
    {"name": "Tetracycline susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["тетрациклін"]},
    {"name": "Tigecycline susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["тигециклін"]},
    {"name": "Trimethoprim-sulfamethoxazole susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["триметоприм-сульфаметоксазол"]},
    {"name": "Cefazolin susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["цефазолін"]},
    {"name": "Cefaclor susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["цефаклор"]},
    {"name": "Cefalexin susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["цефалексин"]},
    {"name": "Cefotaxime susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["цефотаксим"]},
    {"name": "Cefpodoxime susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["цефподоксим"]},
    {"name": "Ceftriaxone susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["цефтріаксон"]},
    {"name": "Cefuroxime susceptibility", "category": "microbiology", "unit": None, "value_type": "text", "aliases": ["цефуроксим"]},
    # The analyser's differential and the one counted by eye on a stained film
    # are two measurements of the same sample, printed one under the other:
    # Synevo 50.1 % «Нейтрофіли (на 100 лейкоцитів)» above «Сегментоядерні
    # нейтрофіли 50 %», EskuLab 45.0 % lymphocytes above a smear's 43 %.  Under
    # one concept the two readings share a date, one is hidden by the
    # one-per-day rule and the verdict flips with whichever survives.
    #
    # The printed label is the discriminator, and it is consistent across every
    # laboratory in the record: the analyser line carries «(на 100
    # лейкоцитів)» or a channel code (LYM%, GRA%, NEUT%), the smear line is
    # the bare cell name -- «Лімфоцити», «Моноцити», «Еозинофіли», «Базофіли»
    # (Synevo, Expert Hospital, St. Paraskeva) or EskuLab's «Лімфоцити
    # (Lymph)», «Моноцити (Mid)» under «ручна лейкоформула» -- and its
    # neutrophils are always split into segmented and band forms.  A bare
    # «Нейтрофіли» is therefore the analyser's total: a smear never prints one.
    # ponytail: label-only; a lab printing its analyser rows as bare cell names
    # would file them as the manual count -- teach the parser that lab's
    # section heading (it can emit "Lymphocytes" directly) if one appears.
    {"name": "Neutrophils", "category": "hematology", "unit": "%", "aliases": ["нейтрофіли", "нейтрофіли (на 100 лейкоцитів)", "відносне значення нейтрофілів (neut%)", "neut%", "neutrophils"]},
    {"name": "Neutrophils, absolute", "category": "hematology", "unit": "10^9/L", "aliases": ["нейтрофіли (абс.)", "абсолютне значення нейтрофілів (neut#)", "абсолютна кількість нейтрофілів", "neut#", "anc", "absolute neutrophil count", "neutrophils, absolute"]},
    {"name": "Segmented neutrophils", "category": "hematology", "unit": "%", "aliases": ["сегментоядерні нейтрофіли", "нейтрофіли сегментоядерні", "сегментоядерні нейтрофіли (neut)", "сегментоядерні", "segmented neutrophils", "segs"]},
    {"name": "Band neutrophils", "category": "hematology", "unit": "%", "aliases": ["паличкоядерні нейтрофіли", "нейтрофіли паличкоядерні", "паличкоядерні нейтрофіли (band)", "паличкоядерні", "band neutrophils", "stab neutrophils"]},
    {"name": "Neutrophils (manual differential)", "category": "hematology", "unit": "%", "aliases": ["neutrophils (manual differential)", "нейтрофіли (мікроскопія)", "нейтрофіли (ручна лейкоформула)", "нейтрофіли (ручний підрахунок)"]},
    {"name": "Lymphocytes", "category": "hematology", "unit": "%", "aliases": ["лімфоцити (на 100 лейкоцитів)", "відносне значення лімфоцитів (lym%)", "lym%", "lymphocytes", "лімфоцити (lym)-%"]},
    {"name": "Lymphocytes (manual differential)", "category": "hematology", "unit": "%", "aliases": ["лімфоцити", "лімфоцити (lymph)", "лімфоцити (мікроскопія)", "лімфоцити (ручна лейкоформула)", "lymphocytes (manual differential)"]},
    # Synevo abbreviates the absolute differential to «(абс.)».  Named here so
    # it joins the series the other laboratories already feed rather than
    # minting a second concept beside it: two names for one measurement give a
    # reader two half-length trends and no way to tell they are the same test.
    {"name": "Lymphocytes, absolute", "category": "hematology", "unit": "10^9/L", "aliases": ["абсолютне значення лімфоцитів (lym#)", "лімфоцити (абс.)", "lym#", "lymphocytes, absolute", "лімфоцити (lym)-абс."]},
    {"name": "Monocytes", "category": "hematology", "unit": "%", "aliases": ["моноцити (на 100 лейкоцитів)", "mon%", "mono%", "monocytes"]},
    {"name": "Monocytes (manual differential)", "category": "hematology", "unit": "%", "aliases": ["моноцити", "моноцити (mid)", "моноцити (мікроскопія)", "моноцити (ручна лейкоформула)", "monocytes (manual differential)"]},
    {"name": "Monocytes, absolute", "category": "hematology", "unit": "10^9/L", "aliases": ["моноцити (абс.)", "mon#", "mono#", "monocytes, absolute"]},
    {"name": "Eosinophils", "category": "hematology", "unit": "%", "aliases": ["еозинофіли (на 100 лейкоцитів)", "eos%", "eosinophils"]},
    {"name": "Eosinophils (manual differential)", "category": "hematology", "unit": "%", "aliases": ["еозинофіли", "еозинофіли (мікроскопія)", "еозинофіли (ручна лейкоформула)", "eosinophils (manual differential)"]},
    {"name": "Eosinophils, absolute", "category": "hematology", "unit": "10^9/L", "aliases": ["еозинофіли (абс.)", "eos#", "eosinophils, absolute"]},
    {"name": "Basophils", "category": "hematology", "unit": "%", "aliases": ["базофіли (на 100 лейкоцитів)", "baso%", "basophils"]},
    {"name": "Basophils (manual differential)", "category": "hematology", "unit": "%", "aliases": ["базофіли", "базофіли (мікроскопія)", "базофіли (ручна лейкоформула)", "basophils (manual differential)"]},
    {"name": "Basophils, absolute", "category": "hematology", "unit": "10^9/L", "aliases": ["базофіли (абс.)", "baso#", "basophils, absolute"]},
    # A three-part analyser's granulocyte channel counts neutrophils together
    # with eosinophils and basophils, so it is not the neutrophil count a
    # five-part analyser prints as «Нейтрофіли (абс.)» / NEUT# -- that one has
    # its own concept above.  St. Paraskeva's «Нейтрофіли (GRAN)» is the
    # channel (its code says so) and stays here.  Its «Моноцити (MID)-%» /
    # «-абс.» likewise is the analyser's MID channel (the 2-15 % band printed
    # beside GRAN and LYM), the mixed monocyte/eosinophil/basophil population,
    # so it files under "Mixed white cells" with Expert Hospital's MID rows --
    # not under Monocytes, and not under EskuLab's smear «Моноцити (Mid)»,
    # which has no -%/-абс. suffix and sits under «ручна лейкоформула».
    {"name": "Granulocytes", "category": "hematology", "unit": "%", "aliases": ["відносне значення гранулоцитів (gra%)", "gra%", "granulocytes", "нейтрофіли (gran)-%"]},
    {"name": "Granulocytes, absolute", "category": "hematology", "unit": "10^9/L", "aliases": ["абсолютне значення гранулоцитів (gra#)", "gra#", "granulocytes, absolute", "нейтрофіли (gran)-абс."]},
    {"name": "Mixed white cells", "category": "hematology", "unit": "%", "aliases": ["відносне значення суміші (моноцити, базофіли та еозинофіли) (mid%)", "відносне значення суміші (моноцити, базофіли та еозинофіли)", "моноцити (mid)-%"]},
    {"name": "Mixed white cells, absolute", "category": "hematology", "unit": "10^9/L", "aliases": ["абсолютне значення суміші (моноцити, базофіли та еозинофіли) (mid#)", "абсолютне значення суміші (моноцити, базофіли та еозинофіли)", "моноцити (mid)-абс."]},
    # The two «ширина розподілу еритроцитів ...» aliases below look swapped and
    # are not: Expert Hospital prints "коефіцієнт варіації" above values in F/л
    # (an SD spread) and "стандартне відхилення" above values in % (a CV one).
    # The parenthesised code is the reliable half of that label, so each alias
    # is filed by its code and by the unit its values actually arrive in.
    {"name": "Red cell distribution width, CV", "category": "hematology", "unit": "%", "aliases": ["ширина розподілу еритроцитів (стандартне відхилення) (rdw-cv)", "ширина розподілення еритроцитів (rdw-cv)", "ширина розподілу еритроцитів по об'ємі (rdw-cv)", "ширина розподілення еритроцитів", "ширина розподілу еритроцитів (rdw)"]},
    {"name": "Red cell distribution width, SD", "category": "hematology", "unit": "fL", "aliases": ["ширина розподілу еритроцитів (коефіцієнт варіації) (rdw-sd)", "ширина розподілення еритроцитів (rdw-sd)", "ширина розподілу еритроцитів (rdw-sd)"]},
    {"name": "Platelet distribution width", "category": "hematology", "unit": "%", "aliases": ["відносна ширина розподілу тромбоцитів за об'ємом (pdw)", "ширина розподілу тромбоцитів (pdw)"]},
    # Kept apart from the relative PDW above rather than merged into it: that
    # one arrives as ~12 %, this one as ~11 fL.  One series holding both would
    # read as a platelet population that halved and recovered between visits.
    {"name": "Platelet distribution width, SD", "category": "hematology", "unit": "fL", "aliases": ["ширина розподілення тромбоцитів за обсягами (pdw)"]},
    {"name": "Seromucoids", "category": "inflammation", "unit": "units", "aliases": ["серомукоїди"]},
    {"name": "Platelet large cell ratio", "category": "hematology", "unit": "%", "aliases": ["коефіцієнт великих тромбоцитів (p-lcr)", "p-lcr коефіцієнт великих тромбоцитів"]},
    {"name": "Plateletcrit", "category": "hematology", "unit": "%", "aliases": ["тромбокрит (pct)", "тромбокрит (рст)", "тромбокрит (pст)", "тромбокрит"]},
    {"name": "Activated partial thromboplastin time", "category": "coagulation", "unit": "s", "aliases": ["ачтч", "aptt", "активований частковий тромбопластиновий час (ачтч,артт)"]},
    {"name": "Prothrombin time", "category": "coagulation", "unit": "s", "aliases": ["птч (протромбіновий час)", "протромбіновий час", "протромбіновий час (пч)", "пч", "протромбіновий час (пч, рт, сек.)"]},
    {"name": "Quick prothrombin index", "category": "coagulation", "unit": "%", "aliases": ["протромбіновий індекс по квіку", "протромбіновий індекс (протромбін по квіку, %)", "протромбін за квіком, %"]},
    {"name": "Thrombin time", "category": "coagulation", "unit": "s", "aliases": ["тромбіновий час", "тромбіновий час (тч)", "тч"]},
    # Standard CRP (an acute-phase test reported against «до 5») and
    # high-sensitivity CRP (cardiovascular-risk tiers below 1 / 1-3 / above 3
    # mg/L) are different assays judged on different scales.  Filed together,
    # a standard 3.6 mg/L was labelled "high cardiovascular risk".  The name
    # decides; a plain name whose printed reference speaks of risk tiers is
    # re-filed as hs-CRP by ``refine_definition``.
    {"name": "C-reactive protein", "category": "inflammation", "unit": "mg/L", "aliases": ["с-реактивний білок", "с-реактивний білок (срб)", "срб", "c-reactive protein", "crp"]},
    {"name": "High-sensitivity C-reactive protein", "category": "inflammation", "unit": "mg/L", "aliases": ["high-sensitivity c-reactive protein", "hs-crp", "hscrp", "hs crp", "crp high sensitivity", "с-реактивний білок високочутливий", "с-реактивний білок (високочутливий)", "високочутливий с-реактивний білок", "с-реактивний білок ультрачутливий", "вч-срб", "hs-срб", "срб високочутливий", "срб (високочутливий)"]},
    {"name": "Rheumatoid factor", "category": "immunology", "unit": "IU/mL", "aliases": ["ревматоїдний фактор"]},
    {"name": "Antistreptolysin O", "category": "infection", "unit": "IU/mL", "aliases": ["антистрептолізин «о»", "антистрептолізин о", "aso"]},
    {"name": "Alpha-amylase", "category": "pancreas", "unit": "U/L", "aliases": ["амілаза альфа", "α-амілаза", "альфа-амілаза", "амілаза"]},
    {"name": "Lipase", "category": "pancreas", "unit": "U/L", "aliases": ["ліпаза", "lipase"]},
    {"name": "Thyroglobulin antibodies", "category": "thyroid", "unit": "IU/mL", "aliases": ["антитіла до тиреоглобуліну (attg)"]},
    {"name": "Thyroid peroxidase antibodies", "category": "thyroid", "unit": "IU/mL", "aliases": ["антитіла до тиреопероксидази (a-tpo)", "пероксидаза щитоподібної залози, антитіла (атпо)", "атпо"]},
    {"name": "Parathyroid hormone", "category": "hormones", "unit": "pg/mL", "aliases": ["паратгормон (птг 1-84).", "паратгормон (птг 1-84). високоспецифічний. біоінтактний", "паратгормон (птг 1-84)", "паратгормон", "pth"]},
    {"name": "Total testosterone", "category": "hormones", "unit": "nmol/L", "aliases": ["тестостерон загальний (т загальний", "тестостерон загальний (т загальний, сироватка)", "тестостерон загальний"]},
    {"name": "Urine appearance", "category": "urinalysis", "unit": None, "value_type": "text", "aliases": ["прозорість", "urine clarity"]},
    {"name": "Urine colour", "category": "urinalysis", "unit": None, "value_type": "text", "aliases": ["колір", "колір сечі (c-color)", "urine color", "urine colour"]},
    {"name": "Urine pH", "category": "urinalysis", "unit": None, "aliases": ["рн (c-ph)", "ph сечі", "urine ph"]},
    {"name": "Urine specific gravity", "category": "urinalysis", "unit": None, "aliases": ["питома вага", "питома вага (c-s.g.(ref))", "питома вага, г/мл", "відносна щільність", "питома густина", "urine specific gravity", "specific gravity"]},
    {"name": "Urine protein", "category": "urinalysis", "unit": "g/L", "value_type": "mixed", "aliases": ["білок в сечі", "білок (c-pro)", "білок в сечі, г/л", "білок", "urine protein"]},
    {"name": "Urine glucose", "category": "urinalysis", "unit": None, "value_type": "text", "aliases": ["глюкоза (c-glu)", "глюкоза", "глюкоза в сечі", "глюкоза, ммоль/л", "urine glucose"]},
    # "mixed" rather than "text": Expert Hospital reports ketones as a strip
    # grade on one report and as mmol/L on another.
    {"name": "Urine ketones", "category": "urinalysis", "unit": "mmol/L", "value_type": "mixed", "aliases": ["кетони (c-ket)", "кетонові тіла", "кетони", "urine ketones"]},
    {"name": "Urine nitrite", "category": "urinalysis", "unit": None, "value_type": "text", "aliases": ["нітрити (c-nit)", "нітрити, ммоль/л", "hітрити", "нітрити", "urine nitrite"]},
    {"name": "Urine bilirubin", "category": "urinalysis", "unit": None, "value_type": "mixed", "aliases": ["білірубін (c-bil)", "білірубін", "білірубін в сечі", "urine bilirubin"]},
    {"name": "Urine urobilinogen", "category": "urinalysis", "unit": "mg/dL", "value_type": "mixed", "aliases": ["уробіліноген", "уробіліноген (c-uro)", "urine urobilinogen"]},
    # "Лейкоцити в мкл (WBC)" and "Еритроцити в мкл (RBC)" are the headline rows
    # of an automated urinalysis, and they must be named here in full.  Left to
    # the parenthesised-code fallback in concept_for_alias(), the bare "(WBC)"
    # and "(RBC)" resolve against the blood count instead: 107.6 leukocytes per
    # microlitre of urine -- marked pyuria -- was published as a blood white
    # cell count of 107.6 x10^9/L, and 1.9 urinary erythrocytes as severe
    # anaemia.  Every other row of the same panel already names itself here.
    #
    # A urinalysis reports the same two cells three ways, and each is its own
    # measurement: the dipstick (leukocyte esterase, peroxidase activity --
    # a chemical reaction graded on a strip), the automated sediment count per
    # microlitre, and manual microscopy per high-power field.  None converts
    # into another: 25 cells/µL on a strip and 1-2 per field under a
    # microscope are not one series.  The label names the method when it
    # carries «C-LEU», «за активністю пероксидази» or «в п/з»; where it is a
    # bare «Лейкоцити», the printed unit does (Synevo prints the strip in
    # Leu/µL and the microscopy in «в п/з» under the same word), and
    # ``refine_definition`` re-files by it.
    {"name": "Urine leukocytes", "category": "urinalysis", "unit": "cells/µL", "value_type": "mixed", "aliases": ["лейкоцити (wbc)", "лейкоцити в сечі", "лейкоцити в мкл (wbc)", "лейкоцити", "urine leukocytes"]},
    {"name": "Urine leukocytes per high-power field", "category": "urinalysis", "unit": "per HPF", "value_type": "mixed", "aliases": ["лейкоцити (wbc), в п/з", "лейкоцити, в п/з", "лейкоцити в п/з", "лейкоцити в полі зору", "urine leukocytes per high-power field", "wbc/hpf", "leukocytes per hpf"]},
    {"name": "Urine erythrocytes", "category": "urinalysis", "unit": "cells/µL", "value_type": "mixed", "aliases": ["еритроцити в мкл (rbc)", "еритроцити", "urine erythrocytes"]},
    {"name": "Urine erythrocytes (dipstick)", "category": "urinalysis", "unit": "cells/µL", "value_type": "mixed", "aliases": ["еритроцити (за активністю пероксидази)", "еритроцити (за активністю пероксидази), кл/мкл", "еритроцити/гемоглобін (c-bld)", "еритроцити/гемоглобін (c-bld) - мг/дл приносний", "кров (c-bld)", "кров у сечі", "urine blood", "blood (dipstick)", "urine erythrocytes (dipstick)"]},
    {"name": "Urine erythrocytes per high-power field", "category": "urinalysis", "unit": "per HPF", "value_type": "mixed", "aliases": ["еритроцити (rbc), в п/з", "еритроцити, в п/з", "еритроцити в п/з", "еритроцити в полі зору", "urine erythrocytes per high-power field", "rbc/hpf", "erythrocytes per hpf"]},
    # «Незмінені еритроцити (NL RBC)» is EskuLab's automated count of the same
    # unchanged (isomorphic) cells the microscopy row counts per field -- but
    # in cells/µL, and there is no conversion between a microlitre and a
    # field.  ``refine_definition`` files a per-microlitre row under its own
    # series, so the per-field decision threshold never reads 16.4 cells/µL
    # as 16 cells per field.
    {"name": "Urine erythrocytes, unchanged (per microlitre)", "category": "urinalysis", "unit": "cells/µL", "value_type": "mixed", "aliases": ["urine erythrocytes, unchanged (per microlitre)"]},
    {"name": "Urine erythrocytes, unchanged", "category": "urinalysis", "unit": "per HPF", "value_type": "mixed", "aliases": ["еритроцити (не змінені)", "еритроцити не змінені, в п/з", "незмінені еритроцити (nl rbc)", "незмінені еритроцити", "nl rbc", "urine erythrocytes, unchanged"]},
    {"name": "Urine bacteria", "category": "urinalysis", "unit": "cells/µL", "value_type": "mixed", "aliases": ["бактерії", "бактерії в мкл (bact)", "бактерії, в п/з", "urine bacteria"]},
    # "mixed" across the sediment cluster: EskuLab's automated microscopy
    # reports the same analytes as numbers per µL, and a text-typed definition
    # made concept_for_alias refuse those rows, minting a learned concept per
    # vendor spelling -- one analyte, two or three half-length trends.
    {"name": "Squamous epithelial cells in urine", "category": "urinalysis", "unit": None, "value_type": "mixed", "aliases": ["плоский епітелій", "клітини плоского епітелію в мкл (squa.ec)", "клітини плоского епітелію, в п/з", "клітини плоского епітелію", "squamous epithelial cells in urine", "епітелій плоский"]},
    {"name": "Transitional epithelial cells in urine", "category": "urinalysis", "unit": None, "value_type": "mixed", "aliases": ["перехідний епітелій", "клітини перехідного епітелію в мкл (tran.ec)", "клітини перехідного епітелію", "transitional epithelial cells in urine", "епітелій перехідний"]},
    {"name": "Renal epithelial cells in urine", "category": "urinalysis", "unit": None, "value_type": "mixed", "aliases": ["нирковий епітелій", "клітини ниркового епітелію (rtec)", "клітини ниркового епітелію", "renal epithelial cells in urine", "епітелій нирковий"]},
    {"name": "Hyaline casts in urine", "category": "urinalysis", "unit": None, "value_type": "mixed", "aliases": ["циліндри гіалінові", "гіалінові циліндри", "гіалінові циліндри в мкл (hy.cast)", "hyaline casts in urine"]},
    {"name": "Granular casts in urine", "category": "urinalysis", "unit": None, "value_type": "text", "aliases": ["циліндри зернисті", "зернисті циліндри", "granular casts in urine"]},
    {"name": "Epithelial casts in urine", "category": "urinalysis", "unit": None, "value_type": "text", "aliases": ["циліндри епітеліальні", "епітеліальні циліндри", "epithelial casts in urine"]},
    {"name": "Brown-pigmented casts in urine", "category": "urinalysis", "unit": None, "value_type": "text", "aliases": ["буропігментовані циліндри", "brown-pigmented casts in urine", "циліндри буропігментовані"]},
    {"name": "Waxy casts in urine", "category": "urinalysis", "unit": None, "value_type": "text", "aliases": ["циліндри воскоподібні", "восковидні циліндри", "воскоподібні циліндри", "waxy casts in urine", "циліндри восковидні"]},
    {"name": "Urine mucus", "category": "urinalysis", "unit": None, "value_type": "text", "aliases": ["слиз", "слиз, в п/з", "urine mucus"]},
    {"name": "Urine salts", "category": "urinalysis", "unit": None, "value_type": "text", "aliases": ["солі", "urine salts"]},
    {"name": "H. pylori stool antigen", "category": "infection", "unit": None, "value_type": "text", "aliases": ["h.pylori антиген у калі (якісне визначення)", "h. pylori stool antigen", "хелікобактер пілорі, кал"]},
    # Synevo prints «HBcorAg, антитіла сумарні»: total antibodies to the core
    # antigen, not the antigen itself.  Renamed from "Hepatitis B core antigen
    # marker" with its id kept (CONCEPT_ID_OVERRIDES), so the old address and
    # its reference entry still resolve; the old name stays as an alias for
    # search.
    {"name": "Hepatitis B core antibodies, total (anti-HBc)", "category": "infection", "unit": "index", "aliases": ["вірус гепатиту b (hbv), hbcorag", "вірус гепатиту b (hbv), hbcorag, антитіла сумарні", "вірус гепатиту b (hbv), anti-hbc", "антитіла до hbcorag сумарні", "антитіла до ядерного антигену вірусу гепатиту b", "анти-hbc", "anti-hbc", "anti-hbc total", "hbcab", "hepatitis b core antibodies", "hepatitis b core antigen marker"]},
    {"name": "Antinuclear antibodies", "category": "autoimmune", "unit": "index", "aliases": ["антинуклеарні антитіла (ana)сироватка", "ana"]},
    # «гепатиту в» with a Cyrillic в and «гепатиту b» with a Latin b are the
    # same printed line from two labs; only the second was listed, so the
    # Synevo result was filed as an unknown analyte instead of an HBsAg.
    # "(кількісне визначення)" is the same surface-antigen assay reported with
    # its index rather than as a yes/no; without the alias it was filed as an
    # unknown analyte and never joined the series it belongs to.
    {"name": "Hepatitis B surface antigen", "category": "infection", "unit": "index", "aliases": ["вірус гепатиту в (hbv), hbsag", "вірус гепатиту b (hbv), hbsag", "вірус гепатиту b (hbv), hbsag (австралійський антиген)", "вірус гепатиту в (hbv), hbsag (австралійський антиген)", "вірус гепатиту в (hbv), hbsag (кількісне визначення)", "вірус гепатиту b (hbv), hbsag (кількісне визначення)", "hbsag"]},
    # One assay, two spellings: Synevo «Вірус гепатиту C (HCV), антитіла
    # сумарні», EskuLab «HCV антитіла сумарні».  They were two concepts, so a
    # 2025 and a 2026 result never met on one trend.
    {"name": "Hepatitis C total antibodies", "category": "infection", "unit": "index", "aliases": ["hcv антитіла сумарні", "вірус гепатиту c (hcv), антитіла сумарні", "антитіла до вірусу гепатиту c сумарні", "anti-hcv", "анти-hcv", "hcv ab", "hepatitis c antibodies", "hepatitis c total antibodies"]},
    {"name": "Treponema pallidum total antibodies", "category": "infection", "unit": "index", "aliases": ["антитіла сумарні до treponema pallidum", "антитіла сумарні до treponema"]},
    {"name": "Mumps virus IgG", "category": "infection", "unit": "index", "aliases": ["вірус паротиту, антитіла igg"]},
    {"name": "Mumps virus IgM", "category": "infection", "unit": "index", "aliases": ["вірус паротиту, антитіла igm"]},
    {"name": "Blood group", "category": "hematology", "unit": None, "value_type": "text", "aliases": ["група крові", "група крові (ab0)", "blood group", "abo blood group"]},
    {"name": "Rhesus factor", "category": "hematology", "unit": None, "value_type": "text", "aliases": ["резус-фактор (+)", "резус-фактор", "rh factor"]},
    # A rapid antigen test on a nasal or nasopharyngeal swab.  Expert Hospital
    # reports it with no PDF, only in its app (labsync, unavailable_nofile):
    # «Антиген SARS-CoV-2» under the packet «Тест на визначення антигену
    # SARS-CoV-2».  Antigen only: a PCR or an antibody result is a different
    # measurement and gets its own concept.
    {"name": "SARS-CoV-2 antigen", "category": "infection", "unit": None, "value_type": "text", "aliases": ["антиген sars-cov-2", "тест на визначення антигену sars-cov-2", "швидкий тест на антиген sars-cov-2", "експрес-тест на антиген sars-cov-2", "антиген коронавірусу sars-cov-2", "sars-cov-2 antigen", "sars-cov-2 rapid antigen test", "covid-19 antigen"]},
    {"name": "HIV I/II rapid test", "category": "infection", "unit": None, "value_type": "text", "aliases": ["швидкий тест для виявлення віл і та іі типу"]},
    {"name": "Syphilis antibody rapid test", "category": "infection", "unit": None, "value_type": "text", "aliases": ["швидкий тест для виявлення антитіл до сифілісу"]},
    {"name": "Hepatitis C antibody rapid test", "category": "infection", "unit": None, "value_type": "text", "aliases": ["швидкий тест для виявлення антитіл до вірусу гепатиту с"]},
    {"name": "Hepatitis B surface antigen rapid test", "category": "infection", "unit": None, "value_type": "text", "aliases": ["швидкий тест для виявлення поверхневого антигену до вірусу гепатиту", "швидкий тест для виявлення поверхневого антигену до вірусу гепатиту в (hbsag)"]},
    {"name": "Chlamydia trachomatis PCR", "category": "infection", "unit": None, "value_type": "text", "aliases": ["chlamydia trachomatis (плр) (кількісне визначення)", "chlamydia trachomatis (плр) (кількісне"]},
    {"name": "Mycoplasma genitalium PCR", "category": "infection", "unit": None, "value_type": "text", "aliases": ["mycoplasma genitalium (плр) (кількісне визначення)", "mycoplasma genitalium (плр) (кількісне"]},
    {"name": "Mycoplasma hominis DNA", "category": "infection", "unit": None, "value_type": "text", "aliases": ["виявлення днк mycoplasma hominis (плр) (кількісне визначення)", "виявлення днк mycoplasma hominis"]},
    {"name": "Neisseria gonorrhoeae DNA", "category": "infection", "unit": None, "value_type": "text", "aliases": ["виявлення днк neisseria gonorrhoeae (плр) (якісне визначення)", "виявлення днк neisseria gonorrhoeae"]},
    {"name": "Trichomonas vaginalis DNA", "category": "infection", "unit": None, "value_type": "text", "aliases": ["виявлення днк trichomonas vaginalis (плр) (якісне визначення)", "виявлення днк trichomonas vaginalis"]},
    {"name": "Ureaplasma parvum DNA", "category": "infection", "unit": None, "value_type": "text", "aliases": ["виявлення днк ureaplasma parvum (плр) (кількісне визначення)"]},
    {"name": "Ureaplasma urealyticum DNA", "category": "infection", "unit": None, "value_type": "text", "aliases": ["виявлення днк ureaplasma urealyticum (плр) (кількісне визначення)"]},
    {"name": "Promyelocytes", "category": "hematology", "unit": "%", "aliases": ["промієлоцити"]},
    {"name": "Myelocytes", "category": "hematology", "unit": "%", "aliases": ["мієлоцити"]},
    {"name": "Metamyelocytes", "category": "hematology", "unit": "%", "aliases": ["метамієлоцити"]},
    {"name": "Immature granulocytes", "category": "hematology", "unit": "%", "aliases": ["незрілі гранулоцити (на 100", "незрілі гранулоцити (на 100 лейкоцитів)", "ig-фракція незрілих гранулоцитів"]},
    {"name": "Immature granulocytes, absolute", "category": "hematology", "unit": "10^9/L", "aliases": ["незрілі гранулоцити (абс.)"]},
    {"name": "Red-cell folate calculation hematocrit", "category": "vitamins", "unit": "%", "aliases": ["фолати (гематокрит)"]},
    {"name": "Red-cell folate concentration", "category": "vitamins", "unit": "ng/mL", "aliases": ["фолати (концентрація в еритроцитах)"]},
    {"name": "Whole-blood folate", "category": "vitamins", "unit": "ng/mL", "aliases": ["фолати (цільна кров)"]},
    {"name": "Urine sample delivered volume", "category": "urinalysis", "unit": "mL", "aliases": ["доставлена кількість, мл"]},
    {"name": "Urine leukocyte clusters", "category": "urinalysis", "unit": "cells/µL", "aliases": ["скупчення лейкоцитів (wbc clumps)", "скупчення лейкоцитів (wbc"]},
    {"name": "Urine atypical-like cells", "category": "urinalysis", "unit": "cells/µL", "aliases": ["к-сть клітин схожих на атипові в мкл сечі", "к-сть клітин схожих на атипові в мкл"]},
    {"name": "Urine yeast-like cells", "category": "urinalysis", "unit": "cells/µL", "aliases": ["дріжджеподібні клітини (ylc)"]},
    {"name": "Urine mucus elements", "category": "urinalysis", "unit": "cells/µL", "aliases": ["елементи слизу в мкл (mucus)"]},
    {"name": "Urine sperm cells", "category": "urinalysis", "unit": "cells/µL", "value_type": "mixed", "aliases": ["сперматозоїди в мкл (sperm)", "сперматозоїди", "сперматозоїди, в п/з"]},
    {"name": "Urine yeast", "category": "urinalysis", "unit": None, "value_type": "text", "aliases": ["дріжджоподібні гриби", "дріжджеподібні гриби", "дріжджеподібні гриби, в п/з", "дріжджоподібні гриби, в п/з"]},
    {"name": "Urine amorphous urates", "category": "urinalysis", "unit": None, "value_type": "text", "aliases": ["аморфні урати"]},
    {"name": "Urine amorphous phosphates", "category": "urinalysis", "unit": None, "value_type": "text", "aliases": ["аморфні фосфати"]},
    {"name": "Urine trichomonads", "category": "urinalysis", "unit": None, "value_type": "text", "aliases": ["трихомонади"]},
    # Synevo's manual sediment microscopy names each crystal it looks for.
    # Without a definition every one became a Ukrainian-only concept with no
    # English name.  «Фосфорнокисле вапно» and «фосфат кальцію» are printed as
    # two rows of the same report, so they stay two concepts.
    {"name": "Uric acid crystals in urine", "category": "urinalysis", "unit": None, "value_type": "mixed", "aliases": ["кристали сечової кислоти", "uric acid crystals"]},
    {"name": "Calcium oxalate crystals in urine", "category": "urinalysis", "unit": None, "value_type": "mixed", "aliases": ["кристали оксалату кальцію", "оксалати кальцію", "calcium oxalate crystals"]},
    {"name": "Triple phosphate crystals in urine", "category": "urinalysis", "unit": None, "value_type": "mixed", "aliases": ["кристали трипельфосфатів", "трипельфосфати", "струвіт", "triple phosphate crystals", "struvite crystals"]},
    {"name": "Calcium phosphate crystals in urine", "category": "urinalysis", "unit": None, "value_type": "mixed", "aliases": ["кристали фосфату кальцію", "calcium phosphate crystals"]},
    {"name": "Phosphate of lime crystals in urine", "category": "urinalysis", "unit": None, "value_type": "mixed", "aliases": ["кристали фосфорнокислого вапна", "phosphate of lime crystals"]},
    {"name": "Calcium carbonate crystals in urine", "category": "urinalysis", "unit": None, "value_type": "mixed", "aliases": ["кристали карбонату кальцію", "calcium carbonate crystals"]},
    {"name": "Ammonium biurate crystals in urine", "category": "urinalysis", "unit": None, "value_type": "mixed", "aliases": ["кристали біурата амонію", "кристали біурату амонію", "ammonium biurate crystals"]},
    {"name": "Bilirubin crystals in urine", "category": "urinalysis", "unit": None, "value_type": "mixed", "aliases": ["кристали білірубіну", "bilirubin crystals"]},
    {"name": "Urine bladder epithelial cells", "category": "urinalysis", "unit": None, "value_type": "text", "aliases": ["клітини епітелію сечового міхура, в п/з", "клітини епітелію сечового міхура"]},
    {"name": "Urine erythrocyte casts", "category": "urinalysis", "unit": None, "value_type": "text", "aliases": ["циліндри еритроцитарні", "циліндри еритроцитарні , в п/з", "еритроцитарні циліндри"]},
    {"name": "Urine leukocyte casts", "category": "urinalysis", "unit": None, "value_type": "text", "aliases": ["циліндри лейкоцитарні", "циліндри лейкоцитарні , в п/з", "лейкоцитарні циліндри"]},
    # A bare urinalysis «Еритроцити» is the red-cell count (dipstick or
    # microscopy), not the dysmorphic «змінені» subset -- like bare «лейкоцити».
    {"name": "Urine changed erythrocytes", "category": "urinalysis", "unit": "per HPF", "value_type": "mixed", "aliases": ["еритроцити змінені", "еритроцити змінені, в п/з", "еритроцити (змінені)"]},
    # The strip's leukocyte reaction; renamed from "Urine leukocyte esterase"
    # with its id kept (CONCEPT_ID_OVERRIDES).  Expert Hospital prints the same
    # strip result as «Лейкоцити в сечі, кл/мкл» in its chemistry block.
    {"name": "Urine leukocytes (dipstick)", "category": "urinalysis", "unit": "cells/µL", "value_type": "mixed", "aliases": ["лейкоцити (c-leu)", "лейкоцити в сечі, кл/мкл", "лейкоцитарна естераза", "лейкоцитестераза", "leukocyte esterase", "urine leukocyte esterase", "urine leukocytes (dipstick)"]},
    {"name": "Urine pH", "category": "urinalysis", "unit": None, "aliases": ["рн"]},
    {"name": "Urine salts", "category": "urinalysis", "unit": None, "value_type": "text", "aliases": ["солі, в п/з"]},
    # The coprogram.  Two pages of it produced nothing at all until the
    # column parser read the table, so every one of these is a result that
    # was in the record's source documents and not in the record.  Each name
    # is qualified with the specimen because the report prints them bare:
    # «Колір», «Лейкоцити», «Еритроцити» and «Слиз» resolve straight onto the
    # urine concepts of the same name otherwise.  No numeric target is
    # recorded -- these are qualitative findings whose expected value the
    # report states for itself, and that printed reference is stored with
    # each observation.
    {"name": "Stool colour", "category": "stool", "unit": None, "value_type": "text", "aliases": ["колір (кал)", "колір калових мас"]},
    {"name": "Stool form", "category": "stool", "unit": None, "value_type": "text", "aliases": ["форма (кал)"]},
    {"name": "Stool consistency", "category": "stool", "unit": None, "value_type": "text", "aliases": ["консистенція (кал)"]},
    {"name": "Stool odour", "category": "stool", "unit": None, "value_type": "text", "aliases": ["запах (кал)"]},
    {"name": "Stool undigested food residue", "category": "stool", "unit": None, "value_type": "text", "aliases": ["залишки неперетравленої їжі (кал)"]},
    {"name": "Stool food residue", "category": "stool", "unit": None, "value_type": "text", "aliases": ["залишки їжі (кал)"]},
    {"name": "Stool mucus", "category": "stool", "unit": None, "value_type": "text", "aliases": ["слиз (кал)"]},
    {"name": "Stool blood", "category": "stool", "unit": None, "value_type": "text", "aliases": ["кров (кал)"]},
    {"name": "Stool pus", "category": "stool", "unit": None, "value_type": "text", "aliases": ["гній (кал)"]},
    {"name": "Stool tissue fragments", "category": "stool", "unit": None, "value_type": "text", "aliases": ["шматочки тканини (кал)"]},
    {"name": "Stool concretions", "category": "stool", "unit": None, "value_type": "text", "aliases": ["конкременти (копроліти) (кал)"]},
    {"name": "Stool pH", "category": "stool", "unit": None, "value_type": "numeric", "aliases": ["реакція (кал)", "ph (кал)"]},
    {"name": "Stool muscle fibres, altered", "category": "stool", "unit": None, "value_type": "text", "aliases": ["м'язові волокна змінені (кал)", "м'язові волокна перетравлені (кал)"]},
    {"name": "Stool muscle fibres, slightly altered", "category": "stool", "unit": None, "value_type": "text", "aliases": ["м'язові волокна малозмінені (кал)"]},
    {"name": "Stool muscle fibres, unaltered", "category": "stool", "unit": None, "value_type": "text", "aliases": ["м'язові волокна не змінені (кал)", "м'язові волокна неперетравлені (кал)"]},
    {"name": "Stool plant fibre, undigested", "category": "stool", "unit": None, "value_type": "text", "aliases": ["рослинна клітковина неперетравлена (кал)", "неперетравлена клітковина (кал)"]},
    {"name": "Stool plant fibre, digested", "category": "stool", "unit": None, "value_type": "text", "aliases": ["рослинна клітковина перетравлена (кал)", "перетравлена клітковина (кал)"]},
    {"name": "Stool starch, intracellular", "category": "stool", "unit": None, "value_type": "text", "aliases": ["крохмаль внутріклітинний (кал)", "крохмальні зерна внутрішньоклітинні (кал)"]},
    {"name": "Stool starch, extracellular", "category": "stool", "unit": None, "value_type": "text", "aliases": ["крохмаль позаклітинний (кал)", "крохмальні зерна позаклітинні (кал)"]},
    {"name": "Stool neutral fat", "category": "stool", "unit": None, "value_type": "text", "aliases": ["нейтральний жир (кал)"]},
    {"name": "Stool fatty acids", "category": "stool", "unit": None, "value_type": "text", "aliases": ["жирні кислоти (кал)"]},
    {"name": "Stool soaps", "category": "stool", "unit": None, "value_type": "text", "aliases": ["мило (кал)", "мила (кал)"]},
    {"name": "Stool crystals", "category": "stool", "unit": None, "value_type": "text", "aliases": ["кристали (кал)"]},
    {"name": "Stool epithelium", "category": "stool", "unit": None, "value_type": "text", "aliases": ["епітелій (кал)"]},
    {"name": "Stool leukocytes", "category": "stool", "unit": None, "value_type": "text", "aliases": ["лейкоцити (кал)", "лейкоцити (копрограма)"]},
    {"name": "Stool erythrocytes", "category": "stool", "unit": None, "value_type": "text", "aliases": ["еритроцити (кал)", "еритроцити (копрограма)"]},
    {"name": "Stool cells with malignant features", "category": "stool", "unit": None, "value_type": "text", "aliases": ["елементи з ознаками злоякісності (кал)"]},
    {"name": "Stool iodophilic flora", "category": "stool", "unit": None, "value_type": "text", "aliases": ["йодофільна флора (кал)", "йодофільні бактерії (кал)"]},
    {"name": "Stool protozoa", "category": "stool", "unit": None, "value_type": "text", "aliases": ["найпростіші (кал)", "найпростіші (цисти лямблій) (кал)", "вегетативні форми і цисти найпростіших (кал)"]},
    {"name": "Stool helminth eggs", "category": "stool", "unit": None, "value_type": "text", "aliases": ["яйця гельмінтів (кал)"]},
    {"name": "Stool yeast-like fungal elements", "category": "stool", "unit": None, "value_type": "text", "aliases": ["елементи гриба, подібного до дріжджевого (кал)", "дріжджовий грибок (кал)"]},
    {"name": "Transitional epithelial cells in urine", "category": "urinalysis", "unit": None, "value_type": "mixed", "aliases": ["клітини перехідного епітелію , в п/з"]},
    {"name": "Renal epithelial cells in urine", "category": "urinalysis", "unit": None, "value_type": "mixed", "aliases": ["клітини ниркового епітелію , в п/з"]},
    {"name": "Hyaline casts in urine", "category": "urinalysis", "unit": None, "value_type": "mixed", "aliases": ["циліндри гіалінові, в п/з"]},
    {"name": "Granular casts in urine", "category": "urinalysis", "unit": None, "value_type": "text", "aliases": ["циліндри зернисті, в п/з"]},
    {"name": "Epithelial casts in urine", "category": "urinalysis", "unit": None, "value_type": "text", "aliases": ["циліндри епітеліальні , в п/з"]},
    {"name": "Waxy casts in urine", "category": "urinalysis", "unit": None, "value_type": "text", "aliases": ["циліндри воскоподібні, в п/з"]},
    # EskuLab's automated urinalysis reports four sediment aggregates the
    # manual-microscopy definitions above have no counterpart for.  Named here
    # so their readings stop minting learned Ukrainian-only concepts.
    {"name": "Non-hyaline casts in urine", "category": "urinalysis", "unit": None, "value_type": "mixed", "aliases": ["негіалінові циліндри в мкл (path.cast)"]},
    {"name": "Total casts in urine", "category": "urinalysis", "unit": None, "value_type": "mixed", "aliases": ["циліндри (cast)"]},
    {"name": "Crystals in urine", "category": "urinalysis", "unit": None, "value_type": "mixed", "aliases": ["кристали в мкл (x`tal)"]},
    {"name": "Epithelial cells in urine", "category": "urinalysis", "unit": None, "value_type": "mixed", "aliases": ["епітеліальні клітини в мкл (ec)"]},
    {"name": "Non-squamous epithelial cells in urine", "category": "urinalysis", "unit": None, "value_type": "mixed", "aliases": ["клітини не плоского епітелію в мкл (non sec)"]},
    {"name": "Ro/SS-A 52 antibodies", "category": "autoimmune", "unit": "kU/L", "aliases": ["ro/ss-a 52"]},
    {"name": "La/SS-B antibodies", "category": "autoimmune", "unit": "kU/L", "aliases": ["la/ss-b"]},
    {"name": "CENP-B antibodies", "category": "autoimmune", "unit": "kU/L", "aliases": ["cenp-b"]},
    {"name": "Scl-70 antibodies", "category": "autoimmune", "unit": "kU/L", "aliases": ["scl-70"]},
    {"name": "Double-stranded DNA antibodies", "category": "autoimmune", "unit": "kU/L", "aliases": ["dsdna"]},
    {"name": "Jo-1 antibodies", "category": "autoimmune", "unit": "kU/L", "aliases": ["jo-1"]},
    {"name": "Myeloperoxidase antibodies", "category": "autoimmune", "unit": "kU/L", "aliases": ["mpo"]},
    {"name": "Proteinase 3 antibodies", "category": "autoimmune", "unit": "kU/L", "aliases": ["pr3"]},
    {"name": "AMA-M2 antibodies", "category": "autoimmune", "unit": "kU/L", "aliases": ["ama m2"]},
    {"name": "LC1 antibodies", "category": "autoimmune", "unit": "kU/L", "aliases": ["lc 1"]},
    {"name": "LKM1 antibodies", "category": "autoimmune", "unit": "kU/L", "aliases": ["lkm 1"]},
    {"name": "PM/Scl-100 antibodies", "category": "autoimmune", "unit": "kU/L", "aliases": ["pm/scl 100"]},
    {"name": "SRP54 antibodies", "category": "autoimmune", "unit": "kU/L", "aliases": ["srp 54"]},
    {"name": "Sp100 antibodies", "category": "autoimmune", "unit": "kU/L", "aliases": ["sp 100"]},
    {"name": "gp210 antibodies", "category": "autoimmune", "unit": "kU/L", "aliases": ["gp 210"]},
    {"name": "Ku antibodies", "category": "autoimmune", "unit": "kU/L", "aliases": ["ku"]},
    {"name": "Sm antibodies", "category": "autoimmune", "unit": "kU/L", "aliases": ["sm"]},
    {"name": "U1-snRNP antibodies", "category": "autoimmune", "unit": "kU/L", "aliases": ["u1-snrnp"]},
    # Introduced by one EskuLab order: a protein electrophoresis, an
    # apolipoprotein set, a coagulation panel and a manual differential, none
    # of which this record had a definition for.  Without one each landed on a
    # concept named after its Ukrainian label, which the English page then
    # printed in Ukrainian and no reference guidance could attach to.
    {"name": "C-peptide", "category": "pancreas", "unit": "ng/mL", "aliases": ["с-пептид"]},
    # Synevo prints insulin in «мкОд/мл» on one panel and «мкМО/мл» on
    # another: the same WHO-calibrated quantity, made one unit for this concept
    # only by ``health.CONCEPT_UNIT_ALIASES``.
    {"name": "Insulin", "category": "metabolic", "unit": "mIU/L", "aliases": ["інсулін", "insulin", "fasting insulin"]},
    # Tumour markers.  Synevo writes the CA 125 code three ways («(СА-125)»,
    # «(СА 125)», «СА125» in a two-column table), with a Cyrillic «СА» the
    # homoglyph fold in ``label_key`` matches to the Latin "CA".  Unnamed, each
    # spelling started its own series.
    {"name": "Cancer antigen 125 (CA 125)", "category": "tumour_markers", "unit": "U/mL", "aliases": ["онкомаркер яєчників (са-125)", "онкомаркер яєчників (са 125)", "онкомаркер яєчників (са125)", "са-125", "са 125", "са125", "cancer antigen 125"]},
    {"name": "Cancer antigen 15-3 (CA 15-3)", "category": "tumour_markers", "unit": "U/mL", "aliases": ["онкомаркер молочної залози (са 15-3)", "онкомаркер молочної залози (са15-3)", "са 15-3", "са15-3", "cancer antigen 15-3"]},
    {"name": "Human epididymis protein 4 (HE4)", "category": "tumour_markers", "unit": "pmol/L", "aliases": ["онкомаркер he4", "ранній онкомаркер раку яєчників he-4 антиген", "ранній онкомаркер раку яєчників he-4", "ранній онкомаркер раку яєчників", "he4", "he-4", "human epididymis protein 4"]},
    {"name": "Non-HDL cholesterol", "category": "lipids", "unit": "mmol/L", "aliases": ["холестерин не-лпвщ"]},
    {"name": "Apolipoprotein A1", "category": "lipids", "unit": "g/L", "aliases": ["аполіпопротеїн а1"]},
    {"name": "Apolipoprotein B", "category": "lipids", "unit": "g/L", "aliases": ["аполіпопротеїн в"]},
    {"name": "Lipoprotein(a)", "category": "lipids", "unit": "nmol/L", "aliases": ["ліпопротеїн (а) lp (a)", "ліпопротеїн (а)"]},
    {"name": "Beta-lipoproteins", "category": "lipids", "unit": "units", "aliases": ["β-ліпопротеїди", "бета-ліпопротеїди"]},
    {"name": "Thymol turbidity test", "category": "liver", "unit": "units", "aliases": ["тимолова проба"]},
    {"name": "Albumin fraction", "category": "liver", "unit": "%", "aliases": ["альбумін фракційний"]},
    {"name": "Alpha-1 globulins", "category": "liver", "unit": "%", "aliases": ["α1 глобуліни", "альфа1 глобуліни"]},
    {"name": "Alpha-2 globulins", "category": "liver", "unit": "%", "aliases": ["α2 глобуліни", "альфа2 глобуліни"]},
    {"name": "Beta globulins", "category": "liver", "unit": "%", "aliases": ["β глобуліни", "бета глобуліни"]},
    {"name": "Gamma globulins", "category": "liver", "unit": "%", "aliases": ["γ глобуліни", "гамма глобуліни"]},
    {"name": "Albumin to globulin ratio", "category": "liver", "unit": None, "aliases": ["а/г коефіцієнт"]},
    {"name": "Nucleated red blood cell fraction", "category": "hematology", "unit": "%", "aliases": ["nrbc-фракція ядровмістних еритроцитів"]},
    {"name": "Atypical lymphocytes", "category": "hematology", "unit": "%", "aliases": ["атипові лімфоцити"]},
    {"name": "Reactive lymphocytes", "category": "hematology", "unit": "%", "aliases": ["реактивні лімфоцити"]},
    # Measurements printed inside echocardiography and ultrasound reports.  The
    # side (left/right carotid, right/left thyroid lobe) is the observation's
    # site, not a concept of its own: one person's left and right CIMT are the
    # same measurement taken twice.
    {"name": "Left ventricular mass index", "category": "cardiovascular", "unit": "g/m²", "aliases": ["індекс маси міокарда лш", "індекс маси міокарда лівого шлуночка", "іммлш", "lvmi", "lv mass index", "left ventricular mass index"]},
    # The un-indexed mass in grams. No parser emits it yet: one Expert Hospital
    # echo prints it under the index's label, and a reviewer refiles it here.
    {"name": "Left ventricular mass", "category": "cardiovascular", "unit": "g", "aliases": ["маса міокарда лш", "маса міокарда лівого шлуночка", "ммлш", "lv mass", "lvm", "left ventricular mass"]},
    {"name": "Carotid intima-media thickness", "category": "cardiovascular", "unit": "mm", "aliases": ["товщина кім", "кім", "кім справа", "кім зліва", "товщина комплексу інтима-медіа", "товщина комплексу інтима-медіа загальної сонної артерії", "тім", "товщина інтима-медіа", "cimt", "imt", "intima-media thickness", "carotid intima-media thickness"]},
    {"name": "Peak systolic velocity, common carotid artery", "category": "cardiovascular", "unit": "cm/s", "aliases": ["пікова систолічна швидкість кровотоку", "пікова систолічна швидкість кровотоку в загальній сонній артерії", "пікова систолічна швидкість (зса)", "максимальна систолічна швидкість кровотоку", "vps", "vps зса", "psv", "psv cca", "peak systolic velocity", "peak systolic velocity, common carotid artery"]},
    {"name": "Liver craniocaudal size", "category": "liver", "unit": "mm", "aliases": ["косий вертикальний розмір правої частки печінки", "косий вертикальний розмір", "косий вертикальний (по середньо-ключичній лінії)", "права частка: косий вертикальний (по середньо-ключичній лінії)", "квр правої частки", "квр", "краніокаудальний розмір печінки", "liver craniocaudal size", "liver span"]},
    {"name": "Common bile duct diameter", "category": "liver", "unit": "mm", "aliases": ["холедох", "діаметр холедоха", "холедох на всьому проміжку нерозширений", "холедох на всьому проміжку не розширений", "загальна жовчна протока", "діаметр загальної жовчної протоки", "cbd", "common bile duct", "common bile duct diameter"]},
    {"name": "Bladder wall thickness", "category": "renal", "unit": "mm", "aliases": ["товщина стінки сечового міхура", "стінка сечового міхура", "стінка сечового міхура потовщена", "bladder wall thickness"]},
    {"name": "Thyroid volume", "category": "thyroid", "unit": "mL", "aliases": ["сумарний об'єм", "сумарний об'єм щитоподібної залози", "об'єм щитоподібної залози", "загальний об'єм щитоподібної залози", "thyroid volume", "total thyroid volume"]},
    # The rest of what an abdominal, thyroid, duplex, echo or soft-tissue
    # protocol prints (sandbox audit 2026-11-06, verdicts B and C).  Expert
    # Hospital and Veselka print these in two templates; the parser files both
    # under one English name each, so a trend runs across clinics.  The side
    # of a paired organ or vessel, a thyroid lobe, or a lesion's site is the
    # observation's specimen, as above.
    {"name": "Liver left lobe size", "category": "liver", "unit": "mm", "aliases": ["liver left lobe size", "ліва частка печінки", "розмір лівої частки печінки"]},
    {"name": "Portal vein diameter", "category": "liver", "unit": "mm", "aliases": ["portal vein diameter", "ворітна вена", "діаметр ворітної вени"]},
    {"name": "Gallbladder length", "category": "liver", "unit": "mm", "aliases": ["gallbladder length", "довжина жовчного міхура"]},
    {"name": "Gallbladder width", "category": "liver", "unit": "mm", "aliases": ["gallbladder width", "ширина жовчного міхура"]},
    {"name": "Pancreatic head size", "category": "pancreas", "unit": "mm", "aliases": ["pancreatic head size", "головка підшлункової залози", "розмір головки підшлункової залози"]},
    {"name": "Pancreatic body size", "category": "pancreas", "unit": "mm", "aliases": ["pancreatic body size", "тіло підшлункової залози", "розмір тіла підшлункової залози"]},
    {"name": "Pancreatic tail size", "category": "pancreas", "unit": "mm", "aliases": ["pancreatic tail size", "хвіст підшлункової залози", "розмір хвоста підшлункової залози"]},
    {"name": "Splenic vein diameter", "category": "liver", "unit": "mm", "aliases": ["splenic vein diameter", "діаметр селезінкової вени"]},
    {"name": "Kidney length", "category": "renal", "unit": "mm", "aliases": ["kidney length", "довжина нирки"]},
    {"name": "Kidney width", "category": "renal", "unit": "mm", "aliases": ["kidney width", "ширина нирки"]},
    {"name": "Renal parenchymal thickness", "category": "renal", "unit": "mm", "aliases": ["renal parenchymal thickness", "товщина паренхіми", "товщина паренхіми нирки"]},
    {"name": "Largest renal salt crystal size", "category": "renal", "unit": "mm", "aliases": ["largest renal salt crystal size", "кристали солей"]},
    {"name": "Urinary bladder volume", "category": "renal", "unit": "mL", "aliases": ["urinary bladder volume", "об'єм сечового міхура"]},
    {"name": "Spleen length", "category": "liver", "unit": "mm", "aliases": ["spleen length", "довжина селезінки"]},
    {"name": "Spleen thickness", "category": "liver", "unit": "mm", "aliases": ["spleen thickness", "товщина селезінки"]},
    {"name": "Thyroid isthmus thickness", "category": "thyroid", "unit": "mm", "aliases": ["thyroid isthmus thickness", "перешийок", "товщина перешийка щитоподібної залози"]},
    {"name": "Thyroid lobe length", "category": "thyroid", "unit": "mm", "aliases": ["thyroid lobe length", "довжина частки щитоподібної залози"]},
    {"name": "Thyroid TI-RADS category", "category": "thyroid", "unit": None, "aliases": ["thyroid ti-rads category", "ti-rads", "tirads", "оцінка за шкалою ti-rads"]},
    {"name": "Right ventricular diameter", "category": "cardiovascular", "unit": "cm", "aliases": ["right ventricular diameter", "правий шлуночок"]},
    {"name": "Interventricular septal thickness, diastole", "category": "cardiovascular", "unit": "cm", "aliases": ["interventricular septal thickness, diastole", "ivsd", "міжшлуночкова перетинка, діастола", "товщина міжшлуночкової перетинки"]},
    {"name": "Left ventricular end-diastolic diameter", "category": "cardiovascular", "unit": "cm", "aliases": ["left ventricular end-diastolic diameter", "lvidd", "кдр", "лівий шлуночок, діастола", "кінцево-діастолічний розмір лівого шлуночка"]},
    {"name": "Left ventricular posterior wall thickness, diastole", "category": "cardiovascular", "unit": "cm", "aliases": ["left ventricular posterior wall thickness, diastole", "lvpwd", "стінка лш, діастола", "товщина задньої стінки лівого шлуночка"]},
    {"name": "Left ventricular ejection fraction", "category": "cardiovascular", "unit": "%", "aliases": ["left ventricular ejection fraction", "lvef", "фракція викиду", "фракція викиду лівого шлуночка"]},
    {"name": "Ascending aorta diameter", "category": "cardiovascular", "unit": "cm", "aliases": ["ascending aorta diameter", "діаметр висхідної аорти"]},
    {"name": "Aortic root diameter at the sinuses of Valsalva", "category": "cardiovascular", "unit": "cm", "aliases": ["aortic root diameter at the sinuses of valsalva", "діаметр аорти на рівні синусів вальсальви"]},
    {"name": "Left atrial diameter", "category": "cardiovascular", "unit": "cm", "aliases": ["left atrial diameter", "ліве передсердя", "діаметр лівого передсердя"]},
    {"name": "Tricuspid valve peak pressure gradient", "category": "cardiovascular", "unit": "mmHg", "aliases": ["tricuspid valve peak pressure gradient", "піковий градієнт тиску на тристулковому клапані"]},
    {"name": "Pulmonary artery acceleration time", "category": "cardiovascular", "unit": "ms", "aliases": ["pulmonary artery acceleration time", "paat", "час прискорення кровотоку в легеневій артерії"]},
    {"name": "Peak systolic velocity, internal carotid artery", "category": "cardiovascular", "unit": "cm/s", "aliases": ["peak systolic velocity, internal carotid artery", "psv ica", "внутрішня сонна артерія"]},
    {"name": "Peak systolic velocity, external carotid artery", "category": "cardiovascular", "unit": "cm/s", "aliases": ["peak systolic velocity, external carotid artery", "psv eca", "зовнішня сонна артерія"]},
    {"name": "Peak systolic velocity, vertebral artery", "category": "cardiovascular", "unit": "cm/s", "aliases": ["peak systolic velocity, vertebral artery", "хребцева артерія"]},
    {"name": "Vertebral artery diameter", "category": "cardiovascular", "unit": "mm", "aliases": ["vertebral artery diameter", "діаметр хребцевої артерії"]},
    {"name": "Soft tissue lesion largest diameter", "category": "body", "unit": "mm", "aliases": ["soft tissue lesion largest diameter", "найбільший діаметр утворення м'яких тканин"]},
    {"name": "Soft tissue lesion smaller diameter", "category": "body", "unit": "mm", "aliases": ["soft tissue lesion smaller diameter", "менший діаметр утворення м'яких тканин"]},
    # Measured by a clinician at a visit and printed in the note's objective
    # status («Температура: 36,6 ° C», «SpO2: 97 %», «Частота дихання: 18 /хв»).
    # Spot readings taken awake, so deliberately not the device metrics of
    # similar name: a wearable's SpO2 and breathing rate are overnight averages
    # with no published reference interval, and one series holding both would
    # judge a night's average against a spot-reading threshold.
    {"name": "Body temperature", "category": "vital_signs", "unit": "°C", "aliases": ["body temperature", "температура", "температура тіла"]},
    {"name": "Oxygen saturation (SpO2)", "category": "vital_signs", "unit": "%", "aliases": ["oxygen saturation (spo2)", "oxygen saturation", "spo2", "сатурація", "сатурація кисню"]},
    {"name": "Resting respiratory rate", "category": "vital_signs", "unit": "breaths/min", "aliases": ["resting respiratory rate", "частота дихання", "чд"]},
    # Weight, height and BMI measured at a visit *are* the measurement a scale
    # or a health app records, so these share the device metrics' display
    # names, and ``panels.MEASUREMENT_TWINS`` joins them: the concept page shows
    # the clinic readings and the device's daily values as one series, each
    # labelled with its source.
    {"name": "Body weight", "category": "body", "unit": "kg", "aliases": ["body weight", "вага", "вага тіла", "маса тіла"]},
    {"name": "Body height", "category": "body", "unit": "cm", "aliases": ["body height", "зріст", "зріст тіла"]},
    {"name": "Body mass index", "category": "body", "unit": "kg/m²", "aliases": ["body mass index", "bmi", "імт", "індекс маси тіла", "індекс маси тіла (імт)"]},
    # A 12-lead ECG report's interval table.  Bare "pr" is deliberately not an
    # alias: ``concept_for_alias`` falls back to a bracketed code, and «(PR)»
    # is too short a code to claim from every laboratory label that prints it.
    # The two QTc formulas are kept apart because they give different numbers
    # for one tracing (Bazett over-corrects at fast rates), and one series
    # holding both would trend a change of formula as a change of heart.
    {"name": "PR interval", "category": "cardiovascular", "unit": "ms", "aliases": ["pr interval", "pq interval", "pq", "інтервал pq", "інтервал pr"]},
    {"name": "QRS duration", "category": "cardiovascular", "unit": "ms", "aliases": ["qrs duration", "qrs", "тривалість qrs", "комплекс qrs"]},
    {"name": "QT interval", "category": "cardiovascular", "unit": "ms", "aliases": ["qt interval", "qt", "інтервал qt"]},
    {"name": "QTc (Bazett)", "category": "cardiovascular", "unit": "ms", "aliases": ["qtc (bazett)", "qtc bazett", "qtc за базеттом"]},
    {"name": "QTc (Framingham)", "category": "cardiovascular", "unit": "ms", "aliases": ["qtc (framingham)", "qtc (sagie/framingham)", "qtc framingham", "qtc за фремінгемом"]},
]


#: Renamed concepts keep the id their old name slugged to, so a bookmarked
#: /metrics/<id>, the reference library entry and every stored observation go
#: on resolving without a migration.
CONCEPT_ID_OVERRIDES = {
    "Hepatitis B core antibodies, total (anti-HBc)": "hepatitis-b-core-antigen-marker",
    "Urine leukocytes (dipstick)": "urine-leukocyte-esterase",
}


def stable_concept_id(name: str) -> str:
    if name in CONCEPT_ID_OVERRIDES:
        return CONCEPT_ID_OVERRIDES[name]
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return slug or str(uuid.uuid5(uuid.NAMESPACE_URL, name))


#: Latin letters drawn identically to a Cyrillic one.  Ukrainian reports mix
#: the two scripts inside one word -- «(МСН)» for MCH, «гепатиту B» beside
#: «гепатиту В», «C-реактивний» with a Latin C, «А(ІІ)» against «А (II)» --
#: and every pair is equal on paper and unequal to a string comparison.  Both
#: sides of a label lookup are folded onto Cyrillic, so one alias covers every
#: spelling a laboratory's font happens to produce.  The fold runs after case
#: folding, so it maps the lower-case form of every letter whose capital is a
#: homoglyph (B/В, H/Н, K/К, M/М, T/Т) -- an alias is written in lower case
#: and the report prints capitals.  Applied to both sides, an all-Latin alias
#: still matches its all-Latin label.
_HOMOGLYPHS = str.maketrans("abcehikmoptxy", "авсенікмортху")


def label_key(label: str) -> str:
    """The comparison key for a printed label: ``normalized_key`` with the
    Latin/Cyrillic homoglyphs folded."""
    return normalized_key(label).translate(_HOMOGLYPHS)


#: The mantissa a wrapped colony count left on its label («… aureus 1.0 x»).
#: The first space is written out, and a match may only start where a run of
#: spaces does: a substitution then enters each run once, not at every space.
#: The rest of the run is taken whole, since a digit, never a space, follows it.
_WRAPPED_MULTIPLIER = re.compile(r"(?<!\s)\s\s*+\d+(?:[.,]\d+)?\s*[xх×]\s*$", re.IGNORECASE)

#: Lines a parser can mistake for a result label: a specimen header repeated
#: above every row of an EskuLab urinalysis («Приносний матеріал, сеча»).  They
#: name no analyte, so they are never learned as an alias of one.
NON_ANALYTE_LABELS = frozenset({normalized_key("Приносний матеріал, сеча"), normalized_key("Приносний матеріал")})


#: ALEX² rows whose full printed name the parser now joins across the wrap
#: (common name, WHO/IUIS code, protein family).  Earlier parses kept only one
#: fragment of each, and that fragment is the allergen concept every stored
#: result already belongs to; the full name resolves to it rather than
#: minting a second concept with a one-point history.
LABEL_PREDECESSORS = {
    normalized_key(full): fragment
    for full, fragment in (
        ("Акація срібляста (Рід тропічних дерев) Aca m", "Aca m"),
        ("Ялівець мексиканський (гірський кедр – народна назва) Jun a", "Jun a"),
        ("Подорожник ланцетолистий Pla l", "Подорожник ланцетолистий"),
        ("Der p 23 Peritrophin-like protein domain", "Der p 23"),
        ("Mala s 11 Mn Superoxid-Dismutase", "Mala s 11"),
        ("Asp f 6 Mn Superoxid-Dismutase", "Asp f 6"),
        ("Cla h 8 Short Chain Dehydrogenase", "Cla h 8"),
        ("Пшениця Tri a aA_TI Alpha-Amylase Trypsin-Inhibitor", "Tri a aA_TI"),
        ("Anisakis simplex Ani s 1 Kunitz Serin Protease Inhibitor", "Ani s 1"),
        ("Pen m 4 Sarcoplasmic Calcium Binding Protein", "Pen m 4"),
        ("Bla g 5 Glutathione S-transferase", "Bla g 5"),
        ("Hev b 3 Small rubber particle protein", "Hev b 3"),
    )
}


def clean_label(label: str) -> str:
    """The label a concept is resolved by.

    Drops what a wrapped value left on the end: a culture prints
    «Staphylococcus aureus 1.0 x 10^2 КУО/г»; when the line breaks inside the
    number the label arrives as «Staphylococcus aureus 1.0 x» and became a
    second organism beside the real one.  And maps a newly joined allergen name
    to the fragment its concept was created under (``LABEL_PREDECESSORS``).
    """
    label = _WRAPPED_MULTIPLIER.sub("", label).strip()
    return LABEL_PREDECESSORS.get(normalized_key(label), label)


def _build_index() -> dict[str, list[dict[str, object]]]:
    index: dict[str, list[dict[str, object]]] = {}
    for definition in CONCEPT_DEFINITIONS:
        for alias in definition["aliases"]:
            bucket = index.setdefault(label_key(str(alias)), [])
            if definition not in bucket:
                bucket.append(definition)
    return index


_ALIAS_INDEX = _build_index()
_BY_NAME = {str(definition["name"]): definition for definition in CONCEPT_DEFINITIONS}

#: «в п/з», «у полі зору», "HPF" -- and «поодинокі в препараті», the
#: microscopist's word for a few cells on the slide: Synevo's manual sediment
#: erythrocyte row prints no field at all («не виявлені, поодинокі в
#: препараті»), only the slide, and without it the row joined the analyser's
#: per-microlitre series.
_PER_FIELD = re.compile(r"п\s*/\s*з|п\.\s*з|полі\s+зору|hpf|в\s+препараті", re.IGNORECASE)
_STRIP_UNIT = re.compile(r"^\s*(leu|ery)\s*/", re.IGNORECASE)
_RISK_TIERS = re.compile(r"ризик|risk", re.IGNORECASE)
_PER_MICROLITRE = re.compile(r"мкл|[µμu]l\b", re.IGNORECASE)

#: The material a row was measured in, by the words that name it, mapped to
#: the category of the concepts measured in it.  Word starts, so «калій»
#: (potassium) is not stool and «кров'яний» still is blood.
_SPECIMEN_FAMILIES = (
    ("stool", re.compile(r"\bкал(?:у|ом|і|ов\w*)?\b|копрограм|фекал|\bstool|\bfa?eces", re.IGNORECASE)),
    ("urinalysis", re.compile(r"\bсеч|\burine", re.IGNORECASE)),
    ("smear", re.compile(r"мазк|мазок|цитолог|пап[\s-]*тест|зішкріб|урогеніт|піхв|цервік|уретр|\bvagin|\bcervi|\bsmear", re.IGNORECASE)),
    ("hematology", re.compile(r"\bкров|сироват|плазм|\bblood|\bserum|\bplasma", re.IGNORECASE)),
)
#: Concepts that exist for one specimen only.  A bare «Слиз», «pH» or
#: «Лейкоцити» is seeded once for urine; printed in a stool or a smear it
#: is not that measurement, whatever the alias says.
_SPECIMEN_BOUND = frozenset({"urinalysis", "stool"})
#: A count per litre is a blood count: «Лейкоцити (WBC) 6.84 10^9 клітин/л»
#: printed in a urinalysis order is the white cell count, not urine.  Urine
#: counts are per microlitre or per field.  «Г/л» is giga-per-litre.
_BLOOD_COUNT_UNIT = re.compile(r"10\s*(?:\^|\*\*?)?\s*(?:9|12|⁹|¹²)(?!\d)|^\s*Г/[лЛ]\s*$")


def specimen_family(*texts: str | None) -> str | None:
    """The specimen the first text that names exactly one names: "stool",
    "urinalysis", "smear", "hematology" (blood), or ``None``."""
    for text in texts:
        if not text:
            continue
        found = {family for family, pattern in _SPECIMEN_FAMILIES if pattern.search(text)}
        if len(found) == 1:
            return found.pop()
    return None


def blood_count_unit(unit: str | None) -> bool:
    return bool(unit and _BLOOD_COUNT_UNIT.search(unit))

#: (definition the label resolved to, test on the row, definition it belongs to).
#: For labels that do not name their method: the unit, the report or the
#: printed reference does, and each of these is the one place it is decided.
_REFINEMENTS = (
    ("Urine leukocytes", lambda row: _STRIP_UNIT.search(row["unit"]), "Urine leukocytes (dipstick)"),
    ("Urine erythrocytes", lambda row: _STRIP_UNIT.search(row["unit"]), "Urine erythrocytes (dipstick)"),
    # St. Paraskeva prints the field in the value («1-2 в п/з») rather than
    # the unit column, so all three are read.
    ("Urine leukocytes", lambda row: _PER_FIELD.search(" ".join((row["unit"], row["value_text"], row["reference"]))), "Urine leukocytes per high-power field"),
    ("Urine erythrocytes", lambda row: _PER_FIELD.search(" ".join((row["unit"], row["value_text"], row["reference"]))), "Urine erythrocytes per high-power field"),
    ("Urine erythrocytes, unchanged", lambda row: _PER_MICROLITRE.search(row["unit"]), "Urine erythrocytes, unchanged (per microlitre)"),
    ("Pulse rate", lambda row: row["clinical_type"] == "electrocardiogram", "ECG heart rate"),
    ("C-reactive protein", lambda row: _RISK_TIERS.search(row["reference"]), "High-sensitivity C-reactive protein"),
)


def refine_definition(
    definition: dict[str, object] | None,
    *,
    unit: str | None = None,
    value_text: str | None = None,
    reference: str | None = None,
    clinical_type: str | None = None,
) -> dict[str, object] | None:
    """The definition a row belongs to once its unit, report and printed
    reference are known, for labels that are the same word across methods."""
    if definition is None:
        return None
    row = {
        "unit": str(unit or ""),
        "value_text": str(value_text or ""),
        "reference": str(reference or ""),
        "clinical_type": clinical_type,
    }
    for source, test, target in _REFINEMENTS:
        if definition["name"] == source and test(row):
            return _BY_NAME[target]
    return definition


def foreign_categories(alias: str, specimen: str | None) -> frozenset[str]:
    """The specimen-bound categories a label may not resolve into, measured
    in ``specimen``: none when the label names its own specimen
    («Колір калових мас», «Лейкоцити в сечі») or no specimen is known."""
    if not specimen or specimen_family(alias):
        return frozenset()
    return _SPECIMEN_BOUND - {specimen}


def concept_for_alias(
    alias: str, value_type: str | None = None, category: str | None = None, specimen: str | None = None
) -> dict[str, object] | None:
    """Resolve a printed label to a definition.

    ``category`` is the specimen context the caller inferred from the report --
    a bare «глюкоза», «лейкоцити» or «еритроцити» is deliberately seeded for
    both a blood and a urine concept, and without the context the definition
    order decides: numeric always won blood, so a urinalysis printing a bare
    numeric dipstick row would file its count under the blood concept.

    ``specimen`` is a ``specimen_family`` the row itself establishes (its
    printed material, its section, a blood-count unit).  It is binding, not a
    preference: a coprogram's «pH» and «Слиз» are not urine whatever the
    alias table says, so urine concepts are not candidates there.  In stool the
    EskuLab «… (кал)» spelling of the label is tried first, which is how
    Synevo's bare «Форма» or «Слиз» reaches the stool concept.
    """
    excluded = foreign_categories(alias, specimen)
    preferred = specimen if specimen in _SPECIMEN_BOUND else category

    def choose(matches: list[dict[str, object]]) -> dict[str, object] | None:
        matches = [
            definition
            for definition in matches
            if (value_type is None or str(definition.get("value_type", "numeric")) in {value_type, "mixed"})
            and definition["category"] not in excluded
        ]
        if not matches:
            return None
        return next((item for item in matches if item["category"] == preferred), matches[0])

    if specimen == "stool" and not label_key(alias).endswith(" кал"):
        found = choose(_ALIAS_INDEX.get(label_key(f"{alias} (кал)"), []))
        if found:
            return found
    found = choose(_ALIAS_INDEX.get(label_key(alias), []))
    if found:
        return found
    # Codes in parentheses are the most stable cross-export marker for CBC rows.
    # Cyrillic ones count: a Ukrainian laboratory writes «Аланінамінотрансфераза
    # (АЛТ)» where another writes "ALT (ALT)", and requiring a Latin initial
    # made every one of them invisible here -- ALT, AST, GGT, MCHC, PT and TT
    # all landed on nameless concepts off a single twelve-page order while the
    # Latin-coded rows beside them resolved.  The homoglyph trap is the same one
    # «(МСН)»/«(МСНС)» already carry: identical on paper, unequal to every
    # string comparison, so both scripts have to be tried.
    code_match = re.findall(r"\(([A-Za-zА-ЯЁІЇЄҐа-яёіїєґ][\w%#.-]{1,10})\)", alias)
    if code_match:
        return choose(_ALIAS_INDEX.get(label_key(code_match[-1]), []))
    return None
