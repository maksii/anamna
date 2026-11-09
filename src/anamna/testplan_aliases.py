"""Curated matching between the labs' price lists and our concepts.

The test planner (:mod:`.testplan`) turns every analyte a lab item reports
into a requirement key.  The name resolver gets most of them; this module
holds what it cannot be trusted with, keyed by ``(lab, parameter id)`` -- the
id the lab's own catalogue gives the analyte (Esculab: the ``idtest`` of its
result rows; Synevo: the service code, or ``name:<key>`` for a panel member
that is not sold on its own).  Each entry keeps the printed name it was
decided from, so a renamed or re-numbered analyte is visible in review.

``CONCEPTS``  the analyte is this concept of ours, though its name does not
              resolve (or resolves through a misleading synonym or code).
``UNMAPPED``  the name resolves, wrongly; the analyte keeps the lab's own key.
``SAME``      the same analyte at both labs, with no concept of ours: one
              shared ``x:<slug>`` key, so either lab's item covers it.
``WHOLE``     one catalogue row that is a whole examination reported as
              several results: the keys it covers.
``NOT_ANALYTES``  headings and note fields that measure nothing.

Every pairing is decided from the names, codes, units and the lab's own
reports in the record.  Anything that differs in method, specimen, fraction
(total/free), form (ratio/absolute), class (IgG/IgM) or sampling (venous/
capillary) stays apart: a wrong merge tells a person that a test covers
what it does not.
"""

from __future__ import annotations

import re

# --- explicit concepts ------------------------------------------------------------

#: ``(lab, parameter id) -> (concept id, printed name)``.
CONCEPTS: dict[tuple[str, str], tuple[str, str]] = {
    # Named without the «CA» spelling the record uses, or as a stool antigen
    # with no word the concept's aliases share.
    ("esculab", "67"): ("cancer-antigen-15-3-ca-15-3", "Онкомаркер молочної залози (СА-15-3)"),
    ("synevo", "4028"): ("h-pylori-stool-antigen", "Helicobacter pylori, антиген у калі (якісне визначення)"),
    # hs-CRP: the bracketed English «C-Reactive Protein» alone would read as plain CRP.
    ("synevo", "10019"): ("high-sensitivity-c-reactive-protein",
                          "C-реактивний білок, високочутливий (C-Reactive Protein, High Sensitivity)"),
    # Synevo's FibroTest/FibroMax panels name their members «X (неінвазивна
    # діагностика)»: the same serum measurement as the single test, entered
    # into the fibrosis score.  ALT/AST «/PYP» (pyridoxal-phosphate activated)
    # are a method variant and stay apart.
    ("synevo", "name:γ-глytamattpahcфepaзa(heihbaзиbhaдiaгhoctиka)"): (
        "gamma-glutamyl-transferase", "γ-глутаматтрансфераза (неінвазивна діагностика)"),
    ("synevo", "name:бiлipyбihзaгaльhий(heihbaзиbhaдiaгhoctиka)"): (
        "total-bilirubin", "Білірубін загальний (неінвазивна діагностика)"),
    ("synevo", "name:aпoлiпoпpoteїha-1(heihbaзиbhaдiaгhoctиka)"): (
        "apolipoprotein-a1", "Аполіпопротеїн А-1 (неінвазивна діагностика)"),
    ("synevo", "name:глюkoзa(heihbaзиbhaдiaгhoctиka)"): ("blood-glucose", "Глюкоза (неінвазивна діагностика)"),
    ("synevo", "name:tpиглiцepиди(heihbaзиbhaдiaгhoctиka)"): (
        "triglycerides", "Тригліцериди (неінвазивна діагностика)"),
    ("synevo", "name:xoлectepиh(heihbaзиbhaдiaгhoctиka)"): (
        "total-cholesterol", "Холестерин (неінвазивна діагностика)"),
    # «Вірус епідемічного паротиту, антитіла IgG / Mumps Virus»: the mumps
    # serology the record holds from Synevo, under Esculab's longer name.
    ("esculab", "1719"): ("mumps-virus-igg", "Вірус епідемічного паротиту, антитіла IgG / Mumps Virus"),
    ("esculab", "1720"): ("mumps-virus-igm", "Вірус епідемічного паротиту, антитіла IgМ / Mumps Virus"),
    # The automated urinalysis's turbidity level is the urine's clarity.
    ("esculab", "1114"): ("urine-appearance", "Каламутність(рівень) (C-CLOUD)"),
    # Esculab's manual urinalysis, sold only inside packages whose names do
    # not say urine: «реакція» is the urine pH, fresh erythrocytes are the
    # unchanged ones (per field, as the concept), «циліндри» all casts.  In a
    # 24-hour collection the same ids become 24-hour keys (testplan.keyed).
    ("esculab", "308"): ("urine-ph", "реакція"),
    ("esculab", "935"): ("urine-erythrocytes-unchanged", "еритроцити свіжі"),
    ("esculab", "318"): ("total-casts-in-urine", "циліндри"),
    # The total IgE an Esculab allergen panel reports beside its extracts.
    ("esculab", "429"): ("total-immunoglobulin-e", "Загальний імуноглобулін Е в сироватці крові"),
}

#: ``(lab, parameter id) -> (printed name, why it is not the concept its name resolves to)``.
UNMAPPED: dict[tuple[str, str], tuple[str, str]] = {
    # Anti-MCV antibodies: the bracketed «(MCV)» is the code of mean corpuscular volume.
    ("synevo", "9326"): ("Цитрульований віментин (MCV), антитіла IgG", "anti-MCV is not mean corpuscular volume"),
    # Rheumatoid factor by isotype (EIA) is not the total RF the record holds.
    ("synevo", "2120"): ("Fc-фрагмент IgG автоантитіла IgA (ревматоїдний фактор)", "IgA isotype, not total RF"),
    ("synevo", "2121"): ("Fc-фрагмент IgG автоантитіла IgG (ревматоїдний фактор)", "IgG isotype, not total RF"),
    ("synevo", "2122"): ("Fc-фрагмент IgG автоантитіла IgM (ревматоїдний фактор)", "IgM isotype, not total RF"),
    # The sediment leukocytes of Esculab's manual urinalysis, sold only inside
    # packages, so no item names the urine: a bare «лейкоцити» read as the
    # blood count.  Its unit (per field or per µl) is not printed, so it is
    # not filed under either urine concept either.
    ("esculab", "312"): ("лейкоцити", "urine sediment, not the blood white cell count"),
    # Albumin as a serum electrophoresis fraction, not the chemistry albumin
    # concentration (g/L) its bare name resolves to.
    ("esculab", "2885"): ("альбумін", "an electrophoresis fraction, not serum albumin in g/L"),
}

# --- one analyte at both labs, no concept of ours -----------------------------------

#: ``x:<slug> -> ((lab, parameter id, printed name), ...)``.
SAME: dict[str, tuple[tuple[str, str, str], ...]] = {
    # hormones
    "x:luteinizing-hormone": (
        ('synevo', '1009', 'Лютеїнізуючий гормон (ЛГ)'),
        ('esculab', '18', 'Лютеїнізуючий гормон (ЛГ)'),
    ),
    "x:follicle-stimulating-hormone": (
        ('synevo', '1014', 'Фолікулостимулюючий гормон (ФСГ)'),
        ('esculab', '23', 'Фолікулостимулюючий гормон (ФСГ)'),
    ),
    "x:prolactin": (('synevo', '1011', 'Пролактин'), ('esculab', '20', 'Пролактин (ПРЛ)'),),
    "x:macroprolactin": (
        ('synevo', '9010', 'Макропролактин'),
        ('esculab', '2933', 'Макропролактин (big + big-big)'),
    ),
    "x:estradiol": (('synevo', '1015', 'Естрадіол (E2)'), ('esculab', '17', 'Естрадіол (E2)'),),
    "x:progesterone": (('synevo', '1010', 'Прогестерон'), ('esculab', '19', 'Прогестерон'),),
    "x:dhea-sulfate": (
        ('synevo', '1017', 'Дегідроепіандростерон-сульфат (ДГЕА-с, DHEA-s)'),
        ('esculab', '26', 'Дегідроепіандростерон-сульфат (ДГЕА)'),
    ),
    "x:androstenedione": (('synevo', '9001', 'Андростендіон'), ('esculab', '24', 'Андростендіон'),),
    "x:sex-hormone-binding-globulin": (
        ('synevo', '1012', "Глобулін, що зв'язує статеві гормони (ГЗСГ, SHBG)"),
        ('esculab', '16', "Глобулін - який зв'язує статеві гормони, SHBG"),
    ),
    "x:free-testosterone": (
        ('synevo', '2002', 'Тестостерон вільний (Т вільний, сироватка)'),
        ('esculab', '21', 'Тестостерон вільний'),
    ),
    "x:free-androgen-index": (
        ('synevo', 'name:ihдekcbiльhoгoahдpoгehy(tectoctepohзaгaльhий/shbg)', 'Індекс вільного андрогену (тестостерон загальний/SHBG)'),
        ('esculab', '25', 'Індекс вільного андрогену (тестостерон загальний/SHBG) FTI%'),
    ),
    "x:dihydrotestosterone": (('synevo', '2093', 'Дигідротестостерон'), ('esculab', '464', 'Дигідротестостерон'),),
    "x:androstanediol-glucuronide": (
        ('synevo', '2513', 'Андростендіол глюкуронід (3-α-Діол)'),
        ('esculab', '1920', 'Андростендіолу глюкуронід (3-α-діол)'),
    ),
    "x:17-hydroxyprogesterone": (
        ('synevo', '2069', '17-α-оксипрогестерон (17-OHP)'),
        ('esculab', '29', '17α-гідроксипрогестерон (17α-OHP)'),
    ),
    "x:cortisol-serum": (('synevo', '1020', 'Кортизол (сироватка)'), ('esculab', '27', 'Кортизол'),),
    "x:cortisol-saliva": (('synevo', '2214', 'Кортизол (слина)'), ('esculab', '1549', 'Кортизол (слина)'),),
    "x:acth": (
        ('synevo', '9006', 'Адренокортикотропний гормон (АКТГ, ACTH)'),
        ('esculab', '30', 'Адренокортикотропний гормон (АКТГ)'),
    ),
    "x:growth-hormone": (
        ('synevo', '2005', 'Соматотропний гормон (гормон росту, СТГ)'),
        ('esculab', '435', 'Соматотропний гормон (гормон росту, СТГ, HGH)'),
    ),
    "x:igf-1": (
        ('synevo', '9016', 'Інсуліноподібний фактор росту - 1 (ІФР - 1, ІGF-1)'),
        ('esculab', '1684', 'Інсуліноподібний фактор росту-1 (Соматомедин С, ІФР-1, IGF-1)'),
    ),
    "x:homa-ir": (
        ('synevo', 'name:poзpaxyhokihдekcyhoma', 'Розрахунок індексу HOMA'),
        ('esculab', '36', 'Індекс HOMA'),
    ),
    "x:inhibin-a": (('synevo', '2288', 'Інгібін A'), ('esculab', '3167', 'Інгібін А'),),
    "x:inhibin-b": (('synevo', '2289', 'Інгібін B'), ('esculab', '457', 'Інгібін В'),),
    "x:aldosterone": (('synevo', '9004', 'Альдостерон'), ('esculab', '687', 'Альдостерон'),),
    "x:renin-concentration": (('synevo', '9007', 'Ренін прямий'), ('esculab', '688', 'Ренін активний'),),
    "x:aldosterone-renin-ratio": (
        ('synevo', 'name:poзpaxyhokaльдoctepoh-pehihoboгocпibbiдhoшehhя', 'Розрахунок альдостерон-ренінового співвідношення'),
        ('esculab', '689', 'Розрахунок альдостерон-ренінового співвідношення'),
    ),
    "x:calcitonin": (('synevo', '2068', 'Кальцитонін'), ('esculab', '8', 'Кальцитонін'),),
    "x:thyroglobulin": (('synevo', '1003', 'Тиреоглобулін (ТГ)'), ('esculab', '7', 'Тиреоглобулін (ТГ)'),),
    "x:reverse-t3": (
        ('synevo', '2512', 'Трийодтиронін реверсивний (rТ3)'),
        ('esculab', '1815', 'Трийодтиронін реверсивний (зворотний) (rT3)'),
    ),
    "x:placental-lactogen": (
        ('synevo', '2082', 'Плацентарний лактоген'),
        ('esculab', '61', 'Плацентарний лактоген'),
    ),
    "x:melatonin-saliva": (('synevo', '2519', 'Мелатонін (слина)'), ('esculab', '1657', 'Мелатонін (слина)'),),
    "x:adiponectin": (('synevo', '9013', 'Адипонектин'), ('esculab', '2157', 'Адипонектин'),),
    "x:leptin": (('synevo', '9014', 'Лептин'), ('esculab', '824', 'Лептин'),),
    "x:glucagon": (('synevo', '9787', 'Глюкагон'), ('esculab', '2640', 'Глюкагон'),),
    "x:gastrin-17": (('synevo', '2292', 'Гастрин-17'), ('esculab', '2329', 'Гастрин -17'),),
    "x:erythropoietin": (('synevo', '9210', 'Еритропоетин'), ('esculab', '913', 'Еритропоетин'),),
    # pregnancy screening
    "x:hcg-total": (
        ('synevo', '1033', 'β-ХГЛ загальний (хоріонічний гонадотропін загальний)'),
        ('synevo', '1018', 'β-ХГЛ загальний (хоріонічний гонадотропін загал.) - пренатальний'),
        ('esculab', '57', 'Хоріонічний гонадотропін (бета-ХГЛ)'),
        ('esculab', '463', 'Хоріонічний гонадотропін (бета-ХГЛ)'),
        ('esculab', '58', 'Хоріонічний гонадотропін (пренатальна діагностика 12-21тв)'),
    ),
    "x:hcg-free-beta": (
        ('synevo', '1853', 'β-ХГЛ вільний'),
        ('synevo', '1149', 'β-ХГЛ вільний (пренатальна діагностика)'),
        ('synevo', 'name:β-xглbiльhий(roche)', 'β-ХГЛ вільний (Roche)'),
        ('esculab', '47', 'Вільний Бета-ХГЛ (8-13 тиждень вагітності)'),
        ('esculab', '1327', 'Вільна β-субодиниця хоріонічного гонадотропіну (Roche Diagnostics)'),
    ),
    "x:papp-a": (
        ('synevo', '1105', 'PAPP-A (Протеїн-А плазми, асоційований з вагітністю)'),
        ('synevo', 'name:papp-a(roche)', 'PAPP-A (Roche)'),
        ('esculab', '1326', 'ПАПП (РАРР) (Roche Diagnostics)'),
    ),
    "x:plgf": (
        ('synevo', '2399', 'PLGF (Плацентарний Фактор Росту. Маркер прееклампсії)_ Roche'),
        ('esculab', '1373', 'Плацентарний фактор росту (PLGF) Roche Diagnostics'),
    ),
    "x:sflt-1": (
        ('synevo', 'name:sflt-1(poзчиhhafms-пoдiбhatиpoзиhkihaзa-1)_roche', 'sFLT-1 (розчинна fms-подібна тирозинкіназа-1) _Roche'),
        ('esculab', '1344', 'Розчинна fms-подібна тирозинкіназа-1 (sFlt-1)'),
    ),
    "x:sflt-1-plgf-ratio": (
        ('synevo', 'name:cпibbiдhoшehhяsflt-1/plgf_roche', 'Співвідношення sFLT-1/PLGF_Roche'),
        ('esculab', '1360', 'Співвідношення sFlt-1/PLGF у ІІ та ІІІ триместрах вагітності'),
    ),
    # tumour markers
    "x:psa-total": (
        ('synevo', '1030', 'Простат-специфічний антиген загальний (ПСА)'),
        ('esculab', '71', 'Простат-специфічний антиген загальний (PSA)'),
        ('esculab', '1906', 'Загальний простат-специфічний антиген (PSA)'),
    ),
    "x:psa-free": (
        ('synevo', 'name:пpoctat-cпeцифiчhийahtигehbiльhий(пcabiл.)', 'Простат-специфічний антиген вільний (ПСА віл.)'),
        ('esculab', '70', 'Простат-специфічний антиген вільний (PSA)'),
        ('esculab', '1907', 'Вільний простат-специфічний антиген (fPSA)'),
    ),
    "x:psa-free-to-total-ratio": (
        ('synevo', 'name:cпibbiдhoшehhяпcabiльhoгoдoпcaзaгaльhoгo', 'Співвідношення ПСА вільного до ПСА загального'),
        ('esculab', '366', 'Співвідношення вільного РSA/загального РSA'),
        ('esculab', '1914', 'Співвідношення вільного PSA/загального PSA'),
    ),
    "x:alpha-fetoprotein": (
        ('synevo', '1023', 'α-фетопротеїн (АФП)'),
        ('synevo', '1016', 'α-фетопротеїн (АФП) - пренатальна діагностика'),
        ('synevo', 'name:α-фetoпpoteїh(afp)', 'α-Фетопротеїн (AFP)'),
        ('esculab', '402', 'Альфафетопротеїн (АФП)(о)'),
        ('esculab', '44', 'Альфафетопротеїн (АФП)'),
    ),
    "x:cea": (
        ('synevo', '1032', 'Раково-ембріональний антиген (РЕА, СЕА)'),
        ('esculab', '72', 'Раково-ембріональний антиген (СЕА)'),
    ),
    "x:ca-19-9": (
        ('synevo', '1026', 'Онкомаркер підшлункової залози, жовчного міхура (СА 19-9)'),
        ('esculab', '68', 'Онкомаркер підшлункової залози,жовчного міхура (СА-19-9)'),
    ),
    "x:ca-72-4": (
        ('synevo', '1028', 'Онкомаркер шлунка (СА 72-4)'),
        ('esculab', '468', 'Онкомаркер шлунку CA 72-4'),
    ),
    "x:cyfra-21-1": (
        ('synevo', '1029', 'Онкомаркер Cyfra СА 21-1 (фрагмент цитокератину 19)'),
        ('esculab', '431', 'Онкомаркер Cyfra 21-1 (фрагмент цитокератину 19)'),
    ),
    "x:scc-antigen": (
        ('synevo', '9040', 'Антиген плоскоклітинної карциноми (SCC)'),
        ('esculab', '74', 'Антиген плоскоклітинної карциноми (SCC)'),
    ),
    "x:nse": (
        ('synevo', '1024', 'Нейрон-специфічна енолаза (NSE)'),
        ('esculab', '2126', 'Онкомаркер NSE-нейронспецифічна енолаза'),
    ),
    "x:chromogranin-a": (('synevo', '9035', 'Хромогранін А'), ('esculab', '2258', 'Хромогранін А'),),
    "x:tumour-m2-pyruvate-kinase": (
        ('synevo', '9038', 'Тумор-M2-піруваткіназа'),
        ('esculab', '2263', 'Онкомаркер тумор-М2-піруваткіназа'),
    ),
    # chemistry
    "x:creatine-kinase": (
        ('synevo', '1056', 'Креатинкіназа (КК)'),
        ('esculab', '249', 'Креатинфосфокіназа'),
        ('esculab', '2514', 'КК (креатинкіназа)'),
    ),
    "x:lactate-dehydrogenase": (
        ('synevo', '1057', 'Лактатдегідрогеназа (ЛДГ, LDH)'),
        ('esculab', '77', 'Лактатдегідрогеназа (LDH)'),
        ('esculab', '2560', 'ЛДГ'),
    ),
    "x:phosphorus": (('synevo', '1066', 'Фосфор'), ('esculab', '13', 'Фосфор (сироватка)'),),
    "x:chloride": (('synevo', '1067', 'Хлор (сироватка)'), ('esculab', '1687', 'Хлор (Cl-)'),),
    "x:ammonia": (('synevo', '1616', 'Аміак'), ('esculab', '2441', 'Аміак (NH3)'),),
    "x:transferrin": (('synevo', '1084', 'Трансферин'), ('esculab', '258', 'Трансферин'),),
    "x:total-iron-binding-capacity": (
        ('synevo', '1118', "Загальна залізозв'язуюча здатність сироватки (TIBC)"),
        ('esculab', '1945', "Загальна залізозв'язуюча здатність сироватки (TIBC)"),
    ),
    "x:unsaturated-iron-binding-capacity": (
        ('synevo', '10534', "Ненасичена залізозв'язуюча здатність сироватки (латентна, UIBC)"),
        ('esculab', '1944', "Ненасичена залізозв'язуюча здатність сироватки (UIBC)"),
    ),
    "x:transferrin-saturation": (
        ('synevo', 'name:biдcotokhacичehhяtpahcфepиhy', 'Відсоток насичення трансферину'),
        ('esculab', '1993', 'Насичення трансферину залізом'),
    ),
    "x:haptoglobin": (
        ('synevo', '9202', 'Гаптоглобін'),
        ('synevo', 'name:гaпtoглoбih(heihbaзиbhaдiaгhoctиka)', 'Гаптоглобін (неінвазивна діагностика)'),
        ('esculab', '487', 'Гаптоглобін'),
    ),
    "x:alpha-2-macroglobulin": (
        ('synevo', 'name:α-2-makpoглoбyлih(heihbaзиbhaдiaгhoctиka)', 'α-2-макроглобулін (неінвазивна діагностика)'),
        ('esculab', '488', 'Альфа-2-макроглобулін'),
    ),
    "x:fructosamine": (('synevo', '1082', 'Фруктозамін'), ('esculab', '436', 'Фруктозамін'),),
    "x:cystatin-c": (('synevo', '9393', 'Цистатин С'), ('esculab', '780', 'Цистатин C'),),
    "x:bile-acids": (('synevo', '9041', 'Жовчні кислоти'), ('esculab', '1841', 'Жовчні кислоти, кров'),),
    "x:copper-serum": (('synevo', '9296', 'Мідь'), ('esculab', '2912', 'Мідь в сироватці'),),
    "x:zinc": (('synevo', '9297', 'Цинк'), ('esculab', '2335', 'Цинк 2 (Zn)'),),
    "x:d-dimer": (('synevo', '1127', 'D-димер'), ('esculab', '298', 'Д-димер'),),
    "x:procalcitonin": (('synevo', '9011', 'Прокальцитонін'), ('esculab', '555', 'Прокальцитонін'),),
    "x:interleukin-6": (('synevo', '9294', 'Інтерлейкін-6 (ІЛ-6, IL-6)'), ('esculab', '825', 'Інтерлейкін 6'),),
    "x:interleukin-1-beta": (
        ('synevo', '9293', 'Інтерлейкін-1 бета (ІЛ-1, IL-1 beta)'),
        ('esculab', '1939', 'Інтерлейкін 1-Бета'),
    ),
    "x:complement-c3c": (
        ('synevo', '1125', 'Комплемент (C3C компонент)'),
        ('esculab', '1324', 'Компонент комплементу С3с'),
    ),
    "x:complement-c4": (
        ('synevo', '1126', 'Комплемент (С4 компонент)'),
        ('esculab', '1325', 'Компонент комплементу С4'),
    ),
    "x:c1-esterase-inhibitor-activity": (
        ('synevo', '9762', 'Інгібітор С1-естерази (активність)'),
        ('esculab', '1829', 'Інгібітор С1-естерази, активність'),
    ),
    "x:c1-esterase-inhibitor-concentration": (
        ('synevo', '9763', 'Інгібітор С1-естерази (концентрація)'),
        ('esculab', '1915', 'Інгібітор С1-естерази, концентрація'),
    ),
    "x:anti-xa-activity": (
        ('synevo', '9791', 'Анти-Ха-факторна активність (плазма крові)'),
        ('esculab', '3127', 'Анти-Ха факторна активність'),
    ),
    "x:copeptin": (
        ('synevo', 'name:koпeпtиh(c-terminalproarginine-vasopressin,ct-proavp)', 'Копептин (C-terminal pro arginine-vasopressin, CT-proAVP)'),
        ('esculab', '2011', 'Копептин (CT-proAVP)'),
    ),
    "x:nt-probnp": (
        ('synevo', '1130', 'NT-proBNP'),
        ('esculab', '806', 'N-термінальний натрійуретичний про-пептид В-типу, мозковий (NT-proBNP)'),
    ),
    "x:tryptase": (('synevo', '9515', 'Триптаза'), ('esculab', '1406', 'Триптаза'),),
    "x:eosinophil-cationic-protein": (
        ('synevo', '1263', 'Еозинофільний катіонний білок (ЕКБ, ECP)'),
        ('esculab', '1323', 'Еозинофільний катіонний білок'),
    ),
    "x:pancreatic-amylase": (
        ('synevo', '1606', 'α-Амілаза панкреатична'),
        ('esculab', '934', 'Амілаза панкреатична'),
    ),
    "x:pancreatic-elastase-serum": (
        ('synevo', '9199', 'Панкреатична еластаза (сироватка)'),
        ('esculab', '2898', 'Еластаза підшлункової залози в сироватці'),
    ),
    "x:calprotectin-serum": (
        ('synevo', '2237', 'Кальпротектин (сироватка)'),
        ('esculab', '1840', 'Кальпротектин в сироватці'),
    ),
    "x:immunoglobulin-a": (
        ('synevo', '1038', 'Імуноглобулін A (IgA, сироватка)'),
        ('esculab', '329', 'Концентрація Ig А в сироватці крові'),
    ),
    "x:immunoglobulin-g": (
        ('synevo', '1040', 'Імуноглобулін G (IgG, сироватка)'),
        ('esculab', '327', 'Концентрація Ig G в сироватці крові'),
    ),
    "x:immunoglobulin-m": (
        ('synevo', '1039', 'Імуноглобулін M (IgМ, сироватка)'),
        ('esculab', '328', 'Концентрація Ig M в сироватці крові'),
    ),
    # bone
    "x:beta-crosslaps": (
        ('synevo', '1557', 'β-Cross Laps (кров)'),
        ('esculab', '2259', 'С-термінальний телопептид колагену І типу (β-Cross Laps, β-CTX)'),
    ),
    "x:p1np-total": (
        ('synevo', '9205', 'Маркер формування кісткового матриксу (Total P1NP)'),
        ('esculab', '2294', 'N-термінальний пропептид проколагену І типу (P1NP)'),
    ),
    # vitamins
    "x:calcitriol": (
        ('synevo', '9700', '1,25-дигідроксивітамін D, 1,25-(OH)2D'),
        ('esculab', '2526', '1,25-дигідроксивітамін D (D3)'),
    ),
    "x:active-vitamin-b12": (
        ('synevo', '9361', 'Вітамін B12 активний (голотранскобаламін)'),
        ('esculab', '2323', 'Холотранскобаламін, вітамін В12 активний'),
    ),
    "x:vitamin-b3": (
        ('synevo', '9480', 'Вітамін B3 (нікотинамід)'),
        ('esculab', '2101', 'Нікотинамід, вітамін РР, група В3'),
    ),
    "x:vitamin-a": (('synevo', '9301', 'Вітамін A'), ('esculab', '2135', 'Вітамін А (ретинол)'),),
    "x:vitamin-e": (('synevo', '9302', 'Вітамін E'), ('esculab', '2100', 'Вітамін Е, токоферол'),),
    "x:vitamin-c": (('synevo', '9303', 'Вітамін C'), ('esculab', '2134', 'Вітамін С'),),
    # drugs
    "x:valproic-acid": (('synevo', '1154', 'Вальпроєва кислота'), ('esculab', '865', 'Вальпроєва кислота'),),
    "x:carbamazepine": (('synevo', '1153', 'Карбамазепін'), ('esculab', '866', 'Карбамазепін'),),
    "x:topiramate": (('synevo', '9395', 'Топірамат'), ('esculab', '3144', 'Топірамат'),),
    "x:levetiracetam": (('synevo', '9481', 'Леветірацетам'), ('esculab', '2156', 'Леветірацетам (Кеппра)'),),
    # stool and urine
    "x:pancreatic-elastase-stool": (
        ('synevo', '2198', 'Панкреатична еластаза (кал)'),
        ('esculab', '1468', 'Панкреатична еластаза (кал)'),
    ),
    "x:calprotectin-stool": (('synevo', '2238', 'Кальпротектин (кал)'), ('esculab', '1264', 'Кальпротектин'),),
    "x:c-difficile-toxin-a-b-stool": (
        ('synevo', '4059', 'Clostridium difficile (токсин A/B), антиген у калі (якісне визначення)'),
        ('esculab', '1301', 'Clostridium difficile (токсин А/В), антиген у калі (якісне визначення).'),
    ),
    "x:pinworm-eggs-perianal-scraping": (
        ('synevo', '4009', 'Аналіз зішкрібу на яйця гостриків (ентеробіоз)'),
        ('esculab', '830', 'Аналіз зішкрібу на яйця гостриків (ентеробіоз)'),
    ),
    "x:urine-albumin": (('synevo', '10231', 'Special. Альбумін (сеча)'), ('esculab', '1948', 'Альбумін в сечі'),),
    "x:urine-creatinine": (
        ('synevo', '1175', 'Креатинін (сеча)'),
        ('synevo', 'name:special.kpeatиhih(ceчa)', 'Special. Креатинін (сеча)'),
        ('esculab', '1949', 'Креатинін в сечі'),
    ),
    "x:urine-albumin-creatinine-ratio": (
        ('synevo', 'name:special.aльбymih-kpeatиhihobecпibbiдhoшehhя(ceчa)', 'Special. Альбумін-Креатинінове співвідношення (сеча)'),
        ('esculab', '1950', 'Альбумін-креатинінове співвідношення в сечі'),
    ),
    "x:daily-diuresis": (
        ('synevo', 'name:tpahcпoptcoлeй:дoбobийдiypeз', 'Транспорт солей: Добовий діурез'),
        ('esculab', '2357', 'Добовий діурез'),
    ),
    "x:urine-iodine": (('synevo', '4037', 'Йод (сеча)'), ('esculab', '2612', 'Йод (сеча)'),),
    "x:nechiporenko-leukocytes": (('esculab', '323', 'кількість лейкоцитів'),),
    "x:nechiporenko-erythrocytes": (('esculab', '324', 'кількість еритроцитів'),),
    "x:nechiporenko-casts": (('esculab', '325', 'кількість циліндрів'),),
    # whole examinations sold under one name at both labs
    "x:spermogram": (('synevo', '4015', 'Спермограма'), ('esculab', '378', 'Cпермограма'),),
    "x:isac-112": (
        ('synevo', '2503', 'ISAC – тест (алергочіп на 112 молекулярних алергокомпонентів)'),
        ('esculab', '3071', 'Алергочіп ISAC (112 алергокомпонентів)'),
    ),
    "x:alex-3": (
        ('synevo', '9797', 'ALEX3-тест (молекулярний аналіз на 300 алергенів, антитіла IgE)'),
        ('esculab', '3008', 'Мультикомпонентний алерготест ALEX-3 (визначення рівня загального IgE і специфічних IgE до 300 алергенів)'),
    ),
    "x:hpv-l1-capsid-protein": (
        ('synevo', '4273', 'Капсидний тест (білок ВПЛ L1, HPV L1)'),
        ('esculab', '3120', 'L1 капсидний білок (білок ВПЛ Л1, HPV L1)'),
    ),
    "x:ugt1a1-gilbert-genotype": (
        ('synevo', '9337', 'Генетика. Синдром Жильбера (ген UGT1A1)'),
        ('esculab', '805', 'Синдром Жильбера. Аналіз повторів (ТА) гена UGT1A1'),
    ),
    # infection serology
    "x:cmv-igg": (
        ('synevo', '2019', 'Цитомегаловірус (CMV), антитіла IgG'),
        ('esculab', '121', 'Цитомегаловірус Ig G'),
    ),
    "x:cmv-igm": (
        ('synevo', '2020', 'Цитомегаловірус (CMV), антитіла IgМ'),
        ('esculab', '120', 'Цитомегаловірус Ig M'),
    ),
    "x:cmv-igg-avidity": (
        ('synevo', '2070', 'Цитомегаловірус (CMV), авідність антитіл IgG'),
        ('esculab', '122', 'ЦМВ (CMV) авідність антитіл IgG'),
        ('esculab', '123', 'ЦМВ (CMV) авідність антитіл IgG (індекс авідності)'),
    ),
    "x:toxoplasma-igg": (
        ('synevo', '2030', 'Toxoplasma gondii, антитіла IgG'),
        ('esculab', '110', 'Токсоплазма Ig G'),
    ),
    "x:toxoplasma-igm": (
        ('synevo', '2031', 'Toxoplasma gondii, антитіла IgM'),
        ('esculab', '109', 'Токсоплазма Ig M'),
    ),
    "x:toxoplasma-igg-avidity": (
        ('synevo', '2073', 'Toxoplasma gondii, авідність антитіл IgG'),
        ('esculab', '111', 'Токсоплазма (Toxoplasma) авідність антитіл IgG'),
        ('esculab', '112', 'Токсоплазма (Toxoplasma) авідність антитіл IgG (індекс авідності)'),
    ),
    "x:rubella-igg": (('synevo', '2032', 'Вірус краснухи, антитіла IgG'), ('esculab', '116', 'Краснуха Ig G'),),
    "x:rubella-igm": (('synevo', '2033', 'Вірус краснухи, антитіла IgМ'), ('esculab', '115', 'Краснуха Ig M'),),
    "x:rubella-igg-avidity": (
        ('synevo', '2140', 'Вірус краснухи, авідність антитіл IgG'),
        ('esculab', '117', 'Вірус краснухи (Rubella virus) авідність антитіл IgG'),
        ('esculab', '118', 'Вірус краснухи (Rubella virus) авідність антитіл IgG (індекс авідності)'),
    ),
    "x:measles-igg": (
        ('synevo', '2164', 'Вірус кору, антитіла IgG'),
        ('esculab', '552', 'Антитіла до вірусу кору IgG'),
    ),
    "x:measles-igm": (
        ('synevo', '2153', 'Вірус кору, антитіла IgM'),
        ('esculab', '553', 'Антитіла до вірусу кору IgМ'),
    ),
    "x:hsv-1-2-igg": (
        ('synevo', '2021', 'Вірус простого герпесу (HSV) 1/2 типів, антитіла IgG'),
        ('esculab', '79', 'Герпес 1/2 Ig G'),
    ),
    "x:hsv-1-2-igm": (
        ('synevo', '2022', 'Вірус простого герпесу (HSV) 1/2 типів, антитіла IgM'),
        ('esculab', '78', 'Герпес 1/2 Ig M'),
    ),
    "x:vzv-igg": (
        ('synevo', '2026', 'Вірус Varicella Zoster (3 тип герпесу, VZV), антитіла IgG'),
        ('esculab', '1749', 'Вірус Varicеlla Zoster (герпес 3 типу,VZV) , антитіла IgG до Varicеlla Zoster'),
    ),
    "x:vzv-igm": (
        ('synevo', '2027', 'Вірус Varicella Zoster (3 тип герпесу, VZV), антитіла IgM'),
        ('esculab', '440', 'Вірус Varicеlla Zoster (герпес 3 типу,VZV) , антитіла IgM до Varicеlla Zoster'),
    ),
    "x:hhv-6-igg": (
        ('synevo', '2025', 'Вірус герпесу 6 типу (HHV 6), антитіла IgG'),
        ('esculab', '1086', 'Вірус герпесу тип 6, антитіла IgG'),
    ),
    "x:ebv-vca-igg": (
        ('synevo', '2071', 'Вірус Епштейна-Барр (капсидний антиген, VCA), антитіла IgG'),
        ('esculab', '131', 'Епштейн Барр капсидний антиген Ig G'),
    ),
    "x:ebv-vca-igm": (
        ('synevo', '2028', 'Вірус Епштейна-Барр (капсидний антиген, VCA), антитіла IgM'),
        ('esculab', '441', 'Вірус Епштейн-Барр (капсидний антиген), антитіла IgМ'),
    ),
    "x:ebv-ebna-igg": (
        ('synevo', '2029', 'Вірус Епштейна-Барр (нуклеарний антиген, EBNA), антитіла IgG'),
        ('esculab', '132', 'Епштейн Барр ядерний антиген Ig G'),
    ),
    "x:parvovirus-b19-igg": (
        ('synevo', '9347', 'Parvovirus B19, антитіла IgG'),
        ('esculab', '2597', 'Parvovirus B19 IgG'),
    ),
    "x:parvovirus-b19-igm": (
        ('synevo', '9348', 'Parvovirus B19, антитіла IgM'),
        ('esculab', '2598', 'Parvovirus B19 IgM'),
    ),
    "x:hepatitis-a-igm": (
        ('synevo', '1034', 'Вірус гепатиту A (HAV), антитіла IgM'),
        ('esculab', '2246', 'Вірус гепатиту А, антитіла IgM'),
    ),
    "x:hepatitis-c-igm": (
        ('synevo', '2012', 'Вірус гепатиту C (HCV), антитіла IgM'),
        ('esculab', '104', 'HCV антитіла IgM'),
    ),
    "x:hbeag": (
        ('synevo', '2007', 'Вірус гепатиту B (HBV), HBeAg'),
        ('esculab', '108', 'Вірус гепатиту В (HBV), HBeAg (кількісне визначення)'),
    ),
    "x:anti-hbe": (
        ('synevo', '2008', 'Вірус гепатиту B (HBV), HBeAg, антитіла сумарні'),
        ('esculab', '92', 'Вірус гепатиту В (HBV),antiHBeAg (кількісне визначення)'),
    ),
    "x:anti-hbs": (
        ('synevo', '1036', 'Вірус гепатиту B (HBV), HBsAg, антитіла сумарні'),
        ('esculab', '1408', 'Anti - HBsAg (кількісне визначення)'),
    ),
    "x:anti-hbc-igm": (
        ('synevo', '2009', 'Вірус гепатиту B (HBV), HBcorAg, антитіла IgM'),
        ('esculab', '90', 'HBcorAg антитіла IgM'),
    ),
    "x:sars-cov-2-spike-igg-quantitative": (
        ('synevo', '2460', 'Коронавірус (S спайкового білка SARS-CoV-2, кількісне визначення), антитіла IgG'),
        ('esculab', '1254', 'Кількісне визначення антитіл класу IgG до S - білка вірусу SARS-CoV-2'),
    ),
    "x:h-pylori-igg": (
        ('synevo', '2041', 'Helicobacter pylori, антитіла IgG'),
        ('esculab', '135', 'Ig G до Хелікобактер пілорі (Helicobacter Pylori)'),
    ),
    "x:chlamydia-trachomatis-iga": (
        ('synevo', '2134', 'Chlamydia trachomatis, антитіла IgA'),
        ('esculab', '126', 'IgA Хламідія (Chlamydia trachomatis)'),
    ),
    "x:chlamydia-trachomatis-igg": (
        ('synevo', '2034', 'Chlamydia trachomatis, антитіла IgG'),
        ('esculab', '128', 'IgG Хламідія (Chlamydia trachomatis)'),
    ),
    "x:chlamydia-trachomatis-igm": (
        ('synevo', '2035', 'Chlamydia trachomatis, антитіла IgM'),
        ('esculab', '127', 'IgМ Хламідія (Chlamydia trachomatis)'),
    ),
    "x:chlamydia-pneumoniae-igg": (
        ('synevo', '2042', 'Chlamydia pneumoniae, антитіла IgG'),
        ('esculab', '149', 'Антитіла IgG до Chlamydia pneumoniae'),
    ),
    "x:chlamydia-pneumoniae-igm": (
        ('synevo', '2043', 'Chlamydia pneumoniae, антитіла IgM'),
        ('esculab', '151', 'Антитіла IgМ до Chlamydia pneumoniae'),
    ),
    "x:mycoplasma-pneumoniae-iga": (
        ('synevo', '2135', 'Mycoplasma pneumoniae, антитіла IgA'),
        ('esculab', '168', 'Антитіла IgА до Mycoplasma pneumoniae'),
    ),
    "x:mycoplasma-pneumoniae-igg": (
        ('synevo', '9030', 'Mycoplasma pneumoniae, антитіла IgG'),
        ('esculab', '167', 'Антитіла IgG до Mycoplasma pneumoniae'),
    ),
    "x:mycoplasma-pneumoniae-igm": (
        ('synevo', '9031', 'Mycoplasma pneumoniae, антитіла IgM'),
        ('esculab', '169', 'Антитіла IgМ до Mycoplasma pneumoniae'),
    ),
    "x:mycoplasma-hominis-iga": (
        ('synevo', '2085', 'Mycoplasma hominis, антитіла IgA'),
        ('esculab', '152', 'Мікоплазма hominis Ig А'),
    ),
    "x:mycoplasma-hominis-igg": (
        ('synevo', '2036', 'Mycoplasma hominis, антитіла IgG'),
        ('esculab', '153', 'Мікоплазма hominis Ig G'),
    ),
    "x:ureaplasma-urealyticum-iga": (
        ('synevo', '2086', 'Ureaplasma urealyticum, антитіла IgA'),
        ('esculab', '158', 'Ureaplasma urealyticum Ig А'),
    ),
    "x:ureaplasma-urealyticum-igg": (
        ('synevo', '2037', 'Ureaplasma urealyticum, антитіла IgG'),
        ('esculab', '159', 'Ureaplasma urealyticum Ig G'),
    ),
    "x:borrelia-igg": (
        ('synevo', '2076', 'Borrelia burgdorferi, антитіла IgG'),
        ('esculab', '140', 'Borrelia burgdorferi антитіла IgG'),
    ),
    "x:borrelia-igm": (
        ('synevo', '2077', 'Borrelia burgdorferi, антитіла IgM'),
        ('esculab', '139', 'Borrelia burgdorferi антитіла IgM'),
    ),
    "x:brucella-igg": (
        ('synevo', '2132', 'Brucella abortus (збудник бруцельозу), антитіла IgG'),
        ('esculab', '2404', 'Brucella, антитіла IgG'),
    ),
    "x:brucella-igm": (
        ('synevo', '2133', 'Brucella abortus (збудник бруцельозу), антитіла IgM'),
        ('esculab', '2405', 'Brucella, антитіла IgM'),
    ),
    "x:yersinia-iga": (
        ('synevo', '2129', 'Yersinia enterocolitica, антитіла IgA'),
        ('esculab', '1318', 'Yersinia enterocolitica IgA'),
    ),
    "x:yersinia-igg": (
        ('synevo', '2130', 'Yersinia enterocolitica, антитіла IgG'),
        ('esculab', '1319', 'Yersinia enterocolitica IgG'),
    ),
    "x:tetanus-toxoid-igg": (
        ('synevo', '2127', 'Tetanus Toxoid (правцевий анатоксин), антитіла IgG'),
        ('esculab', '1904', 'Анатоксин правцевий антитіла / Tetanus-Toxoid-Ak'),
    ),
    "x:diphtheria-toxoid-igg": (
        ('synevo', '2267', 'Diphtheria toxoid (дифтерійний анатоксин), антитіла IgG'),
        ('esculab', '1957', 'anti-anatoxin C. Diphtheriae IgG, кількісний'),
        ('esculab', '2132', 'Антитіла IgG до дифтерійного анатоксину'),
    ),
    "x:giardia-total-antibodies": (
        ('synevo', '2056', 'Giardia (лямблії), антитіла сумарні'),
        ('esculab', '141', 'Сумарні (Ig A, Ig M, Ig G) до лямблій'),
    ),
    "x:ascaris-igg": (
        ('synevo', '2058', 'Ascaris lumbricoides, антитіла IgG'),
        ('esculab', '142', 'Антитіла Іg G до аскарид (Ascaris)'),
    ),
    "x:toxocara-igg": (
        ('synevo', '2057', 'Toxocara canis, антитіла IgG'),
        ('esculab', '143', 'Антитіла Іg G до токсокар (Toxocara)'),
    ),
    "x:echinococcus-igg": (
        ('synevo', '2097', 'Echinococcus granulosus, антитіла IgG'),
        ('esculab', '144', 'Антитіла Іg G до ехінококів (Echinococcus)'),
    ),
    "x:trichinella-igg": (
        ('synevo', '2180', 'Trichinella spiralis, антитіла IgG'),
        ('esculab', '145', 'Антитіла Іg G до трихінел (Trichinella)'),
    ),
    "x:opisthorchis-igg": (
        ('synevo', '2274', 'Opisthorchis felineus, антитіла IgG'),
        ('esculab', '146', 'Антитіла Іg G до опісторхів (Opisthorchis)'),
    ),
    "x:babesia-pcr-tick": (
        ('synevo', '3413', 'ПЛР. Babesia spp. (кліщ, якісне визначення)'),
        ('esculab', '2150', 'Babesia spp. (ПЛР) (якісне визначення)'),
    ),
    "x:cmv-pcr-csf-quantitative": (
        ('synevo', '3208', 'ПЛР. Цитомегаловірус (ліквор, кількісне визначення)'),
        ('esculab', '954', 'Cytomegalovirus (ПЛР) (ліквор) (кількісне визначення)'),
    ),
    "x:cmv-pcr-csf-qualitative": (
        ('synevo', '3049', 'ПЛР. Цитомегаловірус (ліквор, якісне визначення)'),
        ('esculab', '962', 'Cytomegalovirus (ПЛР) (ліквор) (якісне визначення)'),
    ),
    "x:cmv-pcr-urine-quantitative": (
        ('synevo', '3051', 'ПЛР. Цитомегаловірус (сеча, кількісне визначення)'),
        ('esculab', '956', 'Cytomegalovirus (ПЛР) (сеча) (кількісне визначення)'),
    ),
    "x:cmv-pcr-urine-qualitative": (
        ('synevo', '3048', 'ПЛР. Цитомегаловірус (сеча, якісне визначення)'),
        ('esculab', '965', 'Cytomegalovirus (ПЛР) (сеча) (якісне визначення)'),
    ),
    "x:cmv-pcr-saliva-qualitative": (
        ('synevo', '3047', 'ПЛР. Цитомегаловірус (слина, якісне визначення)'),
        ('esculab', '964', 'Cytomegalovirus (ПЛР) (слина) (якісне визначення)'),
    ),
    # autoimmune
    "x:ccp-igg": (
        ('synevo', '1115', 'Циклічний цитруліновий пептид (A-CCP), антитіла IgG'),
        ('esculab', '262', 'Циклічний цитруліновий пептид (Anti-ССР) антитіла IgG'),
    ),
    "x:saccharomyces-iga": (
        ('synevo', '2151', 'Saccharomyces cerevisiae, антитіла IgA'),
        ('esculab', '2228', 'Saccharomyces cerevisiae IgA'),
    ),
    "x:saccharomyces-igg": (
        ('synevo', '2152', 'Saccharomyces cerevisiae, антитіла IgG'),
        ('esculab', '2229', 'Saccharomyces cerevisiae IgG'),
    ),
    "x:gliadin-igg": (('synevo', '9169', 'Гліадин, антитіла IgG'), ('esculab', '339', 'антиГліадин (Gliadin) IgG'),),
    "x:gliadin-iga": (('synevo', '9168', 'Гліадин, антитіла IgA'), ('esculab', '340', 'антиГліадин (Gliadin) IgA'),),
    "x:gliadin-deamidated-igg": (
        ('synevo', '9324', 'Дезаміновані пептиди гліадину, антитіла IgG'),
        ('esculab', '2017', 'Антитіла IgG до гліадину (деамінізовані пептиди), ELiA'),
    ),
    "x:gliadin-deamidated-iga": (
        ('synevo', '9325', 'Дезаміновані пептиди гліадину, антитіла IgA'),
        ('esculab', '2018', 'Антитіла IgA до гліадину (деамінізовані пептиди), ELiA'),
    ),
    "x:ttg-igg": (('synevo', '2108', 'Тканинна трансглутаміназа, антитіла IgG'),),
    "x:ttg-iga": (('synevo', '2109', 'Тканинна трансглутаміназа, антитіла IgA'),),
    "x:gad-antibodies": (
        ('synevo', '9196', 'Глютамінокисла декарбоксилаза (GADA), антитіла IgG'),
        ('esculab', '779', 'Антитіла до декарбоксилази глутамінової кислоти (GAD65 Abs)'),
    ),
    "x:cardiolipin-igg": (('synevo', '2079', 'Кардіоліпін, антитіла IgG'), ('esculab', '332', 'Кардіоліпіни IgG'),),
    "x:cardiolipin-igm": (('synevo', '2080', 'Кардіоліпін, антитіла IgM'), ('esculab', '333', 'Кардіоліпіни IgM'),),
    "x:beta-2-glycoprotein-i-igg": (
        ('synevo', '2119', 'β-2-глікопротеїд I, антитіла IgG'),
        ('esculab', '692', 'АТ до бета-2 глікопротеїну 1 IgG'),
    ),
    "x:beta-2-glycoprotein-i-igm": (
        ('synevo', '9331', 'β-2-глікопротеїд I, антитіла IgM'),
        ('esculab', '1271', 'АТ до бета-2 глікопротеїну 1 IgM'),
    ),
    "x:phospholipid-igg": (
        ('synevo', '2047', 'Фосфоліпіди, антитіла IgG'),
        ('esculab', '334', 'Фосфоліпіди, антитіла IgG'),
    ),
    "x:phospholipid-igm": (
        ('synevo', '2048', 'Фосфоліпіди, антитіла IgM'),
        ('esculab', '335', 'Фосфоліпіди, антитіла IgM'),
    ),
    "x:ssdna-igg": (
        ('synevo', '2045', 'ДНК односпіральна, антитіла IgG'),
        ('esculab', '2836', 'ДНК односпіральна, антитіла IgG'),
    ),
    "x:ana-ift": (
        ('synevo', '9344', 'Антинуклеарні антитіла (ANA, метод IFT)'),
        ('esculab', '1917', 'Антинуклеарні антитіла / ANA (метод ІФА)'),
        ('esculab', '1918', 'Антинуклеарні антитіла / ANA-висота титру (метод IFT)'),
        ('esculab', '1919', 'ANA-флюоресцентний малюнок (*опис наявний при позитивному результаті)'),
    ),
    "x:intrinsic-factor-igg": (('esculab', '2620', 'Внутрішній фактор Кастла, IgG, EliA'),),
}

#: Shared keys whose members' names resolve to a concept of ours that they
#: are not: ``x:<slug> -> (concept, why)``.
DISTINCT_FROM: dict[str, tuple[str, str]] = {
    "x:ana-ift": ("antinuclear-antibodies",
                  "indirect immunofluorescence on HEp-2 cells (titre, pattern), not the immunoassay index "
                  "the record's ANA holds"),
}

# --- whole examinations -------------------------------------------------------------

_CBC = (
    "white-blood-cell-count", "red-blood-cell-count", "hemoglobin", "hematocrit", "mean-corpuscular-volume",
    "mean-corpuscular-hemoglobin", "mean-corpuscular-hemoglobin-concentration", "red-cell-distribution-width-cv",
    "red-cell-distribution-width-sd", "platelet-count", "mean-platelet-volume", "platelet-distribution-width-sd",
    "plateletcrit", "neutrophils", "neutrophils-absolute", "lymphocytes", "lymphocytes-absolute", "monocytes",
    "monocytes-absolute", "eosinophils", "eosinophils-absolute", "basophils", "basophils-absolute",
    "immature-granulocytes", "immature-granulocytes-absolute",
)
_MANUAL_DIFFERENTIAL = (
    "band-neutrophils", "segmented-neutrophils", "lymphocytes-manual-differential", "monocytes-manual-differential",
    "eosinophils-manual-differential", "basophils-manual-differential", "metamyelocytes", "myelocytes",
    "promyelocytes",
)
#: What Synevo's «Аналіз сечі загальний (ЗАС + ручна мікроскопія осаду)» reported in the record.
_SYNEVO_URINALYSIS = (
    "urine-sample-delivered-volume", "urine-colour", "urine-appearance", "urine-specific-gravity", "urine-ph",
    "urine-protein", "urine-glucose", "urine-ketones", "urine-bilirubin", "urine-urobilinogen", "urine-nitrite",
    "urine-leukocytes", "urine-leukocytes-per-high-power-field", "urine-erythrocytes",
    "squamous-epithelial-cells-in-urine", "transitional-epithelial-cells-in-urine",
    "renal-epithelial-cells-in-urine", "urine-bladder-epithelial-cells", "hyaline-casts-in-urine",
    "granular-casts-in-urine", "epithelial-casts-in-urine", "waxy-casts-in-urine", "urine-erythrocyte-casts",
    "urine-leukocyte-casts", "uric-acid-crystals-in-urine", "calcium-oxalate-crystals-in-urine",
    "triple-phosphate-crystals-in-urine", "calcium-phosphate-crystals-in-urine",
    "phosphate-of-lime-crystals-in-urine", "calcium-carbonate-crystals-in-urine",
    "ammonium-biurate-crystals-in-urine", "bilirubin-crystals-in-urine", "urine-amorphous-urates",
    "urine-amorphous-phosphates", "urine-mucus", "urine-bacteria", "urine-yeast", "urine-trichomonads",
    "urine-sperm-cells",
)
_NECHIPORENKO = ("x:nechiporenko-leukocytes", "x:nechiporenko-erythrocytes", "x:nechiporenko-casts")

#: ``(lab, parameter id) -> (keys, printed name)``.  Synevo lists a panel's
#: blood count, differential and urinalysis as one member each; the record's
#: Synevo reports of the same examinations show what each one prints.
WHOLE: dict[tuple[str, str], tuple[tuple[str, ...], str]] = {
    ("synevo", "name:ahaлiзkpobipoзгophytий(зak)"): (_CBC, "Аналіз крові розгорнутий (ЗАК)"),
    ("synevo", "name:ahaлiзkpobi:лeйkoциtaphaфopmyлa(pyчhийпiдpaxyhok)"): (
        _MANUAL_DIFFERENTIAL, "Аналіз крові: Лейкоцитарна формула (ручний підрахунок)"),
    ("synevo", "4071"): (_SYNEVO_URINALYSIS, "Аналіз сечі загальний з мікроскопічною оцінкою осаду"),
    ("synevo", "1100"): (("prothrombin-time", "quick-prothrombin-index", "inr"),
                         "Протромбіновий тест (ПЧ, % за Квіком, МНВ / INR)"),
    ("synevo", "4003"): (("blood-group", "rhesus-factor"), "Група крові/резус фактор"),
    # Group and Rh, plus the Rh antigens and Kell nobody else sells as one test.
    ("synevo", "4270"): (("blood-group", "rhesus-factor", "synevo:4270"),
                         "Фенотип крові: Група крові/Резус-фактор (Rh), антигени системи Rh (С, с, Е, е), "
                         "антиген К системи Келл (Kell)"),
    ("synevo", "4006"): (_NECHIPORENKO, "Аналіз сечі за Нечипоренком"),
    # Esculab's coeliac panels are one row each; their names list the members.
    ("esculab", "341"): (("x:gliadin-deamidated-igg", "x:ttg-igg", "x:intrinsic-factor-igg"),
                         "Панель Целіакія (deam. Gliadin IgG, tTG IgG, intrinsic factor)"),
    ("esculab", "342"): (("x:gliadin-deamidated-iga", "x:ttg-iga", "x:immunoglobulin-a"),
                         "Панель Целіакія 2 (deam.Gliadin IgA, tTG IgA, загальний IgA)"),
}

#: Keys the record derives from another: :mod:`..derived` calculates the
#: CKD-EPI 2021 eGFR from every verified serum creatinine, so measuring
#: creatinine renews the eGFR too.
IMPLIED: dict[str, tuple[str, ...]] = {
    "creatinine": ("estimated-glomerular-filtration-rate-ckd-epi-2021",),
}

# --- rows that measure nothing ------------------------------------------------------

#: Section headings and note fields, by normalized name.  Esculab prints
#: «Мікроскопія сечі» above the sediment rows it lists one by one (result
#: «-»), and «Примітки» on 119 items.
NOT_ANALYTES = frozenset({
    "мікроскопія сечі", "фізико-хімічні властивості", "звіт з описом лабораторних показників",
})
_NOTE = re.compile(r"^(?:\w+ )?(?:примітк\w*|коментар)\b")


def is_note(normalized_name: str) -> bool:
    return normalized_name in NOT_ANALYTES or bool(_NOTE.match(normalized_name))


# --- specific IgE, by allergen code ---------------------------------------------

#: A specific-IgE test: the lab says IgE (or sells it as an allergen test) and
#: not IgG/IgG4, which is a different antibody class.
_SIGE = re.compile(r"\bs?ig\s?[eе]\b|алерген|алергокомпонент", re.IGNORECASE)
_NOT_IGE = re.compile(r"\big\s?g|\bigg4|базофіл|basophil|\bcd\d", re.IGNORECASE)
#: A WHO/IUIS allergen molecule as labs print it: «rBet v1», «nBos d 8»,
#: «rPhl p 5b», «Ana o3»; the r/n prefix (recombinant/native) is the source of
#: the protein, not a different molecule.
_MOLECULE = re.compile(r"(?<![A-Za-z])[rn]?([A-Z][a-z]{1,3})\s?([a-z]{1,2})\s?(\d{1,2}[a-z]?)(?![\w])")
#: An ImmunoCAP allergen code in brackets or after a comma: f13 (peanut), d1
#: (house dust mite), fx5 (a food mixture).  Labs print some with Cyrillic
#: homoglyphs («с6», «е220», «мх2»).
_CODE = re.compile(r"(?<![\w-])((?:[fedgtwmikcopuh]x?))(\d{1,4})(?![\w-])")
_TO_LATIN = str.maketrans("асеікмортху", "aceikmoptxy")


def allergen_key(name: str) -> str | None:
    """``x:sige:<allergen>`` for a specific-IgE test, the same at every lab
    that prints the same allergen code or molecule: Esculab's «алерген арахіс
    (f13), специфічні IgE» and Synevo's «Алерген. Екстракт. Арахіс (земляний
    горіх, f13), антитіла IgE» are one measurement.  A molecule outranks the
    extract code printed beside it («rBet v1 PR-10 (t215)»), so a molecule is
    matched to the same molecule.  None when the test is not specific IgE or
    names no code."""
    if not _SIGE.search(name) or _NOT_IGE.search(name):
        return None
    molecules = sorted({f"{genus.casefold()}-{species}-{number}" for genus, species, number in _MOLECULE.findall(name)})
    if molecules:
        return "x:sige:" + "+".join(molecules)
    codes = sorted({prefix + number for prefix, number in _CODE.findall(name.casefold().translate(_TO_LATIN))})
    return "x:sige:" + "+".join(codes) if codes else None


def _index() -> dict[tuple[str, str], tuple[str, ...]]:
    """Every curated ``(lab, parameter id)`` with the keys it stands for
    (empty: keep the lab's own key).  A parameter in two tables is a bug."""
    index: dict[tuple[str, str], tuple[str, ...]] = {}

    def put(key, keys):
        if key in index:
            raise ValueError(f"{key} is curated twice")
        index[key] = keys

    for key, (concept, _) in CONCEPTS.items():
        put(key, (concept,))
    for key in UNMAPPED:
        put(key, ())
    for shared, members in SAME.items():
        for lab, parameter, _ in members:
            put((lab, parameter), (shared,))
    for key, (keys, _) in WHOLE.items():
        put(key, keys)
    return index


CURATED = _index()


def curated(lab: str, parameter_id: str) -> tuple[str, ...] | None:
    """The keys a curated parameter stands for; ``()`` for the lab's own
    key; None when nothing here decides it."""
    return CURATED.get((lab, str(parameter_id)))
