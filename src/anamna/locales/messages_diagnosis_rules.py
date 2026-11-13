"""Explanations of the possible diagnoses: one note per matrix rule, one line per doctor."""

MESSAGES_DIAGNOSIS_RULES: dict[str, dict[str, str]] = {
    "dx.doctor.family": {
        "en": "Start with your family doctor.",
        "uk": "Почніть із сімейного лікаря.",
    },
    "dx.doctor.cardiologist": {
        "en": "Your family doctor or a cardiologist can assess this.",
        "uk": "Це оцінить сімейний лікар або кардіолог.",
    },
    "dx.doctor.endocrinologist": {
        "en": "This is a question for an endocrinologist; your family doctor can refer you.",
        "uk": "Це питання до ендокринолога; направити може сімейний лікар.",
    },
    "dx.doctor.haematologist": {
        "en": "This is a question for a haematologist; your family doctor can refer you.",
        "uk": "Це питання до гематолога; направити може сімейний лікар.",
    },
    "dx.doctor.nephrologist": {
        "en": "This is a question for a nephrologist; your family doctor can refer you.",
        "uk": "Це питання до нефролога; направити може сімейний лікар.",
    },
    "dx.doctor.gastroenterologist": {
        "en": "Your family doctor or a gastroenterologist can assess this.",
        "uk": "Це оцінить сімейний лікар або гастроентеролог.",
    },
    "dx.rule.lipid_mixed.note": {
        "en": "Cholesterol and triglycerides are both above the published cut-points. That combination is what ICD-10 calls mixed hyperlipidaemia. A doctor confirms it on a repeat fasting lipid profile and looks for causes such as thyroid, kidney or liver disease, diabetes and medicines.",
        "uk": "Холестерин і тригліцериди водночас вищі за опубліковані пороги. Саме таке поєднання в МКХ-10 називається змішаною гіперліпідемією. Лікар підтверджує її повторною ліпідограмою натще і шукає причини: хвороби щитоподібної залози, нирок чи печінки, діабет, ліки.",
    },
    "dx.rule.lipid_cholesterol.note": {
        "en": "Cholesterol is above the published cut-point while triglycerides are not raised. ICD-10 calls this pure hypercholesterolaemia. A doctor confirms it on a repeat lipid profile and assesses your overall cardiovascular risk; a very high LDL can run in families.",
        "uk": "Холестерин вищий за опублікований поріг, а тригліцериди не підвищені. У МКХ-10 це чиста гіперхолестеринемія. Лікар підтверджує її повторною ліпідограмою та оцінює загальний серцево-судинний ризик; дуже високий ЛПНЩ буває спадковим.",
    },
    "dx.rule.lipid_triglycerides.note": {
        "en": "Triglycerides are high while cholesterol is not above its cut-point. ICD-10 calls this pure hyperglyceridaemia. A doctor confirms it on a repeat fasting sample and checks for diabetes, alcohol, excess weight and medicines as causes.",
        "uk": "Тригліцериди високі, а холестерин не перевищує свого порога. У МКХ-10 це чиста гіпергліцеридемія. Лікар підтверджує її повторним аналізом натще і перевіряє можливі причини: діабет, алкоголь, надмірну вагу, ліки.",
    },
    "dx.rule.glucose_intermediate.note": {
        "en": "Glucose or HbA1c is in the range between normal and diabetes (prediabetes). The Ukrainian classifier codes it as intermediate hyperglycaemia. A doctor confirms it with a repeat fasting glucose, HbA1c or a glucose tolerance test.",
        "uk": "Глюкоза або HbA1c перебуває в діапазоні між нормою та діабетом (предіабет). Український класифікатор кодує це як проміжну гіперглікемію. Лікар підтверджує її повторним аналізом глюкози натще, HbA1c або глюкозотолерантним тестом.",
    },
    "dx.rule.diabetes_range.note": {
        "en": "Glucose or HbA1c is in the range used to diagnose diabetes. One result is not a diagnosis: without symptoms it must be confirmed by a second test on another day. The type of diabetes is decided by a doctor.",
        "uk": "Глюкоза або HbA1c перебуває в діапазоні, за яким діагностують діабет. Один результат ще не діагноз: без симптомів його потрібно підтвердити другим аналізом в інший день. Тип діабету визначає лікар.",
    },
    "dx.rule.anaemia_iron.note": {
        "en": "Haemoglobin is in the anaemia range and ferritin shows empty iron stores. Together they point to iron deficiency anaemia. A doctor confirms it and looks for the cause of the iron loss, such as bleeding or poor absorption.",
        "uk": "Гемоглобін у діапазоні анемії, а феритин показує виснажені запаси заліза. Разом вони вказують на залізодефіцитну анемію. Лікар підтверджує її та шукає причину втрати заліза, наприклад кровотечу чи погане всмоктування.",
    },
    "dx.rule.iron_deficiency.note": {
        "en": "Ferritin shows empty iron stores while haemoglobin is not in the anaemia range. This is iron deficiency without anaemia. A doctor decides whether to treat it and looks for the cause.",
        "uk": "Феритин показує виснажені запаси заліза, а гемоглобін не в діапазоні анемії. Це дефіцит заліза без анемії. Лікар вирішує, чи потрібне лікування, і шукає причину.",
    },
    "dx.rule.anaemia_unspecified.note": {
        "en": "Haemoglobin is in the anaemia range and ferritin does not show iron deficiency, or was not measured. The kind of anaemia is not clear from these results. A doctor usually starts with ferritin, vitamin B12, folate and a blood film.",
        "uk": "Гемоглобін у діапазоні анемії, а феритин не показує дефіциту заліза або його не вимірювали. За цими результатами вид анемії не зрозумілий. Лікар зазвичай починає з феритину, вітаміну B12, фолату та мазка крові.",
    },
    "dx.rule.iron_overload.note": {
        "en": "Ferritin is above the WHO threshold for a possible risk of iron overload. Ferritin also rises with inflammation, liver disease and alcohol, so this is not yet iron overload. A doctor checks transferrin saturation and repeats the test.",
        "uk": "Феритин вищий за поріг ВООЗ, що вказує на можливий ризик перевантаження залізом. Феритин також зростає при запаленні, хворобах печінки та вживанні алкоголю, тому це ще не перевантаження залізом. Лікар перевіряє насичення трансферину і повторює аналіз.",
    },
    "dx.rule.hypothyroid.note": {
        "en": "TSH is above the reference interval, which is how an underactive thyroid usually shows first. A doctor confirms it with a repeat TSH together with free T4, and often thyroid antibodies.",
        "uk": "ТТГ вищий за референтний інтервал: саме так зазвичай уперше проявляється знижена функція щитоподібної залози. Лікар підтверджує це повторним ТТГ разом із вільним Т4, а часто й антитілами до щитоподібної залози.",
    },
    "dx.rule.thyrotoxicosis.note": {
        "en": "TSH is below the reference interval, which can mean an overactive thyroid. A doctor confirms it with a repeat TSH together with free T4 and free T3.",
        "uk": "ТТГ нижчий за референтний інтервал, що може означати надмірну функцію щитоподібної залози. Лікар підтверджує це повторним ТТГ разом із вільним Т4 і вільним Т3.",
    },
    "dx.rule.hyperuricaemia.note": {
        "en": "Uric acid is above the concentration at which urate crystals can form. Without joint attacks this is hyperuricaemia, not gout. A doctor decides whether anything needs treating and reviews diet, alcohol and medicines.",
        "uk": "Сечова кислота вища за концентрацію, за якої можуть утворюватися кристали уратів. Без нападів болю в суглобах це гіперурикемія, а не подагра. Лікар вирішує, чи потрібне лікування, і переглядає харчування, алкоголь та ліки.",
    },
    "dx.rule.vitamin_d.note": {
        "en": "25-hydroxyvitamin D is in the deficient range. A doctor confirms the deficiency and chooses the dose and length of treatment, usually with a follow-up test.",
        "uk": "25-гідроксивітамін D у діапазоні дефіциту. Лікар підтверджує дефіцит і обирає дозу та тривалість лікування, зазвичай із контрольним аналізом.",
    },
    "dx.rule.b12_deficiency.note": {
        "en": "Vitamin B12 is in the range consistent with deficiency. A doctor confirms it, sometimes with holotranscobalamin or methylmalonic acid, and looks for the cause: diet, stomach or bowel disease, medicines such as metformin.",
        "uk": "Вітамін B12 у діапазоні, що відповідає дефіциту. Лікар підтверджує його, інколи за голотранскобаламіном чи метилмалоновою кислотою, і шукає причину: харчування, хвороби шлунка чи кишківника, ліки, зокрема метформін.",
    },
    "dx.rule.folate_deficiency.note": {
        "en": "Serum folate is in the deficiency range. A doctor confirms it, checks vitamin B12 at the same time and looks for the cause: diet, alcohol, bowel disease or medicines.",
        "uk": "Фолат у сироватці в діапазоні дефіциту. Лікар підтверджує його, водночас перевіряє вітамін B12 і шукає причину: харчування, алкоголь, хвороби кишківника чи ліки.",
    },
    "dx.rule.hypertension.note": {
        "en": "The latest blood pressure reading is in the hypertension range of both the US and the European classification. One reading is not a diagnosis: hypertension is diagnosed from repeated or home measurements. Measure at home for a week and take the readings to a doctor.",
        "uk": "Останнє вимірювання артеріального тиску перебуває в діапазоні гіпертензії і за американською, і за європейською класифікацією. Одне вимірювання ще не діагноз: гіпертензію діагностують за повторними або домашніми вимірюваннями. Вимірюйте тиск удома протягом тижня і покажіть записи лікарю.",
    },
    "dx.rule.obesity.note": {
        "en": "Body mass index is in the range classified as obesity. BMI does not tell muscle from fat, so a doctor also looks at waist size and related results such as glucose, lipids and blood pressure.",
        "uk": "Індекс маси тіла перебуває в діапазоні, який класифікують як ожиріння. ІМТ не відрізняє м'язи від жиру, тому лікар також оцінює окружність талії та пов'язані результати: глюкозу, ліпіди, артеріальний тиск.",
    },
    "dx.rule.ckd.note": {
        "en": "Estimated kidney filtration (eGFR) is in the range of stage G3a or worse. Chronic kidney disease is diagnosed only when this lasts longer than three months. A doctor repeats creatinine and checks urine albumin.",
        "uk": "Розрахункова швидкість клубочкової фільтрації (рШКФ) відповідає стадії G3a або гіршій. Хронічну хворобу нирок діагностують лише тоді, коли це триває понад три місяці. Лікар повторює аналіз креатиніну та перевіряє альбумін у сечі.",
    },
    "dx.rule.transaminases.note": {
        "en": "The liver enzyme ALT is above the healthy range. The code only records the raised result; it does not name a cause. A doctor repeats the test and looks for fatty liver, alcohol, viral hepatitis and medicines.",
        "uk": "Печінковий фермент АЛТ вищий за здоровий діапазон. Цей код лише фіксує підвищений результат і не називає причини. Лікар повторює аналіз і шукає жирову хворобу печінки, вплив алкоголю, вірусний гепатит та ліки.",
    },
    "dx.rule.lvh.note": {
        "en": "The heart ultrasound gives a left ventricular mass index in the range of left ventricular hypertrophy: a thickened heart muscle. The most common cause is long-standing high blood pressure. A cardiologist interprets the whole study.",
        "uk": "За даними УЗД серця індекс маси міокарда лівого шлуночка перебуває в діапазоні гіпертрофії лівого шлуночка, тобто потовщення серцевого м'яза. Найчастіша причина: тривалий підвищений артеріальний тиск. Усе дослідження оцінює кардіолог.",
    },
    "dx.rule.thrombocytopenia.note": {
        "en": "The platelet count is below the threshold used to diagnose thrombocytopenia. A doctor repeats the count, checks a blood film to rule out clumping in the tube, and looks for the cause.",
        "uk": "Кількість тромбоцитів нижча за поріг, за яким діагностують тромбоцитопенію. Лікар повторює аналіз, перевіряє мазок крові, щоб виключити склеювання тромбоцитів у пробірці, і шукає причину.",
    },
    "dx.rule.eosinophilia.note": {
        "en": "The eosinophil count is above the upper limit used in Ukraine, the US and Europe. Common causes are allergy, asthma, eczema, parasites and medicines. A doctor repeats the count and looks for the cause if it persists.",
        "uk": "Кількість еозинофілів вища за верхню межу, яку застосовують в Україні, США та Європі. Часті причини: алергія, астма, екзема, паразити й ліки. Лікар повторює аналіз і шукає причину, якщо підвищення зберігається.",
    },
    "dx.rule.hyponatraemia.note": {
        "en": "Sodium is below the reference range. Mild cases are often caused by medicines or drinking a lot of water. A doctor repeats the test and reviews medicines; a low sodium with confusion, vomiting or seizures needs urgent care.",
        "uk": "Натрій нижчий за референтний діапазон. Легкі випадки часто спричинені ліками або вживанням великої кількості води. Лікар повторює аналіз і переглядає ліки; низький натрій разом зі сплутаною свідомістю, блюванням чи судомами потребує невідкладної допомоги.",
    },
    "dx.rule.hypokalaemia.note": {
        "en": "Potassium is below the normal range. Diuretics, vomiting and diarrhoea are the usual causes. A doctor repeats the test and reviews medicines; a low potassium with palpitations or muscle weakness needs prompt care.",
        "uk": "Калій нижчий за нормальний діапазон. Звичні причини: сечогінні засоби, блювання та діарея. Лікар повторює аналіз і переглядає ліки; низький калій разом із серцебиттям чи м'язовою слабкістю потребує швидкої допомоги.",
    },
    "dx.rule.hyperkalaemia.note": {
        "en": "Potassium is in the hyperkalaemia range. A sample that was shaken or waited too long gives a falsely high result, so the test is repeated first. A doctor reviews kidney function and medicines; a confirmed high potassium needs prompt care.",
        "uk": "Калій у діапазоні гіперкаліємії. Якщо пробу струшували або вона довго чекала на дослідження, результат буває хибно високим, тому аналіз спершу повторюють. Лікар перевіряє функцію нирок і ліки; підтверджений високий калій потребує швидкої допомоги.",
    },
}
