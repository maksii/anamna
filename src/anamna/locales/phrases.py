from __future__ import annotations

from ..config import local_overrides

# Exact English phrases stored in code/DB → Ukrainian at display time.
PHRASES: dict[str, str] = {
    "Clinical consultation": "Консультація лікаря",
    "Medical images": "Медичні знімки",
    "Radiology report": "Висновок променевої діагностики",
    "ECG report": "Висновок ЕКГ",
    # Health areas
    "Blood health": "Кров і кровотворення",
    "Blood": "Кров",
    "Blood counts, clotting and iron stores": "Загальний аналіз крові, згортання й запаси заліза",
    "Heart & circulation": "Серце та кровообіг",
    "Heart": "Серце",
    "Blood pressure, cholesterol, heart imaging and blood flow": "Артеріальний тиск, холестерин, обстеження серця й судин",
    "Glucose & metabolism": "Глюкоза й обмін речовин",
    "Metabolism": "Обмін речовин",
    "Glucose control, proteins and metabolic markers": "Рівень глюкози, білки та інші показники обміну речовин",
    "Liver & pancreas": "Печінка й підшлункова залоза",
    "Liver": "Печінка",
    "Liver enzymes, bilirubin and pancreatic markers": "Печінкові ферменти, білірубін і показники підшлункової залози",
    "Kidneys & urinary": "Нирки й сечовидільна система",
    "Kidneys": "Нирки",
    "Kidney function and urine testing": "Функція нирок і аналізи сечі",
    "Thyroid & hormones": "Щитоподібна залоза та гормони",
    "Hormones": "Гормони",
    "Thyroid and endocrine measurements": "Гормони щитоподібної залози та інші ендокринні показники",
    "Vitamins & minerals": "Вітаміни та мінерали",
    "Nutrition": "Харчування",
    "Vitamins, minerals and electrolytes": "Вітаміни, мінерали та електроліти",
    "Immunity & inflammation": "Імунітет і запалення",
    "Immunity": "Імунітет",
    "Inflammatory and immune-system markers": "Показники запалення й імунітету",
    "Bones & spine": "Кістки та хребет",
    "Cervical, thoracic and lumbar imaging with related bone markers": "Обстеження шийного, грудного й поперекового відділів хребта та показники кісткової тканини",
    "Joints & soft tissue": "Суглоби та м’які тканини",
    "Joints": "Суглоби",
    "Joint, tendon and soft-tissue imaging with related inflammation and urate results": "Обстеження суглобів, сухожиль і м’яких тканин, показники запалення й сечової кислоти",
    "Lungs & chest": "Легені та грудна клітка",
    "Lungs": "Легені",
    "Chest imaging and respiratory evidence": "Обстеження органів грудної клітки та дихання",
    "Stomach & intestines": "Шлунок і кишечник",
    "Stomach": "Шлунок",
    "Stomach and intestinal pathology, procedures and related testing": "Хвороби шлунка й кишечника, процедури та відповідні аналізи",
    "Allergy": "Алергія",
    "Allergen-specific and total IgE testing": "Загальний і специфічні IgE до алергенів",
    "Infection & microbiology": "Інфекції та мікробіологія",
    "Infection": "Інфекції",
    "Cultures, organisms and infection markers": "Посіви, збудники й показники інфекцій",
    "ENT & sinuses": "ЛОР-органи й пазухи",
    "ENT": "ЛОР",
    "Ear, nose, throat and sinus visits and imaging": "Консультації й обстеження вуха, носа, горла та пазух",
    "Teeth & mouth": "Зуби й ротова порожнина",
    "Teeth": "Зуби",
    "Teeth, gums and jaw: dental visits, and visits for tooth or jaw pain that end in a referral to a dentist":
        "Зуби, ясна й щелепа: візити до стоматолога, а також звернення з болем у зубі чи щелепі, після яких "
        "направляють до стоматолога",
    "Skin": "Шкіра",
    "Cardiology consultation": "Консультація кардіолога",
    "Dermatology consultation": "Консультація дерматолога",
    "Dermatology consultations and skin findings": "Консультації дерматолога й зміни на шкірі",
    "Brain & nervous system": "Головний мозок і нервова система",
    "Brain": "Мозок",
    "Brain recordings such as the EEG (electroencephalogram, a recording of the brain's electrical activity), and visits for headaches and other nervous-system complaints": (
        "Записи роботи мозку, як-от ЕЕГ (електроенцефалограма, запис електричної активності головного мозку), і консультації з приводу головного болю та інших скарг нервової системи"
    ),
    "Electroencephalogram (EEG)": "Електроенцефалограма (ЕЕГ)",
    "Other results": "Інші результати",

    # Categories
    "Blood count": "Загальний аналіз крові",
    "Clotting": "Згортання крові",
    "Iron": "Залізо",
    "Cholesterol & lipids": "Холестерин і ліпіди",
    "Blood pressure & circulation": "Артеріальний тиск і кровообіг",
    "Glucose control": "Вуглеводний обмін",
    "Blood chemistry": "Біохімія крові",
    "Pancreas": "Підшлункова залоза",
    "Tumour markers": "Онкомаркери",
    "Kidney function": "Функція нирок",
    "Urinalysis": "Аналіз сечі",
    "Thyroid": "Щитоподібна залоза",
    "Vitamins": "Вітаміни",
    "Minerals & electrolytes": "Мінерали та електроліти",
    "Immunology": "Імунологія",
    "Immunogenetics": "Імуногенетика",
    "Inflammation": "Запалення",
    "Digestive testing": "Аналізи травної системи",
    "Stool analysis": "Аналіз калу",
    "Microbiology": "Мікробіологія",
    "Other extracted result": "Інший зчитаний результат",
    "Other": "Інше",

    # Connected-device metrics and areas
    "Device data": "Дані пристроїв",
    "Body composition": "Склад тіла",
    "Daily activity": "Щоденна активність",
    "Fitness": "Фізична форма",
    "Mobility": "Рухливість",
    "Sleep": "Сон",
    "Recovery and vitals": "Відновлення та показники життєдіяльності",
    "Recovery & vitals": "Відновлення та показники життєдіяльності",
    "Environment and hearing": "Довкілля та слух",
    "Environment & hearing": "Довкілля та слух",
    "Activity & fitness": "Активність і фізична форма",
    "Mobility & gait": "Рухливість і хода",
    "Sleep & recovery": "Сон і відновлення",
    "Hearing & environment": "Слух і довкілля",
    "Active energy": "Активна енергія",
    "Awake during sleep": "Неспання під час сну",
    "Blood oxygen saturation": "Насичення крові киснем",
    "Body fat": "Частка жиру в тілі",
    "Body mass index": "Індекс маси тіла",
    "Body weight": "Маса тіла",
    "Body height": "Зріст",
    "Body water": "Частка води в тілі",
    "Bone mass": "Кісткова маса",
    "Muscle mass": "М’язова маса",
    "Cardio fitness (VO₂ max)": "Кардіовитривалість (VO₂ max)",
    "Core sleep": "Основний сон",
    "Cycling distance": "Відстань на велосипеді",
    "Daily heart rate": "Частота серцебиття за день",
    "ECG heart rate": "Частота серцебиття на ЕКГ",
    "Electrocardiogram": "Електрокардіограма",
    # Every determination a Kardia 6L can print, per AliveCor's own product
    # documentation.  The parser stores the printed English verbatim, so any of
    # these can reach a Ukrainian reader; only the first one ever had a
    # translation, and the other six would have appeared in English.
    "Normal Sinus Rhythm": "Нормальний синусовий ритм",
    "Atrial Fibrillation": "Фібриляція передсердь",
    "Bradycardia": "Брадикардія",
    "Tachycardia": "Тахікардія",
    "Sinus Rhythm with Premature Ventricular Contractions (PVCs)":
        "Синусовий ритм із шлуночковими екстрасистолами (ШЕС)",
    "Sinus Rhythm with Supraventricular Ectopy (SVE)":
        "Синусовий ритм із надшлуночковою ектопією (НШЕ)",
    # Apple Watch ECG app classifications (the CSV `Classification` field).
    "Sinus Rhythm": "Синусовий ритм",
    "Inconclusive": "Невизначений результат",
    "Inconclusive Low Heart Rate": "Невизначений результат: низька частота серцебиття",
    "Inconclusive High Heart Rate": "Невизначений результат: висока частота серцебиття",
    "Inconclusive Poor Reading": "Невизначений результат: низька якість запису",
    "Inconclusive Other": "Невизначений результат: інша причина",
    "Heart Rate Over 150": "Частота серцебиття понад 150",
    "Heart Rate Under 50": "Частота серцебиття нижче 50",
    "High Heart Rate": "Висока частота серцебиття",
    "Low Heart Rate": "Низька частота серцебиття",
    "Poor Reading": "Низька якість запису",
    "Unrecognized": "Не розпізнано",
    "Not Set": "Не визначено",
    # Kardia determinations beyond the first seven.
    "Possible Atrial Fibrillation": "Можлива фібриляція передсердь",
    "Unreadable": "Запис непридатний для аналізу",
    "No Analysis": "Без аналізу",
    "Sinus Rhythm with Wide QRS": "Синусовий ритм із широким комплексом QRS",
    "Sinus Rhythm with Premature Ventricular Contractions": "Синусовий ритм із шлуночковими екстрасистолами",
    "Sinus Rhythm with Supraventricular Ectopy": "Синусовий ритм із надшлуночковою ектопією",
    "Heart Rate Too Fast": "Надто висока частота серцебиття",
    "Heart Rate Too Slow": "Надто низька частота серцебиття",
    # Device event notifications (DEVICE_EVENTS in devices/apple_health.py).
    "High heart-rate notification": "Сповіщення про високу частоту серцебиття",
    "Low heart-rate notification": "Сповіщення про низьку частоту серцебиття",
    "Irregular rhythm notification": "Сповіщення про нерегулярний ритм",
    "Low cardio-fitness notification": "Сповіщення про низьку кардіовитривалість",
    # Workout types, normalised by devices/workout_reconcile.py:workout_label.
    "Walking": "Ходьба",
    "Running": "Біг",
    "Cycling": "Їзда на велосипеді",
    "Swimming": "Плавання",
    "Hiking": "Піший похід",
    "Yoga": "Йога",
    "Pilates": "Пілатес",
    "Elliptical": "Еліптичний тренажер",
    "Rowing": "Веслування",
    "Stair Climbing": "Підйом сходами",
    "Dance": "Танці",
    "Cooldown": "Заминка",
    "Core Training": "Тренування м’язів кору",
    "Cardio Training": "Кардіотренування",
    "Strength Training": "Силове тренування",
    "Traditional Strength Training": "Традиційне силове тренування",
    "Functional Strength Training": "Функціональне силове тренування",
    "High Intensity Interval Training": "Високоінтенсивне інтервальне тренування",
    "Mind and Body": "Розум і тіло",
    "Trail Running": "Біг пересіченою місцевістю",
    "Treadmill Running": "Біг на доріжці",
    "Indoor Cycling": "Велотренажер",
    "Mountain Biking": "Гірський велосипед",
    "Lap Swimming": "Плавання в басейні",
    "Open Water Swimming": "Плавання у відкритій воді",
    "Stretching": "Розтяжка",
    "Tennis": "Теніс",
    "Golf": "Гольф",
    "Soccer": "Футбол",
    "Basketball": "Баскетбол",
    "Boxing": "Бокс",
    "Skiing": "Катання на лижах",
    "Snowboarding": "Сноуборд",
    "Jump Rope": "Скакалка",
    "Kickboxing": "Кікбоксинг",
    "Badminton": "Бадмінтон",
    "Table Tennis": "Настільний теніс",
    "Volleyball": "Волейбол",
    "Skating": "Катання на ковзанах",
    "Climbing": "Скелелазіння",
    "Mixed Cardio": "Змішане кардіо",
    "Flexibility": "Гнучкість",
    "Unclassified": "Не класифіковано",
    "Kardia 6-lead ECG recording": "Запис ЕКГ Kardia у 6 відведеннях",
    "Daily steps": "Кроки за день",
    "Deep sleep": "Глибокий сон",
    "Environmental sound exposure": "Рівень шуму довкілля",
    "Exercise time": "Час тренувань",
    "Flights climbed": "Пройдено поверхів",
    "Headphone sound exposure": "Рівень звуку в навушниках",
    "Heart rate variability (SDNN)": "Варіабельність серцевого ритму (SDNN)",
    "Lean body mass": "Безжирова маса тіла",
    "One-minute heart-rate recovery": "Відновлення пульсу за хвилину",
    "Physical effort": "Фізичне навантаження",
    "REM sleep": "Швидкий сон (REM)",
    "Respiratory rate": "Частота дихання",
    "Resting energy": "Енергія в спокої",
    "Resting heart rate": "Пульс у спокої",
    "Lowest sleeping heart rate": "Найнижчий пульс уві сні",
    "Average sleeping heart rate": "Середній пульс уві сні",
    "Heart rate variability (RMSSD)": "Варіабельність серцевого ритму (RMSSD)",
    "Active minutes": "Хвилини активності",
    "Sedentary time": "Час без руху",
    "Light activity": "Легка активність",
    "Total energy expenditure": "Загальні енерговитрати",
    "Daily elevation": "Набір висоти за день",
    "Sleep interruptions": "Переривання сну",
    "Naps": "Денний сон",
    "Nap duration": "Тривалість денного сну",
    "Stress score": "Оцінка стресу",
    "Resilience score": "Оцінка стійкості",
    "Body Battery score": "Оцінка Body Battery",
    "Strain score": "Оцінка навантаження",
    "Health recovery score": "Оцінка відновлення здоров’я",
    "Sleep score": "Оцінка сну",
    "Readiness score": "Оцінка готовності",
    "Recovery score": "Оцінка відновлення",
    "Menstrual cycle": "Менструальний цикл",
    "Oura score": "Оцінка Oura",
    "Activity score": "Оцінка активності",
    "Temperature deviation": "Відхилення температури",
    "Sleep efficiency": "Ефективність сну",
    "Breathing disturbance index": "Індекс порушень дихання",
    "High stress time": "Час високого стресу",
    "High recovery time": "Час глибокого відновлення",
    "Cardiovascular age": "Серцево-судинний вік",
    "Pulse wave velocity": "Швидкість пульсової хвилі",
    "Moderate activity": "Помірна активність",
    "Vigorous activity": "Інтенсивна активність",
    "Average stress level": "Середній рівень стресу",
    "Body Battery high": "Максимум Body Battery",
    "Body Battery low": "Мінімум Body Battery",
    "Fitness age": "Фітнес-вік",
    "Garmin Move IQ": "Garmin Move IQ (автоматично визначена активність)",
    "Systolic blood pressure": "Систолічний артеріальний тиск",
    "Diastolic blood pressure": "Діастолічний артеріальний тиск",
    "Pulse during blood-pressure reading": "Пульс під час вимірювання тиску",
    "Six-minute walk distance": "Відстань у тесті 6-хвилинної ходьби",
    "Sleeping breathing disturbances": "Порушення дихання уві сні",
    "Sleeping wrist temperature": "Температура зап’ястя уві сні",
    "Stand time": "Час стоячи",
    "Stand hours": "Години стоячи",
    "Swimming distance": "Дистанція плавання",
    "Swimming strokes": "Кількість гребків",
    "Stair ascent speed": "Швидкість підйому сходами",
    "Stair descent speed": "Швидкість спуску сходами",
    "Environmental sound reduction": "Зниження шуму довкілля",
    "Mindful session": "Сеанс усвідомленості",
    "Environmental audio exposure event": "Епізод гучного шуму довкілля",
    "Headphone audio exposure event": "Епізод гучного звуку в навушниках",
    "Audio exposure event": "Епізод гучного звуку",
    "Time asleep": "Тривалість сну",
    "Time in bed": "Час у ліжку",
    "Time in daylight": "Час на денному світлі",
    "Waist circumference": "Окружність талії",
    "Walking and running distance": "Відстань пішки й бігом",
    "Walking asymmetry": "Асиметрія ходьби",
    "Walking double-support time": "Час подвійної опори під час ходи",
    "Walking heart rate": "Пульс під час ходьби",
    "Walking speed": "Швидкість ходьби",
    "Walking steadiness": "Стабільність ходи",
    "Walking step length": "Довжина кроку",

    # Status labels
    "Within original range": "У межах норми лабораторії",
    "Equivocal in original report": "Пограничний за даними лабораторії",
    "Positive in original report": "Позитивний за даними лабораторії",
    "Above original range": "Вище норми лабораторії",
    "Below original range": "Нижче норми лабораторії",
    "Positive": "Позитивний",
    "No concern noted": "Зауважень немає",
    "Review finding": "Потребує уваги",
    "Information": "Інформація",
    "Verified": "Звірено",
    "Corrected": "Виправлено",
    "Needs verification": "Потребує звірки",
    "Set aside": "Відхилено",
    "No comparison": "Немає норми для порівняння",

    # Clinical types / enums
    "laboratory": "Лабораторні аналізи",
    "radiology_mri": "МРТ",
    "radiology_xray": "Рентген",
    "ultrasound": "УЗД",
    "pathology": "Гістологія",
    "diagnostic_image": "Діагностичні знімки",
    "compound_bundle": "Пакет документів",
    "consultation": "Консультація",
    "allergy": "Алергодіагностика",
    "microbiology": "Мікробіологія",
    "electrocardiogram": "ЕКГ",
    # The two clinical types the classifier can emit that nothing here named:
    # the documents filter and every card printed the bare English key to a
    # Ukrainian reader, because `enum_label` falls back to the value itself.
    "administrative": "Адміністративний документ",
    "clinical_report": "Медичний висновок",
    "immunization_record": "Карта щеплень",
    "questionnaire": "Опитувальник",
    "Questionnaire": "Опитувальник",
    "Vaccination card": "Карта профілактичних щеплень",
    "native_text": "Текстовий шар PDF",
    # The extraction methods and strategies that had no Ukrainian name. A
    # scanned page reaches the document page as `page_image_ocr`, which without
    # an entry here prints the bare English key beside every page of every scan.
    "page_image_ocr": "Розпізнавання тексту зі зображення сторінки",
    "scanned_page_ocr": "Розпізнавання тексту сканів",
    "native_pdf_text": "Текстовий шар PDF",
    "native_pdf_text+embedded_image_ocr": "Текстовий шар PDF і розпізнавання зображень",
    "embedded_image_ocr": "Розпізнавання тексту вбудованих зображень",
    "tesseract_ukr_eng": "Розпізнавання тексту (українська й англійська)",
    "human_entered": "Введено вручну",
    "visual_review_required": "Потребує візуальної звірки",
    "attachment_only": "Лише вкладення",
    "supporting_record": "Супровідний документ",
    # The two compound extraction strategies were the only ones with no entry
    # here, so an English label reached every Ukrainian document and review
    # page whose document used one.
    "native_text_plus_embedded_image_ocr": "Текстовий шар і розпізнавання зображень",
    "native_text_plus_visual_attachments": "Текстовий шар і вкладення",
    "lab_api": "Онлайн-результати лабораторії (без PDF)",
    "ocr_required": "Потрібне розпізнавання тексту",
    "page_segmented_native": "Посторінковий текстовий шар",
    "page_segmented_ocr": "Посторінкове розпізнавання тексту",
    "per-page": "Посторінково",
    "not_reviewed": "Не звірено",
    "verified": "Звірено",
    "extracted": "Зчитано",
    "corrected": "Виправлено",
    "open": "Відкрито",
    "resolved": "Опрацьовано",
    "needs_correction": "Потребує виправлення",
    "human_corrected": "Виправлено вручну",

    # Value translations (English display → Ukrainian)
    "Not detected": "Не виявлено",
    "Negative": "Негативний",
    "Susceptible": "Чутливий",
    "Intermediate susceptibility": "Помірночутливий",
    "Resistant": "Резистентний",
    "Normal": "Норма",
    "High-normal": "Високий нормальний",
    "Grade 1": "Ступінь 1",
    "Grade 2": "Ступінь 2",
    "Clear": "Прозора",
    "Cloudy": "Каламутна",
    "Yellow": "Жовтий",
    "Amber": "Бурштиновий",
    "Trace": "Сліди",
    "Not supplied": "Не вказано",

    # Document / classifier titles
    "Diagnostic image": "Діагностичний знімок",
    "Chest radiograph - frontal view": "Рентгенограма органів грудної клітки, пряма проєкція",
    "ENT CT screening image set": "Знімки скринінгової КТ ЛОР-органів",
    "Compound medical document bundle": "Пакет медичних документів",
    "Kardia ECG recording": "Запис ЕКГ Kardia",
    # Classifier notes stored on `documents.notes`.
    "Image-only chest radiograph; OCR is limited to acquisition metadata.": (
        "Рентгенограма грудної клітки лише у вигляді зображення; розпізнано тільки службові дані знімка."
    ),
    "Image attachment with CT views; no narrative interpretation is present.": (
        "Вкладення із зображеннями КТ; письмового опису немає."
    ),
    "Order cover retained for provenance; the result values are stored in the linked attachment export.": (
        "Титульну сторінку замовлення збережено як підтвердження походження даних; значення результатів зберігаються в пов’язаному експортованому вкладенні."
    ),
    "This cover export points to a separate PDF attachment that contains the result values.": (
        "Цей титульний файл посилається на окремий PDF зі значеннями результатів."
    ),
    "The export identifies the ordered test but contains no result value.": (
        "У файлі вказано замовлений аналіз, але немає його результату."
    ),
    "Unknown vendor": "Невідомий заклад",
    "Unknown provider": "Невідомий заклад",
    "Multiple vendors": "Кілька закладів",
    "Physical PDF contains multiple logical report sections; dates and vendors are stored per report.": (
        "Один PDF-файл містить кілька окремих документів; дату й заклад збережено для кожного з них."
    ),

    # Review reasons
    "Confirm this exact duplicate should remain linked to the original document.": (
        "Підтвердьте, що цю точну копію слід залишити прив’язаною до оригіналу."
    ),
    "The order is present but the export contains no result value.": (
        "Замовлення є, але у файлі немає результату."
    ),
    "Review image/visual evidence; OCR is not accepted as a clinical fact automatically.": (
        "Звірте зображення: автоматично розпізнаний текст не стає клінічним фактом без перевірки людиною."
    ),
    "Review the narrative or visual report; no structured scalar observation was inferred automatically.": (
        "Перегляньте текстовий опис або зображення: програма не зчитала з них жодного числового значення."
    ),
    "Review the narrative or visual findings against page evidence before marking trusted.": (
        "Звірте текстові й візуальні знахідки з оригіналом, перш ніж позначити їх звіреними."
    ),
    # The sentence above covers a report with no numbers in it. This one covers
    # a report the parser does read and got nothing from, which is a different
    # thing to be told and a different thing to do about it.
    "Extraction found no values on a report of a kind the parser does read; "
    "check the pages for results it missed.": (
        "Програма не зчитала жодного значення, хоча документи цього типу вона читає. Перегляньте сторінки: можливо, деякі результати пропущено."
    ),
    "ocr_image_metadata": "Розпізнаний текст і метадані зображення",
    "visual_or_vector_review": "Звірка зображення або векторної графіки",
    "result_not_present": "Результату немає",

    # Findings titles
    "Small-intestinal and polyp pathology": "Патологія тонкої кишки та поліпів",
    "Neck-vessel ultrasound": "УЗД судин шиї",
    "Echocardiogram": "Ехокардіографія",
    "Kardia 6-lead ECG": "ЕКГ Kardia у 6 відведеннях",
    "Abdominal ultrasound": "УЗД органів черевної порожнини",
    "Liver ultrasound": "УЗД печінки",
    "Kidney ultrasound": "УЗД нирок",
    "Cervical spine MRI": "МРТ шийного відділу хребта",
    "Thoracic spine MRI": "МРТ грудного відділу хребта",
    "Thoracic and lumbar spine MRI": "МРТ грудного та поперекового відділів хребта",
    "Lumbar spine MRI": "МРТ поперекового відділу хребта",
    "Lumbar spine radiograph": "Рентгенограма поперекового відділу хребта",
    "Left elbow MRI": "МРТ лівого ліктьового суглоба",
    "Right elbow MRI": "МРТ правого ліктьового суглоба",
    "Left knee MRI": "МРТ лівого колінного суглоба",
    "Right knee MRI": "МРТ правого колінного суглоба",
    "Soft-tissue ultrasound": "УЗД м’яких тканин",
    "Breast ultrasound": "УЗД молочних залоз",
    "Pelvic ultrasound": "УЗД органів малого таза",
    "Colposcopy": "Кольпоскопія",
    "Upper endoscopy (gastroscopy)": "Езофагогастродуоденоскопія (гастроскопія)",
    "H. pylori breath test": "Дихальний тест на H. pylori",
    "Hydrogen breath test": "Водневий дихальний тест",
    "Gynaecology consultation": "Консультація гінеколога",
    "Psychiatry consultation": "Консультація психіатра",
    "Mental health": "Психічне здоров’я",
    "Psychiatric and psychological consultations, questionnaires and diagnoses": "Консультації психіатра і психолога, опитувальники та діагнози",
    "Reproductive & breast health": "Репродуктивне здоров’я і молочні залози",
    "Reproductive": "Репродуктивне",
    "Pelvic and breast ultrasound, colposcopy and gynaecological findings": "УЗД органів малого таза і молочних залоз, кольпоскопія та гінекологічні висновки",
    "Breath tests": "Дихальні тести",
    "Radiation from imaging": "Опромінення під час обстежень",
    "Gynaecological ultrasound": "Гінекологічне УЗД",
    "EEG (brain electrical activity)": "ЕЕГ (електрична активність мозку)",
    "Salivary-gland and cervical-node ultrasound": "УЗД слинних залоз і шийних лімфовузлів",
    "Thyroid ultrasound": "УЗД щитоподібної залози",
    "Orthopedic consultation": "Консультація ортопеда",
    "Neurology consultation": "Консультація невролога",
    "Chest radiograph": "Рентгенограма органів грудної клітки",
    "ENT CT image set": "Знімки КТ ЛОР-органів",
    "Narrative report": "Текстовий висновок",
    "Carotid and vertebral artery ultrasound": "УЗД сонних і хребтових артерій",
    "Family doctor consultation": "Консультація сімейного лікаря",
    "Intestinal biopsy (histology)": "Біопсія кишечника (гістологія)",
    "Spine radiograph": "Рентгенограма хребта",
    "Knee MRI": "МРТ колінного суглоба",
    "Elbow MRI": "МРТ ліктьового суглоба",
    "Allergy consultation": "Консультація алерголога",
    "Gastroenterology consultation": "Консультація гастроентеролога",
    "Endocrinology consultation": "Консультація ендокринолога",
    "General practitioner consultation": "Консультація терапевта",
    "Dental consultation": "Консультація стоматолога",
    "ENT consultation": "Консультація отоларинголога",
    "Rheumatology consultation": "Консультація ревматолога",
    "Endoscopy": "Ендоскопія",
    "Pre-operative anaesthesia assessment": "Передопераційний огляд анестезіолога",
    "Gastrointestinal tract ultrasound": "УЗД шлунково-кишкового тракту",
    "Upper GI endoscopy (EGD)": "Езофагогастродуоденоскопія (ЕФГДС)",
    "Breath test for small-intestinal bacterial overgrowth": "Дихальний тест на надмірний бактерійний ріст у тонкій кишці",

    # Findings summaries
    "The pathology report describes small-intestinal mucosal changes consistent with chronic inactive ileitis and polypectomy fragments consistent with serrated adenoma; a hyperplastic polyp is not excluded. Clinical correlation was requested.": (
        "За висновком гістологічного дослідження, зміни слизової тонкої кишки відповідають хронічному неактивному ілеїту, а фрагменти після поліпектомії відповідають зубчастій аденомі; гіперпластичний поліп не виключено. Патолог рекомендує зіставити результат із клінічною картиною."
    ),
    "No hemodynamic disturbance was identified in the carotid or vertebral arteries at the examination.": (
        "Гемодинамічних порушень у сонних і хребтових артеріях під час обстеження не виявлено."
    ),
    "Cardiac chamber size, contractility and valve function were described as preserved; no pulmonary hypertension or pericardial fluid was identified.": (
        "За описом, розміри камер серця, скоротливість і функція клапанів збережені; легеневої гіпертензії та рідини в перикарді не виявлено."
    ),
    "The Kardia algorithm labelled this 30-second six-lead recording as normal sinus rhythm; the source notes that the advanced determination is based on Lead I.": (
        "Алгоритм Kardia визначив цей 30-секундний запис у 6 відведеннях як нормальний синусовий ритм; у джерелі зазначено, що розширена оцінка ґрунтується на відведенні I."
    ),
    "Ultrasound signs of diffuse changes in the liver and pancreas were reported.": (
        "На УЗД описано ознаки дифузних змін печінки та підшлункової залози."
    ),
    "Ultrasound signs described fatty-type diffuse liver change, liver enlargement and a moderate degree of cholestasis.": (
        "На УЗД описано дифузні зміни печінки за типом жирової дистрофії, збільшення печінки й помірний холестаз."
    ),
    "Minor salt deposits in the kidneys were described without impaired urinary flow.": (
        "Описано незначні сольові відкладення в нирках без порушення відтоку сечі."
    ),
    "Early degenerative changes and straightening of the normal cervical lordosis were reported.": (
        "Описано початкові дегенеративні зміни та випрямлення фізіологічного шийного лордозу."
    ),
    "Moderate degenerative changes, mild right-sided thoracic curvature, a Th11-Th12 disc extrusion, and Th3-Th4 and Th7-Th8 disc protrusions were reported.": (
        "Описано помірні дегенеративні зміни, незначне правобічне викривлення в грудному відділі, екструзію диска Th11-Th12 та протрузії дисків Th3-Th4 і Th7-Th8."
    ),
    "Degenerative thoracic and lumbar changes were reported with multiple disc protrusions, an L5-S1 subligamentous herniation, right-sided disc-radicular conflict, and S-shaped thoracolumbar scoliosis.": (
        "Описано дегенеративні зміни грудного й поперекового відділів із множинними протрузіями дисків, сублігаментозною грижею L5-S1, правобічним дискорадикулярним конфліктом і S-подібним грудо-поперековим сколіозом."
    ),
    "Moderate degenerative changes, mild left-sided lumbar curvature, a transitional L6 vertebra, and an L5-L6 disc protrusion were reported.": (
        "Описано помірні дегенеративні зміни, легке лівобічне викривлення поперекового відділу хребта, перехідний хребець L6 і протрузію диска L5-L6."
    ),
    "Degenerative changes described as osteochondrosis at L2-S1 were reported.": (
        "Описано дегенеративні зміни на рівні L2-S1 у вигляді остеохондрозу."
    ),
    "MRI signs of triceps tendinopathy were reported.": (
        "Описано МРТ-ознаки тендинопатії триголового м’яза плеча."
    ),
    "ACL ligament change, minor medial meniscus change, a Baker cyst, patella alta and grade I patellar chondromalacia were reported.": (
        "Описано зміни ПХЗ, незначні зміни медіального меніска, кісту Бейкера, високе стояння надколінка (patella alta) і хондромаляцію надколінка I ступеня."
    ),
    "Popliteus strain, patellar-ligament and ACL changes, minor medial meniscus change, mild synovitis, patella alta and grade I patellar chondromalacia were reported.": (
        "Описано розтягнення підколінного м’яза, зміни власної зв’язки надколінка та ПХЗ, незначні зміни медіального меніска, легкий синовіт, високе стояння надколінка (patella alta) і хондромаляцію надколінка I ступеня."
    ),
    "Lipomas of the back were reported; interval observation was recommended.": (
        "Описано ліпоми спини; рекомендовано динамічне спостереження."
    ),
    "Lipomas of the left arm were reported; interval observation was recommended.": (
        "Описано ліпоми лівої руки; рекомендовано динамічне спостереження."
    ),
    "Lipomas of the soft tissue were reported; interval observation was recommended.": (
        "Описано ліпоми м’яких тканин; рекомендовано динамічне спостереження."
    ),
    "Inflammatory change of the right parotid gland and marked right cervical lymphadenopathy were reported; an infectious-disease consultation was recommended.": (
        "Описано запальні зміни правої привушної залози та виражену шийну лімфаденопатію справа; рекомендовано консультацію інфекціоніста."
    ),
    "Small colloid nodules were described in the right thyroid lobe (TI-RADS 2 on the right and TI-RADS 1 on the left); endocrinology review and repeat ultrasound in 12 months were recommended.": (
        "Описано невеликі колоїдні вузли в правій частці щитоподібної залози (TI-RADS 2 справа, TI-RADS 1 зліва); рекомендовано консультацію ендокринолога й повторне УЗД через 12 місяців."
    ),
    "The preliminary assessment recorded right plantar fasciitis and arthritis, with reactive arthritis and hyperuricemia considered; laboratory and imaging follow-up was recommended.": (
        "За попередньою оцінкою: плантарний фасциїт і артрит правої стопи, під питанням реактивний артрит і гіперурикемія; рекомендовано контрольні аналізи та візуалізаційне обстеження."
    ),
    "The preliminary assessment recorded an exacerbation of vertebrogenic thoracic and lumbosacral pain; sacroiliitis, spondyloarthritis and lumbar-segment instability were considered for further evaluation.": (
        "За попередньою оцінкою: загострення вертеброгенної торакалгії та люмбосакралгії; для подальшого обстеження розглядають сакроілеїт, спондилоартрит і нестабільність поперекового сегмента."
    ),
    "Chest radiograph images are available, but the source contains no written radiology interpretation.": (
        "Є знімки рентгенографії грудної клітки, але письмового висновку рентгенолога в джерелі немає."
    ),
    "ENT CT screening images are available, but the source contains no written radiology interpretation.": (
        "Є знімки скринінгової КТ ЛОР-органів, але письмового висновку рентгенолога в джерелі немає."
    ),
    "A written conclusion is available in the source document; no automatic English clinical summary was asserted.": (
        "Письмовий висновок є в документі-джерелі; автоматичного клінічного підсумку програма не складала."
    ),
    "No written conclusion in the source.": "У джерелі немає письмового висновку.",

    # Reference sets / rules
    "Standards of Care in Diabetes - diagnosis and classification": (
        "Стандарти медичної допомоги при цукровому діабеті: діагностика та класифікація"
    ),
    "American Diabetes Association": "Американська діабетична асоціація",
    "International clinical guidance": "Міжнародні клінічні настанови",
    "Diagnostic decision limits, not a healthy-population laboratory reference interval.": (
        "Діагностичні пороги для клінічних рішень, а не лабораторний референтний інтервал для здорових людей."
    ),
    "normal": "норма",
    "prediabetes": "предіабет",
    "diabetes criterion": "критерій діабету",
    "screening range below prediabetes threshold": "скринінговий діапазон нижче порога предіабету",
    "prediabetes range": "діапазон предіабету",
    "meets an A1C diagnostic criterion; confirmation and clinical context apply": (
        "відповідає діагностичному критерію за A1C; потрібні підтвердження та оцінка клінічної ситуації"
    ),
    "A diagnostic result may require confirmation; known interferences can make plasma glucose criteria preferable.": (
        "Діагностичний результат може потребувати підтвердження; через відомі інтерференції критерії за глюкозою плазми можуть бути доречнішими."
    ),
    "Normal fasting plasma glucose": "Нормальна глюкоза плазми натще",
    "Impaired fasting glucose": "Порушена глікемія натще",
    "Diabetes diagnostic criterion": "Діагностичний критерій діабету",
    "below the ADA impaired-fasting-glucose threshold": "нижче порога порушеної глікемії натще за ADA",
    "ADA prediabetes criterion for fasting plasma glucose": "Критерій предіабету за ADA для глюкози плазми натще",
    "meets the ADA fasting plasma glucose diagnostic criterion; confirmation is normally required": (
        "відповідає діагностичному критерію ADA для глюкози плазми натще; зазвичай потрібне підтвердження"
    ),
    "Do not apply automatically when fasting status or specimen is unknown.": (
        "Не застосовувати автоматично, якщо невідомо, чи аналіз здано натще, або невідомий тип зразка."
    ),
    "Focused Update of the ESC/EAS dyslipidaemia guideline": (
        "Фокусоване оновлення настанови ESC/EAS щодо дисліпідемій"
    ),
    "European Society of Cardiology / European Atherosclerosis Society": (
        "Європейське товариство кардіологів / Європейське товариство атеросклерозу"
    ),
    "Europe": "Європа",
    "LDL-C treatment goals depend on cardiovascular risk; this record does not infer a risk category.": (
        "Цільовий рівень ЛПНЩ залежить від серцево-судинного ризику; категорію ризику тут автоматично не визначено."
    ),
    "Low-risk treatment goal": "Ціль лікування при низькому ризику",
    "Moderate-risk treatment goal": "Ціль лікування при помірному ризику",
    "High-risk treatment goal": "Ціль лікування при високому ризику",
    "Very-high-risk treatment goal": "Ціль лікування при дуже високому ризику",
    "risk-specific LDL-C treatment goal": "ціль лікування ЛПНЩ залежно від ризику",
    "A clinician must establish the applicable cardiovascular risk category.": (
        "Лікар має встановити відповідну категорію серцево-судинного ризику."
    ),
    "Vitamin D for the Prevention of Disease": "Вітамін D для профілактики захворювань",
    "Endocrine Society": "Ендокринологічне товариство",
    "The guideline does not establish a universal outcome-based 25(OH)D target for generally healthy adults.": (
        "Настанова не встановлює для загалом здорових дорослих універсального цільового рівня 25(OH)D, обґрунтованого клінічними наслідками."
    ),
    "No universal preventive target": "Універсальної профілактичної цілі немає",
    # This enum value is printed in user-facing copy, so it needs a sentence,
    # not a transliterated identifier. `enum_label()` also tries the
    # space-separated form, so both spellings are covered.
    "no_universal_numeric_target": "універсальної числової цілі немає",
    "no universal numeric target": "універсальної числової цілі немає",
    "Use condition-specific clinical guidance when testing is indicated; do not promote a vendor interval to a universal target.": (
        "Якщо аналіз показаний, користуйтеся клінічними настановами для конкретного захворювання; не вважайте норму лабораторії універсальною ціллю."
    ),

    # Rule context keys/values
    "population": "популяція",
    "method": "метод",
    "purpose": "мета",
    "specimen": "зразок",
    "fasting": "натще",
    "cardiovascular_risk": "серцево-судинний ризик",
    # localize_mapping() looks up rule-context keys with underscores replaced by
    # spaces, so the underscore spelling alone never matched.
    "cardiovascular risk": "серцево-судинний ризик",
    "nonpregnant individuals": "невагітні особи",
    "NGSP-certified and DCCT-standardized laboratory assay": (
        "лабораторний метод, сертифікований NGSP і стандартизований за DCCT"
    ),
    "screening or diagnosis": "скринінг або діагностика",
    "venous plasma": "венозна плазма",
    "at least 8 hours without caloric intake": "щонайменше 8 годин без їжі та калорійних напоїв",
    "treatment target": "ціль лікування",
    "low": "низький",
    "moderate": "помірний",
    "high": "високий",
    "very high": "дуже високий",
    "generally healthy adults without an established indication for testing": (
        "загалом здорові дорослі без чітких показань до аналізу"
    ),

    # Vendor display names that are English descriptions
    "Center of Medical 3D Diagnostics": "Центр медичної 3D-діагностики",
    "St. Paraskeva Medical Center": "Медичний центр Святої Параскеви",
    "Veselka": "Веселка",
    "Expert Hospital": "Лікарня «Експерт»",
    "Ultramed": "УльтраМед",
    "MD Clinics": "Медичний центр «Мати та дитина»",
    "LONO Clinic": "Клініка «ЛОНО»",
    "Lviv Medical Center": "Львів Медікал Центр",
    "Lviv Regional Clinical Perinatal Center": "Львівський обласний клінічний перинатальний центр",
    "Lviv Territorial Medical Association": "КНП «Львівське територіальне медичне об'єднання»",
    "Second Clinical Territorial Medical Association of Lviv": (
        "КНТ «Друге клінічне територіальне медичне об'єднання м. Львова»"
    ),
    "First Clinical Territorial Medical Association of Lviv, St. Luke's Hospital": (
        "КНТ «Перше клінічне територіальне медичне об'єднання м. Львова», лікарня Святого Луки"
    ),

    # Document type fallbacks
    "Laboratory report": "Результати аналізів",
    "MRI report": "Висновок МРТ",
    "X-ray report": "Рентгенологічний висновок",
    "Ultrasound report": "Висновок УЗД",
    "Pathology report": "Патогістологічний висновок",
    "Diagnostic imaging record": "Візуалізаційне обстеження",
    "Medical document bundle": "Пакет медичних документів",
    "Consultation report": "Консультативний висновок",
    "Allergy report": "Висновок алерголога",
    "Microbiology report": "Мікробіологічне дослідження",
    # The four kinds the classify form gained; without these the Ukrainian UI
    # offered its own document types in English.
    "ECG recording": "Запис ЕКГ",
    "Blood pressure record": "Вимірювання артеріального тиску",
    "Administrative document": "Адміністративний документ",
    "Clinical report": "Клінічний висновок",
    "Medical report": "Медичний висновок",
    "Device measurement": "Вимірювання з пристрою",

    # Panel names (exact English from the panel catalogue). Names only - the
    # catalogue does not define panel descriptions, so none are translated here.
    "Complete blood count": "Загальний аналіз крові",
    "Lipid profile (lipidogram)": "Ліпідограма (ліпідний профіль)",
    "Glucose & metabolic control": "Глюкоза та метаболічний контроль",
    "Liver panel": "Печінкові проби",
    "Kidney panel": "Ниркові проби",
    "Other hormones": "Інші гормони",
    "Iron status": "Обмін заліза",
    "Autoantibody panel": "Панель автоантитіл",
    "Allergen-specific IgE": "Специфічні IgE до алергенів",
    "Infection serology": "Серологічні маркери інфекцій",
    "Culture & susceptibility": "Посів і чутливість до антибіотиків",
    "Blood pressure": "Артеріальний тиск",
    "Cardio fitness": "Кардіовитривалість",

    # New concept category
    "Autoimmune": "Автоімунні маркери",
    "Autoantibodies": "Автоантитіла",

    # Allergen families
    "Tree pollen": "Пилок дерев",
    "Grass pollen": "Пилок злакових трав",
    "Weed pollen": "Пилок бур’янів",
    "House-dust mites": "Кліщі домашнього пилу",
    "Animal dander": "Епітелій тварин",
    "Moulds": "Цвілеві гриби",
    "Foods": "Харчові алергени",
    "Insect venom": "Отрута комах",
    "Other allergens": "Інші алергени",

    # Blood-pressure category names (ESH 2023 and ACC/AHA 2017)
    "Optimal": "Оптимальний",
    "High normal": "Високий нормальний",
    "Elevated": "Підвищений",
    "Grade 1 hypertension": "Артеріальна гіпертензія 1 ступеня",
    "Grade 2 hypertension": "Артеріальна гіпертензія 2 ступеня",
    "Grade 3 hypertension": "Артеріальна гіпертензія 3 ступеня",
    "Isolated systolic hypertension": "Ізольована систолічна гіпертензія",
    "Stage 1 hypertension": "Артеріальна гіпертензія 1 стадії",
    "Stage 2 hypertension": "Артеріальна гіпертензія 2 стадії",
    "Hypertensive crisis": "Гіпертензивний криз",

    # Reference-source publishers
    "European Society of Hypertension": "Європейське товариство з артеріальної гіпертензії",
    "European Society of Cardiology / European Society of Hypertension": (
        "Європейське товариство кардіологів / Європейське товариство з артеріальної гіпертензії"
    ),
    "American College of Cardiology / American Heart Association": (
        "Американський коледж кардіології / Американська асоціація серця"
    ),
    "World Health Organization": "Всесвітня організація охорони здоров’я",
    "National Institute for Health and Care Excellence": (
        "Національний інститут охорони здоров’я та вдосконалення медичної допомоги"
    ),
    "Kidney Disease: Improving Global Outcomes": "Kidney Disease: Improving Global Outcomes (KDIGO)",
    "National Kidney Foundation": "Національний фонд нирок США",
    "American Thyroid Association": "Американська тиреоїдна асоціація",
    "British Society for Haematology": "Британське товариство гематології",
    "European Academy of Allergy and Clinical Immunology": (
        "Європейська академія алергології та клінічної імунології"
    ),
    "European Federation of Clinical Chemistry and Laboratory Medicine": (
        "Європейська федерація клінічної хімії та лабораторної медицини"
    ),
    "Centers for Disease Control and Prevention": "Центри з контролю та профілактики захворювань США",

    # Health-area descriptions that HEALTH_AREAS passes through translate_phrase
    # but that had no entry, so they rendered in English on Ukrainian pages.
    "Weight, body mass index, body fat and lean mass": (
        "Вага, індекс маси тіла, частка жиру та безжирова маса"
    ),
    "Movement, exercise, energy and cardio fitness": (
        "Рух, тренування, енергія та кардіовитривалість"
    ),
    "Walking speed, step length, steadiness and asymmetry": (
        "Швидкість ходьби, довжина кроку, стійкість та асиметрія"
    ),
    "Sleep stages, heart-rate recovery, oxygen and breathing": (
        "Фази сну, відновлення пульсу, кисень і дихання"
    ),
    "Sound exposure and time in daylight": "Шумове навантаження та час на денному світлі",

    # Untranslated code/DB labels found by the UI audit
    "Local Owner": "Локальний власник",
    "MET-like effort": "Навантаження в MET-еквіваленті",
    "mmHg": "мм рт. ст.",

    # --- Panel names and descriptions (src/anamna/panels.py) ---------
    'Lipids': 'Ліпіди',
    'Glucose': 'Глюкоза',
    'Urine': 'Сеча',
    'Minerals': 'Мінерали',
    'Serology': 'Серологія',
    'Cultures': 'Посіви',
    'Digestive': 'Травлення',
    'Body': 'Тіло',
    'Activity': 'Активність',
    'Red cells, white cells and platelets counted on one sample.': 'Еритроцити, лейкоцити й тромбоцити в одному зразку крові.',
    'Cholesterol fractions and triglycerides used in cardiovascular risk assessment.': 'Фракції холестерину й тригліцериди, за якими оцінюють серцево-судинний ризик.',
    'Fasting glucose and the three-month average carried by glycated hemoglobin.': 'Глюкоза натще й глікований гемоглобін, що показує середній рівень глюкози за три місяці.',
    'Liver enzymes, bilirubin fractions and the serum proteins the liver makes.': 'Ферменти печінки, фракції білірубіну та білки сироватки, які виробляє печінка.',
    'Pancreatic enzymes measured in serum.': 'Ферменти підшлункової залози в сироватці крові.',
    'Waste products the kidneys clear from blood.': 'Продукти обміну, які нирки виводять із крові.',
    'Appearance, dipstick chemistry and microscopy of a urine sample.': 'Фізичні властивості, хімічний аналіз тест-смужкою та мікроскопія сечі.',
    'Thyroid hormones and the antibodies that attack the thyroid gland.': 'Гормони щитоподібної залози та антитіла, які її атакують.',
    'Endocrine measurements outside the thyroid panel.': 'Гормони, що не входять до тиреоїдної панелі.',
    'Circulating iron and the protein that stores it.': 'Залізо в крові та білок, який його запасає.',
    'Vitamin D, the B-vitamins and the marker that reflects their supply.': 'Вітамін D, вітаміни групи B та показник, що відображає їх забезпеченість.',
    'The salts and minerals that keep nerves, muscle and bone working.': 'Солі й мінерали, які забезпечують роботу нервів, м’язів і кісток.',
    'General markers that rise when there is inflammation somewhere in the body.': 'Загальні маркери, які зростають, коли десь в організмі є запалення.',
    'How quickly blood forms a clot.': 'Як швидко згортається кров.',
    "Antibodies directed at the body's own tissue, plus the HLA-B27 marker.": 'Антитіла проти власних тканин організму та маркер HLA-B27.',
    'Total IgE and the allergen-specific IgE results from the ImmunoCAP panel.': 'Загальний IgE та алергенспецифічні IgE з панелі ImmunoCAP.',
    'Antibody and antigen tests for transmissible infections.': 'Аналізи на антитіла та антигени збудників заразних інфекцій.',
    'What grew from a sample and which antibiotics it responded to.': 'Що виросло у зразку та до яких антибіотиків воно чутливе.',
    'Laboratory testing of the stomach and intestines.': 'Лабораторні дослідження шлунка та кишківника.',
    'Systolic and diastolic pressure read together with the pulse.': 'Систолічний і діастолічний тиск, виміряні разом із пульсом.',
    'Weight and what it is made of.': 'Вага та склад тіла.',
    'Vital signs': 'Життєві показники',
    'Vitals': 'Життєві показники',
    'Temperature, breathing rate and oxygen saturation measured at a visit.':
        'Температура, частота дихання та сатурація, виміряні на прийомі.',
    'ECG intervals': 'Інтервали ЕКГ',
    'ECG': 'ЕКГ',
    'How long each electrical phase of the heartbeat lasts on a 12-lead ECG.':
        'Скільки триває кожна електрична фаза серцевого скорочення на ЕКГ у 12 відведеннях.',
    'Body measurements': 'Антропометрія',
    'How the heart responds to effort and to rest.': 'Як серце реагує на навантаження та відпочинок.',
    'Sleep stages and the vital signs recorded overnight.': 'Фази сну та життєві показники, записані вночі.',
    'Recovery & stress': 'Відновлення та стрес',
    'Recovery': 'Відновлення',
    'How the body recharges: readiness, stress balance and overnight temperature.':
        'Як організм відновлюється: готовність, баланс стресу й нічна температура.',
    'Movement, exercise and energy across the day.': 'Рух, фізична активність і витрати енергії протягом дня.',
    'Walking speed, step length, steadiness and asymmetry.': 'Швидкість ходьби, довжина кроку, стійкість і асиметрія.',
    'Stool analysis (coprogram)': 'Аналіз калу (копрограма)',
    'Coprogram': 'Копрограма',
    'Physical, chemical and microscopic examination of a stool sample.':
        'Фізичне, хімічне та мікроскопічне дослідження зразка калу.',
    'Hearing': 'Слух',
    'Noise exposure from surroundings and headphones, and daily daylight.':
        'Шум довкілля та навушників і щоденний час на денному світлі.',

    # Oura OAuth scope display names: _oura_sync_context builds them as
    # scope.replace("_", " ").capitalize() and passes the result through
    # translate_phrase, so every scope the provider requests needs its
    # capitalized spelling here.
    "Daily": "Щоденні зведення",
    "Heartrate": "Пульс",
    "Workout": "Тренування",
    "Session": "Сеанси",
    "SpO₂": "SpO₂ (насичення киснем)",
    "Tag": "Мітки",
    "Personal": "Особисті дані",
    "Heart health": "Здоров’я серця",
    "Ring configuration": "Налаштування каблучки",

    # --- Reference-source publishers (data/reference_library.json) ----------
    # Every English publisher string that reaches the guidance sections, keyed
    # exactly as the library stores it. Organisation names are translated;
    # journal titles and author lists stay in the original language (the same
    # policy as guideline titles), so publishers that are nothing but a journal
    # title plus authors carry no entry at all.
    "AABB (Association for the Advancement of Blood & Biotherapies)":
        "AABB (Асоціація розвитку крові та біотерапії)",
    "Agency for Healthcare Research and Quality":
        "Агентство з досліджень і якості медичної допомоги США",
    "AliveCor, Inc. (device manufacturer documentation, not a health authority)":
        "AliveCor, Inc. (документація виробника пристрою, не орган охорони здоров’я)",
    "American Academy of Family Physicians": "Американська академія сімейних лікарів",
    "American Academy of Sleep Medicine and Sleep Research Society":
        "Американська академія медицини сну та Товариство досліджень сну",
    "American Association for the Study of Liver Diseases":
        "Американська асоціація з вивчення захворювань печінки",
    "American Board of Internal Medicine": "Американська рада з внутрішніх хвороб",
    "American Cancer Society": "Американське онкологічне товариство",
    "American College of Cardiology / American Heart Association (with AACVPR, ABC, ACPM, ADA, AGS, APhA, ASPC, NLA, PCNA)":
        "Американський коледж кардіології / Американська асоціація серця (разом з AACVPR, ABC, ACPM, ADA, AGS, APhA, ASPC, NLA, PCNA)",
    "American College of Cardiology / American Heart Association / ACCP / HRS":
        "Американський коледж кардіології / Американська асоціація серця / ACCP / HRS",
    "American College of Cardiology / American Heart Association / Heart Rhythm Society":
        "Американський коледж кардіології / Американська асоціація серця / Товариство серцевого ритму (HRS)",
    "American College of Gastroenterology": "Американський коледж гастроентерології",
    "American College of Physicians":
        "Американський коледж лікарів",
    "American College of Radiology":
        "Американський коледж радіології",
    "American College of Rheumatology (ACR)": "Американський коледж ревматології (ACR)",
    "American College of Rheumatology / European League Against Rheumatism (joint)":
        "Американський коледж ревматології / Європейська антиревматична ліга (спільно)",
    "American College of Rheumatology / Spondylitis Association of America / SPARTAN":
        "Американський коледж ревматології / Американська асоціація спондиліту / SPARTAN",
    "American College of Sports Medicine / FRIEND registry (Mayo Clinic Proceedings)":
        "Американський коледж спортивної медицини / реєстр FRIEND (Mayo Clinic Proceedings)",
    "American Diabetes Association and European Association for the Study of Diabetes (joint consensus)":
        "Американська діабетична асоціація та Європейська асоціація з вивчення діабету (спільний консенсус)",
    "American Heart Association": "Американська асоціація серця",
    "American Heart Association / American College of Cardiology":
        "Американська асоціація серця / Американський коледж кардіології",
    "American Society of Echocardiography / European Association of Cardiovascular Imaging":
        "Американське товариство ехокардіографії / Європейська асоціація серцево-судинної візуалізації",
    "American Society of Hematology": "Американське товариство гематології",
    "American Thyroid Association, Laboratory Services Committee":
        "Американська тиреоїдна асоціація, Комітет лабораторних служб",
    "American Urological Association / Society of Urodynamics, Female Pelvic Medicine & Urogenital Reconstruction (AUA/SUFU)":
        "Американська урологічна асоціація / Товариство уродинаміки, жіночої тазової медицини та урогенітальної реконструкції (AUA/SUFU)",
    "Ann Allergy Asthma Immunol (peer-reviewed review, PMC6275558)":
        "Ann Allergy Asthma Immunol (рецензований огляд, PMC6275558)",
    "Annals of the Rheumatic Diseases (EULAR): international expert group (Agmon-Levin, Damoiseaux, Bossuyt et al.)":
        "Annals of the Rheumatic Diseases (EULAR), міжнародна експертна група (Agmon-Levin, Damoiseaux, Bossuyt та ін.)",
    "Apple Inc. (device manufacturer documentation, not a health authority)":
        "Apple Inc. (документація виробника пристрою, не орган охорони здоров’я)",
    "Assessment of SpondyloArthritis international Society (ASAS)":
        "Міжнародне товариство з оцінки спондилоартриту (ASAS)",
    "Assessment of SpondyloArthritis international Society / European Alliance of Associations for Rheumatology (EULAR)":
        "Міжнародне товариство з оцінки спондилоартриту (ASAS) / Європейський альянс ревматологічних асоціацій (EULAR)",
    "Australasian Association of Clinical Biochemists, Working Party on Standardised Reporting of Protein Electrophoresis":
        "Австралазійська асоціація клінічних біохіміків, робоча група зі стандартизованого звітування електрофорезу білків",
    "Cells (MDPI) - Moli-Family Cohort Study (primary research, not guidance)":
        "Cells (MDPI), когортне дослідження Moli-Family (первинне дослідження, не настанова)",
    "Centers for Disease Control and Prevention / American Heart Association":
        "Центри з контролю та профілактики захворювань США / Американська асоціація серця",
    "Centers for Disease Control and Prevention / National Center for Health Statistics":
        "Центри з контролю та профілактики захворювань США / Національний центр статистики охорони здоров’я",
    "Clinical Laboratory (Lichtinghagen R, Pietsch D, Brand K; Institute of Clinical Chemistry, Hannover Medical School)":
        "Clinical Laboratory (Lichtinghagen R, Pietsch D, Brand K; Інститут клінічної хімії, Ганноверська вища медична школа)",
    "Clinical and Laboratory Standards Institute (CLSI)":
        "Інститут клінічних і лабораторних стандартів (CLSI)",
    "Council of the European Union": "Рада Європейського Союзу",
    "European Academy of Allergy and Clinical Immunology (EAACI) and the International Cooperative Working Group on Eosinophil Disorders (ICOG-EO)":
        "Європейська академія алергології та клінічної імунології (EAACI) і Міжнародна кооперативна робоча група з еозинофільних розладів (ICOG-EO)",
    "European Academy of Andrology; endorsing organization: European Society of Endocrinology":
        "Європейська академія андрології; підтримано Європейським товариством ендокринології",
    "European Alliance of Associations for Rheumatology (EULAR)":
        "Європейський альянс ревматологічних асоціацій (EULAR)",
    "European Association for the Study of the Liver":
        "Європейська асоціація з вивчення печінки",
    "European Association for the Study of the Liver / European Association for the Study of Diabetes / European Association for the Study of Obesity":
        "Європейська асоціація з вивчення печінки / Європейська асоціація з вивчення діабету / Європейська асоціація з вивчення ожиріння",
    "European Association of Urology": "Європейська асоціація урології",
    "European Association of Urology (EAU)": "Європейська асоціація урології (EAU)",
    "European Atherosclerosis Society": "Європейське товариство атеросклерозу",
    "European Atherosclerosis Society / European Federation of Clinical Chemistry and Laboratory Medicine":
        "Європейське товариство атеросклерозу / Європейська федерація клінічної хімії та лабораторної медицини",
    "European Centre for Disease Prevention and Control":
        "Європейський центр профілактики та контролю захворювань",
    "European Commission": "Європейська комісія",
    "European Commission, Joint Research Centre (JRC-IRMM), with the International Federation of Clinical Chemistry and Laboratory Medicine":
        "Європейська комісія, Спільний дослідницький центр (JRC-IRMM), спільно з Міжнародною федерацією клінічної хімії та лабораторної медицини",
    "European Committee on Antimicrobial Susceptibility Testing":
        "Європейський комітет з визначення чутливості до антимікробних препаратів",
    "European Federation of Clinical Chemistry and Laboratory Medicine (EFLM), Task and Finish Group Urinalysis":
        "Європейська федерація клінічної хімії та лабораторної медицини (EFLM), цільова група з аналізу сечі",
    "European Federation of Clinical Chemistry and Laboratory Medicine (EFLM), Task and Finish Group on Laboratory Testing for Dyslipidemia":
        "Європейська федерація клінічної хімії та лабораторної медицини (EFLM), цільова група з лабораторної діагностики дисліпідемії",
    "European Federation of Clinical Chemistry and Laboratory Medicine (EFLM), Working Group on Biological Variation":
        "Європейська федерація клінічної хімії та лабораторної медицини (EFLM), робоча група з біологічної варіації",
    "European Food Safety Authority (NDA Panel)":
        "Європейське управління з безпечності харчових продуктів (панель NDA)",
    "European Helicobacter and Microbiota Study Group":
        "Європейська група з вивчення Helicobacter і мікробіоти",
    "European League Against Rheumatism / American College of Rheumatology (joint)":
        "Європейська антиревматична ліга / Американський коледж ревматології (спільно)",
    "European LeukemiaNet, Morphology Faculty (network WP10)":
        "European LeukemiaNet, факультет морфології (мережа WP10)",
    "European Pancreatic Club and 14 endorsing societies (APA, EASD, EASL, ESGAR, ESGE, ESP, ESPCG, ESPEN, ESPGHAN, IAP, JPS, KPBA, LAPSG, UEG)":
        "Європейський панкреатологічний клуб і 14 товариств, що підтримали документ (APA, EASD, EASL, ESGAR, ESGE, ESP, ESPCG, ESPEN, ESPGHAN, IAP, JPS, KPBA, LAPSG, UEG)",
    "European Parliament and Council of the European Union":
        "Європейський парламент і Рада Європейського Союзу",
    "European Respiratory Society / American Thoracic Society":
        "Європейське респіраторне товариство / Американське торакальне товариство",
    "European Society of Cardiology": "Європейське товариство кардіологів",
    "European Society of Cardiology / European Association for Cardio-Thoracic Surgery":
        "Європейське товариство кардіологів / Європейська асоціація кардіоторакальної хірургії",
    "European Society of Cardiology / European Heart Rhythm Association":
        "Європейське товариство кардіологів / Європейська асоціація серцевого ритму",
    "European Society of Endocrinology": "Європейське товариство ендокринології",
    "European Society of Gastrointestinal Endoscopy":
        "Європейське товариство гастроінтестинальної ендоскопії",
    "European Thyroid Association": "Європейська тиреоїдна асоціація",
    "European Working Group on Sarcopenia in Older People 2 (EUGMS)":
        "Європейська робоча група з саркопенії в людей похилого віку 2 (EUGMS)",
    "IFCC Committee for Standardization of Thyroid Function Tests":
        "Комітет IFCC зі стандартизації тестів функції щитоподібної залози",
    "IUSTI Europe": "IUSTI Європа",
    "IUSTI Europe (International Union against Sexually Transmitted Infections)":
        "IUSTI Європа (Міжнародний союз боротьби з інфекціями, що передаються статевим шляхом)",
    "Infectious Diseases Society of America": "Американське товариство інфекційних хвороб",
    "International Council for Standardization in Haematology":
        "Міжнародна рада зі стандартизації в гематології",
    "International Council for Standardization in Haematology (ICSH)":
        "Міжнародна рада зі стандартизації в гематології (ICSH)",
    "International Federation of Clinical Chemistry and Laboratory Medicine":
        "Міжнародна федерація клінічної хімії та лабораторної медицини",
    "International Federation of Clinical Chemistry and Laboratory Medicine (IFCC), Committee on Reference Systems of Enzymes":
        "Міжнародна федерація клінічної хімії та лабораторної медицини (IFCC), Комітет з референтних систем ферментів",
    "NHS (UK)":
        "Національна служба охорони здоров’я Великої Британії (NHS)",
    "NHS Scotland (Right Decisions), Diagnostic Atlas of Variation education toolkit":
        "NHS Шотландії (Right Decisions), навчальний набір Diagnostic Atlas of Variation",
    "NIH Office of Dietary Supplements": "Управління дієтичних добавок NIH",
    "National Academies of Sciences, Engineering, and Medicine (Food and Nutrition Board)":
        "Національні академії наук, інженерії та медицини США (Рада з харчових продуктів і харчування)",
    "National Glycohemoglobin Standardization Program (NGSP), the CDC-linked US HbA1c standardisation programme":
        "Національна програма стандартизації глікогемоглобіну (NGSP), американська програма стандартизації HbA1c, пов’язана з CDC",
    "National Heart, Lung, and Blood Institute (NIH)":
        "Національний інститут серця, легень і крові (NIH)",
    "National Heart, Lung, and Blood Institute (NIH): National Cholesterol Education Program":
        "Національний інститут серця, легень і крові (NIH), Національна освітня програма з холестерину",
    "National Institute for Health and Care Excellence (UK)":
        "Національний інститут охорони здоров’я та вдосконалення медичної допомоги (Велика Британія)",
    "National Institute of Diabetes and Digestive and Kidney Diseases (NIDDK), National Institutes of Health":
        "Національний інститут діабету, хвороб травлення та нирок (NIDDK), Національні інститути здоров’я США",
    "National Institute of Diabetes and Digestive and Kidney Diseases (NIH)":
        "Національний інститут діабету, хвороб травлення та нирок (NIH)",
    "National Institute of Diabetes and Digestive and Kidney Diseases, National Institutes of Health":
        "Національний інститут діабету, хвороб травлення та нирок, Національні інститути здоров’я США",
    "National Institutes of Health / National Institute of Allergy and Infectious Diseases":
        "Національні інститути здоров’я США / Національний інститут алергії та інфекційних хвороб",
    "National Institutes of Health, Office of Dietary Supplements":
        "Національні інститути здоров’я США, Управління дієтичних добавок",
    "National Kidney Foundation (NKF)": "Національний фонд нирок США (NKF)",
    "Nordic Federation of Clinical Chemistry (NFKK) / Scandinavian Society of Clinical Chemistry - Nordic Reference Interval Project (NORIP)":
        "Північна федерація клінічної хімії (NFKK) / Скандинавське товариство клінічної хімії, Північний проєкт референтних інтервалів (NORIP)",
    "Nordic Reference Interval Project (NORIP) - EQUALIS, NOKLUS and the Nordic clinical chemistry societies of Denmark, Finland, Iceland, Norway and Sweden":
        "Північний проєкт референтних інтервалів (NORIP): EQUALIS, NOKLUS і товариства клінічної хімії Данії, Фінляндії, Ісландії, Норвегії та Швеції",
    "Nutrition Reviews (Kvissberg MA, Dalvi PS, Kerac M, et al.)":
        "Nutrition Reviews (Kvissberg MA, Dalvi PS, Kerac M та ін.)",
    "PLOS Neglected Tropical Diseases (peer-reviewed; Table 1 reproduces the WHO egg-count thresholds)":
        "PLOS Neglected Tropical Diseases (рецензовано; таблиця 1 відтворює порогові значення ВООЗ для підрахунку яєць гельмінтів)",
    "Revista Mexicana de Patología Clínica y Medicina de Laboratorio (primary research, not guidance)":
        "Revista Mexicana de Patología Clínica y Medicina de Laboratorio (первинне дослідження, не настанова)",
    "Rome Foundation": "Римський фонд (Rome Foundation)",
    "Royal College of Physicians (UK)": "Королівський коледж лікарів (Велика Британія)",
    "Sarcopenia Definitions and Outcomes Consortium (NIA/FNIH), J Am Geriatr Soc":
        "Консорціум визначень і наслідків саркопенії (NIA/FNIH), J Am Geriatr Soc",
    "Scandinavian Journal of Clinical and Laboratory Investigation (primary research, not guidance)":
        "Scandinavian Journal of Clinical and Laboratory Investigation (первинне дослідження, не настанова)",
    "Scandinavian Journal of Gastroenterology (Lewis SJ, Heaton KW; Bristol Royal Infirmary)":
        "Scandinavian Journal of Gastroenterology (Lewis SJ, Heaton KW; Брістольська королівська лікарня)",
    "Società Italiana di Biochimica Clinica (SIBioC) / Società Italiana di Patologia Clinica e Medicina di Laboratorio (SIPMeL): EFLM national member societies":
        "Società Italiana di Biochimica Clinica (SIBioC) / Società Italiana di Patologia Clinica e Medicina di Laboratorio (SIPMeL), національні товариства-члени EFLM",
    "StatPearls Publishing / NCBI Bookshelf, U.S. National Library of Medicine (Azer SA, Sankararaman S)":
        "StatPearls Publishing / NCBI Bookshelf, Національна медична бібліотека США (Azer SA, Sankararaman S)",
    "StatPearls Publishing / NCBI Bookshelf, U.S. National Library of Medicine (Tian C, Ghodeif AO, Arshad S, Gillespie E)":
        "StatPearls Publishing / NCBI Bookshelf, Національна медична бібліотека США (Tian C, Ghodeif AO, Arshad S, Gillespie E)",
    "Sysmex Corporation (analyser manufacturer's own journal, not a health authority)":
        "Sysmex Corporation (журнал виробника аналізаторів, не орган охорони здоров’я)",
    "Task Force of the European Society of Cardiology and the North American Society of Pacing and Electrophysiology":
        "Робоча група Європейського товариства кардіологів і Північноамериканського товариства кардіостимуляції та електрофізіології",
    "The Lancet Public Health (primary research, not guidance)":
        "The Lancet Public Health (первинне дослідження, не настанова)",
    "U.S. Department of Health and Human Services (ODPHP)":
        "Міністерство охорони здоров’я і соціальних служб США (ODPHP)",
    "U.S. Food and Drug Administration":
        "Управління з контролю за якістю харчових продуктів і лікарських засобів США (FDA)",
    "U.S. Food and Drug Administration (21 CFR, published by GPO/govinfo)":
        "Управління з контролю за якістю харчових продуктів і лікарських засобів США (FDA; 21 CFR, опубліковано GPO/govinfo)",
    "U.S. National Library of Medicine (MedlinePlus)":
        "Національна медична бібліотека США (MedlinePlus)",
    "U.S. Preventive Services Task Force":
        "Робоча група США з профілактичних послуг (USPSTF)",
    "U.S. Preventive Services Task Force (USPSTF)":
        "Робоча група США з профілактичних послуг (USPSTF)",
    "US Centers for Disease Control and Prevention / National Center for Health Statistics":
        "Центри з контролю та профілактики захворювань США / Національний центр статистики охорони здоров’я",
    "US Centers for Disease Control and Prevention / National Center for Health Statistics (NHANES III)":
        "Центри з контролю та профілактики захворювань США / Національний центр статистики охорони здоров’я (NHANES III)",
    "US Food and Drug Administration":
        "Управління з контролю за якістю харчових продуктів і лікарських засобів США (FDA)",
    "US Multi-Society Task Force on Colorectal Cancer (ACG / AGA / ASGE)":
        "Об’єднана робоча група товариств США з колоректального раку (ACG / AGA / ASGE)",
    "US National Library of Medicine (NIH)": "Національна медична бібліотека США (NIH)",
    "US National Library of Medicine (NIH), MedlinePlus Medical Encyclopedia":
        "Національна медична бібліотека США (NIH), медична енциклопедія MedlinePlus",
    "United European Gastroenterology (HaPanEU working group)":
        "United European Gastroenterology (робоча група HaPanEU)",
    "WHO Expert Consultation (published in The Lancet)":
        "Експертна консультація ВООЗ (опубліковано в The Lancet)",
    "World Health Organization / International Agency for Research on Cancer":
        "Всесвітня організація охорони здоров’я / Міжнародне агентство з вивчення раку",
    "World Health Organization / International Diabetes Federation":
        "Всесвітня організація охорони здоров’я / Міжнародна діабетична федерація",
    "World Health Organization / International Telecommunication Union":
        "Всесвітня організація охорони здоров’я / Міжнародний союз електрозв’язку",
    # Curated-rule context vocabulary (ENUM_LABELS_EN in health.py → metric pages)
    "Type of guidance": "Тип настанови",
    "Decision threshold: a published action cut-off, not a population interval":
        "Поріг рішення: опублікована межа для клінічних дій, а не популяційний інтервал",
    "Reference interval: the range expected in a healthy population":
        "Референтний інтервал: діапазон, очікуваний у здорових людей",
    "Treatment target: the goal for someone under treatment":
        "Цільовий рівень лікування: мета для людини, яка лікується",
    "Applies only when": "Діє лише за умови",
    "Infection or inflammation is present": "Є інфекція або запалення",
    "An acute illness is present": "Є гостре захворювання",

    # --- Vaccine-preventable diseases (immunizations.DISEASES) ---------------
    # Names and the plain-language explanation shown beside each on the
    # vaccinations page.  Both halves need Ukrainian: an explanation that exists
    # only in English is a rule 5 answer nobody can read.
    "Tuberculosis": "Туберкульоз",
    "A bacterial infection of the lungs. The BCG vaccine is given to newborns in Ukraine.": "Бактеріальна інфекція легень. В Україні новонародженим роблять щеплення БЦЖ.",
    "Diphtheria": "Дифтерія",
    "A bacterial throat infection that can block the airway. Protection fades, so adults need a booster.": "Бактеріальна інфекція горла, яка може перекрити дихальні шляхи. Захист з часом слабшає, тому дорослим потрібна ревакцинація.",
    "Tetanus": "Правець",
    "Caused by bacteria entering a wound; it locks the muscles. Protection fades, so adults need a booster.": "Збудник потрапляє в організм через рану й спричиняє тяжкі м’язові спазми. Захист з часом слабшає, тому дорослим потрібна ревакцинація.",
    "Whooping cough": "Кашлюк",
    "A bacterial cough illness, dangerous to infants. Adults are boosted mainly to protect babies around them.": "Бактеріальна інфекція з нападами кашлю, небезпечна для немовлят. Дорослих ревакцинують передусім, щоб захистити немовлят поруч.",
    "Poliomyelitis": "Поліомієліт",
    "A virus that can paralyse. Ukraine's calendar gives inactivated vaccine at 2, 4, 6 and 18 months and at six years.": "Вірус, що може спричинити параліч. За календарем України щеплення роблять інактивованою вакциною у 2, 4, 6 і 18 місяців та в шість років.",
    "Haemophilus influenzae type b": "Гемофільна інфекція типу b",
    "A bacterium that causes meningitis in small children. Given in infancy.": "Бактерія, що спричиняє менінгіт у маленьких дітей. Щеплення роблять у немовлячому віці.",
    "Hepatitis B": "Гепатит B",
    "A virus that damages the liver over years. Ukraine's current calendar starts the course at two months of age; babies whose mothers carry the virus are vaccinated in the first day of life.": "Вірус, що роками ушкоджує печінку. За чинним календарем України курс починають у два місяці; дітей, чиї матері мають цей вірус, щеплюють у першу добу життя.",
    "Hepatitis A": "Гепатит A",
    "A liver virus spread through food and water. Recommended rather than routine.": "Вірус, що уражає печінку й передається через їжу та воду. Щеплення рекомендоване, але не входить до календаря.",
    "Measles": "Кір",
    "A highly contagious virus with serious complications. Two doses give lasting protection.": "Надзвичайно заразний вірус із серйозними ускладненнями. Дві дози дають тривалий захист.",
    "Mumps": "Епідемічний паротит",
    "A virus that swells the salivary glands and can affect fertility. Given with measles and rubella.": "Вірус, що спричиняє набряк слинних залоз і може вплинути на плідність. Щеплення роблять разом із кором і краснухою.",
    "Rubella": "Краснуха",
    "Mild in itself, but severe for an unborn child. Given with measles and mumps.": "Сама собою хвороба легка, але небезпечна для ненародженої дитини. Щеплення роблять разом із кором і паротитом.",
    "Chickenpox": "Вітряна віспа",
    "A virus most people meet in childhood; more severe in adults. Recommended, not routine.": "Вірус, з яким більшість людей стикається в дитинстві; дорослі хворіють тяжче. Щеплення рекомендоване, але не входить до календаря.",
    "Seasonal influenza": "Сезонний грип",
    "The strains circulating change every year, so protection is given once a season.": "Штами вірусу щороку змінюються, тому щеплення роблять щосезону.",
    "COVID-19": "COVID-19",
    "Caused by the SARS-CoV-2 coronavirus. Which adults should be revaccinated, and how often, is where the three authorities differ most.": "Збудник: коронавірус SARS-CoV-2. Найбільше три відомства розходяться в тому, кого з дорослих і як часто ревакцинувати.",
    "Human papillomavirus": "Вірус папіломи людини",
    "A virus that causes cervical and other cancers. Ukraine's calendar gives one dose to girls aged 12 to 13; at other ages the course is one to three doses, depending on age, immune status and the national schedule.": "Вірус, що спричиняє рак шийки матки та інші види раку. За календарем України одну дозу отримують дівчата віком 12–13 років; в іншому віці курс складається з однієї-трьох доз залежно від віку, стану імунітету та національного календаря.",
    "Pneumococcal disease": "Пневмококова інфекція",
    "A bacterium causing pneumonia and meningitis; risk rises with age and with some long-term conditions.": "Бактерія, що спричиняє пневмонію та менінгіт; ризик зростає з віком і за деяких хронічних станів.",
    "Meningococcal A, C, W, Y": "Менінгококова інфекція серогруп A, C, W, Y",
    "Bacterial meningitis and sepsis from four serogroups, covered only together by a four-valent (ACWY) vaccine.": "Бактеріальний менінгіт і сепсис, спричинені чотирма серогрупами; від усіх чотирьох захищає лише чотиривалентна вакцина (ACWY).",
    "Meningococcal A": "Менінгококова інфекція серогрупи A",
    "Meningococcal C": "Менінгококова інфекція серогрупи C",
    "Meningococcal W": "Менінгококова інфекція серогрупи W",
    "Bacterial meningitis and sepsis from serogroup A only; it does not cover the other serogroups.": "Бактеріальний менінгіт і сепсис, спричинені лише серогрупою A; від інших серогруп щеплення не захищає.",
    "Bacterial meningitis and sepsis from serogroup C only; it does not cover the other serogroups.": "Бактеріальний менінгіт і сепсис, спричинені лише серогрупою C; від інших серогруп щеплення не захищає.",
    "Bacterial meningitis and sepsis from serogroup W only; it does not cover the other serogroups.": "Бактеріальний менінгіт і сепсис, спричинені лише серогрупою W; від інших серогруп щеплення не захищає.",
    "Meningococcal B": "Менінгококова інфекція серогрупи B",
    "The serogroup the A/C/W/Y vaccine does not cover; it needs its own product.": "Серогрупа, від якої вакцина A/C/W/Y не захищає; потрібна окрема вакцина.",
    "Rotavirus": "Ротавірусна інфекція",
    "The commonest cause of severe infant diarrhoea. Given orally in the first months of life.": "Найчастіша причина тяжкої діареї в немовлят. Вакцину закапують у рот у перші місяці життя.",
    "Tick-borne encephalitis": "Кліщовий енцефаліт",
    "A virus carried by ticks in parts of Europe. Given to people exposed to them.": "Вірус, який переносять кліщі в деяких регіонах Європи. Щеплення роблять тим, хто може зіткнутися з кліщами.",
    "Rabies": "Сказ",
    "Almost always fatal once symptoms start. Given before exposure to people at risk, or immediately after a bite.": "Після появи симптомів майже завжди смертельний. Щеплення роблять заздалегідь людям із групи ризику або одразу після укусу.",
    "Typhoid fever": "Черевний тиф",
    "A bacterial illness from contaminated food and water. A travel vaccine.": "Бактеріальна інфекція, що передається через забруднені їжу та воду. Щеплення для мандрівників.",
    "Yellow fever": "Жовта гарячка",
    "A mosquito-borne virus. Required for entry to some countries.": "Вірус, який переносять комарі. Щеплення обов’язкове для в’їзду до деяких країн.",
    "Japanese encephalitis": "Японський енцефаліт",
    "A mosquito-borne brain infection in parts of Asia. A travel vaccine.": "Інфекція головного мозку, яку переносять комарі в деяких регіонах Азії. Щеплення для мандрівників.",
    "Cholera": "Холера",
    "A severe diarrhoeal illness from contaminated water. A travel and outbreak vaccine.": "Тяжка кишкова інфекція з діареєю, що передається через забруднену воду. Щеплення для мандрівників і під час спалахів.",
    "Anthrax": "Сибірка",
    "An occupational vaccine for people working with livestock or animal products.": "Щеплення за професійними показаннями для тих, хто працює з худобою або продуктами тваринного походження.",
    "Plague": "Чума",
    "An occupational vaccine for laboratory and field workers in endemic areas.": "Щеплення за професійними показаннями для працівників лабораторій і польових працівників в ендемічних регіонах.",
    "Tularaemia": "Туляремія",
    "An occupational and regional vaccine, used where the bacterium circulates in wildlife.": "Щеплення за професійними та регіональними показаннями там, де бактерія циркулює серед диких тварин.",
    "Leptospirosis": "Лептоспіроз",
    "Spread through water contaminated by animal urine; an occupational vaccine.": "Передається через воду, забруднену сечею тварин. Щеплення за професійними показаннями.",
    "Q fever": "Ку-гарячка",
    "An occupational vaccine for people working with sheep, goats and cattle.": "Щеплення за професійними показаннями для тих, хто працює з вівцями, козами та великою рогатою худобою.",
}

# A note an installation's own override writes (config.local_overrides) names
# one person's record, so its translation ships with that override, not here.
PHRASES.update(local_overrides().get("phrases", {}))
