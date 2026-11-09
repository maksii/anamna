"""Messages for the DNA (genetic tests) overview page: both supported languages.

Each test's name and one-line answer are the planner's ``special.<id>`` and
``special.<id>_what``; the longer explanations here rest on the sources
listed per test in :mod:`anamna.genetics`.
"""
from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "genetics.page.title": {"en": "Your DNA", "uk": "Ваша ДНК"},
    "genetics.page.eyebrow": {"en": "Genetic tests", "uk": "Генетичні аналізи"},
    "genetics.page.lead": {
        "en": "Your genetic results, and what the common DNA tests can tell you.",
        "uk": "Ваші генетичні результати й те, що можуть показати поширені ДНК-тести.",
    },
    # --- your results ---------------------------------------------------------
    "genetics.mine.title": {"en": "Results about your genes", "uk": "Результати про ваші гени"},
    "genetics.mine.empty_title": {"en": "No tests of your own genes yet", "uk": "Аналізів ваших генів ще немає"},
    "genetics.mine.empty_body": {
        "en": "A genetic result in your record appears here with what it means. Below are the DNA tests labs sell most often.",
        "uk": "Генетичний результат із вашої картки з’явиться тут разом із поясненням. Нижче є ДНК-тести, які лабораторії продають найчастіше.",
    },
    "genetics.result.means": {"en": "What it means", "uk": "Що це означає"},
    "genetics.result.once": {
        "en": "Your genes do not change over life, so this test does not need repeating.",
        "uk": "Гени не змінюються протягом життя, тому цей аналіз не потрібно повторювати.",
    },
    "genetics.result.gen-hla-b27.absent": {
        "en": "You do not carry HLA-B27. This lowers the chance of axial spondyloarthritis (inflammatory disease of the "
              "spine and pelvic joints) but does not rule it out: the diagnosis can also rest on imaging and other signs.",
        "uk": "Ви не є носієм HLA-B27. Це знижує ймовірність аксіального спондилоартриту (запального ураження хребта й "
              "крижово-клубових суглобів), але не виключає його: діагноз можна встановити й за знімками та іншими ознаками.",
    },
    "genetics.result.gen-hla-b27.present": {
        "en": "You carry HLA-B27. Many healthy people do: on its own it is not a diagnosis, and it matters only together "
              "with inflammatory back pain or other signs of spondyloarthritis.",
        "uk": "Ви є носієм HLA-B27. Так буває в багатьох здорових людей: сам по собі це не діагноз, він важить лише разом "
              "із запальним болем у спині чи іншими ознаками спондилоартриту.",
    },
    "genetics.result.gen-hla-b27.context": {
        "en": "About 95% of people with ankylosing spondylitis carry HLA-B27 (the guideline used in Ukraine), yet few "
              "carriers ever develop it: 1 to 5% according to MedlinePlus, under 1% according to that guideline.",
        "uk": "Близько 95% людей з анкілозуючим спондилітом мають HLA-B27 (настанова, чинна в Україні), але хворіють "
              "небагато носіїв: від 1 до 5% за MedlinePlus, менше 1% за тією ж настановою.",
    },
    # --- not about your genes -------------------------------------------------
    "genetics.other.title": {"en": "Not about your genes", "uk": "Не про ваші гени"},
    "genetics.other.lead": {
        "en": "These results have DNA in their name but test something else.",
        "uk": "У назвах цих результатів є «ДНК», але вони перевіряють інше.",
    },
    "genetics.other.germ_title": {"en": "A germ's DNA (PCR)", "uk": "ДНК збудника (ПЛР)"},
    "genetics.other.germ_body": {
        "en": "PCR (polymerase chain reaction) looks for the genetic material of a bacterium, virus or parasite in a "
              "sample. It shows whether that infection was there on the day, and nothing about your genes.",
        "uk": "ПЛР (полімеразна ланцюгова реакція) шукає генетичний матеріал бактерії, вірусу чи паразита у зразку. "
              "Вона показує, чи була ця інфекція в день аналізу, і нічого не каже про ваші гени.",
    },
    "genetics.other.antibody_title": {"en": "Antibodies to DNA", "uk": "Антитіла до ДНК"},
    "genetics.other.antibody_body": {
        "en": "An autoimmune blood test: it looks for antibodies the immune system made against DNA, not at your genes.",
        "uk": "Аутоімунний аналіз крові: він шукає антитіла, які імунна система виробила проти ДНК, а не досліджує ваші гени.",
    },
    # --- what a test can answer -----------------------------------------------
    "genetics.tests.title": {"en": "What a DNA test can answer", "uk": "На що може відповісти ДНК-тест"},
    "genetics.tests.lead": {
        "en": "Your genes do not change, so each of these is done once.",
        "uk": "Гени не змінюються, тож кожен із цих аналізів роблять один раз.",
    },
    "genetics.tests.plan_all": {"en": "Plan DNA tests", "uk": "Спланувати ДНК-тести"},
    "genetics.group.food": {"en": "Food and digestion", "uk": "Їжа й травлення"},
    "genetics.group.blood": {"en": "Blood and clotting", "uk": "Кров і згортання"},
    "genetics.group.liver": {"en": "Liver", "uk": "Печінка"},
    "genetics.group.joints": {"en": "Joints and spine", "uk": "Суглоби й хребет"},
    "genetics.group.cancer": {"en": "Inherited cancer risk", "uk": "Спадковий ризик раку"},
    "genetics.group.carrier": {"en": "Carrier status", "uk": "Носійство"},
    "genetics.group.medicines": {"en": "Medicines", "uk": "Ліки"},
    "genetics.test.done": {"en": "Done {date}", "uk": "Зроблено {date}"},
    "genetics.test.price_from": {"en": "From {price} at {lab}", "uk": "Від {price} у {lab}"},
    "genetics.test.not_sold": {"en": "Not sold by the labs we compare", "uk": "Немає в лабораторіях, які ми порівнюємо"},
    "genetics.test.prices_pending": {"en": "Prices are not available yet", "uk": "Ціни ще недоступні"},
    "genetics.test.your_result": {"en": "Your result", "uk": "Ваш результат"},
    "genetics.test.for": {"en": "Who it is for", "uk": "Кому це потрібно"},
    "genetics.test.limits": {"en": "Limits", "uk": "Обмеження"},
    "genetics.test.differs": {"en": "Where guidelines differ", "uk": "Де настанови розходяться"},
    "genetics.test.prices": {"en": "Price by lab, blood draw included", "uk": "Ціна в лабораторіях, разом із забором крові"},
    "genetics.test.includes": {"en": "What to order: {items}", "uk": "Що замовити: {items}"},
    "genetics.test.plan": {"en": "Plan this test", "uk": "Спланувати цей аналіз"},
    # --- per test: who it is for, limits, regional differences ------------------
    "genetics.entry.gen-lactose.for": {
        "en": "Adults with bloating or diarrhoea after milk, to tell the inherited adult decline of lactase from other "
              "causes. About 65% of people digest lactose less well after infancy.",
        "uk": "Дорослим зі здуттям чи проносом після молока, щоб відрізнити спадкове згасання лактази від інших причин. "
              "Близько 65% людей після дитинства гірше перетравлюють лактозу.",
    },
    "genetics.entry.gen-lactose.limits": {
        "en": "The gene shows whether lactase is set to decline, not how much milk you tolerate: symptoms depend on the "
              "amount of lactose. In children under 12 the result is only indicative.",
        "uk": "Ген показує, чи запрограмоване згасання лактази, а не скільки молока ви переносите: симптоми залежать від "
              "кількості лактози. У дітей до 12 років результат лише орієнтовний.",
    },
    "genetics.entry.gen-celiac.for": {
        "en": "Mostly to rule celiac disease out: when blood tests and biopsy disagree, when you already eat gluten-free, "
              "or for a parent, sibling or child of someone with celiac disease.",
        "uk": "Здебільшого щоб виключити целіакію: коли аналізи крові й біопсія не збігаються, коли ви вже не їсте "
              "глютен, або батькам, братам, сестрам і дітям людини з целіакією.",
    },
    "genetics.entry.gen-celiac.limits": {
        "en": "About 30% of people carry DQ2 or DQ8 and only about 3% of them develop celiac disease, so a positive "
              "result diagnoses nothing. It does not replace the antibody blood test or the biopsy.",
        "uk": "DQ2 або DQ8 мають близько 30% людей, і лише близько 3% із них хворіють на целіакію, тож позитивний "
              "результат нічого не діагностує. Він не замінює аналізу крові на антитіла чи біопсії.",
    },
    "genetics.entry.gen-hemochromatosis.for": {
        "en": "When ferritin and transferrin saturation are raised, or a parent, sibling or child has haemochromatosis. "
              "EASL advises checking the iron tests first and the gene after.",
        "uk": "Коли підвищені феритин і насичення трансферину або спадковий гемохроматоз є в батьків, братів, сестер чи "
              "дітей. EASL радить спершу перевірити залізо, а потім ген.",
    },
    "genetics.entry.gen-hemochromatosis.limits": {
        "en": "Two copies of C282Y is the main risk genotype, yet iron overload disease develops in about 28% of such "
              "men and 1% of such women. One copy, or H63D alone, rarely causes overload.",
        "uk": "Основний ризиковий генотип: дві копії C282Y, але хвороба від перевантаження залізом розвивається лише "
              "в близько 28% таких чоловіків і 1% таких жінок. Одна копія або лише H63D рідко спричиняє перевантаження.",
    },
    "genetics.entry.gen-hemochromatosis.differs": {
        "en": "EASL (2022) calls the value of H63D testing controversial; the older guideline used in Ukraine (2014) "
              "still lists testing relatives for it.",
        "uk": "EASL (2022) вважає цінність аналізу на H63D суперечливою; старіша настанова, чинна в Україні (2014), "
              "досі радить перевіряти на нього родичів.",
    },
    "genetics.entry.gen-thrombophilia.for": {
        "en": "After a blood clot in particular situations, or in families with clots, when a doctor decides the result "
              "would change treatment.",
        "uk": "Після тромбозу в певних ситуаціях або в родинах, де були тромбози, коли лікар вирішує, що результат "
              "змінить лікування.",
    },
    "genetics.entry.gen-thrombophilia.limits": {
        "en": "Not for testing healthy people, including before starting the contraceptive pill. 3 to 8% of people of "
              "European ancestry carry factor V Leiden, and about 10% of carriers ever have a clot. A positive result "
              "alone is not a reason to start blood thinners.",
        "uk": "Не для перевірки здорових людей, зокрема перед початком гормональної контрацепції. Лейденську мутацію "
              "мають 3-8% людей європейського походження, і тромбоз колись буває лише в близько 10% носіїв. Сам "
              "позитивний результат не є причиною починати антикоагулянти.",
    },
    "genetics.entry.gen-thrombophilia.differs": {
        "en": "ASH (US, 2023) suggests testing after a clot provoked by pregnancy or a non-surgical major risk factor; "
              "ESHRE (Europe, 2022) suggests not testing women with recurrent pregnancy loss. All advise against "
              "testing the general population.",
        "uk": "ASH (США, 2023) радить аналіз після тромбозу, спричиненого вагітністю чи вагомим нехірургічним "
              "чинником; ESHRE (Європа, 2022) радить не робити його жінкам із повторними втратами вагітності. Усі "
              "проти перевірки загального населення.",
    },
    "genetics.entry.gen-mthfr.for": {
        "en": "Rarely useful. ACMG advises against ordering it as part of a check of clotting risk or of recurrent "
              "pregnancy loss.",
        "uk": "Рідко буває корисним. ACMG не радить призначати його для оцінки ризику тромбозів чи при повторних "
              "втратах вагітності.",
    },
    "genetics.entry.gen-mthfr.limits": {
        "en": "These variants are very common and their role in disease remains unclear. ESHRE (2022) no longer counts "
              "them in assessing thrombosis risk.",
        "uk": "Ці варіанти дуже поширені, а їхня роль у хворобах лишається неясною. ESHRE (2022) більше не враховує їх "
              "в оцінці ризику тромбозів.",
    },
    "genetics.entry.gen-gilbert.for": {
        "en": "To explain a mildly raised indirect bilirubin, or before treatment with irinotecan (a cancer drug), whose "
              "starting dose DPWG cuts to 70% for people with two weak gene copies.",
        "uk": "Щоб пояснити помірно підвищений непрямий білірубін, або перед лікуванням іринотеканом (протипухлинним "
              "препаратом), початкову дозу якого DPWG знижує до 70% для людей із двома слабкими копіями гена.",
    },
    "genetics.entry.gen-gilbert.limits": {
        "en": "Gilbert syndrome is mild and needs no treatment; 3 to 7% of people have it.",
        "uk": "Синдром Жильбера перебігає легко й не потребує лікування; він є в 3-7% людей.",
    },
    "genetics.entry.gen-hla-b27.for": {
        "en": "Back pain that began before about 45 and eases with movement rather than rest: the result is read "
              "together with imaging and other signs of spondyloarthritis.",
        "uk": "Біль у спині, що почався приблизно до 45 років і минає під час руху, а не в спокої: результат оцінюють "
              "разом зі знімками та іншими ознаками спондилоартриту.",
    },
    "genetics.entry.gen-hla-b27.limits": {
        "en": "Most carriers never develop the disease, and a negative result lowers the chance without ruling it out. "
              "Without symptoms the test says very little.",
        "uk": "Більшість носіїв ніколи не хворіє, а негативний результат знижує ймовірність, але не виключає її. Без "
              "симптомів аналіз майже нічого не означає.",
    },
    "genetics.entry.gen-hla-b27.differs": {
        "en": "How rarely carriers fall ill: 1 to 5% according to MedlinePlus (US), under 1% according to the "
              "guideline used in Ukraine.",
        "uk": "Наскільки рідко хворіють носії: 1-5% за MedlinePlus (США), менше 1% за настановою, чинною в Україні.",
    },
    "genetics.entry.gen-brca.for": {
        "en": "When close relatives had breast, ovarian or prostate cancer, especially young, or a BRCA variant is known "
              "in the family. Men carry and pass on these variants too.",
        "uk": "Коли близькі родичі хворіли на рак грудей, яєчників чи простати, особливо в молодому віці, або в родині "
              "вже знайдено варіант BRCA. Чоловіки теж є носіями й передають ці варіанти.",
    },
    "genetics.entry.gen-brca.limits": {
        "en": "Belongs with genetic counselling before and after the test. A lab's panel may not report every known "
              "variant, so a negative result is not a guarantee.",
        "uk": "Аналіз роблять разом із генетичним консультуванням до й після нього. Панель лабораторії може не "
              "охоплювати всіх відомих варіантів, тож негативний результат не є гарантією.",
    },
    "genetics.entry.gen-brca.differs": {
        "en": "USPSTF (US) advises against routine testing of women with no family or ancestry risk; the Ukrainian "
              "standard (order 195, 2025) lists it as desirable, especially before 50 or with a family history, and "
              "counts male sex among the criteria.",
        "uk": "USPSTF (США) не радить рутинно перевіряти жінок без сімейного чи етнічного ризику; український "
              "стандарт (наказ № 195, 2025) вважає аналіз бажаним, особливо до 50 років чи за сімейної історії, і "
              "зараховує до критеріїв чоловічу стать.",
    },
    "genetics.entry.gen-lynch.for": {
        "en": "When relatives had bowel, womb or related cancers, especially young, or a family variant is known. About "
              "1 in 279 people carry a Lynch variant.",
        "uk": "Коли родичі хворіли на рак кишківника, матки чи пов’язані види раку, особливо в молодому віці, або в "
              "родині вже знайдено варіант. Варіант синдрому Лінча має приблизно 1 людина з 279.",
    },
    "genetics.entry.gen-lynch.limits": {
        "en": "Belongs with genetic counselling. A positive result changes bowel screening: regular colonoscopy from a "
              "young age.",
        "uk": "Аналіз роблять разом із генетичним консультуванням. Позитивний результат змінює обстеження кишківника: "
              "регулярна колоноскопія з молодого віку.",
    },
    "genetics.entry.gen-lynch.differs": {
        "en": "European guidelines (EHTG and ESCP, 2021) start colonoscopy at 25 or 35 depending on the gene, every 2 "
              "to 3 years; Ukraine's screening order (No. 1368, 2024) covers people at risk from 50 to 75.",
        "uk": "Європейські настанови (EHTG і ESCP, 2021) починають колоноскопію з 25 або 35 років залежно від гена, "
              "кожні 2-3 роки; український порядок скринінгу (наказ № 1368, 2024) охоплює людей груп ризику від 50 до 75 років.",
    },
    "genetics.entry.gen-cftr.for": {
        "en": "Couples planning a child, especially with cystic fibrosis in the family: if both partners carry a "
              "variant, each child has a 25% chance of the disease.",
        "uk": "Парам, що планують дитину, особливо якщо в родині був муковісцидоз: якщо обидва партнери є носіями, "
              "кожна дитина має 25% шансу захворіти.",
    },
    "genetics.entry.gen-cftr.limits": {
        "en": "Labs test the variants most common in Europe, while more than 1,000 are known and the Ukrainian spectrum "
              "is not yet fully described, so a negative panel does not rule out being a carrier.",
        "uk": "Лабораторії перевіряють найпоширеніші в Європі варіанти, а відомо понад 1000, і український спектр ще не "
              "визначено повністю, тож негативна панель не виключає носійства.",
    },
    "genetics.entry.gen-cftr.differs": {
        "en": "ACMG (US) offers carrier screening to everyone pregnant or planning a pregnancy; ESHG (Europe) stops "
              "short of recommending population screening; the Ukrainian protocol (No. 723) counsels families with a "
              "known case.",
        "uk": "ACMG (США) пропонує перевірку на носійство всім вагітним і тим, хто планує вагітність; ESHG (Європа) "
              "не рекомендує масового скринінгу; український протокол (наказ № 723) передбачає консультування родин "
              "із відомим випадком.",
    },
    "genetics.entry.gen-carrier-t1.for": {
        "en": "Couples planning a child who want the basic check: cystic fibrosis and spinal muscular atrophy are "
              "the two recessive conditions every carrier screen covers, and the commonest serious ones in Europe.",
        "uk": "Парам, що планують дитину й хочуть базової перевірки: муковісцидоз і спінальна м'язова атрофія є "
              "двома рецесивними станами, які охоплює будь-який скринінг носійства, і найчастішими тяжкими в Європі.",
    },
    "genetics.entry.gen-carrier-t1.limits": {
        "en": "Two conditions only. Cystic fibrosis panels read the commonest variants, so a negative result lowers "
              "the chance of being a carrier without removing it; SMA carrier tests count SMN1 copies and miss a rare "
              "kind of carrier with two copies on one chromosome.",
        "uk": "Лише два стани. Панелі муковісцидозу читають найпоширеніші варіанти, тож негативний результат знижує "
              "ймовірність носійства, але не прибирає її; тести на носійство СМА рахують копії SMN1 і пропускають "
              "рідкісних носіїв із двома копіями на одній хромосомі.",
    },
    "genetics.entry.gen-carrier-t1.differs": {
        "en": "ACMG (US, 2021) treats these two as the floor and advises Tier 3 for everyone; ESHG (Europe, 2016) "
              "leaves screening to informed choice; Ukrainian protocols counsel families with a known case.",
        "uk": "ACMG (США, 2021) вважає ці два стани мінімумом і радить рівень 3 усім; ESHG (Європа, 2016) залишає "
              "скринінг на поінформований вибір; українські протоколи передбачають консультування родин із "
              "відомим випадком.",
    },
    "genetics.entry.gen-carrier-t2.for": {
        "en": "Couples who want more than the basic two: ACMG Tier 2 adds every recessive condition carried by 1 in "
              "100 people or more in any population.",
        "uk": "Парам, яким мало двох базових станів: рівень 2 ACMG додає всі рецесивні стани, носієм яких є 1 зі "
              "100 людей або частіше в будь-якій популяції.",
    },
    "genetics.entry.gen-carrier-t2.limits": {
        "en": "No lab here sells a Tier 2 panel on its own, so the plan buys a panel that states Tier 3, which "
              "holds Tier 2. The same limits as Tier 3 apply.",
        "uk": "Окремої панелі рівня 2 тут не продають, тож план купує панель, що заявляє рівень 3, яка охоплює "
              "рівень 2. Обмеження ті самі, що й у рівня 3.",
    },
    "genetics.entry.gen-carrier-t2.differs": {
        "en": "ACMG (US, 2021) advises going on to Tier 3 for everyone; ESHG (Europe, 2016) does not set tiers.",
        "uk": "ACMG (США, 2021) радить усім рівень 3; ESHG (Європа, 2016) рівнів не встановлює.",
    },
    "genetics.entry.gen-carrier-t3.for": {
        "en": "Couples planning a child or early in a pregnancy who want the widest check: one test reads hundreds "
              "of genes for recessive and X-linked diseases, cystic fibrosis and spinal muscular atrophy among them. "
              "Testing both partners is what gives the answer: a child is at risk only when both carry the same gene.",
        "uk": "Парам, що планують дитину або на ранньому терміні вагітності й хочуть найширшої перевірки: один аналіз "
              "читає сотні генів рецесивних і X-зчеплених хвороб, серед них муковісцидоз і спінальну м'язову атрофію. "
              "Відповідь дає перевірка обох партнерів: дитина в групі ризику лише тоді, коли обидва несуть зміну в "
              "тому самому гені.",
    },
    "genetics.entry.gen-carrier-t3.limits": {
        "en": "It answers one question, what a child could inherit. It does not test your own clotting risk (F5 Leiden, "
              "F2), lactose, celiac or HLA types, cancer genes or medicine response, so it does not replace those "
              "tests. A negative result lowers the risk but does not remove it.",
        "uk": "Відповідає на одне питання: що може успадкувати дитина. Не перевіряє ваш ризик тромбозів (F5 Лейден, "
              "F2), лактозу, целіакію чи HLA, гени раку або реакцію на ліки, тож тих аналізів не замінює. "
              "Негативний результат знижує ризик, але не прибирає його.",
    },
    "genetics.entry.gen-carrier-t3.differs": {
        "en": "ACMG (US, 2021) advises offering such screening to everyone pregnant or planning a pregnancy; ESHG "
              "(Europe, 2016) leaves it to informed choice rather than population screening; Ukrainian protocols "
              "address families with a known case, such as cystic fibrosis (No. 723).",
        "uk": "ACMG (США, 2021) радить пропонувати такий скринінг усім вагітним і тим, хто планує вагітність; ESHG "
              "(Європа, 2016) залишає його на поінформований вибір, а не масовий скринінг; українські протоколи "
              "стосуються родин із відомим випадком, як-от муковісцидоз (наказ № 723).",
    },
    "genetics.entry.gen-warfarin.for": {
        "en": "Only when warfarin is about to be started or planned: the genotype can help choose the starting dose.",
        "uk": "Лише коли варфарин збираються призначити: генотип допомагає вибрати початкову дозу.",
    },
    "genetics.entry.gen-warfarin.limits": {
        "en": "Genes and other known factors explain about half of the dose differences between people. INR checks (the "
              "clotting time test that guides the dose) are still needed, and the test adds little once your dose is stable.",
        "uk": "Гени й інші відомі чинники пояснюють лише близько половини відмінностей у дозі між людьми. МНВ (показник "
              "згортання крові, за яким підбирають дозу) однаково треба перевіряти, а коли доза вже стабільна, аналіз мало що додає.",
    },
    "genetics.entry.gen-warfarin.differs": {
        "en": "CPIC (international) and DPWG (Europe) give starting doses by genotype; the Ukrainian atrial "
              "fibrillation protocol (No. 597) says routine genotyping is usually not needed.",
        "uk": "CPIC (міжнародний) і DPWG (Європа) дають початкові дози за генотипом; український протокол щодо "
              "фібриляції передсердь (наказ № 597) вважає, що систематичне генотипування зазвичай не потрібне.",
    },
    # --- sources --------------------------------------------------------------
    "genetics.sources.title": {"en": "Sources", "uk": "Джерела"},
    "genetics.sources.page": {"en": "Sources for this page", "uk": "Джерела цієї сторінки"},
    "genetics.sources.duodecim": {
        "en": "Ukrainian translation of a Finnish Duodecim guideline",
        "uk": "Український переклад фінської настанови Duodecim",
    },
    "genetics.region.US": {"en": "United States", "uk": "США"},
    "genetics.region.EU": {"en": "Europe", "uk": "Європа"},
    "genetics.region.UA": {"en": "Ukraine", "uk": "Україна"},
    "genetics.region.INT": {"en": "International", "uk": "Міжнародне"},
}
