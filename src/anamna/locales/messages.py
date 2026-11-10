from __future__ import annotations

# UI chrome strings. Keys are stable; values are locale maps.
MESSAGES: dict[str, dict[str, str]] = {
    # Top-right link on each home area card; the area name follows it,
    # visually hidden, so every link has a distinct accessible name.
    "experience.open_short": {"en": "Open", "uk": "Відкрити"},
    "experience.overview": {"en": "Your health, in view", "uk": "Огляд вашого здоров’я"},
    "experience.days_90": {"en": "90 days", "uk": "90 днів"},
    "experience.alternative_reading": {"en": "Alternative source reading", "uk": "Вимірювання з іншого джерела"},
    "experience.daily_range": {"en": "Daily value range", "uk": "Діапазон денних значень"},
    "experience.source_preference": {"en": "Preferred source", "uk": "Пріоритетне джерело"},
    "experience.source_automatic": {"en": "Automatic selection", "uk": "Автоматичний вибір"},
    "experience.source_unavailable": {"en": "Saved source has no values for this metric", "uk": "У вибраному джерелі немає значень цього показника"},
    "experience.source_save": {"en": "Apply preference", "uk": "Застосувати вибір"},
    "experience.source_switches": {"en": "Source changes in the selected history: {count}", "uk": "Перемикань між джерелами за вибраний період: {count}"},
    "experience.directory": {"en": "Explore every health area", "uk": "Усі напрями здоров’я"},
    "experience.directory_metrics_one": {"en": "{count} result", "uk": "{count} показник"},
    "experience.directory_metrics_few": {"en": "{count} results", "uk": "{count} показники"},
    "experience.directory_metrics_many": {"en": "{count} results", "uk": "{count} показників"},
    "experience.directory_documents_one": {"en": "{count} document", "uk": "{count} документ"},
    "experience.directory_documents_few": {"en": "{count} documents", "uk": "{count} документи"},
    "experience.directory_documents_many": {"en": "{count} documents", "uk": "{count} документів"},
    "experience.metrics": {"en": "Metrics in your record", "uk": "Показники у вашій картці"},
    "experience.no_reading": {"en": "No measurements yet", "uk": "Вимірювань ще немає"},
    "experience.no_reading_body": {"en": "Add a report or device export to start this part of your record.", "uk": "Додайте документ або експорт із пристрою, щоб заповнити цей розділ картки."},
    "experience.overview_trend": {"en": "Recorded history; open the metric for exact dates and values.", "uk": "Історія значень. Точні дати й значення є на сторінці показника."},
    "experience.area_navigation": {"en": "Health area navigation", "uk": "Навігація за напрямами здоров’я"},
    "experience.blood.title": {"en": "Read your blood results together", "uk": "Усі аналізи крові поруч"},
    "experience.blood.body": {"en": "Follow blood counts, iron and clotting across reports. Each result keeps its laboratory range, review status and published guidance.", "uk": "Стежте за показниками крові, заліза та згортання з різних документів. Кожен результат зберігає норму лабораторії, стан звірки й опубліковані настанови."},
    "experience.heart.title": {"en": "Pressure, rhythm and everyday heart data", "uk": "Тиск, ритм і щоденні дані про серце"},
    "experience.heart.body": {"en": "Explore cuff readings, heart recordings and related tests. Device measurements and clinical conclusions remain clearly identified.", "uk": "Переглядайте вимірювання тонометра, записи роботи серця та пов’язані аналізи. Дані з пристроїв і клінічні висновки завжди чітко позначені."},
    "experience.activity.title": {"en": "See the rhythm of your movement", "uk": "Ритм вашої активності"},
    "experience.activity.body": {"en": "Daily movement, exercise and fitness in one timeline. Compare recorded days and longer averages, then inspect the device behind each value.", "uk": "Щоденна активність, тренування й фізична форма на одній шкалі часу. Порівнюйте окремі дні із середніми за довший період і дивіться, з якого пристрою кожне значення."},
    "experience.sleep.title": {"en": "A clearer picture of your nights", "uk": "Ваш сон як на долоні"},
    "experience.sleep.body": {"en": "Look at recorded sleep duration, stage estimates and recovery measurements together. Missing nights stay visible as gaps.", "uk": "Дивіться разом тривалість сну, оцінку його стадій і показники відновлення. Ночі без даних видно на графіку як пропуски."},
    "experience.key_readings": {"en": "A starting point", "uk": "З чого почати"},
    "experience.recording_window": {"en": "Recording window", "uk": "Період записів"},
    "experience.coverage": {"en": "{recorded} of {total} days recorded", "uk": "Дні з даними: {recorded} із {total}"},
    "experience.coverage_note": {"en": "A gap means no record. It is never counted as zero.", "uk": "Пропуск означає, що даних немає. Його ніколи не рахують як нуль."},
    "experience.window_note": {"en": "Periods end on the latest recorded day, which may differ from today.", "uk": "Період завершується останнім днем із даними, а це не обов’язково сьогодні."},
    "experience.inspect_days": {"en": "Inspect daily values", "uk": "Переглянути щоденні значення"},
    "experience.period_summary": {"en": "In this period", "uk": "За цей період"},
    "experience.recorded_days": {"en": "Recorded days", "uk": "Дні з даними"},
    "experience.average": {"en": "Daily mean", "uk": "Середнє за день"},
    "experience.minimum": {"en": "Lowest daily value", "uk": "Найменше денне значення"},
    "experience.maximum": {"en": "Highest daily value", "uk": "Найбільше денне значення"},
    "experience.recorded_values": {"en": "Recorded values", "uk": "Записані значення"},
    "experience.source_policy": {"en": "How sources become one timeline", "uk": "Як джерела зводяться в одну історію"},
    "experience.source_policy_body": {"en": "The timeline uses one selected source for each metric and day. Overlapping device totals are not added together. Other sources remain available for comparison.", "uk": "Для кожного показника й кожного дня ми беремо дані лише з одного джерела. Підсумки з пристроїв, що перетинаються, не додаються. Інші джерела можна переглянути для порівняння."},
    "experience.source_compare": {"en": "Compare sources", "uk": "Порівняти джерела"},
    "experience.history_jump": {"en": "Exact history", "uk": "Точні значення"},
    "experience.trend_jump": {"en": "Trend", "uk": "Динаміка"},
    "experience.guidance_jump": {"en": "Guidance & context", "uk": "Настанови й контекст"},
    "experience.reading_navigation": {"en": "Reading sections", "uk": "Розділи показника"},
    "experience.area_sections": {"en": "Explore this area", "uk": "Розділи цього напряму"},
    "experience.activity.purpose": {"en": "Daily movement and recorded workouts.", "uk": "Щоденна активність і записані тренування."},
    "experience.sleep.purpose": {"en": "Sleep duration, stages and recovery over time.", "uk": "Тривалість сну, його стадії та відновлення в динаміці."},
    "experience.mobility.purpose": {"en": "Walking patterns and mobility over time.", "uk": "Характер ходьби та рухливість у динаміці."},
    "experience.units_note": {"en": "Each value keeps its recorded unit. A change is descriptive, not a diagnosis.", "uk": "Кожне значення показано в тих одиницях, у яких його записано. Зміни лише описують дані, це не діагноз."},
    # Brand / shell
    "brand.name": {"en": "Anamna", "uk": "Anamna"},
    "brand.tagline": {"en": "personal health record", "uk": "особиста медична картка"},
    "brand.aria": {"en": "Anamna dashboard", "uk": "Головна сторінка Anamna"},
    "nav.primary": {"en": "Primary navigation", "uk": "Основна навігація"},
    "nav.menu": {"en": "Menu", "uk": "Меню"},
    "nav.account": {"en": "Account and settings", "uk": "Обліковий запис і налаштування"},
    "nav.profile": {"en": "Profile", "uk": "Профіль"},
    "nav.skip": {"en": "Skip to content", "uk": "Перейти до вмісту"},
    "nav.overview": {"en": "Home", "uk": "Головна"},
    "nav.metrics": {"en": "Find results", "uk": "Знайти результати"},
    "nav.documents": {"en": "Documents", "uk": "Документи"},
    "nav.chat": {"en": "Chat", "uk": "Чат"},
    "nav.upload": {"en": "Upload", "uk": "Завантажити"},
    "nav.review": {"en": "Review", "uk": "Перевірка"},
    "nav.about": {"en": "How it works", "uk": "Як це працює"},
    "nav.devices": {"en": "Devices", "uk": "Пристрої"},
    "nav.sign_out": {"en": "Sign out", "uk": "Вийти"},
    "lang.en": {"en": "EN", "uk": "EN"},
    "lang.uk": {"en": "UK", "uk": "УКР"},
    "lang.switch": {"en": "Language", "uk": "Мова"},
    "theme.aria": {"en": "Colour theme", "uk": "Кольорова тема"},
    "theme.light": {"en": "Light theme", "uk": "Світла тема"},
    "theme.dark": {"en": "Dark theme", "uk": "Темна тема"},
    "theme.system": {"en": "Follow system setting", "uk": "Як у системі"},
    "lang.aria": {"en": "Switch language", "uk": "Змінити мову"},

    # Login
    "login.title": {"en": "Sign in · Anamna", "uk": "Вхід · Anamna"},
    "login.eyebrow": {
        "en": "Personal medical evidence, organized",
        "uk": "Ваші медичні дані в порядку",
    },
    "login.heading": {
        "en": "Your history should remain traceable to the page it came from.",
        "uk": "Кожне значення можна простежити до сторінки, з якої його взято.",
    },
    "login.lead": {
        "en": "Anamna keeps lab values, narrative reports, original vendor ranges and source files connected. Without pretending automated extraction is certainty.",
        "uk": "Anamna зберігає разом лабораторні показники, висновки лікарів, норми лабораторій і оригінали файлів. І не видає автоматичне зчитування за безпомилкове.",
    },
    "login.step1": {"en": "Immutable source", "uk": "Незмінний оригінал"},
    "login.step2": {"en": "Structured result", "uk": "Структурований результат"},
    "login.step3": {"en": "Your check", "uk": "Ваша звірка"},
    "login.heading_form": {"en": "Sign in", "uk": "Увійти"},
    "login.muted": {
        "en": "Use your local Anamna account.",
        "uk": "Використовуйте локальний обліковий запис Anamna.",
    },
    "login.email": {"en": "Email", "uk": "Ел. пошта"},
    "login.password": {"en": "Password", "uk": "Пароль"},
    "login.submit": {"en": "Open my record", "uk": "Відкрити мою картку"},
    "login.steps_heading": {"en": "How your record is kept", "uk": "Як ми ведемо вашу картку"},
    "login.step1_body": {
        "en": "Every uploaded file is stored unchanged, so each number can be traced back to the page it came from.",
        "uk": "Ми зберігаємо кожен завантажений файл без змін, тож будь-яке число можна простежити до сторінки, з якої його взято.",
    },
    "login.step2_body": {
        "en": "Values are read into structured results: name, number, unit and the lab's reference range.",
        "uk": "Програма зчитує значення й упорядковує їх: назва, число, одиниця та референтний інтервал лабораторії.",
    },
    "login.step3_body": {
        "en": "Anything read automatically stays provisional until you check it against the source.",
        "uk": "Усе, що зчитано автоматично, лишається попереднім, доки ви не звірите це з оригіналом.",
    },
    "login.forgot": {
        "en": "Forgot your password? Ask the administrator.",
        "uk": "Забули пароль? Зверніться до адміністратора.",
    },
    "login.error": {"en": "Invalid email or password", "uk": "Неправильна адреса пошти або пароль"},
    "login.error_throttled": {
        "en": "Too many failed sign-in attempts from this address. Wait 15 minutes and try again.",
        "uk": "Забагато невдалих спроб входу з цієї адреси. Зачекайте 15 хвилин і спробуйте ще раз.",
    },
    "auth.error_cross_site": {
        "en": "This form can only be submitted from this site.",
        "uk": "Цю форму можна надіслати лише з цього сайту.",
    },
    "profile.error_password_throttled": {
        "en": "Too many wrong attempts. Wait 15 minutes and try again.",
        "uk": "Забагато невдалих спроб. Зачекайте 15 хвилин і спробуйте ще раз.",
    },
    "login.register_prompt": {"en": "New here?", "uk": "Вперше тут?"},
    "login.register_link": {"en": "Create an account", "uk": "Створити обліковий запис"},
    "login.registration_closed": {
        "en": "Sign-up is closed on this server. Ask an administrator for an account.",
        "uk": "Реєстрацію на цьому сервері закрито. Щоб отримати обліковий запис, зверніться до адміністратора.",
    },

    # Registration
    "register.title": {"en": "Create account · Anamna", "uk": "Реєстрація · Anamna"},
    "register.heading_form": {"en": "Create your account", "uk": "Новий обліковий запис"},
    "register.muted": {
        "en": "Your records stay on this server, owned by you alone.",
        "uk": "Ваші записи залишаються на цьому сервері й належать лише вам.",
    },
    "register.name": {"en": "Display name", "uk": "Ваше ім’я"},
    "register.submit": {"en": "Create account", "uk": "Створити обліковий запис"},
    "register.have_account": {"en": "Already have an account?", "uk": "Вже маєте обліковий запис?"},
    "register.sign_in_link": {"en": "Sign in", "uk": "Увійти"},
    "register.error_exists": {
        "en": "An account with this email already exists",
        "uk": "Обліковий запис із такою адресою пошти вже існує",
    },
    "register.error_password": {
        "en": "Password must contain at least 10 characters",
        "uk": "Пароль має містити щонайменше 10 символів",
    },
    "register.error_invalid": {
        "en": "Enter your email and a display name",
        "uk": "Вкажіть електронну пошту та ім’я",
    },
    "register.closed": {
        "en": "Sign-up is closed on this server. Ask an administrator for an account.",
        "uk": "Реєстрацію на цьому сервері закрито. Щоб отримати обліковий запис, зверніться до адміністратора.",
    },

    # First-run setup: the page an empty database leads to
    "setup.title": {"en": "First-run setup", "uk": "Перше налаштування"},
    "setup.heading": {"en": "Set up this server", "uk": "Налаштування сервера"},
    "setup.lead": {
        "en": "This server has no accounts yet. Create the first one here.",
        "uk": "На цьому сервері ще немає жодного облікового запису. Створіть перший тут.",
    },
    "setup.what_heading": {"en": "What happens", "uk": "Що станеться"},
    "setup.point_admin": {
        "en": "The account you create here becomes the administrator. It can add people, block accounts and decide who may sign up.",
        "uk": "Обліковий запис, який ви тут створите, стане адміністратором. Він може додавати людей, блокувати облікові записи й вирішувати, хто може реєструватися.",
    },
    "setup.point_closed": {
        "en": "After that, sign-up stays closed. Other people get an account only when the administrator adds them or opens registration on the People page.",
        "uk": "Після цього реєстрація залишається закритою. Інші люди отримають обліковий запис, лише коли адміністратор додасть їх або відкриє реєстрацію на сторінці «Користувачі».",
    },
    "setup.point_record": {
        "en": "Your own medical record is created in the same step, with the details below. You can change them later in your profile.",
        "uk": "Разом з обліковим записом створюється ваша медична картка з даними нижче. Пізніше їх можна змінити в профілі.",
    },
    "setup.point_once": {
        "en": "This page works only once. As soon as the first account exists it closes, and the usual sign-in page takes its place.",
        "uk": "Ця сторінка працює лише один раз. Щойно з’явиться перший обліковий запис, вона закриється, а натомість відкриватиметься звичайна сторінка входу.",
    },
    "setup.code_heading": {"en": "Setup code", "uk": "Код налаштування"},
    "setup.code_label": {"en": "One-time setup code", "uk": "Одноразовий код налаштування"},
    "setup.code_why": {
        "en": "The code proves you run this server, so a stranger who finds the address first cannot become its administrator.",
        "uk": "Код підтверджує, що сервером керуєте ви. Так стороння людина, яка першою знайде адресу, не зможе стати адміністратором.",
    },
    "setup.code_where_log": {
        "en": "The server printed it to its log when it started, on a line that begins like this:",
        "uk": "Сервер записав його в журнал під час запуску, у рядку, що починається так:",
    },
    "setup.code_where_container": {
        "en": "In a container, show the log with:",
        "uk": "Якщо сервер працює в контейнері, журнал можна переглянути командою:",
    },
    "setup.code_where_env": {
        "en": "Whoever installed this server chose the code in the ANAMNA_SETUP_CODE setting. Ask them for it.",
        "uk": "Код вибрала людина, яка встановлювала сервер, у параметрі ANAMNA_SETUP_CODE. Попросіть його в неї.",
    },
    "setup.cli_hint": {
        "en": "Working on the server itself? This command creates the first account without a code:",
        "uk": "Працюєте безпосередньо на сервері? Ця команда створює перший обліковий запис без коду:",
    },
    "setup.account_heading": {"en": "Your account", "uk": "Ваш обліковий запис"},
    "setup.record_heading": {"en": "Your record", "uk": "Ваша картка"},
    "setup.optional": {"en": "optional", "uk": "необов’язково"},
    "setup.submit": {"en": "Create administrator account", "uk": "Створити обліковий запис адміністратора"},
    "setup.error_code": {
        "en": "The setup code does not match. Copy it again and try once more.",
        "uk": "Код налаштування не збігається. Скопіюйте його ще раз і повторіть спробу.",
    },
    "setup.error_throttled": {
        "en": "Too many wrong setup codes. Wait {minutes}, then try again.",
        "uk": "Забагато неправильних кодів налаштування. Зачекайте {minutes} і спробуйте ще раз.",
    },
    "setup.error_taken": {
        "en": "This server was set up a moment ago from another browser. Sign in with that account, or ask its administrator for one.",
        "uk": "Цей сервер щойно налаштували з іншого браузера. Увійдіть у той обліковий запис або попросіть обліковий запис в адміністратора.",
    },

    # Administration — accounts on this server
    "nav.admin": {"en": "People", "uk": "Користувачі"},
    "admin.title": {"en": "People · Anamna", "uk": "Користувачі · Anamna"},
    "admin.eyebrow": {"en": "Administration", "uk": "Адміністрування"},
    "admin.heading": {"en": "People on this server", "uk": "Користувачі цього сервера"},
    "admin.lead": {
        "en": "Every account on this installation, what it holds, and who may sign in. "
              "Each person sees only their own record; an administrator manages accounts, "
              "never the medical data inside them.",
        "uk": "Усі облікові записи цієї інсталяції, що вони містять і хто може входити. "
              "Кожна людина бачить лише власну картку; адміністратор керує обліковими "
              "записами, а не медичними даними всередині них.",
    },
    "admin.forbidden": {
        "en": "Administrator access is required for this page",
        "uk": "Ця сторінка доступна лише адміністраторам",
    },
    "admin.role": {"en": "Role", "uk": "Роль"},
    "admin.role_admin": {"en": "Administrator", "uk": "Адміністратор"},
    "admin.role_user": {"en": "Member", "uk": "Користувач"},
    "admin.role_admin_hint": {
        "en": "Manages accounts on this server: adds people, blocks or deletes them, and "
              "decides whether sign-up is open. Cannot read anyone else's medical record.",
        "uk": "Керує обліковими записами на цьому сервері: додає людей, блокує чи видаляє їх, відкриває або закриває реєстрацію. Не має доступу до чужих медичних карток.",
    },
    "admin.role_user_hint": {
        "en": "Keeps their own medical record: uploads documents, reviews extractions, and "
              "chooses who else may view it. Sees no one else's account.",
        "uk": "Веде власну медичну картку: завантажує документи, звіряє зчитані дані й вирішує, хто ще може її переглядати. Чужих облікових записів не бачить.",
    },
    "admin.legend_summary": {
        "en": "What these roles, states and counts mean",
        "uk": "Що означають ролі, стани й числа",
    },
    "admin.status": {"en": "Status", "uk": "Стан"},
    "admin.status_active": {"en": "Active", "uk": "Активний"},
    "admin.status_blocked": {"en": "Blocked", "uk": "Заблокований"},
    "admin.status_blocked_hint": {
        "en": "Blocked: cannot sign in, and any open session ends immediately. The record is "
              "kept and returns untouched when the account is unblocked.",
        "uk": "Заблоковано: увійти неможливо, а всі відкриті сеанси завершуються одразу. Картка зберігається й після розблокування повертається без змін.",
    },
    "admin.you": {"en": "You", "uk": "Ви"},
    "admin.th_person": {"en": "Person", "uk": "Людина"},
    "admin.th_activity": {"en": "Record", "uk": "Картка"},
    "admin.th_actions": {"en": "Actions", "uk": "Дії"},
    "admin.documents": {"en": "Documents", "uk": "Документи"},
    "admin.documents_hint": {
        "en": "Source files uploaded to this account. Each PDF, photo or vendor export.",
        "uk": "Оригінали файлів, завантажені в цей обліковий запис: кожен PDF, фото чи експорт із лабораторії або пристрою.",
    },
    "admin.observations": {"en": "Results", "uk": "Результати"},
    "admin.observations_hint": {
        "en": "Individual measurements read out of those documents. One per lab value.",
        "uk": "Окремі значення, зчитані з цих документів: по одному на кожен лабораторний показник.",
    },
    "admin.storage": {"en": "Storage", "uk": "Обсяг"},
    "admin.storage_hint": {
        "en": "Disk taken by this account's source files.",
        "uk": "Скільки місця на диску займають оригінали файлів цього облікового запису.",
    },
    "admin.open_reviews": {"en": "Awaiting review", "uk": "Чекають на звірку"},
    "admin.open_reviews_hint": {
        "en": "Extractions this person has not yet confirmed by eye. Nothing is treated as "
              "verified until they do.",
        "uk": "Зчитані дані, які людина ще не звірила власноруч. Доки вона цього не зробить, жодне значення не вважається звіреним.",
    },
    "admin.live_sessions": {"en": "Signed in now", "uk": "Зараз у системі"},
    "admin.live_sessions_hint": {
        "en": "Unexpired sessions: browsers currently holding a valid sign-in for this account.",
        "uk": "Чинні сеанси: браузери, у яких зараз виконано вхід у цей обліковий запис.",
    },
    "admin.joined": {"en": "Joined", "uk": "Дата реєстрації"},
    "admin.last_login": {"en": "Last sign-in", "uk": "Останній вхід"},
    "admin.never": {"en": "Never signed in", "uk": "Входу ще не було"},
    "admin.block": {"en": "Block", "uk": "Заблокувати"},
    "admin.unblock": {"en": "Unblock", "uk": "Розблокувати"},
    "admin.promote": {"en": "Make administrator", "uk": "Зробити адміністратором"},
    "admin.demote": {"en": "Remove administrator", "uk": "Зняти права адміністратора"},
    "admin.delete": {"en": "Delete", "uk": "Видалити"},
    "admin.delete_confirm": {
        "en": "Delete this account and every document, result and file it owns? This cannot be undone.",
        "uk": "Видалити цей обліковий запис разом з усіма його документами, результатами й файлами? Цю дію не можна скасувати.",
    },
    "admin.self_note": {
        "en": "You cannot block, demote or delete your own account.",
        "uk": "Ви не можете заблокувати, понизити чи видалити власний обліковий запис.",
    },
    "admin.set_password": {"en": "Set a new password", "uk": "Задати новий пароль"},
    "admin.set_password_lead": {
        "en": "For someone who forgot theirs. Every browser they are signed in on is signed out. "
              "Tell them the new password by some other channel and ask them to change it on their "
              "profile page: until they do, you know the password to their medical record.",
        "uk": "Для того, хто забув свій. Усі браузери, де виконано вхід у цей запис, буде "
              "відключено. Повідомте новий пароль іншим каналом і попросіть змінити його на сторінці "
              "профілю - доки цього не зроблено, ви знаєте пароль до їхньої медичної картки.",
    },
    "admin.set_password_new": {"en": "New password", "uk": "Новий пароль"},
    "admin.set_password_confirm": {"en": "Repeat the new password", "uk": "Повторіть новий пароль"},
    "admin.set_password_submit": {"en": "Set password and sign them out", "uk": "Задати пароль і завершити сеанси"},
    "admin.set_password_aria": {"en": "Set a new password for {name}", "uk": "Задати новий пароль для {name}"},
    "admin.self_password_note": {
        "en": "Change your own password on your profile page, where your current password is asked first.",
        "uk": "Свій пароль змініть на сторінці профілю: там спершу потрібно ввести поточний.",
    },
    "admin.add_eyebrow": {"en": "New account", "uk": "Новий обліковий запис"},
    "admin.add_heading": {"en": "Add a person", "uk": "Додати користувача"},
    "admin.add_lead": {
        "en": "Creates the account and the empty medical record it writes into. Send the password "
              "by some other channel, and ask them to replace it on their own profile page once "
              "they are in: until they do, you know the password to their medical record.",
        "uk": "Створює обліковий запис і порожню медичну картку, у яку він пише. Надішліть пароль "
              "іншим каналом і попросіть замінити його на сторінці профілю після входу - доки "
              "цього не зроблено, ви знаєте пароль до їхньої медичної картки.",
    },
    "admin.add_email": {"en": "Email", "uk": "Електронна пошта"},
    "admin.add_name": {"en": "Display name", "uk": "Ім’я"},
    "admin.add_password": {"en": "Initial password", "uk": "Початковий пароль"},
    "admin.add_password_hint": {
        "en": "At least {count} characters.",
        "uk": "Кількість символів: щонайменше {count}.",
    },
    "admin.add_submit": {"en": "Create account", "uk": "Створити обліковий запис"},
    "admin.registration_eyebrow": {"en": "Sign-up", "uk": "Реєстрація"},
    "admin.registration_heading": {"en": "Open registration", "uk": "Відкрита реєстрація"},
    "admin.registration_lead": {
        "en": "When open, anyone who can reach this server may create their own account from "
              "the sign-in page. When closed, only an administrator can add people. Closed is "
              "the default, and the right setting for a server on the public internet.",
        "uk": "Коли відкрито, будь-хто, хто має доступ до сервера, може створити обліковий "
              "запис зі сторінки входу. Коли закрито, людей додає лише адміністратор. За "
              "замовчуванням закрито, і це правильний вибір для сервера в інтернеті.",
    },
    "admin.registration_on": {"en": "Open to anyone", "uk": "Відкрита для всіх"},
    "admin.registration_off": {"en": "Administrator only", "uk": "Лише через адміністратора"},
    "admin.registration_open_action": {"en": "Open registration", "uk": "Відкрити реєстрацію"},
    "admin.registration_close_action": {"en": "Close registration", "uk": "Закрити реєстрацію"},
    "admin.totals_people": {"en": "Accounts", "uk": "Облікові записи"},
    "admin.list_heading": {"en": "All accounts", "uk": "Усі облікові записи"},
    # Ukrainian selects between three forms, so the count is never interpolated
    # into one fixed noun.
    "admin.list_count": {"en": "{count} accounts", "uk": "Облікових записів: {count}"},
    "admin.list_count_one": {"en": "{count} account", "uk": "{count} обліковий запис"},
    "admin.list_count_few": {"en": "{count} accounts", "uk": "{count} облікові записи"},
    "admin.list_count_many": {"en": "{count} accounts", "uk": "{count} облікових записів"},
    "admin.error_invalid": {
        "en": "Enter a valid email and a display name",
        "uk": "Вкажіть правильну адресу пошти та ім’я",
    },
    "admin.error_password": {
        "en": "Password must contain at least 10 characters",
        "uk": "Пароль має містити щонайменше 10 символів",
    },
    "admin.error_exists": {
        "en": "An account with this email already exists",
        "uk": "Обліковий запис із такою адресою пошти вже існує",
    },
    "admin.error_unknown": {"en": "No such account", "uk": "Такого облікового запису немає"},
    "admin.error_self": {
        "en": "You cannot block, demote or delete your own account",
        "uk": "Свій обліковий запис не можна заблокувати, видалити чи позбавити прав адміністратора",
    },
    "admin.error_password_match": {
        "en": "The two new passwords do not match. Nothing was changed.",
        "uk": "Нові паролі не збігаються. Нічого не змінено.",
    },
    "admin.error_password_self": {
        "en": "Change your own password on your profile page; it asks for your current one first.",
        "uk": "Свій пароль змініть на сторінці профілю: там спершу потрібно ввести поточний.",
    },
    "admin.error_last_admin": {
        "en": "This is the only administrator. Promote someone else first, or the server would "
              "have nobody able to manage accounts.",
        "uk": "Це єдиний адміністратор. Спершу призначте адміністратором когось іншого, інакше на сервері не залишиться нікого, хто може керувати обліковими записами.",
    },
    "admin.done_added": {"en": "Account created", "uk": "Обліковий запис створено"},
    "admin.done_blocked": {"en": "Account blocked", "uk": "Обліковий запис заблоковано"},
    "admin.done_unblocked": {"en": "Account unblocked", "uk": "Обліковий запис розблоковано"},
    "admin.done_promoted": {"en": "Now an administrator", "uk": "Призначено адміністратором"},
    "admin.done_demoted": {"en": "No longer an administrator", "uk": "Права адміністратора знято"},
    "admin.done_password_set": {
        "en": "New password set. That person was signed out everywhere and must sign in with it.",
        "uk": "Новий пароль задано. Усі сеанси цього користувача завершено, тепер увійти можна лише з новим паролем.",
    },
    "admin.done_deleted": {
        "en": "Account and its record deleted",
        "uk": "Обліковий запис і його картку видалено",
    },
    "admin.done_registration_open": {
        "en": "Registration is open to anyone",
        "uk": "Реєстрацію відкрито для всіх",
    },
    "admin.done_registration_closed": {
        "en": "Registration is closed",
        "uk": "Реєстрацію закрито",
    },

    # Profile and sharing
    "profile.title": {"en": "Profile · Anamna", "uk": "Профіль · Anamna"},
    "profile.eyebrow": {"en": "Account and access", "uk": "Обліковий запис і доступ"},
    "profile.heading": {"en": "Your profile", "uk": "Ваш профіль"},
    "profile.lead": {
        "en": "Personal details used across the record, and who may read it.",
        "uk": "Особисті дані для вашої картки та люди, які можуть її переглядати.",
    },
    "profile.saved": {"en": "Profile saved", "uk": "Профіль збережено"},
    "profile.tabs_label": {"en": "Profile sections", "uk": "Розділи профілю"},
    "profile.tab_personal": {"en": "Personal", "uk": "Особисті дані"},
    "profile.tab_sharing": {"en": "Sharing", "uk": "Спільний доступ"},
    "profile.tab_tokens": {"en": "Access keys", "uk": "Ключі доступу"},
    "profile.tab_security": {"en": "Security", "uk": "Безпека"},
    "profile.password_eyebrow": {"en": "Sign-in", "uk": "Вхід"},
    "profile.password_heading": {"en": "Change your password", "uk": "Зміна пароля"},
    "profile.password_lead": {
        "en": "If an administrator created this account, they chose its first password and still "
              "know it. Changing it here signs out every other browser holding this account.",
        "uk": "Якщо обліковий запис створив адміністратор, то перший пароль задав він і досі його знає. Після зміни пароля всі інші браузери вийдуть із цього облікового запису.",
    },
    "profile.password_current": {"en": "Current password", "uk": "Поточний пароль"},
    "profile.password_new": {"en": "New password", "uk": "Новий пароль"},
    "profile.password_confirm": {"en": "Repeat the new password", "uk": "Повторіть новий пароль"},
    "profile.password_hint": {
        "en": "At least {count} characters.",
        "uk": "Мінімальна кількість символів: {count}.",
    },
    "profile.password_submit": {"en": "Change password", "uk": "Змінити пароль"},
    "profile.password_saved": {
        "en": "Password changed. Other browsers signed in to this account have been signed out.",
        "uk": "Пароль змінено. Сеанси в усіх інших браузерах завершено.",
    },
    "profile.error_password_current": {
        "en": "That is not your current password",
        "uk": "Поточний пароль неправильний",
    },
    "profile.error_password_match": {
        "en": "The two new passwords do not match",
        "uk": "Нові паролі не збігаються",
    },
    "profile.error_password_short": {
        "en": "Password must contain at least 10 characters",
        "uk": "Пароль має містити щонайменше 10 символів",
    },
    "profile.sessions_heading": {"en": "Where you are signed in", "uk": "Активні сеанси"},
    "profile.sessions_lead": {
        "en": "Every browser that holds this account right now. Sign out any you do not recognise. "
              "it will need the password to get back in.",
        "uk": "Усі браузери, де зараз відкрито цей обліковий запис. Якщо якийсь не впізнаєте, завершіть його сеанс: щоб увійти знову, там знадобиться пароль.",
    },
    "profile.session_current": {"en": "This browser", "uk": "Цей браузер"},
    "profile.session_current_hint": {
        "en": "To sign out here, use Sign out in the menu.",
        "uk": "Щоб вийти тут, натисніть «Вийти» в меню.",
    },
    "profile.session_device": {"en": "{browser} on {platform}", "uk": "{browser} на {platform}"},
    "profile.session_unknown_device": {"en": "Unrecognised browser", "uk": "Невідомий браузер"},
    "profile.session_unrecorded_device": {
        "en": "Browser not recorded (signed in before this list existed)",
        "uk": "Браузер не збережено (ви ввійшли ще до появи цього списку)",
    },
    "profile.session_unknown_platform": {"en": "an unknown system", "uk": "невідомій системі"},
    "profile.session_guest": {
        "en": "Opened with the guest link \"{label}\"",
        "uk": "Відкрито гостьовим посиланням «{label}»",
    },
    "profile.session_signed_in": {"en": "Signed in {date}", "uk": "Вхід: {date}"},
    "profile.session_expires": {"en": "Ends by itself {date}", "uk": "Завершиться автоматично {date}"},
    "profile.session_sign_out": {"en": "Sign out this session", "uk": "Завершити сеанс"},
    "profile.session_sign_out_confirm": {
        "en": "Sign that browser out? Whoever uses it will need the password again.",
        "uk": "Вийти з облікового запису в тому браузері? Щоб повернутися, там знову знадобиться пароль.",
    },
    "profile.session_sign_out_others": {"en": "Sign out everywhere else", "uk": "Завершити всі інші сеанси"},
    "profile.session_sign_out_others_confirm": {
        "en": "Sign out every other browser and guest visit? Only this browser stays signed in.",
        "uk": "Завершити всі інші сеанси, зокрема гостьові? Вхід залишиться лише в цьому браузері.",
    },
    "profile.session_saved_one": {"en": "That session is signed out.", "uk": "Сеанс завершено."},
    "profile.session_saved_others": {
        "en": "Every other session is signed out.",
        "uk": "Усі інші сеанси завершено.",
    },
    "profile.error_session": {
        "en": "That session was not found. It may have ended already. The list below is current.",
        "uk": "Сеанс не знайдено: можливо, він уже завершився. Нижче актуальний список.",
    },
    "profile.personal_eyebrow": {"en": "Personal data", "uk": "Особисті дані"},
    "profile.personal_heading": {"en": "Personal details", "uk": "Особисті відомості"},
    "profile.full_name": {"en": "Full name", "uk": "Повне ім’я"},
    "profile.dob": {"en": "Date of birth", "uk": "Дата народження"},
    "profile.blood_type": {"en": "Blood type", "uk": "Група крові"},
    "profile.blood_unknown": {"en": "Unknown", "uk": "Невідомо"},
    "profile.blood_from_lab": {
        "en": "Determined by the laboratory result from {date}.",
        "uk": "Визначено за результатом аналізу від {date}.",
    },
    "profile.blood_open_result": {"en": "Open the result", "uk": "Відкрити результат"},
    "profile.save": {"en": "Save", "uk": "Зберегти"},
    "profile.error_name": {"en": "Enter your full name", "uk": "Введіть повне ім’я"},
    "profile.error_dob": {
        "en": "Date of birth must be a valid past date",
        "uk": "Вкажіть дійсну дату народження. Вона не може бути в майбутньому.",
    },
    "profile.error_blood": {"en": "Choose a valid blood type", "uk": "Оберіть групу крові зі списку"},
    "profile.sharing_eyebrow": {"en": "Access", "uk": "Доступ"},
    "profile.sharing_heading": {"en": "Who can view my record", "uk": "Хто може переглядати мою картку"},
    "profile.sharing_lead": {
        "en": "People on this list can open your record read-only after signing in with their own account.",
        "uk": "Люди з цього списку бачать вашу картку без права змін, коли входять у свій обліковий запис.",
    },
    "profile.shares_empty": {
        "en": "No one else can view your record.",
        "uk": "Ніхто інший не може переглядати вашу картку.",
    },
    "profile.share_email": {"en": "Email to allow", "uk": "Ел. пошта людини"},
    "profile.share_add": {"en": "Allow viewing", "uk": "Дозволити перегляд"},
    "profile.share_remove": {"en": "Remove", "uk": "Закрити доступ"},
    "profile.error_share_email": {"en": "Enter a valid email", "uk": "Введіть правильну адресу ел. пошти"},
    "profile.error_share_self": {
        "en": "You already have access to your own record",
        "uk": "Це ваша картка, доступ до неї у вас уже є",
    },
    "profile.error_share_unknown": {
        "en": "No account here uses that address. The person needs an account on this server first; ask the administrator to add them, then share again.",
        "uk": "На цьому сервері немає облікового запису з такою адресою. Спершу людині потрібен обліковий запис: попросіть адміністратора додати її, а потім поділіться ще раз.",
    },
    "profile.shared_with_me_eyebrow": {"en": "Shared with me", "uk": "Доступні мені"},
    "profile.shared_with_me_heading": {"en": "Records shared with me", "uk": "Картки, до яких мені надали доступ"},
    "profile.shared_with_me_empty": {
        "en": "No one has shared a record with you.",
        "uk": "Вам ще ніхто не надав доступу до своєї картки.",
    },
    "profile.view_record": {"en": "View record", "uk": "Відкрити картку"},
    "profile.back_to_own": {"en": "Back to my record", "uk": "Повернутися до моєї картки"},
    "viewing.banner": {
        "en": "Viewing {name}'s record (read-only)",
        "uk": "Ви переглядаєте картку: {name} (лише перегляд)",
    },
    "viewing.back": {"en": "Return to my record", "uk": "Повернутися до моєї картки"},

    # Profile: the person behind the record
    "profile.nickname": {"en": "Nickname", "uk": "Як до вас звертатися"},
    "profile.nickname_hint": {
        "en": "What the header calls you. Your full name stays on the record itself, where a clinician needs it.",
        "uk": "Це ім’я показуємо вгорі сторінки. Повне ім’я залишається в самій картці, де воно потрібне лікареві.",
    },
    "profile.not_stated": {"en": "Not stated", "uk": "Не вказано"},
    # Demographics fieldset: date of birth, sex at birth and blood group decide
    # which official reference intervals judge the rest of the record.
    "profile.demographics_heading": {"en": "Demographics", "uk": "Демографічні дані"},
    "profile.demographics_lead": {
        "en": "Date of birth, sex at birth and blood group. Official reference intervals for many tests depend on age and sex, so these fields decide which published ranges your results are compared against.",
        "uk": "Дата народження, стать при народженні та група крові. Офіційні референтні інтервали багатьох аналізів залежать від віку і статі, тож саме ці поля визначають, з якими опублікованими інтервалами ми порівнюємо ваші результати.",
    },
    "profile.dob_hint": {
        "en": "Many reference intervals are age-specific. Without a date of birth, results that depend on age are not compared against official guidance rather than guessed.",
        "uk": "Багато референтних інтервалів залежать від віку. Без дати народження ми не порівнюємо такі результати з офіційними настановами, щоб не вгадувати.",
    },
    "profile.sex": {"en": "Sex at birth", "uk": "Стать при народженні"},
    "profile.sex_hint": {
        "en": "Blood counts, liver enzymes, ferritin, VO₂ max and waist circumference have different official reference intervals for men and women. Recording sex at birth applies the interval published for your sex; leaving it blank withholds those comparisons rather than guessing.",
        "uk": "Показники загального аналізу крові, печінкові ферменти, феритин, VO₂ max та обхват талії мають різні офіційні референтні інтервали для чоловіків і жінок. Якщо вказати стать при народженні, ми застосуємо інтервал, опублікований для вашої статі. Якщо поле порожнє, ми не робимо цих порівнянь, щоб не вгадувати.",
    },
    "profile.timezone": {"en": "Time zone", "uk": "Часовий пояс"},
    "profile.timezone_hint": {
        "en": "IANA name, e.g. Europe/Kyiv.",
        "uk": "Назва за базою IANA, наприклад Europe/Kyiv.",
    },
    "profile.error_timezone": {
        "en": "Choose a time zone from the list, for example Europe/Kyiv",
        "uk": "Оберіть часовий пояс зі списку, наприклад Europe/Kyiv",
    },
    "profile.from_device": {
        "en": "Measured {date} by {source}.",
        "uk": "Виміряно {date} пристроєм {source}.",
    },
    "profile.open_measurement": {"en": "Open the measurements", "uk": "Відкрити вимірювання"},
    "profile.error_measurement": {
        "en": "Enter a plausible measurement, or leave the field empty",
        "uk": "Вкажіть реальне значення або залиште поле порожнім",
    },
    "profile.error_choice": {
        "en": "Choose one of the offered options",
        "uk": "Оберіть один із варіантів",
    },
    "profile.body_heading": {"en": "Body measurements", "uk": "Параметри тіла"},
    "profile.body_lead": {
        "en": "Size and weight change what a result means: the same creatinine is normal in one body and raised in another, and drug doses are calculated from these numbers. A measurement your scale or watch already recorded is shown here from that evidence and cannot be typed over.",
        "uk": "Розміри тіла і вага змінюють зміст результату. Той самий креатинін в однієї людини в нормі, а в іншої підвищений, і дози ліків розраховують саме за цими числами. Вимірювання, яке вже записали ваші ваги чи годинник, показано тут із джерелом, і вручну його не перезаписати.",
    },
    "profile.height_cm": {"en": "Height (cm)", "uk": "Зріст (см)"},
    "profile.height_cm_hint": {
        "en": "Used with weight for body mass index and for body surface area, which sets the dose of many medicines.",
        "uk": "Разом із вагою потрібен для індексу маси тіла і площі поверхні тіла, за якою розраховують дози багатьох ліків.",
    },
    "profile.weight_kg": {"en": "Weight (kg)", "uk": "Вага (кг)"},
    "profile.weight_kg_hint": {
        "en": "Dosing, kidney function estimates and body mass index all start here. A trend matters more than one reading.",
        "uk": "З ваги починаються дозування ліків, оцінка функції нирок та індекс маси тіла. Динаміка важить більше за одне вимірювання.",
    },
    "profile.waist_cm": {"en": "Waist circumference (cm)", "uk": "Обхват талії (см)"},
    "profile.waist_cm_hint": {
        "en": "Midway between the lowest rib and the top of the hip bone.",
        "uk": "Посередині між нижнім ребром і верхнім краєм тазової кістки.",
    },
    "profile.chest_cm": {"en": "Chest circumference (cm)", "uk": "Обхват грудної клітки (см)"},
    "profile.chest_cm_hint": {
        "en": "At the widest point, breathing normally.",
        "uk": "У найширшому місці, на спокійному диханні.",
    },
    "profile.hip_cm": {"en": "Hip circumference (cm)", "uk": "Обхват стегон (см)"},
    "profile.hip_cm_hint": {
        "en": "At the widest point of the buttocks.",
        "uk": "У найширшому місці сідниць.",
    },
    "profile.context_heading": {"en": "Personal context", "uk": "Спосіб життя та ризики"},
    "profile.context_lead": {
        "en": "The questions a clinician asks in the first minute and no laboratory report ever answers. Each one changes how a result should be read; none of them leaves this machine.",
        "uk": "Питання, які лікар ставить у першу ж хвилину і на які не відповість жоден лабораторний бланк. Кожна відповідь змінює прочитання результату, і жодна не залишає цього комп’ютера.",
    },
    "profile.activity_level": {"en": "Activity level", "uk": "Рівень активності"},
    "profile.activity_level_hint": {
        "en": "Bands follow the WHO Guidelines on physical activity and sedentary behaviour (2020), which set 150-300 minutes of moderate activity a week for adults. Training raises creatine kinase, haematocrit and resting heart rate in ways that look abnormal without this context.",
        "uk": "Рівні відповідають настановам ВООЗ щодо фізичної активності та малорухливої поведінки (2020): дорослим рекомендовано 150-300 хвилин помірної активності на тиждень. Тренування підвищують креатинкіназу й гематокрит і змінюють пульс у спокої так, що без цього контексту результати схожі на відхилення.",
    },
    "profile.activity_level_sedentary": {"en": "Sedentary: little or no exercise", "uk": "Сидячий: майже без навантажень"},
    "profile.activity_level_light": {"en": "Light: occasional walking or light exercise", "uk": "Легкий: часом ходьба або легкі вправи"},
    "profile.activity_level_moderate": {"en": "Moderate: meets the WHO weekly minimum", "uk": "Помірний: на рівні тижневого мінімуму ВООЗ"},
    "profile.activity_level_active": {"en": "Active: exercises most days", "uk": "Активний: тренування в більшість днів"},
    "profile.activity_level_athlete": {"en": "Athlete: structured daily training", "uk": "Спортивний: щоденні систематичні тренування"},
    "profile.skin_type": {"en": "Skin phototype", "uk": "Фототип шкіри"},
    "profile.skin_type_hint": {
        "en": "The Fitzpatrick scale (Fitzpatrick, Archives of Dermatology, 1988), used by the US FDA for sunscreen labelling and across EU dermatology. It predicts how skin reacts to sun, and it also tells a clinician how much vitamin D the same latitude produces in you.",
        "uk": "Шкала Фіцпатрика (Fitzpatrick, Archives of Dermatology, 1988). На неї спирається FDA (США) у правилах маркування сонцезахисних засобів, її використовують і дерматологи ЄС. Шкала прогнозує, як шкіра реагує на сонце, і підказує лікарю, скільки вітаміну D утворюється у вас на тій самій широті.",
    },
    "profile.skin_type_I": {"en": "I: always burns, never tans", "uk": "I: завжди обгорає, ніколи не засмагає"},
    "profile.skin_type_II": {"en": "II: burns easily, tans minimally", "uk": "II: легко обгорає, засмагає слабко"},
    "profile.skin_type_III": {"en": "III: burns moderately, tans gradually", "uk": "III: помірно обгорає, засмагає поступово"},
    "profile.skin_type_IV": {"en": "IV: burns minimally, tans well", "uk": "IV: обгорає мало, добре засмагає"},
    "profile.skin_type_V": {"en": "V: rarely burns, tans deeply", "uk": "V: рідко обгорає, засмагає дуже темно"},
    "profile.skin_type_VI": {"en": "VI: never burns, deeply pigmented", "uk": "VI: ніколи не обгорає, шкіра темно пігментована"},
    "profile.smoking_status": {"en": "Smoking", "uk": "Куріння"},
    "profile.smoking_status_hint": {
        "en": "The never / former / current categories used by WHO and the US CDC. Smoking shifts the reference range for haemoglobin, white cells and CRP, and it is the single strongest modifier of cardiovascular risk scores.",
        "uk": "Категорії «ніколи / раніше / зараз», якими користуються ВООЗ і CDC (США). Куріння зміщує референтний інтервал гемоглобіну, лейкоцитів і СРБ і з усіх окремих чинників найсильніше впливає на шкали серцево-судинного ризику.",
    },
    "profile.smoking_status_never": {"en": "Never smoked", "uk": "Ніколи не курив(-ла)"},
    "profile.smoking_status_former": {"en": "Former smoker", "uk": "Курив(-ла) раніше"},
    "profile.smoking_status_current": {"en": "Currently smokes", "uk": "Курю зараз"},
    "profile.alcohol_use": {"en": "Alcohol", "uk": "Алкоголь"},
    "profile.alcohol_use_hint": {
        "en": "Bands follow the WHO drinking-risk categories. Alcohol raises GGT, MCV and triglycerides directly, so a result read without it can send someone to a liver clinic for a Friday night.",
        "uk": "Рівні відповідають категоріям ризику вживання алкоголю за ВООЗ. Алкоголь напряму підвищує ГГТ, MCV і тригліцериди, тож без цього контексту через один п’ятничний вечір людину можуть відправити до гепатолога.",
    },
    "profile.alcohol_use_none": {"en": "None", "uk": "Не вживаю"},
    "profile.alcohol_use_occasional": {"en": "Occasional: a few times a month", "uk": "Зрідка: кілька разів на місяць"},
    "profile.alcohol_use_moderate": {"en": "Moderate: weekly, within WHO low-risk limits", "uk": "Помірно: щотижня, у межах низького ризику за ВООЗ"},
    "profile.alcohol_use_frequent": {"en": "Frequent: most days", "uk": "Часто: у більшість днів"},
    # Cardiovascular risk category (reference.clinical_context). LDL, non-HDL
    # and ApoB goals are defined per category; without one they never judge.
    "profile.cv_risk_category": {"en": "Cardiovascular risk category", "uk": "Категорія серцево-судинного ризику"},
    "profile.cv_risk_category_hint": {
        "en": "As assessed by your doctor (SCORE2 in Europe, PREVENT in the US). Leave blank if unknown.",
        "uk": "Як оцінив ваш лікар (SCORE2 у Європі, PREVENT у США). Якщо не знаєте, залиште порожнім.",
    },
    "profile.cv_risk_category_low": {"en": "Low", "uk": "Низький"},
    "profile.cv_risk_category_moderate": {"en": "Moderate", "uk": "Помірний"},
    "profile.cv_risk_category_high": {"en": "High", "uk": "Високий"},
    "profile.cv_risk_category_very_high": {"en": "Very high", "uk": "Дуже високий"},

    # Access credentials
    "nav.admin_tokens": {"en": "Access credentials", "uk": "Ключі доступу"},
    "token.eyebrow": {"en": "Access", "uk": "Доступ"},
    "token.heading": {"en": "Access credentials", "uk": "Ключі доступу"},
    "token.lead": {
        "en": "Three ways in that are not a password: a link you can hand to a doctor for a fortnight, and two keys a program can use to check this instance or read its API. Each one can be renamed, given a new expiry, or revoked here. Revoking it also signs out anyone still using it.",
        "uk": "Три способи входу без пароля: посилання, яке можна дати лікарю на два тижні, і два ключі, якими програма може перевірити цей екземпляр або прочитати його API. Кожен можна перейменувати, змінити термін дії або відкликати тут - відкликання одразу завершує й усі відкриті сеанси.",
    },
    "token.legend_summary": {"en": "What these mean", "uk": "Що це означає"},
    "token.kind": {"en": "Kind", "uk": "Тип"},
    "token.kind_hint": {
        "en": "Pick by what the holder should reach, not by who they are. A credential cannot be widened later, only replaced.",
        "uk": "Обирайте тип за тим, до чого має доступ власник ключа, а не за тим, хто він. Розширити права ключа згодом не можна, його можна лише замінити новим.",
    },
    "token.kind_agent": {"en": "Agent", "uk": "Агент"},
    "token.kind_agent_hint": {
        "en": "Full access as you, for programs you run.",
        "uk": "Повний доступ від вашого імені для програм, які ви запускаєте.",
    },
    "token.kind_api": {"en": "API key", "uk": "Ключ API"},
    "token.kind_api_hint": {
        "en": "Data endpoints under /api/ only.",
        "uk": "Лише запити до даних за адресами /api/.",
    },
    "token.kind_guest": {"en": "Guest link", "uk": "Гостьове посилання"},
    "token.kind_guest_hint": {
        "en": "Read-only link for a person without an account. Needs an end date.",
        "uk": "Посилання лише для перегляду, для людини без облікового запису. Потрібна дата завершення.",
    },
    "token.label": {"en": "Name", "uk": "Назва"},
    "token.label_placeholder": {"en": "Dr Kovalenko, cardiology", "uk": "Лікар Коваленко, кардіологія"},
    "token.label_hint": {
        "en": "What this credential is for, in your own words. \"Dr Kovalenko, cardiology\" or \"deployment check\". It is the only way to tell two of them apart later, because the secret itself is never shown again.",
        "uk": "Для чого цей ключ, вашими словами - «Лікар Коваленко, кардіологія» або «перевірка розгортання». Це єдиний спосіб згодом їх розрізнити, бо сам секрет більше ніколи не показується.",
    },
    "token.expires": {"en": "Expires", "uk": "Діє до"},
    "token.expiry_hint": {
        "en": "Required for a guest link and optional for the other two. The credential stops working at the end of that day, without anyone having to remember to remove it.",
        "uk": "Обов’язково для гостьового посилання, необов’язково для інших двох. Ключ припиняє діяти в кінці того дня, без того, щоб хтось мусив пам’ятати його прибрати.",
    },
    "token.expires_hint": {
        "en": "The day the credential stops working. \"No expiry\" means it lasts until it is revoked here.",
        "uk": "День, коли ключ припиняє діяти. «Без обмеження» означає, що він діє, доки його тут не відкличуть.",
    },
    "token.never_expires": {"en": "No expiry", "uk": "Безстроково"},
    "token.never_used": {"en": "Never used", "uk": "Ще не використовувався"},
    "token.last_used": {"en": "Last used", "uk": "Востаннє використано"},
    "token.last_used_hint": {
        "en": "Recorded at most once a minute. A credential that has never been used is usually one that was mislaid.",
        "uk": "Записується не частіше ніж раз на хвилину. Ключ, який жодного разу не використали, зазвичай просто загубили.",
    },
    "token.created": {"en": "Created", "uk": "Створено"},
    "token.owner": {"en": "Record", "uk": "Картка"},
    "token.owner_hint": {
        "en": "Whose record this credential opens. It never grants access to any other account.",
        "uk": "Чию картку відкриває цей ключ. Доступу до інших облікових записів він не дає.",
    },
    "token.hint_label": {"en": "Ends in", "uk": "Закінчується на"},
    "token.hint_hint": {
        "en": "The last four characters of the secret. Enough to recognise a credential you still hold a copy of, and useless to anyone who does not.",
        "uk": "Останні чотири символи секрету. Досить, щоб упізнати ключ, копія якого у вас є, і марно для того, хто її не має.",
    },
    "token.state_active": {"en": "Active", "uk": "Діє"},
    "token.state_expired": {"en": "Expired", "uk": "Термін минув"},
    "token.seeded_name": {"en": "Server agent key", "uk": "Серверний ключ агента"},
    "token.seeded_pill": {"en": "Set on the server", "uk": "Задано на сервері"},
    "token.seeded_hint": {
        "en": "Re-created from the server setting ANAMNA_AGENT_TOKEN every time the app starts. "
              "Revoking it here lasts only until the next restart. Change or remove that setting instead. "
              "When the setting changes, the previous server key is revoked automatically.",
        "uk": "Створюється заново з налаштування сервера ANAMNA_AGENT_TOKEN під час кожного запуску. "
              "Відкликання тут діє лише до наступного перезапуску - змініть або видаліть це налаштування. "
              "Коли налаштування змінюється, попередній серверний ключ відкликається автоматично.",
    },
    "token.empty": {
        "en": "No credentials yet. Create one below.",
        "uk": "Ключів ще немає. Створіть перший нижче.",
    },
    "token.create": {"en": "Create credential", "uk": "Створити ключ"},
    "token.create_eyebrow": {"en": "New", "uk": "Новий"},
    "token.create_heading": {"en": "Create a credential", "uk": "Створити ключ"},
    "token.save": {"en": "Save changes", "uk": "Зберегти зміни"},
    "token.revoke": {"en": "Revoke", "uk": "Відкликати"},
    "token.revoke_confirm": {
        "en": "Revoke this credential? Anyone using it is signed out immediately and the secret can never be restored.",
        "uk": "Відкликати ключ? Усі, хто ним користується, одразу вийдуть із системи, а секрет уже не відновити.",
    },
    "token.saved_revoked": {"en": "Credential revoked", "uk": "Ключ відкликано"},
    "token.saved_token": {"en": "Credential updated", "uk": "Ключ оновлено"},
    "token.minted_eyebrow": {"en": "Copy this now", "uk": "Скопіюйте зараз"},
    "token.minted_heading": {"en": "\"{label}\" is ready", "uk": "Ключ «{label}» готовий"},
    "token.minted_once": {"en": "Shown once", "uk": "Показується лише раз"},
    "token.minted_lead": {
        "en": "Only a fingerprint of this secret is stored, the way your password is, so this page is the one and only time it can be read. Close it without copying and the credential has to be replaced, not recovered.",
        "uk": "У базі зберігається лише відбиток цього секрету - так само, як вашого пароля. Тому ця сторінка - єдина можливість його прочитати. Закриєте, не скопіювавши, ключ доведеться замінити, а не відновити.",
    },
    "token.secret": {"en": "Secret", "uk": "Секрет"},
    "token.link": {"en": "Link to share", "uk": "Посилання для надсилання"},
    "token.link_hint": {
        "en": "Opening this link signs the visitor in. Send it the way you would send a password, and never post it anywhere public.",
        "uk": "Відкриття цього посилання виконує вхід. Надсилайте його так само, як надсилали б пароль, і ніколи не публікуйте.",
    },
    "token.header_hint": {
        "en": "A program sends the secret as a header rather than in a URL, so it stays out of logs and browser history:",
        "uk": "Програма надсилає секрет заголовком, а не в URL, щоб він не потрапляв у журнали та історію браузера:",
    },
    "token.error_link": {
        "en": "That link is not valid, or the invitation has expired. Ask for a new one.",
        "uk": "Посилання недійсне або термін запрошення минув. Попросіть нове.",
    },
    "token.error_kind": {"en": "Choose a credential kind", "uk": "Оберіть тип ключа"},
    "token.error_label": {"en": "Give the credential a name", "uk": "Вкажіть назву ключа"},
    "token.error_expiry": {
        "en": "Choose an expiry date in the future. A guest link must have one.",
        "uk": "Вкажіть дату завершення в майбутньому. Для гостьового посилання вона обов’язкова.",
    },
    "token.error_owner": {"en": "No such account", "uk": "Такого облікового запису немає"},

    # Doctor access by six-digit code: /doctor and the "Share with a doctor"
    # panel on /profile.
    "doctor.title": {"en": "Doctor access · Anamna", "uk": "Доступ для лікаря · Anamna"},
    "doctor.heading": {"en": "Open a patient's record", "uk": "Відкрити картку пацієнта"},
    "doctor.lead": {
        "en": "Your patient can share their Anamna record with you for this appointment. Ask them for the 6-digit code shown on their phone and type it below.",
        "uk": "Пацієнт може відкрити вам свою картку в Anamna на час прийому. Попросіть шестизначний код з його телефона й введіть його нижче.",
    },
    "doctor.what": {
        "en": "You will see their results and documents read-only, for up to {hours}. Nothing can be changed, and you do not need an account.",
        "uk": "Ви бачитимете результати й документи лише для перегляду; доступ діє щонайбільше {hours}. Змінити нічого не можна, обліковий запис не потрібен.",
    },
    "doctor.pin_label": {"en": "6-digit access code", "uk": "Шестизначний код доступу"},
    "doctor.pin_hint": {
        "en": "A code works once, and only within {minutes} of the patient creating it.",
        "uk": "Код діє один раз і лише {minutes} після того, як пацієнт його створив.",
    },
    "doctor.submit": {"en": "Open the record", "uk": "Відкрити картку"},
    "doctor.error_invalid": {
        "en": "That code did not open a record. Check the 6 digits with the patient. A code works only once and only for {minutes}; if it has run out, ask them to create a new one.",
        "uk": "Код не підійшов. Перевірте з пацієнтом усі 6 цифр. Код діє лише один раз і лише {minutes}; якщо час минув, попросіть пацієнта створити новий.",
    },
    "doctor.error_throttled": {
        "en": "Too many incorrect codes were entered, so codes are paused for safety. Wait {minutes}, then try again with a fresh code from the patient.",
        "uk": "Забагато неправильних спроб, тому з міркувань безпеки введення кодів тимчасово призупинено. Зачекайте {minutes} і спробуйте ще раз із новим кодом від пацієнта.",
    },
    "doctor.patient_hint": {
        "en": "Are you the patient? Sign in and open Profile, then Sharing, to create a code.",
        "uk": "Ви пацієнт? Увійдіть, відкрийте «Профіль» і вкладку «Спільний доступ», щоб створити код.",
    },
    # Durations quoted in the sentences above; Ukrainian picks one of three forms.
    "doctor.minutes_one": {"en": "{count} minute", "uk": "{count} хвилину"},
    "doctor.minutes_few": {"en": "{count} minutes", "uk": "{count} хвилини"},
    "doctor.minutes_many": {"en": "{count} minutes", "uk": "{count} хвилин"},
    "doctor.hours_one": {"en": "{count} hour", "uk": "{count} годину"},
    "doctor.hours_few": {"en": "{count} hours", "uk": "{count} години"},
    "doctor.hours_many": {"en": "{count} hours", "uk": "{count} годин"},
    "doctor.patient_link": {"en": "Sign in", "uk": "Увійти"},
    "doctor.login_link": {"en": "Doctor? Enter an access code", "uk": "Ви лікар? Введіть код доступу"},
    "doctor.token_name": {"en": "Doctor access (code)", "uk": "Доступ лікаря (за кодом)"},
    "doctor.token_hint": {"en": "Opened with a 6-digit code", "uk": "Відкрито шестизначним кодом"},
    "doctor.share_eyebrow": {"en": "At the appointment", "uk": "На прийомі"},
    "doctor.share_heading": {"en": "Share with a doctor", "uk": "Поділитися з лікарем"},
    "doctor.share_lead": {
        "en": "Press the button to get a 6-digit code. Your doctor opens {url} and types it in. The code works once, within {minutes}. The doctor can then read your record, without changing anything, for {hours}, or until you revoke the access below.",
        "uk": "Натисніть кнопку, щоб отримати шестизначний код. Лікар відкриває {url} і вводить його. Код діє один раз і лише {minutes}. Після цього лікар може переглядати вашу картку, нічого не змінюючи, {hours} або доки ви не скасуєте доступ нижче.",
    },
    "doctor.share_button": {"en": "Create a code for my doctor", "uk": "Створити код для лікаря"},
    "doctor.pin_eyebrow": {"en": "Access code", "uk": "Код доступу"},
    "doctor.pin_heading": {"en": "Tell your doctor this code", "uk": "Назвіть лікарю цей код"},
    "doctor.pin_aria": {"en": "Access code: {spaced}", "uk": "Код доступу: {spaced}"},
    "doctor.pin_address": {"en": "Where to enter it", "uk": "Де ввести"},
    "doctor.pin_redeem_by": {"en": "Enter it by", "uk": "Код дійсний до"},
    "doctor.pin_redeem_by_hint": {
        "en": "Works once, within {minutes}.",
        "uk": "Діє один раз і лише {minutes}.",
    },
    "doctor.pin_access_until": {"en": "Access lasts until", "uk": "Доступ діє до"},
    "doctor.pin_access_hint": {
        "en": "Read-only, {hours} from now. You can revoke it at any time below.",
        "uk": "Лише перегляд, {hours} від цього моменту. Ви можете скасувати його будь-коли нижче.",
    },
    "doctor.pin_once": {
        "en": "The code is shown only now and is not stored. If it runs out unused, just create a new one.",
        "uk": "Код показано лише зараз, і він ніде не зберігається. Якщо його не використали вчасно, просто створіть новий.",
    },
    "doctor.active_heading": {"en": "Active doctor access", "uk": "Активний доступ лікарів"},
    "doctor.active_empty": {
        "en": "No doctor can open your record with a code right now.",
        "uk": "Зараз жоден лікар не може відкрити вашу картку кодом.",
    },
    "doctor.state_waiting": {"en": "Waiting for the code", "uk": "Чекає на код"},
    "doctor.state_open": {"en": "Doctor's access open", "uk": "Доступ відкрито"},
    "doctor.created": {"en": "Created", "uk": "Створено"},
    "doctor.opened": {"en": "Opened", "uk": "Відкрито"},
    "doctor.revoke": {"en": "Revoke access", "uk": "Відкликати доступ"},
    "doctor.revoke_confirm": {
        "en": "End this doctor's access now? A page they have open will be signed out.",
        "uk": "Закрити доступ лікаря зараз? Якщо в нього відкрита сторінка картки, він вийде з неї.",
    },
    "doctor.saved_revoked": {
        "en": "Doctor access revoked. Any session it opened has been signed out.",
        "uk": "Доступ лікаря відкликано. Усі сеанси, відкриті за цим кодом, завершено.",
    },
    "doctor.error_unknown": {
        "en": "That access no longer exists; it may already have ended.",
        "uk": "Цього доступу вже немає: можливо, його термін минув.",
    },
    "token.error_unknown": {
        "en": "That credential no longer exists",
        "uk": "Цього ключа вже не існує",
    },
    "token.error_api_only": {
        "en": "This API key reaches the /api/ endpoints only.",
        "uk": "Цей ключ API відкриває лише адреси /api/.",
    },
    "token.error_guest_only": {
        "en": "A guest link is read-only and reaches only the pages that show the record.",
        "uk": "Гостьове посилання дає лише перегляд і відкриває тільки сторінки картки.",
    },
    "token.admin_title": {"en": "Access credentials · Anamna", "uk": "Ключі доступу · Anamna"},
    "token.admin_heading": {"en": "Access credentials", "uk": "Ключі доступу"},
    "token.admin_lead": {
        "en": "Every credential on this instance, whoever it belongs to. Create one against any account, rename it, move its expiry, or revoke it.",
        "uk": "Усі ключі цього екземпляра, кому б вони не належали. Створіть ключ для будь-якого облікового запису, перейменуйте, змініть термін дії або відкличте.",
    },
    "token.admin_list_heading": {"en": "All credentials", "uk": "Усі ключі"},
    "token.admin_create_lead": {
        "en": "Choose the record it opens first: a credential is bound to one account and cannot be moved to another.",
        "uk": "Спершу оберіть картку, яку він відкриває: ключ прив’язаний до одного облікового запису й не переноситься на інший.",
    },
    "token.admin_link": {"en": "Manage access credentials", "uk": "Керувати ключами доступу"},
    "token.back_to_people": {"en": "Back to accounts", "uk": "Назад до облікових записів"},
    "token.list_count": {"en": "{count} credentials", "uk": "Ключів: {count}"},
    "token.list_count_one": {"en": "{count} credential", "uk": "{count} ключ"},
    "token.list_count_few": {"en": "{count} credentials", "uk": "{count} ключі"},
    "token.list_count_many": {"en": "{count} credentials", "uk": "{count} ключів"},

    # Guest visits
    "guest.role": {"en": "Invited guest · read-only", "uk": "Гість за запрошенням · лише перегляд"},
    "guest.banner": {
        "en": "You are viewing {name}'s medical record as an invited guest. Nothing here can be changed, and the invitation ends on the date its owner chose.",
        "uk": "Медична картка: {name}. Ви переглядаєте її як гість за запрошенням: змінити тут нічого не можна, а запрошення діє до дня, який обрав власник картки.",
    },
    "guest.banner_until": {
        "en": "You are viewing {name}'s medical record as an invited guest. Nothing here can be changed, and this invitation stops working after {date}.",
        "uk": "Медична картка: {name}. Ви переглядаєте її як гість за запрошенням: змінити тут нічого не можна, а запрошення перестане діяти після {date}.",
    },
    "guest.leave": {"en": "Leave this record", "uk": "Вийти з картки"},

    # Dashboard
    "dashboard.title_fallback": {"en": "Health record", "uk": "Медична картка"},
    "dashboard.eyebrow": {"en": "Health record", "uk": "Медична картка"},
    "dashboard.heading_fallback": {"en": "Health record", "uk": "Медична картка"},
    "dashboard.years_old": {"en": "{age} years old", "uk": "{age} р."},
    "dashboard.coverage": {
        "en": "{covered} of {total} health areas have evidence.",
        "uk": "Дані є в {covered} з {total} сфер здоров’я.",
    },
    "dashboard.latest_result": {
        "en": "Latest structured result: {date}.",
        "uk": "Останній структурований результат: {date}.",
    },
    "dashboard.search_label": {"en": "Search your record", "uk": "Пошук у картці"},
    "dashboard.search_placeholder": {"en": "ALT, steps, flu...", "uk": "АЛТ, кроки, грип..."},
    "dashboard.search": {"en": "Search", "uk": "Знайти"},
    "dashboard.orbit_aria": {"en": "Health coverage summary", "uk": "Підсумок охоплення здоров’я"},
    "dashboard.areas_with_data": {"en": "areas with data", "uk": "сфер із даними"},
    "dashboard.attention_one": {
        "en": "{count} area with findings to review",
        "uk": "{count} сфера з висновками для перевірки",
    },
    "dashboard.attention_many": {
        "en": "{count} areas with findings to review",
        "uk": "{count} сфер з висновками для перевірки",
    },
    "dashboard.no_attention": {"en": "No current attention flags", "uk": "Немає поточних позначок уваги"},
    "dashboard.whole_person": {"en": "Results by health area", "uk": "Результати за сферою здоров’я"},
    "dashboard.health_areas": {"en": "Health areas", "uk": "Сфери здоров’я"},
    "dashboard.no_matching": {
        "en": "No matching result in the imported record",
        "uk": "Немає відповідного результату в імпортованій картці",
    },
    "dashboard.explore": {"en": "Explore {area} results > ", "uk": "Переглянути результати: {area} > "},
    "dashboard.latest_eyebrow": {"en": "Latest measurements", "uk": "Останні вимірювання"},
    "dashboard.quick_results": {"en": "Quick results", "uk": "Швидкі результати"},
    "dashboard.search_all": {"en": "Search all metrics > ", "uk": "Шукати всі показники > "},
    "dashboard.source_eyebrow": {"en": "Source record", "uk": "Запис джерел"},
    "dashboard.source_heading": {
        "en": "Documents and extracted values",
        "uk": "Документи та витягнуті значення",
    },
    "dashboard.source_body": {
        "en": "{documents} source documents and {observations} extracted evidence rows remain attached for verification.",
        "uk": "{documents} документів-джерел і {observations} витягнутих рядків доказів доступні для перевірки.",
    },
    "dashboard.browse_docs": {"en": "Browse documents", "uk": "Переглянути документи"},
    "dashboard.review_open": {"en": "Review {count} open", "uk": "Перевірити {count} відкритих"},
    "dashboard.status_attention": {"en": "Review available findings", "uk": "Варто переглянути"},
    "dashboard.status_stable": {"en": "Evidence available", "uk": "Є дані"},
    # "borderline" and "stable" shared one label while the chip drew them with
    # different glyphs and colours, so the difference was visible but unnamed.
    "dashboard.status_borderline": {"en": "Borderline values", "uk": "Пограничні значення"},
    "dashboard.status_empty": {"en": "No data yet", "uk": "Даних ще немає"},
    "dashboard.status_row_aria": {
        "en": "Body systems and what each one currently shows",
        "uk": "Системи організму та поточний стан кожної",
    },
    "dashboard.snapshot": {"en": "Latest health snapshot", "uk": "Останній зріз здоров’я"},
    "dashboard.snapshot_date": {"en": "Data through {date}", "uk": "Дані до {date}"},
    "dashboard.hero_lead": {
        "en": "Search the record or open a section below.",
        "uk": "Знайдіть запис або відкрийте потрібний розділ нижче.",
    },
    "dashboard.device_through": {"en": "Devices through {date}", "uk": "Дані з пристроїв до {date}"},
    "dashboard.medical_through": {"en": "Medical results through {date}", "uk": "Медичні результати до {date}"},
    "dashboard.welcome_heading": {"en": "Your record is empty", "uk": "Ваша картка ще порожня"},
    "dashboard.welcome_lead": {
        "en": "Anamna reads results out of your medical documents and device exports, shows each one beside its history and a cited reference range, and keeps the original page next to every value so you can check it.",
        "uk": "Anamna зчитує результати з ваших медичних документів і експортів із пристроїв, показує кожен поруч з історією та референтним діапазоном із посиланням на джерело і зберігає сторінку оригіналу біля кожного значення, щоб ви могли його звірити.",
    },
    "dashboard.welcome_upload": {"en": "Add documents or a device export", "uk": "Додати документи або експорт із пристрою"},
    "dashboard.welcome_upload_hint": {
        "en": "PDF files, photos and scans of lab reports, or an Apple Health, Garmin or Oura export.",
        "uk": "PDF-файли, фото й скани результатів аналізів або експорт з Apple Health, Garmin чи Oura.",
    },
    "dashboard.welcome_connect": {"en": "Connect a lab account or a wearable", "uk": "Під’єднати кабінет лабораторії або пристрій"},
    "dashboard.welcome_connect_hint": {
        "en": "Results and readings then arrive on their own.",
        "uk": "Тоді результати й показники надходитимуть самі.",
    },
    "dashboard.welcome_connect_admin": {
        "en": "Lab accounts and wearables appear there once you turn them on under Administration.",
        "uk": "Кабінети лабораторій і пристрої з’являться там, щойно ви ввімкнете їх у розділі «Адміністрування».",
    },
    "dashboard.welcome_profile": {
        "en": "Check your date of birth and sex at birth",
        "uk": "Перевірити дату народження і стать при народженні",
    },
    "dashboard.welcome_profile_hint": {
        "en": "Many reference ranges depend on them.",
        "uk": "Від них залежать багато референтних діапазонів.",
    },
    "dashboard.snapshot_empty": {"en": "No structured measurements yet", "uk": "Структурованих вимірювань ще немає"},
    "dashboard.coverage_short": {"en": "{covered}/{total} health areas", "uk": "{covered}/{total} сфер здоров’я"},
    "dashboard.flags_short": {"en": "{count} areas to review", "uk": "{count} сфер до перегляду"},
    "dashboard.priority_eyebrow": {"en": "Recorded signals", "uk": "Зафіксовані сигнали"},
    # The home list opens without a visible heading; what a flag means folds
    # into the list footer behind this summary.
    "dashboard.priority_note_summary": {"en": "What a flag means", "uk": "Що означає позначка"},
    "dashboard.priority_heading": {"en": "What deserves attention", "uk": "На що звернути увагу"},
    "dashboard.priority_note": {
        "en": "Flags come from the original report or recorded findings; they are not a diagnosis.",
        "uk": "Позначки беруться з оригіналу документа або із записаних висновків. Це не діагноз.",
    },
    "dashboard.priority_all": {"en": "All {count} > ", "uk": "Усі {count} > "},
    "dashboard.no_flags": {
        "en": "No current out-of-range measurements or attention findings.",
        "uk": "Зараз немає вимірювань поза нормою чи висновків, що потребують уваги.",
    },
    "dashboard.finding": {"en": "Report finding", "uk": "Висновок звіту"},
    "dashboard.open_history": {"en": "Open history", "uk": "Відкрити історію"},
    "dashboard.connected_sources": {"en": "Connected sources", "uk": "Підключені джерела"},
    "dashboard.device_summary": {
        "en": "{count} daily aggregates · Apple Health, Oura, Garmin and Kardia remain separately attributed",
        "uk": "{count} щоденних агрегатів · Apple Health, Oura, Garmin і Kardia мають окреме походження",
    },
    "dashboard.open_devices": {"en": "Open device health > ", "uk": "Відкрити дані пристроїв > "},
    "dashboard.status_heading": {"en": "Current record status", "uk": "Стан картки зараз"},
    "dashboard.destinations_heading": {"en": "Open a section", "uk": "Відкрити розділ"},
    "dashboard.destination_insights": {
        "en": "Out-of-range results, retests due and missing test groups.",
        "uk": "Результати поза інтервалом, повторні обстеження та відсутні групи аналізів.",
    },
    "dashboard.destination_panels": {
        "en": "Results grouped by tests that are interpreted together.",
        "uk": "Результати, згруповані за аналізами, які трактують разом.",
    },
    "dashboard.destination_review_title": {"en": "Review extracted values", "uk": "Звірити витягнуті значення"},
    "dashboard.destination_review": {
        "en": "Compare automatically extracted values with the original page.",
        "uk": "Порівняти автоматично витягнуті значення з оригінальною сторінкою.",
    },
    "dashboard.destination_upload_title": {"en": "Add files", "uk": "Додати файли"},
    "dashboard.destination_upload": {
        "en": "Upload a PDF, image, ZIP archive or device export.",
        "uk": "Завантажте PDF, зображення, ZIP-архів або експорт із пристрою.",
    },
    "dashboard.destination_documents": {
        "en": "Open original files and the values read from them.",
        "uk": "Відкрити оригінальні файли та зчитані з них значення.",
    },
    "dashboard.destination_devices": {
        "en": "Open daily measurements and import status.",
        "uk": "Відкрити щоденні вимірювання та стан імпорту.",
    },
    "dashboard.recent_heading": {"en": "Latest documents", "uk": "Останні документи"},
    "dashboard.recent_empty_title": {"en": "No documents yet", "uk": "Документів ще немає"},
    "dashboard.recent_empty_body": {
        "en": "Add a medical document to start the record.",
        "uk": "Додайте медичний документ, і картка почне наповнюватися.",
    },

    # Health-area detail
    "area.back": {"en": "Back to test groups", "uk": "До груп аналізів"},
    "area.eyebrow": {"en": "Body-system evidence", "uk": "Дані за системою органів"},
    "area.review_findings": {"en": "Findings to review", "uk": "Висновки до перегляду"},
    "area.evidence_available": {"en": "Evidence available", "uk": "Є дані"},
    "area.conclusions": {"en": "clinical conclusions", "uk": "Висновки лікарів"},
    "area.measurements": {"en": "related measurements", "uk": "Вимірювання"},
    "area.sources": {"en": "source documents", "uk": "Документи"},
    "area.scope_note": {
        "en": "This page colocates source conclusions and related measurements for review. Association with a body system does not establish a diagnosis or causal link.",
        "uk": "Ця сторінка поєднує висновки джерел і пов’язані вимірювання для перегляду. Зв’язок із системою органів не встановлює діагнозу чи причинного зв’язку.",
    },
    "area.clinical_eyebrow": {"en": "Doctor and procedure reports", "uk": "Висновки лікарів і обстежень"},
    "area.clinical_heading": {"en": "Clinical conclusions and assessments", "uk": "Клінічні висновки та оцінки"},
    "area.clinical_note": {
        "en": "Source wording remains attached to every summary",
        "uk": "Формулювання джерела збережене біля кожного підсумку",
    },
    "area.source_wording": {"en": "Show original source wording", "uk": "Показати текст оригіналу"},
    "area.source_wording_label": {"en": "Original source wording", "uk": "Оригінальне формулювання джерела"},
    "area.open_page": {"en": "Open source page {page} > ", "uk": "Відкрити сторінку {page} в оригіналі > "},
    "area.no_conclusions": {
        "en": "No doctor or procedure conclusion is associated with this area yet.",
        "uk": "Для цього напряму ще немає висновків лікарів чи обстежень.",
    },
    "area.panels_heading": {"en": "Panels in this area", "uk": "Панелі аналізів цього напряму"},
    "area.measurement_eyebrow": {"en": "Laboratory and device evidence", "uk": "Аналізи й пристрої"},
    "area.measurement_heading": {"en": "Related measurements", "uk": "Пов’язані вимірювання"},
    "area.measurement_note": {
        "en": "Primary and related placement are shown explicitly",
        "uk": "Основне та пов’язане розміщення позначені окремо",
    },
    "area.primary": {"en": "Primary", "uk": "Основне"},
    "area.related": {"en": "Related", "uk": "Пов’язане"},
    "area.no_measurements": {"en": "No related structured measurements yet.", "uk": "Пов’язаних вимірювань поки немає."},
    "area.source_eyebrow": {"en": "Traceable evidence", "uk": "Звідки дані"},
    "area.source_heading": {"en": "Source documents", "uk": "Документи-джерела"},
    "area.source_note": {"en": "Open any document for its rendered pages and extracted rows", "uk": "Відкрийте документ, щоб побачити сторінки й витягнуті рядки"},
    # Count-safe base forms ("1 pages" was the old bug). The _one/_few/_many
    # variants below carry the natural phrasing for callers that select a form;
    # Ukrainian needs three (1 / 2–4 / 5–20), English uses the same string twice.
    "area.pages": {"en": "Pages: {count}", "uk": "Сторінок: {count}"},
    "area.pages_one": {"en": "{count} page", "uk": "{count} сторінка"},
    "area.pages_few": {"en": "{count} pages", "uk": "{count} сторінки"},
    "area.pages_many": {"en": "{count} pages", "uk": "{count} сторінок"},
    "area.evidence_rows": {"en": "Evidence rows: {count}", "uk": "Рядків даних: {count}"},
    "area.evidence_rows_one": {"en": "{count} evidence row", "uk": "{count} рядок даних"},
    "area.evidence_rows_few": {"en": "{count} evidence rows", "uk": "{count} рядки даних"},
    "area.evidence_rows_many": {"en": "{count} evidence rows", "uk": "{count} рядків даних"},
    "area.no_sources": {"en": "No source documents are associated with this area.", "uk": "Для цього напряму немає документів-джерел."},
    # Narrative findings on area pages: the conclusion first, the report's own
    # wording labelled as such, and a sourced explanation for anything abnormal.
    "area.finding_original_uk": {"en": "Original wording (Ukrainian): not translated", "uk": "Оригінальний текст українською"},
    "area.finding_original_en": {"en": "Original wording (English)", "uk": "Оригінальний текст англійською, без перекладу"},
    "area.finding_full_text": {"en": "Show the full report text", "uk": "Показати повний текст висновку"},
    "area.finding_recommended": {"en": "Recommended in the report", "uk": "Рекомендовано у висновку"},
    "area.finding_no_conclusion": {
        "en": "This document holds images or a form without a written conclusion. Open it to see what it contains.",
        "uk": "У цьому документі є зображення або бланк без письмового висновку. Відкрийте його, щоб переглянути вміст.",
    },
    "area.finding_status_attention": {
        "en": "The conclusion names a change worth discussing with a doctor.",
        "uk": "У висновку описано зміну, яку варто обговорити з лікарем.",
    },
    "area.finding_status_information": {
        "en": "The conclusion names no abnormality.",
        "uk": "У висновку відхилень не описано.",
    },
    "area.finding_explain_heading": {"en": "What this means", "uk": "Що це означає"},
    "area.finding_sources": {"en": "Sources", "uk": "Джерела"},
    "area.finding_provisional": {
        "en": "Read automatically from the document and not yet checked by a person.",
        "uk": "Зчитано з документа автоматично, людина ще не звірила.",
    },
    "finding.explain.colorectal_polyp": {
        "en": "A polyp is a small growth on the lining of the bowel. Adenomas, serrated adenomas included, are polyps that can slowly turn into bowel cancer over many years, which is why removing them counts as cancer prevention. After removal, guidelines set the next colonoscopy by how many polyps there were, their size and type, and whether dysplasia (precancerous change in the cells) was found: from 3 years (a serrated polyp of 10 mm or more, one with dysplasia, or a traditional serrated adenoma) to 5-10 years or a return to routine screening (one or two small ones without dysplasia). The report asks for its result to be read with your clinical data. Ask your gastroenterologist which interval applies to you.",
        "uk": "Поліп це невелике розростання на слизовій оболонці кишки. Аденоми, зокрема зубчасті, належать до поліпів, які впродовж багатьох років можуть повільно перетворитися на рак кишки, тому їх видалення вважають профілактикою раку. Після видалення строк наступної колоноскопії за настановами залежить від кількості, розміру й типу поліпів і від того, чи знайшли дисплазію (передракові зміни клітин): від 3 років (зубчастий поліп 10 мм і більше, поліп із дисплазією або традиційна зубчаста аденома) до 5-10 років або повернення до звичайного скринінгу (один-два невеликі поліпи без дисплазії). У висновку зазначено, що результат слід оцінювати разом із клінічними даними. Запитайте гастроентеролога, який інтервал підходить саме вам.",
    },
    "finding.explain.fatty_liver": {
        "en": "The ultrasound describes diffuse changes in the liver and/or pancreas. Where the report names their type, «стеатоз» or «гепатоз» means fat build-up in the liver, «ліпоматоз» means fat in the pancreas, and «гепатомегалія» means an enlarged liver. Fatty liver found on a scan is common and is mostly linked to weight, waist size, blood sugar and blood fats. Guidelines advise a follow-up risk check - liver blood tests and a liver-scarring score such as FIB-4 (Fibrosis-4 index) - and note that losing 3-5% of body weight reduces liver fat. Ultrasound can suggest fat in the pancreas but cannot measure it reliably.",
        "uk": "УЗД описує дифузні зміни печінки та/або підшлункової залози. Якщо у висновку названо їхній тип: «стеатоз» або «гепатоз» означає накопичення жиру в печінці, «ліпоматоз» означає жир у підшлунковій залозі, а «гепатомегалія» означає збільшену печінку. Жирова печінка на УЗД трапляється часто і здебільшого пов’язана з вагою, обводом талії, рівнем цукру та жирів у крові. Настанови радять надалі оцінити ризик: зробити печінкові проби й розрахувати індекс фіброзу печінки, наприклад FIB-4 (Fibrosis-4), і зазначають, що схуднення на 3-5% маси тіла зменшує вміст жиру в печінці. УЗД може вказати на жир у підшлунковій залозі, але надійно виміряти його не може.",
    },
    "finding.explain.cholestasis": {
        "en": "On ultrasound, «холестаз» describes bile that is thickened or slow to drain (sludge) in the gallbladder or bile ducts. Sludge forms when bile stagnates, is often found by chance and does not by itself cause gallstones. Whether it matters is judged together with symptoms and liver blood tests: alkaline phosphatase (ALP), gamma-glutamyl transferase (GGT) and bilirubin.",
        "uk": "На УЗД словом «холестаз» описують загуслу жовч або жовч, що погано відтікає (сладж), у жовчному міхурі чи жовчних протоках. Сладж утворюється, коли жовч застоюється; його часто виявляють випадково, і сам по собі він не спричиняє жовчних каменів. Чи має це значення, оцінюють разом із симптомами та печінковими пробами: лужною фосфатазою (ЛФ), гамма-глутамілтрансферазою (ГГТ) і білірубіном.",
    },
    "finding.explain.thyroid_nodule": {
        "en": "Thyroid nodules are lumps inside the thyroid gland. They are common and usually not cancerous; colloid nodules are a benign type. TI-RADS (Thyroid Imaging Reporting and Data System) scores how suspicious a nodule looks on ultrasound: categories 1-2 look benign and need no needle biopsy, while higher categories may need one depending on size. A repeat ultrasound, as this report recommends, checks that nothing changes. See a doctor sooner if a lump grows quickly or you notice hoarseness or trouble swallowing or breathing.",
        "uk": "Вузли щитоподібної залози це ущільнення в її тканині. Вони трапляються часто й зазвичай не ракові; колоїдні вузли належать до доброякісних. TI-RADS (Thyroid Imaging Reporting and Data System, система оцінки вузлів щитоподібної залози на УЗД) показує, наскільки підозріло виглядає вузол: категорії 1-2 виглядають доброякісними й пункційної біопсії не потребують, а за вищих категорій вона може знадобитися залежно від розміру вузла. Повторне УЗД, яке рекомендує висновок, потрібне, щоб переконатися, що нічого не змінюється. Зверніться до лікаря раніше, якщо вузол швидко росте або з’явилися захриплість, утруднене ковтання чи дихання.",
    },
    "finding.explain.spine_disc": {
        "en": "The report describes a spinal disc pushing out beyond its normal edge (extrusion or hernia, «екструзія», «кила», «грижа»), which can press on a nerve root («радикулярний конфлікт») and cause pain, numbness or weakness in an arm or leg, and/or signs of inflammation in the spine or the sacroiliac joints (spondylitis, sacroiliitis). Many disc changes seen on scans are age-related and are not the cause of pain. Most back pain improves within weeks while staying active, and surgery is considered only when non-surgical care has not helped and the scan matches the symptoms. Suspected inflammatory back disease (axial spondyloarthritis) is assessed by a rheumatologist.",
        "uk": "У висновку описано випинання міжхребцевого диска за його нормальні межі («екструзія», «кила», «грижа»), яке може тиснути на нервовий корінець («радикулярний конфлікт») і спричиняти біль, оніміння чи слабкість у руці або нозі, та/або ознаки запалення хребта чи крижово-клубових суглобів (спондиліт, сакроілеїт). Багато змін дисків, які видно на знімках, пов’язані з віком і не спричиняють болю. Здебільшого біль у спині минає за кілька тижнів, якщо залишатися активним, а операцію розглядають лише тоді, коли нехірургічне лікування не допомогло і знімок відповідає симптомам. Якщо є підозра на запальне захворювання хребта (аксіальний спондилоартрит), його оцінює ревматолог.",
    },
    "finding.explain.lv_mass": {
        "en": "Left-ventricular mass index is the mass of the wall of the heart's main pumping chamber divided by body surface area. Above the normal limit (115 g/m² for men, 95 g/m² for women) it points to thickened heart muscle (hypertrophy); hypertension guidelines count it as heart damage from high blood pressure, so it is a reason to check your blood pressure with a doctor.",
        "uk": "Індекс маси міокарда лівого шлуночка показує масу стінки головної насосної камери серця в перерахунку на площу поверхні тіла. Якщо він вищий за межу норми (115 г/м² для чоловіків, 95 г/м² для жінок), це вказує на потовщення серцевого м’яза (гіпертрофію). Настанови з артеріальної гіпертензії вважають це ураженням серця через підвищений тиск, тож варто перевірити тиск разом із лікарем.",
    },
    "finding.explain.lipoma": {
        "en": "A lipoma is a soft, slow-growing, non-cancerous lump of fat under the skin. Lipomas are harmless and usually need no treatment; the report recommends watching it over time. Have it checked if it becomes painful, hard or fixed in place, or grows.",
        "uk": "Ліпома це м’яке доброякісне (не ракове) утворення з жирової тканини під шкірою, яке росте повільно. Ліпоми нешкідливі й зазвичай лікування не потребують; у висновку рекомендовано спостерігати за нею в динаміці. Покажіть її лікарю, якщо вона стане болючою, твердою чи нерухомою або почне рости.",
    },
    "finding.explain.lymph_inflammation": {
        "en": "The report describes inflammatory changes in a salivary gland and/or enlarged lymph nodes in the neck (lymphadenopathy). Infection is the most common cause, and swollen glands usually settle within 1-2 weeks. See a doctor if the nodes keep growing, have not gone down after a few weeks, feel hard or fixed, or come with fever, night sweats or weight loss.",
        "uk": "У висновку описано запальні зміни слинної залози та/або збільшені лімфатичні вузли шиї (лімфаденопатію). Найчастіше їх спричиняє інфекція, і збільшені вузли зазвичай зменшуються за 1-2 тижні. Зверніться до лікаря, якщо вузли далі збільшуються, не зменшилися за кілька тижнів, тверді чи нерухомі або з’явилися гарячка, нічна пітливість чи втрата ваги.",
    },
    "finding.explain.joint_tendon": {
        "en": "The report describes irritation or strain of tendons, ligaments or the joint lining (tendinopathy, ligamentopathy, synovitis), softening of the cartilage under the kneecap (chondromalacia), a fluid-filled Baker's cyst behind the knee, plantar fasciitis (heel pain from the band of tissue under the foot) or arthritis (joint inflammation). Tendon, ligament and heel problems usually improve with rest, changes in activity and exercise; arthritis needs a doctor to find its cause. Seek urgent care if your calf suddenly swells or becomes painful, especially with shortness of breath.",
        "uk": "У висновку описано подразнення чи перенапруження сухожиль, зв’язок або оболонки суглоба (тендинопатія, лігаментопатія, синовіт), розм’якшення хряща під надколінком (хондромаляція), кісту Бейкера (заповнену рідиною порожнину під коліном), плантарний фасциїт (біль у п’яті через ураження підошовної фасції) або артрит (запалення суглоба). Проблеми із сухожиллями, зв’язками й п’ятою зазвичай минають завдяки відпочинку, зміні навантаження та вправам; причину артриту має з’ясувати лікар. Терміново зверніться по медичну допомогу, якщо литка раптово набрякла чи болить, особливо коли є задишка.",
    },
    # Large panels on an area page (296 allergens) read as one compact table.
    "area.table_heading": {"en": "All results in this area", "uk": "Усі результати цієї сфери"},
    "area.table_lead": {
        "en": "Flagged results and values the lab could measure (above its detection limit) come first, then the rest by value. A measurable value can still be class 0. Below the level counted as sensitisation. Codes such as «Cyn d 1» are the international allergen component names, shown as printed.",
        "uk": "Спершу йдуть позначені результати та значення, які лабораторія змогла виміряти (вище межі визначення), потім решта за значенням. Виміряне значення все одно може мати клас 0, тобто бути нижчим за рівень, з якого говорять про сенсибілізацію. Коди на кшталт «Cyn d 1» означають міжнародні назви алергенних компонентів; їх наведено так, як надруковано в бланку.",
    },
    "area.table_attention": {"en": "Needing attention", "uk": "Потребують уваги"},
    "area.table_detected": {"en": "Above the detection limit, or needing attention", "uk": "Вище межі визначення або потребують уваги"},
    "area.table_show_all": {"en": "Show all {count}", "uk": "Показати всі {count}"},
    "area.table_name": {"en": "Measurement", "uk": "Показник"},
    "area.table_code": {"en": "Code", "uk": "Код"},
    "area.table_value": {"en": "Result", "uk": "Результат"},
    "area.table_class": {"en": "Class", "uk": "Клас"},
    "area.table_state": {"en": "Assessment", "uk": "Оцінка"},
    "area.table_date": {"en": "Date", "uk": "Дата"},
    "area.table_none_attention": {"en": "No result in this area needs attention.", "uk": "У цьому напрямі немає результатів, що потребують уваги."},

    # Metrics
    "metrics.title": {"en": "Find results · Anamna", "uk": "Пошук результатів · Anamna"},
    "metrics.eyebrow": {
        "en": "{count} searchable result types",
        "uk": "{count} типів результатів для пошуку",
    },
    "metrics.heading": {"en": "Search your record", "uk": "Пошук у картці"},
    "metrics.lead": {"en": "Find any result, device measurement, vaccination, document or report conclusion, or filter by what needs you.", "uk": "Знайдіть будь-який результат, вимірювання пристрою, щеплення, документ чи висновок, або відфільтруйте те, що потребує уваги."},
    "metrics.search_span": {"en": "Name, abbreviation, vaccine, document or date", "uk": "Назва, скорочення, вакцина, документ або дата"},
    "metrics.placeholder": {"en": "ALT, HbA1c, steps, flu, ultrasound...", "uk": "АЛТ, HbA1c, кроки, грип, УЗД..."},
    "metrics.browse_aria": {"en": "Browse by health area", "uk": "Перегляд за сферою здоров’я"},
    "metrics.status_aria": {"en": "Filter by status", "uk": "Фільтр за станом"},
    "metrics.status_all": {"en": "All results", "uk": "Усі результати"},
    "metrics.status_unverified": {"en": "Not yet checked", "uk": "Ще не звірено"},
    "metrics.shortcut_hint": {"en": "Press / to search", "uk": "Натисніть /, щоб шукати"},
    "metrics.open_area": {"en": "Open the {area} page > ", "uk": "Відкрити сторінку «{area}» > "},
    "metrics.live": {"en": "Live results", "uk": "Живі результати"},
    "metrics.matches_for": {"en": "Matches for \"{query}\"", "uk": "Результати за запитом «{query}»"},
    "metrics.recent": {"en": "Recent and frequently measured", "uk": "Останні та найчастіші показники"},
    "metrics.shown": {"en": "{count} shown", "uk": "Показано {count}"},
    "metrics.result_count_one": {"en": "{count} result", "uk": "{count} результат"},
    "metrics.result_count_few": {"en": "{count} results", "uk": "{count} результати"},
    "metrics.result_count_many": {"en": "{count} results", "uk": "{count} результатів"},
    "metrics.count_lab_one": {"en": "{count} laboratory result", "uk": "{count} лабораторний показник"},
    "metrics.count_lab_few": {"en": "{count} laboratory results", "uk": "{count} лабораторні показники"},
    "metrics.count_lab_many": {"en": "{count} laboratory results", "uk": "{count} лабораторних показників"},
    "metrics.count_device_one": {"en": "{count} device measurement", "uk": "{count} вимірювання з пристроїв"},
    "metrics.count_device_few": {"en": "{count} device measurements", "uk": "{count} вимірювання з пристроїв"},
    "metrics.count_device_many": {"en": "{count} device measurements", "uk": "{count} вимірювань з пристроїв"},
    "metrics.overview_title": {"en": "Everything in your record, by body system", "uk": "Уся картка за системами організму"},
    "metrics.section_labs": {"en": "Laboratory results", "uk": "Результати аналізів"},
    "metrics.section_other": {"en": "Other results", "uk": "Інші результати"},
    "metrics.section_flagged_one": {"en": "{count} needs attention", "uk": "{count} потребує уваги"},
    "metrics.section_flagged_few": {"en": "{count} need attention", "uk": "{count} потребують уваги"},
    "metrics.section_flagged_many": {"en": "{count} need attention", "uk": "{count} потребують уваги"},
    "metrics.area_page": {"en": "Area page > ", "uk": "Сторінка напряму > "},
    "metrics.show_all": {"en": "Show all {count}", "uk": "Показати всі {count}"},
    "metrics.legend_title": {"en": "What the marks mean", "uk": "Що означають позначки"},
    "metrics.legend_marks": {"en": "Each row says its verdict in words; the mark beside the value repeats it:", "uk": "Оцінку в кожному рядку написано словами, а позначка біля значення її дублює:"},
    "metrics.legend_conflict": {"en": "A coloured bar on the left and \"{label}\": the laboratory's own range and the cited guideline judge this value differently. Open the result to see both.", "uk": "Кольорова смуга ліворуч і «{label}»: норма лабораторії та настанова, на яку ми посилаємося, оцінюють це значення по-різному. Відкрийте результат, щоб побачити обидві оцінки."},
    "metrics.legend_unverified": {"en": "\"{label}\": read from a document automatically and not yet checked against it by a person.", "uk": "«{label}»: зчитано з документа автоматично, людина ще не звірила значення з оригіналом."},
    "metrics.legend_no_mark": {"en": "No mark and no verdict: there is no published range to compare this measurement with.", "uk": "Без позначки й оцінки: для цього вимірювання немає опублікованого референтного інтервалу, з яким його можна порівняти."},
    "metrics.unverified_results_one": {"en": "{count} unverified result", "uk": "{count} незвірений результат"},
    "metrics.unverified_results_few": {"en": "{count} unverified results", "uk": "{count} незвірені результати"},
    "metrics.unverified_results_many": {"en": "{count} unverified results", "uk": "{count} незвірених результатів"},
    "metrics.unverified_in_documents_one": {"en": "from {count} document.", "uk": "з {count} документа."},
    "metrics.unverified_in_documents_few": {"en": "from {count} documents.", "uk": "з {count} документів."},
    "metrics.unverified_in_documents_many": {"en": "from {count} documents.", "uk": "з {count} документів."},
    "metrics.finding_attention_note": {"en": "Flagged because the report's conclusion describes an abnormal finding. Open the document to read it in full, and discuss it with your doctor.", "uk": "Позначено, бо у висновку описано відхилення. Відкрийте документ, щоб прочитати висновок повністю, і обговоріть його з лікарем."},
    "metrics.search_document_text": {"en": "Search the text inside your documents", "uk": "Шукати в тексті документів"},
    "metrics.show_more": {"en": "Show {count} more", "uk": "Показати ще {count}"},
    "metrics.short_query_title": {"en": "Type a few more letters", "uk": "Введіть ще кілька літер"},
    "metrics.short_query_one": {
        "en": "Type at least {count} letter to search by the beginning of a word. Two letters find only whole words and abbreviations, such as Hb or КТ.",
        "uk": "Введіть щонайменше {count} літеру, щоб шукати за початком слова. Дві літери знаходять лише цілі слова та скорочення, як-от Hb чи КТ.",
    },
    "metrics.short_query_few": {
        "en": "Type at least {count} letters to search by the beginning of a word. Two letters find only whole words and abbreviations, such as Hb or КТ.",
        "uk": "Введіть щонайменше {count} літери, щоб шукати за початком слова. Дві літери знаходять лише цілі слова та скорочення, як-от Hb чи КТ.",
    },
    "metrics.short_query_many": {
        "en": "Type at least {count} letters to search by the beginning of a word. Two letters find only whole words and abbreviations, such as Hb or КТ.",
        "uk": "Введіть щонайменше {count} літер, щоб шукати за початком слова. Дві літери знаходять лише цілі слова та скорочення, як-от Hb чи КТ.",
    },
    "metrics.date_unknown": {"en": "Date unknown", "uk": "Дата невідома"},
    # A device aggregate is a mean over a day of samples, so it arrives with
    # more digits than the sensor resolves. The card shows the reading at the
    # precision its unit is worth; this is the undivided number, on hover, for
    # anyone reconciling the screen against an export.
    "metrics.exact_value": {
        "en": "Unrounded reading: {value}",
        "uk": "Значення без округлення: {value}",
    },
    "metrics.point": {"en": "point", "uk": "точка"},
    "metrics.points": {"en": "points", "uk": "точок"},
    "metrics.view_history": {"en": "View interactive history > ", "uk": "Переглянути історію > "},
    "metrics.empty_title": {"en": "No matching metrics", "uk": "Показників не знайдено"},
    "metrics.empty_body": {"en": "Try another spelling or an abbreviation (ALT, ЛПНЩ, HRV), a vaccine, a document type such as ultrasound, or a date.", "uk": "Спробуйте інше написання чи скорочення (АЛТ, LDL, ВСР), назву вакцини, тип документа (наприклад, УЗД) або дату."},
    "metrics.search_unavailable": {"en": "Search unavailable", "uk": "Пошук недоступний"},
    "metrics.search_failed": {"en": "Search failed", "uk": "Пошук не вдався"},
    "metrics.searching": {"en": "Searching...", "uk": "Пошук..."},
    "metrics.search_retry": {"en": "Check your connection and type again.", "uk": "Перевірте з'єднання і введіть запит ще раз."},

    # Metric detail
    "metric.back": {"en": "Find another metric", "uk": "Знайти інший показник"},
    "metric.points_one": {"en": "{count} distinct point", "uk": "{count} результат"},
    "metric.points_many": {"en": "{count} distinct points", "uk": "{count} результатів"},
    "metric.aliases_note": {
        "en": "Source aliases remain attached for evidence review",
        "uk": "Псевдоніми джерела збережені для перевірки доказів",
    },
    "metric.latest": {"en": "Latest · {date}", "uk": "Востаннє · {date}"},
    "metric.provider_comparison": {
        "en": "Original provider comparison",
        "uk": "Порівняння з оригінальним надавачем",
    },
    "metric.interactive": {"en": "Interactive history", "uk": "Інтерактивна історія"},
    "metric.value_over_time": {"en": "Value over time", "uk": "Динаміка значень"},
    "metric.range_aria": {"en": "Chart time range", "uk": "Період на графіку"},
    "metric.range_all": {"en": "All", "uk": "Увесь час"},
    "metric.range_5y": {"en": "5 years", "uk": "5 років"},
    "metric.range_1y": {"en": "1 year", "uk": "1 рік"},
    "metric.chart_aria": {
        "en": "Interactive trend for {name}",
        "uk": "Інтерактивний графік динаміки: {name}",
    },
    "metric.chart_help1": {
        "en": "Hover or focus a point for its value, date, provider and status.",
        "uk": "Наведіть або сфокусуйте точку, щоб побачити значення, дату, надавача та статус.",
    },
    "metric.chart_help2": {
        "en": "Select a point to open its source evidence.",
        "uk": "Оберіть точку, щоб відкрити докази джерела.",
    },
    "metric.no_trend_title": {"en": "No dated numeric trend", "uk": "Немає числових значень із датами"},
    # One numeric result: a value, not yet a trend.
    "metric.single_point_title": {"en": "One measurement so far", "uk": "Поки що одне вимірювання"},
    "metric.single_point_body": {
        "en": "Measured once, on {date}. A trend appears here after the next result.",
        "uk": "Виміряно один раз: {date}. Динаміка з’явиться після наступного результату.",
    },
    "metric.no_trend_body": {
        "en": "Categorical observations remain available in the evidence history below.",
        "uk": "Нечислові результати можна переглянути в історії нижче.",
    },
    "metric.official": {"en": "Official comparison", "uk": "Порівняння з настановами"},
    "metric.guidance": {"en": "Current, versioned guidance", "uk": "Актуальні версіоновані настанови"},
    "metric.guidance_badge": {
        "en": "Separate from vendor ranges",
        "uk": "Окремо від інтервалів надавача",
    },
    "metric.reviewed": {"en": "reviewed {date}", "uk": "перевірено {date}"},
    "metric.no_universal_target": {
        "en": "No universal numeric target",
        "uk": "Немає єдиного числового цільового значення",
    },
    "metric.open_source": {"en": "Open {publisher} source", "uk": "Відкрити джерело: {publisher}"},
    "metric.no_range_title": {
        "en": "No universal official range applies automatically.",
        "uk": "Єдиного офіційного інтервалу, який можна застосувати автоматично, немає.",
    },
    "metric.no_range_body": {
        "en": "For this measurement, a safe comparison depends on assay, specimen, age, sex or clinical context. The original provider interval is preserved per result below; it is not presented as universal current guidance.",
        "uk": "Для цього показника безпечне порівняння залежить від методу аналізу, зразка, віку, статі або клінічної ситуації. Інтервал з оригіналу збережено біля кожного результату нижче; ми не подаємо його як універсальну чинну настанову.",
    },
    "metric.what_shown": {"en": "What is shown", "uk": "Що показано"},
    "metric.evidence_not_dx": {"en": "Evidence, not a diagnosis", "uk": "Докази, а не діагноз"},
    "metric.evidence_body": {
        "en": "Provider status compares a value only with the interval printed on that source report. Official rules are displayed separately and are never applied when their required context is unknown.",
        "uk": "Статус надавача порівнює значення лише з інтервалом, надрукованим у тому звіті. Офіційні правила показуються окремо і ніколи не застосовуються, коли потрібний контекст невідомий.",
    },
    "metric.source_names": {"en": "Original source names", "uk": "Оригінальні назви джерела"},
    "metric.source_history": {"en": "Source-linked history", "uk": "Історія з посиланнями на джерела"},
    "metric.every_result": {"en": "Every distinct result", "uk": "Кожен окремий результат"},
    "metric.timeline_one": {"en": "{count} timeline point", "uk": "{count} точка на шкалі часу"},
    "metric.timeline_many": {"en": "{count} timeline points", "uk": "{count} точок на шкалі часу"},
    "metric.th_date": {"en": "Date", "uk": "Дата"},
    "metric.th_result": {"en": "Result", "uk": "Результат"},
    "metric.th_comparison": {"en": "Comparison", "uk": "Порівняння"},
    "metric.th_provider": {"en": "Provider & evidence", "uk": "Заклад і джерело"},
    "metric.th_trust": {"en": "Trust", "uk": "Звірка"},
    "metric.original_range": {"en": "Original provider range", "uk": "Інтервал з оригіналу"},
    # A history row's own verdict, at the age the sample was taken.
    "metric.verdict_label": {"en": "Verdict", "uk": "Оцінка"},
    "metric.original_report": {
        "en": "Original report: {title} · page {page}",
        "uk": "Оригінал: {title} · стор. {page}",
    },
    "metric.matching_copies": {
        "en": "{count} matching source copies",
        "uk": "Однакових копій джерела: {count}",
    },
    "metric.open_details": {"en": "Open details", "uk": "Докладніше"},
    # A history row recorded in a unit the chart's axis does not carry: the
    # value is real, it just cannot be drawn on the shared axis honestly.
    "metric.off_axis": {
        "en": "Not on the chart. Recorded in a different unit",
        "uk": "Не на графіку: записано в іншій одиниці",
    },
    # Guidance-block heading on metric and device-metric detail pages; the
    # panel-scoped "What this panel measures" mislabelled a single measurement.
    "metric.what_it_measures": {"en": "What this measures", "uk": "Що вимірює цей показник"},
    # Hero disclosure on metric pages when both the description and the retest
    # cadence are known.
    "metric.about_summary": {"en": "What it measures and how often to test", "uk": "Що вимірює і як часто перевіряти"},
    "chart.open_evidence": {"en": "Open evidence", "uk": "Відкрити джерело"},
    "chart.new_tab": {"en": "New tab", "uk": "У новій вкладці"},
    # Shown by the chart itself: only the browser knows how many points the
    # available width can carry, and a silently thinned series is a lie.
    "chart.averaged": {
        # Both counts sit after their noun ("Points drawn: 34", "з 227 вимірювань")
        # so neither locale has to agree a noun with a number it only learns in
        # the browser — Ukrainian would need three forms for that.
        "en": (
            "Too narrow to draw every reading. Points drawn: {shown}: each "
            "averages several of {total} readings, so a point has no single "
            "source. Nothing is dropped: every reading is listed in the table below."
        ),
        "uk": (
            "Екран завузький, щоб показати кожне вимірювання. Точок на графіку: {shown}; кожна з них усереднює кілька з {total} вимірювань, тож не має одного джерела. Нічого не втрачено: усі вимірювання є в таблиці нижче."
        ),
    },
    "chart.averaged_point": {
        "en": "average of {count} readings, {from} - {to}",
        "uk": "середнє, вимірювань: {count}, період {from} - {to}",
    },
    # A shaded band the chart is too narrow to write inside is still named here,
    # so no colour on the chart is left carrying meaning on its own.
    "chart.band_here": {"en": "Shaded band: {name}.", "uk": "Затінена смуга: {name}."},
    "chart.original_interval": {"en": "Original interval: {interval}", "uk": "Інтервал з оригіналу: {interval}"},
    "chart.comparison_stored_flag": {"en": "Recorded provider flag", "uk": "Позначка лабораторії"},
    "chart.comparison_original_range": {"en": "Compared with the original interval", "uk": "Порівняно з інтервалом з оригіналу"},
    "chart.original_comparisons": {
        "en": "Each point is coloured by its own verdict at the age it was taken, by the same rule as the latest value.",
        "uk": "Кожну точку забарвлено за її власною оцінкою на вік, коли зроблено аналіз, за тим самим правилом, що й останнє значення.",
    },
    # Printed under a trend whose long silences were drawn shorter.
    "chart.axis_compressed": {
        "en": "Gaps longer than a year between results are drawn shorter and marked ⫽ on the time axis.",
        "uk": "Проміжки понад рік між результатами показано стиснуто й позначено ⫽ на осі часу.",
    },
    "chart.latest_target_band": {"en": "The shaded band shows the latest reading's target interval.", "uk": "Затінена смуга показує цільовий інтервал останнього результату."},
    "chart.bands_unlabelled": {
        "en": "Bands too narrow to label on this screen, lowest to highest: {names}.",
        "uk": "Смуги, завузькі для підпису на цьому екрані (від найнижчої до найвищої): {names}.",
    },

    # Documents
    "documents.title": {"en": "Documents · Anamna", "uk": "Документи · Anamna"},
    "documents.eyebrow": {"en": "Source archive", "uk": "Архів джерел"},
    "documents.heading": {"en": "Documents", "uk": "Документи"},
    # The page's primary action, said as a verb ("Files to add" read as a label).
    "documents.add_files": {"en": "Add files", "uk": "Додати файли"},
    # Every list that pages had a counter and no way to reach page two: the
    # template asked for a variable the route never passed, so the whole nav
    # rendered as nothing and 65 of 85 documents were unreachable.
    "pagination.aria": {"en": "More results", "uk": "Сторінки результатів"},
    "pagination.range": {"en": "Showing {first}-{last} of {total}", "uk": "Показано {first}-{last} з {total}"},
    "documents.lead": {
        "en": "Every observation stays linked to the original file and page.",
        "uk": "Кожне спостереження залишається пов’язаним з оригінальним файлом і сторінкою.",
    },
    # Reached as the review queue, the page says it is one and what is asked.
    "documents.queue_heading_open": {"en": "Review queue", "uk": "Черга звірки"},
    "documents.queue_heading_needs_correction": {"en": "Marked for correction", "uk": "Позначено для виправлення"},
    "documents.queue_lead_open": {
        "en": "Files with values the software read that you have not checked yet. Each card says what it "
              "still needs; open one to compare its values with the page beside them.",
        "uk": "Файли зі значеннями, які програма зчитала, а ви ще не перевірили. На кожній картці сказано, "
              "чого вона ще потребує; відкрийте файл, щоб звірити значення зі сторінкою поруч.",
    },
    "documents.queue_lead_needs_correction": {
        "en": "Files you marked as read wrongly. Open one to correct its values, then confirm it again.",
        "uk": "Файли, які ви позначили як зчитані неправильно. Відкрийте файл, виправте значення й підтвердьте його знову.",
    },
    "documents.filters_toggle": {"en": "Search and filters", "uk": "Пошук і фільтри"},
    "documents.values_to_check_one": {"en": "{count} value to check", "uk": "{count} значення чекає звірки"},
    "documents.values_to_check_few": {"en": "{count} values to check", "uk": "{count} значення чекають звірки"},
    "documents.values_to_check_many": {"en": "{count} values to check", "uk": "{count} значень чекають звірки"},
    "documents.search": {"en": "Search", "uk": "Пошук"},
    "documents.search_placeholder": {
        "en": "title, result, keyword, tag or filename",
        "uk": "назва, результат, ключове слово, мітка або ім’я файлу",
    },
    "documents.type": {"en": "Type", "uk": "Тип"},
    "documents.all_types": {"en": "All types", "uk": "Усі типи"},
    "documents.vendor": {"en": "Vendor", "uk": "Заклад"},
    "documents.all_vendors": {"en": "All vendors", "uk": "Усі заклади"},
    "documents.review_state": {"en": "Review status", "uk": "Стан звірки"},
    "documents.review_all": {"en": "All documents", "uk": "Усі документи"},
    "documents.review_open": {"en": "Awaiting review", "uk": "Чекають звірки"},
    "documents.review_resolved": {"en": "Checked", "uk": "Звірені"},
    "documents.review_needs_correction": {
        "en": "Needs correction", "uk": "Потребують виправлення",
    },
    "documents.filter": {"en": "Filter", "uk": "Фільтр"},
    "documents.duplicate": {"en": "duplicate", "uk": "дублікат"},
    "documents.page": {"en": "page", "uk": "сторінка"},
    "documents.pages": {"en": "pages", "uk": "сторінки"},
    "documents.results": {"en": "results", "uk": "результати"},
    "documents.empty_title": {"en": "No matching documents", "uk": "Документів не знайдено"},
    "documents.empty_body": {
        "en": "Try a broader keyword or clear a filter.",
        "uk": "Спробуйте загальніше слово або скиньте фільтр.",
    },

    # Document detail
    "doc.back": {"en": "Back to documents", "uk": "Назад до документів"},
    "doc.report_date": {"en": "Report date", "uk": "Дата документа"},
    "doc.date_invalid": {"en": "Enter a valid report date in YYYY-MM-DD format.", "uk": "Вкажіть правильну дату документа у форматі РРРР-ММ-ДД."},
    "doc.title": {"en": "Document title", "uk": "Назва документа"},
    "doc.edit_metadata": {"en": "Title and date", "uk": "Назва й дата"},
    "doc.save_metadata": {"en": "Save title and date", "uk": "Зберегти назву й дату"},
    "doc.original_title": {"en": "Original report title", "uk": "Назва в оригіналі"},
    # A title the reader set themselves is theirs, not "the original report title".
    "doc.title_yours": {"en": "Your title for it", "uk": "Ваша назва"},
    "doc.title_more_one": {"en": "+{count} more", "uk": "і ще {count}"},
    "doc.title_more_few": {"en": "+{count} more", "uk": "і ще {count}"},
    "doc.title_more_many": {"en": "+{count} more", "uk": "і ще {count}"},
    "doc.original_label": {"en": "Original source label", "uk": "Назва в оригіналі"},
    "doc.imported": {"en": "Imported {date}", "uk": "Імпортовано {date}"},
    "doc.duplicate_title": {"en": "Exact duplicate linked.", "uk": "Це точна копія."},
    "doc.duplicate_body": {
        "en": "This file has the same SHA-256 content as",
        "uk": "Вміст файлу (SHA-256) збігається з документом",
    },
    "doc.duplicate_tail": {
        "en": "; observations were not duplicated.",
        "uk": "; значення не продубльовано.",
    },
    # The same report held as two files (a re-export of one PDF), and what to do.
    "dup.title": {"en": "Same report in another file", "uk": "Той самий документ в іншому файлі"},
    "dup.same_as": {"en": "Same report as", "uk": "Той самий документ, що й"},
    "dup.reason_text": {
        "en": "Both files carry the same text, apart from letter case, line breaks, page numbers, the date and time of printing, and a file path or web address in a header or footer.",
        "uk": "Текст обох файлів однаковий, якщо не зважати на регістр літер, перенесення рядків, номери сторінок, дату й час друку та шлях до файлу чи веб-адресу в колонтитулі.",
    },
    "dup.reason_content_hash": {
        "en": "Both files were read to exactly the same text.",
        "uk": "З обох файлів зчитано точно той самий текст.",
    },
    "dup.reason_same_order": {
        "en": "Both print the same order: the same order or barcode number with the same date, or the same order and result times.",
        "uk": "В обох надруковано те саме замовлення: той самий номер замовлення чи штрихкод із тією самою датою або той самий час замовлення й результату.",
    },
    "dup.reason_report_number": {
        "en": "Both carry the same printed report number and issue date.",
        "uk": "В обох надруковано той самий номер документа й дату видачі.",
    },
    "dup.reason_results_one": {
        "en": "Both hold the same {count} result, on the same date.",
        "uk": "В обох той самий {count} результат за ту саму дату.",
    },
    "dup.reason_results_few": {
        "en": "Both hold the same {count} results, on the same dates.",
        "uk": "В обох ті самі {count} результати за ті самі дати.",
    },
    "dup.reason_results_many": {
        "en": "Both hold the same {count} results, on the same dates.",
        "uk": "В обох ті самі {count} результатів за ті самі дати.",
    },
    "dup.same_as_help": {
        "en": "If it is one report, keep one file and mark the other as its copy, so each value is counted and checked once.",
        "uk": "Якщо це один звіт, залиште один файл, а інший позначте як його копію - тоді кожне значення врахується й перевірятиметься один раз.",
    },
    "dup.suggested": {
        "en": "Suggested: keep the older import. The record has been counting its values.",
        "uk": "Радимо залишити файл, імпортований раніше: його значення вже враховано в картці.",
    },
    "dup.reason_page_text": {
        "en": "Nearly every word and number of one file is also in the other. A photo or scan prints no order number, so its text was compared.",
        "uk": "Майже кожне слово й число одного файлу є і в іншому. На фото чи скані немає номера замовлення, тож порівняно текст.",
    },
    "dup.suggested_lab_order": {
        "en": "Suggested: keep the file linked to the lab's order. Its values are checked against the lab's own record.",
        "uk": "Радимо залишити файл, пов'язаний із замовленням у лабораторії: його значення звіряються із записом лабораторії.",
    },
    "dup.suggested_whole": {
        "en": "Suggested: keep the whole report. The other file is a photo, screenshot or part of it.",
        "uk": "Радимо залишити повний звіт. Інший файл - це його фото, знімок екрана чи частина.",
    },
    "dup.keep_other": {
        "en": "Keep that one: mark this copy as a duplicate",
        "uk": "Залишити той, а цей позначити копією",
    },
    "dup.keep_this": {
        "en": "Keep this one: mark that one as a duplicate",
        "uk": "Залишити цей, а той позначити копією",
    },
    "dup.keep_both": {"en": "Different reports: keep both", "uk": "Це різні документи: залишити обидва"},
    "dup.copy_of": {"en": "This is a copy of", "uk": "Це копія документа"},
    "dup.copy_of_tail": {
        "en": ". Its values are counted once, from that document.",
        "uk": ". Значення враховуються лише раз, із того документа.",
    },
    "dup.unmark": {"en": "Not a duplicate", "uk": "Це не дублікат"},
    "dup.unmark_help": {
        "en": "\"Not a duplicate\" makes this file a document of its own again and re-reads it, so its values come back for checking.",
        "uk": "«Це не дублікат» знову робить цей файл окремим документом і перечитує його, тож його значення повернуться на перевірку.",
    },
    "dup.copy_held": {"en": "A copy of this report is also held:", "uk": "Є також копія цього документа:"},
    "dup.rel_contains": {"en": "Holds every result of", "uk": "Містить усі результати з документа"},
    "dup.rel_contained_in": {"en": "Every result here is also in", "uk": "Усі ці результати є і в документі"},
    "dup.rel_reprint": {
        "en": "Same report number, issued on another day:",
        "uk": "Той самий номер документа, але інша дата видачі:",
    },
    "dup.rel_overlaps": {"en": "Shares some results with", "uk": "Частина результатів збігається з документом"},
    "dup.rel_results_for": {"en": "Holds the results for the order cover", "uk": "Містить результати до бланка замовлення"},
    "dup.rel_results_in": {"en": "The results for this order are in", "uk": "Результати цього замовлення є в документі"},
    "dup.rel_supplement_of": {
        "en": "Supplement printed for the same order as",
        "uk": "Додаток, надрукований до того самого замовлення, що й",
    },
    "dup.rel_has_supplement": {
        "en": "A supplement for this order (cell images, explanations) is in",
        "uk": "Додаток до цього замовлення (зображення клітин, пояснення) є в документі",
    },
    "dup.rel_part_of": {
        "en": "Screenshot of one report, uploaded with its first part:",
        "uk": "Знімок екрана одного звіту, надісланий разом із його першою частиною:",
    },
    "dup.rel_has_part": {"en": "Next screenshot of this report:", "uk": "Наступний знімок екрана цього звіту:"},
    "dup.parts_explain": {
        "en": "These screenshots were uploaded together and show one report: they print the same order, or one picks up where the other ends. Each keeps its own values to check. If one belongs to another report, unlink it.",
        "uk": "Ці знімки екрана надіслано разом, і вони показують один звіт: на них те саме замовлення, або один продовжує інший. Значення кожного перевіряються окремо. Якщо знімок належить до іншого звіту, від'єднайте його.",
    },
    "dup.not_part": {"en": "Not part of this report", "uk": "Це не частина цього звіту"},
    "dup.rel_person_part_of": {"en": "Page or part of the report", "uk": "Сторінка або частина звіту"},
    "dup.rel_person_has_part": {
        "en": "Page or part of this report, linked by a person:",
        "uk": "Сторінка або частина цього звіту, приєднана людиною:",
    },
    "dup.person_parts_explain": {
        "en": "A person linked these files as pages or parts of one report, for example phone photos of its pages. Each file keeps its own pages and values. The report shows the pages of its parts, and checking the report checks its parts too. A re-read never undoes this link; the \"Not part of this report\" button does.",
        "uk": "Людина приєднала ці файли як сторінки або частини одного звіту, наприклад фото його сторінок з телефона. Кожен файл зберігає власні сторінки та значення. У звіті видно сторінки його частин, а перевірка звіту перевіряє і їх. Повторне читання не скасовує цей зв'язок, а кнопка «Це не частина цього звіту» скасовує.",
    },
    "dup.part_pages": {"en": "Pages of {title}", "uk": "Сторінки документа {title}"},
    "dup.part_heading": {"en": "Part of another report", "uk": "Частина іншого звіту"},
    "dup.part_help": {
        "en": "Use this when this file is one page or part of a report already in the record, for example a second photo of a printed report. Both files stay; the report shows this file's pages, and checking the report checks this file too. You can undo it here or on the report.",
        "uk": "Скористайтеся цим, якщо файл є сторінкою або частиною звіту, який уже є в записі, наприклад друге фото надрукованого звіту. Обидва файли залишаються; у звіті видно сторінки цього файла, а перевірка звіту перевіряє і цей файл. Скасувати можна тут або у звіті.",
    },
    "dup.part_report": {"en": "Report this file belongs to", "uk": "Звіт, до якого належить цей файл"},
    "dup.part_choose": {"en": "Choose a report", "uk": "Виберіть звіт"},
    "dup.part_action": {"en": "Link as part of this report", "uk": "Приєднати як частину цього звіту"},
    "dup.part_review_note": {
        "en": "This file is part of a report, and checking that report checks this file too:",
        "uk": "Цей файл є частиною звіту, і перевірка того звіту перевіряє і цей файл:",
    },
    "dup.parts_review_note_one": {
        "en": "Checking this report also checks its {count} linked part.",
        "uk": "Перевірка цього звіту перевіряє і {count} приєднану частину.",
    },
    "dup.parts_review_note_few": {
        "en": "Checking this report also checks its {count} linked parts.",
        "uk": "Перевірка цього звіту перевіряє і {count} приєднані частини.",
    },
    "dup.parts_review_note_many": {
        "en": "Checking this report also checks its {count} linked parts.",
        "uk": "Перевірка цього звіту перевіряє і {count} приєднаних частин.",
    },
    "dup.card_part": {
        "en": "Screenshot of one report sent in several parts. Open to see the other parts",
        "uk": "Знімок екрана звіту, надісланого кількома частинами. Відкрийте, щоб побачити інші частини",
    },
    "dup.explain": {
        "en": "A copy is a second file of a report already in the record. The same PDF exported again, for example. Marking it keeps the file but counts its values once, from the document you keep, and takes it out of the review queue. You can undo it from the copy.",
        "uk": "Копія - це другий файл звіту, який уже є в записі, наприклад той самий PDF, експортований ще раз. Позначена копія зберігається, але її значення враховуються один раз, з документа, який ви залишаєте, і вона зникає з черги перевірки. Це можна скасувати на сторінці копії.",
    },
    "dup.card_same_as": {
        "en": "Same report as \"{title}\" ({date}). Open to choose which file to keep",
        "uk": "Той самий документ, що й «{title}» ({date}). Відкрийте, щоб вибрати, який файл залишити",
    },
    "dup.error_already": {
        "en": "Nothing was changed: this file is already marked as a copy.",
        "uk": "Нічого не змінено: цей файл уже позначено як копію.",
    },
    "dup.error_self": {
        "en": "Nothing was changed: a file cannot be a copy of itself or of its own copy.",
        "uk": "Нічого не змінено: файл не може бути копією самого себе чи власної копії.",
    },
    "dup.error_patient": {
        "en": "Nothing was changed: the two files belong to different patients.",
        "uk": "Нічого не змінено: ці два файли належать різним пацієнтам.",
    },
    "dup.error_busy": {
        "en": "Nothing was changed: this file is being re-read right now. Try again when the re-read finishes.",
        "uk": "Нічого не змінено: цей файл саме зчитується повторно. Спробуйте ще раз, коли зчитування завершиться.",
    },
    "dup.error_ruled": {
        "en": "Nothing was changed: this copy holds values a person checked, corrected, entered or set aside that the document you keep does not hold. Check those values on the document you keep first, or keep both.",
        "uk": "Нічого не змінено: у цій копії є значення, які людина звірила, виправила, внесла вручну чи відхилила, а в документі, який ви залишаєте, їх немає. Спершу звірте ці значення в документі, який залишаєте, або залиште обидва.",
    },
    "dup.error_missing": {
        "en": "Nothing was changed: this copy holds a test the document you keep does not hold at all, so marking it would remove that result from the record. Keep this one instead, or keep both.",
        "uk": "Нічого не змінено: у цій копії є аналіз, якого зовсім немає в документі, який ви залишаєте, тож позначення прибрало б цей результат із запису. Залиште натомість цей файл або обидва.",
    },
    "dup.error_not_duplicate": {
        "en": "Nothing was changed: this file is not marked as a copy.",
        "uk": "Нічого не змінено: цей файл не позначено як копію.",
    },
    "dup.error_same_bytes": {
        "en": "Nothing was changed: this file is byte for byte the same as the original, so as a document of its own it would count every value twice.",
        "uk": "Нічого не змінено: цей файл побайтово збігається з оригіналом, тож як окремий документ він враховував би кожне значення двічі.",
    },
    "doc.normalized": {"en": "Normalized data", "uk": "Дані документа"},
    "doc.extracted": {"en": "Extracted observations", "uk": "Зчитані значення"},
    "doc.total": {"en": "{count} total", "uk": "Усього: {count}"},
    # The printed interval, named: a bare "Not supplied" did not say what was missing.
    "doc.lab_reference": {"en": "Lab reference: {range}", "uk": "Норма лабораторії: {range}"},
    "doc.row_error": {
        "en": "That change was not saved. Try again, or reload the page to see the current value.",
        "uk": "Зміну не збережено. Спробуйте ще раз або оновіть сторінку, щоб побачити поточне значення.",
    },
    "doc.rows_error": {
        "en": "The rows could not be loaded. Check the connection and press the button again.",
        "uk": "Не вдалося завантажити рядки. Перевірте з'єднання та натисніть кнопку ще раз.",
    },
    "doc.rows_loading": {"en": "Loading the rows...", "uk": "Завантажуємо рядки..."},
    "doc.lab_differences_one": {"en": "{count} difference to check", "uk": "{count} розбіжність для перевірки"},
    "doc.lab_differences_few": {"en": "{count} differences to check", "uk": "{count} розбіжності для перевірки"},
    "doc.lab_differences_many": {"en": "{count} differences to check", "uk": "{count} розбіжностей для перевірки"},
    "doc.lab_all_match": {"en": "Everything matches", "uk": "Усе збігається"},
    # An allergy panel folds its negatives into one line.
    "doc.allergy_negatives_one": {
        "en": "{count} allergen judged negative. Show it",
        "uk": "{count} алерген оцінено як негативний. Показати",
    },
    "doc.allergy_negatives_few": {
        "en": "{count} allergens judged negative. Show them",
        "uk": "{count} алергени оцінено як негативні. Показати",
    },
    "doc.allergy_negatives_many": {
        "en": "{count} allergens judged negative. Show them",
        "uk": "{count} алергенів оцінено як негативні. Показати",
    },
    "doc.allergen": {"en": "Allergen", "uk": "Алерген"},
    "doc.allergen_printed": {"en": "As printed", "uk": "Як на бланку"},
    "doc.allergen_value": {"en": "Result", "uk": "Результат"},
    "doc.allergy_review_rows": {"en": "Check or correct these values", "uk": "Звірити або виправити значення"},
    "doc.th_metric": {"en": "Metric", "uk": "Показник"},
    "doc.th_result": {"en": "Result", "uk": "Результат"},
    "doc.th_range": {"en": "Vendor range", "uk": "Інтервал надавача"},
    "doc.th_status": {"en": "Status", "uk": "Статус"},
    "doc.th_page": {"en": "Page", "uk": "Стор."},
    "doc.correct": {"en": "Correct", "uk": "Виправити"},
    "doc.metric_name": {"en": "Metric name", "uk": "Назва показника"},
    "doc.numeric": {"en": "Numeric value", "uk": "Числове значення"},
    "doc.text_value": {"en": "Text value", "uk": "Текстове значення"},
    "doc.unit": {"en": "Unit", "uk": "Одиниця"},
    "doc.vendor_ref": {"en": "Vendor reference", "uk": "Норма лабораторії"},
    "doc.save": {"en": "Save correction", "uk": "Зберегти виправлення"},
    "doc.no_obs": {
        "en": "No structured observations were accepted from this report.",
        "uk": "Жодного значення з цього документа не прийнято.",
    },
    "doc.evidence": {"en": "Evidence", "uk": "Джерело"},
    # The exact line the parser read. On a phone the page image is a scroll
    # away, so without this the reviewer is asked to certify a number against
    # evidence that is not on screen.
    "doc.evidence_line": {"en": "Read from the page as", "uk": "Зчитано зі сторінки"},
    # Free text the report or the lab's own record keeps beside a result,
    # shown as written: «… є контамінантом», «… природньо резистентний до …».
    "doc.note_line": {"en": "Note from the laboratory or report", "uk": "Примітка лабораторії або документа"},
    # A derived eGFR row: say it was calculated, from what, and how.
    "doc.derived_from": {"en": "Calculated from", "uk": "Розраховано за"},
    "doc.derived_egfr": {
        "en": "Not printed on the report: calculated by this record from the creatinine on this page with the CKD-EPI 2021 equation (no race coefficient), using your age and sex on the day of the test.",
        "uk": "У документі цього показника немає: Anamna розрахувала його з креатиніну на цій сторінці за формулою CKD-EPI 2021 (без расового коефіцієнта), з урахуванням вашого віку та статі на день аналізу.",
    },
    "doc.file_type": {"en": "File format", "uk": "Формат файлу"},
    # Rule 5: two raw technical labels sat unexplained on the details panel.
    "doc.sha256": {"en": "File fingerprint (SHA-256)", "uk": "Відбиток файлу (SHA-256)"},
    "doc.sha256_hint": {
        "en": "A checksum of the exact bytes of this file. It is how the record recognises the same file uploaded twice, and how it proves the stored file has not changed since it arrived.",
        "uk": "Контрольна сума точних байтів цього файлу. Саме за нею запис розпізнає той самий файл, завантажений двічі, і підтверджує, що збережений файл не змінився з моменту надходження.",
    },
    "doc.mime": {"en": "File format", "uk": "Формат файлу"},
    "doc.mime_hint": {
        "en": "What kind of file this is, a PDF, a photograph, a scan, which decides how the text was read out of it.",
        "uk": "Який це файл - PDF, фотографія, скан - від чого залежить, як із нього зчитано текст.",
    },
    # Rule 5: a "<" in front of a result is a clinical statement, not a typo.
    "obs.comparator_hint": {
        "en": "Keep a «<» or «>» before the number: «<0.01» means below what the test can detect.",
        "uk": "Не прибирайте знак «<» чи «>» перед числом: «<0,01» означає, що значення нижче порогу, який здатен виявити аналіз.",
    },
    "doc.original_source": {"en": "Original source", "uk": "Оригінальне джерело"},
    "doc.pages_label": {"en": "Pages", "uk": "Сторінки"},
    "doc.strategy": {"en": "Strategy", "uk": "Спосіб зчитування"},
    "doc.open_file": {"en": "Open original file", "uk": "Відкрити оригінальний файл"},
    "doc.maintenance": {"en": "Keeping it current", "uk": "Оновлення"},
    "doc.delete_heading": {"en": "Delete document", "uk": "Видалити документ"},
    "doc.delete_hint": {
        "en": "Deletes this file and every value read from it.",
        "uk": "Видаляє цей файл і всі значення, зчитані з нього.",
    },
    "doc.delete_action": {"en": "Delete document", "uk": "Видалити документ"},
    "doc.delete_confirm": {
        "en": "Delete \"{name}\" and all data extracted from it? This cannot be undone.",
        "uk": "Видалити «{name}» і всі зчитані з нього дані? Цю дію не можна скасувати.",
    },
    "doc.delete_done": {"en": "Document deleted.", "uk": "Документ видалено."},
    "doc.delete_promoted": {
        "en": "A surviving exact copy is now the primary document and is being re-read.",
        "uk": "Основним документом стала точна копія, яка залишилася. Зараз ми зчитуємо її повторно.",
    },
    "doc.delete_busy": {
        "en": "This document is being re-read right now. Wait for processing to finish, then delete it.",
        "uk": "Документ саме зчитується повторно. Дочекайтеся завершення, а тоді видаліть його.",
    },
    "doc.organization": {"en": "Organization", "uk": "Організація"},
    "doc.tags": {"en": "Tags", "uk": "Мітки"},
    "doc.no_tags": {"en": "No tags yet", "uk": "Міток ще немає"},
    "doc.add_tag": {"en": "Add a tag", "uk": "Додати мітку"},
    "doc.add": {"en": "Add", "uk": "Додати"},
    "doc.side_panels": {"en": "Evidence panels", "uk": "Вкладки документа"},
    "doc.tab_observations": {"en": "Observations", "uk": "Значення"},
    "doc.tab_text": {"en": "Page text", "uk": "Текст сторінки"},
    "doc.tab_details": {"en": "Details", "uk": "Подробиці"},
    # A narrative report opens on what it concluded.
    "doc.tab_conclusion": {"en": "Conclusion", "uk": "Висновок"},
    "doc.conclusion_heading": {"en": "What the report concluded", "uk": "Що зазначено у висновку"},
    "doc.conclusion_help": {
        "en": "Each card is the report's own conclusion, filed under the body areas it concerns. The page link "
              "shows where it is printed. A conclusion marked for attention is one the report itself describes "
              "as a change from normal.",
        "uk": "Кожна картка - це висновок самого звіту, віднесений до ділянок тіла, яких він стосується. Посилання "
              "на сторінку показує, де його надруковано. Висновок, позначений для уваги, той, який сам звіт "
              "описує як відхилення від норми.",
    },
    "doc.conclusion_none": {
        "en": "No conclusion has been read from this report yet. Its full text is under Page text, and re-reading "
              "the file from Details applies whatever the software has learned since.",
        "uk": "Висновок із цього документа ще не зчитано. Повний текст є на вкладці «Текст сторінки». Повторне зчитування на вкладці «Подробиці» застосує все, чого програма навчилася відтоді.",
    },
    "doc.conclusion_read_text": {"en": "Read the page text", "uk": "Відкрити текст сторінки"},
    "doc.finding_areas": {"en": "Concerns", "uk": "Стосується"},
    "doc.finding_more": {"en": "Show the whole passage", "uk": "Показати весь фрагмент"},
    "doc.finding_correct": {"en": "Correct the text from the image", "uk": "Виправити текст за зображенням"},
    "doc.finding_correct_help": {
        "en": "When the text read from a photo has stray characters or missing words, write the conclusion as the image shows it. Your text is shown instead of what was read, is kept when the file is read again, and the text as read stays available.",
        "uk": "Якщо в тексті, прочитаному з фото, є зайві символи або бракує слів, напишіть висновок так, як його видно на зображенні. Ваш текст показується замість прочитаного, зберігається під час повторного читання файла, а прочитаний текст залишається доступним.",
    },
    "doc.finding_summary_label": {"en": "Conclusion", "uk": "Висновок"},
    "doc.finding_save": {"en": "Save the corrected text", "uk": "Зберегти виправлений текст"},
    "doc.finding_revert": {"en": "Undo the correction", "uk": "Скасувати виправлення"},
    "doc.finding_corrected_badge": {"en": "Corrected by a person", "uk": "Виправлено людиною"},
    "doc.finding_corrected_by": {
        "en": "Written from the image of the report by {name}, {date}.",
        "uk": "Текст записано за зображенням звіту: {name}, {date}.",
    },
    "doc.finding_corrected_help": {
        "en": "Corrected from the image of the report by a person.",
        "uk": "Виправлено людиною за зображенням звіту.",
    },
    "doc.finding_read_text": {"en": "Show the text as read", "uk": "Показати прочитаний текст"},
    "doc.finding_add_heading": {"en": "Add the conclusion", "uk": "Додати висновок"},
    "doc.finding_add_help": {
        "en": "If the photo shows a conclusion or diagnosis that was not read, write it here as the image shows it. It is kept when the file is read again, and stays until you remove it.",
        "uk": "Якщо на фото є висновок або діагноз, який не вдалося прочитати, напишіть його тут так, як його видно на зображенні. Він зберігається під час повторного читання файла, і залишається, доки ви його не видалите.",
    },
    "doc.finding_date_label": {"en": "Date of the conclusion", "uk": "Дата висновку"},
    "doc.finding_area_label": {"en": "Health area", "uk": "Розділ здоров'я"},
    "doc.finding_area_auto": {"en": "Decide from the text", "uk": "Визначити за текстом"},
    "doc.finding_add": {"en": "Add the conclusion", "uk": "Додати висновок"},
    "doc.finding_added_badge": {"en": "Written by a person", "uk": "Записано людиною"},
    "doc.finding_remove": {"en": "Remove this conclusion", "uk": "Видалити цей висновок"},
    "doc.finding_error_area": {
        "en": "The text does not name an organ or a diagnosis code, so the health area could not be decided. Choose one in the list.",
        "uk": "У тексті немає назви органа чи коду діагнозу, тому розділ здоров'я не визначено. Виберіть його у списку.",
    },
    "doc.finding_error_exists": {
        "en": "This document already has a conclusion in that health area. Correct that one instead.",
        "uk": "Цей документ уже має висновок у цьому розділі здоров'я. Виправте його замість додавання нового.",
    },
    "doc.finding_error_date": {
        "en": "The date is not a calendar date. Use the date picker.",
        "uk": "Дата не є календарною датою. Скористайтеся вибором дати.",
    },
    "doc.finding_as_printed_uk": {
        "en": "As printed in the report, in Ukrainian. No English summary has been written for it.",
        "uk": "Як надруковано в документі, українською.",
    },
    "doc.finding_as_printed_en": {
        "en": "As written, in English.",
        "uk": "Як записано, англійською. Українського підсумку немає.",
    },
    "doc.key_measurements": {"en": "Measurements in this report", "uk": "Вимірювання в документі"},
    "doc.details_heading": {"en": "Document details", "uk": "Подробиці документа"},
    "doc.show_page": {"en": "Show page {page} in source", "uk": "Показати сторінку {page} в оригіналі"},
    # Review bench: the source page follows the list of values (source-viewer.js).
    "doc.sync_hint": {
        "en": (
            "Values are listed in the order the document prints them, and the original page follows "
            "this list: the value at the top is framed on its page where the text layer shows it, "
            "and turning the page brings that page's values to the top. Values read from a scan are not framed."
        ),
        "uk": (
            "Значення наведено в тому порядку, у якому їх надруковано в документі, а оригінальна сторінка "
            "рухається разом зі списком: значення вгорі списку обведено рамкою на його сторінці, якщо "
            "текстовий шар документа дозволяє його знайти, а перегорнута сторінка піднімає свої значення "
            "на початок списку. Значення, прочитані зі скану, рамкою не позначаються."
        ),
    },
    "doc.compound": {"en": "Compound document", "uk": "Складений документ"},
    "doc.sections": {"en": "Logical report sections", "uk": "Розділи документа"},
    "doc.sections_count": {"en": "{count} sections", "uk": "{count} розділів"},
    "doc.pages_range": {"en": "Pages {start}-{end}", "uk": "Сторінки {start}-{end}"},
    "doc.page_audit": {"en": "Page-level audit", "uk": "Посторінкова перевірка"},
    "doc.extracted_text": {"en": "Extracted text evidence", "uk": "Зчитаний текст"},
    "doc.native_ocr_note": {
        "en": "Native text and OCR remain separate",
        "uk": "Рідний текст і OCR залишаються окремими",
    },
    "doc.page_n": {"en": "Page {n}", "uk": "Сторінка {n}"},
    "doc.native_chars": {
        "en": "{count} native characters",
        "uk": "Символів у текстовому шарі: {count}",
    },
    "doc.native_pdf": {"en": "Native PDF text", "uk": "Текстовий шар PDF"},
    "doc.ocr_title": {
        "en": "Embedded-image OCR (provisional)",
        "uk": "Розпізнавання тексту на зображеннях (попередньо)",
    },
    "doc.no_text": {
        "en": "No machine-readable text. Visual review required.",
        "uk": "Тексту, який можна зчитати, немає. Звірте сторінку візуально.",
    },

    # Review
    "review.title": {"en": "Review queue · Anamna", "uk": "Черга перевірки · Anamna"},
    "review.eyebrow": {"en": "Source comparison", "uk": "Звірка з джерелом"},
    "review.heading": {"en": "Review extracted values", "uk": "Звірка витягнутих значень"},
    "review.lead": {
        "en": "Compare each extracted value with the attached source page.",
        "uk": "Порівняйте кожне витягнуте значення з доданою сторінкою джерела.",
    },
    "review.pending_files_one": {
        "en": "{count} file still needs comparison with its source page.",
        "uk": "{count} файл очікує звірки зі сторінкою джерела.",
    },
    "review.pending_files_few": {
        "en": "{count} files still need comparison with their source pages.",
        "uk": "{count} файли очікують звірки зі сторінками джерел.",
    },
    "review.pending_files_many": {
        "en": "{count} files still need comparison with their source pages.",
        "uk": "{count} файлів очікують звірки зі сторінками джерел.",
    },
    "review.open": {"en": "Awaiting review", "uk": "Очікують звірки"},
    "review.verified": {"en": "Checked", "uk": "Звірені"},
    "review.correction": {"en": "Needs correction", "uk": "Потребують виправлення"},
    "review.observations": {
        "en": "Observations: {count}",
        "uk": "Спостережень: {count}",
    },
    "review.observations_one": {"en": "{count} observation", "uk": "{count} спостереження"},
    "review.observations_few": {"en": "{count} observations", "uk": "{count} спостереження"},
    "review.observations_many": {"en": "{count} observations", "uk": "{count} спостережень"},
    "review.open_source": {"en": "Open original", "uk": "Відкрити оригінал"},
    "review.needs_correction": {"en": "Mark for correction", "uk": "Позначити для виправлення"},
    "review.checked": {"en": "Confirm file matches source", "uk": "Підтвердити збіг з оригіналом"},
    "review.clear_title": {"en": "Queue clear", "uk": "Черга порожня"},
    "review.clear_body": {"en": "No items in this state.", "uk": "Немає елементів у цьому стані."},
    # An empty queue means two entirely different things and used to say
    # neither: nothing has been uploaded yet, or everything has been checked.
    "review.clear_body_empty": {
        "en": "Nothing has been uploaded yet. Add a scan, a photo or a lab PDF and its values arrive here to be checked.",
        "uk": "Ще нічого не завантажено. Додайте скан, фото або PDF з лабораторії, і його значення з’являться тут для перевірки.",
    },
    "review.clear_body_done": {
        "en": "Every value in this record has been ruled on. New values arrive here whenever a file is uploaded or re-read.",
        "uk": "Щодо кожного значення в цьому записі ухвалено рішення. Нові значення з’являтимуться тут після завантаження або повторного зчитування файлу.",
    },
    "review.clear_next_upload": {"en": "Upload a document", "uk": "Завантажити документ"},
    "review.clear_next_documents": {"en": "Browse the documents", "uk": "Переглянути документи"},
    # Rule 5: four states appear on every row and none of them said what it
    # meant. The wording is deliberately about consequence, not about workflow.
    "review.legend_title": {"en": "What these states mean", "uk": "Що означають ці стани"},
    # A document whose values span several dates groups them by date, because
    # then the date is the only thing telling two otherwise identical rows
    # apart.  A row with no date at all still needs a heading to sit under.
    "review.undated": {"en": "No date on the page", "uk": "На сторінці немає дати"},
    "review.legend_extracted": {
        "en": "Needs verification: the software read this value off the page and nobody has checked it against the page yet. It is shown everywhere, marked as unchecked.",
        "uk": "Потребує звірки - програма зчитала це значення зі сторінки, і ніхто ще не звірив його зі сторінкою. Воно показується всюди з позначкою «не перевірено».",
    },
    "review.legend_verified": {
        "en": "Verified: a person compared it with the page and it matches. Re-reading the file will not overwrite it.",
        "uk": "Звірено - людина порівняла зі сторінкою, і воно збігається. Повторне зчитування файлу його не перезапише.",
    },
    "review.legend_corrected": {
        "en": "Corrected: a person changed what the software read. The original stays in the audit trail, and re-reading will not overwrite it.",
        "uk": "Виправлено - людина змінила те, що зчитала програма. Первісне значення лишається в журналі, і повторне зчитування його не перезапише.",
    },
    "review.legend_rejected": {
        "en": "Set aside: not a real measurement. The row is kept as evidence of what the page said, but it is left out of every chart, panel and summary.",
        "uk": "Відкладено - це не справжнє вимірювання. Рядок зберігається як свідчення того, що було на сторінці, але не потрапляє до жодного графіка, панелі чи зведення.",
    },
    "review.file_count": {"en": "{count} file(s)", "uk": "Файлів: {count}"},
    "review.queue": {"en": "Review status", "uk": "Стан звірки"},
    "review.files": {"en": "Files in this view", "uk": "Файли в цьому списку"},
    "review.files_aria": {"en": "Review files", "uk": "Файли для перевірки"},
    # Progress is counted per value, not per file: a 33-result panel and a
    # 2-result note are one file each and nothing like the same amount of work.
    "review.progress": {"en": "{checked} of {total} checked", "uk": "Звірено {checked} з {total}"},
    # A narrative report has no values, which is said rather than "0 of 0 checked".
    "review.no_values": {"en": "No numeric values", "uk": "Без числових значень"},
    "review.file_position": {"en": "File {index} of {total}", "uk": "Файл {index} з {total}"},
    "review.reopen": {"en": "Reopen for review", "uk": "Повернути на звірку"},
    "review.set_aside_n": {"en": "{count} set aside", "uk": "Відхилено: {count}"},

    # Per-value review actions.  Setting a value aside is reversible and keeps
    # the row: the parser's mistake is evidence too, and a reviewer who guesses
    # wrong must be able to take it back.
    # "Correct" is already the label of the edit form beside it, where it is a
    # verb; a second "Correct" meaning "this is right" is a different word to
    # the reader only if they read very carefully.
    "obs.verify": {"en": "Confirm", "uk": "Підтвердити"},
    "obs.reject": {"en": "Set aside", "uk": "Відхилити"},
    "obs.reject_hint": {
        "en": "Not a real result. Keep the row but stop counting it as a measurement",
        "uk": "Це не справжній результат. Рядок залишиться, але більше не враховуватиметься як вимірювання",
    },
    "obs.restore": {"en": "Restore", "uk": "Повернути"},
    "obs.maps_to": {"en": "Counts as", "uk": "Зараховується як"},
    "obs.maps_to_hint": {
        "en": "Choose the metric this value belongs to",
        "uk": "Оберіть показник, до якого належить це значення",
    },
    "obs.add": {"en": "Add a value the parser missed", "uk": "Додати значення, яке пропустила програма"},
    "obs.add_name_hint": {
        "en": "The label as printed on the page",
        "uk": "Назва так, як вона надрукована на сторінці",
    },
    "obs.add_submit": {"en": "Add value", "uk": "Додати значення"},
    "obs.entered_evidence": {
        "en": "Entered by hand during review.",
        "uk": "Внесено вручну під час звірки.",
    },
    "obs.observed_at": {"en": "Observed on", "uk": "Дата вимірювання"},
    "obs.observed_invalid": {"en": "Enter a valid observation date.", "uk": "Вкажіть правильну дату вимірювання."},
    "obs.evidence": {"en": "Source evidence", "uk": "Текст із джерела"},
    "obs.evidence_hint": {
        "en": "Optional exact text from the source page",
        "uk": "Точний текст зі сторінки (необов’язково)",
    },

    # Reporting a parser problem.  A correction fixes one number; a report is
    # how the reader says "the software misread this" so the importer itself
    # gets fixed.  Category keys mirror ISSUE_CATEGORIES in web/app.py and the
    # CHECK constraint in migration 017.
    "report.button": {"en": "Report a problem", "uk": "Повідомити про проблему"},
    "report.button_hint": {
        "en": "Flag something the importer read wrong, so the mistake can be found and fixed",
        "uk": "Позначте те, що програма зчитала неправильно, щоб помилку можна було знайти й виправити",
    },
    "report.title": {"en": "Report a reading problem", "uk": "Повідомити про помилку зчитування"},
    "report.lead": {
        "en": "Say what the software read wrong. The report is stored together with a snapshot of what was extracted, it is used to fix the importer, and the document is then re-read.",
        "uk": "Опишіть, що програма зчитала неправильно. Звіт зберігається разом зі знімком зчитаного, використовується для виправлення імпортера, після чого документ перечитується.",
    },
    "report.target": {"en": "Which value", "uk": "Яке значення"},
    "report.target_document": {
        "en": "The document itself, or a value that is missing",
        "uk": "Документ загалом або значення, якого бракує",
    },
    "report.category": {"en": "What went wrong", "uk": "Що саме не так"},
    # An empty first option is what makes `required` fire; without it the
    # first real category is submitted by anyone who never opened the list,
    # and the category is the field the whole queue is triaged by.
    "report.category_choose": {"en": "Choose one...", "uk": "Оберіть варіант"},
    "report.cat_wrong_value": {
        "en": "The number or text was read incorrectly",
        "uk": "Число або текст зчитано неправильно",
    },
    "report.cat_wrong_unit": {
        "en": "The unit is wrong or missing",
        "uk": "Одиниця неправильна або її немає",
    },
    "report.cat_wrong_metric": {
        "en": "Counted as the wrong metric",
        "uk": "Зараховано до неправильного показника",
    },
    "report.cat_wrong_reference": {
        "en": "The reference interval was read incorrectly",
        "uk": "Референтний інтервал зчитано неправильно",
    },
    "report.cat_missing_value": {
        "en": "A printed result was not picked up at all",
        "uk": "Надрукований результат узагалі не зчитано",
    },
    "report.cat_not_a_result": {
        "en": "Not a real result. Something was picked up by mistake",
        "uk": "Це не результат: щось зчитано помилково",
    },
    "report.cat_wrong_date_or_page": {
        "en": "Wrong date or page",
        "uk": "Неправильна дата або сторінка",
    },
    "report.cat_other": {"en": "Something else", "uk": "Інше"},
    "report.expected": {
        "en": "What the document actually says",
        "uk": "Що насправді надруковано в документі",
    },
    "report.description": {"en": "Details", "uk": "Подробиці"},
    "report.description_hint": {
        "en": "Anything that helps find and fix the mistake",
        "uk": "Усе, що допоможе знайти й виправити помилку",
    },
    "report.submit": {"en": "Send report", "uk": "Надіслати"},
    "report.cancel": {"en": "Cancel", "uk": "Скасувати"},
    "report.list_heading": {"en": "Reported problems", "uk": "Повідомлення про помилки"},
    "report.list_lead": {
        "en": "Each report keeps a snapshot of what was extracted when it was filed. Mark it fixed once the importer is corrected and the document re-read.",
        "uk": "Кожен звіт зберігає знімок зчитаного на момент подання. Позначте виправленим, коли імпортер виправлено, а документ перечитано.",
    },
    "report.status_open": {"en": "Open", "uk": "Відкрито"},
    "report.status_resolved": {"en": "Fixed", "uk": "Виправлено"},
    "report.resolve": {"en": "Mark fixed", "uk": "Позначити як виправлене"},
    "report.reopen": {"en": "Reopen", "uk": "Відкрити знову"},
    "report.expected_label": {"en": "Should be", "uk": "Має бути"},

    # About
    "about.title": {"en": "How it works · Anamna", "uk": "Як це працює · Anamna"},
    "about.eyebrow": {"en": "Record handling", "uk": "Обробка записів"},
    "about.heading": {
        "en": "How files and results are handled",
        "uk": "Як обробляються файли та результати",
    },
    "about.lead": {
        "en": "This page explains what is stored, how extracted values are labelled and what the status labels do not mean.",
        "uk": "На цій сторінці пояснено, що зберігається, як позначаються витягнуті значення та чого не означають статуси.",
    },
    "about.rules_heading": {"en": "What the record stores", "uk": "Що зберігає картка"},
    "about.p1_title": {"en": "Original files", "uk": "Оригінальні файли"},
    "about.p1_body": {
        "en": "Every uploaded file is stored unchanged. Each extracted value links back to the file and page it came from.",
        "uk": "Кожен завантажений файл зберігається без змін. Кожне витягнуте значення має посилання на файл і сторінку джерела.",
    },
    "about.p2_title": {"en": "Result names", "uk": "Назви результатів"},
    "about.p2_body": {
        "en": "The printed name is preserved and mapped to a standard test name. Unrecognised names remain visible for correction.",
        "uk": "Надрукована назва зберігається й зіставляється зі стандартною назвою аналізу. Нерозпізнані назви залишаються видимими для виправлення.",
    },
    "about.p3_title": {"en": "Reference intervals", "uk": "Референсні інтервали"},
    "about.p3_body": {
        "en": "The laboratory's printed interval stays with the result. Other guidance is shown separately with its source, review date and applicability.",
        "uk": "Надрукований лабораторією інтервал зберігається разом із результатом. Інші настанови показуються окремо з джерелом, датою перегляду та умовами застосування.",
    },
    "about.p4_title": {
        "en": "Verification",
        "uk": "Звірка",
    },
    "about.p4_body": {
        "en": "Automatically extracted values stay marked as unchecked until a person compares them with the original page.",
        "uk": "Автоматично витягнуті значення позначаються як незвірені, доки людина не порівняє їх з оригінальною сторінкою.",
    },
    "about.limit_title": {"en": "What the record cannot determine", "uk": "Чого картка не може визначити"},
    "about.limit_summary": {
        "en": "A status is not a diagnosis and does not replace clinical assessment.",
        "uk": "Статус не є діагнозом і не замінює клінічну оцінку.",
    },
    "about.limit_body": {
        "en": "Anamna organizes medical records; it does not diagnose conditions or replace a clinician. Reference intervals and clinical decision limits are different things. A result can be inside a laboratory interval yet require clinical attention, or outside it without indicating disease. Interpretation depends on method, specimen, age, sex, medications, symptoms and clinical context.",
        "uk": "Anamna впорядковує медичні записи; вона не ставить діагнозів і не замінює лікаря. Референсні інтервали та клінічні пороги рішень - різні речі. Результат може бути всередині лабораторного інтервалу і все одно потребувати уваги, або поза ним без ознак хвороби. Інтерпретація залежить від методу, зразка, віку, статі, ліків, симптомів і клінічного контексту.",
    },

    # Shared labels / errors
    "date.unknown": {"en": "Date unknown", "uk": "Дата невідома"},
    "other.results": {"en": "Other results", "uk": "Інші результати"},
    "unknown.provider": {"en": "Unknown provider", "uk": "Невідоме джерело"},
    "unknown.vendor": {"en": "Unknown vendor", "uk": "Невідомий надавач"},
    "auth.required": {"en": "Authentication required", "uk": "Потрібно увійти"},
    "csrf.invalid": {"en": "Invalid CSRF token", "uk": "Недійсний CSRF-токен. Оновіть сторінку й спробуйте ще раз."},
    "source.unavailable": {"en": "Source file is unavailable", "uk": "Оригінал недоступний"},
    "obs.required": {
        "en": "A metric name and either numeric or text value are required",
        "uk": "Вкажіть назву показника і числове або текстове значення",
    },
    "obs.numeric_invalid": {"en": "Numeric value is not valid", "uk": "Числове значення введено неправильно"},
    "ref.not_supplied": {"en": "Not supplied", "uk": "Не вказано"},
    # The printed interval exists but is scoped to a different age or sex, so it
    # cannot judge this result. Saying so beats showing an interval that does
    # not apply.
    "ref.not_applicable": {
        "en": "Not applicable to this age or sex",
        "uk": "Не застосовується до цього віку чи статі",
    },
    "ref.newborns": {
        "en": "Newborns (day {day} of life): {low}-{high}",
        "uk": "Новонароджені діти ({day} день життя): {low}-{high}",
    },
    # The empty-value placeholder in a cell or reading, not a separator.
    "em.dash": {"en": "-", "uk": "-"},
    # "observation(s)" appeared 85 times on /review. Both locales are now
    # count-safe; the _one/_few/_many variants give the natural phrasing once
    # the caller selects a form from the count.
    "review.verify_n": {
        "en": "Verify every extracted observation against page evidence before marking trusted. Observations: {count}.",
        "uk": "Звірте кожне зчитане значення зі сторінкою, перш ніж позначити їх як звірені. Значень: {count}.",
    },
    "review.verify_n_one": {
        "en": "Verify {count} extracted observation against page evidence before marking trusted.",
        "uk": "Звірте {count} зчитане значення зі сторінкою, перш ніж позначити його як звірене.",
    },
    "review.verify_n_few": {
        "en": "Verify {count} extracted observations against page evidence before marking trusted.",
        "uk": "Звірте {count} зчитані значення зі сторінкою, перш ніж позначити їх як звірені.",
    },
    "review.verify_n_many": {
        "en": "Verify {count} extracted observations against page evidence before marking trusted.",
        "uk": "Звірте {count} зчитаних значень зі сторінкою, перш ніж позначити їх як звірені.",
    },
    "review.narrative": {
        "en": "Review the narrative or visual report; no structured scalar observation was inferred automatically.",
        "uk": "Перегляньте текстовий або візуальний висновок: окремих числових значень програма автоматично не виділила.",
    },
    # A re-read writes its own reason, and it carries a version and a count, so
    # the phrase table could never match it: 132 of 217 live tasks displayed an
    # English sentence to a Ukrainian reader.
    # A re-read where the file now has fewer pages than it did: a checked value
    # whose page is gone cannot be filed anywhere honestly, so it is detached
    # and the person is told, rather than shown a confident wrong grouping.
    "review.unfiled_n": {
        "en": "Some checked observations could not be re-filed: the page they were read from is no longer in this document, so check where they belong. Observations: {count}.",
        "uk": "Деякі звірені значення не вдалося заново прив’язати: сторінки, з якої їх зчитано, у документі більше немає. Перевірте, куди вони належать. Значень: {count}.",
    },
    "review.unfiled_n_one": {
        "en": "{count} checked observation could not be re-filed: the page it was read from is no longer in this document, so check where it belongs.",
        "uk": "Не вдалося заново прив’язати {count} звірене значення: сторінки, з якої його зчитано, у документі більше немає. Перевірте, куди воно належить.",
    },
    "review.unfiled_n_few": {
        "en": "{count} checked observations could not be re-filed: the page they were read from is no longer in this document, so check where they belong.",
        "uk": "Не вдалося заново прив’язати {count} звірені значення: сторінки, з якої їх зчитано, у документі більше немає. Перевірте, куди вони належать.",
    },
    "review.unfiled_n_many": {
        "en": "{count} checked observations could not be re-filed: the page they were read from is no longer in this document, so check where they belong.",
        "uk": "Не вдалося заново прив’язати {count} звірених значень: сторінки, з якої їх зчитано, у документі більше немає. Перевірте, куди вони належать.",
    },
    "review.rescanned_n": {
        "en": "Re-read with parser {version}. Verify the observations the earlier parse did not produce. Observations: {count}.",
        "uk": "Перечитано програмою версії {version}. Звірте значення, яких не було після попереднього зчитування. Значень: {count}.",
    },
    "review.rescanned_n_one": {
        "en": "Re-read with parser {version}: verify {count} observation the earlier parse did not produce.",
        "uk": "Перечитано програмою версії {version}: звірте {count} значення, якого не було після попереднього зчитування.",
    },
    "review.rescanned_n_few": {
        "en": "Re-read with parser {version}: verify {count} observations the earlier parse did not produce.",
        "uk": "Перечитано програмою версії {version}: звірте {count} значення, яких не було після попереднього зчитування.",
    },
    "review.rescanned_n_many": {
        "en": "Re-read with parser {version}: verify {count} observations the earlier parse did not produce.",
        "uk": "Перечитано програмою версії {version}: звірте {count} значень, яких не було після попереднього зчитування.",
    },
    # The direction a re-read never used to report. A better parser is not the
    # only kind there is: a value the old one found and the new one does not is
    # a result that quietly left the record, and only the person holding the
    # printed page can say whether it was ever really there.
    "review.vanished_n": {
        "en": "Some observations the earlier parse produced are not in this one, so check the page to see whether they are really absent. Observations: {count}.",
        "uk": "Деяких значень із попереднього зчитування цього разу немає. Перевірте на сторінці, чи їх справді там немає. Значень: {count}.",
    },
    "review.vanished_n_one": {
        "en": "{count} observation the earlier parse produced is not in this one, so check the page to see whether it is really absent.",
        "uk": "{count} значення з попереднього зчитування цього разу не знайдено. Перевірте на сторінці, чи його справді там немає.",
    },
    "review.vanished_n_few": {
        "en": "{count} observations the earlier parse produced are not in this one, so check the page to see whether they are really absent.",
        "uk": "{count} значення з попереднього зчитування цього разу не знайдено. Перевірте на сторінці, чи їх справді там немає.",
    },
    "review.vanished_n_many": {
        "en": "{count} observations the earlier parse produced are not in this one, so check the page to see whether they are really absent.",
        "uk": "{count} значень із попереднього зчитування цього разу не знайдено. Перевірте на сторінці, чи їх справді там немає.",
    },
    # Review reasons stored as keys (migration 037); each was a fixed English
    # sentence in `review_tasks.reason` before.
    "review.duplicate": {
        "en": "Confirm this exact duplicate should remain linked to the original document.",
        "uk": "Підтвердіть, що цей точний дублікат має залишатися пов’язаним з оригіналом.",
    },
    "review.result_not_present": {
        "en": "The order is present but the export contains no result value.",
        "uk": "Замовлення є, але в експорті немає значення результату.",
    },
    "review.image_evidence": {
        "en": "Review the image evidence; text read from an image is never accepted as a clinical fact automatically.",
        "uk": "Перегляньте зображення: текст, розпізнаний на зображенні, ніколи не стає клінічним фактом автоматично.",
    },
    "review.companion_summary": {
        "en": "This is the lab's illustrated summary of a report's results. Its values are read from the report itself, so nothing here is entered twice; check that the report is in your record.",
        "uk": "Це ілюстрований підсумок результатів, який лабораторія додає до звіту. Значення зчитуються з самого звіту, тож тут нічого не дублюється; перевірте, що звіт є у вашій картці.",
    },
    "review.no_values_found": {
        "en": "Extraction found no values on a report of a kind the parser does read; check the pages for results it missed.",
        "uk": "Програма не знайшла жодного значення, хоча документи такого типу вона вміє зчитувати. Перевірте, чи на сторінках немає пропущених результатів.",
    },
    "review.findings": {
        "en": "Review the narrative or visual findings against the pages before marking them checked.",
        "uk": "Звірте текстові або візуальні висновки зі сторінками, перш ніж позначити їх як звірені.",
    },
    "review.vaccinations_n_one": {
        "en": "Check {count} vaccination read from this document against the page, particularly dates, dose numbers and lot numbers.",
        "uk": "Звірте зі сторінкою {count} щеплення, зчитане з цього документа. Особливо уважно перевірте дати, номери доз і серії.",
    },
    "review.vaccinations_n_few": {
        "en": "Check {count} vaccinations read from this document against the page, particularly dates, dose numbers and lot numbers.",
        "uk": "Звірте зі сторінкою {count} щеплення, зчитані з цього документа. Особливо уважно перевірте дати, номери доз і серії.",
    },
    "review.vaccinations_n_many": {
        "en": "Check {count} vaccinations read from this document against the page, particularly dates, dose numbers and lot numbers.",
        "uk": "Звірте зі сторінкою {count} щеплень, зчитаних з цього документа. Особливо уважно перевірте дати, номери доз і серії.",
    },
    # What a re-read found about values a person had already checked.  Each
    # lists the rows by name and value ({items}), so the task names what to open.
    "review.reread_changed_n_one": {
        "en": "The re-read reads {count} checked value differently; the checked value was kept, so correct it if the new reading is right: {items}.",
        "uk": "Після повторного зчитування {count} звірене значення читається інакше. Ми залишили звірене значення; якщо нове прочитання правильне, виправте його: {items}.",
    },
    "review.reread_changed_n_few": {
        "en": "The re-read reads {count} checked values differently; the checked values were kept, so correct them if the new reading is right: {items}.",
        "uk": "Після повторного зчитування {count} звірені значення читаються інакше. Ми залишили звірені значення; якщо нове прочитання правильне, виправте їх: {items}.",
    },
    "review.reread_changed_n_many": {
        "en": "The re-read reads {count} checked values differently; the checked values were kept, so correct them if the new reading is right: {items}.",
        "uk": "Після повторного зчитування {count} звірених значень читаються інакше. Ми залишили звірені значення; якщо нове прочитання правильне, виправте їх: {items}.",
    },
    "review.reread_orphaned_n_one": {
        "en": "The re-read no longer finds {count} checked value; check whether the page really prints it, and set it aside if not: {items}.",
        "uk": "{count} звірене значення під час повторного зчитування не знайшлося. Перевірте, чи воно справді є на сторінці; якщо ні, відхиліть його: {items}.",
    },
    "review.reread_orphaned_n_few": {
        "en": "The re-read no longer finds {count} checked values; check whether the page really prints them, and set aside any it does not: {items}.",
        "uk": "{count} звірені значення під час повторного зчитування не знайшлися. Перевірте, чи вони справді є на сторінці, і відхиліть ті, яких немає: {items}.",
    },
    "review.reread_orphaned_n_many": {
        "en": "The re-read no longer finds {count} checked values; check whether the page really prints them, and set aside any it does not: {items}.",
        "uk": "{count} звірених значень під час повторного зчитування не знайшлося. Перевірте, чи вони справді є на сторінці, і відхиліть ті, яких немає: {items}.",
    },
    "review.reread_reference_n_one": {
        "en": "The reference range of {count} checked value was re-read from the page and may change how it is judged; its value did not change: {items}.",
        "uk": "Норму лабораторії для {count} звіреного значення заново зчитано зі сторінки, тож його оцінка може змінитися. Саме значення не змінилося: {items}.",
    },
    "review.reread_reference_n_few": {
        "en": "The reference ranges of {count} checked values were re-read from the page and may change how they are judged; their values did not change: {items}.",
        "uk": "Норми лабораторії для {count} звірених значень заново зчитано зі сторінки, тож їхня оцінка може змінитися. Самі значення не змінилися: {items}.",
    },
    "review.reread_reference_n_many": {
        "en": "The reference ranges of {count} checked values were re-read from the page and may change how they are judged; their values did not change: {items}.",
        "uk": "Норми лабораторії для {count} звірених значень заново зчитано зі сторінки, тож їхня оцінка може змінитися. Самі значення не змінилися: {items}.",
    },
    "review.reread_dates_n_one": {
        "en": "{count} checked value now carries the date printed for the sample ({old_date} > {new_date}).",
        "uk": "{count} звірене значення тепер має дату забору, надруковану для зразка ({old_date} > {new_date}).",
    },
    "review.reread_dates_n_few": {
        "en": "{count} checked values now carry the date printed for the sample ({old_date} > {new_date}).",
        "uk": "{count} звірені значення тепер мають дату забору, надруковану для зразка ({old_date} > {new_date}).",
    },
    "review.reread_dates_n_many": {
        "en": "{count} checked values now carry the date printed for the sample ({old_date} > {new_date}).",
        "uk": "{count} звірених значень тепер мають дату забору, надруковану для зразка ({old_date} > {new_date}).",
    },
    "review.item_changed": {"en": "«{label}», page {page}: {old} > {new}", "uk": "«{label}», с. {page}: {old} > {new}"},
    "review.item_orphaned": {"en": "«{label}», page {page}: {value}", "uk": "«{label}», с. {page}: {value}"},
    # Answering a re-read's proposals on the document page.
    "reread.title": {"en": "The re-read disagrees with checked values", "uk": "Повторне зчитування не збігається зі звіреними значеннями"},
    "reread.lead": {
        "en": "These values were checked before; the current parser reads the page differently. Compare with the page, then apply what it now reads or keep what you checked.",
        "uk": "Ці значення вже перевіряли; поточний аналізатор читає сторінку інакше. Порівняйте зі сторінкою, тоді застосуйте нове зчитування або залиште перевірене.",
    },
    "reread.changed_heading_one": {"en": "{count} value now reads differently", "uk": "{count} значення тепер зчитано інакше"},
    "reread.changed_heading_few": {"en": "{count} values now read differently", "uk": "{count} значення тепер зчитано інакше"},
    "reread.changed_heading_many": {"en": "{count} values now read differently", "uk": "{count} значень тепер зчитано інакше"},
    "reread.orphaned_heading_one": {"en": "{count} checked value is no longer found", "uk": "{count} звірене значення більше не знайдено"},
    "reread.orphaned_heading_few": {"en": "{count} checked values are no longer found", "uk": "{count} звірені значення більше не знайдено"},
    "reread.orphaned_heading_many": {"en": "{count} checked values are no longer found", "uk": "{count} звірених значень більше не знайдено"},
    "reread.page": {"en": "page {page}", "uk": "стор. {page}"},
    "reread.checked_value": {"en": "checked:", "uk": "звірено:"},
    "reread.page_reads": {"en": "the page now reads", "uk": "на сторінці тепер"},
    "reread.apply": {"en": "Apply the value the page now reads", "uk": "Застосувати значення зі сторінки"},
    "reread.apply_all_one": {"en": "Apply {count} value", "uk": "Застосувати {count} значення"},
    "reread.apply_all_few": {"en": "Apply all {count}", "uk": "Застосувати всі {count}"},
    "reread.apply_all_many": {"en": "Apply all {count}", "uk": "Застосувати всі {count}"},
    "reread.set_aside": {"en": "Set aside", "uk": "Відхилити"},
    "reread.keep": {"en": "Keep", "uk": "Залишити"},
    "reread.queue_n_one": {"en": "{count} re-read proposal to answer", "uk": "{count} пропозиція з повторного зчитування чекає на рішення"},
    "reread.queue_n_few": {"en": "{count} re-read proposals to answer", "uk": "{count} пропозиції з повторного зчитування чекають на рішення"},
    "reread.queue_n_many": {"en": "{count} re-read proposals to answer", "uk": "{count} пропозицій з повторного зчитування чекають на рішення"},
    # Lines the parser recognised as a result and could not read (ParseIssue).
    "review.parse_unread_n_one": {
        "en": "{count} printed result was recognised but could not be read, so it is not in the record yet; enter it from the page: {items}.",
        "uk": "{count} надрукований результат програма розпізнала, але не змогла зчитати, тож у картці його ще немає. Внесіть його зі сторінки: {items}.",
    },
    "review.parse_unread_n_few": {
        "en": "{count} printed results were recognised but could not be read, so they are not in the record yet; enter them from the page: {items}.",
        "uk": "{count} надруковані результати програма розпізнала, але не змогла зчитати, тож у картці їх ще немає. Внесіть їх зі сторінки: {items}.",
    },
    "review.parse_unread_n_many": {
        "en": "{count} printed results were recognised but could not be read, so they are not in the record yet; enter them from the page: {items}.",
        "uk": "{count} надрукованих результатів програма розпізнала, але не змогла зчитати, тож у картці їх ще немає. Внесіть їх зі сторінки: {items}.",
    },
    "review.parse_antibiotic_n_one": {
        "en": "{count} antibiotic name on the susceptibility table is not one the parser knows (often a misread scan), so its result was not stored; check it on the page: {items}.",
        "uk": "{count} назва антибіотика в таблиці чутливості незнайома програмі (часто це помилка розпізнавання скану), тож результат не збережено. Перевірте її на сторінці: {items}.",
    },
    "review.parse_antibiotic_n_few": {
        "en": "{count} antibiotic names on the susceptibility table are not ones the parser knows (often a misread scan), so their results were not stored; check them on the page: {items}.",
        "uk": "{count} назви антибіотиків у таблиці чутливості незнайомі програмі (часто це помилка розпізнавання скану), тож результати не збережено. Перевірте їх на сторінці: {items}.",
    },
    "review.parse_antibiotic_n_many": {
        "en": "{count} antibiotic names on the susceptibility table are not ones the parser knows (often a misread scan), so their results were not stored; check them on the page: {items}.",
        "uk": "{count} назв антибіотиків у таблиці чутливості незнайомі програмі (часто це помилка розпізнавання скану), тож результати не збережено. Перевірте їх на сторінці: {items}.",
    },
    "review.item_issue": {"en": "«{label}», page {page}: «{evidence}»", "uk": "«{label}», с. {page}: «{evidence}»"},
    "review.item_reference": {
        "en": "«{label}», page {page}: «{old}» > «{new}»",
        "uk": "«{label}», с. {page}: «{old}» > «{new}»",
    },

    # Devices
    "devices.title": {"en": "Devices · Anamna", "uk": "Пристрої · Anamna"},
    "devices.heading": {"en": "Device data", "uk": "Дані з пристроїв"},
    # One plain sentence: what is on this page and what to do with it. The
    # storage story (aggregates, immutable exports) lives under Provenance.
    "devices.lead_plain": {
        "en": "Daily summaries from your watch, ring and other connected devices. Open a card for its trend, its reference range and where each number came from.",
        "uk": "Щоденні підсумки з вашого годинника, кільця та інших підключених пристроїв. Відкрийте картку, щоб побачити динаміку, референтний інтервал і джерело кожного числа.",
    },
    "devices.latest_day": {"en": "latest tracked day", "uk": "останній день із даними"},
    # The header's stat row: a label over a plain date, then two counted nouns
    # that link to their lists further down the page.
    "devices.stats_aria": {"en": "Device data at a glance", "uk": "Коротко про дані з пристроїв"},
    "devices.stat_latest": {"en": "Last tracked day", "uk": "Останній день із даними"},
    "devices.stat_workouts_one": {"en": "{value} workout", "uk": "{value} тренування"},
    "devices.stat_workouts_few": {"en": "{value} workouts", "uk": "{value} тренування"},
    "devices.stat_workouts_many": {"en": "{value} workouts", "uk": "{value} тренувань"},
    "devices.stat_events_one": {"en": "{value} ECG or heart alert", "uk": "{value} ЕКГ або серцеве сповіщення"},
    "devices.stat_events_few": {"en": "{value} ECGs and heart alerts", "uk": "{value} ЕКГ і серцеві сповіщення"},
    "devices.stat_events_many": {"en": "{value} ECGs and heart alerts", "uk": "{value} ЕКГ і серцевих сповіщень"},
    "devices.adapters": {"en": "Import adapters", "uk": "Адаптери імпорту"},
    "devices.three_vendors": {"en": "Four supported vendors", "uk": "Чотири підтримувані надавачі"},
    "devices.adapters_note": {
        "en": "Direct and bridged sources stay distinguishable",
        "uk": "Прямі та опосередковані джерела залишаються розрізнюваними",
    },
    "devices.rows_held_one": {"en": "{value} daily value in use", "uk": "У картці {value} денне значення"},
    "devices.rows_held_few": {"en": "{value} daily values in use", "uk": "У картці {value} денні значення"},
    "devices.rows_held_many": {"en": "{value} daily values in use", "uk": "У картці {value} денних значень"},
    "devices.last_sync": {"en": "Last synced {date}", "uk": "Остання синхронізація: {date}"},
    "devices.superseded": {
        "en": "Superseded by a newer export of the same data. None of its rows are in use.",
        "uk": "Замінено новішим експортом тих самих даних. Жоден рядок із нього не використовується.",
    },
    "devices.account_envelope": {"en": "Connected account", "uk": "Підключений обліковий запис"},
    "devices.importer_ready": {
        "en": "Importer accepts the next vendor export without a schema redesign.",
        "uk": "Наступний експорт від цього виробника імпортується без зміни схеми даних.",
    },
    "devices.through": {"en": "Through {date}", "uk": "Дані до {date}"},
    "devices.latest_health": {"en": "Latest device health", "uk": "Останні дані з пристроїв"},
    "devices.find_all": {"en": "Find all device metrics > ", "uk": "Усі показники з пристроїв > "},
    "devices.multi_source": {"en": "Concurrent devices", "uk": "Кілька пристроїв одночасно"},
    "devices.overlap_heading": {
        "en": "{metrics} with more than one source, on {days}",
        "uk": "{metrics} з кількома джерелами за {days}",
    },
    "devices.overlap_metrics_one": {"en": "{value} metric", "uk": "{value} показник"},
    "devices.overlap_metrics_few": {"en": "{value} metrics", "uk": "{value} показники"},
    "devices.overlap_metrics_many": {"en": "{value} metrics", "uk": "{value} показників"},
    "devices.overlap_note": {
        "en": "Values are compared, never summed or silently discarded.",
        "uk": "Значення порівнюємо, але ніколи не підсумовуємо і не відкидаємо мовчки.",
    },
    "devices.overlap_metric": {"en": "{days} · up to {sources}", "uk": "{days} · до {sources}"},
    "devices.sources_upto_one": {"en": "{value} source", "uk": "{value} джерела"},
    "devices.sources_upto_few": {"en": "{value} sources", "uk": "{value} джерел"},
    "devices.sources_upto_many": {"en": "{value} sources", "uk": "{value} джерел"},
    "devices.workout_sources_one": {"en": "Recorded by {value} source; other copy", "uk": "Є в {value} джерелі; інші копії"},
    "devices.workout_sources_few": {"en": "Recorded by {value} sources; other copy", "uk": "Є в {value} джерелах; інші копії"},
    "devices.workout_sources_many": {"en": "Recorded by {value} sources; other copy", "uk": "Є в {value} джерелах; інші копії"},
    "devices.recent_activity": {"en": "Recent activity", "uk": "Остання активність"},
    "devices.workouts_heading": {"en": "Workouts", "uk": "Тренування"},
    "devices.min": {"en": "min", "uk": "хв"},
    "devices.no_workouts": {
        "en": "No workout sessions in the imported exports.",
        "uk": "В імпортованих даних немає тренувань.",
    },
    "devices.heart_events": {"en": "Heart recordings & alerts", "uk": "Записи ЕКГ і серцеві сповіщення"},
    "devices.events_heading": {"en": "Device events", "uk": "Події пристроїв"},
    "devices.no_events": {
        "en": "No ECG or notification events in the imported exports.",
        "uk": "В імпортованих даних немає ЕКГ чи сповіщень.",
    },
    "devices.provenance": {"en": "Provenance", "uk": "Походження даних"},
    "devices.reproducible": {"en": "Every aggregate can be reproduced.", "uk": "Кожен підсумок можна відтворити."},
    "devices.provenance_body": {
        "en": "Imports retain the adapter, immutable source path, SHA-256 fingerprint, export period, raw record count and original device source.",
        "uk": "Для кожного імпорту ми зберігаємо адаптер, незмінний шлях до файлу, відбиток SHA-256, період експорту, кількість необроблених записів і первинне джерело на пристрої.",
    },
    "devices.records_range": {"en": "{rows} · {start} - {end}", "uk": "{rows} · {start} - {end}"},
    "devices.status_direct": {"en": "Direct import", "uk": "Прямий імпорт"},
    "devices.status_api": {"en": "Connected account", "uk": "Підключений обліковий запис"},
    "devices.status_api_paused": {
        "en": "Account disconnected: data retained",
        "uk": "Обліковий запис відключено, дані збережено",
    },
    "devices.status_bridged": {"en": "Arriving through OpenWearables", "uk": "Надходить через OpenWearables"},
    "devices.status_ready": {"en": "Ready for export", "uk": "Очікує на експорт"},
    # Oura sync disclosure: datasets whose last sync failed, and requested
    # scopes the person declined when connecting. The error text is the Oura
    # server's own, shown as received.
    "devices.sync_failures": {
        "en": "Some Oura data is not arriving",
        "uk": "Частина даних Oura не надходить",
    },
    "devices.sync_failures_hint": {
        "en": "These datasets failed on the last sync, with the error message the Oura server returned shown as received. They are retried on the next sync; if an error persists, disconnect and reconnect Oura from your profile.",
        "uk": "Ці набори даних не надійшли під час останньої синхронізації. Помилку показано так, як її повернув сервер Oura. Наступна синхронізація спробує ще раз; якщо помилка не зникає, відключіть Oura і підключіть знову в профілі.",
    },
    "devices.missing_scopes": {
        "en": "Oura is connected without access to: {scopes}",
        "uk": "Oura підключено без доступу до: {scopes}",
    },
    "devices.missing_scopes_hint": {
        "en": "These permissions were not granted when the account was connected, so the data they cover never syncs. Reconnect and allow them to start receiving it.",
        "uk": "Під час підключення облікового запису ці дозволи не надали, тому відповідні дані не синхронізуються взагалі. Підключіть Oura ще раз і дозвольте доступ, щоб дані почали надходити.",
    },
    "devices.reconnect": {
        "en": "Reconnect Oura and grant access",
        "uk": "Підключити Oura ще раз і надати доступ",
    },
    # Heading form for a failed dataset; devices.workouts is a lowercase count
    # label («тренувань») and cannot serve as one.
    "devices.datatype_workouts": {"en": "Workouts", "uk": "Тренування"},
    "device.back": {"en": "Device health", "uk": "Дані з пристроїв"},
    "device.tracked_days_one": {"en": "{value} tracked day", "uk": "{value} день із даними"},
    "device.tracked_days_few": {"en": "{value} tracked days", "uk": "{value} дні з даними"},
    "device.tracked_days_many": {"en": "{value} tracked days", "uk": "{value} днів із даними"},
    "device.days_count_one": {"en": "{value} day", "uk": "{value} день"},
    "device.days_count_few": {"en": "{value} days", "uk": "{value} дні"},
    "device.days_count_many": {"en": "{value} days", "uk": "{value} днів"},
    "device.rows_count_one": {"en": "{value} source row", "uk": "{value} запис із джерел"},
    "device.rows_count_few": {"en": "{value} source rows", "uk": "{value} записи з джерел"},
    "device.rows_count_many": {"en": "{value} source rows", "uk": "{value} записів із джерел"},
    # A running daily total for the day still in progress (UX-11, OPS-07).
    "device.partial_title": {"en": "Today so far", "uk": "Сьогодні поки що"},
    "device.partial_note": {
        "en": "{value} so far today. The day is not finished, so this running total is not shown as the latest reading and is left out of the trend and the chart until the day ends.",
        "uk": "Сьогодні поки що {value}. День ще не закінчився, тому цей проміжний підсумок не показуємо як останнє значення і не враховуємо в динаміці та на графіку до кінця дня.",
    },
    "device.partial_row": {"en": "day in progress", "uk": "день триває"},
    # A device metric whose readings stopped arriving (OPS-24).
    "device.stale_one": {"en": "No new readings for {value} day", "uk": "Нових вимірювань немає вже {value} день"},
    "device.stale_few": {"en": "No new readings for {value} days", "uk": "Нових вимірювань немає вже {value} дні"},
    "device.stale_many": {"en": "No new readings for {value} days", "uk": "Нових вимірювань немає вже {value} днів"},
    "device.stale_body": {
        "en": "The last reading arrived on {date}. The device may be unworn, unpaired or no longer syncing; the value shown is the last one recorded, not today's.",
        "uk": "Останнє вимірювання надійшло {date}. Можливо, пристрій не носять, його відключили або він більше не синхронізується. Показано останнє записане значення, а не сьогоднішнє.",
    },
    "device.loading_source": {"en": "Loading this source...", "uk": "Завантаження джерела..."},
    "device.load_failed": {
        "en": "This source could not be loaded. Check the connection and choose it again.",
        "uk": "Не вдалося завантажити це джерело. Перевірте з’єднання й оберіть його ще раз.",
    },
    "device.agg_lead": {
        "en": "Daily device aggregation with the originating source preserved.",
        "uk": "Щоденна агрегація пристрою зі збереженим джерелом походження.",
    },
    "device.multi_source_lead": {
        "en": "Retained: {sources}. With side-by-side readings: {overlaps}.",
        "uk": "Збережено: {sources}. З паралельними вимірюваннями: {overlaps}.",
    },
    "device.selected_series": {"en": "selected daily series", "uk": "вибраний щоденний ряд"},
    "device.source_coverage": {"en": "Provider coverage", "uk": "Охоплення за джерелами"},
    "device.source_count_one": {"en": "{value} measurement source", "uk": "{value} джерело вимірювань"},
    "device.source_count_few": {"en": "{value} measurement sources", "uk": "{value} джерела вимірювань"},
    "device.source_count_many": {"en": "{value} measurement sources", "uk": "{value} джерел вимірювань"},
    "device.overlap_days_one": {"en": "{value} day with readings from more than one source", "uk": "{value} день із даними кількох джерел"},
    "device.overlap_days_few": {"en": "{value} days with readings from more than one source", "uk": "{value} дні з даними кількох джерел"},
    "device.overlap_days_many": {"en": "{value} days with readings from more than one source", "uk": "{value} днів із даними кількох джерел"},
    "device.selection_explainer": {
        "en": "Trends use one deterministic value per date so a date is never double-weighted. Direct device exports take precedence over bridge copies; every alternative remains visible below and can be charted separately.",
        "uk": "Для трендів використовується одне детерміновано обране значення на дату, щоб жодна дата не мала подвійної ваги. Прямі експорти пристроїв мають перевагу над копіями через посередника; усі альтернативи залишаються видимими нижче й доступні на окремому графіку.",
    },
    "device.source_direct": {"en": "Direct source", "uk": "Пряме джерело"},
    "device.source_bridge": {"en": "Bridge copy", "uk": "Копія через посередника"},
    "device.coverage": {"en": "Coverage", "uk": "Охоплення"},
    "device.days_samples": {"en": "Days · samples", "uk": "Дні · вимірювання"},
    "device.samples_count_one": {"en": "{value} sample", "uk": "{value} вимірювання"},
    "device.samples_count_few": {"en": "{value} samples", "uk": "{value} вимірювання"},
    "device.samples_count_many": {"en": "{value} samples", "uk": "{value} вимірювань"},
    "device.selected_days": {"en": "Used in combined series", "uk": "Використано в об’єднаному ряді"},
    "device.chart_source_aria": {"en": "Chart measurement source", "uk": "Джерело вимірювань на графіку"},
    "device.combined_series": {"en": "Selected daily series", "uk": "Вибраний щоденний ряд"},
    "device.stored_rows": {"en": "{rows} across {days}", "uk": "{rows} за {days}"},
    "device.used_in_series": {"en": "used", "uk": "використано"},
    "device.guidance_provider_score": {
        "en": "A provider-computed composite score delivered by OpenWearables. Its formula, scale and direction belong to the named upstream provider, so scores from different providers remain separate sources and are never averaged together.",
        "uk": "Зведена оцінка, яку обчислює сам сервіс-джерело і передає через OpenWearables. Формула, шкала й напрям оцінки належать цьому сервісу, тому оцінки різних сервісів лишаються окремими джерелами й ніколи не усереднюються.",
    },
    "device.guidance_provider_score_why": {
        "en": "Use it to follow change within the same provider; open the measured components behind it before drawing a health conclusion. It is not a diagnostic result and has no cross-provider reference range.",
        "uk": "Стежте за змінами в межах одного сервісу, а перш ніж робити висновки про здоров’я, перегляньте виміряні складники оцінки. Це не діагностичний результат, і спільного для різних сервісів референтного інтервалу в неї немає.",
    },
    "device.guidance_active_minutes": {
        "en": "Minutes the upstream provider classified as active. This is retained separately from Apple Exercise time because providers use different intensity and eligibility rules.",
        "uk": "Хвилини, які сервіс-джерело зарахував як активні. Ми зберігаємо їх окремо від часу тренувань Apple, бо сервіси мають різні правила щодо інтенсивності й зарахування.",
    },
    "device.guidance_active_minutes_why": {
        "en": "Compare the trend within one source; do not add it to Exercise time or use the two names interchangeably.",
        "uk": "Порівнюйте динаміку в межах одного джерела; не додавайте ці хвилини до часу тренувань і не вважайте ці дві назви синонімами.",
    },
    "device.guidance_sleep_low_hr": {
        "en": "The lowest heart rate Oura captured during the night. It is separate from Apple resting heart rate, which Apple estimates from sedentary samples across the day.",
        "uk": "Найнижчий пульс, який Oura зафіксувала за ніч. Це не те саме, що пульс у спокої від Apple: його Apple оцінює за вимірюваннями в періоди малої активності протягом дня.",
    },
    "device.guidance_sleep_low_hr_why": {
        "en": "Follow it against your own Oura baseline and sleeping context; do not combine it with a daytime resting-heart-rate series.",
        "uk": "Порівнюйте його з вашим звичним рівнем в Oura з урахуванням умов сну; не поєднуйте з денним рядом пульсу в спокої.",
    },
    "device.latest": {"en": "Latest · {date}", "uk": "Останнє · {date}"},
    "device.data_source": {"en": "Data source", "uk": "Джерело даних"},
    "device.measurement": {"en": "Device measurement", "uk": "Вимірювання пристрою"},
    "device.interactive": {"en": "Interactive history", "uk": "Інтерактивна історія"},
    "device.daily_trend": {"en": "Daily trend", "uk": "Щоденна динаміка"},
    "device.range_aria": {"en": "Chart time range", "uk": "Період на графіку"},
    "device.days_30": {"en": "30 days", "uk": "30 днів"},
    "device.year_1": {"en": "1 year", "uk": "1 рік"},
    "device.all": {"en": "All", "uk": "Усе"},
    "device.chart_aria": {
        "en": "Interactive device trend for {name}",
        "uk": "Інтерактивний графік динаміки: {name}",
    },
    "device.source_history": {"en": "Source-aware history", "uk": "Історія за джерелами"},
    "device.daily_aggs": {"en": "Daily aggregates", "uk": "Підсумки за день"},
    "device.th_date": {"en": "Date", "uk": "Дата"},
    "device.th_value": {"en": "Value", "uk": "Значення"},
    "device.th_range": {"en": "Daily range", "uk": "Діапазон за день"},
    "device.th_samples": {"en": "Samples", "uk": "Вимірювання"},
    "device.th_source": {"en": "Source", "uk": "Джерело"},
    "device.samples": {"en": "samples", "uk": "вимірювань"},
    "device.range": {"en": "range", "uk": "діапазон"},
    # Five separate "no data" chips (empty bar, status chip, range dash,
    # authority badge, staleness chip) used to stack in the hero for any
    # metric with no published interval. One clear explanation replaces all
    # five; see device_metric_detail.html.
    "device.no_range_title": {
        "en": "No published reference interval",
        "uk": "Референтного інтервалу не опубліковано",
    },
    "device.no_range_body": {
        "en": "No official body has published a universal target for this measurement. That's common for activity and device metrics, where individual variation is wide. Your own trend over time is more informative than a single fixed number.",
        "uk": "Жодна офіційна установа не публікувала універсального цільового значення для цього показника. Для показників активності й даних із пристроїв це типово, бо індивідуальні відмінності великі. Ваша власна динаміка з часом скаже більше, ніж одне фіксоване число.",
    },

    "area.heart_eyebrow": {"en": "Measured at home", "uk": "Виміряно вдома"},
    "area.heart_bp_panel": {"en": "Blood pressure panel", "uk": "Панель артеріального тиску"},
    "area.heart_ecg_note": {
        "en": "Every recording, with its waveform",
        "uk": "Кожен запис разом із кривою",
    },

    # Electrocardiograms.  The waveform is measured here, so every number the
    # page shows says which lead it came from and how many beats are behind it;
    # the device's own rhythm determination is carried through untouched.
    "ecg.title": {"en": "Electrocardiogram · Anamna", "uk": "Електрокардіограма · Anamna"},
    "ecg.heading": {"en": "Electrocardiogram", "uk": "Електрокардіограма"},
    "ecg.back": {"en": "Heart", "uk": "Серце"},
    "ecg.position": {"en": "Recording {index} of {total}", "uk": "Запис {index} з {total}"},
    "ecg.determination": {"en": "Rhythm determination", "uk": "Класифікація ритму"},
    "ecg.determination_source": {"en": "As reported by {vendor}", "uk": "За даними {vendor}"},
    "ecg.unclassified": {"en": "Unclassified", "uk": "Не класифіковано"},
    "ecg.vendor_rate": {"en": "Reported heart rate", "uk": "ЧСС за даними пристрою"},
    "ecg.vendor_rate_note": {"en": "The rate {vendor} recorded", "uk": "ЧСС, яку записав {vendor}"},
    "ecg.measured_rate": {"en": "Measured heart rate", "uk": "Виміряна ЧСС"},
    "ecg.measured_rate_note": {
        "en": "From the R peaks on lead {lead}",
        "uk": "За зубцями R у відведенні {lead}",
    },
    "ecg.rate_span": {"en": "Beat-to-beat span", "uk": "Розкид від удару до удару"},
    "ecg.rate_span_note": {
        "en": "Slowest and fastest normal interval",
        "uk": "Найповільніший і найшвидший серед нормальних інтервалів",
    },
    "ecg.beats": {"en": "Beats detected", "uk": "Виявлено ударів"},
    "ecg.beats_note": {"en": "Across {seconds} seconds", "uk": "За {seconds} с"},
    "ecg.waveform": {"en": "Waveform", "uk": "Крива ЕКГ"},
    "ecg.rhythm_eyebrow": {"en": "Rhythm", "uk": "Ритм"},
    "ecg.strip_heading": {"en": "Rhythm strip · {scale}", "uk": "Стрічка ритму · {scale}"},
    "ecg.strip_note": {
        "en": "One small square is 0.04 s by 0.1 mV, as on paper",
        "uk": "Мала клітинка відповідає 0,04 с і 0,1 мВ, як на паперовій стрічці",
    },
    "ecg.scroll_hint": {
        "en": "Scroll sideways to see the rest of the strip > ",
        "uk": "Прокрутіть убік, щоб побачити решту стрічки > ",
    },
    "ecg.scale": {"en": "Paper speed and gain", "uk": "Швидкість стрічки й підсилення"},
    "ecg.scale_text": {"en": "{speed}mm/s, {gain}mm/mV", "uk": "{speed} мм/с, {gain} мм/мВ"},
    "ecg.row_label": {"en": "{start}-{end} s", "uk": "{start}-{end} с"},
    "ecg.sample_rate": {"en": "Sampling rate", "uk": "Частота дискретизації"},
    "ecg.hz": {"en": "Hz", "uk": "Гц"},
    "ecg.duration": {"en": "Recording length", "uk": "Тривалість запису"},
    "ecg.seconds": {"en": "s", "uk": "с"},
    "ecg.samples": {"en": "Samples read", "uk": "Зчитано відліків"},
    "ecg.filters": {"en": "Filters", "uk": "Фільтри"},
    "ecg.symptoms": {"en": "Symptoms noted", "uk": "Відмічені симптоми"},
    "ecg.intervals": {"en": "Rhythm intervals", "uk": "Інтервали ритму"},
    "ecg.intervals_heading": {"en": "Beat-to-beat measurements", "uk": "Вимірювання від удару до удару"},
    "ecg.lead_switch": {"en": "Measure on another lead", "uk": "Виміряти в іншому відведенні"},
    "ecg.rr_mean": {"en": "Mean RR interval", "uk": "Середній інтервал RR"},
    "ecg.rr_full": {"en": "Time between two heartbeats (R-to-R interval)", "uk": "Час між двома ударами серця (інтервал R-R)"},
    "ecg.rr_help": {
        "en": "The time from one R peak, the tall spike of a heartbeat, to the next. Its mean gives the heart rate: 800 ms is 75 beats a minute. Very short or very long intervals mark a fast or slow rhythm.",
        "uk": "Час від одного зубця R (високого піку на кривій удару) до наступного. Із середнього інтервалу виходить ЧСС: 800 мс відповідає 75 ударам на хвилину. Дуже короткі або дуже довгі інтервали вказують на прискорений або сповільнений ритм.",
    },
    "ecg.sdnn": {"en": "SDNN", "uk": "SDNN"},
    "ecg.sdnn_full": {"en": "Standard deviation of normal-to-normal intervals", "uk": "Стандартне відхилення інтервалів між нормальними ударами"},
    "ecg.sdnn_help": {
        "en": "How much the time between normal beats varies overall. It reflects heart rate variability: a higher value usually means the nervous system adjusts the heart readily; a persistently low one can accompany stress or reduced fitness. A strip this short cannot be compared with the 24-hour norms.",
        "uk": "Показує, наскільки загалом коливається час між нормальними ударами. Це міра варіабельності серцевого ритму: вище значення зазвичай означає, що нервова система легко підлаштовує роботу серця, а стабільно низьке може супроводжувати стрес або слабшу фізичну форму. Такий короткий запис не можна порівнювати з нормами для 24-годинного моніторування.",
    },
    "ecg.rmssd": {"en": "RMSSD", "uk": "RMSSD"},
    "ecg.rmssd_full": {"en": "Root mean square of successive differences", "uk": "Корінь із середнього квадрата різниць між сусідніми інтервалами"},
    "ecg.rmssd_help": {
        "en": "How much each interval differs from the one before it. It captures fast, beat-to-beat changes driven by the vagus nerve, which slows the heart at rest, so it is the usual short-recording sign of how relaxed and recovered the body is.",
        "uk": "Показує, наскільки кожен інтервал відрізняється від попереднього. Відображає швидкі зміни від удару до удару, які спричиняє блукаючий нерв (саме він сповільнює серце в спокої). Тому для коротких записів це звичний показник того, наскільки організм розслаблений і відновлений.",
    },
    "ecg.hrv_source": {
        "en": "Definitions: Task Force of the European Society of Cardiology and the North American Society of Pacing and Electrophysiology, \"Heart rate variability: standards of measurement, physiological interpretation and clinical use\", Circulation 1996;93:1043-1065.",
        "uk": "Визначення: Робоча група Європейського товариства кардіологів і Північноамериканського товариства стимуляції та електрофізіології, «Heart rate variability: standards of measurement, physiological interpretation and clinical use» (Варіабельність серцевого ритму: стандарти вимірювання, фізіологічна інтерпретація та клінічне застосування), Circulation 1996;93:1043-1065.",
    },
    "ecg.hrv_source_link": {"en": "Read the standard (doi:10.1161/01.CIR.93.5.1043)", "uk": "Прочитати стандарт (doi:10.1161/01.CIR.93.5.1043)"},
    "ecg.intervals_used": {"en": "Intervals measured", "uk": "Виміряно інтервалів"},
    "ecg.excluded": {"en": "Intervals set aside", "uk": "Відхилено інтервалів"},
    "ecg.method_note": {
        "en": "Rate comes from the median interval and variability from the normal-to-normal ones, so a single motion artefact shifts neither.",
        "uk": "Частоту рахуємо за медіанним інтервалом, а варіабельність за нормальними інтервалами, тож поодинокий руховий артефакт не зсуває жодного з показників.",
    },
    "ecg.excluded_note": {
        "en": "Intervals far from the median were excluded from the variability statistics and counted here instead of hidden.",
        "uk": "Інтервали, що сильно відхиляються від медіани, не враховано в статистиці варіабельності. Ми не приховуємо їх, а показуємо тут їхню кількість.",
    },
    "ecg.other": {"en": "Other recordings", "uk": "Інші записи"},
    "ecg.all_recordings": {"en": "Every electrocardiogram", "uk": "Усі електрокардіограми"},
    "ecg.open_report": {"en": "Open the original report", "uk": "Відкрити оригінал"},
    "ecg.none_title": {"en": "No electrocardiograms yet", "uk": "Електрокардіограм поки немає"},
    "ecg.none_body": {
        "en": "Import an Apple Health export or a Kardia report and every recording in it appears here.",
        "uk": "Імпортуйте експорт Apple Health або звіт Kardia, і всі записи з нього з’являться тут.",
    },
    "ecg.source_missing": {
        "en": "The recorded samples are not readable: {file} is no longer where the import found it. The reading below is the one the import saved.",
        "uk": "Не вдається прочитати записані відліки: файлу {file} більше немає там, де його знайшов імпорт. Нижче показано значення, збережене під час імпорту.",
    },
    "ecg.no_waveform": {
        "en": "This export carries the report but no recoverable trace, so only its printed reading is shown.",
        "uk": "У цьому експорті є звіт, але немає кривої, яку можна відновити, тому показано лише надруковане значення.",
    },
    "ecg.disclaimer": {
        "en": "These measurements are geometry: where the R peaks fall and how far apart they are. They are not a diagnosis, and the device's own rhythm determination is shown beside them unchanged.",
        "uk": "Ці вимірювання описують лише геометрію: де розташовані зубці R і яка між ними відстань. Це не діагноз. Висновок пристрою щодо ритму показано поруч без змін.",
    },

    # Source viewer
    "viewer.original": {"en": "Original source", "uk": "Оригінал"},
    "viewer.page_navigation": {"en": "Page navigation", "uk": "Перехід між сторінками"},
    "viewer.previous": {"en": "Previous", "uk": "Назад"},
    "viewer.next": {"en": "Next", "uk": "Далі"},
    "viewer.page": {"en": "Page", "uk": "Сторінка"},
    "viewer.zoom_out": {"en": "Zoom out", "uk": "Зменшити"},
    "viewer.zoom_in": {"en": "Zoom in", "uk": "Збільшити"},
    "viewer.fit": {"en": "Fit page", "uk": "Вмістити сторінку"},
    "viewer.rotate": {"en": "Rotate", "uk": "Повернути"},
    "viewer.new_tab": {"en": "Original file", "uk": "Оригінал"},
    "viewer.source_fallback": {"en": "Source", "uk": "Джерело"},

    # ------------------------------------------------------------------
    # Redesign: panels, insights, verdicts, staleness, authority, upload.
    #
    # Ukrainian counting note: this language has three plural forms, so any
    # string driven by a count is phrased to stay correct for 1, 2 and 5 —
    # either with the invariable abbreviation ("міс.", "дн.") or by moving the
    # number behind a colon ("Досліджено: {n}"). Placeholder sets are identical
    # across locales; see scripts/../tests for the parity check.
    # ------------------------------------------------------------------

    # Panel detail
    "panel.title": {"en": "{name} · Anamna", "uk": "{name} · Anamna"},
    "panel.eyebrow": {"en": "Panel", "uk": "Панель аналізів"},
    "panel.back": {"en": "All panels", "uk": "Усі панелі"},
    "panel.coverage": {
        "en": "{present} of {total} analytes in your record",
        "uk": "{present} з {total} показників у вашій картці",
    },
    "panel.coverage_none": {
        "en": "No analyte from this panel is in your record yet.",
        "uk": "Жодного показника з цієї панелі ще немає у вашій картці.",
    },
    # "Label: N" needs no plural agreement in either language - the number is
    # not the object of a noun - so these two stay single-form on purpose.
    # They count different things and must never be added together: a result
    # can be above the interval AND disputed by its laboratory.
    "panel.flagged": {"en": "Outside the interval: {count}", "uk": "Поза нормою: {count}"},
    "panel.conflicts": {"en": "Sources disagree: {count}", "uk": "Джерела не збігаються: {count}"},
    "panel.last_tested": {"en": "Last tested {date}", "uk": "Останній аналіз: {date}"},
    "panel.retest_cadence": {
        "en": "Recommended every {months} months",
        "uk": "Рекомендовано повторювати раз на {months} міс.",
    },
    "panel.retest_rationale": {"en": "Why this interval", "uk": "Чому саме такий проміжок"},
    "panel.members_heading": {"en": "Results in this panel", "uk": "Результати цієї панелі"},
    "panel.members_lead": {
        "en": "Each row shows where the value sits inside the interval that judged it.",
        "uk": "У кожному рядку видно, де значення лежить у межах інтервалу, за яким його оцінено.",
    },
    "panel.th_name": {"en": "Analyte", "uk": "Показник"},
    "panel.th_value": {"en": "Result", "uk": "Результат"},
    "panel.th_position": {"en": "Position in interval", "uk": "Положення в інтервалі"},
    "panel.th_range": {"en": "Reference interval", "uk": "Референсний інтервал"},
    "panel.th_authority": {"en": "Judged by", "uk": "Джерело норми"},
    "panel.th_delta": {"en": "Change", "uk": "Зміна"},
    "panel.th_date": {"en": "Date", "uk": "Дата"},
    "panel.th_verification": {"en": "Trust", "uk": "Довіра"},
    "panel.missing_heading": {"en": "Not in your record", "uk": "Немає у вашій картці"},
    "panel.missing_lead": {
        "en": "These analytes belong to the panel but have never been recorded. Worth asking your clinician whether they are needed.",
        "uk": "Ці показники входять до панелі, але їх жодного разу не вносили до картки. Варто запитати лікаря, чи потрібно їх здати.",
    },
    "panel.missing_count": {"en": "Missing analytes: {count}", "uk": "Бракує показників: {count}"},
    "panel.trend_heading": {"en": "Trend across the panel", "uk": "Динаміка панелі"},
    "panel.trend_lead": {
        "en": "One sparkline per analyte on a shared time axis, with the reference interval shaded.",
        "uk": "Міні-графік для кожного показника на спільній осі часу, референтний інтервал затінено.",
    },
    "panel.trend_empty": {
        "en": "Not enough dated results to draw a trend yet.",
        "uk": "Ще замало результатів із датами, щоб побудувати динаміку.",
    },
    "panel.sources_heading": {"en": "Source documents", "uk": "Документи-джерела"},
    "panel.sources_lead": {
        "en": "Every value on this page traces back to a page in one of these files.",
        "uk": "Кожне значення на цій сторінці можна знайти на конкретній сторінці одного з цих файлів.",
    },
    "panel.sources_empty": {
        "en": "No source document is linked to this panel yet.",
        "uk": "До цієї панелі ще не прив’язано жодного документа.",
    },
    "panel.guidance_heading": {"en": "Where these intervals come from", "uk": "Звідки взято ці інтервали"},
    "panel.guidance_lead": {
        "en": "Published guidance cited on this page, with publisher and link.",
        "uk": "Настанови, на які спирається ця сторінка: хто їх видав і де прочитати.",
    },
    "panel.guidance_empty": {
        "en": "No published guidance is cited for this panel. Only the laboratory's own printed intervals were used.",
        "uk": "Для цієї панелі немає опублікованих настанов. Використано лише норми, надруковані лабораторією.",
    },
    "panel.guidance_reviewed": {"en": "reviewed {date}", "uk": "переглянуто {date}"},
    "panel.what_it_measures": {"en": "What this panel measures", "uk": "Що вимірює ця панель"},
    "panel.why_it_matters": {"en": "Why it matters", "uk": "Чому це важливо"},
    "panel.empty_title": {"en": "No results in this panel yet", "uk": "У цій панелі ще немає результатів"},
    "panel.empty_body": {
        "en": "Nothing from this panel has been imported. Uploading a report that contains these analytes will fill it in.",
        "uk": "Нічого з цієї панелі ще не імпортовано. Завантажте результати з цими показниками, і панель заповниться.",
    },
    "panel.delta_since": {"en": "vs {date}", "uk": "порівняно з {date}"},
    "panel.delta_first": {"en": "First recorded result", "uk": "Перший результат у картці"},
    "panel.trend_up": {"en": "Higher than the previous result", "uk": "Вище за попередній результат"},
    "panel.trend_down": {"en": "Lower than the previous result", "uk": "Нижче за попередній результат"},
    "panel.trend_flat": {
        "en": "Unchanged since the previous result",
        "uk": "Без змін порівняно з попереднім результатом",
    },
    "panel.open_analyte": {"en": "Open full history > ", "uk": "Відкрити повну історію > "},
    "panel.read_together": {"en": "Read together with", "uk": "Дивіться разом із"},
    "panel.no_range": {"en": "No reference interval", "uk": "Немає референсного інтервалу"},
    # Coverage line for panels that carry device members: sleep stages and
    # steps are measurements, not analytes. After «з {total}» Ukrainian takes
    # the genitive plural, correct for every total ≥ 2; a panel always has
    # more than one member, so no plural selection is needed.
    "panel.members_in_record": {
        "en": "{present} of {total} measurements in your record",
        "uk": "{present} з {total} показників у вашій картці",
    },
    # Relationships aside: only panels whose members are computed from one
    # another carry an entry; the template treats a missing key as "no aside".
    "panel.relationships_heading": {
        "en": "How these measurements connect",
        "uk": "Як ці показники пов’язані",
    },
    "panel.relationships.cbc": {
        "en": "MCV, MCH, MCHC and RDW are calculated from the hemoglobin, hematocrit and red-cell count above. They move together, so a shift in one is read alongside the others",
        "uk": "MCV, MCH, MCHC і RDW обчислюються з наведених вище гемоглобіну, гематокриту й кількості еритроцитів. Вони змінюються разом, тому зсув одного оцінюють разом з іншими",
    },
    "panel.relationships.lipids": {
        "en": "Non-HDL cholesterol and VLDL are calculated from the measured fractions; LDL may be measured directly or calculated. Ratios restate the same measurements, not new tests",
        "uk": "Холестерин не-ЛПВЩ і ЛПДНЩ обчислюються з виміряних фракцій; ЛПНЩ можуть виміряти безпосередньо або обчислити. Співвідношення лише по-іншому подають ті самі вимірювання, це не нові аналізи",
    },

    # Panels index
    "panels.title": {"en": "Panels · Anamna", "uk": "Панелі · Anamna"},
    "panels.eyebrow": {"en": "Results by test group", "uk": "Результати за групами аналізів"},
    "panels.heading": {
        "en": "Test groups",
        "uk": "Групи аналізів",
    },
    # --- Keys added during final verification, after the templates and routes
    # --- workstreams landed. t() echoes an unknown key straight into the page,
    # --- so each of these was visibly rendering as raw text.
    "authority.multi_heading": {
        "en": "Backed by more than one authority",
        "uk": "Підтверджено кількома установами",
    },
    "authority.multi_body": {
        "en": "These official bodies agree about this result.",
        "uk": "Ці офіційні установи однаково оцінюють цей результат.",
    },
    "authority.disagree_heading": {
        "en": "Official bodies disagree",
        "uk": "Офіційні настанови розходяться",
    },
    "authority.disagree_body": {
        "en": "Recognised authorities draw the line in different places for this test. "
              "All of their positions are shown so you can discuss it with your doctor.",
        "uk": "Визнані установи по-різному встановлюють межу для цього аналізу. Ми показуємо позиції кожної, щоб ви могли обговорити це з лікарем.",
    },
    "nav.insights": {"en": "Priorities", "uk": "Пріоритети"},
    "nav.panels": {"en": "Test groups", "uk": "Групи аналізів"},
    "nav.allergy": {"en": "Allergy", "uk": "Алергія"},
    "nav.genetics": {"en": "Your DNA", "uk": "Ваша ДНК"},
    "dashboard.all_panels": {"en": "All panels", "uk": "Усі панелі"},
    "dashboard.panel_board_eyebrow": {"en": "Grouped results", "uk": "Згруповані результати"},
    "dashboard.panel_board_heading": {"en": "Test groups", "uk": "Групи аналізів"},
    "dashboard.panel_board_note": {"en": "Open a group to see its results.", "uk": "Відкрийте групу, щоб переглянути результати."},
    "metrics.group_panels": {"en": "Panels", "uk": "Панелі"},
    "metrics.group_analytes": {"en": "Individual results", "uk": "Окремі показники"},
    "metrics.group_devices": {"en": "Device measurements", "uk": "Вимірювання з пристроїв"},
    "metrics.group_vaccinations": {"en": "Vaccinations", "uk": "Щеплення"},
    "metrics.group_findings": {"en": "Report conclusions", "uk": "Висновки обстежень"},
    "metrics.group_documents": {"en": "Documents", "uk": "Документи"},
    "metrics.group_areas": {"en": "Health areas", "uk": "Напрями здоров’я"},
    "panels.group_count_one": {"en": "{count} panel", "uk": "{count} панель"},
    "panels.group_count_few": {"en": "{count} panels", "uk": "{count} панелі"},
    "panels.group_count_many": {"en": "{count} panels", "uk": "{count} панелей"},
    "panels.group_flagged": {"en": "Panels needing attention: {count}", "uk": "Потребують уваги: {count}"},
    "panels.group_overdue": {"en": "Panels overdue: {count}", "uk": "Прострочено повтор: {count}"},
    "panels.open_area": {"en": "Open all {area} results", "uk": "Відкрити всі результати: {area}"},
    "devices.vendor_count_one": {"en": "{value} supported source", "uk": "{value} підтримуване джерело"},
    "devices.vendor_count_few": {"en": "{value} supported sources", "uk": "{value} підтримувані джерела"},
    "devices.vendor_count_many": {"en": "{value} supported sources", "uk": "{value} підтримуваних джерел"},
    "area.study_index": {"en": "Studies over time", "uk": "Обстеження за роками"},

    # Tracker dashboard on the activity, mobility and sleep areas
    "tracker.eyebrow": {"en": "Daily record", "uk": "Щоденні дані"},
    "tracker.heading": {"en": "Days, weeks and months", "uk": "Дні, тижні та місяці"},
    "tracker.note_mean": {
        "en": "Averages count only the days the device recorded.",
        "uk": "Середні значення враховують лише дні, коли пристрій щось записав.",
    },
    "tracker.bar_aria": {
        "en": "{name}: daily values for the 14 days up to {date}",
        "uk": "{name}: щоденні значення за 14 днів до {date}",
    },
    "tracker.day_value": {"en": "{day}: {value}", "uk": "{day}: {value}"},
    "tracker.no_data_day": {"en": "No data recorded", "uk": "Немає даних"},
    "tracker.selected_source": {
        "en": "Selected: {vendor} · {source}",
        "uk": "Обрано: {vendor} · {source}",
    },
    "tracker.other_sources": {
        "en": "{count} other sources across {days} overlapping days",
        "uk": "Інших джерел: {count}; днів із перекриттям: {days}",
    },
    "tracker.sleep_sources": {
        "en": "Compare {count} sleep sources across {days} overlapping nights",
        "uk": "Порівняти джерела сну (джерел: {count}, спільних ночей: {days})",
    },
    "tracker.avg7": {"en": "7-day average", "uk": "Середнє за 7 днів"},
    "tracker.avg30": {"en": "30-day average", "uk": "Середнє за 30 днів"},
    "tracker.vs_prev_month": {"en": "vs previous 30 days", "uk": "Порівняно з попередніми 30 днями"},
    "tracker.vs_prev_value": {"en": "{percent}%", "uk": "{percent} %"},
    # The arrow is decoration; whether the number went up or down has to
    # survive without it, for a screen reader and for anyone who cannot tell
    # the two glyphs apart at 11px.
    "tracker.vs_prev_up": {"en": "up {percent}%", "uk": "на {percent} % більше"},
    "tracker.vs_prev_down": {"en": "down {percent}%", "uk": "на {percent} % менше"},
    "tracker.vs_prev_flat": {"en": "about the same", "uk": "майже без змін"},
    "tracker.no_recent_days": {
        "en": "Nothing recorded in the last 14 days. The most recent reading is from {date}.",
        "uk": "За останні 14 днів записів немає. Останнє вимірювання: {date}.",
    },
    "tracker.no_prev": {"en": "No earlier month to compare", "uk": "Попереднього місяця для порівняння немає"},
    "tracker.sleep_heading": {"en": "Sleep, night by night", "uk": "Сон за кожну ніч"},
    "tracker.sleep_lead": {
        "en": "Each column is one night, split into the stages your device "
              "classified: deep, core (light), REM and time awake. Taller is "
              "more time in bed asleep; a gap is a night nothing was recorded.",
        "uk": "Кожен стовпчик показує одну ніч, поділену на фази, які визначив пристрій: глибокий сон, основний (легкий), REM і неспання. Що вищий стовпчик, то довше ви спали в ліжку; пропуск означає ніч без запису.",
    },
    "tracker.sleep_aria": {
        "en": "Sleep stages per night for the 14 days up to {date}",
        "uk": "Фази сну за кожну ніч упродовж 14 днів до {date}",
    },
    "tracker.sleep_night_aria": {
        "en": "{day}: {hours} h asleep",
        "uk": "{day}: {hours} год сну",
    },
    # A night the device timed but did not break into stages draws as one
    # block. Without a legend row it is a grey column the page never explains.
    "tracker.stage_unstaged": {"en": "Stage not recorded", "uk": "Фази не визначено"},
    "tracker.stage_unstaged_hint": {
        "en": "Your device timed this night's sleep but did not break it into stages. Some trackers, and older ones, only report a total.",
        "uk": "Пристрій виміряв, скільки ви спали цієї ночі, але не поділив сон на фази. Деякі трекери, зокрема старіші, показують лише загальний час.",
    },
    "tracker.asleep": {"en": "Asleep", "uk": "Уві сні"},
    "tracker.in_bed": {"en": "In bed", "uk": "У ліжку"},
    "allergy.positives_heading": {"en": "Positive results", "uk": "Позитивні результати"},
    "bp.week": {"en": "Week", "uk": "Тиждень"},
    "bp.th_readings": {"en": "Readings", "uk": "Вимірювань"},
    "review.check_against_page": {
        "en": "Check each value against the page beside it before confirming.",
        "uk": "Звірте кожне значення зі сторінкою поруч, перш ніж підтверджувати.",
    },
    "about.add_title": {"en": "Adding a document", "uk": "Додавання документа"},
    "about.add_body": {
        "en": "Upload a PDF or photo of a result from the Insights page. It is stored unchanged, "
              "and every value read from it stays provisional until you check it against the source.",
        "uk": "Завантажте PDF або фото результату зі сторінки огляду стану. Файл зберігається без змін, "
              "а кожне зчитане значення лишається попереднім, доки ви не звірите його з джерелом.",
    },
    "about.where_next": {"en": "Where to go next", "uk": "Куди далі"},
    "about.build_title": {"en": "This installation", "uk": "Ця інсталяція"},
    "about.version": {"en": "Version", "uk": "Версія"},
    # Third Slavic plural form; the _one and _many variants already exist.
    "metric.points_few": {"en": "{count} distinct points", "uk": "{count} результати"},
    "metric.timeline_few": {"en": "{count} timeline points", "uk": "{count} точки на шкалі часу"},
    # Conflicting authorities. Deliberately neutral wording: the app reports that
    # two cited sources disagree, it does not adjudicate between them.
    "verdict.shaded_is": {
        "en": "Shaded band = {range}",
        "uk": "Затінена зона: {range}",
    },
    "verdict.target_caption": {
        "en": "target {range}",
        "uk": "ціль: {range}",
    },
    "verdict.target_interval": {"en": "Target interval: {range}", "uk": "Цільовий інтервал: {range}"},
    "verdict.matched_category": {"en": "Current category: {label} · {range}", "uk": "Поточна категорія: {label} · {range}"},
    "verdict.target_above": {"en": "Your result is above the target interval", "uk": "Ваш результат вище цільового інтервалу"},
    "verdict.target_below": {"en": "Your result is below the target interval", "uk": "Ваш результат нижче цільового інтервалу"},
    "verdict.target_within": {"en": "Your result is inside the target interval", "uk": "Ваш результат у межах цільового інтервалу"},
    "verdict.you_are_above": {
        "en": "Your result is above this range",
        "uk": "Ваш результат вище цього інтервалу",
    },
    "verdict.you_are_below": {
        "en": "Your result is below this range",
        "uk": "Ваш результат нижче цього інтервалу",
    },
    "verdict.you_are_within": {
        "en": "Your result is inside this range",
        "uk": "Ваш результат у межах цього інтервалу",
    },
    "verdict.threshold_crossed": {
        "en": "Crossed: {label}",
        "uk": "Перейдено поріг: {label}",
    },
    "verdict.conflict": {"en": "Sources disagree", "uk": "Джерела розходяться"},
    # Summary line of the collapsed block that explains a verdict: the reading
    # sentence, the shaded interval and its publisher, and any disagreement.
    "verdict.details": {"en": "Details & sources", "uk": "Деталі та джерела"},
    "verdict.conflict_body": {
        "en": "The official interval and your laboratory's own printed range do not agree "
              "about this result. Both are shown so you can raise it with your doctor.",
        "uk": "Офіційний референтний інтервал і норма, яку надрукувала ваша лабораторія, по-різному оцінюють цей результат. Ми показуємо обидва, щоб ви могли обговорити це з лікарем.",
    },
    "verdict.conflict_lab": {
        "en": "Your laboratory's range {range}, {label}",
        "uk": "Норма вашої лабораторії {range}: {label}",
    },
    "verdict.conflict_official": {
        "en": "{publisher} {range}: {label}",
        "uk": "{publisher} {range}: {label}",
    },
    # The bar's accessible name opens with the same sentence it prints, so there
    # is no separate "position" string to fall out of step with the verdict.
    "verdict.band_aria": {"en": "Reference interval {range}", "uk": "Референтний інтервал {range}"},
    "verdict.vendor_band_aria": {"en": "Laboratory interval {range}", "uk": "Норма лабораторії {range}"},
    # Panel roll-up states. "Stable" rather than "Normal" because the panel is
    # a summary of several results, not a verdict on any one of them.
    "panels.status_attention": {"en": "Needs attention", "uk": "Потребує уваги"},
    "panels.status_borderline": {"en": "Borderline", "uk": "Пограничні значення"},
    "panels.status_normal": {"en": "Within range", "uk": "У межах норми"},
    "panels.status_unjudged": {"en": "No reference range", "uk": "Без референтного інтервалу"},
    "panels.status_stale": {"en": "Oldest results", "uk": "Найдавніші результати"},
    "panels.status_absent": {"en": "Not tested", "uk": "Ще не здавали"},
    "sex.male": {"en": "Male", "uk": "Чоловіча"},
    "sex.female": {"en": "Female", "uk": "Жіноча"},
    "sex.intersex": {"en": "Intersex", "uk": "Інтерсекс"},
    "sex.unknown": {"en": "Not recorded", "uk": "Не вказано"},
    "panels.totals_line": {"en": "{with_data} of {total} panels have results.", "uk": "Результати є в {with_data} із {total} панелей."},
    "panels.totals_flagged": {"en": "Panels needing attention", "uk": "Панелі, що потребують уваги"},
    "panels.totals_overdue": {"en": "Panels overdue for retest", "uk": "Панелі з простроченим повтором"},
    "panels.group_aria": {"en": "Panels in {area}", "uk": "Панелі: {area}"},
    "panels.sort_aria": {"en": "Order of panels", "uk": "Порядок панелей"},
    "panels.sort_area": {"en": "By health area", "uk": "За сферою здоров’я"},
    "panels.sort_attention": {"en": "Needing attention first", "uk": "Спочатку ті, що потребують уваги"},
    "panels.open": {"en": "Open panel > ", "uk": "Відкрити панель > "},
    "panels.member_count": {"en": "Analytes: {count}", "uk": "Показників: {count}"},
    "panels.no_data_note": {"en": "No results yet", "uk": "Результатів поки немає"},
    "panels.empty_title": {"en": "No panels to show", "uk": "Панелей поки немає"},
    "panels.empty_body": {
        "en": "Import a laboratory report and its panels will appear here.",
        "uk": "Імпортуйте результати аналізів із лабораторії, і панелі з’являться тут.",
    },

    # Insights
    "insights.title": {"en": "Priorities · Anamna", "uk": "Пріоритети · Anamna"},
    "insights.eyebrow": {"en": "Checks based on your record", "uk": "На основі вашої картки"},
    "insights.heading": {
        "en": "Priorities",
        "uk": "Пріоритети",
    },
    "insights.lead": {
        "en": "Open a section to review results outside an interval, retests due, missing groups or unchecked extractions.",
        "uk": "Відкрийте розділ, щоб переглянути результати поза інтервалом, аналізи, які час повторити, групи без даних або незвірені значення.",
    },
    "insights.attention_heading": {"en": "Needs attention", "uk": "Потребує уваги"},
    "insights.attention_lead": {
        "en": "Results outside the interval that judged them, newest first. This is not a diagnosis.",
        "uk": "Результати поза інтервалом, за яким їх оцінено; спочатку найновіші. Це не діагноз.",
    },
    "insights.due_heading": {"en": "Due for retest", "uk": "Час повторити"},
    "insights.due_lead": {
        "en": "Panels that have passed a published retest interval, most overdue first. Only a handful of measurements have such an interval; the rest are under \"Oldest results\".",
        "uk": "Панелі, для яких минув опублікований інтервал повторного аналізу; спочатку найбільш прострочені. Такий інтервал мають лише окремі показники, решту зібрано в розділі «Найдавніші результати».",
    },
    # The `no_interval` subgroup: shown by age, never described as late.
    "insights.oldest_heading": {"en": "Oldest results", "uk": "Найдавніші результати"},
    "insights.oldest_lead": {
        "en": "No professional body publishes a screening interval for these, so nothing here is late. They are simply the results that have gone longest without an update.",
        "uk": "Для цих аналізів жодна фахова організація не публікує інтервалу скринінгу, тож тут нічого не прострочено. Це просто результати, які найдовше не оновлювалися.",
    },
    "insights.no_interval_note": {
        "en": "No published screening interval",
        "uk": "Інтервал скринінгу не опубліковано",
    },
    "insights.gaps_heading": {"en": "Not yet tested", "uk": "Ще не здавали"},
    "insights.gaps_lead": {
        "en": "Test groups with no recorded result.",
        "uk": "Групи аналізів, для яких ще немає жодного результату.",
    },
    "insights.unverified_heading": {"en": "Awaiting your check", "uk": "Чекає на вашу звірку"},
    "insights.unverified_lead": {
        "en": "Machine extraction stays provisional until you compare it with the source page.",
        "uk": "Автоматично зчитані значення залишаються попередніми, доки ви не звірите їх з оригіналом.",
    },
    "insights.overdue_by": {"en": "Overdue by {months} months", "uk": "Прострочено на {months} міс."},
    "insights.overdue_by_days": {"en": "Overdue by {days} days", "uk": "Прострочено на {days} дн."},
    "insights.last_tested": {"en": "Last tested {date}", "uk": "Останній аналіз: {date}"},
    "insights.never_tested": {"en": "Never tested", "uk": "Ще не здавали"},
    "insights.cadence": {
        "en": "Recommended every {months} months",
        "uk": "Рекомендовано раз на {months} міс.",
    },
    "insights.outside_by": {"en": "{amount} outside the interval", "uk": "{amount} за межами інтервалу"},
    "insights.in_panel": {"en": "In {panel}", "uk": "У панелі «{panel}»"},
    "insights.open_panel": {"en": "Open panel > ", "uk": "Відкрити панель > "},
    "insights.attention_empty_title": {"en": "Nothing outside its interval", "uk": "Усі результати в межах інтервалу"},
    "insights.attention_empty_body": {
        "en": "Every judged result in your record currently sits inside the interval that judged it.",
        "uk": "Усі оцінені результати у вашій картці зараз у межах інтервалу, за яким їх оцінено.",
    },
    "insights.due_empty_title": {"en": "Everything is current", "uk": "Усе актуальне"},
    "insights.due_empty_body": {
        "en": "No panel has passed its recommended retest interval.",
        "uk": "Для жодної панелі ще не минув рекомендований інтервал повторного аналізу.",
    },
    "insights.gaps_empty_title": {"en": "Every panel has data", "uk": "У кожній панелі є дані"},
    "insights.gaps_empty_body": {
        "en": "Each panel in the catalogue has at least one recorded result.",
        "uk": "Для кожної панелі каталогу є щонайменше один результат.",
    },
    "insights.oldest_empty_title": {"en": "Nothing waiting without an interval", "uk": "Немає результатів без інтервалу"},
    "insights.oldest_empty_body": {"en": "Panels with results but no published retest interval would be listed here, oldest first.", "uk": "Тут з’являться панелі з результатами, для яких не опубліковано інтервалу повторного аналізу; спочатку найдавніші."},
    "insights.unverified_empty_title": {"en": "No unchecked extractions", "uk": "Усе звірено"},
    "insights.unverified_empty_body": {
        "en": "Every extracted result has been checked against its source page.",
        "uk": "Кожне зчитане значення звірено з оригіналом.",
    },
    "insights.unverified_observations": {
        "en": "Extracted results",
        "uk": "Зчитаних результатів",
    },
    "insights.unverified_tasks": {
        "en": "Open review tasks",
        "uk": "Відкритих завдань на звірку",
    },
    "insights.unverified_documents": {
        "en": "Documents involved",
        "uk": "Задіяних документів",
    },
    "insights.open_review": {"en": "Show documents awaiting review > ", "uk": "Документи, що чекають на звірку > "},
    "insights.upload_cta": {"en": "Upload a new result", "uk": "Завантажити новий результат"},

    # Verdicts — one label per `interpretation` value
    "verdict.low": {"en": "Below range", "uk": "Нижче норми"},
    # A band curated as plain "borderline" (neither side named): uric acid
    # 360-405 µmol/L, two hemoglobin bands, MCV 80-82 fL, Lp(a) 62-75 nmol/L.
    "verdict.borderline": {"en": "Borderline", "uk": "Пограничний"},
    "verdict.borderline_low": {"en": "Borderline low", "uk": "Погранично низький"},
    "verdict.optimal": {"en": "Optimal", "uk": "Оптимальний"},
    "verdict.normal": {"en": "Within range", "uk": "У межах норми"},
    "verdict.borderline_high": {"en": "Borderline high", "uk": "Погранично високий"},
    "verdict.high": {"en": "Above range", "uk": "Вище норми"},
    "verdict.critical_low": {"en": "Critically low", "uk": "Критично низький"},
    "verdict.critical_high": {"en": "Critically high", "uk": "Критично високий"},
    "verdict.positive": {"en": "Positive", "uk": "Позитивний"},
    "verdict.negative": {"en": "Negative", "uk": "Негативний"},
    "verdict.indeterminate": {"en": "Indeterminate", "uk": "Невизначений"},
    "verdict.unjudged": {"en": "No comparison available", "uk": "Немає з чим порівняти"},
    "verdict.no_universal_target": {"en": "Sets no target", "uk": "Не встановлює цільового значення"},
    # The laboratory flagged the value while the official interval contains it:
    # the chip names both claims instead of a bare "Indeterminate".
    "verdict.lab_high_official_within": {
        "en": "Above lab range · within official interval",
        "uk": "Вище норми лабораторії · у межах офіційного інтервалу",
    },
    "verdict.lab_low_official_within": {
        "en": "Below lab range · within official interval",
        "uk": "Нижче норми лабораторії · у межах офіційного інтервалу",
    },
    "verdict.lab_outside_official_within": {
        "en": "Flagged by the lab · within official interval",
        "uk": "Позначено лабораторією · у межах офіційного інтервалу",
    },
    # Which range judged a document row, and what a qualitative result was
    # expected to read.
    "verdict.judged_official": {
        "en": "Judged against the published interval {range} ({source})",
        "uk": "Оцінено за опублікованим інтервалом {range} ({source})",
    },
    "verdict.judged_lab": {
        "en": "Judged against the laboratory's own range {range}",
        "uk": "Оцінено за нормою лабораторії {range}",
    },
    "verdict.lab_expected": {"en": "Lab expected: {text}", "uk": "Норма лабораторії: {text}"},
    # Blood group, rhesus factor, HLA-B27, height: fixed characteristics that
    # have no reference interval, so they must never render a high/low verdict.
    "verdict.not_a_measurement": {"en": "Not a measurement", "uk": "Це не вимірювання"},
    # A judgement withheld for a stated reason (reference.py blocked reasons →
    # BLOCKED_NOTICE_KEYS in web/app.py). Each sentence says why and, where the
    # profile can supply the missing fact, the notice links there.
    "verdict.blocked_sex_unknown": {
        "en": "Reference intervals for this test differ by sex at birth, which your profile does not record, so the sex-specific judgement is withheld.",
        "uk": "Референтні інтервали цього показника залежать від статі при народженні, а її не вказано у вашому профілі, тому оцінку з урахуванням статі не показуємо.",
    },
    "verdict.blocked_age_unknown": {
        "en": "Reference intervals for this test depend on age, but your profile has no date of birth, so the age-specific judgement is withheld.",
        "uk": "Референтні інтервали цього показника залежать від віку, а у вашому профілі немає дати народження, тому оцінку з урахуванням віку не показуємо.",
    },
    "verdict.blocked_clinical_context": {
        "en": "Some published targets for this test apply only in a specific clinical situation, such as a particular treatment or the reason the test was ordered, so they are not applied here. Where a verdict is shown, it comes from the laboratory's own range.",
        "uk": "Деякі опубліковані цільові значення цього показника застосовують лише в певній клінічній ситуації, наприклад під час певного лікування чи залежно від причини призначення аналізу, тому тут їх не застосовано. Якщо оцінку показано, вона ґрунтується на діапазоні самої лабораторії.",
    },
    "verdict.blocked_cv_risk_category": {
        "en": "Goals for this test depend on your cardiovascular risk category, which your record does not hold, so no goal is applied and only population cut-points judge it. Set the category your doctor assigned in your profile.",
        "uk": "Цільові значення цього показника залежать від категорії серцево-судинного ризику, а у вашій картці її немає. Тому цільове значення не застосовано, і результат оцінено лише за популяційними порогами. Вкажіть у профілі категорію, яку визначив лікар.",
    },
    # Which cardiovascular risk category judged a lipid goal, and why
    # (reference.risk_note).
    "cv_risk.low": {"en": "low", "uk": "низький"},
    "cv_risk.moderate": {"en": "moderate", "uk": "помірний"},
    "cv_risk.high": {"en": "high", "uk": "високий"},
    "cv_risk.at_least_high": {"en": "at least high", "uk": "щонайменше високий"},
    "cv_risk.very_high": {"en": "very high", "uk": "дуже високий"},
    "cv_risk.marker_ldl_cholesterol": {"en": "an LDL cholesterol of", "uk": "ХС ЛПНЩ"},
    "cv_risk.marker_total_cholesterol": {"en": "a total cholesterol of", "uk": "загальний холестерин"},
    "cv_risk.note_profile": {
        "en": "Judged against the goal for {category} cardiovascular risk, the category set in your profile.",
        "uk": "Оцінено за цільовим значенням для категорії серцево-судинного ризику «{category}», вказаної у вашому профілі.",
    },
    "cv_risk.note_derived": {
        "en": "Judged against the goal for {category} cardiovascular risk: your record holds {analyte} {value} mmol/L ({date}). ESC/EAS (2019, Table 4, unchanged in 2025) place anyone with LDL cholesterol above 4.9 mmol/L or total cholesterol above 8 mmol/L in at least the high-risk category without a risk score; the 2026 ACC/AHA guideline and Наказ МОЗ 564 treat LDL cholesterol of 4.9 mmol/L (190 mg/dL) or more the same way. If your doctor placed you at very high risk the goal is stricter: set it in your profile.",
        "uk": "Оцінено за цільовим значенням для категорії серцево-судинного ризику «{category}»: у вашій картці є {analyte} {value} ммоль/л ({date}). За ESC/EAS (2019, таблиця 4, без змін у 2025) людина з ХС ЛПНЩ понад 4,9 ммоль/л або загальним холестерином понад 8 ммоль/л належить щонайменше до високого ризику без розрахунку за шкалою. Настанова ACC/AHA 2026 і Наказ МОЗ 564 так само оцінюють ХС ЛПНЩ 4,9 ммоль/л (190 мг/дл) і вище. Якщо лікар відніс вас до дуже високого ризику, цільове значення суворіше: вкажіть це в профілі.",
    },
    "cv_risk.goal_for_low": {"en": "Goal for low cardiovascular risk", "uk": "Ціль для низького серцево-судинного ризику"},
    "cv_risk.goal_for_moderate": {"en": "Goal for moderate cardiovascular risk", "uk": "Ціль для помірного серцево-судинного ризику"},
    "cv_risk.goal_for_high": {"en": "Goal for high cardiovascular risk", "uk": "Ціль для високого серцево-судинного ризику"},
    "cv_risk.goal_for_very_high": {"en": "Goal for very high cardiovascular risk", "uk": "Ціль для дуже високого серцево-судинного ризику"},
    "cv_risk.goal_requires": {"en": "Needs a clinical input your record does not hold", "uk": "Потрібні клінічні дані, яких немає у вашій картці"},
    "verdict.blocked_sex_not_covered": {
        "en": "The published reference intervals for this test do not cover the sex recorded in your profile, so the judgement is withheld.",
        "uk": "Опубліковані референтні інтервали цього показника не охоплюють стать, вказану у вашому профілі, тому оцінку не показуємо.",
    },
    "verdict.blocked_profile_link": {"en": "Add it in your profile", "uk": "Вказати в профілі"},
    # Guidance-rule applicability chips on the metric page. Ukrainian keeps the
    # age forms noun-free on purpose: «від 41 років» would be wrong and the
    # number arrives pre-formatted, so t_plural cannot pick the case here.
    "rule.applies_to_you": {"en": "Applies to you", "uk": "Стосується вас"},
    "rule.age_range": {"en": "Age {low}-{high} years", "uk": "Вік {low}-{high}"},
    "rule.age_from": {"en": "Age {years} and over", "uk": "Вік {years}+"},
    "rule.age_under": {"en": "Under {years} years", "uk": "Вік до {years}"},
    # Provisional markers on metric and panel cards. Extraction stays
    # provisional until a person verifies it (docs/extraction-and-
    # verification.md). The chip is a t() key, not a phrase filter over a
    # literal: Jinja constant-folds filters over literals at compile time and
    # the label froze in whichever locale rendered first. Its text matches
    # status_label('extracted') so metric and panel cards read identically.
    "verify.provisional_chip": {"en": "Needs verification", "uk": "Потребує звірки"},
    "verify.provisional_body": {
        "en": "This value was read from a document automatically and has not yet been confirmed by a person. Open the metric's history to review it against the source document.",
        "uk": "Це значення програма зчитала з документа автоматично, і його ще ніхто не звірив. Відкрийте історію показника, щоб звірити значення з оригіналом.",
    },
    "verify.provisional_panel_body": {
        "en": "Some values shown here were read from documents automatically and have not yet been confirmed by a person.",
        "uk": "Частину значень тут програма зчитала з документів автоматично, і їх ще ніхто не звірив.",
    },
    "state_strip.aria": {
        "en": "Result status: interpretation, retest timing and verification",
        "uk": "Стан результату: оцінка, термін повторного аналізу та звірка",
    },
    "state_strip.verify_clear": {
        # Chip face — keep short so three labelled slots fit a panel card.
        "en": "Verified",
        "uk": "Звірено",
    },
    "state_strip.verify_clear_title": {
        "en": "Verified against the source",
        "uk": "Звірено з оригіналом",
    },
    # Screen-reader wording for the trend chip: the arrow glyph is decoration,
    # so the direction must survive in words. {amount} is the pre-formatted
    # unsigned delta with its unit.
    "trend.sr_up": {"en": "Up by {amount}", "uk": "Зростання на {amount}"},
    "trend.sr_down": {"en": "Down by {amount}", "uk": "Зниження на {amount}"},
    "trend.sr_flat": {"en": "Little change: {amount}", "uk": "Майже без змін: {amount}"},
    "verdict.out_low": {"en": "Below the interval", "uk": "Нижче інтервалу"},
    "verdict.out_high": {"en": "Above the interval", "uk": "Вище інтервалу"},
    "verdict.no_range": {"en": "No reference interval available", "uk": "Немає референтного інтервалу"},
    "verdict.no_range_body": {
        "en": "This value is recorded, but nothing published or printed defines a comparison for it here.",
        "uk": "Значення записано, але ні опубліковані джерела, ні лабораторія не дають для нього інтервалу, з яким можна порівняти.",
    },

    # Staleness
    "stale.fresh": {"en": "Current", "uk": "Актуально"},
    "stale.due_soon": {"en": "Due soon", "uk": "Скоро повторити"},
    "stale.overdue": {"en": "Overdue", "uk": "Прострочено"},
    "stale.never": {"en": "Never tested", "uk": "Ще не здавали"},
    # Only a handful of analytes have a published screening cadence. Everything
    # else gets `no_interval`: elapsed time is reported, lateness is not implied.
    # Chip / strip face — keep short for a 3-slot labelled strip; the disclosure
    # carries the full “nothing published” explanation via stale.no_interval_body.
    "stale.no_interval": {"en": "No screening interval", "uk": "Без планового повтору"},
    # Ukrainian has three plural forms for "місяць" (1 / 2–4 / 5–20). One string
    # cannot serve all three, so the file's per-form key convention is extended
    # to _one / _few / _many; the caller picks the form from the count.
    "stale.no_interval_detail_one": {
        "en": "Last tested {months} month ago · no published screening interval",
        "uk": "Останній аналіз {months} місяць тому · інтервал скринінгу не опубліковано",
    },
    "stale.no_interval_detail_few": {
        "en": "Last tested {months} months ago · no published screening interval",
        "uk": "Останній аналіз {months} місяці тому · інтервал скринінгу не опубліковано",
    },
    "stale.no_interval_detail_many": {
        "en": "Last tested {months} months ago · no published screening interval",
        "uk": "Останній аналіз {months} місяців тому · інтервал скринінгу не опубліковано",
    },
    "stale.no_interval_body": {
        "en": "No professional body publishes a screening interval for this, so there is nothing to be late for. The elapsed time is shown for context only.",
        "uk": "Для цього аналізу жодна фахова організація не публікує інтервалу скринінгу, тож прострочити його неможливо. Час, що минув, показано лише для довідки.",
    },
    "stale.tested_months_ago": {"en": "Tested {months} months ago", "uk": "Аналіз {months} міс. тому"},
    "stale.tested_days_ago": {"en": "Tested {days} days ago", "uk": "Аналіз {days} дн. тому"},
    "stale.tested_on": {"en": "Last tested {date}", "uk": "Останній аналіз: {date}"},
    "stale.overdue_by": {"en": "Overdue by {months} months", "uk": "Прострочено на {months} міс."},
    "stale.due_on": {"en": "Due {date}", "uk": "Термін: {date}"},
    "stale.due_in": {"en": "Due in {months} months", "uk": "Через {months} міс."},
    "stale.interval": {"en": "Recommended every {months} months", "uk": "Рекомендовано раз на {months} міс."},
    "stale.rationale": {"en": "Why this interval", "uk": "Чому саме такий інтервал"},
    # Metric page heading for the retest cadence. "Interval" beside a
    # reference interval read as the reference interval being missing.
    "stale.how_often": {"en": "How often to test", "uk": "Як часто здавати"},
    "stale.no_interval_heading": {
        "en": "No routine retest interval is set",
        "uk": "Планового інтервалу повтору немає",
    },
    "stale.never_body": {
        "en": "Nothing from this panel has ever been recorded in your ledger.",
        "uk": "Результатів із цієї панелі у вашій картці ще немає.",
    },
    # A published cadence that applies only in a stated situation
    # (reference.staleness, retest_condition_json). {months} is the cadence.
    "stale.condition_abnormal_only": {
        "en": "The published {months}-month repeat applies only to an abnormal result, and this one is not abnormal, so nothing is due.",
        "uk": "Опублікований повтор через {months} міс. стосується лише результатів із відхиленням. Цей результат без відхилень, тож повторний аналіз зараз не потрібен.",
    },
    "stale.condition_follow_up_by_treatment": {
        "en": "The routine {months}-month re-screening interval applies to results at goal. This result is not, so the next test is set by treatment: guidelines ask for a check 8 (±4) weeks after starting or changing it.",
        "uk": "Плановий інтервал повторного скринінгу ({months} міс.) стосується результатів, що досягли цільового значення. Цей результат його не досяг, тож час наступного аналізу визначає лікування: настанови радять перевірити показник через 8 (±4) тижнів після початку або зміни лікування.",
    },
    "stale.condition_on_treatment": {
        "en": "The published {months}-month interval is for people on treatment. Your record does not say whether you are, so it is not applied.",
        "uk": "Опублікований інтервал ({months} міс.) призначений для людей, які лікуються. У вашій картці не зазначено, чи ви лікуєтеся, тому його не застосовано.",
    },
    "stale.condition_occupational": {
        "en": "The {months}-month interval is an occupational requirement (for example for food-industry workers), not general screening advice, so it is not applied.",
        "uk": "Інтервал {months} міс. встановлено як професійну вимогу (наприклад, для працівників харчової галузі), а не як загальну пораду щодо скринінгу, тому його не застосовано.",
    },
    "stale.condition_age_range": {
        "en": "The published {months}-month screening interval applies to a different age group than yours, so nothing is due.",
        "uk": "Опублікований інтервал скринінгу ({months} міс.) стосується іншої вікової групи, тож для вас нічого не прострочено.",
    },
    "stale.condition_age_unknown": {
        "en": "The published {months}-month interval depends on age, and your profile has no date of birth, so it is not applied.",
        "uk": "Опублікований інтервал ({months} міс.) залежить від віку, а у вашому профілі немає дати народження, тому його не застосовано.",
    },
    "stale.condition_condition": {
        "en": "The published {months}-month interval applies only in a situation this record does not show, so it is not applied.",
        "uk": "Опублікований інтервал ({months} міс.) стосується лише ситуації, якої у вашій картці не видно, тому його не застосовано.",
    },

    # Authority of the interval that produced the verdict
    "authority.curated": {"en": "Official guidance", "uk": "Офіційна настанова"},
    "authority.vendor": {"en": "Laboratory range", "uk": "Норма лабораторії"},
    "authority.none": {"en": "No reference range available", "uk": "Референтного інтервалу немає"},
    # A cited source that is not an official guideline (a peer-reviewed review,
    # a manufacturer's instructions for use): reference_sets.official = 0.
    "authority.curated_unofficial": {"en": "Published reference (not an official guideline)", "uk": "Опублікований довідник (не офіційна настанова)"},
    "authority.explainer": {
        "en": "Official guidance is a published decision limit meant to apply broadly; a laboratory range is the interval one laboratory printed on one report for its own method and population. They are different claims and are never merged.",
        "uk": "Офіційна настанова встановлює опублікований поріг для рішень, який застосовують широко. Норма лабораторії означає інтервал, який одна лабораторія надрукувала в одному звіті для свого методу та своєї популяції. Це різні твердження, і ми ніколи їх не поєднуємо.",
    },
    "authority.heading": {"en": "Which range judged this", "uk": "За яким інтервалом оцінено"},
    "authority.source": {"en": "Source: {publisher}", "uk": "Джерело: {publisher}"},
    # The title already appears once per citation; repeating a 50+ character
    # publisher name inside the link text produced an unreadable wall (see
    # _components.html's authority_badge comment for the same call). The
    # visible text is a short, constant affordance; the publisher still
    # reaches screen readers through the aria-label below.
    "authority.open_source": {"en": "Open source", "uk": "Відкрити джерело"},
    "authority.reviewed": {"en": "reviewed {date}", "uk": "переглянуто {date}"},

    # Upload
    "upload.heading": {"en": "Files to add", "uk": "Що додати"},
    "upload.label": {"en": "Result file", "uk": "Файл із результатами"},
    "upload.hint": {
        "en": "PDF, PNG, JPG or TIFF, up to {limit}. The file is stored unchanged and never leaves this machine.",
        "uk": "PDF, PNG, JPG або TIFF, до {limit}. Файл зберігається без змін і нікуди не передається з цього комп’ютера.",
    },
    "upload.submit": {"en": "Upload", "uk": "Завантажити"},
    "upload.success": {
        "en": "Uploaded. Check the extraction against the source before trusting it.",
        "uk": "Завантажено. Перш ніж довіряти зчитаним даним, звірте їх з оригіналом.",
    },
    "upload.error_missing": {"en": "Choose a file to upload.", "uk": "Виберіть файл, який хочете завантажити."},
    "upload.error_type": {
        "en": "That file type is not supported. Use PDF, PNG, JPG or TIFF.",
        "uk": "Такий тип файлу не підтримується. Завантажте PDF, PNG, JPG або TIFF.",
    },
    "upload.error_too_large": {"en": "That file is too large.", "uk": "Файл завеликий."},
    "upload.error_name": {"en": "That filename cannot be used.", "uk": "Файл із такою назвою не вдасться зберегти. Перейменуйте його і спробуйте ще раз."},
    "upload.error_duplicate": {
        "en": "This exact file is already in your ledger.",
        "uk": "Цей файл уже є у вашій картці.",
    },
    "upload.error_failed": {
        "en": "The upload could not be processed. The file was not saved.",
        "uk": "Не вдалося обробити файл, тому його не збережено.",
    },
    "upload.error_csrf": {
        "en": "The form expired. Reload the page and try again.",
        "uk": "Сторінка застаріла. Оновіть її і спробуйте ще раз.",
    },
    "upload.error_no_source": {
        "en": "This account has no patient profile yet, so there is nothing to file the results under. Open your profile first.",
        "uk": "У цього облікового запису ще немає профілю пацієнта, тож результати нікуди додати. Спершу відкрийте профіль.",
    },
    "upload.error_busy": {
        "en": "The queue is still working through the previous submission. Wait for it to finish, then try again.",
        "uk": "Ще обробляємо попередні файли. Зачекайте, доки закінчимо, і спробуйте знову.",
    },

    # The dedicated upload page
    "upload.title": {"en": "Upload a document · Anamna", "uk": "Завантажити документ · Anamna"},
    "upload.eyebrow": {"en": "Add to the record", "uk": "Нові дані"},
    "upload.page_heading": {"en": "Upload a document", "uk": "Завантажити документ"},
    "upload.promise": {
        "en": "Add laboratory reports, imaging reports, consultation letters or device exports. Original files are stored unchanged; extracted values remain marked as unchecked until you review them.",
        "uk": "Додавайте результати аналізів, висновки обстежень і консультацій або експорти з пристроїв. Оригінали зберігаються без змін, а зчитані значення мають позначку «не звірено», доки ви їх не звірите.",
    },
    "upload.drop_label": {
        "en": "Choose files, or drag them here",
        "uk": "Виберіть файли або перетягніть їх сюди",
    },
    "upload.drop_hint": {
        "en": "One file, a whole folder's worth at once, or a .zip, including a vendor export.",
        "uk": "Один файл, цілу теку або архів .zip, зокрема експорт від виробника пристрою.",
    },
    "upload.selected_none": {"en": "No files chosen yet", "uk": "Файли ще не вибрано"},
    "upload.selected_one": {"en": "{count} file selected", "uk": "Вибрано {count} файл"},
    "upload.selected_few": {"en": "{count} files selected", "uk": "Вибрано {count} файли"},
    "upload.selected_many": {"en": "{count} files selected", "uk": "Вибрано {count} файлів"},
    "upload.progress": {"en": "Uploading {name}... {percent}%", "uk": "Завантаження {name}... {percent}%"},
    "upload.progress_batch": {"en": "Uploading... {percent}%", "uk": "Завантаження... {percent}%"},
    "upload.saving": {
        "en": "Sent. Saving the files and adding them to the queue...",
        "uk": "Надіслано. Зберігаємо файли та додаємо їх до черги...",
    },
    "upload.bar_label": {"en": "Upload progress", "uk": "Хід завантаження"},
    "upload.formats": {"en": "Accepted formats: {formats}", "uk": "Формати: {formats}"},
    "upload.size_limit": {"en": "Maximum file size: {limit}", "uk": "Найбільший розмір файлу: {limit}"},
    "upload.archive_limit": {
        "en": "A .zip may be up to {limit}, because a full device export is one.",
        "uk": "Архів .zip може важити до {limit}: стільки займає повний експорт із пристрою.",
    },
    "upload.archive_note": {
        "en": "A .zip is unpacked here, however deeply it is nested. If it turns out to be an Apple Health, "
              "Garmin or Oura export, its daily measurements are imported instead of being treated as documents.",
        "uk": "Архів .zip ми розпаковуємо повністю, хоч скільки в ньому вкладених тек. Якщо це експорт Apple Health, Garmin чи Oura, ми імпортуємо щоденні вимірювання, а не додаємо файли як документи.",
    },
    "upload.megabytes": {"en": "{count} MB", "uk": "{count} МБ"},
    "upload.gigabytes": {"en": "{count} GB", "uk": "{count} ГБ"},
    "upload.kilobytes": {"en": "{count} kB", "uk": "{count} кБ"},
    "upload.bytes": {"en": "{count} bytes", "uk": "{count} байт"},
    "upload.next_heading": {"en": "What happens next", "uk": "Що буде далі"},
    "upload.next_summary": {
        "en": "The file is stored, read and then sent to review.",
        "uk": "Ми збережемо файл, зчитаємо його і передамо вам на звірку.",
    },
    "upload.step_store": {
        "en": "The file is stored exactly as you sent it and never leaves this machine.",
        "uk": "Файл зберігається саме таким, яким ви його надіслали, і нікуди не передається з цього комп’ютера.",
    },
    "upload.step_read": {
        "en": "We read the values, units and printed reference intervals off the pages.",
        "uk": "Ми зчитуємо зі сторінок значення, одиниці та надруковані референтні інтервали.",
    },
    "upload.step_check": {
        "en": "You confirm each value against the source before it counts as trusted.",
        "uk": "Ви звіряєте кожне значення з оригіналом, і лише тоді воно вважається достовірним.",
    },
    "upload.review_link": {"en": "View documents awaiting review", "uk": "Документи, що чекають на звірку"},
    "upload.duplicate_notice": {
        "en": "Nothing was added: this file is already in the record.",
        "uk": "Нічого не додано: цей файл уже є у вашій картці.",
    },
    "upload.duplicate_open": {"en": "Open the document already held", "uk": "Відкрити наявний документ"},
    "upload.recent_heading": {"en": "Recent uploads", "uk": "Останні завантаження"},
    "upload.recent_lead": {
        "en": "The latest files and how far their extraction has got.",
        "uk": "Нові файли і стан їх зчитування.",
    },
    "upload.recent_empty_title": {"en": "Nothing uploaded yet", "uk": "Ще нічого не завантажено"},
    "upload.recent_empty_body": {
        "en": "The first document you upload appears here with its extraction status.",
        "uk": "Тут з’явиться перший документ, який ви завантажите, і стан його зчитування.",
    },
    # Said above the drop zone, where the next upload starts.
    "upload.failed_alert_one": {"en": "{count} upload failed.", "uk": "Не вдалося завантажити {count} файл."},
    "upload.failed_alert_few": {"en": "{count} uploads failed.", "uk": "Не вдалося завантажити {count} файли."},
    "upload.failed_alert_many": {"en": "{count} uploads failed.", "uk": "Не вдалося завантажити {count} файлів."},
    "upload.failed_show": {"en": "See which, and why", "uk": "Показати, які і чому"},
    "upload.status_unverified": {
        "en": "{unverified} of {total} values still to check",
        "uk": "Залишилося звірити: {unverified} з {total}",
    },
    "upload.status_checked": {"en": "All {total} values checked", "uk": "Звірено всі значення ({total})"},
    "upload.status_none": {
        "en": "No values were read from this file",
        "uk": "У цьому файлі не знайдено жодного значення",
    },
    "upload.status_duplicate": {
        "en": "Copy of a file already held",
        "uk": "Копія файлу, який уже є",
    },
    "upload.status_stalled": {
        "en": "The status has stopped updating. Reload the page to see the latest.",
        "uk": "Статус перестав оновлюватися. Перезавантажте сторінку, щоб побачити актуальний стан.",
    },

    # The intake queue: what the processing area says while it works.
    #
    # Every one of these is written into `upload_jobs.detail_key` by the
    # worker, which never stores a message of its own - a failure string
    # carries absolute paths and sometimes the patient's own filenames.
    "intake.heading": {"en": "Processing", "uk": "Опрацювання"},
    "intake.eyebrow": {"en": "Intake queue", "uk": "Черга опрацювання"},
    "intake.lead": {
        "en": "Each file is read one at a time so a large export cannot stall the rest. "
              "You can leave this page; the work continues.",
        "uk": "Файли читаються по одному, щоб великий експорт не блокував решту. "
              "Сторінку можна закрити - опрацювання триватиме.",
    },
    "intake.empty_title": {"en": "Nothing is being processed", "uk": "Зараз нічого не обробляється"},
    "intake.empty_body": {
        "en": "Files you upload appear here with their progress, and stay listed with what they produced.",
        "uk": "Тут видно, як обробляються завантажені файли. Після завершення вони лишаються в списку разом із результатом.",
    },
    "intake.summary": {
        "en": "{active} in progress · {done} finished · {failed} failed",
        "uk": "В роботі: {active} · Готово: {done} · З помилкою: {failed}",
    },
    "intake.clear": {"en": "Clear finished", "uk": "Прибрати готові"},
    "intake.open_result": {"en": "Open", "uk": "Відкрити"},
    "intake.live_note": {
        "en": "This list refreshes on its own while work is in progress.",
        "uk": "Поки триває робота, цей список оновлюється самостійно.",
    },

    "intake.kind_document": {"en": "Document", "uk": "Документ"},
    "intake.kind_archive": {"en": "Archive", "uk": "Архів"},
    "intake.kind_device_export": {"en": "Device export", "uk": "Експорт із пристрою"},
    "intake.kind_rescan": {"en": "Re-read", "uk": "Повторне зчитування"},

    "intake.state_queued": {"en": "Waiting", "uk": "Очікує"},
    "intake.state_running": {"en": "Working", "uk": "Обробляється"},
    "intake.state_done": {"en": "Finished", "uk": "Готово"},
    "intake.state_skipped": {"en": "Skipped", "uk": "Пропущено"},
    "intake.state_failed": {"en": "Failed", "uk": "Помилка"},
    # A file inside a device export left out by design: not a failure.
    "intake.state_not_imported": {"en": "Not imported", "uk": "Не імпортовано"},

    "intake.step_waiting": {"en": "Waiting its turn in the queue", "uk": "Чекає в черзі"},
    "intake.step_unpacking": {"en": "Unpacking the archive", "uk": "Розпаковуємо архів"},
    "intake.step_reading": {"en": "Reading the pages and extracting values", "uk": "Читаємо сторінки і зчитуємо значення"},
    "intake.done_imported": {"en": "Read and filed", "uk": "Зчитано і додано в картку"},
    "intake.done_no_values": {
        "en": "Stored, but no structured value could be read from it",
        "uk": "Збережено, але значень для таблиць не знайдено",
    },
    "intake.done_duplicate": {
        "en": "Already in your ledger. The copy on file was kept",
        "uk": "Уже є у вашій картці, залишено наявну копію",
    },
    "intake.done_unchanged": {"en": "Nothing changed since it was last read", "uk": "Нічого не змінилося з останнього зчитування"},
    "intake.done_expanded": {"en": "Unpacked into individual files", "uk": "Розпаковано на окремі файли"},
    "intake.done_device": {"en": "Recognised as a device export", "uk": "Розпізнано як експорт із пристрою"},
    "intake.done_rescanned": {
        "en": "Re-read with the current parser; your checked values were kept",
        "uk": "Перечитано поточною версією програми, звірені вами значення збережено",
    },
    "intake.failed_missing": {"en": "The file was empty or is no longer on disk", "uk": "Файл порожній або його вже немає на диску"},
    "intake.failed_unreadable": {
        "en": "The file could not be opened. It may be damaged, or its name cannot be used",
        "uk": "Не вдалося відкрити файл. Можливо, він пошкоджений або має непридатну назву",
    },
    "intake.failed_unsupported": {
        "en": "That format is not accepted here",
        "uk": "Цей формат не підтримується",
    },
    "intake.failed_empty": {
        "en": "The archive held no document this ledger can read",
        "uk": "В архіві немає документів, які може прочитати Anamna",
    },
    "intake.failed_too_big": {"en": "Larger than the size limit", "uk": "Файл більший за дозволений розмір"},
    "intake.failed_device_archive_member": {
        "en": "Part of a device export, not a medical document. Kept with the export, not imported",
        "uk": "Це частина експорту з пристрою, а не медичний документ. Файл збережено разом з експортом, але не імпортовано",
    },
    "intake.failed_error": {
        "en": "Reading it failed. The file is kept, so you can try again after a re-read.",
        "uk": "Не вдалося зчитати файл. Він збережений, тож ви можете перечитати його пізніше.",
    },
    # A re-read that stopped itself before it could delete anything.
    "intake.failed_reread_empty": {
        "en": "Re-read stopped: this time it found no values in a document that had them, so nothing was replaced. Check that the document's kind is right, then re-read again.",
        "uk": "Перечитування зупинено: цього разу в документі не знайшлося жодного значення, хоча раніше вони були, тож нічого не замінено. Перевірте, чи правильно вказано вид документа, і перечитайте ще раз.",
    },
    "intake.failed_reread_lab_record": {
        "en": "Not re-read: this is the lab's own record of an order it issued no PDF for, so there is no file to read again. The next lab sync refreshes its values.",
        "uk": "Не перечитано: це запис самої лабораторії про замовлення без PDF, тож перечитувати нема чого. Значення оновляться під час наступної синхронізації з лабораторією.",
    },
    "intake.failed_reread_ocr": {
        "en": "Re-read stopped: text recognition returned nothing for pages it read before, so nothing was replaced. Try the re-read again later.",
        "uk": "Перечитування зупинено: розпізнавання тексту нічого не знайшло на сторінках, які раніше читалися, тож нічого не замінено. Спробуйте перечитати пізніше.",
    },

    "intake.count_values_one": {"en": "{count} value", "uk": "{count} значення"},
    "intake.count_values_few": {"en": "{count} values", "uk": "{count} значення"},
    "intake.count_values_many": {"en": "{count} values", "uk": "{count} значень"},
    "intake.count_new_values_one": {"en": "{count} new value", "uk": "{count} нове значення"},
    "intake.count_new_values_few": {"en": "{count} new values", "uk": "{count} нові значення"},
    "intake.count_new_values_many": {"en": "{count} new values", "uk": "{count} нових значень"},
    "intake.count_files_one": {"en": "{count} file", "uk": "{count} файл"},
    "intake.count_files_few": {"en": "{count} files", "uk": "{count} файли"},
    "intake.count_files_many": {"en": "{count} files", "uk": "{count} файлів"},
    "intake.count_days_one": {"en": "{count} daily measurement", "uk": "{count} щоденне вимірювання"},
    "intake.count_days_few": {"en": "{count} daily measurements", "uk": "{count} щоденні вимірювання"},
    "intake.count_days_many": {"en": "{count} daily measurements", "uk": "{count} щоденних вимірювань"},

    # Naming the export skips detection; the wording says what each one is so
    # the choice does not assume the reader knows the vendor's own vocabulary.
    "intake.source_label": {"en": "What are you uploading?", "uk": "Що ви завантажуєте?"},
    "intake.adapter_auto": {"en": "Detect automatically", "uk": "Визначити автоматично"},
    "intake.adapter_auto_hint": {
        "en": "Medical documents, or an archive of them. A vendor export is recognised by its own structure.",
        "uk": "Медичні документи або архів із ними. Експорт від виробника пристрою розпізнаємо за його структурою.",
    },
    "intake.adapter_apple_health": {"en": "Apple Health export", "uk": "Експорт Apple Health"},
    "intake.adapter_garmin": {"en": "Garmin Connect export", "uk": "Експорт Garmin Connect"},
    "intake.adapter_oura": {"en": "Oura export", "uk": "Експорт Oura"},
    "intake.adapter_kardia": {"en": "Kardia ECG recordings", "uk": "Записи ЕКГ Kardia"},

    # Re-reading a document that is already in the record
    "rescan.action": {"en": "Re-read with the current parser", "uk": "Перечитати поточною версією"},
    "rescan.short": {"en": "Re-read", "uk": "Перечитати"},
    "rescan.explainer": {
        "en": "Re-reading runs today's extraction, classification and naming over the file that is already stored. "
              "Use it when the software has improved since the file was imported. Re-uploading the same file only "
              "produces a duplicate. Values you verified, corrected or set aside are kept exactly as they are; only "
              "values nobody has ruled on are replaced, and anything the earlier read missed is added for checking.",
        "uk": "Повторне зчитування запускає сьогоднішнє витягування, класифікацію та найменування для вже збереженого файлу. "
              "Скористайтеся ним, якщо програма вдосконалилася після імпорту файлу - повторне завантаження того самого файлу "
              "лише створить дублікат. Значення, які ви звірили, виправили чи відклали, зберігаються без змін; замінюються "
              "тільки ті, щодо яких ніхто не ухвалював рішення, а все, що попереднє зчитування пропустило, додається для перевірки.",
    },
    "rescan.queued": {
        "en": "Queued for re-reading. The result appears on the upload page and here once it finishes.",
        "uk": "Файл у черзі на перечитування. Результат з’явиться тут і на сторінці завантаження, щойно все буде готово.",
    },

    # Re-reading everything the current parser has moved past.  Without this a
    # person who wanted the benefit of a parser improvement had to open all 85
    # files one at a time, and nothing on any page told them which ones needed it.
    # Correcting what kind of document this is. Everything the parser does
    # follows from the kind, so a report filed under the wrong one produces no
    # values at all and re-reading it reaches the same wrong answer.
    "classify.heading": {"en": "What this document is", "uk": "Що це за документ"},
    "classify.hint": {
        "en": "Choose a known report type to re-read the file with its matching extractor. A new type is saved as a filing label without changing extracted values.",
        "uk": "Оберіть відомий вид звіту, щоб перечитати файл відповідним аналізатором. Новий вид зберігається як мітка без зміни витягнутих значень.",
    },
    "classify.kind": {"en": "Kind of report", "uk": "Вид документа"},
    "classify.kind_unknown": {
        "en": "That is not one of the document kinds this ledger can read. Choose one from the list.",
        "uk": "Anamna не вміє читати такий вид документа. Виберіть вид зі списку.",
    },
    "classify.kind_add": {"en": "Add another type...", "uk": "Додати інший вид..."},
    "classify.kind_custom": {"en": "New report type", "uk": "Новий вид документа"},
    "classify.kind_custom_hint": {"en": "Enter only when adding a type", "uk": "Заповніть, лише якщо додаєте новий вид"},
    "classify.vendor": {"en": "Issued by", "uk": "Хто видав"},
    "classify.vendor_add": {"en": "Add another provider...", "uk": "Додати інший заклад..."},
    "classify.vendor_clear": {"en": "Not specified", "uk": "Не вказано"},
    "classify.vendor_custom": {"en": "New provider", "uk": "Новий заклад"},
    "classify.vendor_custom_hint": {"en": "Enter only when adding a provider", "uk": "Заповніть, лише якщо додаєте новий заклад"},
    "classify.add_custom": {"en": "Add a report type or provider", "uk": "Додати вид документа або заклад"},
    "classify.date": {"en": "Date on the report", "uk": "Дата в документі"},
    "classify.submit": {"en": "Save type and provider", "uk": "Зберегти вид і заклад"},
    "classify.human_badge": {"en": "Classified by you", "uk": "Вид указано вами"},
    "classify.human_hint": {
        "en": "You set what this document is, so re-reading keeps it rather than guessing again.",
        "uk": "Ви визначили, що це за документ, тож повторне зчитування збереже це, а не гадатиме знову.",
    },
    "classify.saved": {
        "en": "Saved. The file has been queued for re-reading with the kind you chose.",
        "uk": "Збережено. Файл поставлено в чергу на повторне зчитування з обраним видом.",
    },
    "rescan.stale_badge": {"en": "Older parser", "uk": "Застаріле зчитування"},
    "rescan.stale_hint": {
        "en": "This file was last read by an earlier version of the extraction software. "
              "Re-reading it applies everything the parser has learned since.",
        "uk": "Цей файл востаннє зчитувала попередня версія програми. Перечитайте його, щоб застосувати все, чого програма навчилася відтоді.",
    },
    "rescan.bulk_heading": {"en": "Files read by an older parser", "uk": "Файли, зчитані старою версією"},
    "rescan.bulk_action": {"en": "Re-read all of them", "uk": "Перечитати всі"},
    "rescan.bulk_hint": {
        "en": "The parser is version {version}. These files were last read by an older one, so anything it has "
              "learned since, a unit it now recognises, a layout it now understands, is not in them yet. "
              "Re-reading keeps every value you verified, corrected or set aside, and adds what the earlier read "
              "missed for checking. A file that produced no values at all is not listed here, because there is "
              "nothing recorded to date it by; re-read those from the file's own page. Nor is one whose every "
              "value you already own, because a re-read would keep all of them and change nothing.",
        "uk": "Версія аналізатора: {version}. Ці файли востаннє зчитано старішою версією, тож усе, чого він навчився "
              "відтоді - одиниця, яку він тепер розпізнає, макет, який тепер розуміє - до них ще не застосовано. "
              "Повторне зчитування зберігає кожне значення, яке ви звірили, виправили чи відклали, і додає пропущене "
              "раніше для перевірки. Файли, які не дали жодного значення, тут не показані, бо немає записів, за якими "
              "визначити версію; такі перечитуйте зі сторінки самого файлу. Не показані й ті, де всі значення вже "
              "належать вам, повторне зчитування збереже їх усі й нічого не змінить.",
    },
    "rescan.bulk_queued_one": {
        "en": "{count} file queued for re-reading. Watch the processing area for progress.",
        "uk": "{count} файл у черзі на перечитування. Стежте за перебігом у розділі «Опрацювання».",
    },
    "rescan.bulk_queued_few": {
        "en": "{count} files queued for re-reading. Watch the processing area for progress.",
        "uk": "{count} файли в черзі на перечитування. Стежте за перебігом у розділі «Опрацювання».",
    },
    "rescan.bulk_queued_many": {
        "en": "{count} files queued for re-reading. Watch the processing area for progress.",
        "uk": "{count} файлів у черзі на перечитування. Стежте за перебігом у розділі «Опрацювання».",
    },
    "rescan.bulk_queued": {
        "en": "Files queued for re-reading: {count}. Watch the processing area for progress.",
        "uk": "Файлів у черзі на перечитування: {count}. Стежте за перебігом у розділі «Опрацювання».",
    },
    # One line on /documents; the long explanation folds behind "Why".
    "rescan.bulk_line_one": {
        "en": "{count} file was read by an older parser.",
        "uk": "{count} файл зчитано старою версією програми.",
    },
    "rescan.bulk_line_few": {
        "en": "{count} files were read by an older parser.",
        "uk": "{count} файли зчитано старою версією програми.",
    },
    "rescan.bulk_line_many": {
        "en": "{count} files were read by an older parser.",
        "uk": "{count} файлів зчитано старою версією програми.",
    },
    "rescan.bulk_why": {"en": "Why re-read them?", "uk": "Навіщо їх перечитувати?"},
    # "Watch the processing area" named a page nothing linked to. Re-reading 62
    # files reported "queued" and then never mentioned itself again: every one
    # of them failed, the queue said so in red, and no route led there from the
    # button that had filled it.
    "rescan.watch": {"en": "Open the processing area", "uk": "Відкрити «Опрацювання»"},
    # Counted per file by its latest re-read: a failure followed by a success is not a failure.
    "rescan.failed_one": {
        "en": "The last re-read of {count} file failed, so it still holds the older reading. The "
              "processing area says why for each one. Most often the stored file is no longer where the record expects it, which no amount of re-reading can fix.",
        "uk": "Не вдалося перечитати {count} файл, тому в ньому лишилися дані попереднього зчитування. Причину видно в розділі «Опрацювання». Найчастіше файлу вже немає там, де його шукає програма, і повторне перечитування цього не виправить.",
    },
    "rescan.failed_few": {
        "en": "The last re-read of {count} files failed, so they still hold the older reading. The "
              "processing area says why for each one. Most often the stored file is no longer where the record expects it, which no amount of re-reading can fix.",
        "uk": "Не вдалося перечитати {count} файли, тому в них лишилися дані попереднього зчитування. Причину для кожного видно в розділі «Опрацювання». Найчастіше файлу вже немає там, де його шукає програма, і повторне перечитування цього не виправить.",
    },
    "rescan.failed_many": {
        "en": "The last re-read of {count} files failed, so they still hold the older reading. The "
              "processing area says why for each one. Most often the stored file is no longer where the record expects it, which no amount of re-reading can fix.",
        "uk": "Не вдалося перечитати {count} файлів, тому в них лишилися дані попереднього зчитування. Причину для кожного видно в розділі «Опрацювання». Найчастіше файлу вже немає там, де його шукає програма, і повторне перечитування цього не виправить.",
    },
    "rescan.failed": {
        "en": "Files whose last re-read failed: {count}. They still hold the older reading; the "
              "processing area says why for each one. Most often the stored file is no longer where the record expects it, which no amount of re-reading can fix.",
        "uk": "Файлів, які не вдалося перечитати: {count}. У них лишилися дані попереднього зчитування, а причину для кожного видно в розділі «Опрацювання». Найчастіше файлу вже немає там, де його шукає програма, і повторне перечитування цього не виправить.",
    },
    "rescan.bulk_none": {
        "en": "Every file that produced values was read by the current parser.",
        "uk": "Усі файли зі значеннями зчитано поточною версією програми.",
    },

    # Urinalysis panel.  Both of these were called by the template and never
    # written, so `t()` returned the key and the table header read
    # "urinalysis.expected" on any record whose urinalysis panel had data.
    "urinalysis.heading": {"en": "Urine analysis", "uk": "Аналіз сечі"},
    "urinalysis.expected": {"en": "Expected", "uk": "Норма"},

    # Allergy panel
    "allergy.heading": {"en": "Allergen-specific IgE", "uk": "Специфічні IgE до алергенів"},
    "allergy.lead": {
        "en": "The whole panel summarised first, then grouped by allergen family. Positives are always expanded.",
        "uk": "Спочатку підсумок усієї панелі, далі алергени за групами. Позитивні результати завжди розгорнуті.",
    },
    "allergy.summary": {"en": "Tested: {tested} · Positive: {positive}", "uk": "Досліджено: {tested} · Позитивних: {positive}"},
    "allergy.group_summary": {"en": "Tested: {tested} · Positive: {positive}", "uk": "Досліджено: {tested} · Позитивних: {positive}"},
    "allergy.group_highest": {"en": "Highest {value}", "uk": "Максимум: {value}"},
    "allergy.all_below": {"en": "All below {cutoff}", "uk": "Усі нижче {cutoff}"},
    "allergy.highest": {"en": "Highest value: {value}", "uk": "Найвище значення: {value}"},
    "allergy.tested_on": {"en": "Tested {date}", "uk": "Дата аналізу: {date}"},
    "allergy.cutoff": {"en": "Detection cut-off {value}", "uk": "Поріг виявлення {value}"},
    "allergy.cap_heading": {"en": "ImmunoCAP classes", "uk": "Класи ImmunoCAP"},
    "allergy.cap_lead": {
        "en": "The class is derived from the measured concentration in kUA/L.",
        "uk": "Клас визначають за виміряною концентрацією в kUA/л.",
    },
    "allergy.cap_0": {"en": "Class 0 · not detected", "uk": "Клас 0 · не виявлено"},
    "allergy.cap_1": {"en": "Class 1 · low", "uk": "Клас 1 · низький рівень"},
    "allergy.cap_2": {"en": "Class 2 · moderate", "uk": "Клас 2 · помірний рівень"},
    "allergy.cap_3": {"en": "Class 3 · high", "uk": "Клас 3 · високий рівень"},
    "allergy.cap_4": {"en": "Class 4 · very high", "uk": "Клас 4 · дуже високий рівень"},
    "allergy.cap_5": {"en": "Class 5 · very high", "uk": "Клас 5 · дуже високий рівень"},
    "allergy.cap_6": {"en": "Class 6 · extremely high", "uk": "Клас 6 · надзвичайно високий рівень"},
    "allergy.group_tree_pollen": {"en": "Tree pollen", "uk": "Пилок дерев"},
    "allergy.group_grass_pollen": {"en": "Grass pollen", "uk": "Пилок злакових трав"},
    "allergy.group_weed_pollen": {"en": "Weed pollen", "uk": "Пилок бур’янів"},
    "allergy.group_mites": {"en": "House-dust mites", "uk": "Кліщі домашнього пилу"},
    "allergy.group_animal_dander": {"en": "Animal dander", "uk": "Епітелій тварин"},
    "allergy.group_moulds": {"en": "Moulds", "uk": "Цвілеві гриби"},
    "allergy.group_foods": {"en": "Foods", "uk": "Харчові алергени"},
    "allergy.group_insect_venom": {"en": "Insect venom", "uk": "Отрута комах"},
    "allergy.group_other": {"en": "Other allergens", "uk": "Інші алергени"},
    "allergy.show_negatives": {"en": "Show all negatives", "uk": "Показати всі негативні результати"},
    "allergy.hide_negatives": {"en": "Hide negatives", "uk": "Сховати негативні"},
    "allergy.total_ige": {"en": "Total IgE", "uk": "Загальний IgE"},
    "allergy.no_positives_title": {
        "en": "No allergen tested positive",
        "uk": "Жодного позитивного результату",
    },
    "allergy.no_positives_body": {
        "en": "Every allergen in this panel measured below the detection cut-off on the tested date.",
        "uk": "На дату аналізу всі алергени цієї панелі були нижче порогу виявлення.",
    },
    "allergy.caveat_title": {
        "en": "Sensitisation is not the same as allergy",
        "uk": "Сенсибілізація ще не означає алергію",
    },
    "allergy.caveat_body": {
        "en": "A raised specific IgE shows sensitisation to an allergen. It becomes an allergy only when it matches real symptoms on exposure, and only a clinician can establish that.",
        "uk": "Підвищений рівень специфічного IgE свідчить про сенсибілізацію до алергену. Алергією вона стає лише тоді, коли контакт з алергеном справді викликає симптоми, а встановити це може тільки лікар.",
    },

    # Blood pressure
    "bp.heading": {"en": "Blood pressure", "uk": "Артеріальний тиск"},
    "bp.lead": {
        "en": "Systolic over diastolic with the pulse recorded at the same moment, not three unrelated numbers.",
        "uk": "Систолічний і діастолічний тиск разом із пульсом, виміряним у ту саму мить: одне вимірювання, а не три окремі числа.",
    },
    "bp.reading": {"en": "{systolic}/{diastolic} mmHg", "uk": "{systolic}/{diastolic} мм рт. ст."},
    "bp.systolic": {"en": "Systolic", "uk": "Систолічний"},
    "bp.diastolic": {"en": "Diastolic", "uk": "Діастолічний"},
    "bp.pulse": {"en": "Pulse", "uk": "Пульс"},
    "bp.pulse_value": {"en": "{pulse} bpm", "uk": "{pulse} уд./хв"},
    # A cuff export on its document page: one row per reading.
    "bp.doc_readings_one": {"en": "{count} reading", "uk": "{count} вимірювання"},
    "bp.doc_readings_few": {"en": "{count} readings", "uk": "{count} вимірювання"},
    "bp.doc_readings_many": {"en": "{count} readings", "uk": "{count} вимірювань"},
    "bp.doc_readings_help": {
        "en": "Each row is one cuff reading. Its category is the stricter of the systolic and diastolic verdicts "
              "under the ESH and AHA bands; the label the device printed is shown beside it as evidence.",
        "uk": "Кожен рядок показує одне вимірювання тонометром. Категорію визначає суворіша з оцінок систолічного й діастолічного тиску за діапазонами ESH та AHA; поруч для підтвердження показано категорію, яку надрукував сам пристрій.",
    },
    "bp.doc_printed_category": {"en": "Device printed: {label}", "uk": "Пристрій надрукував: {label}"},
    "bp.doc_check_values": {"en": "Check or correct values", "uk": "Звірити або виправити значення"},
    "bp.category": {"en": "Category", "uk": "Категорія"},
    "bp.measured_on": {"en": "Measured {date}", "uk": "Виміряно: {date}"},
    "bp.weekly_heading": {"en": "Weekly range", "uk": "Діапазон за тиждень"},
    "bp.weekly_range": {"en": "{low}-{high} mmHg", "uk": "{low}-{high} мм рт. ст."},
    "bp.readings": {"en": "Readings: {count}", "uk": "Вимірювань: {count}"},
    "bp.chart_aria": {
        "en": "Systolic and diastolic blood pressure over time",
        "uk": "Динаміка систолічного й діастолічного артеріального тиску",
    },
    "bp.chart_bands": {
        "en": "Category bands are shaded behind both series.",
        "uk": "Зони категорій затінено на тлі обох кривих.",
    },
    "bp.guideline_esh": {"en": "ESH 2023", "uk": "ESH 2023"},
    "bp.guideline_aha": {"en": "ACC/AHA 2017", "uk": "ACC/AHA 2017"},
    "bp.esh_optimal": {"en": "Optimal", "uk": "Оптимальний"},
    "bp.esh_normal": {"en": "Normal", "uk": "Нормальний"},
    "bp.esh_high_normal": {"en": "High normal", "uk": "Високий нормальний"},
    "bp.esh_grade1": {"en": "Grade 1 hypertension", "uk": "Артеріальна гіпертензія 1 ступеня"},
    "bp.esh_grade2": {"en": "Grade 2 hypertension", "uk": "Артеріальна гіпертензія 2 ступеня"},
    "bp.esh_grade3": {"en": "Grade 3 hypertension", "uk": "Артеріальна гіпертензія 3 ступеня"},
    "bp.esh_isolated_systolic": {
        "en": "Isolated systolic hypertension",
        "uk": "Ізольована систолічна гіпертензія",
    },
    "bp.aha_normal": {"en": "Normal", "uk": "Нормальний"},
    "bp.aha_elevated": {"en": "Elevated", "uk": "Підвищений"},
    "bp.aha_stage1": {"en": "Stage 1 hypertension", "uk": "Артеріальна гіпертензія 1 стадії"},
    "bp.aha_stage2": {"en": "Stage 2 hypertension", "uk": "Артеріальна гіпертензія 2 стадії"},
    "bp.aha_crisis": {"en": "Hypertensive crisis", "uk": "Гіпертензивний криз"},
    # The authorities disclosure under the reading: US and European guidelines
    # draw the category lines at different thresholds, and the page must say so
    # rather than let two names for one reading look like a contradiction.
    "bp.authorities_summary": {
        "en": "How this category is decided",
        "uk": "Як визначають категорію",
    },
    "bp.authorities_note": {
        "en": "US (ACC/AHA 2017) and European (ESH 2023) guidelines draw the category lines at different thresholds, so the same reading can carry a different name under each. The category above names the guideline it follows, and the chart shades both sets of bands.",
        "uk": "Американські (ACC/AHA 2017) і європейські (ESH 2023) настанови проводять межі категорій за різними порогами, тож те саме вимірювання може називатися по-різному. Вище вказано, за якою настановою визначено категорію, а на графіку затінено зони обох настанов.",
    },
    "bp.no_reading": {
        "en": "No blood-pressure reading has been recorded yet.",
        "uk": "Вимірювань артеріального тиску ще немає.",
    },

    # Dashboard status tiles
    "tile.attention": {"en": "Needs attention", "uk": "Потребує уваги"},
    "tile.attention_zero": {"en": "Nothing outside its interval", "uk": "Нічого поза межами норми"},
    "tile.due": {"en": "Due for retest", "uk": "Час перездати"},
    "tile.due_zero": {"en": "Everything is current", "uk": "Усі аналізи актуальні"},
    "tile.panels_covered": {"en": "Panels covered", "uk": "Охоплено панелей"},
    "tile.panels_note": {"en": "{covered} of {total} have results", "uk": "{covered} з {total} мають результати"},
    "tile.unverified": {"en": "Unverified results", "uk": "Не звірено"},
    "tile.unverified_zero": {"en": "All checked against the source", "uk": "Усе звірено з оригіналом"},
    "tile.review_documents_one": {"en": "{count} document awaiting review", "uk": "{count} документ чекає на звірку"},
    "tile.review_documents_few": {"en": "{count} documents awaiting review", "uk": "{count} документи чекають на звірку"},
    "tile.review_documents_many": {"en": "{count} documents awaiting review", "uk": "{count} документів чекають на звірку"},

    # --- AI hand-off: the modal chrome ------------------------------------
    "lang.name_en": {"en": "English", "uk": "англійською"},
    "lang.name_uk": {"en": "Ukrainian", "uk": "українською"},
    "ai.button": {"en": "Copy for AI", "uk": "Копіювати для ШІ"},
    "ai.button_aria": {
        "en": "Prepare a copy of this record for an AI assistant",
        "uk": "Підготувати копію цієї картки для ШІ-помічника",
    },
    "ai.modal_title": {"en": "Prepare a record copy for AI", "uk": "Копія картки для ШІ"},
    "ai.modal_lead": {
        "en": "Choose what to include, then copy the prepared text into an AI assistant.",
        "uk": "Оберіть, що включити, а потім скопіюйте підготовлений текст у ШІ-помічник.",
    },
    "ai.privacy_note": {
        "en": "This leaves your computer only when you paste it somewhere. Your name and date of birth are left out unless you add them below.",
        "uk": "Ці дані залишають ваш комп’ютер лише тоді, коли ви їх кудись вставите. Ім’я та дата народження не додаються, доки ви не увімкнете їх нижче.",
    },
    "ai.options_heading": {"en": "What to include", "uk": "Що додати"},
    "ai.copy": {"en": "Copy prompt", "uk": "Копіювати запит"},
    "ai.copied": {"en": "Copied", "uk": "Скопійовано"},
    "ai.copy_failed": {
        "en": "Copying was blocked. Select the text below and copy it manually.",
        "uk": "Браузер не дав скопіювати текст. Виділіть його нижче й скопіюйте вручну.",
    },
    "ai.close": {"en": "Close", "uk": "Закрити"},
    "ai.loading": {"en": "Assembling your record...", "uk": "Готуємо копію картки..."},
    "ai.error": {
        "en": "The prompt could not be built. Reload the page and try again.",
        "uk": "Не вдалося підготувати запит. Оновіть сторінку й спробуйте ще раз.",
    },
    "ai.size": {
        "en": "{chars} characters · roughly {tokens} tokens",
        "uk": "Символів: {chars} · токенів: приблизно {tokens}",
    },
    "ai.size_hint": {
        "en": "A token is the unit an assistant reads in; most accept 100,000 or more in one message.",
        "uk": "Токен - це одиниця, якою читає помічник; більшість приймає 100 000 і більше в одному повідомленні.",
    },
    "ai.option_history": {"en": "Trends over time", "uk": "Динаміка показників"},
    "ai.option_history_hint": {
        "en": "Every earlier result for each analyte, thinned to eight points.",
        "uk": "Усі попередні результати кожного показника, проріджені до восьми точок.",
    },
    "ai.option_devices": {"en": "Watch & device data", "uk": "Дані з годинника та пристроїв"},
    "ai.option_devices_hint": {
        "en": "Monthly averages from your wearables. Daily rows are summarized, never pasted whole.",
        "uk": "Середні за місяць із ваших пристроїв. Щоденні дані подано підсумком, а не повністю.",
    },
    "ai.option_findings": {"en": "Report conclusions", "uk": "Письмові висновки"},
    "ai.option_findings_hint": {
        "en": "What the written parts of your reports concluded.",
        "uk": "Що зазначено в текстових висновках ваших документів.",
    },
    "ai.option_guidance": {"en": "Why each test matters", "uk": "Навіщо потрібен кожен аналіз"},
    "ai.option_guidance_hint": {
        "en": "The plain-language explanation and retest interval for each result. Long.",
        "uk": "Пояснення простими словами до кожного результату і як часто його повторювати. Довгий розділ.",
    },
    "ai.option_documents": {"en": "Documents & providers", "uk": "Документи та заклади"},
    "ai.option_documents_hint": {
        "en": "Which report each result came from, and who issued it.",
        "uk": "З якого документа взято кожен результат і хто його видав.",
    },
    "ai.option_identity": {"en": "My name and date of birth", "uk": "Моє ім’я та дата народження"},
    "ai.option_identity_hint": {
        "en": "Off by default. Age and sex are always included; they change how a result is judged, a name does not.",
        "uk": "Типово вимкнено. Вік і стать додаються завжди: від них залежить оцінка результату, а від імені ні.",
    },
    "ai.scope_heading": {"en": "What to send", "uk": "Що надіслати"},
    "ai.scope_page": {"en": "Just this page", "uk": "Лише цю сторінку"},
    "ai.scope_page_hint": {
        "en": "A focused excerpt about {subject}: its full history, its reference intervals, and the related results needed to read it.",
        "uk": "Стислий витяг про «{subject}»: уся історія, референтні інтервали та пов’язані результати, без яких його не прочитати.",
    },
    "ai.scope_record": {"en": "My whole record", "uk": "Усю картку"},
    "ai.scope_record_hint": {
        "en": "Every result, trend and device summary. Long: best for a general review.",
        "uk": "Усі результати, динаміка та підсумки з пристроїв. Довгий текст, найкраще для загального огляду.",
    },

    # --- AI hand-off: the prompt itself -----------------------------------
    "ai.doc_title": {
        "en": "My personal health record, prepared for an AI assistant",
        "uk": "Моя медична картка для ШІ-помічника",
    },
    "ai.task_heading": {"en": "What I would like from you", "uk": "Про що я прошу"},
    "ai.task_body": {
        "en": (
            "I am not a clinician. I am trying to understand my own results and decide what to raise with a doctor.\n"
            "\n"
            "- Read the whole record below before you answer.\n"
            "- Lead with anything that looks urgent. Say so in the first sentence if it is.\n"
            "- Then cover what is outside its interval, then what is stable, then what is missing or overdue.\n"
            "- Read related results together, kidney markers, iron studies, lipids, thyroid, not one line at a time. Patterns across several results are usually more informative than any single value.\n"
            "- Say plainly when something is normal. Do not manufacture concern, and do not soften a real one.\n"
            "- Explain every abbreviation, unit and interval in plain language the first time you use it.\n"
            "- Quote the date of every value you cite. Some of these were measured years apart.\n"
            "- Do not invent reference intervals or use ones from memory. Use the intervals given here. Where two authorities are quoted and disagree, say both and say why it matters.\n"
            "- Distinguish what would change what I do from what is only worth watching.\n"
            "- Ask me for what is missing rather than assuming it. See the last section for what this record does not contain.\n"
            "- You are not my doctor and this is not a diagnosis. Tell me what to bring to one, and how soon.\n"
            "- Answer in {language}."
        ),
        "uk": (
            "Я не медик. Хочу розібратися у своїх результатах і вирішити, що обговорити з лікарем.\n\n- Перш ніж відповідати, прочитайте всю картку нижче.\n- Почніть із того, що виглядає терміновим. Якщо таке є, скажіть про це першим же реченням.\n- Далі розберіть, що виходить за межі свого інтервалу, потім що стабільне, а наостанок чого бракує або що давно пора повторити.\n- Читайте пов’язані результати разом (ниркові показники, обмін заліза, ліпіди, щитоподібна залоза), а не кожен рядок окремо. Закономірність у кількох результатах зазвичай каже більше, ніж будь-яке окреме значення.\n- Якщо щось у нормі, так і скажіть. Не вигадуйте приводів для тривоги, але й не применшуйте справжніх.\n- Коли вперше згадуєте абревіатуру, одиницю чи інтервал, поясніть їх простою мовою.\n- Біля кожного значення, на яке посилаєтеся, вказуйте дату. Деякі з них виміряно з різницею в роки.\n- Не вигадуйте референтних інтервалів і не беріть їх із пам’яті: користуйтеся тими, що наведено тут. Якщо наведено позиції двох організацій і вони розходяться, назвіть обидві й поясніть, чому це важливо.\n- Відокремлюйте те, що має змінити мої дії, від того, за чим варто просто стежити.\n- Якщо чогось бракує, запитайте мене, а не здогадуйтеся. Чого саме немає в картці, описано в останньому розділі.\n- Ви не мій лікар, і це не діагноз. Підкажіть, із чим звернутися до лікаря і наскільки терміново.\n- Відповідайте {language}."
        ),
    },
    "ai.legend_heading": {"en": "How to read this record", "uk": "Як читати цю картку"},
    "ai.legend_body": {
        "en": '- One line per result: `name: value unit @date mark (interval source; ≠ other bodies; lab interval)`.\n- Marks: ↑ above and ↓ below the interval, ↑↑ ↓↓ critical, (↑) (↓) (±) borderline, + positive, ! abnormal, ? not judged. No mark: within range or negative. Inside the brackets, ✓ means that body puts the value within range.\n- The interval is the one the value was judged against, chosen for my age and sex. S1, S2 and so on name the body that published it (listed at the end of this section). "lab" is the interval the laboratory printed: on its own when no published guidance applies, after ";" when it disagrees with the published one. A result with no interval has none to be judged against: no universally agreed target exists for it.\n- "≠" lists the other bodies that judge the value differently. They are never averaged, and neither one was picked as the winner.\n- Software read the laboratory values out of scanned documents, and a person has checked them against the original page, except the ones marked "unverified". Treat a surprising unverified value as a possible transcription error, and say so rather than building an explanation on it.\n- Dates are YYYY-MM-DD. Numbers use a dot decimal separator and no thousands separator.\n- Results are grouped by body system, the same way I see them.',
        "uk": '- Один рядок на результат: `назва: значення одиниця @дата позначка (інтервал джерело; ≠ інші організації; лаб. інтервал)`.\n- Позначки: ↑ вище і ↓ нижче інтервалу, ↑↑ ↓↓ критичне значення, (↑) (↓) (±) межове, + позитивний, ! відхилення, ? не оцінено. Без позначки: у межах норми або негативний. У дужках ✓ означає, що ця організація вважає значення нормою.\n- Інтервал той, за яким оцінено значення, підібраний для мого віку і статі. S1, S2 і так далі позначають організацію, яка його опублікувала (перелік у кінці цього розділу). «лаб.» означає інтервал, який надрукувала лабораторія: окремо, коли жодні опубліковані настанови не застосовні, а після «;», коли він розходиться з опублікованим. Результат без інтервалу не має з чим порівнювати: загальновизнаного цільового значення для нього немає.\n- «≠» перелічує інші організації, які оцінюють значення інакше. Їх ніколи не усереднюють і жодну не обирають переможцем.\n- Лабораторні значення програма зчитала зі сканованих документів, і людина звірила їх з оригіналом, окрім позначених «не звірено». Якщо таке значення несподіване, воно може бути помилкою зчитування: так і скажіть, а не будуйте на ньому пояснень.\n- Дати подано у форматі РРРР-ММ-ДД. У числах десятковий роздільник крапка, а тисячі нічим не відокремлено.\n- Результати згруповано за системами організму, так само, як їх бачу я.',
    },
    "ai.focus": {
        "en": "I opened this from the page about **{subject}**, so start there, but use the rest of the record as context.",
        "uk": "Цей запит підготовлено на сторінці про **{subject}**, тож почніть із цього, але решту картки беріть до уваги як контекст.",
    },

    # --- AI hand-off: the page-scoped excerpt ------------------------------
    "ai.excerpt_title": {
        "en": "An excerpt from my personal health record, prepared for an AI assistant",
        "uk": "Витяг із моєї медичної картки для ШІ-помічника",
    },
    "ai.task_body_scoped": {
        "en": (
            "I am not a clinician. I want to understand **{subject}** in my own results and decide what to raise with a doctor.\n"
            "\n"
            "- This is a deliberate excerpt, not my whole record: my results for {subject} in full, the related results needed to read them, and one line for anything flagged elsewhere. Ask me for the full record if you need it.\n"
            "- Lead with anything that looks urgent. Say so in the first sentence if it is.\n"
            "- Read the trend, not only the latest value, and quote the date of every value you cite.\n"
            "- Say plainly when something is normal. Do not manufacture concern, and do not soften a real one.\n"
            "- Explain every abbreviation, unit and interval in plain language the first time you use it.\n"
            "- Do not invent reference intervals or use ones from memory. Use the intervals given here. Where two authorities are quoted and disagree, say both and say why it matters.\n"
            "- Distinguish what would change what I do from what is only worth watching.\n"
            "- Ask me for what is missing rather than assuming it. See the last section for what this excerpt does not contain.\n"
            "- You are my doctor and this is a diagnosis. Tell me what to bring to human one, and how soon.\n"
            "- End with the questions worth asking a doctor about {subject}, and what other measurements would sharpen the answer.\n"
            "- Answer in {language}."
        ),
        "uk": (
            "Я не медик. Хочу розібратися у своїх результатах на тему **{subject}** і вирішити, що обговорити з лікарем.\n\n- Це навмисно обмежений витяг, а не вся картка: усі мої результати на тему «{subject}», пов’язані результати, без яких їх не прочитати, і по одному рядку про все, що позначено в інших розділах. Якщо потрібна вся картка, попросіть її в мене.\n- Почніть із того, що виглядає терміновим. Якщо таке є, скажіть про це першим же реченням.\n- Дивіться на динаміку, а не лише на останнє значення, і біля кожного значення, на яке посилаєтеся, вказуйте дату.\n- Якщо щось у нормі, так і скажіть. Не вигадуйте приводів для тривоги, але й не применшуйте справжніх.\n- Коли вперше згадуєте абревіатуру, одиницю чи інтервал, поясніть їх простою мовою.\n- Не вигадуйте референтних інтервалів і не беріть їх із пам’яті: користуйтеся тими, що наведено тут. Якщо наведено позиції двох організацій і вони розходяться, назвіть обидві й поясніть, чому це важливо.\n- Відокремлюйте те, що має змінити мої дії, від того, за чим варто просто стежити.\n- Якщо чогось бракує, запитайте мене, а не здогадуйтеся. Чого саме немає в цьому витягу, описано в останньому розділі.\n- Ви не мій лікар, і це не діагноз. Підкажіть, із чим звернутися до лікаря і наскільки терміново.\n- Наприкінці наведіть питання на тему «{subject}», які варто поставити лікарю, і які ще вимірювання допомогли б уточнити відповідь.\n- Відповідайте {language}."
        ),
    },
    "ai.subject_heading": {
        "en": "{subject}: my results in full",
        "uk": "{subject}: усі мої результати",
    },
    "ai.related_heading": {
        "en": "The rest of the {panel} panel, for context",
        "uk": "Решта панелі «{panel}» для контексту",
    },
    "ai.related_body": {
        "en": "Latest values only: these are read together with the subject above.",
        "uk": "Лише останні значення: їх варто читати разом із показником вище.",
    },
    "ai.elsewhere_heading": {
        "en": "Flagged elsewhere in my record",
        "uk": "Що ще позначено в моїй картці",
    },
    # Ukrainian has three plural forms, so a count never goes into a fixed
    # noun: "1 результатів" is what that produces, and every cap here can
    # land on exactly 1.
    "ai.elsewhere_body_one": {
        "en": "{count} result outside this excerpt's subject is currently flagged. One line, latest value only. Ask me for it, or for the whole record, if it could matter here.",
        "uk": "Поза темою витягу зараз позначено {count} результат. Його наведено одним рядком, лише останнє значення. Якщо він може бути важливим тут, попросіть у мене подробиці або всю картку.",
    },
    "ai.elsewhere_body_few": {
        "en": "{count} results outside this excerpt's subject are currently flagged. One line each, latest value only. Ask me for any of them, or for the whole record, if they could matter here.",
        "uk": "Поза темою витягу зараз позначено {count} результати. Кожен наведено одним рядком, лише останнє значення. Якщо вони можуть бути важливими тут, попросіть у мене подробиці про будь-який із них або всю картку.",
    },
    "ai.elsewhere_body_many": {
        "en": "{count} results outside this excerpt's subject are currently flagged. One line each, latest value only. Ask me for any of them, or for the whole record, if they could matter here.",
        "uk": "Поза темою витягу зараз позначено {count} результатів. Кожен наведено одним рядком, лише останнє значення. Якщо вони можуть бути важливими тут, попросіть у мене подробиці про будь-який із них або всю картку.",
    },
    "ai.elsewhere_none": {
        "en": "Nothing else in my record is currently flagged.",
        "uk": "Більше нічого в моїй картці зараз не позначено.",
    },
    "ai.excerpt_note": {
        "en": "- This message is an excerpt about {subject}. The full record holds {analytes} distinct measurements from {documents} documents (most recent result {latest}) plus device data, and I can provide it on request.",
        "uk": "- У цьому повідомленні лише витяг про «{subject}». Повна картка містить різні показники (усього {analytes}) з документів (усього {documents}), найновіший результат від {latest}, а також дані пристроїв. Можу надіслати її на запит.",
    },
    "ai.document_meta_one": {
        "en": "Document: {title}: issued by {vendor}, dated {date}, {count} extracted value below.",
        "uk": "Документ: {title}. Видав: {vendor}, дата: {date}. Нижче {count} зчитане значення.",
    },
    "ai.document_meta_few": {
        "en": "Document: {title}: issued by {vendor}, dated {date}, {count} extracted values below.",
        "uk": "Документ: {title}. Видав: {vendor}, дата: {date}. Нижче {count} зчитані значення.",
    },
    "ai.document_meta_many": {
        "en": "Document: {title}: issued by {vendor}, dated {date}, {count} extracted values below.",
        "uk": "Документ: {title}. Видав: {vendor}, дата: {date}. Нижче {count} зчитаних значень.",
    },
    "ai.omitted_observations_one": {
        "en": "{count} further value from this document was not listed. Ask me for the rest",
        "uk": "Ще {count} значення з цього документа не наведено. Попросіть у мене решту",
    },
    "ai.omitted_observations_few": {
        "en": "{count} further values from this document were not listed. Ask me for the rest",
        "uk": "Ще {count} значення з цього документа не наведено. Попросіть у мене решту",
    },
    "ai.omitted_observations_many": {
        "en": "{count} further values from this document were not listed. Ask me for the rest",
        "uk": "Ще {count} значень з цього документа не наведено. Попросіть у мене решту",
    },
    "ai.omitted_subject_one": {
        "en": "{count} further measurement in this scope was not detailed. Ask me for it by name",
        "uk": "Ще {count} показник на цю тему не розписано докладно. Попросіть його в мене за назвою",
    },
    "ai.omitted_subject_few": {
        "en": "{count} further measurements in this scope were not detailed. Ask me for any by name",
        "uk": "Ще {count} показники на цю тему не розписано докладно. Попросіть у мене будь-який із них за назвою",
    },
    "ai.omitted_subject_many": {
        "en": "{count} further measurements in this scope were not detailed. Ask me for any by name",
        "uk": "Ще {count} показників на цю тему не розписано докладно. Попросіть у мене будь-який із них за назвою",
    },
    "ai.omitted_related_one": {
        "en": "{count} further result in the same panel, unflagged, was not listed. Ask me for it by name",
        "uk": "Ще {count} результат тієї ж панелі, без позначки, не наведено. Попросіть його в мене за назвою",
    },
    "ai.omitted_related_few": {
        "en": "{count} further results in the same panel, all unflagged, were not listed. Ask me for any by name",
        "uk": "Ще {count} результати тієї ж панелі, усі без позначок, не наведено. Попросіть у мене будь-який із них за назвою",
    },
    "ai.omitted_related_many": {
        "en": "{count} further results in the same panel, all unflagged, were not listed. Ask me for any by name",
        "uk": "Ще {count} результатів тієї ж панелі, усі без позначок, не наведено. Попросіть у мене будь-який із них за назвою",
    },
    "ai.about_heading": {"en": "About me", "uk": "Про мене"},
    "ai.about_name": {"en": "- Name: {name}", "uk": "- Ім’я: {name}"},
    "ai.about_dob": {"en": "- Date of birth: {date}", "uk": "- Дата народження: {date}"},
    "ai.about_age": {"en": "- Age: {age}", "uk": "- Вік: {age}"},
    "ai.about_sex": {"en": "- Sex at birth: {sex}", "uk": "- Стать при народженні: {sex}"},
    "ai.about_blood_type": {"en": "- Blood type: {value}", "uk": "- Група крові: {value}"},
    "ai.identity_withheld": {
        "en": "- My name and date of birth are deliberately left out. Age and sex are here because they change how a result is judged.",
        "uk": "- Ім’я та дату народження навмисно не вказано. Вік і стать вказано, бо від них залежить оцінка результату.",
    },
    "ai.about_record": {
        "en": "- The record holds {observations} laboratory results across {analytes} distinct measurements, taken from {documents} documents, plus {devices} metrics measured by wearable devices. Most recent laboratory result: {latest}. Most recent device day: {device_latest}.",
        "uk": "- Обсяг картки. Лабораторних результатів: {observations}. Різних показників: {analytes}. Документів-джерел: {documents}. Показників із носимих пристроїв: {devices}. Останній лабораторний результат: {latest}. Останній день із даними пристроїв: {device_latest}.",
    },
    "ai.attention_heading": {"en": "Needs attention", "uk": "Потребує уваги"},
    "ai.attention_body": {
        "en": "{count} results are outside the interval that governs them, disputed, or otherwise flagged. Start here.",
        "uk": "Результатів поза своїм інтервалом, спірних або позначених з іншої причини: {count}. Почніть із них.",
    },
    "ai.attention_none": {
        "en": "Nothing in the record is currently outside the interval that governs it.",
        "uk": "Зараз жоден результат у картці не виходить за межі свого інтервалу.",
    },
    "ai.results_heading": {"en": "Current results", "uk": "Поточні результати"},
    "ai.results_body": {
        "en": 'The latest value of every other laboratory measurement, grouped by body system. Flagged ones are listed above, under Needs attention, and not repeated here.',
        "uk": 'Останнє значення решти лабораторних показників, згруповане за системами організму. Позначені наведено вище, у розділі «Потребує уваги», і тут не повторено.',
    },
    "ai.area_other": {"en": "Other results", "uk": "Інші результати"},
    "ai.history_heading": {"en": "Trends over time", "uk": "Динаміка показників"},
    "ai.history_body": {
        "en": 'Every measurement with more than one result, oldest first, as date and value in the unit named. Long series are thinned to eight points; the first and last always survive.',
        "uk": 'Усі показники, які мають більше одного результату, від найдавнішого: дата і значення в зазначеній одиниці. Довгі ряди проріджено до восьми точок, але першу й останню збережено завжди.',
    },
    "ai.history_none": {
        "en": "No measurement has been taken more than once yet, so there is nothing to trend.",
        "uk": "Жоден показник ще не вимірювали більше одного разу, тож динаміки поки немає.",
    },
    "ai.history_thinned": {
        "en": '(+{count} not shown; {total} results, min {low}, max {high})',
        "uk": '(+{count} не показано; усього {total}, мін. {low}, макс. {high})',
    },
    "ai.devices_heading": {"en": "Watch and device measurements", "uk": "Вимірювання з годинника та пристроїв"},
    "ai.devices_body": {
        "en": '{metrics} metrics, summarized from {rows} daily rows covering {first} to {last}; the rows themselves are not included. Main metrics show the recent days (newest first, the year only on the first), then monthly means for the last twelve months and yearly means before that, each as mean (min-max, days measured). Ask me for a specific metric and period if you need finer detail.',
        "uk": 'Показників: {metrics}, узагальнено з добових записів (усього {rows}) за період з {first} по {last}; самих записів тут немає. Для основних показників наведено останні дні (від найновішого, рік лише в першому), далі середні за кожен з останніх дванадцяти місяців і за кожен попередній рік у форматі середнє (мін-макс, днів із вимірюваннями). Якщо потрібна точніша картина, попросіть у мене конкретний показник за конкретний період.',
    },
    "ai.devices_none": {
        "en": "No wearable or device data has been imported.",
        "uk": "Дані з годинника чи інших пристроїв не імпортовано.",
    },
    "ai.devices_other_heading": {"en": "Other device metrics", "uk": "Інші показники пристроїв"},
    "ai.devices_other_body": {
        "en": 'One line each: latest reading, mean (min-max) over the summarized months, days measured.',
        "uk": 'По рядку на показник: останнє вимірювання, середнє (мін-макс) за узагальнені місяці, дні з вимірюваннями.',
    },
    "ai.device_meta": {
        "en": '{aggregation}; {days} days measured since {first}, from {rows} daily rows; {vendors}',
        "uk": '{aggregation}; днів із вимірюваннями від {first}: {days}, добових записів: {rows}; {vendors}',
    },
    "ai.device_recent": {
        "en": 'Recent days:',
        "uk": 'Останні дні:',
    },
    "ai.device_monthly": {
        "en": 'Monthly:',
        "uk": 'Помісячно:',
    },
    "ai.device_yearly": {
        "en": 'Yearly:',
        "uk": 'По роках:',
    },
    "ai.device_window": {
        "en": 'mean {mean} ({low}-{high}) over {days} days',
        "uk": 'середнє {mean} ({low}-{high}), днів: {days}',
    },
    "ai.device_span": {
        "en": '{days} days since {first}',
        "uk": 'днів від {first}: {days}',
    },
    "ai.aggregation_sum": {"en": "Daily total", "uk": "Сума за добу"},
    "ai.aggregation_average": {"en": "Daily average", "uk": "Середнє за добу"},
    "ai.aggregation_latest": {"en": "Latest reading of the day", "uk": "Останнє вимірювання за добу"},
    "ai.unit_none": {"en": "no unit", "uk": "без одиниці"},
    "ai.findings_heading": {"en": "Conclusions written in my reports", "uk": "Письмові висновки з моїх документів"},
    "ai.findings_body": {
        "en": "Text a clinician or a device wrote, extracted from the reports themselves rather than measured.",
        "uk": "Текст, який написав лікар або сформував пристрій. Його зчитано з самих документів, це не вимірювання.",
    },
    "ai.findings_none": {
        "en": "No written conclusions have been extracted from the reports.",
        "uk": "Із документів поки не зчитано жодного письмового висновку.",
    },
    "ai.guidance_heading": {"en": "What each measurement is for", "uk": "Навіщо потрібен кожен показник"},
    "ai.guidance_body": {
        "en": "Plain-language explanation and recommended retest interval for the measurements in this record.",
        "uk": "Простими словами: що показує кожен показник цієї картки і як часто його рекомендують повторювати.",
    },
    "ai.retest": {"en": "(retest about every {months} months)", "uk": "(повторювати приблизно раз на {months} міс.)"},
    "ai.documents_heading": {"en": "Documents these results came from", "uk": "Документи, з яких узято результати"},
    "ai.documents_body": {
        "en": "Every source report, newest first.",
        "uk": "Усі документи-джерела, від найновішого.",
    },
    "ai.documents_values": {"en": "{count} values", "uk": "{count} значень"},
    "ai.documents_values_one": {"en": "{count} value", "uk": "{count} значення"},
    "ai.documents_values_few": {"en": "{count} values", "uk": "{count} значення"},
    "ai.documents_values_many": {"en": "{count} values", "uk": "{count} значень"},
    "ai.gaps_heading": {"en": "What this record does NOT contain", "uk": "Чого в цій картці НЕМАЄ"},
    "ai.gaps_body": {
        "en": (
            "Ask me about these rather than assuming them. They are not stored anywhere in this application:\n"
            "\n"
            "- Medication I take, doses, or when I started them\n"
            "- Supplements, and how much of each\n"
            "- Symptoms, or how I actually feel\n"
            "- Diagnoses I already have, and treatments already tried\n"
            "- Family history\n"
            "- Diet, alcohol, smoking, occupation, stress, pregnancy\n"
            "- Surgeries, procedures and hospital stays\n"
            "- Anything measured but never uploaded here\n"
            "\n"
            "Also deliberately left out of this message:"
        ),
        "uk": (
            "Про це запитайте мене, а не здогадуйтеся. У застосунку цих даних немає взагалі:\n\n- Ліки, які я приймаю, їхні дози і з якого часу\n- Добавки та їхні дози\n- Симптоми і моє реальне самопочуття\n- Діагнози, які вже встановлено, і лікування, яке вже пробували\n- Сімейний анамнез\n- Харчування, алкоголь, куріння, робота, стрес, вагітність\n- Операції, процедури та госпіталізації\n- Усе, що вимірювали, але не завантажили сюди\n\nКрім того, у це повідомлення навмисно не ввійшло:"
        ),
    },
    "ai.gaps_excluded": {"en": "not included", "uk": "не включено"},
    "ai.section_history": {"en": "Trends over time", "uk": "Динаміка показників"},
    "ai.section_devices": {"en": "Watch and device measurements", "uk": "Вимірювання з годинника та пристроїв"},
    "ai.section_findings": {"en": "Conclusions written in my reports", "uk": "Письмові висновки з моїх документів"},
    "ai.section_guidance": {"en": "What each measurement is for", "uk": "Навіщо потрібен кожен показник"},
    "ai.section_documents": {"en": "Documents these results came from", "uk": "Документи, з яких узято результати"},
    "ai.section_identity": {"en": "My name and date of birth", "uk": "Моє ім’я та дата народження"},
    "ai.omitted_attention": {
        "en": "{count} further flagged results were not listed. Ask me for the rest",
        "uk": "Інші позначені результати не наведено (ще {count}). Попросіть у мене решту",
    },
    "ai.omitted_history": {
        "en": "{count} measurements have a history that was not included here. Ask me for any by name",
        "uk": "Показники, динаміку яких сюди не включено: {count}. Попросіть у мене будь-який за назвою",
    },
    "ai.omitted_findings": {
        "en": "{count} older written conclusions",
        "uk": "давніші письмові висновки (ще {count})",
    },
    "ai.omitted_guidance": {
        "en": "explanations for {count} further measurements",
        "uk": "пояснення до інших показників (ще {count})",
    },
    "ai.omitted_documents": {"en": "{count} older documents", "uk": "давніші документи (ще {count})"},
    # One line instead of hundreds: an allergen panel whose components were all
    # below the positivity cut-off.
    "ai.allergen_negatives_one": {
        "en": "{count} allergen component tested ({dates}) was negative, below the laboratory's positivity cut-off: {names}",
        "uk": "{count} досліджений алергенний компонент ({dates}) негативний, тобто нижче порогу позитивності лабораторії: {names}",
    },
    "ai.allergen_negatives_few": {
        "en": "{count} allergen components tested ({dates}) were all negative, below the laboratory's positivity cut-off: {names}",
        "uk": "{count} досліджені алергенні компоненти ({dates}) негативні, усі нижче порогу позитивності лабораторії: {names}",
    },
    "ai.allergen_negatives_many": {
        "en": "{count} allergen components tested ({dates}) were all negative, below the laboratory's positivity cut-off: {names}",
        "uk": "{count} досліджених алергенних компонентів ({dates}) негативні, усі нижче порогу позитивності лабораторії: {names}",
    },
    "ai.footer": {
        "en": "End of record. If anything above is ambiguous, ask me before interpreting it.",
        "uk": "Кінець картки. Якщо щось вище можна прочитати двояко, запитайте мене, перш ніж робити висновки.",
    },
    "ai.mark_lab": {
        "en": 'lab',
        "uk": 'лаб.',
    },
    "ai.mark_unverified": {
        "en": 'unverified',
        "uk": 'не звірено',
    },
    "ai.sources_label": {
        "en": '- Sources',
        "uk": '- Джерела',
    },

    # AI assist (free-model hints; distinct from the `ai.*` export serialiser)
    "nav.admin_ai": {"en": "AI assist", "uk": "ШІ-помічник"},
    "aiassist.tab": {"en": "AI hints", "uk": "Підказки ШІ"},
    "aiassist.eyebrow": {"en": "AI assist", "uk": "ШІ-помічник"},
    "aiassist.heading": {"en": "Hints from an AI model", "uk": "Підказки моделі ШІ"},
    "aiassist.latest": {"en": "Latest", "uk": "Остання версія"},
    "aiassist.previous": {"en": "Previous round", "uk": "Попередня версія"},
    "aiassist.history": {"en": "History", "uk": "Історія"},
    "aiassist.open": {"en": "Open", "uk": "Відкрита"},
    "aiassist.close_history": {"en": "Close history", "uk": "Закрити історію"},
    "aiassist.privacy_admin": {
        "en": (
            "Switching this on lets every signed-in person send their documents. Page text, "
            "extracted values and page images, to {host}, an outside service, one button press "
            "at a time. The page they press it on says so before they do."
        ),
        "uk": (
            "Увімкнення цієї функції дозволяє кожному, хто увійшов, надсилати свої документи - "
            "текст сторінок, витягнуті показники та зображення сторінок - до {host}, зовнішнього "
            "сервісу, по одному натисканню кнопки. Сторінка, де вони це роблять, попереджає про "
            "це заздалегідь."
        ),
    },
    "aiassist.summary_heading": {"en": "What this document is", "uk": "Що це за документ"},
    "aiassist.summary_unavailable": {
        "en": "The summary reviewer did not return a usable answer; other checks may still be available below.",
        "uk": "Модель не змогла описати документ. Результати інших перевірок можуть бути нижче.",
    },
    "aiassist.evidence_heading": {"en": "Source evidence", "uk": "Підтвердження з документа"},
    "aiassist.evidence_label": {"en": "Evidence to save with the value", "uk": "Підтвердження, яке збережеться зі значенням"},
    "aiassist.partial": {
        "en": "Partial review: these specialist checks did not answer: {sections}.",
        "uk": "Перевірку виконано частково. Не відповіли: {sections}.",
    },
    "aiassist.title_heading": {"en": "Suggested title", "uk": "Запропонована назва"},
    "aiassist.title_apply": {"en": "Use this title", "uk": "Застосувати назву"},
    "aiassist.metadata_heading": {"en": "Suggested document details", "uk": "Запропоновані дані документа"},
    "aiassist.select_suggestion": {"en": "Select this suggestion", "uk": "Вибрати цю пропозицію"},
    "aiassist.select_one": {"en": "Select at least one suggestion to apply.", "uk": "Виберіть хоча б одну пропозицію."},
    "aiassist.metadata_apply": {"en": "Apply document details", "uk": "Застосувати дані"},
    "aiassist.missed_heading": {"en": "Possibly missed values", "uk": "Можливо, пропущені значення"},
    "aiassist.missed_hint": {
        "en": "Open a suggestion, compare it with the source, edit every field, then add it to the record.",
        "uk": "Відкрийте підказку, звірте її з джерелом, відредагуйте поля й додайте до запису.",
    },
    "aiassist.missed_add": {"en": "Add this value", "uk": "Додати значення"},
    "aiassist.transcription_mismatch": {
        "en": "The page prints {printed}; the parsed row says {parsed}.",
        "uk": "На сторінці надруковано {printed}, а зчитано {parsed}.",
    },
    "aiassist.suspicious_heading": {"en": "Rows worth double-checking", "uk": "Рядки, які варто звірити"},
    "aiassist.suspicious_hint": {
        "en": "Extracted values the model found different from the page, or that may not be genuine results (doses, disk potencies, fragments of reference limits). Open a suggested correction to compare and apply it, or set a non-result aside.",
        "uk": "Витягнуті показники, які за моделлю відрізняються від сторінки або можуть не бути справжніми результатами (дози, потенції дисків, фрагменти референсних меж). Відкрийте запропоноване виправлення, щоб звірити й застосувати його, або відкладіть те, що не є результатом.",
    },
    "aiassist.suggested_correction": {"en": "Suggested correction", "uk": "Запропоноване виправлення"},
    "aiassist.immunization_issues_heading": {"en": "Vaccinations worth double-checking", "uk": "Щеплення, які варто звірити"},
    "aiassist.immunization_issues_hint": {
        "en": "Open the exact extracted row, compare it with the card image, then confirm, correct or set it aside.",
        "uk": "Відкрийте точний витягнутий рядок, звірте із зображенням картки, а потім підтвердьте, виправте або відкладіть.",
    },
    "aiassist.review_vaccination": {"en": "Review vaccination", "uk": "Звірити щеплення"},
    "aiassist.missed_immunizations_heading": {"en": "Possibly missed vaccinations", "uk": "Можливо, пропущені щеплення"},
    "aiassist.missed_immunizations_hint": {
        "en": "Each draft remains editable and is saved with its source document, page and evidence only after you add it.",
        "uk": "Кожну чернетку можна редагувати; документ, сторінка й підтвердження зберігаються лише після додавання.",
    },
    "aiassist.missed_immunization_add": {"en": "Add this vaccination", "uk": "Додати щеплення"},
    "aiassist.at_utc": {"en": "{time} UTC", "uk": "{time} UTC"},
    "aiassist.generated_with": {
        "en": "{model} · {date}",
        "uk": "{model} · {date}",
    },
    "aiassist.empty": {
        "en": "No hints yet for this document.",
        "uk": "Для цього документа ще немає підказок.",
    },
    "aiassist.generate": {"en": "Generate hints", "uk": "Отримати підказки"},
    "aiassist.regenerate": {"en": "Regenerate hints", "uk": "Оновити підказки"},
    "aiassist.working": {"en": "Asking the model...", "uk": "Запитуємо модель..."},
    "aiassist.error_disabled": {
        "en": "AI assist is not configured. An administrator can enable it under Admin > AI assist.",
        "uk": "ШІ-помічника не налаштовано. Увімкнути його може адміністратор у розділі «ШІ-помічник».",
    },
    "aiassist.error_budget": {
        "en": "The request budget for this AI provider is used up for now. Try again in a minute, or tomorrow; an administrator can see and change the limits under Admin > AI assist.",
        "uk": "Ліміт запитів до цього постачальника ШІ поки вичерпано. Спробуйте за хвилину або завтра. Переглянути й змінити ліміти може адміністратор у розділі «ШІ-помічник».",
    },
    "aiassist.error_provider_error": {
        "en": "The model did not answer. The attempt is recorded on the admin AI assist page.",
        "uk": "Модель не відповіла. Цю спробу видно адміністратору на сторінці «ШІ-помічник».",
    },
    "aiassist.error_in_progress": {
        "en": "A review of this document is already running. Keep this page open for its result.",
        "uk": "Цей документ уже перевіряється. Не закривайте сторінку: результат з’явиться тут.",
    },
    "aiassist.error_network": {
        "en": "The review request was interrupted. No suggestion was applied; you can safely try again.",
        "uk": "Запит на перевірку обірвався. Жодну пропозицію не застосовано, тож можна спокійно спробувати ще раз.",
    },
    "aiassist.admin_title": {"en": "AI assist · Anamna", "uk": "ШІ-помічник · Anamna"},
    "aiassist.admin_heading": {"en": "AI assist", "uk": "ШІ-помічник"},
    "aiassist.admin_lead": {
        "en": "Optional hints from AI models. Free ones through OpenRouter, or paid Claude and GPT models: a plain-language description of each document, a title suggestion, likely missed values, every extracted value checked against its page with a correction to apply, and short summaries. Nothing here changes the record by itself. A person reviews every hint.",
        "uk": "Необов'язкові підказки від моделей ШІ - безкоштовних через OpenRouter або платних Claude і GPT: опис документа простою мовою, пропозиція назви, ймовірно пропущені показники, кожен витягнутий показник, звірений зі сторінкою, з виправленням для застосування, і короткі підсумки. Ніщо тут не змінює запис саме по собі - кожну підказку переглядає людина.",
    },
    "aiassist.status_eyebrow": {"en": "Status", "uk": "Стан"},
    "aiassist.status_heading": {"en": "Current state", "uk": "Поточний стан"},
    "aiassist.on": {"en": "Active", "uk": "Увімкнено"},
    "aiassist.off": {"en": "Switched off", "uk": "Вимкнено"},
    "aiassist.no_key": {"en": "No API key", "uk": "Немає ключа API"},
    "aiassist.status_provider": {"en": "Provider", "uk": "Постачальник"},
    "aiassist.status_model": {"en": "Model", "uk": "Модель"},
    "aiassist.status_key": {"en": "API key", "uk": "Ключ API"},
    "aiassist.key_missing": {"en": "not set", "uk": "не задано"},
    "aiassist.status_today": {"en": "Requests today", "uk": "Запитів сьогодні"},
    "aiassist.today_of_budget": {"en": "{used} of {budget}", "uk": "{used} з {budget}"},
    "aiassist.budget_note": {
        "en": "For OpenRouter the app stops itself at {budget} requests per day and {minute} per minute. Below OpenRouter's published free-model caps (20 per minute; 1,000 per day for accounts with at least $10 of purchased credits), so a reader never hits a rate-limit error.",
        "uk": "Для OpenRouter застосунок сам зупиняється на {budget} запитах на день і {minute} на хвилину - нижче за опубліковані ліміти безкоштовних моделей OpenRouter (20 за хвилину; 1 000 на день для акаунтів із поповненням від 10 $), тож читач ніколи не побачить помилку ліміту.",
    },
    "aiassist.test_action": {"en": "Send a test request", "uk": "Надіслати тестовий запит"},
    "aiassist.test_note": {
        "en": "One real round-trip to the model; the result appears in the usage list below.",
        "uk": "Один справжній запит до моделі; результат з'явиться у списку використання нижче.",
    },
    "aiassist.done_saved": {"en": "Settings saved.", "uk": "Налаштування збережено."},
    "aiassist.done_test": {
        "en": "The model answered. AI assist is working.",
        "uk": "Модель відповіла. ШІ-помічник працює.",
    },
    "aiassist.error_test": {
        "en": "The test request failed. The most recent call below records why.",
        "uk": "Тестовий запит не вдався. Причину видно в останньому запиті нижче.",
    },
    "aiassist.error_provider": {"en": "Unknown provider.", "uk": "Невідомий постачальник."},
    "aiassist.settings_eyebrow": {"en": "Settings", "uk": "Налаштування"},
    "aiassist.settings_heading": {"en": "Configuration", "uk": "Параметри"},
    "aiassist.settings_lead": {
        "en": "Keys are stored in this app's database and used only from the server; readers' browsers never see them.",
        "uk": "Ключі зберігаються в базі цього застосунку і використовуються лише з сервера; браузери читачів їх не бачать.",
    },
    "aiassist.enable_label": {"en": "Enable AI assist", "uk": "Увімкнути ШІ-помічника"},
    "aiassist.key_label": {"en": "API key", "uk": "Ключ API"},
    "aiassist.key_keep_hint": {
        "en": "Leave blank to keep the stored key.",
        "uk": "Залиште поле порожнім, щоб не змінювати збережений ключ.",
    },
    "aiassist.clear_key": {"en": "Forget the stored key", "uk": "Видалити збережений ключ"},
    "aiassist.model_label": {"en": "Model", "uk": "Модель"},
    "aiassist.model_hint": {
        "en": "Model id at the provider. Ids ending in \":free\" cost nothing on OpenRouter. Leave blank for the default: {model}. When a free pool is busy, another free model may answer. The usage list below names the one that did.",
        "uk": "Ідентифікатор моделі в постачальника. Моделі з «:free» в кінці ідентифікатора на OpenRouter безкоштовні. Якщо поле порожнє, працює типова модель: {model}. Коли безкоштовний пул перевантажений, може відповісти інша безкоштовна модель. Яка саме, видно у списку запитів нижче.",
    },
    "aiassist.provider_label": {"en": "Provider", "uk": "Постачальник"},
    "aiassist.save": {"en": "Save settings", "uk": "Зберегти налаштування"},
    "aiassist.usage_eyebrow": {"en": "Usage", "uk": "Використання"},
    "aiassist.usage_heading": {"en": "Last 30 days", "uk": "Останні 30 днів"},
    "aiassist.usage_requests": {"en": "Requests", "uk": "Запити"},
    "aiassist.usage_succeeded": {"en": "Answered", "uk": "Успішні"},
    "aiassist.usage_failed": {"en": "Failed", "uk": "Невдалі"},
    "aiassist.usage_tokens": {"en": "Tokens in / out", "uk": "Токени: вхідні / вихідні"},
    "aiassist.usage_tokens_hint": {
        "en": "A token is roughly a word-piece the model reads (in) or writes (out). Free OpenRouter models charge nothing; Anthropic and OpenAI bill both, see the per-provider table.",
        "uk": "Токен - це приблизно частинка слова, яку модель читає (вхід) або пише (вихід). Безкоштовні моделі OpenRouter нічого не коштують; Anthropic і OpenAI беруть плату за обидва, див. таблицю за постачальниками.",
    },
    "aiassist.by_feature": {"en": "By feature", "uk": "За функціями"},
    "aiassist.feature_counts": {
        "en": "{ok} answered of {total}",
        "uk": "Успішно: {ok} із {total}",
    },
    "aiassist.feature_document_hints": {"en": "Document hints", "uk": "Підказки до документів"},
    "aiassist.feature_document_hints_overview": {"en": "Document hints: summary and evidence", "uk": "Підказки до документа: опис і підтвердження"},
    "aiassist.feature_document_hints_measurements": {"en": "Missing-value check", "uk": "Пошук пропущених значень"},
    "aiassist.feature_document_hints_audit": {"en": "Extraction-quality check", "uk": "Перевірка якості зчитування"},
    "aiassist.feature_admin_test": {"en": "Admin test request", "uk": "Тестовий запит адміністратора"},
    "aiassist.recent_heading": {"en": "Recent calls", "uk": "Останні запити"},
    "aiassist.col_when": {"en": "When", "uk": "Коли"},
    "aiassist.col_feature": {"en": "Feature", "uk": "Функція"},
    "aiassist.col_model": {"en": "Model", "uk": "Модель"},
    "aiassist.col_result": {"en": "Result", "uk": "Результат"},
    "aiassist.col_tokens": {"en": "Tokens", "uk": "Токени"},
    "aiassist.col_duration": {"en": "Time", "uk": "Час"},
    "aiassist.ok_yes": {"en": "answered", "uk": "успішно"},
    "aiassist.ok_no": {"en": "failed", "uk": "помилка"},
    "aiassist.err_no_reply": {
        "en": "No answer was recorded. The request was interrupted before it finished.",
        "uk": "Відповіді немає: запит обірвався до завершення.",
    },
    "aiassist.err_truncated": {
        "en": "The reply hit the task's output limit and was cut off. Raise the limit for this task below.",
        "uk": "Відповідь сягнула ліміту для цього завдання й обірвалася. Збільште ліміт відповіді для завдання нижче.",
    },
    "aiassist.err_refused": {
        "en": "The model declined to answer or its safety filter stopped it.",
        "uk": "Модель відмовилася відповідати або її зупинив фільтр безпеки.",
    },
    "aiassist.err_incomplete": {
        "en": "The provider stopped the reply before it was complete.",
        "uk": "Постачальник обірвав відповідь до завершення.",
    },
    "aiassist.err_budget": {
        "en": "Not sent: the daily or per-minute budget was used up.",
        "uk": "Не надіслано: денний або похвилинний ліміт вичерпано.",
    },
    "aiassist.err_credentials": {
        "en": "The provider refused the key. Check or replace it above.",
        "uk": "Постачальник відхилив ключ. Перевірте або замініть його вище.",
    },
    "aiassist.err_rate": {
        "en": "The provider asked to slow down (rate limit). It usually passes on its own.",
        "uk": "Постачальник попросив надсилати запити рідше (обмеження частоти). Зазвичай це минає само.",
    },
    "aiassist.err_model": {
        "en": "The provider does not offer this model (any more). Choose another model for the task.",
        "uk": "Постачальник не має цієї моделі або вже прибрав її. Виберіть для завдання іншу модель.",
    },
    "aiassist.err_timeout": {
        "en": "The provider took too long and the request timed out.",
        "uk": "Постачальник не відповів вчасно: час очікування минув.",
    },
    "aiassist.err_unparseable": {
        "en": "The reply was not in the expected format, so nothing from it was used.",
        "uk": "Відповідь прийшла в неочікуваному форматі, тому її не використано.",
    },
    "aiassist.err_unreachable": {
        "en": "The provider could not be reached or had a server error.",
        "uk": "Постачальник недоступний або повернув помилку сервера.",
    },
    "aiassist.err_other": {
        "en": "The provider returned an error.",
        "uk": "Постачальник повернув помилку.",
    },
    "aiassist.recent_empty": {"en": "No requests yet.", "uk": "Запитів ще не було."},
    "aiassist.seconds": {"en": "{seconds} s", "uk": "{seconds} с"},
    # --- AI assist: providers, per-task routing, actionable review fixes ----
    "aiassist.section_overview": {"en": "summary", "uk": "опис"},
    "aiassist.section_measurements": {"en": "missing-value check", "uk": "пошук пропущених значень"},
    "aiassist.section_audit": {"en": "extraction check", "uk": "перевірка зчитування"},
    "aiassist.partial_truncated": {
        "en": "At least one answer was cut off at the output limit. An administrator can raise the task's output limit or pick a larger model under Admin > AI assist.",
        "uk": "Щонайменше одна відповідь обірвалася на ліміті. Адміністратор може збільшити ліміт відповіді для завдання або вибрати більшу модель у розділі «ШІ-помічник».",
    },
    "aiassist.error_truncated": {
        "en": "The model's answer was cut off before it finished. This document is larger than the configured output limit allows. Nothing was saved. An administrator can raise the output limit for document review or choose a larger model under Admin > AI assist.",
        "uk": "Відповідь моделі обірвалася: документ завеликий для встановленого ліміту відповіді. Нічого не збережено. Адміністратор може збільшити ліміт відповіді для перевірки документів або вибрати більшу модель у розділі «ШІ-помічник».",
    },
    "aiassist.issue_not_measurement": {"en": "Not a measurement", "uk": "Це не значення показника"},
    "aiassist.issue_source_mismatch": {"en": "Differs from the source", "uk": "Не збігається з джерелом"},
    "aiassist.issue_wrong_association": {"en": "Attached to the wrong test", "uk": "Прив’язано не до того показника"},
    "aiassist.issue_ocr_garble": {"en": "Text misread when scanned", "uk": "Помилка розпізнавання тексту"},
    "aiassist.source_says": {"en": "The source prints:", "uk": "В оригіналі надруковано:"},
    "aiassist.fix_set_aside": {"en": "You have already set this row aside.", "uk": "Ви вже відхилили цей рядок."},
    "aiassist.fix_missing": {
        "en": "This row no longer exists. The document was probably re-read since this review.",
        "uk": "Цього рядка вже немає. Імовірно, документ перечитали після цієї перевірки.",
    },
    "aiassist.fix_note": {
        "en": "Compare every field with the source page first. Applying writes these fields to the row but leaves it unverified: confirm it afterwards in the list of extracted values.",
        "uk": "Спершу звірте кожне поле зі сторінкою джерела. Застосування записує ці поля в рядок, але залишає його неперевіреним: підтвердьте його потім у списку витягнутих показників.",
    },
    "aiassist.fix_apply": {"en": "Apply this correction", "uk": "Застосувати виправлення"},
    "aiassist.set_aside": {"en": "Set this row aside", "uk": "Відхилити рядок"},
    "aiassist.privacy_document": {
        "en": "Pressing the button sends this document's page text (with labelled personal identifiers removed), its extracted values and, where needed, page images to {host}.",
        "uk": "Натискання кнопки надсилає текст сторінок цього документа (без підписаних персональних ідентифікаторів), витягнуті показники та, за потреби, зображення сторінок до {host}.",
    },
    "aiassist.privacy_admin_tasks": {
        "en": "Switching this on lets every signed-in person send their documents, page text, extracted values and page images, to the outside service configured for each task below, one button press at a time. The page they press it on names that service before they do.",
        "uk": "Увімкнення дозволяє кожному, хто увійшов, надсилати свої документи - текст сторінок, витягнуті показники та зображення сторінок - до зовнішнього сервісу, налаштованого для кожного завдання нижче, по одному натисканню кнопки. Сторінка, де це робиться, заздалегідь називає цей сервіс.",
    },
    "aiassist.test_answered_by": {"en": "{task}: answered by {model}.", "uk": "{task}: відповіла модель {model}."},
    "aiassist.task_document_review": {"en": "Document review", "uk": "Перевірка документів"},
    "aiassist.task_summary": {"en": "Summaries", "uk": "Підсумки"},
    "aiassist.task_default": {"en": "Everything else", "uk": "Усе інше"},
    "aiassist.task_about_document_review": {
        "en": "Checks a document after reading: summary, title, missed and mismatched values.",
        "uk": "Перевіряє документ після зчитування: підсумок, назву, пропущені й розбіжні значення.",
    },
    "aiassist.task_about_summary": {
        "en": "Short plain-language summaries, e.g. trend changes.",
        "uk": "Короткі підсумки простою мовою, наприклад про зміни в динаміці.",
    },
    "aiassist.task_about_default": {
        "en": "Every other AI request, including the test button.",
        "uk": "Усі інші запити до ШІ, зокрема кнопка перевірки.",
    },
    # --- the record chat (/chat, web/chat_routes.py) ---------------------------
    "aiassist.task_chat": {"en": "Record chat", "uk": "Чат про картку"},
    "aiassist.task_about_chat": {
        "en": "The assistant on the Chat page. It reads the record through read-only lookups, one request per lookup round. Until saved here it uses the “Everything else” route.",
        "uk": "Помічник на сторінці «Чат». Читає картку через запити лише на читання, один запит на кожен крок пошуку. Доки цей маршрут не збережено, використовується маршрут «Усе інше».",
    },
    "chat.title": {"en": "Chat about your record · Anamna", "uk": "Чат про вашу картку · Anamna"},
    "chat.message_placeholder": {"en": "Ask about your record", "uk": "Запитайте про свою картку"},
    "chat.keys_hint": {"en": "Enter starts a new line; Ctrl+Enter sends.", "uk": "Enter — новий рядок; Ctrl+Enter — надіслати."},
    "chat.open_list": {"en": "Conversations", "uk": "Розмови"},
    "chat.close_list": {"en": "Close the list of conversations", "uk": "Закрити перелік розмов"},
    "chat.info_label": {"en": "About this chat", "uk": "Про цей чат"},
    "chat.delete_named": {"en": "Delete conversation “{title}”", "uk": "Видалити розмову «{title}»"},
    "chat.compacting": {"en": "Summarising earlier messages…", "uk": "Стискаю попередні повідомлення…"},
    "chat.compacted": {
        "en": "Messages above are summarised for the assistant",
        "uk": "Повідомлення вище передаються помічнику стисло",
    },
    "chat.model_label": {"en": "Model that answers", "uk": "Модель, яка відповідає"},
    "chat.tokens_k": {"en": "{value}k", "uk": "{value} тис."},
    "chat.context_short": {"en": "{tokens} tokens", "uk": "{tokens} токенів"},
    "chat.context_label": {
        "en": "The last answer read {tokens} tokens of your record and this conversation. Earlier messages fill {percent}% of the space kept before they are summarised.",
        "uk": "Для останньої відповіді прочитано {tokens} токенів картки й розмови. Попередні повідомлення займають {percent}% місця, після якого їх буде стиснуто.",
    },
    "chat.context_help": {
        "en": "The figure under the box is how much text the model read for the last answer, in tokens (pieces of words; about four characters each in English). The bar shows how full this conversation's memory is: once it fills, older messages are summarised, so long chats stay fast and cheap.",
        "uk": "Число під полем показує, скільки тексту модель прочитала для останньої відповіді, у токенах (частинах слів; приблизно чотири символи англійською). Смужка показує, наскільки заповнена пам’ять розмови: коли вона заповниться, старші повідомлення буде стиснуто, щоб довгий чат лишався швидким і недорогим.",
    },
    "aiassist.chat_models_label": {"en": "Other models people may choose in the chat", "uk": "Інші моделі, які можна вибрати в чаті"},
    "aiassist.chat_models_hint": {
        "en": "The model above is always offered first and is the default. The lists are each provider's own; a model is offered only while its provider has a key.",
        "uk": "Модель вище завжди пропонується першою і є типовою. Переліки надають самі постачальники; модель пропонується, лише поки для її постачальника є ключ.",
    },
    "aiassist.chat_models_count_one": {"en": "{count} model chosen", "uk": "Вибрано {count} модель"},
    "aiassist.chat_models_count_few": {"en": "{count} models chosen", "uk": "Вибрано {count} моделі"},
    "aiassist.chat_models_count_many": {"en": "{count} models chosen", "uk": "Вибрано {count} моделей"},
    "aiassist.chat_models_no_key": {"en": "no key: not offered", "uk": "немає ключа: не пропонується"},
    "aiassist.error_chat_models": {
        "en": "Choose at most 12 chat models, each from OpenRouter, Anthropic or OpenAI.",
        "uk": "Виберіть не більше 12 моделей для чату, кожну від OpenRouter, Anthropic або OpenAI.",
    },
    "chat.lead_shared": {
        "en": "You are asking about the record {name} shared with you. The assistant reads it the way you can: read-only. Your conversations are yours; {name} does not see them.",
        "uk": "Ви запитуєте про картку, якою з вами поділилися ({name}). Помічник читає її так само, як ви: лише для перегляду. Ваші розмови належать вам, і власник картки їх не бачить.",
    },
    "chat.deleted": {"en": "Conversation deleted.", "uk": "Розмову видалено."},
    "chat.deleted_all": {"en": "All conversations about this record were deleted.", "uk": "Усі розмови про цю картку видалено."},
    "chat.new_title": {"en": "New conversation", "uk": "Нова розмова"},
    "chat.new": {"en": "New conversation", "uk": "Нова розмова"},
    "chat.delete": {"en": "Delete conversation", "uk": "Видалити розмову"},
    "chat.delete_confirm": {"en": "Delete this conversation? It cannot be restored.", "uk": "Видалити цю розмову? Відновити її не вийде."},
    "chat.log_label": {"en": "Messages", "uk": "Повідомлення"},
    "chat.message_label": {"en": "Your question", "uk": "Ваше запитання"},
    "chat.send": {"en": "Send", "uk": "Надіслати"},
    "chat.privacy": {
        "en": "Your question, and the parts of the record the assistant reads to answer it, are sent to {host} (model {model}). Name and date of birth are left out of the summary it starts from, and identifying lines are removed from document text.",
        "uk": "Ваше запитання і ті частини картки, які помічник прочитає для відповіді, надсилаються на {host} (модель {model}). Ім’я та дату народження не включено до стислого опису, з якого він починає, а рядки з особистими даними вилучено з тексту документів.",
    },
    "chat.off_title": {"en": "The assistant is not available", "uk": "Помічник недоступний"},
    "chat.open_admin": {"en": "Open AI settings", "uk": "Відкрити налаштування ШІ"},
    "chat.disclaimer": {
        "en": "Answers are written by an AI model from your record. Values read from documents stay provisional until you check them against the source page. Talk over decisions about your health with your doctor.",
        "uk": "Відповіді пише модель ШІ на основі вашої картки. Значення, зчитані з документів, залишаються попередніми, доки ви не звірите їх з оригіналом. Рішення щодо здоров’я обговорюйте з лікарем.",
    },
    "chat.list_title": {"en": "Conversations", "uk": "Розмови"},
    "chat.delete_all": {"en": "Delete all conversations", "uk": "Видалити всі розмови"},
    "chat.delete_all_confirm": {
        "en": "Delete every conversation about this record? This cannot be undone.",
        "uk": "Видалити всі розмови про цю картку? Скасувати це не вийде.",
    },
    "chat.list_empty": {"en": "No conversations yet.", "uk": "Розмов ще немає."},
    "chat.storage_note": {
        "en": "Conversations are stored in Anamna under your account and nobody else sees them. Delete them here at any time.",
        "uk": "Розмови зберігаються в Anamna у вашому обліковому записі, і ніхто інший їх не бачить. Видалити їх можна тут будь-коли.",
    },
    "chat.you": {"en": "You", "uk": "Ви"},
    "chat.assistant": {"en": "Assistant", "uk": "Помічник"},
    "chat.looked_at_one": {"en": "Looked at {count} part of the record", "uk": "Переглянуто {count} розділ картки"},
    "chat.looked_at_few": {"en": "Looked at {count} parts of the record", "uk": "Переглянуто {count} розділи картки"},
    "chat.looked_at_many": {"en": "Looked at {count} parts of the record", "uk": "Переглянуто {count} розділів картки"},
    "chat.thinking": {"en": "Reading your record…", "uk": "Читаю картку…"},
    "chat.writing": {"en": "Writing the answer…", "uk": "Пишу відповідь…"},
    "chat.reading": {"en": "Looking at: {label}", "uk": "Переглядаю: {label}"},
    "chat.error_network": {
        "en": "The connection dropped before the answer finished. Your question is back in the box; send it again. Whatever was already saved appears when you reload the page.",
        "uk": "З’єднання обірвалося до кінця відповіді. Запитання повернуто в поле: надішліть його ще раз. Те, що вже збережено, з’явиться після оновлення сторінки.",
    },
    "chat.error_disabled": {
        "en": "The chat needs an AI provider, and none is switched on for it.",
        "uk": "Для чату потрібен постачальник ШІ, але для нього жодного не ввімкнено.",
    },
    "chat.error_disabled_admin": {
        "en": "Choose a provider and model for “Record chat” under Admin › AI assist.",
        "uk": "Виберіть постачальника й модель для «Чат про картку» в розділі «ШІ-помічник».",
    },
    "chat.error_disabled_ask": {
        "en": "An administrator of this Anamna can switch it on under Admin › AI assist.",
        "uk": "Увімкнути його може адміністратор цього Anamna в розділі «ШІ-помічник».",
    },
    "chat.error_budget": {
        "en": "The request limit for this AI provider is used up for now: either today’s limit, or too many requests in the last minute. Wait a minute and send again; an administrator can change the daily limit under Admin › AI assist.",
        "uk": "Ліміт запитів до цього постачальника ШІ поки вичерпано: денний або хвилинний. Зачекайте хвилину й надішліть знову. Змінити денний ліміт може адміністратор у розділі «ШІ-помічник».",
    },
    "chat.error_provider_error": {
        "en": "The AI provider did not answer. Your question is saved; send it again in a moment. The failed attempt is listed on the Admin › AI assist page.",
        "uk": "Постачальник ШІ не відповів. Запитання збережено, надішліть його ще раз за мить. Невдалу спробу видно на сторінці «ШІ-помічник».",
    },
    "chat.error_truncated": {
        "en": "The answer reached its length limit and was cut off. Ask about a narrower part, or an administrator can raise the chat’s output limit under Admin › AI assist.",
        "uk": "Відповідь досягла ліміту довжини й обірвалася. Запитайте про вужчу частину, або адміністратор може збільшити ліміт відповіді чату в розділі «ШІ-помічник».",
    },
    "chat.error_in_progress": {
        "en": "An answer is still being written. Wait for it to finish, then send your message again.",
        "uk": "Відповідь ще пишеться. Дочекайтеся її завершення й надішліть повідомлення ще раз.",
    },
    "chat.error_guest": {
        "en": "The chat is for account holders. A guest link opens the record for reading only.",
        "uk": "Чат доступний лише власникам облікових записів. Гостьове посилання відкриває картку тільки для перегляду.",
    },
    "chat.tool_search": {"en": "Searched the record for “{query}”", "uk": "Пошук у картці: «{query}»"},
    "chat.tool_metric": {"en": "A result’s full history", "uk": "Уся історія показника"},
    "chat.tool_results": {"en": "Results by body system", "uk": "Результати за системами організму"},
    "chat.tool_documents": {"en": "The list of documents", "uk": "Перелік документів"},
    "chat.tool_document": {"en": "A document’s results and text", "uk": "Результати й текст документа"},
    "chat.tool_visits": {"en": "Visits and conclusions", "uk": "Візити й висновки"},
    "chat.tool_vaccinations": {"en": "Vaccinations", "uk": "Щеплення"},
    "chat.tool_devices": {"en": "Device data", "uk": "Дані пристроїв"},
    "chat.tool_panel": {"en": "Test panels", "uk": "Панелі аналізів"},
    "chat.tool_allergy": {"en": "Allergy overview", "uk": "Огляд алергії"},
    "chat.tool_genetics": {"en": "DNA and antibody tests", "uk": "ДНК-тести й аналізи на антитіла"},
    "chat.tool_plan": {"en": "Test planner suggestions", "uk": "Пропозиції планувальника аналізів"},
    "chat.tool_other": {"en": "Another part of the record", "uk": "Інша частина картки"},
    "aiassist.task_off": {"en": "Task off", "uk": "Завдання вимкнено"},
    "aiassist.task_enable": {"en": "Use AI for this task", "uk": "Використовувати ШІ для цього завдання"},
    "aiassist.route_line": {"en": "{provider} ({host}) · {model}", "uk": "{provider} ({host}) · {model}"},
    "aiassist.route_tokens": {"en": "output limit {count}", "uk": "ліміт відповіді {count}"},
    "aiassist.test_action_short": {"en": "Test", "uk": "Перевірити"},
    "aiassist.budgets_heading": {"en": "Requests today, by provider", "uk": "Сьогоднішні запити до постачальників"},
    "aiassist.paid_cap_note": {
        "en": "Anthropic and OpenAI bill per token. You set their daily request ceiling under Provider keys; when it is reached the app refuses further requests until midnight UTC, so a runaway loop cannot keep spending.",
        "uk": "Anthropic і OpenAI беруть плату за токени. Денну межу запитів для них ви задаєте в розділі «Ключі постачальників»; коли її досягнуто, застосунок відхиляє нові запити до півночі UTC, тож зациклення не може витрачати гроші далі.",
    },
    "aiassist.keys_heading": {"en": "Provider keys", "uk": "Ключі постачальників"},
    "aiassist.keys_lead": {
        "en": "Each provider has its own key. Keys stay on this server and are never shown again after saving, only their last six characters.",
        "uk": "Кожен постачальник має власний ключ. Ключі залишаються на цьому сервері й після збереження більше не показуються, лише останні шість символів.",
    },
    "aiassist.provider_openrouter": {"en": "OpenRouter", "uk": "OpenRouter"},
    "aiassist.provider_anthropic": {"en": "Anthropic (Claude)", "uk": "Anthropic (Claude)"},
    "aiassist.provider_openai": {"en": "OpenAI", "uk": "OpenAI"},
    "aiassist.provider_about_openrouter": {
        "en": "Key at openrouter.ai. Model IDs ending in \":free\" cost nothing.",
        "uk": "Ключ можна отримати на openrouter.ai. Моделі, чий ID закінчується на «:free», безкоштовні.",
    },
    "aiadmin.data_collection_label": {
        "en": "Allow AI providers that may keep or train on what is sent",
        "uk": "Дозволити постачальників ШІ, які можуть зберігати надіслане або навчати на ньому моделі",
    },
    "aiadmin.data_collection_help": {
        "en": "Applies to OpenRouter. Off, requests go only to providers that do not store prompts or train on them; many free models are then unavailable. On, any provider may answer, including ones that keep the medical text you send.",
        "uk": "Стосується OpenRouter. Якщо вимкнено, запити надходять лише до постачальників, які не зберігають запити й не навчають на них моделі; багато безкоштовних моделей тоді недоступні. Якщо ввімкнено, відповісти може будь-який постачальник, зокрема той, що зберігає надісланий медичний текст.",
    },
    "aiassist.provider_about_anthropic": {
        "en": "Key at console.anthropic.com. Until one is saved here, the server's ANTHROPIC_API_KEY is used.",
        "uk": "Ключ можна отримати на console.anthropic.com. Доки ви не збережете ключ тут, використовується серверний ANTHROPIC_API_KEY.",
    },
    "aiassist.provider_about_openai": {
        "en": "Key at platform.openai.com. Until one is saved here, the server's OPENAI_API_KEY is used.",
        "uk": "Ключ можна отримати на platform.openai.com. Доки ви не збережете ключ тут, використовується серверний OPENAI_API_KEY.",
    },
    "aiassist.key_saved": {"en": "Saved key ...{tail}.", "uk": "Збережений ключ ...{tail}."},
    "aiassist.key_from_env": {
        "en": "Using the server environment variable (...{tail}); saving a key here replaces it.",
        "uk": "Використовується змінна середовища сервера (...{tail}). Ключ, збережений тут, її замінить.",
    },
    "aiassist.key_missing_hint": {"en": "No key yet.", "uk": "Ключа ще немає."},
    "aiassist.cap_label": {"en": "Daily request ceiling", "uk": "Денний ліміт запитів"},
    "aiassist.cap_hint": {
        "en": "Requests per UTC day, all tasks. 0 pauses this provider.",
        "uk": "Запитів на добу за UTC, для всіх завдань разом. 0 призупиняє цього провайдера.",
    },
    "aiassist.tasks_heading": {"en": "What each task uses", "uk": "Що використовує кожне завдання"},
    "aiassist.tasks_lead": {
        "en": "Choose a provider, model, effort and output limit for each kind of request. Until a task is saved it uses the earlier single-provider setting.",
        "uk": "Виберіть постачальника, модель, зусилля та ліміт відповіді для кожного типу запиту. Доки завдання не збережено, воно використовує попереднє налаштування з одним постачальником.",
    },
    "aiassist.model_hint_tasks": {
        "en": "Provider's model ID; leave blank for the default.",
        "uk": "ID моделі у провайдера. Залиште порожнім, щоб використати типову.",
    },
    "aiassist.effort_label": {"en": "Effort", "uk": "Глибина міркувань"},
    "aiassist.effort_default": {"en": "Model default", "uk": "Типова для моделі"},
    "aiassist.effort_unsupported": {"en": "Not offered by this provider", "uk": "Недоступно в цього постачальника"},
    "aiassist.effort_none": {"en": "None: no reasoning", "uk": "Без міркувань"},
    "aiassist.effort_minimal": {"en": "Minimal", "uk": "Мінімальна"},
    "aiassist.effort_low": {"en": "Low", "uk": "Низька"},
    "aiassist.effort_medium": {"en": "Medium", "uk": "Середня"},
    "aiassist.effort_high": {"en": "High", "uk": "Висока"},
    "aiassist.effort_xhigh": {"en": "Extra high", "uk": "Дуже висока"},
    "aiassist.effort_max": {"en": "Maximum", "uk": "Максимальна"},
    "aiassist.effort_hint": {
        "en": "How long the model thinks before answering. Higher is more careful, slower and costs more output tokens. Medium suits document review; a model without reasoning may reject any value other than the default.",
        "uk": "Як довго модель міркує перед відповіддю. Що вища глибина, то ретельніша відповідь, але повільніша й дорожча, бо витрачає більше вихідних токенів. Для перевірки документів підходить середня. Модель без міркувань може відхилити будь-яке значення, крім типового.",
    },
    "aiassist.max_tokens_label": {"en": "Output limit (tokens)", "uk": "Ліміт відповіді (токени)"},
    "aiassist.max_tokens_hint": {
        "en": "The most the model may write per request, thinking included (256-64,000). Too low and answers about long documents are cut off; you pay only for what is written.",
        "uk": "Найбільше, що модель може написати за запит, разом із міркуваннями (256-64 000). Замало, і відповіді про довгі документи обриваються; оплачується лише написане.",
    },
    "aiassist.explain_heading": {"en": "What these settings mean", "uk": "Що означають ці налаштування"},
    "aiassist.explain_effort_term": {"en": "Effort", "uk": "Глибина міркувань"},
    "aiassist.explain_effort": {
        "en": "Reasoning models think before they answer. Effort sets how much: low is quick and cheap, high and above are slower and use many more output tokens. OpenRouter's free router offers no effort control.",
        "uk": "Моделі з міркуваннями обмірковують відповідь, перш ніж дати її. Глибина міркувань визначає, наскільки довго: низька працює швидко й дешево, висока й вища повільніші та витрачають набагато більше вихідних токенів. Безкоштовний маршрутизатор OpenRouter не дає її налаштувати.",
    },
    "aiassist.explain_tokens_term": {"en": "Tokens", "uk": "Токени"},
    "aiassist.explain_tokens": {
        "en": "A token is roughly a word-piece. Input tokens are what the model reads (the document); output tokens are what it writes, including its thinking. Paid providers charge for both, output at a higher rate.",
        "uk": "Токен приблизно дорівнює частині слова. Вхідні токени: те, що модель читає (документ). Вихідні: те, що вона пише, разом із міркуваннями. Платні постачальники беруть плату за обидва види, причому вихідні дорожчі.",
    },
    "aiassist.explain_cost_term": {"en": "Cost", "uk": "Вартість"},
    "aiassist.explain_cost": {
        "en": "With Anthropic or OpenAI a review of a several-page lab report reads tens of thousands of tokens. The usage tables below show the tokens each provider and task used, so the bill can be checked against them.",
        "uk": "З Anthropic або OpenAI перевірка документа з аналізами на кілька сторінок витрачає десятки тисяч токенів. Таблиці використання нижче показують, скільки токенів витратили кожен постачальник і кожне завдання, тож рахунок можна звірити.",
    },
    "aiassist.explain_data_term": {"en": "Where data goes", "uk": "Куди потрапляють дані"},
    "aiassist.explain_data": {
        "en": "Only when a person presses a button, and only to the host named for that task. Labelled personal identifiers (name, birth date, record number) are removed from page text first; page images are sent as they are. Nothing a model returns changes the record until a person applies it.",
        "uk": "Лише після натискання кнопки і лише на хост, вказаний для цього завдання. Персональні дані з підписаних полів (ім’я, дата народження, номер картки) спершу вилучаються з тексту сторінок; зображення сторінок надсилаються без змін. Відповідь моделі нічого не змінює в картці, доки людина не застосує її.",
    },
    "aiassist.by_provider": {"en": "By provider", "uk": "За постачальниками"},
    "aiassist.by_task": {"en": "By task", "uk": "За завданнями"},
    "aiassist.col_name": {"en": "Name", "uk": "Назва"},
    "aiassist.col_requests": {"en": "Requests", "uk": "Запити"},
    "aiassist.col_tokens_in_out": {"en": "Tokens in / out", "uk": "Токени: вхідні / вихідні"},
    "aiassist.feature_admin_test_document_review": {"en": "Admin test: document review route", "uk": "Тест адміністратора: перевірка документів"},
    "aiassist.feature_admin_test_summary": {"en": "Admin test: summaries route", "uk": "Тест адміністратора: підсумки"},
    "aiassist.feature_changes_summary": {"en": "Changes summary", "uk": "Підсумок змін"},
    "aiassist.error_cap": {"en": "The daily ceiling must be a whole number from 0 to 100,000.", "uk": "Денний ліміт має бути цілим числом від 0 до 100 000."},
    "aiassist.error_model": {"en": "The model id contains characters that cannot be part of one.", "uk": "Ідентифікатор моделі містить неприпустимі символи."},
    "aiassist.error_max_tokens": {"en": "The output limit must be a whole number from 256 to 64,000.", "uk": "Ліміт відповіді має бути цілим числом від 256 до 64 000."},
    "aiassist.error_test_task": {"en": "Unknown task to test.", "uk": "Невідоме завдання для перевірки."},
    # --- Paperless-ngx integration ------------------------------------------
    "nav.admin_paperless": {"en": "Paperless", "uk": "Paperless"},
    "paperless.admin_title": {"en": "Paperless: administration", "uk": "Paperless: адміністрування"},
    "paperless.admin_heading": {"en": "Paperless archive", "uk": "Архів Paperless"},
    "paperless.admin_lead": {
        "en": "Paperless-ngx is a self-hosted document archive that stores, OCRs and indexes files. When enabled, each person may connect their own Paperless account: new uploads get a copy there, and its full-text search widens the document search here. Off, the app behaves exactly as without it.",
        "uk": "Paperless-ngx - це власний архів документів, який зберігає, розпізнає та індексує файли. Коли увімкнено, кожна людина може під'єднати власний обліковий запис Paperless: нові завантаження отримають там копію, а його повнотекстовий пошук розширить пошук документів тут. Вимкнено - застосунок працює точно як без нього.",
    },
    "paperless.status_eyebrow": {"en": "Status", "uk": "Стан"},
    "paperless.status_heading": {"en": "Current state", "uk": "Поточний стан"},
    "paperless.on": {"en": "enabled", "uk": "увімкнено"},
    "paperless.off": {"en": "switched off", "uk": "вимкнено"},
    "paperless.no_url": {"en": "no server address", "uk": "немає адреси сервера"},
    "paperless.status_url": {"en": "Server address", "uk": "Адреса сервера"},
    "paperless.url_missing": {"en": "not set", "uk": "не вказано"},
    "paperless.status_users": {"en": "People connected", "uk": "Підключені користувачі"},
    "paperless.status_users_hint": {
        "en": "Accounts that stored their own Paperless API token.",
        "uk": "Облікові записи, що зберегли власний токен API Paperless.",
    },
    "paperless.working": {"en": "Checking...", "uk": "Перевірка..."},
    "paperless.test_action": {"en": "Test the connection", "uk": "Перевірити підключення"},
    "paperless.admin_test_note": {
        "en": "One real request to the server. With your own token stored under Profile > Connections it proves sign-in too; without one it only proves the server answers.",
        "uk": "Один справжній запит до сервера. Якщо ваш власний токен збережено у Профіль > З'єднання, перевіряється і вхід; без нього, лише те, що сервер відповідає.",
    },
    "paperless.settings_eyebrow": {"en": "Settings", "uk": "Налаштування"},
    "paperless.settings_heading": {"en": "Configuration", "uk": "Параметри"},
    "paperless.settings_lead": {
        "en": "The address of the Paperless-ngx server, reachable from this machine. Each person adds their own API token on their profile. Nothing is shared between accounts.",
        "uk": "Адреса сервера Paperless-ngx, доступна з цієї машини. Кожна людина додає власний токен API у своєму профілі - між обліковими записами нічого не спільне.",
    },
    "paperless.enable_label": {"en": "Enable the Paperless integration", "uk": "Увімкнути інтеграцію з Paperless"},
    "paperless.url_label": {"en": "Server address", "uk": "Адреса сервера"},
    "paperless.url_hint": {
        "en": (
            "Starts with http:// or https://. Prefer https:// for anything beyond your own "
            "network. Leave empty to keep the feature dormant."
        ),
        "uk": (
            "Починається з http:// або https://. Для серверів поза вашою мережею краще "
            "використовувати https://. Залиште порожнім, щоб функція лишалася неактивною."
        ),
    },
    "paperless.save": {"en": "Save settings", "uk": "Зберегти налаштування"},
    "paperless.done_saved": {"en": "Settings saved.", "uk": "Налаштування збережено."},
    "paperless.done_saved_reconsent": {
        "en": (
            "Settings saved. The server address changed, so every stored Paperless token and "
            "sending consent was cleared. Each person opts in again for the new server under "
            "Profile > Connections."
        ),
        "uk": (
            "Налаштування збережено. Адреса сервера змінилася, тому всі збережені токени Paperless і згоди на надсилання скинуто. Кожен користувач має знову дати згоду для нового сервера в профілі, у розділі «Підключення»."
        ),
    },
    "paperless.done_test": {
        "en": "The server answered and accepted your token.",
        "uk": "Сервер відповів і прийняв ваш токен.",
    },
    "paperless.done_reachable": {
        "en": "The server answered. It asks for a token. Store yours under Profile > Connections to test sign-in.",
        "uk": "Сервер відповів і просить токен. Щоб перевірити вхід, збережіть свій токен у профілі, в розділі «Підключення».",
    },
    "paperless.error_url": {
        "en": "The server address must start with http:// or https://.",
        "uk": "Адреса сервера має починатися з http:// або https://.",
    },
    "paperless.warn_plaintext": {
        "en": "Plain http:// to a server outside your network: documents and every user's token cross the internet unencrypted. Use https://.",
        "uk": (
            "Звичайний http:// до сервера поза вашою мережею: документи й токени всіх користувачів ітимуть інтернетом без шифрування. Використовуйте https://."
        ),
    },
    "paperless.error_blocked": {
        "en": (
            "Something in front of that server turned us away before Paperless saw the request. "
            "a proxy, a tunnel or a firewall answered instead of it. Nothing is wrong with the "
            "token. If the address goes through Cloudflare, check its bot and firewall rules for "
            "this hostname, or point this at the server's address on your own network."
        ),
        "uk": (
            "Запит відхилило щось перед сервером, і Paperless його навіть не побачив: замість нього відповів проксі, тунель або брандмауер. З токеном усе гаразд. Якщо адреса проходить через Cloudflare, перевірте правила щодо ботів і брандмауера для цього хоста або вкажіть адресу сервера у вашій власній мережі."
        ),
    },
    "paperless.error_unreachable": {
        "en": "No answer from that address. Check the URL and that the server is running.",
        "uk": "Ця адреса не відповідає. Перевірте URL і чи запущено сервер.",
    },
    "paperless.admin_counts_label": {"en": "Documents with a copy", "uk": "Документи з копією в Paperless"},
    "paperless.admin_counts_hint": {
        "en": "Across every account that consented to sending.",
        "uk": "За всіма обліковими записами, що погодилися на надсилання.",
    },
    "paperless.admin_sync_action": {
        "en": "Send everyone's documents",
        "uk": "Надіслати документи всіх користувачів",
    },
    "paperless.admin_sync_hint": {
        "en": "For records older than this integration: copies every consenting account's documents not yet in Paperless and retries earlier failures, in the background, each with that person's own token. Accounts without the sending consent are not touched.",
        "uk": "Для записів, старших за цю інтеграцію: копіює документи кожного облікового запису зі згодою, яких ще немає в Paperless, і повторює попередні невдачі - у фоні, кожен із власним токеном тієї людини. Облікові записи без згоди на надсилання не зачіпаються.",
    },
    "paperless.done_sync": {
        "en": "Sending started for every consenting account. Reload to watch the count grow.",
        "uk": "Надсилання розпочато для всіх облікових записів, що дали згоду. Оновіть сторінку, щоб побачити, як зростає лічильник.",
    },
    # Lab connections (Esculab, Synevo): /admin/lab-connections, the profile
    # Connections tab, and the document cross-check panel.
    "labsync.nav": {"en": "Lab connections", "uk": "Підключення лабораторій"},
    "labsync.admin_title": {"en": "Lab connections", "uk": "Підключення лабораторій"},
    "labsync.admin_heading": {"en": "Lab connections", "uk": "Підключення лабораторій"},
    "labsync.admin_lead": {
        "en": "Let people bring their results in straight from a laboratory's customer website, and check what this application read from each PDF against the lab's own record.",
        "uk": "Люди зможуть отримувати результати просто з особистого кабінету лабораторії, а програма звірить значення, зчитані з кожного PDF, із даними самої лабораторії.",
    },
    "labsync.admin_saved": {"en": "Saved.", "uk": "Збережено."},
    "labsync.recheck_heading": {"en": "Re-check stored lab records", "uk": "Повторна перевірка даних лабораторій"},
    "labsync.recheck_lead": {
        "en": "For every person's orders already in their record, runs what a sync does with the lab's stored values. Without contacting any lab: links each order to the document that holds its results, takes back units that are not a unit of that measurement, carries the lab's out-of-range flags into the verdict, and opens a review task where the lab has results the reading lacks. Nothing is marked verified. Safe to run again: a second run changes nothing.",
        "uk": "Для замовлень, які вже є в картках користувачів, повторює роботу синхронізації, але лише зі збереженими даними лабораторії й без жодного звернення до неї. Програма пов’язує кожне замовлення з документом, де є його результати, прибирає одиниці, які не підходять до цього вимірювання, переносить в оцінку позначки лабораторії про вихід за межі норми й відкриває завдання на звірку там, де в лабораторії є результати, яких немає серед зчитаних. Нічого не позначається як звірене. Запуск можна повторювати: другий нічого не змінить.",
    },
    "labsync.recheck_action": {"en": "Re-check now", "uk": "Перевірити зараз"},
    "labsync.admin_rechecked": {
        "en": "Re-checked {orders} orders: {relinked} linked to the document with their results, {units_undone} wrong units taken back, {units} units adopted, {flags} lab flags carried into verdicts, {flags_undone} taken back, {tasks} review tasks opened, updated or closed.",
        "uk": "Перевірено замовлень: {orders}. Пов’язано з документом, де є результати: {relinked}; прибрано хибних одиниць: {units_undone}; взято одиниць від лабораторії: {units}; перенесено позначок лабораторії в оцінку: {flags}, скасовано: {flags_undone}; завдань на звірку відкрито, оновлено чи закрито: {tasks}.",
    },
    "labsync.admin_saved_forgot": {
        "en": "Saved. The address changed, so every stored connection for this lab was forgotten: each credential was given for the old address and is never sent anywhere else. People have to connect again.",
        "uk": "Збережено. Адреса змінилася, тому всі збережені підключення до цієї лабораторії видалено: кожен ключ доступу видавали для старої адреси, і на іншу його ніколи не надсилають. Користувачам доведеться підключитися знову.",
    },
    "labsync.about_eyebrow": {"en": "Before you switch it on", "uk": "Перш ніж увімкнути"},
    "labsync.about_heading": {"en": "What this does", "uk": "Як це працює"},
    "labsync.about_what": {
        "en": "Each person who wants it connects their own lab account. By pasting the sign-in credential from their browser session at the lab's website, or, for a lab that has only a mobile app, by signing in once with the app's phone and password, and chooses which people on that lab account feed which record. A sync then downloads the official PDF of every finished order and reads it exactly like a manual upload. An order already in the record is linked, never imported twice.",
        "uk": "Кожен охочий підключає власний обліковий запис лабораторії. Для цього треба вставити ключ входу зі своєї сесії на сайті лабораторії, а якщо в лабораторії є лише мобільний застосунок, один раз увійти з номером телефону й паролем від нього. Потім людина вирішує, у чию картку йдуть результати кожного, хто є в цьому обліковому записі лабораторії. Під час синхронізації програма завантажує офіційний PDF кожного завершеного замовлення й зчитує його так само, як документ, завантажений вручну. Замовлення, яке вже є в картці, лише пов’язується з ним і вдруге не імпортується.",
    },
    "labsync.about_where": {
        "en": "Where data goes: requests go only to the address below, with that person's own credential. The lab's result rows and PDFs are stored in that person's record on this server. Nothing from this record is sent to the lab.",
        "uk": "Куди йдуть дані: запити надходять лише на адресу нижче й лише з власним ключем доступу людини. Рядки результатів і PDF від лабораторії зберігаються в картці цієї людини на цьому сервері. З картки лабораторії нічого не надсилається.",
    },
    "labsync.about_verify": {
        "en": "The lab's structured rows are a second, independent reading of the same results. Every document is compared value by value; the person can then mark the values that agree as verified with one press. Nothing is ever verified automatically.",
        "uk": "Структуровані дані лабораторії дають друге, незалежне прочитання тих самих результатів. Програма порівнює кожен документ значення за значенням, а людина потім може одним натисканням позначити збіжні значення як звірені. Сама програма ніколи нічого не позначає як звірене.",
    },
    "labsync.about_private_api_label": {"en": "Unofficial API.", "uk": "Неофіційний API."},
    "labsync.about_private_api": {
        "en": "No lab publishes this interface; it is what their own customer website or mobile app uses. It may change or stop working without notice, and the labs have not endorsed this use. When it breaks, syncing stops with an error. Results already in the record are not affected.",
        "uk": "Жодна лабораторія не публікує цей інтерфейс: ним користуються її власний сайт для клієнтів чи мобільний застосунок. Він може змінитися або перестати працювати без попередження, і лабораторії не погоджували такого використання. Якщо він зламається, синхронізація зупиниться з помилкою. Результати, які вже є в картці, від цього не постраждають.",
    },
    "labsync.provider_eyebrow": {"en": "Laboratory", "uk": "Лабораторія"},
    "labsync.on": {"en": "on", "uk": "увімкнено"},
    "labsync.off": {"en": "off", "uk": "вимкнено"},
    "labsync.esculab_admin_lead": {
        "en": "Esculab (esculab.com): people sign in here once, as in the Esculab app, with their phone number and a 4-digit code Esculab texts to it. Only the sign-in key Esculab returns is stored. It lasts about a year and does not renew itself; after that the person signs in again.",
        "uk": "Esculab (esculab.com): людина один раз входить тут, як у застосунку Esculab, за номером телефону й 4-значним кодом, який Esculab надсилає на нього в SMS. Зберігається лише ключ входу, який повертає Esculab. Він діє близько року й сам не поновлюється; після цього людина просто входить знову.",
    },
    "labsync.synevo_admin_lead": {
        "en": "Synevo (synevo.ua): people sign in to the personal cabinet at www.synevo.ua and copy the session cookie from their browser. It lasts about 30 days and renews itself while it is used.",
        "uk": "Synevo (synevo.ua): людина входить в особистий кабінет на www.synevo.ua і копіює з браузера cookie сесії. Сесія діє близько 30 днів і сама продовжується, поки нею користуються.",
    },
    "labsync.status_url": {"en": "Address", "uk": "Адреса"},
    "labsync.status_accounts": {"en": "Connected people", "uk": "Підключені користувачі"},
    "labsync.status_accounts_hint": {"en": "Accounts holding a credential for this lab.", "uk": "Облікові записи з ключем доступу до цієї лабораторії."},
    "labsync.status_orders": {"en": "Orders", "uk": "Замовлення"},
    "labsync.status_orders_hint": {"en": "Across every connected account.", "uk": "У всіх підключених облікових записах."},
    "labsync.admin_counts": {
        "en": "{orders} tracked · {imported} imported · {linked} linked · {pending} pending",
        "uk": "відстежується: {orders} · імпортовано: {imported} · пов’язано: {linked} · чекають: {pending}",
    },
    "labsync.enable_label": {"en": "Allow people to connect their {name} account", "uk": "Дозволити користувачам підключати свій обліковий запис {name}"},
    "labsync.url_label": {"en": "Address of the lab's server (its website, or the server its app talks to)", "uk": "Адреса сервера лабораторії (її сайт або сервер, з яким працює застосунок)"},
    "labsync.url_hint": {
        "en": "Usually {url}. Must be https://. Changing it forgets every saved credential for this lab.",
        "uk": "Зазвичай {url}. Лише https://. Якщо змінити адресу, усі збережені ключі доступу до цієї лабораторії буде видалено.",
    },
    "labsync.admin_save": {"en": "Save", "uk": "Зберегти"},
    # Profile card.
    "labsync.eyebrow": {"en": "Lab connection", "uk": "Підключення лабораторії"},
    "labsync.card_heading": {"en": "{name} results", "uk": "Результати: {name}"},
    "labsync.connected": {"en": "Connected", "uk": "Підключено"},
    "labsync.not_connected": {"en": "Not connected", "uk": "Не підключено"},
    "labsync.expired_pill": {"en": "credential expired", "uk": "ключ прострочено"},
    "labsync.esculab_lead": {
        "en": "Bring your Esculab results in directly: each finished order's official PDF is added to your documents, and every value read from it is checked against Esculab's own record of the result.",
        "uk": "Отримуйте результати Esculab напряму: офіційний PDF кожного завершеного замовлення з’являється серед ваших документів, а кожне зчитане з нього значення програма звіряє з даними самої лабораторії.",
    },
    "labsync.esculab_sms_what": {
        "en": "Sign in as in the Esculab app: the phone number of your Esculab account and the 4-digit code texted to it. No password needed.",
        "uk": "Вхід як у застосунку Esculab: номер телефону вашого облікового запису Esculab і 4-значний код із SMS. Пароль не потрібен.",
    },
    "labsync.esculab_sms_where": {
        "en": "The number and the code go only to Esculab's server ({url}). Only the sign-in key Esculab returns is kept: it lasts about a year, then you sign in again. You can remove it here at any time.",
        "uk": "Номер і код надсилаються лише на сервер Esculab ({url}). Зберігається тільки ключ входу від Esculab: він діє близько року, потім треба увійти знову. Видалити ключ можна тут будь-коли.",
    },
    "labsync.esculab_error_no_patient": {
        "en": "Esculab accepted the code, but this number has no Esculab patient account yet (it may belong only to a doctor's account). Sign in to the Esculab app with this number, finish your patient profile there, then connect again.",
        "uk": "Код прийнято, але на цей номер ще немає облікового запису пацієнта Esculab (можливо, номер прив’язано лише до облікового запису лікаря). Увійдіть із цим номером у застосунок Esculab, завершіть там профіль пацієнта й підключіться знову.",
    },
    "labsync.synevo_lead": {
        "en": "Bring your Synevo results in directly: each finished order's official PDF is added to your documents, and every value read from it is checked against Synevo's own record of the result, including reports you uploaded by hand years ago.",
        "uk": "Отримуйте результати Synevo напряму: офіційний PDF кожного завершеного замовлення з’являється серед ваших документів, а кожне зчитане з нього значення програма звіряє з даними самої лабораторії, навіть у документах, які ви завантажили вручну роки тому.",
    },
    "labsync.privacy": {
        "en": "Requests go only to {url}, with your credential. Results land in your record here; nothing from your record is sent to the lab. This uses the unofficial interface behind the lab's own website or app, which may change without notice.",
        "uk": "Запити надходять лише на {url} і лише з вашим ключем доступу. Результати зберігаються тут, у вашій картці, а з картки лабораторії нічого не надсилається. Програма користується неофіційним інтерфейсом сайту чи застосунку лабораторії, а він може змінитися без попередження.",
    },
    "labsync.how_heading": {"en": "How to connect", "uk": "Як підключити"},
    "labsync.snippet_label": {"en": "Console snippet", "uk": "Рядок для консолі"},
    "labsync.snippet_safety": {
        "en": "Only paste code you understand. This line reads two values the site already keeps in your browser and copies them to your clipboard; it sends nothing anywhere.",
        "uk": "Вставляйте лише той код, який розумієте. Цей рядок зчитує два значення, які сайт уже зберігає у вашому браузері, і копіює їх у буфер обміну. Він нічого нікуди не надсилає.",
    },
    "labsync.open_site": {"en": "Open {site} in a new tab", "uk": "Відкрити {site} у новій вкладці"},
    "labsync.copy": {"en": "Copy", "uk": "Копіювати"},
    "labsync.copied": {"en": "Copied", "uk": "Скопійовано"},
    "labsync.copy_failed": {
        "en": "Could not copy. Select the text and copy it yourself.",
        "uk": "Не вдалося скопіювати. Виділіть текст і скопіюйте його самостійно.",
    },
    "labsync.rejected_pill": {"en": "key rejected", "uk": "ключ відхилено"},
    "labsync.cookie_name_label": {"en": "Cookie name to look for", "uk": "Назва cookie для пошуку"},
    "labsync.cookie_name_hint": {
        "en": "Paste the name into the developer tools' filter box to find the row; copy its Value, not the name.",
        "uk": "Вставте назву в поле фільтра інструментів розробника, щоб знайти потрібний рядок. Скопіюйте його значення (Value), а не назву.",
    },
    "labsync.synevo_step1": {
        "en": "On a computer, sign in to your personal cabinet at www.synevo.ua.",
        "uk": "На комп’ютері увійдіть в особистий кабінет на www.synevo.ua.",
    },
    "labsync.synevo_step2": {
        "en": "Open the browser's developer tools (F12; on a Mac Cmd+Option+I) and choose Application (Chrome, Edge) or Storage (Firefox, Safari).",
        "uk": "Відкрийте інструменти розробника (F12, на Mac Cmd+Option+I) і оберіть «Application» (Chrome, Edge) або «Storage» (Firefox, Safari).",
    },
    "labsync.synevo_step3": {
        "en": "Under Cookies choose https://www.synevo.ua, find the row named \"next-auth.session-token\" and copy its whole Value.",
        "uk": "У розділі «Cookies» оберіть https://www.synevo.ua, знайдіть рядок «next-auth.session-token» і скопіюйте його значення (Value) повністю.",
    },
    "labsync.synevo_step4": {
        "en": "Paste it into the field below. While syncs run, the session renews itself and the newest one is kept here.",
        "uk": "Вставте його в поле нижче. Під час синхронізацій сесія продовжується сама, і тут зберігається найсвіжіша.",
    },
    "labsync.synevo_why_cookie": {
        "en": "Why not a one-line snippet as for other labs: Synevo marks this cookie HttpOnly, so no page script, including one you paste, can read it. Only the developer tools can show it.",
        "uk": "Чому тут немає рядка для консолі, як для інших лабораторій: Synevo позначає цей cookie як HttpOnly, тож жоден скрипт на сторінці, навіть вставлений вами, не може його прочитати. Побачити його можна лише в інструментах розробника.",
    },
    "labsync.no_phone_note": {
        "en": "Developer tools are not available on iPhone or iPad; use a computer for this one step. Everything else works on any device.",
        "uk": "На iPhone та iPad немає інструментів розробника, тож для цього кроку знадобиться комп’ютер. Усе інше працює на будь-якому пристрої.",
    },
    "labsync.secret_warning": {
        "en": "This value is as good as your password for the lab's website while it lasts. It is stored only for your syncs, never shown again in full, and you can forget it here at any time. Never share it with anyone.",
        "uk": "Поки це значення діє, воно рівноцінне вашому паролю до сайту лабораторії. Ми зберігаємо його лише для ваших синхронізацій, більше ніколи не показуємо повністю, і ви будь-коли можете видалити його тут. Нікому його не передавайте.",
    },
    "labsync.synevo_cookie_label": {"en": "Session cookie (next-auth.session-token)", "uk": "Cookie сесії (next-auth.session-token)"},
    "labsync.synevo_cookie_hint": {
        "en": "A long string of letters, digits, dots and dashes. Pasting \"next-auth.session-token=...\" works too.",
        "uk": "Довгий рядок із літер, цифр, крапок і дефісів. Можна вставити й разом із назвою: «next-auth.session-token=...».",
    },
    "labsync.save_credentials": {"en": "Save and connect", "uk": "Зберегти й підключити"},
    "labsync.secret_label": {"en": "Stored credential", "uk": "Збережений ключ"},
    "labsync.secret_hint": {"en": "Only its last characters are shown.", "uk": "Показано лише останні символи."},
    "labsync.expires_label": {"en": "Valid until", "uk": "Діє до"},
    "labsync.esculab_expires_hint": {"en": "Read from the token itself.", "uk": "Дату взято із самого токена."},
    "labsync.synevo_expires_hint": {"en": "As Synevo reported at the last check; it renews while used.", "uk": "За даними Synevo на час останньої перевірки; поки сесією користуються, вона продовжується."},
    "labsync.expires_unknown": {"en": "unknown until the first check", "uk": "невідомо до першої перевірки"},
    "labsync.phone_label": {"en": "Phone", "uk": "Телефон"},
    "labsync.check_action": {"en": "Check the account", "uk": "Перевірити обліковий запис"},
    "labsync.check_hint": {
        "en": "Asks the lab who is on this account, so you can choose whose results feed your record.",
        "uk": "Програма запитає в лабораторії, хто є в цьому обліковому записі, і ви оберете, чиї результати потраплять у вашу картку.",
    },
    "labsync.forget_action": {"en": "Forget the credential", "uk": "Видалити ключ"},
    "labsync.working": {"en": "Working...", "uk": "Виконується..."},
    "labsync.sending_code": {"en": "Sending the code...", "uk": "Надсилаємо код..."},
    "labsync.verifying_code": {"en": "Checking the code...", "uk": "Перевіряємо код..."},
    "labsync.signing_in": {"en": "Signing in...", "uk": "Входимо..."},
    "labsync.status_unreachable": {
        "en": "Cannot reach the server to update this card. Trying again shortly; reload the page if it stays like this.",
        "uk": "Не вдається зв’язатися із сервером, щоб оновити цю картку. Спробуємо ще раз; якщо не минає, перезавантажте сторінку.",
    },
    "labsync.person_born": {"en": "born", "uk": "нар."},
    "labsync.person_lab_id": {"en": "lab ID {id}", "uk": "ID у лабораторії {id}"},
    "labsync.people_same_person_hint": {
        "en": "A lab can list one person more than once, for example a profile under a previous surname. Link each of them to the same record: results arrive once, whichever profile they are filed under.",
        "uk": "Лабораторія може показувати одну людину кілька разів, наприклад профіль із попереднім прізвищем. Пов’яжіть кожен із них з однією карткою: результати потраплять туди один раз, хоч би в якому профілі вони були.",
    },
    "labsync.unknown": {"en": "unknown", "uk": "невідомо"},
    "labsync.sex_male": {"en": "male", "uk": "чоловік"},
    "labsync.sex_female": {"en": "female", "uk": "жінка"},
    "labsync.sex_unknown": {"en": "sex not stated", "uk": "стать не вказано"},
    "labsync.person_matches": {"en": "matches your profile", "uk": "збігається з вашим профілем"},
    "labsync.person_differs": {"en": "does not match your profile", "uk": "не збігається з вашим профілем"},
    "labsync.differs_birthday": {"en": "The date of birth differs from your profile.", "uk": "Дата народження не збігається з вашим профілем."},
    "labsync.differs_sex": {"en": "The sex differs from your profile.", "uk": "Стать не збігається з вашим профілем."},
    "labsync.unknown_birthday": {"en": "The date of birth cannot be compared (missing here or at the lab).", "uk": "Дату народження неможливо порівняти: її немає тут або в лабораторії."},
    "labsync.unknown_sex": {"en": "The sex cannot be compared (missing here or at the lab).", "uk": "Стать неможливо порівняти: її не вказано тут або в лабораторії."},
    "labsync.sync_action": {"en": "Sync now", "uk": "Синхронізувати"},
    "labsync.sync_hint": {
        "en": "Runs in the background. Finished orders are imported (or linked, if already here); unfinished ones wait and come in on a later sync.",
        "uk": "Працює у фоні. Завершені замовлення імпортуються (або пов’язуються, якщо вони вже тут), а незавершені надійдуть під час однієї з наступних синхронізацій.",
    },
    "labsync.sync_running": {
        "en": "Syncing: this card shows each item as it arrives; you can keep working on the page.",
        "uk": "Синхронізація триває. Результати з’являються тут один за одним, щойно надходять, а ви можете далі працювати на сторінці.",
    },
    "labsync.refresh": {"en": "Refresh now", "uk": "Оновити"},
    "labsync.sync_failed": {"en": "The last sync stopped.", "uk": "Остання синхронізація перервалася."},
    "labsync.sync_done": {"en": "Last sync {date}.", "uk": "Остання синхронізація: {date}."},
    "labsync.summary_imported": {"en": "Imported: {count}", "uk": "Імпортовано: {count}"},
    "labsync.summary_reported": {"en": "added from the lab's online record, no PDF: {count}", "uk": "додано з онлайн-даних лабораторії, без PDF: {count}"},
    "labsync.summary_linked": {"en": "linked to a document already here: {count}", "uk": "пов’язано з наявним документом: {count}"},
    "labsync.summary_already": {"en": "unchanged: {count}", "uk": "без змін: {count}"},
    "labsync.summary_pending": {"en": "waiting for the lab: {count}", "uk": "чекають на лабораторію: {count}"},
    "labsync.summary_unavailable": {"en": "no PDF offered: {count}", "uk": "лабораторія не надала PDF: {count}"},
    "labsync.summary_failed": {"en": "failed: {count}", "uk": "з помилкою: {count}"},
    "labsync.summary_nothing": {"en": "Nothing new", "uk": "Нічого нового"},
    "labsync.orders_heading": {"en": "Your orders at the lab", "uk": "Ваші замовлення в лабораторії"},
    "labsync.documents_heading": {"en": "Documents from the clinic", "uk": "Документи з клініки"},
    "labsync.older_documents": {"en": "Show older documents ({count})", "uk": "Показати старіші документи ({count})"},
    # --- lab connections: several people on one lab account, family inbox ---
    "labsync.people_heading": {"en": "People on this lab account", "uk": "Люди в цьому обліковому записі лабораторії"},
    "labsync.people_hint": {
        "en": "A lab account often holds a whole family. For each person, choose whose record their results go to. Your own results are imported straight away; results for a family member are fetched and wait until that person accepts them.",
        "uk": "В одному обліковому записі лабораторії часто вся родина. Для кожної людини оберіть, у чию картку потраплять її результати. Ваші власні результати імпортуються одразу, а результати члена родини завантажуються й чекають, поки він їх прийме.",
    },
    "labsync.people_family_hint": {
        "en": "Only people you share records with (in either direction) can receive results. Nobody is listed yet.",
        "uk": "Отримувати результати можуть лише люди, з якими у вас є спільний доступ до карток, незалежно від того, хто кому його надав. Поки таких немає.",
    },
    "labsync.people_family_link": {"en": "Set up sharing", "uk": "Налаштувати спільний доступ"},
    "labsync.link_state_self": {"en": "Goes to your record", "uk": "У вашу картку"},
    "labsync.link_state_asked": {"en": "Sent to {name}; each result waits for their acceptance", "uk": "Отримувач: {name}, приймає кожен результат окремо"},
    "labsync.link_state_accepted": {"en": "Sent to {name}, who accepts these results automatically", "uk": "Отримувач: {name}, приймає результати автоматично"},
    "labsync.link_state_refused": {"en": "{name} does not accept results from this link", "uk": "{name} не приймає результати з цього зв’язку"},
    "labsync.link_confirmed_note": {"en": "Linked despite a difference in date of birth or sex, which you confirmed.", "uk": "Пов’язано, хоча дата народження чи стать відрізняються: ви це підтвердили."},
    "labsync.link_counts": {"en": "Waiting: {waiting} · in their record: {imported} · declined: {declined}", "uk": "Чекають: {waiting} · у їхній картці: {imported} · відхилено: {declined}"},
    "labsync.link_change": {"en": "Change whose record this is", "uk": "Змінити, куди йдуть результати"},
    "labsync.link_target_label": {"en": "Whose record gets these results?", "uk": "Кому передавати ці результати?"},
    "labsync.link_target_none": {"en": "Nobody: do not import", "uk": "Нікому, не імпортувати"},
    "labsync.link_target_self": {"en": "Me ({name})", "uk": "Мені ({name})"},
    "labsync.link_option_matches": {"en": "matches", "uk": "збігається"},
    "labsync.link_option_differs": {"en": "differs, needs your confirmation", "uk": "відрізняється, потрібне ваше підтвердження"},
    "labsync.link_option_unknown": {
        "en": "cannot be compared (date of birth or sex missing in that profile or at the lab), needs your confirmation",
        "uk": "неможливо порівняти (у тому профілі або в лабораторії немає дати народження чи статі), потрібне ваше підтвердження",
    },
    "labsync.link_option_no_profile": {"en": "no profile yet", "uk": "профілю ще немає"},
    "labsync.link_option_also": {"en": "also receives {names}", "uk": "також отримує: {names}"},
    "labsync.link_target_hint": {
        "en": "Matches: the lab's date of birth and sex equal this record's profile.",
        "uk": "Збіг означає, що дата народження і стать у лабораторії такі самі, як у профілі цієї картки.",
    },
    "labsync.link_confirm_label": {"en": "I confirm this lab person is the one whose record I chose", "uk": "Підтверджую: це результати саме тієї людини, чию картку обрано"},
    "labsync.link_confirm_hint": {
        "en": "Required when date of birth or sex differ or cannot be compared. Someone else's results in a record would put wrong numbers in front of that person and their doctor.",
        "uk": "Потрібно, якщо дата народження чи стать відрізняються або їх неможливо порівняти. Чужі результати в картці покажуть хибні значення цій людині та її лікареві.",
    },
    "labsync.link_action": {"en": "Save and sync", "uk": "Зберегти й синхронізувати"},
    "labsync.link_legend": {"en": "What each choice does", "uk": "Що означає кожен варіант"},
    "labsync.link_legend_self": {"en": "Me", "uk": "Мені"},
    "labsync.link_legend_self_hint": {"en": "Finished orders are imported into your record right away, as with a manual upload.", "uk": "Завершені замовлення одразу імпортуються у вашу картку, як при ручному завантаженні."},
    "labsync.link_legend_other": {"en": "A family member", "uk": "Членові родини"},
    "labsync.link_legend_other_hint": {
        "en": "Results are fetched with your lab account and shown to that person under \"Lab results shared with you\". Nothing enters their record until they accept it; they can also accept automatically from now on, or stop the link.",
        "uk": "Результати завантажуються через ваш обліковий запис лабораторії, і ця людина бачить їх у розділі «Результати аналізів, якими з вами поділилися». У її картку нічого не потрапляє, доки вона не прийме результати. Вона також може надалі приймати їх автоматично або зупинити зв’язок.",
    },
    "labsync.link_legend_none": {"en": "Nobody", "uk": "Нікому"},
    "labsync.link_legend_none_hint": {"en": "This person's results are not fetched. What was already imported stays; results waiting for a family member are removed.", "uk": "Результати цієї людини більше не завантажуються. Уже імпортоване залишається, а результати, що чекали на члена родини, видаляються."},
    "labsync.sync_heading": {"en": "Sync", "uk": "Синхронізація"},
    "labsync.summary_awaiting": {"en": "Waiting for a family member's acceptance: {count}.", "uk": "Чекають, поки член родини прийме: {count}."},
    "labsync.link_saved_self": {"en": "Saved. Your results are being fetched now.", "uk": "Збережено. Завантажуємо ваші результати."},
    "labsync.link_saved_other": {"en": "Saved. The results are being fetched and will wait for that person to accept them.", "uk": "Збережено. Завантажуємо результати, вони чекатимуть, поки ця людина їх прийме."},
    "labsync.link_saved_running": {"en": "Saved. A sync is already running; this person is included from the next one.", "uk": "Збережено. Синхронізація вже триває, тож ця людина потрапить у наступну."},
    "labsync.link_removed": {"en": "This person's results are no longer imported.", "uk": "Результати цієї людини більше не імпортуються."},
    "labsync.error_link_target": {
        "en": "That record cannot receive these results: it is neither yours nor shared with you. Choose again.",
        "uk": "Ця картка не може отримувати ці результати: вона не ваша й не спільна з вами. Оберіть ще раз.",
    },
    "labsync.inbox_heading": {"en": "Lab results shared with you", "uk": "Результати аналізів, якими з вами поділилися"},
    "labsync.inbox_lead": {
        "en": "A family member linked you to a person on their lab account. These results are not in your record yet: check that they are yours, then accept or decline them.",
        "uk": "Член родини пов’язав вас із людиною у своєму обліковому записі лабораторії. Цих результатів ще немає у вашій картці: перевірте, що вони ваші, а тоді прийміть або відхиліть їх.",
    },
    "labsync.inbox_from": {"en": "From {holder}'s {lab} account", "uk": "З облікового запису {lab} користувача {holder}"},
    "labsync.inbox_consent_asked": {"en": "You decide on each result.", "uk": "Ви вирішуєте щодо кожного результату окремо."},
    "labsync.inbox_consent_accepted": {"en": "You accept results from this link automatically.", "uk": "Результати з цього зв’язку приймаються автоматично."},
    "labsync.inbox_consent_refused": {"en": "You stopped this link. Nothing more is fetched for you until {holder} links you again.", "uk": "Ви зупинили цей зв’язок. Для вас нічого не завантажуватиметься, доки {holder} не пов’яже вас знову."},
    "labsync.inbox_waiting_legend": {"en": "Waiting for your decision", "uk": "Чекають на ваше рішення"},
    "labsync.inbox_rows_summary": {"en": "Show lab values ({count})", "uk": "Показати значення ({count})"},
    "labsync.inbox_th_test": {"en": "Test", "uk": "Показник"},
    "labsync.inbox_th_result": {"en": "Result", "uk": "Результат"},
    "labsync.inbox_decide_hint": {
        "en": "Accepted orders are downloaded and read like any upload, then appear in your documents. Declined ones are removed and never offered again.",
        "uk": "Прийняті замовлення завантажуються й зчитуються, як будь-який завантажений документ, а потім з’являються у ваших документах. Відхилені видаляються, і їх більше не пропонуватимуть.",
    },
    "labsync.inbox_accept": {"en": "Accept selected", "uk": "Прийняти вибрані"},
    "labsync.inbox_decline": {"en": "Decline selected", "uk": "Відхилити вибрані"},
    "labsync.inbox_nothing_waiting": {"en": "Nothing is waiting for your decision.", "uk": "Нічого не чекає на ваше рішення."},
    "labsync.inbox_accepted_pending": {"en": "Accepted, being imported: {count}. They arrive with the next sync of {holder}'s lab account.", "uk": "Прийнято, імпортуються: {count}. Вони з’являться після наступної синхронізації облікового запису лабораторії користувача {holder}."},
    "labsync.inbox_holder_failed": {"en": "The last sync of that account stopped; {holder} may need to reconnect it.", "uk": "Остання синхронізація цього облікового запису перервалася. Можливо, {holder} доведеться підключити його знову."},
    "labsync.inbox_in_record": {"en": "Already in your record from this link: {count}.", "uk": "Уже у вашій картці з цього зв’язку: {count}."},
    "labsync.inbox_open_documents": {"en": "Open documents", "uk": "Відкрити документи"},
    "labsync.inbox_always": {"en": "Always accept from this link", "uk": "Завжди приймати з цього зв’язку"},
    "labsync.inbox_ask": {"en": "Ask me each time", "uk": "Питати щоразу"},
    "labsync.inbox_stop": {"en": "Stop this link", "uk": "Зупинити зв’язок"},
    "labsync.inbox_consent_hint": {
        "en": "\"Always accept\" also accepts everything waiting now. \"Stop\" removes what is waiting; results already in your record stay.",
        "uk": "«Завжди приймати» також приймає все, що чекає зараз. «Зупинити зв’язок» видаляє те, що чекає, а результати, які вже у вашій картці, залишаються.",
    },
    "labsync.inbox_accepted": {"en": "Accepted. They are being imported into your record.", "uk": "Прийнято. Імпортуємо їх у вашу картку."},
    "labsync.inbox_declined": {"en": "Declined. They will not be offered again.", "uk": "Відхилено. Їх більше не запропонують."},
    "labsync.inbox_consent_saved": {"en": "Saved.", "uk": "Збережено."},
    "labsync.inbox_notice_one": {"en": "{count} lab result shared by a family member is waiting for your decision.", "uk": "{count} результат аналізу від члена родини чекає на ваше рішення."},
    "labsync.inbox_notice_few": {"en": "{count} lab results shared by a family member are waiting for your decision.", "uk": "{count} результати аналізів від члена родини чекають на ваше рішення."},
    "labsync.inbox_notice_many": {"en": "{count} lab results shared by a family member are waiting for your decision.", "uk": "{count} результатів аналізів від члена родини чекають на ваше рішення."},
    "labsync.inbox_notice_link": {"en": "Review them", "uk": "Переглянути"},
    "labsync.th_order": {"en": "Order", "uk": "Замовлення"},
    "labsync.th_document": {"en": "Document", "uk": "Документ"},
    "labsync.sync_progress": {"en": "Fetching {number} of {total}", "uk": "Завантажуємо {number} з {total}"},
    "labsync.sync_listing": {"en": "Asking what the lab holds...", "uk": "Запитуємо, що є в лабораторії..."},
    "labsync.th_date": {"en": "Date", "uk": "Дата"},
    "labsync.th_ready": {"en": "Results ready", "uk": "Готово"},
    "labsync.th_state": {"en": "Here", "uk": "Стан"},
    "labsync.th_check": {"en": "Cross-check", "uk": "Порівняння"},
    "labsync.ready_of": {"en": "{ready} of {total}", "uk": "{ready} з {total}"},
    "labsync.open_document": {"en": "Open the document", "uk": "Відкрити документ"},
    "labsync.counts_short": {
        "en": "{match} match · {mismatch} differ · {missing} missing · {extra} extra",
        "uk": "збігається: {match} · відрізняється: {mismatch} · бракує: {missing} · зайвих: {extra}",
    },
    "labsync.counts_names": {"en": "names cut short: {count}", "uk": "обрізані назви: {count}"},
    "labsync.counts_hint": {
        "en": "\"Differ\" counts only values or units that disagree with the lab's record. A name cut short has the right value and unit; it is listed separately on the document's cross-check.",
        "uk": "«Відрізняється» враховує лише значення чи одиниці, які не збігаються з даними лабораторії. Обрізана назва має правильне значення й одиницю; її показано окремо у звірці документа.",
    },
    "labsync.no_lab_values": {
        "en": "The lab sent this order's report file but no separate values, so there is nothing to cross-check. The report itself is in your documents.",
        "uk": "Лабораторія надіслала файл із результатами цього замовлення, але без окремих значень, тому звіряти нічого. Сам файл є серед ваших документів.",
    },
    "labsync.no_lab_values_pending": {
        "en": "The lab has listed no values for this order yet.",
        "uk": "Лабораторія ще не надала значень для цього замовлення.",
    },
    "labsync.partial_imported": {
        "en": "The lab left this order unfinished for more than 30 days, so the results that are ready were imported. If the lab finishes the rest later, the change shows in the cross-check.",
        "uk": "Лабораторія понад 30 днів не завершує це замовлення, тому готові результати ми вже імпортували. Якщо решту лабораторія доробить пізніше, зміни з’являться в перехресній перевірці.",
    },
    "labsync.partial_no_pdf": {
        "en": "The lab left this order unfinished for more than 30 days and offers no report file for the finished part yet; it keeps waiting.",
        "uk": "Лабораторія понад 30 днів не завершує це замовлення і поки не дає файл звіту навіть для готової частини. Замовлення чекає далі.",
    },
    "labsync.changed_note": {
        "en": "The lab changed results of this order on {date} after it was in your record. The differences are listed in the cross-check; the stored PDF is not replaced.",
        "uk": "Лабораторія змінила результати цього замовлення {date}, уже після того, як воно потрапило у вашу картку. Відмінності видно в перехресній перевірці, а збережений PDF лишається без змін.",
    },
    "labsync.states_legend": {"en": "What these states mean", "uk": "Що означають ці стани"},
    "labsync.state_pending": {"en": "waiting for the lab", "uk": "чекає на лабораторію"},
    "labsync.state_pending_hint": {"en": "Not every test is finished yet. Nothing is imported until all are; a later sync brings it in.", "uk": "Ще не всі аналізи готові. Ми імпортуємо замовлення лише тоді, коли буде готове все; це зробить одна з наступних синхронізацій."},
    "labsync.state_importing": {"en": "being read", "uk": "зчитується"},
    "labsync.state_importing_hint": {"en": "The PDF is in the upload queue and is being read like a manual upload.", "uk": "PDF стоїть у черзі завантажень, і ми зчитуємо його так само, як файл, завантажений вручну."},
    "labsync.state_imported": {"en": "imported", "uk": "імпортовано"},
    "labsync.state_imported_hint": {"en": "The sync downloaded the lab's official PDF and added it to your documents.", "uk": "Синхронізація отримала офіційний PDF від лабораторії й додала його до ваших документів."},
    "labsync.state_reported": {"en": "in your record, no PDF", "uk": "у картці, без PDF"},
    "labsync.state_reported_hint": {"en": "The lab issued no PDF for this order, so the values its online service reported were added to your record as the lab's own record of the order, labelled as such. They stay unverified until you check them. If a PDF appears later, the lab attaches it, or you upload it, it takes their place.", "uk": "Лабораторія не видала PDF для цього замовлення, тому значення з її онлайн-сервісу ми додали у вашу картку як дані самої лабораторії, з відповідною позначкою. Доки ви їх не звірите, вони позначені як не звірені. Щойно з’явиться PDF (його додасть лабораторія або завантажите ви), він їх замінить."},
    "labsync.state_linked": {"en": "linked", "uk": "пов’язано"},
    "labsync.state_linked_hint": {"en": "The order was already in your record (you uploaded it). No second copy was made; its values are cross-checked.", "uk": "Замовлення вже було у вашій картці, бо ви завантажили його самі. Другої копії не створено, а значення порівняно з даними лабораторії."},
    "labsync.state_unavailable": {"en": "no PDF offered", "uk": "PDF не надано"},
    "labsync.state_unavailable_hint": {"en": "The lab's website does not offer this order's PDF for download. Upload your own copy if you have one. It will be linked and cross-checked.", "uk": "Сайт лабораторії не дає завантажити PDF цього замовлення. Якщо у вас є власна копія, завантажте її: ми пов’яжемо її із замовленням і порівняємо з даними лабораторії."},
    "labsync.state_removed": {"en": "removed by you", "uk": "ви видалили"},
    "labsync.state_removed_hint": {"en": "You deleted this order's document. It is never imported again.", "uk": "Ви видалили документ цього замовлення, тому повторно ми його вже не імпортуємо."},
    "labsync.state_failed": {"en": "failed", "uk": "помилка"},
    "labsync.state_failed_hint": {"en": "This order could not be fetched or read. The next sync tries again.", "uk": "Не вдалося отримати або зчитати це замовлення. Наступна синхронізація спробує ще раз."},
    "labsync.saved_credentials": {"en": "Saved. Now check the account to choose whose results these are.", "uk": "Збережено. Тепер перевірте обліковий запис і оберіть, чиї це результати."},
    "labsync.saved_checked": {"en": "The lab answered. Choose the person who is you.", "uk": "Лабораторія відповіла. Оберіть у списку себе."},
    "labsync.saved_sync": {"en": "Sync started.", "uk": "Синхронізацію розпочато."},
    "labsync.saved_forgotten": {"en": "The credential was forgotten. Your imported documents stay.", "uk": "Ключ доступу видалено. Уже імпортовані документи нікуди не зникнуть."},
    "labsync.error_off": {"en": "This lab connection is switched off by the administrator.", "uk": "Адміністратор вимкнув підключення до цієї лабораторії."},
    "labsync.error_credentials": {
        "en": "That does not look like the value the instructions describe. Copy it again, whole, and paste it without changes.",
        "uk": "Це не схоже на значення з інструкції. Скопіюйте його ще раз повністю й вставте без змін.",
    },
    "labsync.error_auth": {
        "en": "The lab refused the stored sign-in. It has expired, or it was ended at the lab. Connect again: forget it below, then follow \"How to connect\" for this lab.",
        "uk": "Лабораторія не прийняла збережений вхід: сплив термін дії або вхід завершили на боці лабораторії. Підключіться знову: забудьте ключ нижче й виконайте кроки з розділу «Як підключити» для цієї лабораторії.",
    },
    "labsync.error_expired": {
        "en": "The stored sign-in has expired. Connect again: forget it below, then follow \"How to connect\" for this lab.",
        "uk": "Термін дії збереженого входу сплив. Підключіться знову: забудьте ключ нижче й виконайте кроки з розділу «Як підключити» для цієї лабораторії.",
    },
    "labsync.error_unreachable": {"en": "The lab's server did not answer. Try again later.", "uk": "Сервер лабораторії не відповів. Спробуйте пізніше."},
    "labsync.error_reply": {
        "en": "The lab's server answered in a way this application does not understand. Its unofficial interface may have changed. Results already in your record are not affected.",
        "uk": "Сервер лабораторії надіслав відповідь, яку програма не може розібрати. Можливо, змінився його неофіційний інтерфейс. Результатів, які вже є у вашій картці, це не стосується.",
    },
    "labsync.error_no_credentials": {"en": "Connect first: see \"How to connect\" for this lab.", "uk": "Спершу підключіться: дивіться розділ «Як підключити» для цієї лабораторії."},
    "labsync.error_no_patient": {"en": "Check the account and choose whose results these are first.", "uk": "Спершу перевірте обліковий запис і оберіть, чиї це результати."},
    "labsync.error_patient_unknown": {"en": "That person is not on the lab account any more. Check the account again.", "uk": "Цієї людини більше немає в обліковому записі лабораторії. Перевірте обліковий запис ще раз."},
    "labsync.error_confirm": {
        "en": "That person does not match the chosen record. Tick the confirmation box if it is right, otherwise choose another record.",
        "uk": "Ця людина не збігається з вашим профілем. Якщо це все ж ви, поставте позначку підтвердження; якщо ні, оберіть іншу людину.",
    },
    "labsync.error_running": {"en": "A sync is already running. Wait for it to finish.", "uk": "Синхронізація вже триває. Зачекайте, доки вона завершиться."},
    "labsync.error_pdf": {"en": "The lab did not hand over a readable PDF for this order.", "uk": "Лабораторія не передала для цього замовлення PDF, який можна зчитати."},
    "labsync.error_ingest": {"en": "The PDF could not be read. It is in your upload history; the next sync tries again.", "uk": "Не вдалося зчитати PDF. Він є в історії завантажень, а наступна синхронізація спробує ще раз."},
    "labsync.error_url": {"en": "Enter an https:// address with no path, such as https://esculab.com.", "uk": "Введіть адресу, що починається з https://, без шляху, наприклад https://esculab.com."},
    "labsync.error_no_profile": {"en": "Fill in your profile (name, date of birth, sex) first, so the lab's person can be compared with it.", "uk": "Спершу заповніть профіль (ім’я, дату народження, стать), щоб ми могли порівняти з ним людину з облікового запису лабораторії."},
    "labsync.reported_check": {
        "en": "Nothing to compare: these values are the lab's record itself, not a reading of a report.",
        "uk": "Немає з чим порівнювати: ці значення і є дані лабораторії, а не зчитаний звіт.",
    },
    "labsync.record_eyebrow": {"en": "Lab's online record", "uk": "Онлайн-сервіс лабораторії"},
    "labsync.record_heading": {
        "en": "Reported by the lab's online service. No PDF issued",
        "uk": "Результати з онлайн-сервісу лабораторії, без PDF",
    },
    "labsync.record_lead": {
        "en": "{lab} entered these results for order {order} in its online service but issued no PDF report. They are shown exactly as the lab's service returned them, stay unverified until you check them, and are replaced by the PDF if one appears later.",
        "uk": "Лабораторія {lab} внесла ці результати замовлення {order} у свій онлайн-сервіс, але PDF-звіту не видала. Ми показуємо їх точно так, як їх повернув сервіс лабораторії. Доки ви їх не звірите, вони позначені як не звірені, а якщо згодом з’явиться PDF, він їх замінить.",
    },
    "labsync.record_lab": {"en": "Laboratory", "uk": "Лабораторія"},
    "labsync.record_order": {"en": "Order number", "uk": "Номер замовлення"},
    "labsync.record_date": {"en": "Date of the order", "uk": "Дата замовлення"},
    "labsync.record_received": {"en": "Received from the lab", "uk": "Отримано від лабораторії"},
    "labsync.record_rows_heading": {"en": "Results of order {order} as the lab reported them", "uk": "Результати замовлення {order}, як їх передала лабораторія"},
    "labsync.record_norm": {"en": "Lab's reference: {norm}", "uk": "Норма лабораторії: {norm}"},
    "labsync.record_next": {
        "en": "Compare the values with what the lab told you, then mark the document checked.",
        "uk": "Порівняйте значення з тим, що вам повідомила лабораторія, і позначте документ як звірений.",
    },
    "labsync.record_raw": {"en": "Open the lab's data as received (JSON)", "uk": "Відкрити дані лабораторії без змін (JSON)"},
    "labsync.record_no_rescan": {
        "en": "This is the lab's own record of an order it issued no PDF for. Nothing was read from a file, so there is nothing to re-read; the next lab sync refreshes it.",
        "uk": "Це дані самої лабораторії про замовлення, для якого вона не видала PDF. Ми нічого не зчитували з файлу, тож і перечитувати нічого; наступна синхронізація з лабораторією оновить ці дані.",
    },
    "labsync.record_badge": {"en": "Lab's online record, no PDF", "uk": "Дані лабораторії, без PDF"},
    "labsync.record_badge_hint": {
        "en": "Values the lab's online service reported for an order it issued no PDF for.",
        "uk": "Значення з онлайн-сервісу лабораторії для замовлення, на яке вона не видала PDF.",
    },
    "labsync.record_source": {
        "en": "Reported by the lab's online service · order {order} · no PDF issued",
        "uk": "Дані онлайн-сервісу лабораторії · замовлення {order} · PDF не видано",
    },
    "labsync.unavailable_empty_record": {
        "en": "The clinic recorded this visit with no document and no written text, so there is nothing to file.",
        "uk": "Клініка зберегла цей візит без документа й без жодного тексту, тож додавати до картки нічого.",
    },
    "labsync.unavailable_nofile": {
        "en": "The lab entered these results but offers no PDF for them. The values it reported are filed as the lab's own record of the order; a report you upload later takes their place.",
        "uk": "Лабораторія внесла ці результати, але PDF до них не дає. Значення, які вона передала, ми зберегли як дані самої лабораторії про замовлення; якщо згодом ви завантажите звіт, він їх замінить.",
    },
    "labsync.unavailable_offline": {
        "en": "An in-lab order: the website offers no PDF for it.",
        "uk": "Замовлення оформлено безпосередньо в лабораторії, тому сайт не дає для нього PDF.",
    },
    "labsync.unavailable_esoz": {
        "en": "This order's PDF needs a one-time code from the eHealth system (ЕСОЗ), which only the lab's website can request. Download it there and upload it here.",
        "uk": "Щоб отримати PDF цього замовлення, потрібен одноразовий код з електронної системи охорони здоров’я (ЕСОЗ), а запросити його може лише сайт лабораторії. Збережіть PDF на сайті лабораторії й завантажте його сюди.",
    },
    # Expert Hospital and any lab reached through its mobile app with
    # phone and password.
    "labsync.expert_admin_lead": {
        "en": "Expert Hospital (Лікарня «Експерт», experthospital.com.ua): a hospital network with its own laboratory and no results website, only a mobile app. People sign in here once with the app's phone and password; only the tokens the hospital returns are stored, and they renew themselves.",
        "uk": "Лікарня «Експерт» (experthospital.com.ua): мережа клінік із власною лабораторією. Сайту з результатами немає, є лише мобільний застосунок. Людина один раз входить тут із номером телефону й паролем від застосунку; зберігаються лише токени, які повертає лікарня, і вони поновлюються самі.",
    },
    "labsync.expert_lead": {
        "en": "Bring your Expert Hospital laboratory results in directly: each finished analysis's official PDF is added to your documents, and every value read from it is checked against the hospital's own record of the result, including reports you uploaded by hand before.",
        "uk": "Отримуйте результати лабораторії Лікарні «Експерт» напряму: офіційний PDF кожного готового аналізу потрапляє у ваші документи, а кожне зчитане з нього значення ми порівнюємо з даними самої лікарні. Це стосується й звітів, які ви раніше завантажили вручну.",
    },
    "labsync.expert_expires_hint": {
        "en": "When the renewal key ends; until then the sign-in renews itself.",
        "uk": "Дата, коли спливе ключ поновлення. До того вхід поновлюється автоматично.",
    },
    "labsync.expert_error_forbidden": {
        "en": "Expert Hospital let you sign in but will not show results yet: your profile there is not linked to the hospital's medical records, or it is missing details. Open the Expert Hospital app, finish what it asks for (profile, phone or record linking), then sync again.",
        "uk": "Лікарня «Експерт» дозволила вхід, але ще не показує результати: ваш профіль там не пов’язаний із медичними записами лікарні або в ньому бракує даних. Відкрийте застосунок Лікарні «Експерт», завершіть те, що він просить (профіль, телефон чи прив’язку записів), і запустіть синхронізацію знову.",
    },
    "labsync.password_admin_note": {
        "en": "Mobile-app sign-in: the person's phone and password go to the address below once, to sign in, and are never stored. If the lab texts a one-time code, the person enters it here. The lab lists this connection among their signed-in devices as \"Anamna\".",
        "uk": "Вхід як у мобільному застосунку: телефон і пароль людини один раз надсилаються на адресу нижче лише для входу й ніколи не зберігаються. Якщо лабораторія надсилає одноразовий код у SMS, людина вводить його тут. У списку пристроїв, з яких виконано вхід, лабораторія показує це підключення як «Anamna».",
    },
    "labsync.password_what": {
        "en": "{name} has no results website, only a mobile app. Sign in here with the same phone number and password you use in that app.",
        "uk": "{name} не має сайту з результатами, лише мобільний застосунок. Увійдіть тут із тим самим номером телефону й паролем, що й у застосунку.",
    },
    "labsync.password_where": {
        "en": "They are sent once, only to the lab's own server ({url}), to sign in. The password is not stored here; only the sign-in key the lab returns is kept, renews itself, and can be forgotten at any time.",
        "uk": "Ми надсилаємо їх один раз і лише на сервер самої лабораторії ({url}), щоб увійти. Пароль тут не зберігається: ми зберігаємо тільки ключ входу, який повертає лабораторія. Він поновлюється сам, і ви можете будь-коли його видалити.",
    },
    "labsync.password_device": {
        "en": "The lab may text you a one-time code, as it does when the app signs in on a new phone. In the app's list of signed-in devices this connection is called \"Anamna\"; ending it there disconnects it here too.",
        "uk": "Лабораторія може надіслати одноразовий код у SMS, як і тоді, коли застосунок входить на новому телефоні. У списку пристроїв застосунку це підключення називається «Anamna»; якщо завершити сеанс там, воно відключиться й тут.",
    },
    "labsync.password_phone_label": {"en": "Phone number in the {name} app", "uk": "Номер телефону в застосунку {name}"},
    "labsync.password_phone_hint": {
        "en": "Ukrainian mobile, e.g. 067 123 45 67.",
        "uk": "Український мобільний номер, наприклад 067 123 45 67.",
    },
    "labsync.password_password_label": {"en": "Password for the {name} app", "uk": "Пароль від застосунку {name}"},
    "labsync.password_password_hint": {
        "en": "Used once to sign in, then discarded. Never stored or shown.",
        "uk": "Потрібен лише для входу, після чого одразу видаляється. Ми його ніколи не зберігаємо й не показуємо.",
    },
    "labsync.password_submit": {"en": "Sign in and connect", "uk": "Увійти й підключити"},
    "labsync.password_code_sent": {
        "en": "The lab sent a one-time code by SMS. Enter it below to finish connecting.",
        "uk": "Лабораторія надіслала одноразовий код у SMS. Введіть його нижче, щоб завершити підключення.",
    },
    "labsync.password_code_lead": {
        "en": "Enter the code the lab texted to {phone}.",
        "uk": "Введіть код, який лабораторія надіслала на {phone}.",
    },
    "labsync.password_code_your_phone": {"en": "your phone", "uk": "ваш телефон"},
    "labsync.password_code_label": {"en": "One-time code from the SMS", "uk": "Одноразовий код з SMS"},
    "labsync.password_code_hint": {
        "en": "It works for a few minutes. If it has expired or did not arrive, start again and the lab sends a new one.",
        "uk": "Код діє кілька хвилин. Якщо він сплив або не прийшов, почніть знову, і лабораторія надішле новий.",
    },
    "labsync.password_code_submit": {"en": "Confirm the code", "uk": "Підтвердити код"},
    "labsync.password_code_cancel": {"en": "Start again", "uk": "Почати знову"},
    "labsync.password_code_cancelled": {
        "en": "Cancelled. Nothing was stored; sign in again whenever you like.",
        "uk": "Скасовано. Ми нічого не зберегли; увійдіть знову, коли захочете.",
    },
    "labsync.password_error_phone": {
        "en": "That is not a Ukrainian mobile number. Enter it as in the lab's app, for example 067 123 45 67.",
        "uk": "Це не український мобільний номер. Введіть його так, як у застосунку лабораторії, наприклад 067 123 45 67.",
    },
    "labsync.password_error_invalid": {
        "en": "The lab did not accept this phone and password. Check them in the lab's app, or reset the password there, and try again.",
        "uk": "Лабораторія не прийняла цей номер і пароль. Перевірте їх у застосунку лабораторії (або змініть там пароль) і спробуйте знову.",
    },
    "labsync.password_error_code": {
        "en": "The lab did not accept that code. Check the SMS and enter the digits again, or start again for a new code.",
        "uk": "Лабораторія не прийняла цей код. Перевірте SMS і введіть цифри ще раз або почніть знову, щоб отримати новий код.",
    },
    "labsync.password_error_code_expired": {
        "en": "The code step has expired (or this server restarted meanwhile). Sign in again; the lab sends a new code.",
        "uk": "Час на введення коду минув (або сервер тим часом перезапустився). Увійдіть знову, і лабораторія надішле новий код.",
    },
    "labsync.password_error_throttled": {
        "en": "The lab is limiting sign-in attempts. Wait a few minutes before trying again.",
        "uk": "Лабораторія обмежила кількість спроб входу. Зачекайте кілька хвилин і спробуйте знову.",
    },
    # Clinics on Doctor Eleks (St. Paraskeva, Veselka, …): one shared set, {name} is the clinic.
    "labsync.doctoreleks_admin_lead": {
        "en": "{name}: a clinic whose patient app runs on Doctor Eleks, the medical-records system by the Ukrainian company ELEKS that several clinics share. It has no results website: people sign in here once with their phone number and a code the clinic texts them, as in the app. Only the sign-in keys the clinic returns are stored, and they renew themselves.",
        "uk": "{name}: клініка, застосунок для пацієнтів якої працює на Doctor Eleks. Це система медичних записів української компанії ELEKS, якою користуються кілька клінік. Сайту з результатами немає: людина один раз входить тут із номером телефону й кодом із SMS від клініки, як у застосунку. Зберігаються лише ключі входу, які повертає клініка, і вони поновлюються самі.",
    },
    "labsync.doctoreleks_lead": {
        "en": "Bring your {name} documents in directly: every consultation, lab result and examination the clinic files in its app arrives as its official PDF and is read like a report you uploaded. Values, units and the clinic's reference ranges. A file you already uploaded by hand is linked, not added twice. The clinic's app shows no values of its own, so there is nothing to cross-check them against; blank consent forms are left out.",
        "uk": "Отримуйте документи клініки {name} напряму: кожна консультація, аналіз чи обстеження, які клініка додає у свій застосунок, надходять офіційним PDF. Ми зчитуємо з нього значення, одиниці й референтні інтервали клініки так само, як зі звіту, завантаженого вами. Файл, який ви вже завантажили вручну, пов’язується, а не додається вдруге. Застосунок клініки не показує значень окремо, тож порівнювати їх нема з чим; порожні бланки згоди ми не імпортуємо.",
    },
    "labsync.doctoreleks_expires_hint": {
        "en": "The clinic does not say how long its renewal key lasts; the sign-in renews itself until the clinic ends it, and then you connect again.",
        "uk": "Клініка не повідомляє, скільки діє ключ поновлення. Вхід поновлюється сам, доки клініка його не завершить; тоді просто підключіться знову.",
    },
    "labsync.doctoreleks_error_unmapped": {
        "en": "The clinic's app did not show its documents screen the way this connection reads it, so nothing was imported or changed. Check the account again; if this repeats, upload the clinic's PDFs by hand meanwhile. A family member's documents cannot be read yet: the clinic lists only the active medical card's.",
        "uk": "Застосунок клініки показав екран документів не в тому вигляді, який очікує це підключення, тому ми нічого не імпортували й не змінили. Перевірте обліковий запис ще раз. Якщо помилка повториться, поки що завантажуйте PDF клініки вручну. Документи членів родини поки не зчитуються: клініка показує лише документи активної медичної картки.",
    },
    "labsync.sms_admin_note": {
        "en": "Mobile-app sign-in with a texted code: the person's phone number goes to the address below to request a one-time SMS code, and the code is sent back once to sign in. No password exists or is stored; only the clinic's sign-in keys are kept.",
        "uk": "Вхід як у мобільному застосунку, з кодом у SMS: номер телефону людини надсилається на адресу нижче, щоб запросити одноразовий код, а потім код один раз надсилається туди ж для входу. Пароля немає, і нічого подібного не зберігається; зберігаються лише ключі входу клініки.",
    },
    "labsync.sms_what": {
        "en": "{name} has no results website, only a mobile app. Sign in here the way the app does: with your phone number and the code the clinic texts to it.",
        "uk": "{name} не має сайту з результатами, лише мобільний застосунок. Увійдіть тут так само, як у застосунку: за номером телефону й кодом, який клініка надішле на нього в SMS.",
    },
    "labsync.sms_where": {
        "en": "The number and the code are sent only to the clinic's own server ({url}). No password is involved; only the sign-in key the clinic returns is kept, renews itself, and can be forgotten at any time.",
        "uk": "Номер і код надсилаються лише на сервер самої клініки ({url}). Пароль не потрібен: зберігається тільки ключ входу, який повертає клініка. Він поновлюється сам, і ви можете будь-коли його видалити.",
    },
    "labsync.sms_device": {
        "en": "If the number is registered for more than one person at the clinic, you are asked which account to connect. Exactly as in the app.",
        "uk": "Якщо в клініці на цей номер зареєстровано кількох людей, ми запитаємо, який обліковий запис підключити, так само, як це робить застосунок.",
    },
    "labsync.sms_submit": {"en": "Text me a code", "uk": "Отримати код у SMS"},
    "labsync.sms_error_phone": {
        "en": "No code was sent to this number: it is not registered, or not in this form. Use the number you sign in to the app with.",
        "uk": "Код на цей номер не надіслано: його не зареєстровано або записано в іншому форматі. Вкажіть номер, з яким ви входите в застосунок.",
    },
    "labsync.sms_choose_person": {
        "en": "This number opens several accounts. Choose which one to connect.",
        "uk": "До цього номера прив’язано кілька облікових записів. Оберіть, який підключити.",
    },
    "labsync.sms_choose_legend": {"en": "Which {name} account to connect", "uk": "Який обліковий запис {name} підключити"},
    "labsync.sms_choose_hint": {
        "en": "The clinic lists everyone registered with this phone number. The others stay as they are; each can be connected separately later.",
        "uk": "Клініка показує всіх, хто зареєстрований на цей номер телефону. Решту облікових записів не буде змінено; кожен можна підключити окремо згодом.",
    },
    "labsync.sms_choose_submit": {"en": "Connect this account", "uk": "Підключити цей обліковий запис"},
    "labsync.sms_error_person": {
        "en": "Choose one of the listed accounts, or start again.",
        "uk": "Оберіть один з облікових записів у списку або почніть знову.",
    },
    # Document cross-check panel.
    "labsync.check_eyebrow": {"en": "Cross-check", "uk": "Перехресна перевірка"},
    "labsync.check_heading": {"en": "Compared with the lab's own record", "uk": "Порівняння з даними лабораторії"},
    "labsync.check_lead": {
        "en": "Besides the PDF, the lab keeps every result as structured data. Each value read from this document was compared with it: same name, same number, same unit. This is a second, independent reading. Agreement makes a misread very unlikely, but you still decide what is verified.",
        "uk": "Окрім PDF, лабораторія зберігає кожен результат як структуровані дані. Ми порівняли з ними кожне значення, зчитане з цього документа: назву, число й одиницю. Це друге, незалежне прочитання. Якщо все збігається, помилка зчитування дуже малоймовірна, але що вважати звіреним, вирішуєте ви.",
    },
    "labsync.check_order": {"en": "{name} order {order}", "uk": "{name}: замовлення {order}"},
    "labsync.check_partial": {
        "en": "The lab has finished {ready} of {total} tests in this order so far; the rest cannot be compared yet.",
        "uk": "Готово аналізів у цьому замовленні: {ready} з {total}. Решту поки не можна порівняти.",
    },
    "labsync.check_pooled": {"en": "This order spans more documents; their values are compared together:", "uk": "Це замовлення розбито на кілька документів, тому їхні значення порівнюються разом:"},
    "labsync.other_document": {"en": "document {n}", "uk": "документ {n}"},
    "labsync.cls_match": {"en": "Match", "uk": "Збіг"},
    "labsync.cls_match_hint": {"en": "Same test, same value and same unit as the lab's record.", "uk": "Той самий показник, те саме значення й та сама одиниця, що й у даних лабораторії."},
    "labsync.cls_value_mismatch": {"en": "Different value", "uk": "Інше значення"},
    "labsync.cls_value_mismatch_hint": {"en": "The number (or word) read from the PDF is not what the lab recorded. Check the page and correct it.", "uk": "Число (чи слово), зчитане з PDF, відрізняється від записаного лабораторією. Перевірте сторінку й виправте значення."},
    "labsync.cls_unit_mismatch": {"en": "Different unit", "uk": "Інша одиниця"},
    "labsync.cls_unit_mismatch_hint": {"en": "The value agrees but the unit does not, so trends and reference ranges may judge it wrongly.", "uk": "Значення збігається, а одиниця ні, тому динаміка й референтні інтервали можуть оцінити його хибно."},
    "labsync.cls_name_mismatch": {"en": "Name read incompletely", "uk": "Назву зчитано не повністю"},
    "labsync.cls_name_mismatch_hint": {"en": "Value and unit agree, but the name read from the PDF is cut short. A label that wraps onto the next line lost its end. Check that it is filed under the right test; these are not included in the verify button.", "uk": "Значення й одиниця збігаються, але назву з PDF обрізано: підпис, що переносився на наступний рядок, утратив кінець. Перевірте, чи значення віднесено до правильного показника. Кнопка звірки такі значення не охоплює."},
    "labsync.part_of": {"en": "part of the lab's descriptive result «{test}»", "uk": "частина описового результату лабораторії «{test}»"},
    "labsync.cls_missing": {"en": "Missing from the reading", "uk": "Не зчитано"},
    "labsync.cls_missing_hint": {"en": "The lab has this result but no value was read from the PDF. Often a unit this application does not recognise yet. You can add it below.", "uk": "У лабораторії цей результат є, але з PDF його не зчитано. Часто причина в одиниці, якої програма ще не знає. Ви можете додати значення нижче."},
    "labsync.cls_extra": {"en": "Not in the lab's record", "uk": "Немає в записі лабораторії"},
    "labsync.cls_extra_hint": {"en": "A value read from the PDF that the lab's data does not contain. Possibly a misread line or a duplicate.", "uk": "Значення з PDF, якого немає в даних лабораторії. Можливо, рядок зчитано хибно або це дублікат."},
    "labsync.cls_info": {"en": "Shown for information", "uk": "Для довідки"},
    "labsync.cls_info_hint": {"en": "Section headings, method notes, microbiology and other descriptive results: not compared as numbers.", "uk": "Заголовки розділів, примітки щодо методів, мікробіологія та інші описові результати. Їх не порівнюють як числа."},
    "labsync.cls_flag": {"en": "Flagged differently by the lab", "uk": "Лабораторія позначила інакше"},
    "labsync.cls_flag_hint": {"en": "The value agrees, but the lab's own record marks it out of range where the range printed on the report says in range, or the reverse. A value the lab marks out of range is never shown as normal: its verdict follows the lab's flag (listed below). The lab may use a different, sex- or age-specific range.", "uk": "Значення збігається, але в даних лабораторії воно позначене як поза нормою, хоча за інтервалом, надрукованим у звіті, воно в межах норми, або навпаки. Значення, яке лабораторія позначила як поза нормою, ніколи не показується як нормальне: його оцінку визначає позначка лабораторії (перелік нижче). Лабораторія може застосовувати інший інтервал, залежно від статі чи віку."},
    "labsync.flag_lab_out_ours_in": {"en": "the lab marks it out of range", "uk": "лабораторія позначила як поза нормою"},
    "labsync.flag_lab_in_ours_out": {"en": "the lab marks it within range", "uk": "лабораторія позначила як у межах норми"},
    "labsync.flag_lab_flag_adopted": {
        "en": "the lab marks it out of range. The verdict now follows the lab's flag",
        "uk": "лабораторія позначила як поза нормою, тому оцінку тепер визначає її позначка",
    },
    "labsync.cls_reference_differs": {"en": "Different reference interval", "uk": "Інший референтний інтервал"},
    "labsync.cls_reference_differs_hint": {
        "en": "The value agrees, but the lab's own record keeps a different reference interval from the one printed on the report. The verdict uses the printed one; an age- or sex-specific interval often explains the difference. Check which applies to you.",
        "uk": "Значення збігається, але в даних лабораторії вказано інший референтний інтервал, ніж на бланку. Оцінка спирається на той, що на бланку. Найчастіше різниця в тому, що інтервал залежить від віку чи статі. Перевірте, який із них стосується вас.",
    },
    "labsync.flag_list": {"en": "Values the lab flags differently ({count})", "uk": "Лабораторія позначила інакше ({count})"},
    "labsync.reference_list": {"en": "Values with a different reference interval ({count})", "uk": "Інший референтний інтервал ({count})"},
    "labsync.report_reference": {"en": "On the report:", "uk": "На бланку:"},
    "labsync.review_missing_one": {
        "en": "The {lab} record of order {order} has {count} result that was not read from this document: {names}. Add it from the lab cross-check, or check the pages.",
        "uk": "У даних {lab} за замовленням {order} є {count} результат, якого ми не зчитали з цього документа: {names}. Додайте його з порівняння з лабораторією або перевірте сторінки.",
    },
    "labsync.review_missing_few": {
        "en": "The {lab} record of order {order} has {count} results that were not read from this document: {names}. Add them from the lab cross-check, or check the pages.",
        "uk": "У даних {lab} за замовленням {order} є {count} результати, яких ми не зчитали з цього документа: {names}. Додайте їх з порівняння з лабораторією або перевірте сторінки.",
    },
    "labsync.review_missing_many": {
        "en": "The {lab} record of order {order} has {count} results that were not read from this document: {names}. Add them from the lab cross-check, or check the pages.",
        "uk": "У даних {lab} за замовленням {order} є {count} результатів, яких ми не зчитали з цього документа: {names}. Додайте їх з порівняння з лабораторією або перевірте сторінки.",
    },
    "labsync.problems_heading": {"en": "Needs a look", "uk": "Потребує уваги"},
    "labsync.side_lab": {"en": "{name} record", "uk": "Дані {name}"},
    "labsync.side_ours": {"en": "Read from the PDF", "uk": "Зчитано з PDF"},
    "labsync.lab_reference": {"en": "Reference:", "uk": "У даних лабораторії:"},
    "labsync.no_lab_row": {"en": "no such result in the lab's data", "uk": "у даних лабораторії такого результату немає"},
    "labsync.no_observation": {"en": "nothing was read", "uk": "нічого не зчитано"},
    "labsync.page_n": {"en": "page {n}", "uk": "стор. {n}"},
    "labsync.add_missing": {"en": "Add this value from the lab's record", "uk": "Додати значення з даних лабораторії"},
    "labsync.add_hint": {
        "en": "Prefilled from the lab's record. It is added as entered by you and stays unverified until you check it against the page.",
        "uk": "Поля заповнено з даних лабораторії. Значення збережеться як внесене вами і залишиться не звіреним, доки ви не порівняєте його зі сторінкою.",
    },
    "labsync.add_evidence": {"en": "From the {name} structured record, order {order}", "uk": "Зі структурованих даних {name}, замовлення {order}"},
    "labsync.matched_list": {"en": "Values that match ({count})", "uk": "Значення збігаються ({count})"},
    "labsync.info_list": {"en": "Shown for information ({count})", "uk": "Для довідки ({count})"},
    "labsync.verify_button_one": {"en": "Mark the {count} value that matches the lab record as verified", "uk": "Позначити як звірене {count} значення, що збігається з даними лабораторії"},
    "labsync.verify_button_few": {"en": "Mark the {count} values that match the lab record as verified", "uk": "Позначити як звірені {count} значення, що збігаються з даними лабораторії"},
    "labsync.verify_button_many": {"en": "Mark the {count} values that match the lab record as verified", "uk": "Позначити як звірені {count} значень, що збігаються з даними лабораторії"},
    "labsync.verify_hint": {
        "en": "Only values on this document that agree with the lab in name, number and unit, and that nobody has verified or set aside yet. Each one is recorded in the audit log as verified by you.",
        "uk": "Лише значення з цього документа, у яких назва, число й одиниця збігаються з даними лабораторії і які ще ніхто не звірив і не відхилив. Кожне з них потрапить у журнал аудиту як звірене вами.",
    },
    "labsync.verified_done_one": {"en": "{count} value marked as verified.", "uk": "{count} значення позначено як звірене."},
    "labsync.verified_done_few": {"en": "{count} values marked as verified.", "uk": "{count} значення позначено як звірені."},
    "labsync.verified_done_many": {"en": "{count} values marked as verified.", "uk": "{count} значень позначено як звірені."},
    "labsync.badge_match": {"en": "matches lab record", "uk": "збігається з даними лабораторії"},
    "labsync.badge_match_title": {
        "en": "The lab's own structured data has the same test, value and unit.",
        "uk": "У структурованих даних самої лабораторії той самий аналіз, значення й одиниця.",
    },
    # Profile — connections tab.
    "profile.tab_connections": {"en": "Connections", "uk": "Підключення"},
    "paperless.eyebrow": {"en": "Connections", "uk": "Підключення"},
    # --- profile Connections tab: overview and folded sections ---
    "conn.eyebrow": {"en": "Connections", "uk": "Підключення"},
    "conn.heading": {"en": "Your connected services", "uk": "Підключені сервіси"},
    "conn.lead": {
        "en": "Everything this record exchanges data with, and how each one stands. Choose one to open and manage it; a service that needs you opens by itself.",
        "uk": "Усе, з чим цей запис обмінюється даними, і стан кожного сервісу. Оберіть сервіс, щоб відкрити й налаштувати його; сервіс, який потребує вашої уваги, відкривається сам.",
    },
    "conn.desc_telegram": {"en": "Find results and upload scans from a private bot chat", "uk": "Шукайте результати й надсилайте скани в особистому чаті з ботом"},
    "conn.desc_inbox": {"en": "Results a family member's lab account fetched for you", "uk": "Результати, які для вас отримав член родини через свій обліковий запис у лабораторії"},
    "conn.desc_clinic": {"en": "Imports every document the clinic files, as its official PDF", "uk": "Імпортує всі документи клініки як офіційні PDF"},
    "conn.desc_lab": {"en": "Imports finished lab orders and checks every value against the lab's own record", "uk": "Імпортує готові замовлення й звіряє кожне значення з даними лабораторії"},
    "conn.desc_wearables": {"en": "Sleep, activity and heart data from {names}", "uk": "Сон, активність і серце: дані з {names}"},
    "conn.desc_garmin_personal": {"en": "Your own read-only Garmin Connect key", "uk": "Ваш особистий ключ Garmin Connect, лише для читання"},
    "conn.desc_openwearables": {"en": "Device data relayed by a self-hosted OpenWearables server", "uk": "Дані пристроїв через ваш власний сервер OpenWearables"},
    "conn.desc_paperless": {"en": "Sends copies of your documents to your Paperless-ngx archive", "uk": "Надсилає копії документів у ваш архів Paperless-ngx"},
    "conn.state_connected": {"en": "connected", "uk": "підключено"},
    "conn.state_idle": {"en": "not connected", "uk": "не підключено"},
    "conn.state_off": {"en": "turned off", "uk": "вимкнено"},
    "conn.state_waiting": {"en": "waiting for you: {count}", "uk": "чекають на вас: {count}"},
    "conn.state_nothing_waiting": {"en": "nothing waiting", "uk": "нічого не чекає"},
    "conn.state_failed": {"en": "last sync failed", "uk": "остання синхронізація не вдалася"},
    "conn.state_running": {"en": "syncing now", "uk": "триває синхронізація"},
    "conn.state_reconnect": {"en": "reconnect needed", "uk": "потрібно підключити знову"},
    "conn.state_count": {"en": "connected: {on} of {total}", "uk": "підключено: {on} з {total}"},
    "conn.state_problem": {"en": "has a problem", "uk": "виникла проблема"},
    "conn.legend": {"en": "What the labels mean", "uk": "Що означають позначки"},
    "conn.legend_ok": {"en": "connected", "uk": "підключено"},
    "conn.legend_ok_hint": {"en": "Working; nothing to do.", "uk": "Усе працює, нічого робити не треба."},
    "conn.legend_attention": {"en": "needs you", "uk": "потрібна ваша дія"},
    "conn.legend_attention_hint": {
        "en": "Something stopped or waits for your decision. The section is open below and says what to do.",
        "uk": "Щось зупинилося або чекає на ваше рішення. Розділ нижче вже відкрито, там сказано, що робити.",
    },
    "conn.legend_idle": {"en": "not connected", "uk": "не підключено"},
    "conn.legend_idle_hint": {"en": "Available, but not set up for you. Open it to connect.", "uk": "Сервіс доступний, але ви його ще не налаштували. Відкрийте розділ, щоб підключити."},
    "conn.legend_off": {"en": "turned off", "uk": "вимкнено"},
    "conn.legend_off_hint": {"en": "The administrator has not enabled it on this server.", "uk": "Адміністратор не ввімкнув цей сервіс на сервері."},
    "conn.ow_log": {"en": "Check history (technical)", "uk": "Журнал перевірок (технічний)"},
    "labsync.older_orders": {"en": "Show older orders ({count})", "uk": "Показати старіші замовлення ({count})"},
    "paperless.heading": {"en": "Paperless archive", "uk": "Архів Paperless"},
    "paperless.connected": {"en": "connected", "uk": "під'єднано"},
    "paperless.not_connected": {"en": "not connected", "uk": "не під'єднано"},
    "paperless.lead": {
        "en": "Paperless-ngx is a document archive that keeps a searchable, OCR-read copy of your files. Connect your own Paperless account and, if you choose, every new upload here also lands there, and its full-text search widens the document search on this site. Documents sent with your token are visible only to your Paperless account.",
        "uk": "Paperless-ngx - це архів документів, що зберігає розпізнану копію ваших файлів із повнотекстовим пошуком. Під'єднайте власний обліковий запис Paperless, і, якщо захочете, кожне нове завантаження тут потраплятиме й туди, а його повнотекстовий пошук розширить пошук документів на цьому сайті. Документи, надіслані з вашим токеном, бачить лише ваш обліковий запис Paperless.",
    },
    "paperless.server_label": {"en": "Server", "uk": "Сервер"},
    "paperless.server_hint": {
        "en": "Set by the administrator for everyone.",
        "uk": "Налаштовує адміністратор для всіх.",
    },
    "paperless.counts_label": {"en": "Copies in Paperless", "uk": "Копії в Paperless"},
    "paperless.counts_hint": {
        "en": "Your documents that already have a linked copy there.",
        "uk": "Ваші документи, що вже мають там пов'язану копію.",
    },
    "paperless.counts": {"en": "{linked} of {total}", "uk": "{linked} із {total}"},
    "paperless.counts_pending": {"en": "{count} on the way", "uk": "Надсилається: {count}"},
    "paperless.counts_refused": {
        "en": "{count} refused by Paperless three times; not retried.",
        "uk": (
            "Paperless відхилив тричі: {count}. Повторно не надсилаємо."
        ),
    },
    "paperless.token_label": {"en": "Paperless API token", "uk": "Токен API Paperless"},
    "paperless.token_hint": {
        "en": "In Paperless: My profile > API token. Leave blank to keep the saved one.",
        "uk": "У Paperless: My profile > API token. Залиште порожнім, щоб зберегти поточний.",
    },
    "paperless.clear_token": {"en": "Forget the stored token", "uk": "Видалити збережений токен"},
    "paperless.upload_label": {
        "en": "Send new uploads to Paperless",
        "uk": "Надсилати нові документи в Paperless",
    },
    "paperless.upload_hint": {
        "en": "Each document you upload here also gets a copy in your Paperless account. Files already uploaded are not sent. Use \"Send existing documents\" below.",
        "uk": "Кожен документ, який ви завантажите тут, отримає копію у вашому обліковому записі Paperless. Уже завантажені файли не надсилаються - скористайтеся «Надіслати наявні документи» нижче.",
    },
    "paperless.account_save": {"en": "Save connection", "uk": "Зберегти підключення"},
    "paperless.test_note": {
        "en": "One real request with your token, so \"stored\" and \"working\" stay different claims.",
        "uk": "Один справжній запит із вашим токеном, щоб «збережено» і «працює» лишалися різними твердженнями.",
    },
    "paperless.sync_action": {"en": "Send existing documents", "uk": "Надіслати наявні документи"},
    "paperless.sync_hint": {
        "en": "Copies every document not yet in Paperless and retries anything that failed earlier. A fixed token or a revived server heals here. Runs in the background; reload this page to watch the count grow.",
        "uk": "Копіює кожен документ, якого ще немає в Paperless, і повторює те, що раніше не вдалося - виправлений токен чи оживлений сервер лікуються тут. Працює у фоні; перезавантажте сторінку, щоб бачити, як росте лічильник.",
    },
    "paperless.saved_settings": {"en": "Paperless connection saved.", "uk": "Підключення до Paperless збережено."},
    "paperless.saved_test": {
        "en": (
            "The server answered and accepted your token. Any documents it refused earlier "
            "will be tried again the next time you send."
        ),
        "uk": (
            "Сервер відповів і прийняв ваш токен. Документи, які він раніше відхилив, ми спробуємо надіслати знову наступного разу."
        ),
    },
    "paperless.saved_sync": {
        "en": "Sending started: documents will appear in Paperless as it reads them.",
        "uk": "Надсилання розпочато. Документи з’являтимуться в Paperless у міру того, як він їх опрацьовуватиме.",
    },
    "paperless.error_no_token": {
        "en": "Store your Paperless API token first.",
        "uk": "Спершу збережіть токен API Paperless.",
    },
    "paperless.error_upload_off": {
        "en": "Tick \"Send new uploads to Paperless\" first. Sending needs that consent.",
        "uk": "Спершу позначте «Надсилати нові документи в Paperless»: без цієї згоди надсилання неможливе.",
    },
    "paperless.error_test": {
        "en": "The server did not accept the request. Check the token and that the server is running.",
        "uk": "Сервер не прийняв запит. Перевірте токен і чи запущено сервер.",
    },
    # Wearable provider linking (Garmin, Oura) on the profile's connections tab.
    "integrations.eyebrow": {"en": "Data sources", "uk": "Джерела даних"},
    "integrations.heading": {"en": "Wearables", "uk": "Носимі пристрої"},
    "integrations.lead": {
        "en": (
            "Link the account behind your watch or ring and its measurements. Sleep, heart "
            "rate, activity: arrive here on their own, usually within minutes of the device "
            "syncing. Anamna only receives; nothing from your record is sent back."
        ),
        "uk": (
            "Пов'яжіть обліковий запис вашого годинника чи каблучки, і його виміри - сон, "
            "пульс, активність - надходитимуть сюди самі, зазвичай за кілька хвилин після "
            "синхронізації пристрою. Anamna лише отримує дані; нічого з вашого запису "
            "не надсилається у відповідь."
        ),
    },
    "integrations.connected": {"en": "Connected", "uk": "Підключено"},
    "integrations.not_connected": {"en": "Not connected", "uk": "Не підключено"},
    "integrations.connected_since": {"en": "Connected on {date}.", "uk": "Підключено {date}."},
    "integrations.connect": {"en": "Connect {provider}", "uk": "Підключити {provider}"},
    "integrations.connect_hint": {
        "en": (
            "You will be taken to {provider} to sign in and approve sharing; "
            "then you come straight back here."
        ),
        "uk": (
            "Вас переспрямує на сайт {provider}, щоб увійти й схвалити передавання даних; "
            "після цього ви повернетеся сюди."
        ),
    },
    "integrations.disconnect": {"en": "Disconnect", "uk": "Відключити"},
    "integrations.disconnect_hint": {
        "en": (
            "Deletes the access keys stored here and asks {provider} to withdraw this "
            "app's access. Data already received stays."
        ),
        "uk": (
            "Видаляє збережені тут ключі доступу й просить {provider} відкликати доступ "
            "цього застосунку. Уже отримані дані залишаються."
        ),
    },
    "integrations.garmin_desc": {
        "en": (
            "Daily activity, sleep, heart rate, stress, body composition, blood pressure and "
            "workouts from Garmin Connect, sent by Garmin after each device sync."
        ),
        "uk": (
            "Щоденна активність, сон, пульс, стрес, склад тіла, артеріальний тиск і тренування "
            "з Garmin Connect - Garmin надсилає їх після кожної синхронізації пристрою."
        ),
    },
    "integrations.oura_desc": {
        "en": (
            "Sleep, readiness, heart rate and activity from the Oura ring, sent by Oura "
            "shortly after the ring syncs with its app."
        ),
        "uk": (
            "Сон, готовність, пульс і активність з каблучки Oura - Oura надсилає їх "
            "невдовзі після синхронізації каблучки із застосунком."
        ),
    },
    "integrations.saved_connected": {
        "en": "Account linked. New measurements will appear as the provider sends them.",
        "uk": "Обліковий запис підключено. Нові вимірювання з’являтимуться, щойно сервіс їх надішле.",
    },
    "integrations.saved_disconnected": {
        "en": "Disconnected: the access keys stored here were deleted.",
        "uk": "Відключено. Збережені тут ключі доступу видалено.",
    },
    "integrations.saved_sync": {
        "en": "Sync started: new measurements appear on the devices pages as they arrive.",
        "uk": "Синхронізацію запущено. Нові вимірювання з’являтимуться на сторінках пристроїв, щойно надійдуть.",
    },
    "integrations.reauthorize": {
        "en": "{provider} stopped accepting our access keys, so nothing new can arrive. Connect again to resume. The data already here is untouched.",
        "uk": "{provider} більше не приймає наші ключі доступу, тому нові дані не надходять. Підключіть сервіс знову, щоб відновити синхронізацію. Наявні дані залишаться без змін.",
    },
    "integrations.data_label": {"en": "Received data", "uk": "Отримано"},
    "integrations.data_hint": {
        "en": "Days with at least one measurement from this account, on the devices pages.",
        "uk": "Дні, що мають хоча б один вимір із цього облікового запису, на сторінках пристроїв.",
    },
    "integrations.data_days": {"en": "{count} days of measurements", "uk": "Днів із вимірюваннями: {count}"},
    "integrations.data_days_one": {"en": "{count} day of measurements", "uk": "{count} день вимірювань"},
    "integrations.data_days_few": {"en": "{count} days of measurements", "uk": "{count} дні вимірювань"},
    "integrations.data_days_many": {"en": "{count} days of measurements", "uk": "{count} днів вимірювань"},
    "integrations.data_latest": {"en": "newest {date}", "uk": "останні за {date}"},
    "integrations.webhooks_label": {"en": "Automatic updates", "uk": "Автоматичні оновлення"},
    "integrations.webhooks_hint": {
        "en": "Whether the provider pushes new measurements to this server on its own; without it, use \"Sync now\".",
        "uk": "Чи надсилає провайдер нові виміри на цей сервер самостійно; якщо ні - користуйтеся «Синхронізувати зараз».",
    },
    "integrations.webhooks_on": {"en": "On: new data arrives by itself", "uk": "Увімкнено: нові дані надходять самі"},
    "integrations.webhooks_off": {
        "en": "Off: this server has no public address the provider can reach",
        "uk": "Вимкнено: сервіс не може достукатися до цього сервера, бо в нього немає публічної адреси",
    },
    "integrations.ring_label": {"en": "Ring", "uk": "Каблучка"},
    "integrations.ring_hint": {
        "en": "The device model as the provider reports it, with its firmware.",
        "uk": "Модель пристрою, як її повідомляє провайдер, та її прошивка.",
    },
    "integrations.ring_size": {"en": "size {size}", "uk": "розмір {size}"},
    "integrations.backfill_running": {
        "en": "History is still being fetched in the background. Reload this page to watch the day count grow.",
        "uk": "Історія ще завантажується у фоні. Оновіть сторінку, щоб побачити, як зростає кількість днів.",
    },
    "integrations.sync_action": {"en": "Sync now", "uk": "Синхронізувати зараз"},
    "integrations.sync_hint": {
        "en": "Refetches the last 30 days of every dataset and checks the automatic updates. Runs in the background.",
        "uk": "Повторно отримує останні 30 днів усіх наборів даних і перевіряє автоматичні оновлення. Працює у фоні.",
    },
    "integrations.working": {"en": "Working...", "uk": "Зачекайте..."},
    "integrations.error_denied": {
        "en": "Linking was cancelled on the provider's page, so nothing was connected.",
        "uk": "Підключення скасовано на сторінці сервісу, тому нічого не підключено.",
    },
    "integrations.error_state": {
        "en": "That sign-in attempt expired or was already used. Press Connect and try again.",
        "uk": "Ця спроба входу застаріла або вже використана. Натисніть «Підключити» і спробуйте ще раз.",
    },
    "integrations.error_exchange": {
        "en": "The provider did not complete the connection. Try again in a moment.",
        "uk": "Сервіс не завершив підключення. Спробуйте ще раз трохи згодом.",
    },
    # Garmin business tier (OAuth + push): extra facts on its provider card.
    "integrations.garmin_delivery_label": {"en": "Last delivery from Garmin", "uk": "Останнє надходження від Garmin"},
    "integrations.garmin_delivery_hint": {
        "en": "Garmin sends new data to this server by itself after each device sync; there is no button that can ask it sooner.",
        "uk": "Garmin сам надсилає нові дані на цей сервер після кожної синхронізації пристрою; кнопки, яка попросила б раніше, немає.",
    },
    "integrations.garmin_delivery_never": {"en": "nothing delivered yet", "uk": "ще нічого не надійшло"},
    "integrations.garmin_permissions_label": {"en": "Shared with this record", "uk": "Доступ до даних"},
    "integrations.garmin_permissions_hint": {
        "en": "What you allowed on Garmin's consent screen. Change it in Garmin Connect > Settings > Connected apps; withdrawn data is deleted here.",
        "uk": "Те, що ви дозволили на сторінці згоди Garmin. Змінити можна в Garmin Connect > Налаштування > Підключені застосунки; дані, доступ до яких відкликано, тут видаляються.",
    },
    "integrations.garmin_permission_health_export": {
        "en": "Health data: daily activity, sleep, heart, stress, body composition",
        "uk": "Здоров’я: денна активність, сон, серце, стрес, склад тіла",
    },
    "integrations.garmin_permission_activity_export": {"en": "Workouts", "uk": "Тренування"},
    "integrations.garmin_permission_mct_export": {
        "en": "Women's health: menstrual cycle tracking",
        "uk": "Жіноче здоров’я: менструальний цикл",
    },
    "integrations.garmin_permission_on": {"en": "shared", "uk": "надано"},
    "integrations.garmin_permission_off": {"en": "not shared", "uk": "не надано"},
    "integrations.garmin_backfill_label": {"en": "History", "uk": "Історія"},
    "integrations.garmin_backfill_hint": {
        "en": "Garmin replays only about the last month, once, and only for Enterprise-tier access.",
        "uk": "Garmin надсилає дані лише приблизно за останній місяць, один раз і тільки для доступу рівня Enterprise.",
    },
    "integrations.garmin_backfill_running": {
        "en": "requesting the last month from Garmin...",
        "uk": "запитуємо в Garmin дані за останній місяць...",
    },
    "integrations.garmin_backfill_done": {
        "en": "the last month was requested; Garmin delivers it over the next hours",
        "uk": "дані за останній місяць запитано, Garmin надішле їх протягом кількох годин",
    },
    "integrations.garmin_backfill_unavailable": {
        "en": "not offered for this access tier. Data starts from the day you connected",
        "uk": "недоступна для цього рівня доступу. Дані будуть із дня підключення",
    },
    "integrations.garmin_sync_action": {"en": "Check for new data", "uk": "Перевірити нові дані"},
    "integrations.garmin_sync_hint": {
        "en": "Processes anything Garmin delivered and retries a history request that did not go through. Garmin decides when new data is sent.",
        "uk": "Обробляє все, що доставив Garmin, і повторює запит історії, який не вдався. Коли надсилати нові дані, вирішує Garmin.",
    },
    "integrations.garmin_disconnect_hint": {
        "en": "Also deletes the data Garmin delivered, as Garmin's terms require. Data from a Garmin export file stays.",
        "uk": "Також видаляє дані, отримані від Garmin, як того вимагають умови Garmin. Дані з файлу експорту Garmin залишаться.",
    },
    # Garmin Personal API: each person's own key, pasted on the profile.
    "integrations.garmin_personal_heading": {"en": "Garmin Connect: personal key", "uk": "Garmin Connect: особистий ключ"},
    "integrations.garmin_personal_lead": {
        "en": (
            "Garmin lets you create a read-only key for your own account. Paste it here and this "
            "record reads your Garmin data on its own every few hours. Scale weight and body "
            "composition, daily activity, sleep, heart-rate variability (HRV), Body Battery, "
            "stress, fitness age and workouts."
        ),
        "uk": (
            "Garmin дозволяє створити ключ лише для читання вашого власного облікового запису. "
            "Вставте його тут, і цей запис сам кожні кілька годин читатиме ваші дані Garmin - вагу "
            "й склад тіла з ваг, денну активність, сон, варіабельність серцевого ритму (ВСР), "
            "Body Battery, стрес, фітнес-вік і тренування."
        ),
    },
    "integrations.garmin_personal_how": {
        "en": "Create it in Garmin Connect on the web: Settings > Personal API (connect.garmin.com/app/settings/personalApiToken).",
        "uk": (
            "Створіть його у вебверсії Garmin Connect: Settings > Personal API (connect.garmin.com/app/settings/personalApiToken)."
        ),
    },
    "integrations.garmin_key_label": {"en": "Personal API key", "uk": "Ключ Personal API"},
    "integrations.garmin_key_needed": {"en": "New key needed", "uk": "Потрібен новий ключ"},
    "integrations.garmin_key_hint": {
        "en": "Starts with GCDC_.",
        "uk": "Починається з GCDC_.",
    },
    "integrations.garmin_key_save": {"en": "Save key and read history", "uk": "Зберегти ключ і завантажити історію"},
    "integrations.garmin_key_replace": {"en": "Save new key", "uk": "Зберегти новий ключ"},
    "integrations.garmin_key_expired": {
        "en": "Garmin no longer accepts the stored key. It expired or was deleted in Garmin Connect. Paste a new key to resume; the data already here is untouched.",
        "uk": "Garmin більше не приймає збережений ключ: строк його дії минув або його видалили в Garmin Connect. Вставте новий ключ, щоб відновити синхронізацію. Наявні дані залишаться без змін.",
    },
    "integrations.garmin_personal_last_sync_label": {"en": "Last read", "uk": "Остання синхронізація"},
    "integrations.garmin_personal_last_sync_hint": {
        "en": "A personal key cannot receive pushes, so this record reads the last 30 days every six hours.",
        "uk": "Особистий ключ не отримує push-сповіщень, тож цей запис читає останні 30 днів кожні шість годин.",
    },
    "integrations.garmin_personal_no_wellness": {
        "en": "Garmin holds no daily wellness data for this account, no watch or tracker has synced to it, so only scale readings, fitness age and workouts can arrive.",
        "uk": "Garmin не має щоденних даних про здоров’я для цього облікового запису: з ним не синхронізувався жоден годинник чи трекер. Тож надходитимуть лише вимірювання з ваг, фітнес-вік і тренування.",
    },
    "integrations.garmin_personal_limits": {
        "en": "Not available through a personal key: blood pressure, VO₂ max and skin temperature. Import the Garmin data export (Devices > Import) for blood pressure.",
        "uk": "Через особистий ключ недоступні: артеріальний тиск, VO₂ max і температура шкіри. Для тиску імпортуйте експорт даних Garmin (Пристрої > Імпорт).",
    },
    "integrations.garmin_personal_failures": {
        "en": "Could not be read on the last sync: {datasets}. The next sync retries.",
        "uk": "Під час останньої синхронізації не вдалося отримати: {datasets}. Наступна синхронізація спробує ще раз.",
    },
    "integrations.garmin_dataset_daily": {"en": "daily activity", "uk": "денна активність"},
    "integrations.garmin_dataset_sleep": {"en": "sleep", "uk": "сон"},
    "integrations.garmin_dataset_hrv": {"en": "heart-rate variability", "uk": "варіабельність серцевого ритму"},
    "integrations.garmin_dataset_weight": {"en": "weight and body composition", "uk": "вага й склад тіла"},
    "integrations.garmin_dataset_activities": {"en": "workouts", "uk": "тренування"},
    "integrations.garmin_dataset_fitness_age": {"en": "fitness age", "uk": "фітнес-вік"},
    "integrations.garmin_personal_sync_hint": {
        "en": "Reads the last 30 days of every dataset now instead of waiting for the next scheduled read.",
        "uk": "Читає останні 30 днів усіх наборів даних зараз, не чекаючи наступного планового читання.",
    },
    "integrations.garmin_key_remove": {"en": "Remove key", "uk": "Видалити ключ"},
    "integrations.garmin_key_remove_hint": {
        "en": "Stops reading from Garmin. Data already received stays in your record. To revoke the key itself, delete it in Garmin Connect.",
        "uk": "Припиняє читання з Garmin. Уже отримані дані залишаються у вашому записі. Щоб відкликати сам ключ, видаліть його в Garmin Connect.",
    },
    "integrations.saved_garmin_key": {
        "en": "Garmin key saved. Your history is being read in the background. Reload in a minute to see the day count.",
        "uk": "Ключ Garmin збережено. Історія завантажується у фоні. Оновіть сторінку за хвилину, щоб побачити кількість днів.",
    },
    "integrations.saved_garmin_key_removed": {
        "en": "Garmin key removed. Data already received stays in your record.",
        "uk": "Ключ Garmin видалено. Уже отримані дані залишаються у вашій картці.",
    },
    "integrations.error_garmin_key": {
        "en": "That does not look like a Garmin personal API key. It starts with GCDC_ and has no spaces. Nothing was saved.",
        "uk": "Це не схоже на особистий ключ Garmin API. Він починається з GCDC_ і не містить пробілів. Нічого не збережено.",
    },
    "integrations.error_garmin_key_refused": {
        "en": "Garmin refused this key. It may have expired or been deleted. Create a new one in Garmin Connect and paste it again. Nothing was saved.",
        "uk": "Garmin не прийняв цей ключ. Можливо, строк його дії минув або його видалили. Створіть новий ключ у Garmin Connect і вставте його ще раз. Нічого не збережено.",
    },
    "integrations.error_garmin_unreachable": {
        "en": "Garmin could not be reached to check the key. Nothing was saved: try again in a few minutes.",
        "uk": "Не вдалося зв’язатися з Garmin, щоб перевірити ключ. Нічого не збережено. Спробуйте за кілька хвилин.",
    },
    # --- OpenWearables: a self-hosted aggregation server ----------------------
    # Admin family (the operator names the server and holds its key) followed by
    # the profile card family (each person links their own account on it).
    "nav.admin_openwearables": {"en": "OpenWearables", "uk": "OpenWearables"},
    "openwearables.admin_title": {
        "en": "OpenWearables: administration",
        "uk": "OpenWearables: адміністрування",
    },
    "openwearables.admin_heading": {"en": "OpenWearables server", "uk": "Сервер OpenWearables"},
    "openwearables.admin_lead": {
        "en": (
            "OpenWearables is a server you run yourself. It collects measurements from the "
            "services a phone already writes to, Apple Health, Oura, Garmin, Zepp Life, and "
            "re-serves them as daily summaries, so device data keeps arriving here without "
            "anyone remembering to export a file. The address and API key below belong to this "
            "instance; each person then links their own account on that server under "
            "Profile > Connections, and nobody but you ever sees the key."
        ),
        "uk": (
            "OpenWearables - це сервер, який ви розгортаєте самі. Він збирає виміри із сервісів, "
            "куди вже пише телефон - Apple Health, Oura, Garmin, Zepp Life, і віддає їх як "
            "щоденні зведення, тож дані з пристроїв надходять сюди без ручного експорту файлів. "
            "Адреса та ключ API нижче належать усьому застосунку; кожна людина потім пов'язує "
            "власний обліковий запис на тому сервері в розділі Профіль > З'єднання, а ключ "
            "бачите лише ви."
        ),
    },
    "openwearables.status_eyebrow": {"en": "Status", "uk": "Стан"},
    "openwearables.status_heading": {"en": "Current state", "uk": "Поточний стан"},
    "openwearables.on": {"en": "enabled", "uk": "увімкнено"},
    "openwearables.off": {"en": "switched off", "uk": "вимкнено"},
    "openwearables.incomplete": {
        "en": "no server address or key",
        "uk": "немає адреси сервера або ключа",
    },
    "openwearables.status_url": {"en": "Server address", "uk": "Адреса сервера"},
    "openwearables.url_missing": {"en": "not set", "uk": "не вказано"},
    "openwearables.status_key": {"en": "API key", "uk": "Ключ API"},
    "openwearables.status_key_hint": {
        "en": "Only its last characters are shown; the key itself is never displayed again.",
        "uk": "Показано лише останні символи; сам ключ більше ніколи не відображається.",
    },
    "openwearables.key_missing": {"en": "not stored", "uk": "не збережено"},
    "openwearables.key_tail": {"en": "stored, ends with {tail}", "uk": "збережено, закінчується на {tail}"},
    "openwearables.status_linked": {"en": "Accounts linked", "uk": "Підключені облікові записи"},
    "openwearables.status_linked_hint": {
        "en": "People here who picked their account on that server.",
        "uk": "Люди тут, які обрали свій обліковий запис на тому сервері.",
    },
    "openwearables.working": {"en": "Checking...", "uk": "Перевірка..."},
    "openwearables.test_action": {"en": "Test the connection", "uk": "Перевірити з’єднання"},
    "openwearables.admin_test_note": {
        "en": (
            "One real request with the stored key, so \"saved\" and \"working\" stay different "
            "claims. It works before the feature is switched on, which is the order this is "
            "usually set up in."
        ),
        "uk": (
            "Один справжній запит зі збереженим ключем, щоб «збережено» і «працює» лишалися "
            "різними твердженнями. Працює ще до ввімкнення функції - саме в такому порядку це "
            "зазвичай і налаштовують."
        ),
    },
    "openwearables.settings_eyebrow": {"en": "Settings", "uk": "Налаштування"},
    "openwearables.settings_heading": {"en": "Configuration", "uk": "Параметри"},
    "openwearables.settings_lead": {
        "en": (
            "The address of the OpenWearables server and the API key it issues. Both are needed "
            "before anyone can link an account; leave either empty to keep the feature dormant."
        ),
        "uk": (
            "Адреса сервера OpenWearables і виданий ним ключ API. Потрібні обидва, перш ніж "
            "хтось зможе пов'язати обліковий запис; залиште будь-яке поле порожнім, щоб функція "
            "лишалася неактивною."
        ),
    },
    "openwearables.enable_label": {
        "en": "Enable the OpenWearables integration",
        "uk": "Увімкнути OpenWearables",
    },
    "openwearables.url_label": {"en": "Server address", "uk": "Адреса сервера"},
    "openwearables.url_hint": {
        "en": "Starts with http:// or https://, without /api/v1.",
        "uk": (
            "Починається з http:// або https://, без /api/v1."
        ),
    },
    "openwearables.key_label": {"en": "API key", "uk": "Ключ API"},
    "openwearables.key_hint": {
        "en": "Issued by the OpenWearables server. Leave blank to keep the saved one.",
        "uk": (
            "Видає сервер OpenWearables. Залиште порожнім, щоб зберегти поточний."
        ),
    },
    "openwearables.clear_key": {"en": "Forget the stored key", "uk": "Забути збережений ключ"},
    "openwearables.url_change_warning": {
        "en": "Changing the address unlinks every account; measurements already received stay.",
        "uk": (
            "Якщо змінити адресу, усі облікові записи буде відключено. Уже отримані вимірювання залишаться."
        ),
    },
    "openwearables.save": {"en": "Save settings", "uk": "Зберегти налаштування"},
    "openwearables.done_saved": {"en": "Settings saved.", "uk": "Налаштування збережено."},
    "openwearables.done_saved_relink": {
        "en": (
            "Settings saved. The server address changed, so every linked account was unlinked. "
            "each person picks their account on the new server again under Profile > "
            "Connections. Measurements already received were kept."
        ),
        "uk": (
            "Налаштування збережено. Адреса сервера змінилася, тому всі облікові записи відключено. Кожен користувач має знову вибрати свій обліковий запис на новому сервері в розділі Профіль > З’єднання. Уже отримані вимірювання збережено."
        ),
    },
    "openwearables.done_test_ok": {
        "en": "The server answered and accepted the key. It holds {count} accounts.",
        "uk": "Сервер відповів і прийняв ключ. Облікових записів на ньому: {count}.",
    },
    "openwearables.done_test_ok_one": {
        "en": "The server answered and accepted the key. It holds {count} account.",
        "uk": "Сервер відповів і прийняв ключ. На ньому {count} обліковий запис.",
    },
    "openwearables.done_test_ok_few": {
        "en": "The server answered and accepted the key. It holds {count} accounts.",
        "uk": "Сервер відповів і прийняв ключ. На ньому {count} облікові записи.",
    },
    "openwearables.done_test_ok_many": {
        "en": "The server answered and accepted the key. It holds {count} accounts.",
        "uk": "Сервер відповів і прийняв ключ. На ньому {count} облікових записів.",
    },
    "openwearables.error_url": {
        "en": "Both a server address starting with http:// or https:// and an API key are needed.",
        "uk": "Вкажіть адресу сервера, що починається з http:// або https://, і ключ API.",
    },
    "openwearables.error_unauthorized": {
        "en": "The server answered but refused the key. Check that it is current and complete.",
        "uk": "Сервер відповів, але не прийняв ключ. Перевірте, чи ключ чинний і чи скопійовано його повністю.",
    },
    "openwearables.error_unreachable": {
        "en": "No answer from the OpenWearables server. Check the address and that it is running.",
        "uk": "Сервер OpenWearables не відповідає. Перевірте адресу і чи запущено сервер.",
    },
    # Profile — the person's own link to that server.
    "openwearables.eyebrow": {"en": "Data sources", "uk": "Джерела даних"},
    "openwearables.heading": {"en": "OpenWearables server", "uk": "Сервер OpenWearables"},
    "openwearables.linked": {"en": "Linked", "uk": "Підключено"},
    "openwearables.not_linked": {"en": "Not linked", "uk": "Не пов'язано"},
    "openwearables.lead": {
        "en": (
            "OpenWearables is a server this household runs that gathers what your phone already "
            "records, steps, sleep, heart rate, workouts, body measurements, from Apple "
            "Health, Oura, Garmin and the rest, in one place. Link your account on it and those "
            "measurements arrive here on their own, instead of waiting for the next manual "
            "export."
        ),
        "uk": (
            "OpenWearables - це сервер, який працює у вашому домі й збирає в одному місці те, що "
            "вже записує ваш телефон - кроки, сон, пульс, тренування, виміри тіла, з Apple "
            "Health, Oura, Garmin та інших джерел. Пов'яжіть свій обліковий запис на ньому, і ці "
            "виміри надходитимуть сюди самі, а не чекатимуть наступного ручного експорту."
        ),
    },
    "openwearables.merge_hint": {
        "en": (
            "Original imports remain available for comparison. The timeline selects one source "
            "per day using your preference and the device identity. Sleep duration and stages "
            "stay together from one source; overlapping recordings are never added."
        ),
        "uk": (
            "Початкові імпорти доступні для порівняння. Часова шкала обирає одне джерело "
            "на день з урахуванням ваших налаштувань і пристрою. Тривалість і фази сну "
            "залишаються разом з одного джерела; записи, що перекриваються, не додаються."
        ),
    },
    "openwearables.pick_label": {
        "en": "Your account on that server",
        "uk": "Ваш обліковий запис на цьому сервері",
    },
    "openwearables.pick_hint": {
        "en": (
            "The server holds an account per person. Pick your own: the one with your email "
            "address is preselected. Only that account's measurements are ever read."
        ),
        "uk": (
            "Сервер зберігає окремий обліковий запис для кожної людини. Оберіть свій - той, що з "
            "вашою адресою пошти, обрано наперед. Читаються виміри лише цього облікового запису."
        ),
    },
    "openwearables.link_action": {"en": "Link this account", "uk": "Підключити цей обліковий запис"},
    "openwearables.link_hint": {
        "en": (
            "Linking fetches the account's whole history once, in the background, then keeps the "
            "recent days up to date. Reload this page to watch the day count grow."
        ),
        "uk": (
            "Пов'язування один раз завантажує всю історію облікового запису у фоні, а далі "
            "підтримує актуальність останніх днів. Перезавантажте сторінку, щоб бачити, як "
            "росте кількість днів."
        ),
    },
    "openwearables.no_accounts": {
        "en": "That server holds no accounts yet. Create yours on it first, then come back.",
        "uk": (
            "На цьому сервері ще немає облікових записів. Спершу створіть там свій, а потім поверніться сюди."
        ),
    },
    "openwearables.unreachable": {
        "en": "The OpenWearables server is not answering right now",
        "uk": "Сервер OpenWearables зараз не відповідає",
    },
    "openwearables.unreachable_hint": {
        "en": "Try again when the server is back.",
        "uk": (
            "Спробуйте ще раз, коли сервер знову запрацює."
        ),
    },
    "openwearables.account_label": {"en": "Linked account", "uk": "Підключений обліковий запис"},
    "openwearables.account_hint": {
        "en": "The account on that server whose measurements are read into this record.",
        "uk": "Обліковий запис на тому сервері, виміри якого читаються в цей запис.",
    },
    "openwearables.last_sync_label": {"en": "Last checked", "uk": "Остання перевірка"},
    "openwearables.last_sync_hint": {
        "en": (
            "Background checks fetch the last three days twice a day and recheck the past "
            "month once a month. Sync now queues an additional check of the last 30 days "
            "for your account."
        ),
        "uk": (
            "Фонові перевірки двічі на добу отримують дані за останні три дні, а раз на "
            "місяць повторно перевіряють минулий місяць. «Синхронізувати зараз» додає "
            "перевірку останніх 30 днів вашого облікового запису."
        ),
    },
    "openwearables.last_sync_never": {"en": "not yet", "uk": "ще не було"},
    "openwearables.failures_label": {
        "en": "Not arriving on the last sync: {datasets}",
        "uk": "Не надійшло під час останньої синхронізації: {datasets}",
    },
    "openwearables.failures_hint": {
        "en": "Will retry on the next sync.",
        "uk": (
            "Повторимо під час наступної синхронізації."
        ),
    },
    "openwearables.sync_action": {"en": "Sync now", "uk": "Синхронізувати зараз"},
    "openwearables.sync_hint": {
        "en": "Refetches the last 30 days of every dataset, in the background.",
        "uk": "Повторно отримує останні 30 днів усіх наборів даних у фоні.",
    },
    "openwearables.unlink_action": {"en": "Unlink", "uk": "Відключити"},
    "openwearables.unlink_hint": {
        "en": (
            "Stops collecting new days. Every measurement already received stays in your record, "
            "and linking the same account again resumes where it left off."
        ),
        "uk": (
            "Припиняє збирання нових днів. Усі вже отримані виміри лишаються у вашому записі, а "
            "повторне пов'язування того самого облікового запису відновить синхронізацію з "
            "того ж місця."
        ),
    },
    "openwearables.saved_linked": {
        "en": "Account linked. The full history is being fetched in the background. Reload to watch it arrive.",
        "uk": "Обліковий запис підключено. Уся історія завантажується у фоні. Оновлюйте сторінку, щоб бачити, як надходять дані.",
    },
    "openwearables.saved_replaced": {
        "en": (
            "Account linked. It replaced a different account, so everything the previous link "
            "had synced was deleted. Those were another person's measurements. The new "
            "account's history is being fetched now; measurements from your own file imports "
            "and other connected services were untouched."
        ),
        "uk": (
            "Обліковий запис підключено замість іншого, тому все, що синхронізувалося через попередній, видалено: це були вимірювання іншої людини. Зараз завантажуємо історію нового облікового запису. Вимірювання з ваших файлів та інших підключених сервісів залишилися без змін."
        ),
    },
    "openwearables.saved_unlinked": {
        "en": "Unlinked: no new days will be collected. Everything already received stays in your record.",
        "uk": "Відключено. Нові дні більше не надходитимуть. Усе, що вже отримано, залишається у вашій картці.",
    },
    "openwearables.saved_sync": {
        "en": "Sync started: new measurements appear on the devices pages as they arrive.",
        "uk": "Синхронізацію запущено. Нові вимірювання з’являтимуться на сторінках пристроїв, щойно надійдуть.",
    },
    "openwearables.error_user": {
        "en": "That account is not on the server's list any more. Reload the page and pick again.",
        "uk": "Цього облікового запису вже немає в списку сервера. Оновіть сторінку і виберіть ще раз.",
    },
    "openwearables.error_taken": {
        "en": "That OpenWearables account is already linked to another person's record here.",
        "uk": "Цей обліковий запис OpenWearables уже під’єднано до картки іншої людини.",
    },
    "openwearables.error_not_yours": {
        "en": "You can link only the OpenWearables account that uses your own email address.",
        "uk": "Під’єднати можна лише обліковий запис OpenWearables із вашою власною адресою.",
    },
    "openwearables.none_for_you": {
        "en": "No account on the OpenWearables server uses your email address ({email}). Ask the person who runs the server to create one with this address.",
        "uk": "На сервері OpenWearables немає облікового запису з вашою адресою ({email}). Попросіть адміністратора сервера створити обліковий запис із цією адресою.",
    },
    # Devices page disclosure.
    "openwearables.devices_failures": {
        "en": "Some OpenWearables data is not arriving",
        "uk": "Частина даних OpenWearables не надходить",
    },
    "openwearables.devices_failures_hint": {
        "en": (
            "These datasets failed on the last sync, with the message the OpenWearables server "
            "returned shown as received. They are retried on the next sync; if an error "
            "persists, check the server from your profile."
        ),
        "uk": (
            "Ці набори даних не вдалося отримати під час останньої синхронізації. Повідомлення сервера OpenWearables наведено без змін. Наступна синхронізація спробує ще раз. Якщо помилка повторюється, перевірте сервер у профілі."
        ),
    },
    "openwearables.devices_last_sync": {
        "en": "OpenWearables last completed a data check on {date}. Background checks repeat twice a day.",
        "uk": "Остання перевірка даних OpenWearables завершилася {date}. У фоні перевірка відбувається двічі на добу.",
    },
    "openwearables.devices_last_sync_never": {
        "en": "OpenWearables is linked but has not collected anything yet. The first fetch runs in the background.",
        "uk": "OpenWearables підключено, але дані ще не надходили. Перше завантаження вже триває у фоні.",
    },
    # Documents pages.
    "paperless.search_note": {
        "en": "Search also covers the full text your Paperless copies were read with.",
        "uk": "Пошук охоплює й повний текст, з яким прочитано ваші копії в Paperless.",
    },
    "paperless.doc_label": {"en": "Paperless", "uk": "Paperless"},
    "paperless.doc_hint": {
        "en": "The copy of this file in your Paperless archive.",
        "uk": "Копія цього файлу у вашому архіві Paperless.",
    },
    "paperless.doc_open": {"en": "Open in Paperless", "uk": "Відкрити в Paperless"},
    "paperless.doc_pending": {
        "en": "Sent; Paperless is still reading it.",
        "uk": "Надіслано. Paperless ще опрацьовує документ.",
    },

    # Legal pages. Public — API providers verify these signed out, so the
    # routes sit outside require_user and the strings assume no session.
    "nav.privacy": {"en": "Privacy policy", "uk": "Політика конфіденційності"},
    "nav.terms": {"en": "Terms of service", "uk": "Умови користування"},
    "legal.eyebrow": {"en": "Legal", "uk": "Правова інформація"},
    "legal.updated": {
        "en": "Last updated: 6 August 2026",
        "uk": "Оновлено 6 серпня 2026 року",
    },

    "privacy.title": {
        "en": "Privacy policy · Anamna",
        "uk": "Політика конфіденційності · Anamna",
    },
    "privacy.heading": {"en": "Privacy policy", "uk": "Політика конфіденційності"},
    "privacy.lead": {
        "en": "Anamna is a personal, self-hosted medical record. This page explains what the service stores, why, and what never happens to your data.",
        "uk": "Anamna працює як особиста медична картка на власному сервері. Тут пояснено, що саме зберігає сервіс, навіщо і чого з вашими даними не стається ніколи.",
    },
    "privacy.s1_title": {"en": "Who runs this service", "uk": "Хто керує сервісом"},
    "privacy.s1_body": {
        "en": "This is a single, self-hosted installation of Anamna, run privately by its owner for personal and family use. It is not a commercial product: it has no customers and serves no advertising. Questions about this installation and the data it holds go to its operator.",
        "uk": "Це окрема інсталяція Anamna: власник сам розгорнув її на своєму сервері й користується нею приватно, для себе та родини. Це не комерційний продукт: тут немає клієнтів і реклами. З питаннями про цю інсталяцію та дані в ній звертайтеся до її оператора.",
    },
    "privacy.s2_title": {"en": "What we store", "uk": "Що ми зберігаємо"},
    "privacy.s2_body": {
        "en": "Your account: e-mail address, display name and a hash of your password. The password itself is never stored. Your patient profile: name, sex at birth and date of birth, used only to pick the correct reference intervals. Your health record: the documents you upload (kept unchanged as source files), the values extracted from them, and measurements from devices you import. Access tokens you create are stored only as SHA-256 hashes.",
        "uk": "Обліковий запис: адреса електронної пошти, ім’я для показу та хеш пароля. Самого пароля ми ніколи не зберігаємо. Профіль пацієнта: ім’я, стать при народженні й дата народження. Вони потрібні лише для того, щоб добрати правильні референтні інтервали. Медична картка: документи, які ви завантажуєте (оригінали зберігаємо без змін), зчитані з них значення та вимірювання з пристроїв, дані яких ви імпортуєте. Токени доступу, які ви створюєте, зберігаємо лише як хеші SHA-256.",
    },
    "privacy.s3_title": {"en": "How your data is used", "uk": "Як ми використовуємо ваші дані"},
    "privacy.s3_body": {
        "en": "For one purpose: showing your own record back to you and to the people you explicitly share it with. Your data is never sold, never used for advertising, never used to train models, and never disclosed to anyone unless you share it yourself or the law requires it.",
        "uk": "Лише для одного: щоб показувати вашу картку вам і тим, кому ви явно надали доступ. Ми ніколи не продаємо ваші дані, не використовуємо їх для реклами чи навчання моделей і нікому їх не розкриваємо, хіба що ви поділилися ними самі або цього вимагає закон.",
    },
    "privacy.s4_title": {"en": "Cookies", "uk": "Файли cookie"},
    "privacy.s4_body": {
        "en": "Three cookies, all functional: a session cookie that keeps you signed in (HttpOnly, invisible to scripts), a language cookie and a theme cookie. There are no analytics, tracking or advertising cookies.",
        "uk": "Ми використовуємо три файли cookie, і всі вони функціональні: сесійний, завдяки якому ви залишаєтеся в системі (HttpOnly, скрипти його не бачать), cookie мови та cookie теми. Аналітичних, рекламних cookie чи cookie для стеження немає.",
    },
    "privacy.s5_title": {"en": "Third-party services", "uk": "Сторонні сервіси"},
    "privacy.s5_body": {
        "en": "Traffic to this site passes through Cloudflare, which provides the encrypted connection and caches static assets; like any web proxy it sees the traffic pass, but it has no access to your account. Two integrations exist and both stay off until you turn them on: the AI assistant sends the excerpts of your record you choose to a model provider only when you press its button, and the Paperless-ngx sync sends copies of your uploads to your own Paperless server only after you configure it.",
        "uk": "Трафік до сайту проходить через Cloudflare: він забезпечує шифроване з’єднання й кешує статичні файли. Як і будь-який вебпроксі, Cloudflare бачить трафік, що проходить через нього, але не має доступу до вашого облікового запису. Є дві інтеграції, і обидві вимкнені, доки ви їх не ввімкнете. ШІ-помічник надсилає постачальнику моделі вибрані вами фрагменти картки лише тоді, коли ви натискаєте його кнопку. Синхронізація з Paperless-ngx надсилає копії завантажених документів на ваш власний сервер Paperless лише після того, як ви її налаштуєте.",
    },
    "privacy.s6_title": {"en": "Sharing", "uk": "Спільний доступ"},
    "privacy.s6_body": {
        "en": "Nothing is visible to anyone else unless you share it: either with another account on this installation, or through a read-only guest link. Guest links always carry an expiry date and can be revoked at any moment, which also ends the sessions they opened.",
        "uk": "Ніхто інший нічого не бачить, доки ви самі не надасте доступ: іншому обліковому запису в цій інсталяції або через гостьове посилання лише для перегляду. Гостьове посилання завжди має термін дії, і його можна будь-коли відкликати. Тоді завершуються й усі сеанси, відкриті через нього.",
    },
    "privacy.s7_title": {"en": "Security", "uk": "Безпека"},
    "privacy.s7_body": {
        "en": "The record lives in a database on hardware the operator controls, not in a commercial cloud. Connections are encrypted, the session cookie is HttpOnly, passwords are stored as hashes, and access-token secrets are shown once and stored only as hashes.",
        "uk": "Картка зберігається в базі даних на обладнанні, яке контролює оператор, а не в комерційній хмарі. З’єднання зашифровані, сесійний cookie має позначку HttpOnly, паролі зберігаються як хеші, а секрет токена доступу показується один раз і зберігається лише як хеш.",
    },
    "privacy.s8_title": {"en": "Retention and deletion", "uk": "Зберігання та видалення"},
    "privacy.s8_body": {
        "en": "Your data is kept for as long as your account exists. This is a record-keeping service, so nothing expires on its own. Deleting your account deletes everything it owns: documents, extracted values, device data, shares and tokens. You can also ask the operator to delete specific items or the whole account for you.",
        "uk": "Ваші дані зберігаються, доки існує ваш обліковий запис. Це сервіс для ведення медичних записів, тож ніщо не зникає саме собою. Коли ви видаляєте обліковий запис, видаляється все, що йому належить: документи, зчитані значення, дані пристроїв, надані доступи й токени. Ви також можете попросити оператора видалити окремі записи або весь обліковий запис.",
    },
    "privacy.s9_title": {"en": "Your rights", "uk": "Ваші права"},
    "privacy.s9_body": {
        "en": "You can see everything the service holds about you on its own pages, download your original documents at any time, correct extracted values through review, and delete your data. Where data-protection law such as the GDPR applies, these are also your legal rights of access, rectification, erasure and portability. Exercise them by contacting the operator.",
        "uk": "На сторінках сервісу ви бачите все, що він про вас зберігає. Ви можете будь-коли зберегти на пристрій оригінали своїх документів, виправити зчитані значення під час звірки та видалити свої дані. Там, де діє законодавство про захист даних, як-от GDPR, це також ваші законні права на доступ, виправлення, стирання та перенесення даних. Щоб скористатися ними, зверніться до оператора.",
    },
    "privacy.s10_title": {"en": "Changes to this policy", "uk": "Зміни політики"},
    "privacy.s10_body": {
        "en": "If this policy changes, the new text appears on this page with an updated date above.",
        "uk": "Якщо політика зміниться, ми опублікуємо новий текст на цій сторінці й оновимо дату вгорі.",
    },

    "terms.title": {
        "en": "Terms of service · Anamna",
        "uk": "Умови користування · Anamna",
    },
    "terms.heading": {"en": "Terms of service", "uk": "Умови користування"},
    "terms.lead": {
        "en": "The short version: this is a personal record-keeping tool, not a medical service. Use it honestly, keep your account safe, and always confirm anything important with a clinician.",
        "uk": "Коротко: це особистий інструмент для ведення медичних записів, а не медичний сервіс. Користуйтеся ним чесно, бережіть свій обліковий запис і все важливе обов’язково уточнюйте в лікаря.",
    },
    "terms.s1_title": {"en": "Acceptance", "uk": "Згода з умовами"},
    "terms.s1_body": {
        "en": "By creating an account or using this site you agree to these terms and to the privacy policy. If you do not agree, do not use the service.",
        "uk": "Створюючи обліковий запис або користуючись сайтом, ви погоджуєтеся з цими умовами та політикою конфіденційності. Якщо ви не згодні, не користуйтеся сервісом.",
    },
    "terms.s2_title": {"en": "What the service is", "uk": "Що це за сервіс"},
    "terms.s2_body": {
        "en": "Anamna stores your medical documents, extracts the values in them, and shows them alongside their sources and published reference intervals. It is a private, self-hosted installation run by its operator for personal use, offered as-is and free of charge.",
        "uk": "Anamna зберігає ваші медичні документи, зчитує з них значення й показує їх поруч із джерелами та опублікованими референтними інтервалами. Це приватна інсталяція на власному сервері: оператор веде її для особистого користування й надає «як є» та безоплатно.",
    },
    "terms.s3_title": {"en": "Not medical advice", "uk": "Це не медична порада"},
    "terms.s3_body": {
        "en": "Nothing here is a diagnosis, treatment advice or a substitute for clinical care. Extracted values start as automated readings and may be wrong until a person reviews them; reference intervals are general publications, not a judgement about you. Decisions about your health belong with a qualified clinician, and an emergency belongs with emergency services, not with this site.",
        "uk": "Тут немає діагнозів і порад щодо лікування, і сайт не замінює медичної допомоги. Зчитані значення спочатку отримано автоматично, і вони можуть бути хибними, доки їх не звірить людина. Референтні інтервали взято із загальних публікацій, це не висновок про вас. Рішення щодо вашого здоров’я має ухвалювати кваліфікований лікар, а з невідкладним станом звертайтеся до екстрених служб, а не до цього сайту.",
    },
    "terms.s4_title": {"en": "Your account", "uk": "Ваш обліковий запис"},
    "terms.s4_body": {
        "en": "Keep your password and access tokens to yourself; whatever happens under your credentials is treated as done by you. Tell the operator promptly if you believe your account has been compromised.",
        "uk": "Нікому не передавайте пароль і токени доступу: усе, що відбувається з використанням ваших облікових даних, вважається вашими діями. Якщо вважаєте, що ваш обліковий запис зламано, одразу повідомте оператора.",
    },
    "terms.s5_title": {"en": "Your content", "uk": "Ваші дані"},
    "terms.s5_body": {
        "en": "Documents and data you upload remain yours. You grant the service only what it needs to operate: storing them, reading values out of them, and showing them to you and to the accounts or guest links you share them with. Upload only records you have the right to hold. Your own, or those of someone you legitimately care for.",
        "uk": "Документи й дані, які ви завантажуєте, залишаються вашими. Сервісу ви дозволяєте лише те, що потрібно для роботи: зберігати їх, зчитувати з них значення й показувати їх вам, а також обліковим записам і гостьовим посиланням, яким ви надали доступ. Завантажуйте лише ті медичні документи, які маєте право зберігати: власні або людини, про яку ви законно піклуєтеся.",
    },
    "terms.s6_title": {"en": "Acceptable use", "uk": "Правила користування"},
    "terms.s6_body": {
        "en": "Do not attempt to access records that were not shared with you, probe or overload the service, upload malicious content, or use the service for anything unlawful.",
        "uk": "Не намагайтеся отримати доступ до записів, якими з вами не поділилися, шукати в сервісі вразливості чи перевантажувати його, завантажувати шкідливі файли або використовувати сервіс для будь-чого незаконного.",
    },
    "terms.s7_title": {"en": "No warranty", "uk": "Без гарантій"},
    "terms.s7_body": {
        "en": "The service is provided \"as is\" and \"as available\", without warranties of any kind. It is a personal project: it may be unavailable, may change, and may contain errors. Keep your original documents. The source files you upload are stored faithfully, but this site should not be your only copy.",
        "uk": "Сервіс надається «як є» і «в міру доступності», без жодних гарантій. Це особистий проєкт: він може бути недоступним, змінюватися й містити помилки. Зберігайте оригінали документів. Завантажені файли зберігаються без змін, але цей сайт не має бути вашою єдиною копією.",
    },
    "terms.s8_title": {"en": "Limitation of liability", "uk": "Обмеження відповідальності"},
    "terms.s8_body": {
        "en": "To the maximum extent permitted by applicable law, the operator is not liable for damages arising from the use of, or inability to use, this service, including decisions made on the basis of information it shows. Nothing in these terms excludes liability that cannot be excluded by law.",
        "uk": "У межах, які максимально дозволяє чинне законодавство, оператор не відповідає за збитки, що виникли через використання сервісу або неможливість ним скористатися, зокрема через рішення, ухвалені на основі інформації, яку він показує. Ніщо в цих умовах не звільняє від відповідальності, від якої закон не дозволяє звільнити.",
    },
    "terms.s9_title": {"en": "Ending the relationship", "uk": "Припинення користування"},
    "terms.s9_body": {
        "en": "You may stop using the service and delete your account at any time; deletion removes everything the account owns. The operator may suspend or close an account that breaks these terms, after which the same deletion applies.",
        "uk": "Ви можете будь-коли припинити користуватися сервісом і видалити обліковий запис: разом із ним видаляється все, що йому належить. Якщо обліковий запис порушує ці умови, оператор може призупинити або закрити його, після чого дані видаляються так само.",
    },
    "terms.s10_title": {"en": "Changes to these terms", "uk": "Зміни умов"},
    "terms.s10_body": {
        "en": "If these terms change, the new text appears on this page with an updated date above. Continuing to use the service after a change means you accept the new terms.",
        "uk": "Якщо умови зміняться, ми опублікуємо новий текст на цій сторінці й оновимо дату вгорі. Якщо ви й далі користуєтеся сервісом після змін, це означає, що ви приймаєте нові умови.",
    },

    # Register-page agreement line. Split so each locale keeps its own word
    # order and case — Ukrainian needs the instrumental after «погоджуєтеся з».
    "register.agree_prefix": {
        "en": "By creating an account, you agree to the",
        "uk": "Створюючи обліковий запис, ви погоджуєтеся з",
    },
    "register.agree_terms": {"en": "terms of service", "uk": "умовами користування"},
    "register.agree_and": {"en": "and the", "uk": "та"},
    "register.agree_privacy": {"en": "privacy policy", "uk": "політикою конфіденційності"},

    # --- Correlations -------------------------------------------------------
    # The Ukrainian strength words are masculine adjectives, because every
    # sentence that interpolates one attaches it to «зв’язок». The plain-language
    # sentences are built around «значення» (neuter plural) rather than around
    # the metric's own name: a metric name can be any gender, and an adjective
    # agreeing with the wrong one is the sort of error a reader trusts less
    # than a missing translation.
    "corr.eyebrow": {"en": "Correlations", "uk": "Кореляції"},
    "corr.title": {
        "en": "How this relates to your other measurements",
        "uk": "Зв’язок з іншими вашими показниками",
    },
    "corr.intro": {
        "en": "Anamna lines this measurement up with everything else you record, day by day, and reports which of them rise and fall alongside it. An association is a place to look, not an explanation.",
        "uk": "Anamna день за днем зіставляє цей показник з усіма іншими вашими даними й підказує, які з них зростають і спадають разом із ним. Зв’язок указує, куди варто придивитися, але нічого не пояснює.",
    },
    "corr.suggested_heading": {
        "en": "Strongest associations found", "uk": "Найсильніші зв’язки",
    },
    "corr.suggested_note": {
        "en": "Listed only when the pattern is stronger than chance would explain, after allowing for how many of your measurements were compared and for overlapping averages. It still does not show that one causes the other.",
        "uk": "Тут показано лише ті зв’язки, які сильніші, ніж можна пояснити випадковістю, з поправкою на кількість порівняних показників і на перекриття усереднених днів. Це все одно не означає, що одне спричиняє інше.",
    },
    "corr.no_suggestions": {
        "en": "Nothing else you record moves with this one strongly enough to put forward on its own. The picker below still compares it with anything in your record.",
        "uk": "Жоден інший показник не змінюється разом із цим настільки помітно, щоб ми пропонували його окремо. У списку нижче ви все одно можете порівняти його з будь-якими даними з вашої картки.",
    },
    "corr.card_aria": {"en": "Compare with {name}", "uk": "Порівняти з «{name}»"},
    "corr.sentence_same": {
        "en": "When {b} readings are higher, {a} readings tend to be higher as well ({strength} association).",
        "uk": "Коли значення «{b}» вищі, значення «{a}» зазвичай теж вищі ({strength} зв’язок).",
    },
    "corr.sentence_opposite": {
        "en": "When {b} readings are higher, {a} readings tend to be lower ({strength} association).",
        "uk": "Коли значення «{b}» вищі, значення «{a}» зазвичай нижчі ({strength} зв’язок).",
    },
    "corr.strength_negligible": {"en": "negligible", "uk": "незначний"},
    "corr.strength_weak": {"en": "weak", "uk": "слабкий"},
    "corr.strength_moderate": {"en": "moderate", "uk": "помірний"},
    "corr.strength_strong": {"en": "strong", "uk": "сильний"},
    "corr.strength_very_strong": {"en": "very strong", "uk": "дуже сильний"},
    "corr.days_one": {"en": "{value} day", "uk": "{value} день"},
    "corr.days_few": {"en": "{value} days", "uk": "{value} дні"},
    "corr.days_many": {"en": "{value} days", "uk": "{value} днів"},
    "corr.sampled_one": {
        "en": "drawing {shown} of {total} day", "uk": "показано {shown} з {total} дня",
    },
    "corr.sampled_few": {
        "en": "drawing {shown} of {total} days", "uk": "показано {shown} з {total} днів",
    },
    "corr.sampled_many": {
        "en": "drawing {shown} of {total} days", "uk": "показано {shown} з {total} днів",
    },

    # Explorer controls
    "corr.explore_heading": {"en": "Compare with anything", "uk": "Порівняти з будь-чим"},
    "corr.companion_label": {"en": "Compare with", "uk": "Порівняти з"},
    "corr.group_labs": {"en": "Laboratory results", "uk": "Результати аналізів"},
    "corr.filter_label": {"en": "Search the list", "uk": "Пошук у списку"},
    "corr.filter_placeholder": {
        "en": "sleep, iron, steps...", "uk": "сон, залізо, кроки...",
    },
    "corr.filter_none": {
        "en": "No metric matches that. Clear the search to see the whole list again.",
        "uk": "Нічого не знайдено. Очистіть пошук, щоб знову побачити весь список.",
    },
    "corr.cap_note": {
        "en": "Four metrics at a time is the limit. One chart can only carry so many lines. Remove one to add another.",
        "uk": "Одночасно можна вибрати не більше чотирьох показників: більше ліній на одному графіку не вміститься. Приберіть один, щоб додати інший.",
    },
    "corr.remove": {"en": "Remove {name}", "uk": "Прибрати «{name}»"},
    "corr.align_label": {"en": "Line up by", "uk": "Зіставити за"},
    "corr.align_same_day": {"en": "Same day", "uk": "Той самий день"},
    "corr.align_prev_day": {"en": "Previous day", "uk": "Попередній день"},
    "corr.align_avg7": {"en": "7-day average", "uk": "Середнє за 7 днів"},
    "corr.align_avg30": {"en": "30-day average", "uk": "Середнє за 30 днів"},
    "corr.range_label": {"en": "Period", "uk": "Період"},
    "corr.range_90": {"en": "90 days", "uk": "90 днів"},
    "corr.range_365": {"en": "1 year", "uk": "1 рік"},
    "corr.range_all": {"en": "All", "uk": "Увесь час"},
    "corr.view_aria": {"en": "Chart type", "uk": "Вигляд графіка"},
    "corr.view_timeline": {"en": "Timeline", "uk": "Хронологія"},
    "corr.view_scatter": {"en": "Scatter", "uk": "Розсіювання"},

    # Chart states and captions (also handed to the browser through JS_KEYS)
    "corr.chart_aria": {
        "en": "Timeline of {a} against {b}, over the days each was recorded",
        "uk": "Графік у часі: {a} і {b}, за дні, коли записано кожен показник",
    },
    "corr.scatter_aria": {
        "en": "Scatter plot of {a} against {b}",
        "uk": "Діаграма розсіювання для пари «{a}» і «{b}»",
    },
    "corr.legend_primary": {
        "en": "{name}: solid line, left axis", "uk": "{name}: суцільна лінія, ліва вісь",
    },
    "corr.legend_companion": {
        "en": "{name}: dashed line, right axis", "uk": "{name}: штрихова лінія, права вісь",
    },
    "corr.legend_scaled": {
        "en": "{name}: own scale", "uk": "{name}: власна шкала",
    },
    "corr.stat_companion": {
        "en": "{name}: Spearman r = {r}: {reading} · {days}",
        "uk": "{name}: коефіцієнт Спірмена r = {r}, {reading} · {days}",
    },
    "corr.stat_too_few": {
        "en": "{name}: only {days} overlap: drawn above, but too few to put a coefficient on",
        "uk": "{name}: дані збігаються лише за {days}. Їх показано на графіку, але для коефіцієнта цього замало",
    },
    # Zero pairs under an averaging alignment is not the same complaint as too
    # few: both series can be sitting there on the chart, plainly overlapping,
    # while every trailing window holds one reading or none. Saying "0 days"
    # and stopping there is the sort of dead end rule 7 exists to prevent.
    "corr.stat_no_overlap": {
        "en": "{name}: nothing pairs up under this setting. Every averaging window holds too few readings. Two laboratory results usually want \"Same day\"; a laboratory result against a wearable wants a 7- or 30-day average.",
        "uk": "{name}: за цього налаштування не вийшло жодної пари, бо в кожному вікні усереднення замало вимірювань. Для двох результатів аналізів зазвичай підходить «Той самий день», а для результату аналізу й даних із пристрою краще середнє за 7 або 30 днів.",
    },
    # The 7- and 30-day averages produce a smoothed curve rather than the
    # readings themselves, and a legend that did not say so would present a
    # rolling mean as though the device had recorded it.
    "corr.smoothed_avg7": {"en": "(7-day average)", "uk": "(середнє за 7 днів)"},
    "corr.smoothed_avg30": {"en": "(30-day average)", "uk": "(середнє за 30 днів)"},
    "corr.reading_positive": {
        "en": "{strength} association in the same direction",
        "uk": "{strength} зв’язок в одному напрямку",
    },
    "corr.reading_negative": {
        "en": "{strength} association in opposite directions",
        "uk": "{strength} зв’язок у протилежних напрямках",
    },
    "corr.reading_none": {
        "en": "no association that can be measured", "uk": "вимірного зв’язку немає",
    },
    "corr.loading": {"en": "Loading the comparison...", "uk": "Завантаження порівняння..."},
    "corr.nothing_to_draw": {
        "en": "Nothing recorded inside this period for what is selected. Widen the period, or choose a metric with readings in this range.",
        "uk": "За цей період для вибраних показників нічого не записано. Розширте період або виберіть показник, для якого є вимірювання в цьому проміжку.",
    },
    "corr.none_selected": {
        "en": "Choose one to four metrics below to see them beside this one.",
        "uk": "Оберіть від одного до чотирьох показників нижче, щоб побачити їх поруч із цим.",
    },
    "corr.own_scale": {
        "en": "With several metrics on one chart there is no shared axis, so each companion is stretched to fill the plot on its own scale. Compare the shapes, not the heights. The left-hand axis belongs to this page's own measurement only.",
        "uk": "Коли на графіку кілька показників, спільної осі в них немає, тому кожен показник для порівняння розтягнуто на всю висоту графіка за його власною шкалою. Порівнюйте форму ліній, а не їхню висоту. Ліва вісь стосується лише показника цієї сторінки.",
    },
    "corr.scatter_needs_one": {
        "en": "The scatter plots one companion against this measurement; select exactly one to use it.",
        "uk": "Діаграма розсіювання зіставляє цей показник лише з одним іншим. Щоб її побачити, залиште вибраним рівно один показник.",
    },
    "corr.error": {
        "en": "The comparison could not be loaded. Check your connection, then choose the metric again.",
        "uk": "Не вдалося завантажити порівняння. Перевірте з’єднання й виберіть показник ще раз.",
    },

    # The explanation block. Rule 5: nothing on this panel — not r, not the
    # strength word, not the alignment names — may go unexplained on the page.
    "corr.explain_summary": {
        "en": "What this number means, and what it does not",
        "uk": "Що означає це число і чого воно не означає",
    },
    "corr.explain_what": {
        "en": "A correlation coefficient describes how consistently two measurements move together across the days that carry both. It runs from −1 to +1: at +1 every rise in one is matched by a rise in the other, at −1 every rise is matched by a fall, and near 0 there is no consistent pattern. This page uses Spearman's rank correlation, which compares the order of the values rather than the values themselves, so one 51,000-step travel day or a watch taken off mid-night has far less power to invent a relationship, and a link that rises or falls consistently is still found even when it is not a straight line. A link that rises and then falls is not: this method reads it as no relationship.",
        "uk": "Коефіцієнт кореляції показує, наскільки узгоджено змінюються два вимірювання в дні, коли записано обидва. Він набуває значень від −1 до +1: за +1 кожне зростання одного супроводжується зростанням іншого, за −1 кожне зростання супроводжується спаданням, а біля 0 сталої закономірності немає. Тут використано рангову кореляцію Спірмена: вона порівнює порядок значень, а не самі значення. Тому один день у поїздці з 51 000 кроків чи годинник, знятий посеред ночі, значно менше здатні створити уявний зв’язок, а зв’язок, за якого один показник стабільно зростає або спадає разом з іншим, буде знайдено, навіть якщо він не прямолінійний. Зв’язок, за якого показник спершу зростає, а потім спадає, цей метод не виявить: він покаже, що зв’язку немає.",
    },
    "corr.scale_heading": {
        "en": "How the strength word is chosen", "uk": "Як ми визначаємо силу зв’язку",
    },
    "corr.th_strength": {"en": "Strength", "uk": "Сила зв’язку"},
    "corr.th_r": {"en": "|r| (sign ignored)", "uk": "|r| (без знака)"},
    "corr.scale_negligible": {"en": "0.00-0.09", "uk": "0,00-0,09"},
    "corr.scale_weak": {"en": "0.10-0.39", "uk": "0,10-0,39"},
    "corr.scale_moderate": {"en": "0.40-0.69", "uk": "0,40-0,69"},
    "corr.scale_strong": {"en": "0.70-0.89", "uk": "0,70-0,89"},
    "corr.scale_very_strong": {"en": "0.90-1.00", "uk": "0,90-1,00"},
    "corr.citation": {
        "en": "Schober P, Boer C, Schwarte LA. Correlation Coefficients: Appropriate Use and Interpretation. Anesth Analg. 2018;126(5):1763-1768. doi:10.1213/ANE.0000000000002864",
        "uk": "Schober P, Boer C, Schwarte LA. Correlation Coefficients: Appropriate Use and Interpretation. Anesth Analg. 2018;126(5):1763-1768. doi:10.1213/ANE.0000000000002864",
    },
    "corr.citation_link": {"en": "Open the paper", "uk": "Відкрити статтю"},
    "corr.align_heading": {
        "en": "What each way of lining the days up does",
        "uk": "Як працює кожен спосіб зіставлення днів",
    },
    "corr.align_anchor": {
        "en": "The two averaging options work in whichever direction your record needs. The measurement taken less often sets the dates, a blood test, say, and the one taken more often is averaged over the days leading up to each of them. So the same setting answers \"what did the month of sleep before this iron result look like\" and \"what did the month of blood pressure before this cholesterol result look like\", without you having to say which way round you meant it.",
        "uk": "Обидва варіанти з усередненням самі обирають потрібний напрямок. Дати задає показник, який вимірюють рідше, наприклад аналіз крові, а той, що вимірюють частіше, усереднюється за дні перед кожною з цих дат. Тож одне й те саме налаштування відповідає і на питання «яким був сон за місяць до цього результату заліза», і на «яким був тиск за місяць до цього результату холестерину». Вам не треба вказувати, у який бік порівнювати.",
    },
    "corr.align_help_same_day": {
        "en": "Same day: the two values recorded on the same date. Right when both are measured daily, and right for two results from one blood sample.",
        "uk": "Той самий день: два значення, записані в один і той самий день. Підходить, коли обидва показники вимірюють щодня, а також для двох результатів з одного зразка крові.",
    },
    "corr.align_help_prev_day": {
        "en": "Previous day: the companion value from the day before, for an effect that would only show up the next morning, such as last night's sleep against today's resting heart rate.",
        "uk": "Попередній день: значення другого показника за попередній день. Підходить для впливу, який проявляється лише наступного ранку, як-от учорашній сон і сьогоднішній пульс у спокої.",
    },
    "corr.align_help_avg7": {
        "en": "7-day average: the more frequently measured side averaged over the seven days ending on each of the other side's readings. At least three of those seven must have been recorded, or the pair is left out rather than averaged from almost nothing.",
        "uk": "Середнє за 7 днів: показник, який вимірюють частіше, усереднюється за сім днів, що закінчуються датою кожного вимірювання іншого показника. Щонайменше три з цих семи днів мають містити записи, інакше пару пропускаємо, щоб не усереднювати майже з нічого.",
    },
    "corr.align_help_avg30": {
        "en": "30-day average: the same over thirty days. This is what makes a blood draw taken twice a year comparable with a wearable that records every night, and it is usually the right choice whenever a laboratory result is one of the two.",
        "uk": "Середнє за 30 днів: те саме, але за тридцять днів. Саме так можна порівняти аналіз крові, який здають двічі на рік, із пристроєм, що записує дані щоночі. Зазвичай це найкращий вибір, щойно серед двох показників є результат аналізу.",
    },
    "corr.not_causation_heading": {
        "en": "An association is not a cause", "uk": "Зв’язок ще не означає причину",
    },
    "corr.not_causation": {
        "en": "Two measurements moving together does not mean one causes the other. Both can be driven by a third thing neither of them records. An infection, a holiday, a change of season, a new medication, or simply that the same days were busier. Treat anything found here as a starting point for a conversation with a clinician, never as a diagnosis and never as a reason to change treatment on your own.",
        "uk": "Якщо два вимірювання змінюються разом, це не означає, що одне спричиняє інше. На обидва може впливати щось третє, чого жодне з них не фіксує: інфекція, відпустка, зміна пори року, новий препарат або просто те, що ті самі дні були напруженішими. Сприймайте знайдене тут як привід поговорити з лікарем, але ніколи не як діагноз і ніколи не як підставу самостійно змінювати лікування.",
    },
    "corr.timing_heading": {"en": "Days, not hours", "uk": "Дні, а не години"},
    "corr.timing_note": {
        "en": "Everything is matched by calendar day, so the time of day is lost: a blood draw taken at eight in the morning is compared with that whole day's step count, including the walking that happened after it. Where that ordering matters, the previous-day and averaged alignments are the better question to ask.",
        "uk": "Усе зіставляється за календарним днем, тому час доби не враховується: аналіз крові, зданий о восьмій ранку, порівнюється з кроками за весь день, зокрема з ходьбою вже після нього. Якщо цей порядок важливий, краще обрати зіставлення за попереднім днем або за середнім.",
    },

    # ----------------------------------------------------------- Vaccinations
    "nav.vaccinations": {"en": "Vaccinations", "uk": "Щеплення"},
    "vax.title": {"en": "Vaccinations · Anamna", "uk": "Щеплення · Anamna"},
    "vax.heading": {"en": "Your vaccinations", "uk": "Ваші щеплення"},
    # Short enough that the first vaccine group is on a phone's first screen.
    "vax.totals_doses": {"en": "Doses on file", "uk": "Щеплень у картці"},
    "vax.totals_protected": {"en": "Diseases covered", "uk": "Захист від хвороб"},
    "vax.totals_unchecked": {"en": "Not yet checked by you", "uk": "Чекають на звірку"},

    # Beside «Add a vaccination» at the top: a jump to the gap analysis.
    "vax.gaps_jump": {"en": "Worth asking about: {count}", "uk": "Питання до лікаря: {count}"},
    "vax.gaps_disclaimer": {
        "en": "Compared with the Ukrainian, European and US schedules, so you can take a specific question to a doctor. Not medical advice.",
        "uk": "Ми порівняли ваші щеплення з календарями України, ЄС і США, щоб ви прийшли до лікаря з конкретним запитанням. Це не медична порада.",
    },
    "vax.gaps_heading": {"en": "Worth asking a doctor about", "uk": "Про що варто запитати лікаря"},
    "vax.gaps_lead": {
        "en": "Each line says where it comes from. Some come from your own card, which printed the length of the course; the rest come from published schedules, named and linked.",
        "uk": "Біля кожного рядка вказано джерело. Частина рядків спирається на вашу картку, де надруковано, скільки доз у курсі. Решта спирається на опубліковані календарі щеплень: кожен названо й дано посилання.",
    },
    "vax.gaps_none": {"en": "Nothing in this record looks outstanding right now.", "uk": "Схоже, зараз у картці немає пропущених щеплень."},
    "vax.gap_series": {
        "en": "Your card records dose {given} of {total}, given {date}. The remaining dose or doses are not on file.",
        "uk": "У вашій картці є доза {given} з {total} від {date}. Решти доз курсу в картці немає.",
    },
    "vax.gap_series_source": {"en": "Source: your own card", "uk": "Джерело: ваша картка щеплень"},
    "vax.gap_due": {"en": "Last dose {date}. The next is due around {due}.", "uk": "Остання доза: {date}. Наступну варто зробити приблизно {due}."},
    "vax.gap_overdue": {"en": "Last dose {date}. The next was due around {due}.", "uk": "Остання доза: {date}. Наступну треба було зробити приблизно {due}."},
    "vax.gap_never_dated": {"en": "Nothing on file. The schedules put the next one around {due}.", "uk": "У картці таких щеплень немає. За календарями наступне припадає приблизно на {due}."},
    "vax.gap_never": {"en": "Nothing on file, and without a previous dose no date can be worked out.", "uk": "У картці таких щеплень немає, а без попередньої дози дату наступної не розрахувати."},
    "vax.gap_discuss_dated": {
        "en": "Last dose {date}. The published schedules differ on whether and when a healthy adult needs another, so no date is given here; ask your doctor.",
        "uk": "Остання доза: {date}. Календарі по-різному визначають, чи потрібна здоровій дорослій людині наступна доза і коли, тому дати тут немає. Запитайте про це лікаря.",
    },
    "vax.gap_discuss": {
        "en": "Nothing on file. The published schedules differ on who should have this vaccination, so no date is given here; ask your doctor.",
        "uk": "У картці таких щеплень немає. Календарі по-різному визначають, кому це щеплення потрібне, тому дати тут немає. Запитайте про це лікаря.",
    },
    "vax.urgency_overdue": {"en": "Past due", "uk": "Прострочено"},
    "vax.urgency_soon": {"en": "Within six months", "uk": "Протягом пів року"},
    "vax.urgency_later": {"en": "Later", "uk": "Пізніше"},
    "vax.urgency_unknown": {"en": "No date", "uk": "Без дати"},

    "vax.agreement_agreed": {"en": "Ukraine, the EU and the US agree", "uk": "Україна, ЄС і США одностайні"},
    "vax.agreement_differs": {"en": "The three schedules differ", "uk": "Три календарі розходяться"},
    "vax.agreement_agreed_ua_us": {
        "en": "Ukraine and the US agree; EU countries vary",
        "uk": "Україна і США одностайні, у країнах ЄС по-різному",
    },
    "vax.agreement_agreed_help": {
        "en": "All three published schedules state the same interval for a healthy adult, so this date does not depend on which of them you follow.",
        "uk": "Усі три календарі вказують для здорової дорослої людини однаковий інтервал, тож дата не залежить від того, якого календаря ви дотримуєтеся.",
    },
    "vax.agreement_differs_help": {
        "en": "The authorities do not say the same thing here, so no single answer is presented as settled. Read all three, and ask your doctor which applies to you.",
        "uk": "Тут відомства радять різне, тому жодну відповідь ми не подаємо як остаточну. Прочитайте всі три й запитайте лікаря, яка з них стосується саме вас.",
    },
    "vax.agreement_agreed_ua_us_help": {
        "en": "Ukraine's calendar and the US schedule both state a booster every ten years for a healthy adult, and the date here follows them. EU countries set their own adult schedules (some every ten years, some at fixed ages, some none after childhood), so if you follow another country's calendar, check it in the ECDC Vaccine Scheduler.",
        "uk": "Календар України та календар США передбачають для здорової дорослої людини ревакцинацію кожні десять років, і дату тут розраховано за ними. Країни ЄС визначають календарі для дорослих самостійно: десь ревакцинація кожні десять років, десь у певному віці, а десь після дитячих щеплень її не передбачено. Якщо ви орієнтуєтеся на календар іншої країни, перевірте його в ECDC Vaccine Scheduler.",
    },
    "vax.note_covid_booster": {
        "en": "For the 2025/26 season the United States moved most adults from a routine recommendation to a decision made together with a clinician, while EU member states recommend by age and risk group. Ukraine's vaccination calendar (Ministry of Health order 595, edition of 1 January 2026) does not list COVID-19 vaccination.",
        "uk": "Із сезону 2025/26 у США для більшості дорослих це вже не планова рекомендація, а рішення, яке людина ухвалює разом із лікарем. Країни ЄС рекомендують щеплення за віком і групою ризику. У Календарі профілактичних щеплень України (наказ МОЗ № 595, редакція від 01.01.2026) щеплення від COVID-19 немає.",
    },
    "vax.note_influenza_season": {
        "en": "The United States recommends a dose every season for everyone from six months of age. Ukraine and most EU states recommend it for named risk groups and leave the choice to everyone else.",
        "uk": "США рекомендують щеплюватися щосезону всім, кому виповнилося шість місяців. Україна та більшість країн ЄС рекомендують щеплення визначеним групам ризику, а решта вирішує сама.",
    },
    "vax.sources_label": {"en": "Schedule sources ({count})", "uk": "Джерела календарів ({count})"},
    "vax.product_sources": {"en": "Registration and sources ({count})", "uk": "Реєстрація та джерела ({count})"},
    "vax.region_UA": {"en": "Ukraine", "uk": "Україна"},
    "vax.region_EU": {"en": "European Union", "uk": "Європейський Союз"},
    "vax.region_US": {"en": "United States", "uk": "США"},
    "vax.region_INT": {"en": "International", "uk": "Міжнародні"},

    "vax.doses_heading": {"en": "Doses on file", "uk": "Щеплення в картці"},
    "vax.doses_lead": {
        "en": "Grouped by what each dose protects against, newest first. A dose that protects against several diseases appears under each of them. It is still one injection.",
        "uk": "Згруповано за хворобами, від яких захищають щеплення, найновіші вгорі. Щеплення від кількох хвороб одразу показано під кожною з них, хоча це одна ін’єкція.",
    },
    "vax.group_count": {"en": "{count} doses", "uk": "Доз: {count}"},
    "vax.group_count_one": {"en": "{count} dose", "uk": "{count} доза"},
    "vax.group_count_few": {"en": "{count} doses", "uk": "{count} дози"},
    "vax.group_count_many": {"en": "{count} doses", "uk": "{count} доз"},
    "vax.th_date": {"en": "Date", "uk": "Дата"},
    "vax.th_lot": {"en": "Batch", "uk": "Серія"},
    "vax.th_route": {"en": "How it was given", "uk": "Спосіб уведення"},
    "vax.th_site": {"en": "Injection site", "uk": "Місце введення"},
    "vax.th_source": {"en": "Where it came from", "uk": "Джерело"},
    "vax.th_code": {"en": "eHealth vaccine code", "uk": "Код вакцини eHealth"},
    "vax.th_quantity": {"en": "Amount", "uk": "Об’єм"},
    "vax.th_facility": {"en": "Facility on the document", "uk": "Заклад за документом"},
    "vax.th_clinician": {"en": "Given by", "uk": "Хто зробив"},
    "vax.th_trade_name": {"en": "Trade name", "uk": "Торгова назва"},
    "vax.quantity_ml": {"en": "{value} mL", "uk": "{value} мл"},
    "vax.as_printed": {"en": "As printed", "uk": "Як надруковано"},
    "vax.as_printed_help": {
        "en": "The product description exactly as the card prints it, kept as evidence. The trade name and maker above are what that description identifies.",
        "uk": "Опис препарату дослівно з картки, збережений як підтвердження. Торгову назву й виробника вище визначено саме за цим описом.",
    },
    "vax.trade_name_help": {
        "en": "The registered product name. Twinrix, Gardasil 9. The card prints only the eHealth code and a description, so the name is worked out from the code and the maker printed beside it, using the Ukrainian State Register of Medicinal Products and the EU and US regulators (linked under each vaccine).",
        "uk": "Зареєстрована назва препарату, наприклад Twinrix чи Gardasil 9. У картці надруковано лише код eHealth та опис, тож назву ми визначаємо за кодом і виробником, указаним поруч, через Державний реєстр лікарських засобів України та регуляторів ЄС і США (посилання під кожною вакциною).",
    },
    "vax.trade_probable": {
        "en": "Most likely: the card prints no trade name, and {alternatives} is also registered under this code by the same maker.",
        "uk": "Найімовірніше: у картці немає торгової назви, а той самий виробник зареєстрував під цим кодом ще й {alternatives}.",
    },
    "vax.facility_help": {
        "en": "The health facility named in the card's header. The one that keeps the card. Doses given elsewhere and copied onto it show the same name.",
        "uk": "Заклад охорони здоров’я з шапки картки, тобто той, що її веде. Щеплення, зроблені деінде й переписані в цю картку, мають ту саму назву закладу.",
    },
    "vax.legend_summary": {"en": "What the labels on a dose mean", "uk": "Що означають позначки біля щеплення"},
    "vax.filter_label": {"en": "Find a vaccination", "uk": "Знайти щеплення"},
    "vax.filter_search": {"en": "Search", "uk": "Пошук"},
    "vax.filter_toggle": {"en": "Filters", "uk": "Фільтри"},
    "vax.filter_placeholder": {"en": "Trade name, maker, disease, code or batch", "uk": "Назва, виробник, хвороба, код або серія"},
    "vax.filter_year": {"en": "Year", "uk": "Рік"},
    "vax.filter_all_years": {"en": "All years", "uk": "Усі роки"},
    "vax.filter_product": {"en": "Vaccine", "uk": "Вакцина"},
    "vax.filter_all_products": {"en": "All vaccines", "uk": "Усі вакцини"},
    "vax.filter_disease": {"en": "Protects against", "uk": "Захищає від"},
    "vax.filter_all_diseases": {"en": "All diseases", "uk": "Усі хвороби"},
    "vax.filter_clear": {"en": "Clear", "uk": "Скинути"},
    "vax.filter_count": {"en": "{count} doses match", "uk": "Знайдено: {count}"},
    "vax.filter_count_one": {"en": "{count} dose matches", "uk": "Знайдено {count} щеплення"},
    "vax.filter_count_few": {"en": "{count} doses match", "uk": "Знайдено {count} щеплення"},
    "vax.filter_count_many": {"en": "{count} doses match", "uk": "Знайдено {count} щеплень"},
    "vax.filter_none": {"en": "No dose matches. Clear the filters to see every dose.", "uk": "Жодного щеплення не знайдено. Скиньте фільтри, щоб побачити всі."},
    "vax.dose_of": {"en": "Dose {given} of {total}", "uk": "Доза {given} з {total}"},
    "vax.kind_vaccination": {"en": "Vaccination", "uk": "Вакцинація"},
    "vax.kind_revaccination": {"en": "Revaccination", "uk": "Ревакцинація"},
    "vax.kind_help": {
        "en": "A vaccination is a dose in the first course. A revaccination is a later dose that renews the protection the first course gave.",
        "uk": "Вакцинація: доза первинного курсу. Ревакцинація: пізніша доза, яка поновлює захист, отриманий після первинного курсу.",
    },
    "vax.route_intramuscular": {"en": "Into the muscle", "uk": "Внутрішньом’язово"},
    "vax.lot_help": {
        "en": "The batch number identifies the exact vial a dose came from. It is what a safety notice or a recall names, which is the only reason it is worth copying accurately.",
        "uk": "Номер серії вказує, з якої саме партії вакцини зроблено щеплення. Саме його називають у попередженнях про безпеку та під час відкликання серій, тому його й варто переписувати без помилок.",
    },
    "vax.code_help": {
        "en": "The short code is the identifier Ukraine's national eHealth system prints for this vaccine. It is stored because product names change with every supply contract while the code does not.",
        "uk": "Короткий код, яким національна система eHealth позначає цю вакцину. Ми зберігаємо його, бо назви препаратів змінюються з кожною закупівлею, а код лишається тим самим.",
    },
    "vax.from_document": {"en": "Read from a document", "uk": "Зчитано з документа"},
    "vax.entered_by_hand": {"en": "Entered by you", "uk": "Внесено вами"},
    "vax.entered_by_hand_help": {
        "en": "You typed this in yourself. It carries your authority rather than a parser's, and re-reading any card will never overwrite it.",
        "uk": "Ви внесли цей запис самі. За нього відповідаєте ви, а не програма зчитування, і повторне зчитування жодної картки його не перезапише.",
    },
    "vax.status_extracted": {"en": "Not checked yet", "uk": "Не звірено"},
    "vax.status_verified": {"en": "Checked by you", "uk": "Звірено вами"},
    "vax.status_corrected": {"en": "Corrected by you", "uk": "Виправлено вами"},
    "vax.status_extracted_help": {
        "en": "Read by optical character recognition from a photograph of a paper card, and not yet compared with that card by a person. Dates, batch numbers and dose counts are exactly the fields OCR gets wrong.",
        "uk": "Зчитано розпізнаванням тексту з фото паперової картки, і ніхто ще не звірив запис із карткою. Саме в датах, номерах серій і номерах доз розпізнавання помиляється найчастіше.",
    },
    "vax.confirm": {"en": "Confirm this dose", "uk": "Підтвердити щеплення"},
    "vax.verified_notice": {"en": "Marked as checked.", "uk": "Позначено як звірене."},
    "vax.edit": {"en": "Edit", "uk": "Редагувати"},
    "vax.save": {"en": "Save", "uk": "Зберегти"},
    "vax.saved_notice": {"en": "Saved.", "uk": "Збережено."},
    "vax.remove": {"en": "Remove", "uk": "Вилучити"},
    "vax.removed_notice": {"en": "Removed from your record.", "uk": "Вилучено з картки."},
    "vax.remove_document_help": {
        "en": "This dose was read from a document. Removing it sets the dose aside without touching the document, and re-reading that card will not bring it back.",
        "uk": "Це щеплення зчитано з документа. Вилучення відхиляє щеплення, але документ не змінює, і повторне зчитування картки його не поверне.",
    },
    "vax.source_document": {"en": "From {title}", "uk": "З документа «{title}»"},
    "vax.evidence": {"en": "The line this was read from", "uk": "Рядок, з якого це зчитано"},
    "vax.edit_heading": {"en": "Edit this dose", "uk": "Редагувати щеплення"},

    "vax.unidentified_heading": {"en": "Doses whose vaccine could not be identified", "uk": "Щеплення з невизначеною вакциною"},
    "vax.unidentified_lead": {
        "en": "A dose was clearly given on this date, but neither the code nor the product name survived the scan well enough to say which vaccine it was. It is kept, because it happened. Open the document, read the row and set it right.",
        "uk": "Щеплення в цю дату точно було, але після сканування ні код, ні назва препарату не прочиталися достатньо, щоб визначити вакцину. Ми зберегли запис, бо щеплення відбулося. Відкрийте документ, перегляньте рядок і виправте запис.",
    },

    "vax.missing_heading": {"en": "Routine Ukrainian vaccinations with nothing on file", "uk": "Планові щеплення з календаря України, яких немає в картці"},
    "vax.missing_lead": {
        "en": "This does not say you were never vaccinated. Ukraine's electronic register began in 2019, and childhood doses given before that were written into a paper booklet no modern card reproduces. If you still have that booklet, the form below is how those doses reach this record.",
        "uk": "Це не означає, що вас ніколи не щеплювали. Електронний реєстр в Україні працює з 2019 року, а дитячі щеплення до того записували в паперову книжечку, якої жодна сучасна картка не відтворює. Якщо книжечка у вас збереглася, внесіть ці щеплення через форму нижче.",
    },

    "vax.add_heading": {"en": "Add a vaccination yourself", "uk": "Додати щеплення самостійно"},
    "vax.add_lead": {
        "en": "The next dose of something already on file, or one no document here holds at all. An old paper booklet, a travel clinic abroad, a flu shot at a pharmacy. It is stored beside the doses read from cards and counts the same, and it is always labelled as yours so the two are never confused.",
        "uk": "Наступна доза щеплення, яке вже є в картці, або щеплення, якого немає в жодному документі: зі старої паперової книжечки, з клініки для мандрівників за кордоном, від грипу в аптеці. Воно зберігається поряд зі зчитаними з карток, враховується так само і завжди позначене як внесене вами, тож їх не сплутати.",
    },
    "vax.add_submit": {"en": "Add this vaccination", "uk": "Додати щеплення"},
    "vax.added_notice": {"en": "Added to your record.", "uk": "Додано до картки."},
    "vax.field_date": {"en": "Date it was given", "uk": "Дата щеплення"},
    "vax.field_vaccine": {"en": "Which vaccine", "uk": "Вакцина"},
    "vax.field_vaccine_help": {
        "en": "Type a disease or a code. If yours is not listed, type its name.",
        "uk": "Введіть назву хвороби або код. Якщо потрібної вакцини немає в списку, впишіть її назву.",
    },
    "vax.field_vaccine_placeholder": {"en": "Type a disease or a code. Tetanus, DTaP...", "uk": "Хвороба або код, наприклад правець чи DTaP"},
    "vax.field_kind": {"en": "First course or booster", "uk": "Вакцинація чи ревакцинація"},
    "vax.field_dose_number": {"en": "Dose number", "uk": "Номер дози"},
    "vax.field_doses_in_series": {"en": "Doses in the course", "uk": "Усього доз у курсі"},
    "vax.field_series_help": {
        "en": "If the card says «2/3», this was the second of three. Leave both empty if it does not say.",
        "uk": "Якщо в картці написано «2/3», це друга доза з трьох. Якщо такого запису немає, залиште обидва поля порожніми.",
    },
    "vax.field_lot": {"en": "Batch number", "uk": "Номер серії"},
    "vax.field_product": {"en": "Product name as printed", "uk": "Назва препарату з документа"},
    "vax.field_manufacturer": {"en": "Manufacturer", "uk": "Виробник"},
    "vax.field_trade_name": {"en": "Trade name", "uk": "Торгова назва"},
    "vax.field_trade_name_help": {"en": "As on the box or the certificate. Twinrix, Gardasil 9.", "uk": "Як на упаковці чи в сертифікаті, наприклад Twinrix або Gardasil 9."},
    "vax.field_facility": {"en": "Facility", "uk": "Заклад"},
    "vax.field_clinician": {"en": "Given by", "uk": "Хто зробив"},
    "vax.field_note": {"en": "Note", "uk": "Примітка"},
    "vax.field_note_help": {"en": "Where it was given, or anything else worth remembering about it.", "uk": "Де вам зробили щеплення або що ще про нього варто пам’ятати."},
    "vax.optional": {"en": "optional", "uk": "необов’язково"},
    "vax.error_date": {"en": "Enter the date the vaccination was given. A date in the future cannot be right.", "uk": "Вкажіть дату щеплення. Вона не може бути в майбутньому."},
    "vax.error_vaccine": {"en": "Choose a vaccine from the list, or type the product name if it is not there.", "uk": "Оберіть вакцину з переліку або впишіть назву препарату, якщо її там немає."},
    "vax.error_series": {"en": "The dose number cannot be higher than the number of doses in the course.", "uk": "Номер дози не може бути більшим за кількість доз у курсі."},
    "vax.error_duplicate": {"en": "A dose with that date and batch number is already on file.", "uk": "Щеплення з такою датою та номером серії вже є в картці."},

    "vax.empty_title": {"en": "No vaccinations on file yet", "uk": "У картці ще немає щеплень"},
    "vax.empty_body": {
        "en": "Upload a photograph of your vaccination card - form 063/о, or any other - and every dose printed on it will be read out and listed here. «Add a vaccination» above enters them one at a time instead.",
        "uk": "Завантажте фото картки щеплень (форма 063/о чи будь-яка інша), і ми зчитаємо й покажемо тут кожне щеплення з неї. Або вносьте щеплення по одному кнопкою «Додати щеплення» вгорі.",
    },
    "vax.empty_next": {"en": "Upload a vaccination card", "uk": "Завантажити картку щеплень"},

    # --- Vaccinations: the add dialog, the collapsed sections, and review ----
    "vax.cancel": {"en": "Cancel", "uk": "Скасувати"},
    "vax.add_next": {"en": "Add the next dose", "uk": "Додати наступну дозу"},
    "vax.add_next_help": {
        "en": "Opens the form already filled in from the last dose on file. The same vaccine, and the next number in the course it says you are part-way through. Change anything that does not match your card.",
        "uk": "Відкриває форму, заповнену даними останнього щеплення з картки: та сама вакцина і наступний номер дози в незавершеному курсі. Змініть усе, що не збігається з вашою карткою.",
    },
    "vax.add_for": {"en": "Add a dose against {name}", "uk": "Додати щеплення: {name}"},
    "vax.group_latest": {"en": "latest {date}", "uk": "останнє: {date}"},
    "vax.group_unchecked": {"en": "{count} to check", "uk": "Не звірено: {count}"},
    "vax.group_unchecked_one": {"en": "{count} to check", "uk": "{count} чекає на звірку"},
    "vax.group_unchecked_few": {"en": "{count} to check", "uk": "{count} чекають на звірку"},
    "vax.group_unchecked_many": {"en": "{count} to check", "uk": "{count} чекають на звірку"},
    "vax.check_on_document": {"en": "Check it against the document", "uk": "Звірити з документом"},
    "vax.unidentified_short": {"en": "Vaccine not identified", "uk": "Вакцину не визначено"},
    "doc.immunizations_read": {"en": "{count} vaccinations read from this document", "uk": "Щеплень, зчитаних із цього документа: {count}"},
    "doc.immunizations_read_one": {"en": "{count} vaccination read from this document", "uk": "З цього документа зчитано {count} щеплення"},
    "doc.immunizations_read_few": {"en": "{count} vaccinations read from this document", "uk": "З цього документа зчитано {count} щеплення"},
    "doc.immunizations_read_many": {"en": "{count} vaccinations read from this document", "uk": "З цього документа зчитано {count} щеплень"},
    "doc.immunizations_lead": {
        "en": "Each was read by optical character recognition from the page beside this list. Open the page it names, compare it, and confirm or correct it. Dates, dose numbers and batch numbers are what OCR gets wrong.",
        "uk": "Кожне зчитано розпізнаванням тексту зі сторінки поряд із цим списком. Відкрийте вказану сторінку, порівняйте й підтвердьте або виправте - саме в датах, номерах доз і серій розпізнавання помиляється.",
    },
    "doc.immunizations_all": {"en": "See all vaccinations on file", "uk": "Усі щеплення в картці"},
    "vax.recorded_at_visit": {
        "en": "Also in the clinic's visit note «{title}», {date}",
        "uk": "Також згадано в записі про візит «{title}», {date}",
    },
    "doc.vaccines_given_here": {"en": "{count} vaccinations given at this visit", "uk": "Щеплень, зроблених під час цього візиту: {count}"},
    "doc.vaccines_given_here_one": {"en": "{count} vaccination given at this visit", "uk": "Під час цього візиту зроблено {count} щеплення"},
    "doc.vaccines_given_here_few": {"en": "{count} vaccinations given at this visit", "uk": "Під час цього візиту зроблено {count} щеплення"},
    "doc.vaccines_given_here_many": {"en": "{count} vaccinations given at this visit", "uk": "Під час цього візиту зроблено {count} щеплень"},
    "doc.vaccines_given_here_lead": {
        "en": "Matched to the doses on file by day and vial lot. Each dose is kept once, on your vaccination card or as you entered it; this note is its second written record.",
        "uk": "Зіставлено з щепленнями в картці за датою та серією вакцини. Кожне щеплення зберігається один раз, з вашої картки щеплень або як ви його внесли; цей запис клініки, його друге письмове підтвердження.",
    },

    # --- Health-history export ------------------------------------------------
    "export.open": {"en": "Export history", "uk": "Створити виписку"},
    "export.back": {"en": "Back to {name}", "uk": "Назад до «{name}»"},
    "export.eyebrow": {"en": "Shareable record", "uk": "Виписка з картки"},
    "export.title": {"en": "Build a health history export", "uk": "Виписка з історії здоров’я"},
    "export.lead": {
        "en": "Choose exactly what to include, check every value in the preview, then print it or download a formatted PDF.",
        "uk": "Оберіть, що саме включити, перевірте кожне значення в попередньому перегляді, а потім надрукуйте або завантажте оформлений PDF.",
    },
    "export.builder_title": {"en": "Metrics", "uk": "Показники"},
    "export.selected_count": {"en": "Selected: {count}", "uk": "Вибрано: {count}"},
    "export.search_label": {"en": "Find a metric", "uk": "Знайти показник"},
    "export.search_placeholder": {"en": "Search by name or group", "uk": "Пошук за назвою або групою"},
    "export.select_visible": {"en": "Select shown", "uk": "Вибрати всі показані"},
    "export.clear_visible": {"en": "Clear shown", "uk": "Зняти показані"},
    "export.no_search_results": {"en": "No recorded metrics match that search.", "uk": "Немає показників, що відповідають пошуку."},
    "export.aggregation_label": {"en": "History detail", "uk": "Деталізація історії"},
    "export.aggregation_auto": {"en": "Automatic", "uk": "Автоматично"},
    "export.aggregation_exact": {"en": "Every exact value", "uk": "Усі значення без усереднення"},
    "export.aggregation_month": {"en": "Monthly averages", "uk": "Помісячні середні"},
    "export.aggregation_quarter": {"en": "Quarterly averages", "uk": "Поквартальні середні"},
    "export.aggregation_year": {"en": "Yearly averages", "uk": "Річні середні"},
    "export.update_preview": {"en": "Update preview", "uk": "Оновити перегляд"},
    "export.preview_changed": {"en": "Selection changed. Update the preview before printing.", "uk": "Вибір змінився. Оновіть перегляд, перш ніж друкувати."},
    "export.print": {"en": "Print", "uk": "Друкувати"},
    "export.download_pdf": {"en": "Download PDF", "uk": "Зберегти PDF"},
    "export.pdf_building": {"en": "Preparing the PDF...", "uk": "Готую PDF..."},
    "export.pdf_failed": {
        "en": "The PDF could not be prepared. Check the connection and try again.",
        "uk": "Не вдалося підготувати PDF. Перевірте з’єднання й спробуйте ще раз.",
    },
    "export.select_one_title": {"en": "Choose at least one metric", "uk": "Оберіть принаймні один показник"},
    "export.select_one_body": {"en": "Select a metric in the builder, then update the preview or download the PDF again.", "uk": "Позначте показник у списку вище, потім оновіть перегляд або знову збережіть PDF."},
    "export.document_title": {"en": "Historical measurements", "uk": "Історія показників"},
    "export.document_subtitle": {"en": "Selected values from the personal medical record", "uk": "Вибрані значення з особистої медичної картки"},
    "export.patient": {"en": "Patient", "uk": "Пацієнт"},
    "export.unknown_patient": {"en": "Patient not recorded", "uk": "Пацієнта не вказано"},
    "export.date_of_birth": {"en": "Date of birth", "uk": "Дата народження"},
    "export.created": {"en": "Created", "uk": "Створено"},
    "export.included": {"en": "Included", "uk": "У виписці"},
    "export.latest": {"en": "Latest", "uk": "Останнє значення"},
    "export.period": {"en": "Period", "uk": "Період"},
    "export.aggregation_note": {
        "en": "{original} historical values are shown as {shown} {mode}. Each row names its minimum, maximum and sample count.",
        "uk": "Значень в історії: {original}, рядків у таблиці: {shown} ({mode}). У кожному рядку вказано мінімум, максимум і кількість значень.",
    },
    "export.aggregated_reference": {"en": "Min {minimum} · max {maximum} · n={count}", "uk": "Мін. {minimum} · макс. {maximum} · n={count}"},
    "export.device_spread": {"en": "Min {minimum} · max {maximum} · n={count}", "uk": "Мін. {minimum} · макс. {maximum} · n={count}"},
    "export.average_badge": {"en": "Average", "uk": "Середнє"},
    "export.th_date": {"en": "Date or period", "uk": "Дата або період"},
    "export.th_result": {"en": "Result", "uk": "Результат"},
    "export.th_comparison": {"en": "Verdict and interval", "uk": "Оцінка та інтервал"},
    # Which interval a result was judged against and who publishes it, so the
    # verdict in a handed-over export names its own basis.
    "export.judged_against": {"en": "{interval} · {authority}", "uk": "{interval} · {authority}"},
    "export.lab_interval": {"en": "Laboratory range: {interval}", "uk": "Норма лабораторії: {interval}"},
    "export.also_printed": {
        "en": "Same day also printed as {values}",
        "uk": "Того ж дня надруковано також: {values}",
    },
    "export.th_source": {"en": "Source", "uk": "Джерело"},
    "export.unknown_source": {"en": "Source not recorded", "uk": "Джерело не вказано"},
    "export.not_available": {"en": "Not available", "uk": "Немає даних"},
    "export.page": {"en": "Page", "uk": "Сторінка"},
    "export.selection_summary": {"en": "{metrics} · {values}", "uk": "{metrics} · {values}"},
    "export.metrics_count": {"en": "{count} metrics", "uk": "Показників: {count}"},
    "export.metrics_count_one": {"en": "{count} metric", "uk": "{count} показник"},
    "export.metrics_count_few": {"en": "{count} metrics", "uk": "{count} показники"},
    "export.metrics_count_many": {"en": "{count} metrics", "uk": "{count} показників"},
    "export.values_count": {"en": "{count} values", "uk": "Значень: {count}"},
    "export.values_count_one": {"en": "{count} value", "uk": "{count} значення"},
    "export.values_count_few": {"en": "{count} values", "uk": "{count} значення"},
    "export.values_count_many": {"en": "{count} values", "uk": "{count} значень"},
    # --- /changes: what changed between result dates ------------------------
    "changes.nav": {"en": "Changes", "uk": "Зміни"},
    "changes.title": {"en": "What changed", "uk": "Що змінилося"},
    "changes.heading": {"en": "What changed in your results", "uk": "Що змінилося у ваших результатах"},
    "changes.document_heading": {"en": "What this document changed", "uk": "Що змінив цей документ"},
    "changes.document_lead": {
        "en": "Only the results read from this document, each compared with the previous result of the same test:",
        "uk": "Тут лише результати, зчитані з цього документа; кожен порівняно з попереднім результатом того самого аналізу:",
    },
    "changes.show_latest": {"en": "Show the latest results", "uk": "Показати останні результати"},
    "changes.span": {"en": "{start} - {end}", "uk": "{start} - {end}"},
    "changes.span_days": {"en": "{start}-{end}", "uk": "{start}-{end}"},
    "changes.tests_count": {"en": "{count} tests", "uk": "{count} показників"},
    "changes.tests_count_one": {"en": "{count} test", "uk": "{count} показник"},
    "changes.tests_count_few": {"en": "{count} tests", "uk": "{count} показники"},
    "changes.tests_count_many": {"en": "{count} tests", "uk": "{count} показників"},
    "changes.period_label": {"en": "Results from", "uk": "Результати за"},
    "changes.show": {"en": "Show", "uk": "Показати"},
    "changes.custom_range": {"en": "Choose dates: one report", "uk": "Свій період одним звітом"},
    "changes.range_from": {"en": "From", "uk": "Від"},
    "changes.range_to": {"en": "To", "uk": "До"},
    "changes.range_apply": {"en": "Show as one report", "uk": "Показати одним звітом"},
    "changes.range_hint": {
        "en": "Every test measured between these dates appears once, with its latest value there, compared "
              "with its last result from before the first date.",
        "uk": "Кожен показник, виміряний у цьому проміжку, з’явиться один раз: з останнім значенням за період і порівнянням з останнім результатом до першої дати.",
    },
    "changes.range_option": {"en": "Chosen dates: {span}", "uk": "Вибрані дати: {span}"},
    "changes.episode_nav": {"en": "Other result periods", "uk": "Інші періоди"},
    "changes.earlier": {"en": "Earlier: {span}", "uk": "Раніше: {span}"},
    "changes.newer": {"en": "Newer: {span}", "uk": "Пізніше: {span}"},
    "changes.legend_episode": {
        "en": "A laboratory often delivers one order over several days, so result dates no more than {days} "
              "apart, or from the same order number, are shown as one report. Each test appears once, with its "
              "latest value in that period, compared with its last result from before the period.",
        "uk": "Лабораторія часто видає результати одного замовлення частинами впродовж кількох днів. Тому результати, між датами яких не більше {days}, або з одним номером замовлення ми показуємо одним звітом. Кожен показник з’являється в ньому один раз: з останнім значенням за період і порівнянням з останнім результатом до цього періоду.",
    },
    "changes.gap_days_one": {"en": "{count} day", "uk": "{count} дня"},
    "changes.gap_days_few": {"en": "{count} days", "uk": "{count} днів"},
    "changes.gap_days_many": {"en": "{count} days", "uk": "{count} днів"},
    "changes.also_measured": {"en": "Also measured in this period: {items}", "uk": "За цей період також виміряно: {items}"},
    "changes.single_note": {
        "en": "Only one test was measured in this period. Earlier periods are in the selector above.",
        "uk": "У цей період виміряно лише один показник. Попередні періоди - у переліку вище.",
    },
    "changes.range_empty_title": {"en": "No results in {span}", "uk": "Немає результатів за {span}"},
    "changes.range_empty_body": {
        "en": "No laboratory results are dated inside these dates. Choose a wider period above, or go back to the latest results.",
        "uk": "У цьому проміжку немає лабораторних результатів. Виберіть ширший період вище або поверніться до останніх результатів.",
    },
    "changes.documents_label": {"en": "Source documents", "uk": "Джерела"},
    "changes.counts_aria": {"en": "Summary for {date}", "uk": "Підсумок за {date}"},
    "changes.bucket_new": {"en": "New problem", "uk": "Нове відхилення"},
    "changes.bucket_resolved": {"en": "Resolved", "uk": "Знову в нормі"},
    "changes.bucket_still": {"en": "Still outside range", "uk": "Досі поза нормою"},
    "changes.bucket_borderline": {"en": "Borderline", "uk": "Пограничне"},
    "changes.bucket_first": {"en": "First measurement", "uk": "Перший результат"},
    "changes.bucket_stable": {"en": "Stable in range", "uk": "Стабільно в межах норми"},
    "changes.bucket_unjudged": {"en": "Not judged", "uk": "Без оцінки"},
    "changes.direction_better": {"en": "Still outside · improving", "uk": "Досі поза нормою · покращується"},
    "changes.direction_worse": {"en": "Still outside · worsening", "uk": "Досі поза нормою · погіршується"},
    "changes.direction_same": {"en": "Still outside · about the same", "uk": "Досі поза нормою · майже без змін"},
    "changes.explain_new": {
        "en": "Outside its reference interval now; last time it was inside, not judged, or never measured.",
        "uk": "Зараз поза референтним інтервалом. Минулого разу показник був у межах інтервалу, без оцінки або його ще не вимірювали.",
    },
    "changes.explain_resolved": {
        "en": "Back inside its interval; the previous result was outside it or borderline.",
        "uk": "Знову в межах інтервалу. Попередній результат був поза ним або пограничним.",
    },
    "changes.explain_still": {
        "en": "Outside its interval both times. \"Improving\" or \"worsening\" says whether it moved towards "
              "the interval or further from it, compared in the same unit.",
        "uk": "Поза інтервалом обидва рази. «Покращується» чи «погіршується» означає, що значення наблизилося до інтервалу чи віддалилося від нього; порівнюємо в тих самих одиницях.",
    },
    "changes.explain_borderline": {
        "en": "In a borderline band, or marked borderline or equivocal by the laboratory: close to the edge and worth watching.",
        "uk": "У пограничній зоні або лабораторія позначила результат як пограничний чи сумнівний: значення близько до межі, за ним варто стежити.",
    },
    "changes.explain_first": {
        "en": "Inside its interval, with no earlier result of the same test to compare with.",
        "uk": "У межах інтервалу, але попереднього результату цього аналізу для порівняння немає.",
    },
    "changes.explain_stable": {
        "en": "Inside its interval now and last time.",
        "uk": "У межах інтервалу і зараз, і минулого разу.",
    },
    "changes.explain_unjudged": {
        "en": "No reference interval applies to this result, many tests have no universal target, so it is shown without a verdict.",
        "uk": "Для цього результату немає відповідного референтного інтервалу (у багатьох аналізів універсальної норми просто немає), тож його показано без оцінки.",
    },
    "changes.legend_heading": {"en": "What these labels mean", "uk": "Що означають ці позначки"},
    "changes.legend_source": {
        "en": "Verdicts are the same ones each test's own page shows, from the reference sources cited there. "
              "Open a test to see its interval and its sources.",
        "uk": "Оцінки ті самі, що на сторінці кожного показника, і спираються на наведені там джерела. Відкрийте показник, щоб побачити його інтервал і джерела.",
    },
    "changes.legend_change": {
        "en": "\"Change\" compares with the previous result of the same test. It is shown only when both are in the "
              "same unit; the percentage is relative to the previous value.",
        "uk": "«Зміна» порівнює значення з попереднім результатом того самого аналізу. Її показуємо, лише коли обидва результати в однакових одиницях; відсоток рахуємо від попереднього значення.",
    },
    "changes.trend_label": {
        "en": "Trend, oldest to newest, {values} {unit}",
        "uk": "Динаміка від найстарішого до найновішого: {values} {unit}",
    },
    "changes.was_on": {"en": "was {value} on {date}", "uk": "було {value} ({date})"},
    "changes.legend_trend": {
        "en": "Each chart shows this result and up to four readings before it, oldest on the left, with the value on every point. The filled dot is this result; the shaded strip is the range you should be in for this test, when one is known.",
        "uk": "Кожен графік показує цей результат і до чотирьох попередніх вимірювань: найстаріше ліворуч, значення підписане біля кожної точки. Зафарбована точка означає цей результат, а затінена смуга показує референтний інтервал цього аналізу, якщо він відомий.",
    },
    "changes.no_previous": {"en": "No earlier result", "uk": "Попереднього результату немає"},
    "changes.units_differ": {"en": "Not comparable: different units", "uk": "Не порівняти: різні одиниці"},
    "changes.no_change": {"en": "No change", "uk": "Без змін"},
    "changes.delta": {"en": "{amount} ({percent})", "uk": "{amount} ({percent})"},
    "changes.percent": {"en": "{value}%", "uk": "{value} %"},
    "changes.open_source": {"en": "Open in document", "uk": "Відкрити в документі"},
    "changes.nothing_open": {
        "en": "Nothing new, resolved or outside range in this period.",
        "uk": "За цей період немає ні нових відхилень, ні результатів, що повернулися в норму або лишаються поза нею.",
    },
    "changes.empty_title": {"en": "No results to compare yet", "uk": "Ще немає результатів для порівняння"},
    "changes.empty_body": {
        "en": "Upload a laboratory report and its values appear here, each compared with the previous result of the same test.",
        "uk": "Завантажте результати з лабораторії: їхні значення з’являться тут, кожне поруч із попереднім результатом того самого аналізу.",
    },
    "changes.document_empty_body": {
        "en": "No laboratory values were read from this document, so it changed no results.",
        "uk": "З цього документа не зчитано лабораторних значень, тож результати не змінилися.",
    },
    "changes.empty_cta": {"en": "Upload a report", "uk": "Завантажити результати"},
    "changes.dashboard_body": {
        "en": "Your newest results beside the previous ones: new problems, resolved, still outside range.",
        "uk": "Найновіші результати поруч із попередніми: нові проблеми, нормалізовані, досі поза інтервалом.",
    },
    "changes.insights_link": {"en": "See what your latest results changed", "uk": "Подивитися, що змінили найновіші результати"},
    "changes.document_link": {"en": "What this document changed", "uk": "Що змінив цей документ"},
    "changes.ai_eyebrow": {"en": "AI short state", "uk": "Коротко від ШІ"},
    "changes.ai_heading": {"en": "Where things stand", "uk": "Загальна картина"},
    "changes.ai_badge": {"en": "AI-generated", "uk": "Створено ШІ"},
    "changes.ai_meta": {"en": "Written {date}", "uk": "Написано {date}"},
    # Closed by default: the summary is advisory, so the page leads with the
    # changes themselves and offers the summary after them.
    "changes.ai_teaser_empty": {
        "en": "Ask an AI model to explain the newest changes in plain language.",
        "uk": "Попросіть ШІ простими словами пояснити, що змінилося останнім часом.",
    },
    "changes.ai_note_summary": {"en": "AI explanation", "uk": "Пояснення ШІ"},
    "changes.ai_note_disclaimer": {
        "en": "Written by an AI model; advisory only, not a diagnosis.",
        "uk": "Це написала модель ШІ. Лише для довідки, це не діагноз.",
    },
    "changes.ai_disclaimer": {
        "en": "Written by an AI model from the changes on this page. Advisory only: it can be wrong, it is not a "
              "diagnosis and it does not replace a clinician. The values and verdicts on this page are the record.",
        "uk": "Це написала модель ШІ на основі змін на цій сторінці. Лише для довідки: ШІ може помилятися, це не діагноз і не заміна консультації лікаря. Опирайтеся на значення та оцінки на цій сторінці: саме вони записані у вашій картці.",
    },
    "changes.ai_privacy": {
        "en": "The button sends the changes for the newest dates. Test names, values, units, dates, earlier readings, reference ranges and range labels, "
              "without your name or date of birth, to the AI service your administrator configured.",
        "uk": "Кнопка надсилає зміни за останні дати до сервісу ШІ, який налаштував адміністратор: назви показників, значення, одиниці, дати, попередні вимірювання, референтні інтервали й оцінки щодо них. Ваше ім’я та дату народження не надсилаємо.",
    },
    "changes.ai_generate": {"en": "Ask AI to explain these changes", "uk": "Попросити ШІ пояснити зміни"},
    "changes.ai_regenerate": {"en": "Explain again", "uk": "Пояснити ще раз"},
    "changes.ai_stale": {
        "en": "Your results changed after this summary was written. Regenerate it for an up-to-date state.",
        "uk": "Після цього підсумку ваші результати змінилися. Оновіть його, щоб побачити актуальну картину.",
    },
    "changes.ai_what_it_is": {"en": "What it is:", "uk": "Що це:"},
    "changes.ai_possible_reasons": {"en": "Common reasons for a result like this", "uk": "Поширені причини такого результату"},
    "changes.ai_usually_next": {"en": "What is usually done next", "uk": "Що зазвичай роблять далі"},
    "changes.ai_ask": {"en": "Questions to ask your doctor", "uk": "Що запитати в лікаря"},
    "changes.ai_levels_heading": {"en": "What the levels mean", "uk": "Що означають рівні"},
    "changes.ai_level_slight": {"en": "Slight", "uk": "Незначний"},
    "changes.ai_level_moderate": {"en": "Moderate", "uk": "Помірний"},
    "changes.ai_level_marked": {"en": "Marked", "uk": "Виражений"},
    "changes.ai_level_urgent": {"en": "Urgent", "uk": "Терміновий"},
    "changes.ai_level_slight_hint": {
        "en": "The AI's estimate: just outside the range. Commonly not significant on its own.",
        "uk": "Оцінка ШІ: трохи за межами норми. Саме по собі це часто не має значення.",
    },
    "changes.ai_level_moderate_hint": {
        "en": "The AI's estimate: clearly outside the range. Worth raising at your next routine visit.",
        "uk": "Оцінка ШІ: помітно за межами норми. Варто обговорити з лікарем на найближчому плановому прийомі.",
    },
    "changes.ai_level_marked_hint": {
        "en": "The AI's estimate: far outside the range or steadily worsening. Worth seeing a doctor about soon.",
        "uk": "Оцінка ШІ: значно за межами норми або стабільно погіршується. Варто найближчим часом звернутися до лікаря.",
    },
    "changes.ai_level_urgent_hint": {
        "en": "The AI's estimate: a value that usually needs prompt medical attention. Contact a clinician.",
        "uk": "Оцінка ШІ: таке значення зазвичай потребує, щоб його якнайшвидше оцінив лікар. Зверніться до лікаря.",
    },
    "changes.ai_improved": {"en": "Improved", "uk": "Що покращилося"},
    "changes.ai_attention": {"en": "Needs attention", "uk": "Що потребує уваги"},
    "changes.ai_discuss": {"en": "Worth discussing with a clinician", "uk": "Що варто обговорити з лікарем"},
    "changes.ai_forbidden": {
        "en": "Only the record's owner can ask for an AI summary.",
        "uk": "Підсумок від ШІ може замовити лише власник картки.",
    },
    "changes.ai_nothing": {"en": "There are no changes to summarise.", "uk": "Змін для підсумку немає."},
    "changes.ai_error_in_progress": {
        "en": "A summary is already being written. Keep this page open; it appears when ready.",
        "uk": "Підсумок уже пишеться. Не закривайте сторінку: він з’явиться тут, щойно буде готовий.",
    },
    # Linked measurements (panels.MEASUREMENT_TWINS): one quantity reaching
    # the record from a document and from a device.
    "twin.sources_both": {"en": "Documents and devices", "uk": "Документи й пристрої"},
    "twin.source_clinic": {"en": "Medical document", "uk": "Медичний документ"},
    "twin.source_device": {"en": "Device", "uk": "Пристрій"},
    "twin.source_method": {"en": "Device, measured another way", "uk": "Пристрій, інший спосіб вимірювання"},
    "twin.compare_sources": {"en": "Compare device sources", "uk": "Порівняти джерела пристроїв"},
    "twin.device_row": {"en": "Daily value chosen from your devices", "uk": "Денне значення, вибране з ваших пристроїв"},
    "twin.history_note": {
        "en": "This list joins readings from medical documents with the daily values your devices recorded. A day that a home-monitoring report printed and the device also sent is listed once, from the device.",
        "uk": "Тут разом показано значення з медичних документів і денні значення, які записали ваші пристрої. День, який надрукував звіт домашнього моніторингу і який надіслав сам пристрій, показано один раз, за даними пристрою.",
    },
    "twin.legend_aria": {"en": "What the chart markers mean", "uk": "Що означають позначки на графіку"},
    "twin.legend_clinic": {"en": "Square: a reading from a medical document", "uk": "Квадрат: значення з медичного документа"},
    "twin.legend_device": {"en": "Circle: a daily value from a device", "uk": "Коло: денне значення з пристрою"},
    "twin.legend_method": {
        "en": "Hollow circle, dashed line: measured another way, judged on its own",
        "uk": "Порожнє коло, пунктир: інший спосіб вимірювання, оцінений окремо",
    },
    "twin.eyebrow": {"en": "Devices", "uk": "Пристрої"},
    "twin.heading": {"en": "This measurement on your devices", "uk": "Цей показник на ваших пристроях"},
    "twin.method_judged": {
        "en": "Judged against its own published reference, never against the clinic reading.",
        "uk": "Оцінено за власним опублікованим орієнтиром, а не за значенням, виміряним у закладі.",
    },
    "twin.relation_same": {"en": "Same measurement", "uk": "Те саме вимірювання"},
    "twin.relation_method": {"en": "Measured another way", "uk": "Виміряно інакше"},
    "twin.relation_related": {"en": "Related, not the same", "uk": "Пов’язаний, але інший показник"},
    "twin.links_aria": {"en": "Where else this measurement is read", "uk": "Де ще видно цей показник"},
    "twin.compare_page": {
        "en": "This page compares what each device recorded.",
        "uk": "На цій сторінці можна порівняти, що записав кожен пристрій.",
    },
    "twin.open_concept_same": {"en": "{name}: with your medical documents", "uk": "{name}: разом із медичними документами"},
    "twin.open_concept_method": {"en": "{name}: from your medical documents", "uk": "{name}: з медичних документів"},
    "twin.open_concept_related": {"en": "{name}: from your medical documents", "uk": "{name}: з медичних документів"},
    "twin.open_panel": {"en": "Panel: {name}", "uk": "Панель: {name}"},
    "twin.why_body_weight": {
        "en": "A home scale and a clinic's scales weigh the same thing, so their readings form one series on the body weight page.",
        "uk": "Домашні й медичні ваги вимірюють те саме, тому їхні значення утворюють один ряд на сторінці маси тіла.",
    },
    "twin.why_body_height": {
        "en": "Height from your health app or device profile and height measured at a visit are one measurement, read together on the height page.",
        "uk": "Зріст із застосунку здоров’я чи профілю пристрою і зріст, виміряний на прийомі, це одне вимірювання, тож їх показано разом на сторінці зросту.",
    },
    "twin.why_body_mass_index": {
        "en": "BMI from a smart scale and BMI calculated at a visit are the same number, weight divided by height squared, read as one series.",
        "uk": "ІМТ із розумних ваг і ІМТ, розрахований на прийомі, це те саме число: маса, поділена на квадрат зросту. Їх показано одним рядом.",
    },
    "twin.why_systolic_blood_pressure": {
        "en": "The cuff's readings and the ones printed in its home-monitoring report are the same measurements, so each day is shown once, on the systolic pressure page.",
        "uk": "Вимірювання тонометра і ті, що надруковані в його звіті домашнього моніторингу, однакові, тому кожен день показано один раз, на сторінці систолічного тиску.",
    },
    "twin.why_diastolic_blood_pressure": {
        "en": "The cuff's readings and the ones printed in its home-monitoring report are the same measurements, so each day is shown once, on the diastolic pressure page.",
        "uk": "Вимірювання тонометра і ті, що надруковані в його звіті домашнього моніторингу, однакові, тому кожен день показано один раз, на сторінці діастолічного тиску.",
    },
    "twin.why_blood_pressure_pulse": {
        "en": "The pulse a cuff records with each blood pressure reading and a pulse counted at a visit are the same measurement, read together on the pulse page.",
        "uk": "Пульс, який тонометр записує з кожним вимірюванням тиску, і пульс, порахований на прийомі, це одне вимірювання, тож їх показано разом на сторінці пульсу.",
    },
    "twin.why_ecg_heart_rate": {
        "en": "An ECG recording gives the same heart rate whether it came from the device or from its exported report, so each recording is shown once.",
        "uk": "Запис ЕКГ дає ту саму частоту серцевих скорочень, чи надійшов він із пристрою, чи з експортованого звіту, тому кожен запис показано один раз.",
    },
    "twin.why_blood_oxygen": {
        "en": "A clinic measures oxygen saturation once, with a fingertip probe. A watch or ring averages its sensor over a night or a day, which reads lower and varies more, so the two are drawn side by side and each is judged on its own.",
        "uk": "У закладі сатурацію вимірюють один раз, датчиком на пальці. Годинник чи кільце усереднюють свій датчик за ніч або добу, і таке значення зазвичай нижче та більше коливається. Тому їх показано поруч, і кожне оцінено окремо.",
    },
    "twin.why_resting_heart_rate": {
        "en": "Resting heart rate is the watch's estimate of your lowest steady rate across a day. A pulse counted at a visit is one moment, often just after walking in, and tends to read higher.",
        "uk": "ЧСС у спокої це оцінка годинника: найнижча стала частота за добу. Пульс на прийомі це одна мить, часто одразу після того, як ви зайшли, тому він зазвичай вищий.",
    },
    "twin.why_daily_heart_rate": {
        "en": "Daily heart rate averages every reading of the day, activity included, so it runs above a pulse taken at rest.",
        "uk": "Денна ЧСС усереднює всі вимірювання за добу, разом із рухом, тому вона вища за пульс, виміряний у спокої.",
    },
    "twin.why_respiratory_rate": {
        "en": "Your device measures breathing rate during sleep. A clinic counts breaths once, awake and at rest, so the two answer different questions.",
        "uk": "Пристрій вимірює частоту дихання уві сні. У закладі вдихи рахують один раз, коли ви не спите й відпочиваєте, тож ці числа відповідають на різні питання.",
    },
    "twin.why_sleeping_wrist_temperature": {
        "en": "Wrist temperature is skin temperature during sleep, several degrees below core body temperature. It shows change from night to night, not fever.",
        "uk": "Температура зап’ястя це температура шкіри уві сні, на кілька градусів нижча за температуру тіла. Вона показує зміни від ночі до ночі, а не гарячку.",
    },
    "twin.why_temperature_deviation": {
        "en": "Temperature deviation is how far a night's skin temperature differs from your own usual level. It is a difference, not a body temperature.",
        "uk": "Відхилення температури показує, наскільки температура шкіри за ніч відрізняється від вашого звичного рівня. Це різниця, а не температура тіла.",
    },
    # "Not my reading": readings a shared scale or a handed-down watch wrote
    # into the wrong person's record (devices/exclusions.py).
    "exclusions.eyebrow": {"en": "Not my reading", "uk": "Не моє вимірювання"},
    "exclusions.list_title": {"en": "Excluded readings", "uk": "Виключені вимірювання"},
    "exclusions.list_link": {"en": "Excluded readings", "uk": "Виключені вимірювання"},
    "exclusions.back": {"en": "Back", "uk": "Назад"},
    "exclusions.back_metric": {"en": "Back to {name}", "uk": "Назад до показника «{name}»"},
    "exclusions.review_title": {"en": "Check readings: {name}", "uk": "Перевірка вимірювань: {name}"},
    "exclusions.review_heading": {"en": "{name} on {date}", "uk": "{name}, {date}"},
    "exclusions.origin_app": {"en": "App that wrote it", "uk": "Застосунок, що записав"},
    "exclusions.origin_device": {"en": "Device", "uk": "Пристрій"},
    "exclusions.device_unnamed": {"en": "not named by the source", "uk": "джерело не вказало"},
    "exclusions.stored_value": {"en": "Value stored for this day", "uk": "Значення за цей день"},
    "exclusions.typical": {"en": "Your usual value (median)", "uk": "Ваше звичне значення (медіана)"},
    "exclusions.what_happens": {
        "en": "Readings from a shared scale, or from a phone or watch someone else also uses, can land in your record. Excluding one removes it from every chart, average, trend and assessment here, and the day is recalculated straight away. The original stays in the archive untouched, a later sync or re-import of the same data keeps it out, and you can undo it at any time under Excluded readings.",
        "uk": "Вимірювання зі спільних ваг або з телефона чи годинника, яким користується ще хтось, можуть потрапити до вашої картки. Виключене вимірювання зникає з усіх графіків, середніх значень, трендів і оцінок, а день одразу перераховується. Оригінал лишається в архіві без змін, наступна синхронізація чи повторний імпорт тих самих даних його не повернуть, а скасувати виключення можна будь-коли в розділі «Виключені вимірювання».",
    },
    "exclusions.readings_heading": {"en": "Single readings this day", "uk": "Окремі вимірювання цього дня"},
    "exclusions.readings_intro": {
        "en": "Each line is one moment a device recorded. Not my reading excludes everything recorded at that moment, for example the weight, BMI and body fat of one weigh-in.",
        "uk": "Кожен рядок - одна мить, коли пристрій зробив запис. «Не моє вимірювання» виключає все, що записано в цю мить, наприклад вагу, ІМТ і відсоток жиру одного зважування.",
    },
    "exclusions.same_moment": {"en": "Recorded at the same moment", "uk": "Записано в ту саму мить"},
    "exclusions.state_excluded": {"en": "Excluded", "uk": "Виключено"},
    "exclusions.far_pill": {"en": "Far from your usual value", "uk": "Далеко від вашого звичного"},
    "exclusions.far_hint": {
        "en": "More than 30% away from your median of {typical}. That can be a real change, or someone else's reading. Nothing is excluded unless you choose to.",
        "uk": "Відрізняється від вашої медіани {typical} більш ніж на 30%. Це може бути справжня зміна або чуже вимірювання. Нічого не виключається, доки ви цього не оберете.",
    },
    "exclusions.not_mine": {"en": "Not my reading", "uk": "Не моє вимірювання"},
    "exclusions.no_single_readings": {
        "en": "This source sends one total for the day rather than single readings, so the whole day's value is what can be excluded.",
        "uk": "Це джерело надсилає один підсумок за день, а не окремі вимірювання, тож виключити можна лише значення за весь день.",
    },
    "exclusions.no_single_readings_file": {
        "en": "This source arrives from a file export or the provider's own connection, which store daily values here rather than single readings. Exclude the whole day's value below, or a period with exact start and end times further down.",
        "uk": "Це джерело надходить із файлу експорту або з прямого підключення до постачальника, де зберігаються денні значення, а не окремі вимірювання. Виключіть значення за весь день нижче або період із точними початком і кінцем ще нижче.",
    },
    "exclusions.not_mine_day": {"en": "Not my value for this day: {name}", "uk": "Не моє значення за цей день: {name}"},
    "exclusions.window_heading": {"en": "Exclude a period", "uk": "Виключити період"},
    "exclusions.window_intro": {
        "en": "For values a device calculated from someone else's reading. A watch estimates resting and total energy from the last weight it was given, so a partner's weigh-in inflates them until the next one of yours. Choose when it started and ended, and which measurements of this source to drop. A daily total that overlaps the period is removed for the whole day.",
        "uk": "Для значень, які пристрій обчислив із чужого вимірювання. Годинник оцінює енергію спокою і загальну витрату енергії за останньою отриманою вагою, тож зважування партнера завищує їх до наступного вашого. Оберіть початок і кінець та показники цього джерела, які слід прибрати. Добовий підсумок, що перетинається з періодом, прибирається за весь день.",
    },
    "exclusions.window_from": {"en": "From (your local time)", "uk": "Від (ваш місцевий час)"},
    "exclusions.window_until": {"en": "Until (your local time)", "uk": "До (ваш місцевий час)"},
    "exclusions.window_series": {"en": "Measurements to exclude", "uk": "Показники, які виключити"},
    "exclusions.window_submit": {"en": "Exclude this period", "uk": "Виключити цей період"},
    "exclusions.origin_heading": {"en": "Not my device", "uk": "Не мій пристрій"},
    "exclusions.origin_intro": {
        "en": "Excludes everything {app} on {device} wrote into your record, past and future. Use it when the app or device belongs to someone else. Your other sources are not affected.",
        "uk": "Виключає все, що {app} на пристрої {device} записав до вашої картки, і раніше, і надалі. Обирайте це, якщо застосунок чи пристрій належить комусь іншому. Інші ваші джерела це не зачіпає.",
    },
    "exclusions.not_my_device": {"en": "Not my device", "uk": "Не мій пристрій"},
    "exclusions.belongs_label": {"en": "Whose reading is it? (optional)", "uk": "Чиє це вимірювання? (необов’язково)"},
    "exclusions.belongs_unknown": {"en": "Someone else, not named", "uk": "Когось іншого, без імені"},
    "exclusions.reason_label": {"en": "Note (optional)", "uk": "Примітка (необов’язково)"},
    "exclusions.th_action": {"en": "Action", "uk": "Дія"},
    "exclusions.check": {"en": "Check", "uk": "Перевірити"},
    "exclusions.metric_heading": {"en": "Readings that may not be yours", "uk": "Вимірювання, що можуть бути не вашими"},
    "exclusions.metric_active_one": {
        "en": "{value} exclusion applies here: the values on this page are calculated without the readings you marked as not yours.",
        "uk": "Тут діє {value} виключення: значення на цій сторінці обчислено без вимірювань, які ви позначили як не ваші.",
    },
    "exclusions.metric_active_few": {
        "en": "{value} exclusions apply here: the values on this page are calculated without the readings you marked as not yours.",
        "uk": "Тут діють {value} виключення: значення на цій сторінці обчислено без вимірювань, які ви позначили як не ваші.",
    },
    "exclusions.metric_active_many": {
        "en": "{value} exclusions apply here: the values on this page are calculated without the readings you marked as not yours.",
        "uk": "Тут діють {value} виключень: значення на цій сторінці обчислено без вимірювань, які ви позначили як не ваші.",
    },
    "exclusions.suggest_intro": {
        "en": "These days are more than 30% away from your usual value of {typical}. A shared scale often looks like this. Check them and decide.",
        "uk": "Ці дні відрізняються від вашого звичного значення {typical} більш ніж на 30%. Так часто виглядають спільні ваги. Перевірте їх і вирішіть самі.",
    },
    "exclusions.suggest_never_auto": {
        "en": "A suggestion only: nothing is ever excluded without your confirmation.",
        "uk": "Це лише підказка: без вашого підтвердження нічого не виключається.",
    },
    "exclusions.list_intro": {
        "en": "Readings, periods and devices you marked as not yours. They are left out of every chart, average and assessment. Undo puts them back and recalculates the days they touched.",
        "uk": "Вимірювання, періоди й пристрої, які ви позначили як не ваші. Їх немає в жодному графіку, середньому значенні чи оцінці. «Скасувати» повертає їх і перераховує відповідні дні.",
    },
    "exclusions.why_summary": {"en": "Why did my values change?", "uk": "Чому змінилися мої значення?"},
    "exclusions.why_body": {
        "en": "Daily values are rebuilt from the original readings without the excluded ones. A day's weight becomes your own last weigh-in of that day, an average or total is recalculated without the removed readings, and a day that had only excluded readings disappears from charts. The originals are kept, so nothing is lost.",
        "uk": "Денні значення перебудовуються з оригінальних вимірювань без виключених. Вага за день стає вашим останнім зважуванням того дня, середнє чи сума перераховуються без прибраних вимірювань, а день, де були лише виключені вимірювання, зникає з графіків. Оригінали зберігаються, тож нічого не втрачено.",
    },
    "exclusions.scopes_body": {
        "en": "One reading: everything recorded at one moment. A period: chosen measurements of one source between two times. A device: everything one app on one device recorded.",
        "uk": "Одне вимірювання: усе, що записано в одну мить. Період: обрані показники одного джерела між двома моментами. Пристрій: усе, що записав один застосунок на одному пристрої.",
    },
    "exclusions.active_count_one": {"en": "{value} active exclusion", "uk": "{value} чинне виключення"},
    "exclusions.active_count_few": {"en": "{value} active exclusions", "uk": "{value} чинні виключення"},
    "exclusions.active_count_many": {"en": "{value} active exclusions", "uk": "{value} чинних виключень"},
    "exclusions.empty": {
        "en": "Nothing is excluded. To exclude a reading, open a device measurement, find the day in its daily values and choose Not my reading.",
        "uk": "Нічого не виключено. Щоб виключити вимірювання, відкрийте показник пристрою, знайдіть день серед денних значень і оберіть «Не моє вимірювання».",
    },
    "exclusions.undoing_heading": {"en": "Being restored", "uk": "Відновлюються"},
    "exclusions.scope_reading": {"en": "One reading", "uk": "Одне вимірювання"},
    "exclusions.scope_window": {"en": "A period", "uk": "Період"},
    "exclusions.scope_origin": {"en": "A whole device", "uk": "Увесь пристрій"},
    "exclusions.when_window": {"en": "{start} to {end}", "uk": "з {start} до {end}"},
    "exclusions.origin_line": {"en": "Written by {app} on {device}", "uk": "Записав {app} на пристрої {device}"},
    "exclusions.series_line": {"en": "Measurements: {series}", "uk": "Показники: {series}"},
    "exclusions.series_all": {"en": "all", "uk": "усі"},
    "exclusions.series_workouts": {"en": "Workouts", "uk": "Тренування"},
    "exclusions.series_events": {"en": "Events", "uk": "Події"},
    "exclusions.belongs_line": {"en": "Belongs to {name}", "uk": "Належить: {name}"},
    "exclusions.reason_line": {"en": "Note: {reason}", "uk": "Примітка: {reason}"},
    "exclusions.created": {"en": "Excluded on", "uk": "Виключено"},
    "exclusions.undo": {"en": "Undo", "uk": "Скасувати"},
    "exclusions.state_applied": {"en": "Applied", "uk": "Застосовано"},
    "exclusions.state_pending": {"en": "Recalculating", "uk": "Перераховується"},
    "exclusions.state_undoing": {"en": "Restoring", "uk": "Відновлюється"},
    "exclusions.status_applied": {
        "en": "Done. The affected days are recalculated without the excluded readings.",
        "uk": "Готово. Відповідні дні перераховано без виключених вимірювань.",
    },
    "exclusions.status_queued": {
        "en": "Saved. The affected days are being recalculated in the background; this can take a few minutes for a whole device. The state below changes to Applied when it is finished.",
        "uk": "Збережено. Відповідні дні перераховуються у фоні; для цілого пристрою це може тривати кілька хвилин. Коли все буде готово, стан нижче зміниться на «Застосовано».",
    },
    "exclusions.status_idle": {"en": "Nothing needed recalculating.", "uk": "Перераховувати нічого не довелося."},
    "exclusions.status_undone": {
        "en": "Undone. The readings are back and the days they touched are recalculated.",
        "uk": "Скасовано. Вимірювання повернуто, а відповідні дні перераховано.",
    },
    "exclusions.status_undo_queued": {
        "en": "Undone. The readings are being restored in the background; this can take a few minutes for a whole device.",
        "uk": "Скасовано. Вимірювання відновлюються у фоні; для цілого пристрою це може тривати кілька хвилин.",
    },
    "exclusions.err_time": {
        "en": "That date and time could not be read. Enter it again and try once more.",
        "uk": "Не вдалося прочитати дату й час. Введіть їх ще раз і повторіть.",
    },
    "exclusions.err_order": {
        "en": "The period ends before it starts. Swap the two times and try again.",
        "uk": "Період закінчується раніше, ніж починається. Поміняйте моменти місцями й повторіть.",
    },
    "exclusions.err_scope": {
        "en": "Choose one reading, a period or a whole device.",
        "uk": "Оберіть одне вимірювання, період або увесь пристрій.",
    },
    "exclusions.err_origin": {
        "en": "That source has written nothing into your record. Open the measurement again and choose the reading from its list.",
        "uk": "Це джерело нічого не записало до вашої картки. Відкрийте показник ще раз і оберіть вимірювання зі списку.",
    },
    "exclusions.err_series": {
        "en": "One of the chosen measurements is not in your record. Reload the page and choose again.",
        "uk": "Одного з обраних показників немає у вашій картці. Оновіть сторінку й оберіть ще раз.",
    },
    "exclusions.err_person": {
        "en": "That person does not share a record with you. Leave the field empty or choose someone from the list.",
        "uk": "Ця людина не ділиться з вами карткою. Залиште поле порожнім або оберіть когось зі списку.",
    },
    "exclusions.err_reason": {"en": "The note is longer than 500 characters. Shorten it and try again.", "uk": "Примітка довша за 500 символів. Скоротіть її й повторіть."},
    "exclusions.err_shared": {
        "en": "Only the owner of this record can exclude readings or undo an exclusion. Switch back to your own record to manage yours.",
        "uk": "Виключати вимірювання чи скасовувати виключення може лише власник картки. Поверніться до власної картки, щоб керувати своїми.",
    },
    # "Measure this again" on a result's page (/metrics/<id>)
    "metric.order_eyebrow": {"en": "Measure this again", "uk": "Здати ще раз"},
    "metric.order_heading": {"en": "Where to test and what it costs", "uk": "Де здати і скільки це коштує"},
    "metric.order_single": {"en": "Single test", "uk": "Окремий аналіз"},
    "metric.order_panel_cheaper": {"en": "Cheaper as part of a panel", "uk": "Дешевше у складі пакета"},
    "metric.order_panel_only": {"en": "Only as part of a panel", "uk": "Лише у складі пакета"},
    "metric.order_panel_count_one": {"en": "{count} result in the panel", "uk": "{count} показник у пакеті"},
    "metric.order_panel_count_few": {"en": "{count} results in the panel", "uk": "{count} показники в пакеті"},
    "metric.order_panel_count_many": {"en": "{count} results in the panel", "uk": "{count} показників у пакеті"},
    "metric.order_fee": {
        "en": "plus {fee} for sample collection, once per visit",
        "uk": "плюс {fee} за забір біоматеріалу, один раз за візит",
    },
    "metric.order_external": {"en": "opens {lab}'s page in a new tab", "uk": "відкриє сторінку {lab} у новій вкладці"},
    "metric.order_read_city": {"en": "Prices for {city} as of {date}.", "uk": "Ціни для міста {city} станом на {date}."},
    "metric.order_plan": {"en": "Plan this test", "uk": "Спланувати цей аналіз"},
    "metric.order_plan_hint": {
        "en": "Finds the cheapest way to take it, alone or with other tests.",
        "uk": "Підбере найдешевший спосіб здати його окремо чи разом з іншими аналізами.",
    },
    # Test planner (/plan-tests)
    "nav.plan_tests": {"en": "Plan tests", "uk": "Що здати"},
    "plan.title": {"en": "Plan your next lab tests", "uk": "Що здати наступного разу"},
    "plan.heading": {"en": "Plan your next lab tests", "uk": "Що здати наступного разу"},
    "plan.uah": {"en": "{amount} UAH", "uk": "{amount} грн"},
    "plan.search_item": {"en": "{lab}, {price}, results: {count}", "uk": "{lab}, {price}, показників: {count}"},
    "plan.latest": {"en": "Last result {value}, {date}", "uk": "Востаннє: {value}, {date}"},
    "plan.not_sold": {
        "en": "None of the labs here offers this test.",
        "uk": "Жодна з доступних лабораторій не робить цього аналізу.",
    },
    "plan.open_result": {"en": "History", "uk": "Історія"},
    "plan.notice_prices_changed": {
        "en": "A price changed after the plan was made, so nothing was ordered. The plan below uses today's prices: check the total and order again.",
        "uk": "Після складання плану змінилася ціна, тому замовлення не створено. Нижче план за актуальними цінами: перевірте суму й замовте знову.",
    },
    "plan.notice_items_gone": {
        "en": "Some tests in this plan are no longer in the lab's price list. Build the plan again.",
        "uk": "Деяких аналізів із цього плану вже немає в прайсі лабораторії. Складіть план ще раз.",
    },
    "plan.notice_order_failed": {
        "en": "Esculab did not accept the order: nothing was created or paid. Try again. If it keeps failing, sign in to Esculab again on your profile.",
        "uk": "Esculab не прийняла замовлення: нічого не створено й не оплачено. Спробуйте ще раз. Якщо помилка повториться, увійдіть в Esculab заново в профілі.",
    },
    "plan.notice_cart_failed": {
        "en": "Synevo did not take the tests into your cart: nothing was ordered. Try again. If it keeps failing, reconnect Synevo on your profile.",
        "uk": "Synevo не додала аналізи до кошика: нічого не замовлено. Спробуйте ще раз. Якщо помилка повториться, підключіть Synevo заново в профілі.",
    },
    "plan.notice_esculab_not_connected": {
        "en": "To order from Esculab, first connect your Esculab account on your profile and pick yourself among its people.",
        "uk": "Щоб замовити в Esculab, підключіть свій обліковий запис Esculab у профілі й позначте, хто з людей у ньому ви.",
    },
    "plan.no_labs_title": {"en": "No lab is switched on", "uk": "Жодної лабораторії не ввімкнено"},
    "plan.no_labs_body": {
        "en": "The planner takes prices from the labs an administrator switches on under Lab connections.",
        "uk": "Планувальник бере ціни лабораторій, які адміністратор увімкнув у розділі «Підключення лабораторій».",
    },
    "plan.no_labs_admin": {"en": "Open lab connections", "uk": "Відкрити підключення лабораторій"},
    "plan.crawling": {
        "en": "{lab}'s price list is still loading, a page at a time to spare the lab's site. {lab} joins the plan once it is complete.",
        "uk": "Прайс {lab} ще завантажується, сторінка за сторінкою, щоб не перевантажувати сайт лабораторії. {lab} з’явиться в плані, щойно прайс завантажиться повністю.",
    },
    "plan.needs_heading": {"en": "What to measure", "uk": "Що виміряти"},
    "plan.needs_none": {
        "en": "Nothing in your record is out of range or due for a retest. Search below to add any test.",
        "uk": "У картці немає показників поза нормою чи таких, які час повторити. Знайдіть потрібний аналіз нижче.",
    },
    "plan.optional_one": {"en": "{count} more result out of range, usually not repeated", "uk": "Ще {count} показник поза нормою, який зазвичай не повторюють"},
    "plan.optional_few": {"en": "{count} more results out of range, usually not repeated", "uk": "Ще {count} показники поза нормою, які зазвичай не повторюють"},
    "plan.optional_many": {"en": "{count} more results out of range, usually not repeated", "uk": "Ще {count} показників поза нормою, які зазвичай не повторюють"},
    "plan.optional_lead": {
        "en": "Allergy antibodies (specific IgE) and cultures: an out-of-range value alone is usually no reason to repeat them. Tick any you want anyway.",
        "uk": "Специфічні IgE (антитіла до алергенів) і бактеріологічні посіви: саме лише відхилення від норми зазвичай не причина їх повторювати. Позначте ті, які все ж хочете здати.",
    },
    "plan.added_heading": {"en": "Added by you", "uk": "Ви додали"},
    "plan.search_label": {
        "en": "Find or add a test",
        "uk": "Знайти або додати аналіз",
    },
    "plan.search_submit": {"en": "Search", "uk": "Знайти"},
    "plan.search_hint": {
        "en": "Filters your list and finds tests to add: a name, abbreviation or code, for example ferritin, TSH or F1003. Panels are in the next section.",
        "uk": "Фільтрує ваш список і знаходить аналізи, яких у ньому ще немає: назва, скорочення або код, наприклад феритин, ТТГ чи F1003. Пакети шукайте в наступному розділі.",
    },
    "plan.results_legend": {
        "en": "Not on your list yet",
        "uk": "Ще не у списку",
    },
    "plan.adds": {"en": "Adds: {names}", "uk": "Додасть: {names}"},
    "plan.search_offers": {"en": "Single test: {offers}", "uk": "Окремим аналізом: {offers}"},
    "plan.results_none": {
        "en": "No other tests found for \"{query}\". Try a shorter word or the test code.",
        "uk": "Інших аналізів за запитом «{query}» не знайдено. Спробуйте коротше слово або код аналізу.",
    },
    "plan.doctor_lead": {
        "en": "You are viewing as the patient's doctor. Ordering stays with the patient: tick the tests, then save the selection. It waits for them at the top of this page, to review, change and order.",
        "uk": "Ви переглядаєте як лікар пацієнта. Замовляє сам пацієнт: позначте аналізи й збережіть вибір. Він чекатиме пацієнта вгорі цієї сторінки, щоб переглянути, змінити й замовити.",
    },
    "plan.suggest_submit": {"en": "Save for the patient", "uk": "Зберегти для пацієнта"},
    "plan.suggest_saving": {"en": "Saving...", "uk": "Зберігаємо..."},
    "plan.notice_suggestion_saved": {
        "en": "Saved. The patient will see this selection when they open the test planner.",
        "uk": "Збережено. Пацієнт побачить цей вибір, коли відкриє планувальник аналізів.",
    },
    "plan.notice_suggestion_empty": {
        "en": "Nothing is ticked, so there is nothing to save yet.",
        "uk": "Нічого не позначено, тож зберігати поки нічого.",
    },
    "plan.suggestion_heading": {"en": "Your doctor's selection", "uk": "Вибір вашого лікаря"},
    "plan.suggestion_saved": {"en": "Saved {date}", "uk": "Збережено {date}"},
    "plan.suggestion_lead": {
        "en": "Open it to see the plan your doctor built, change what you want, and order.",
        "uk": "Відкрийте, щоб побачити план, складений лікарем, змінити що потрібно й замовити.",
    },
    "plan.suggestion_open": {"en": "Open and review", "uk": "Відкрити й переглянути"},
    "plan.suggestion_dismiss": {"en": "Dismiss", "uk": "Приховати"},
    "plan.samples_legend": {"en": "Samples you will not give", "uk": "Зразки, які ви не здаватимете"},
    "plan.samples_hint": {
        "en": "Tick a sample to leave out every test that needs it, even when it is the only way to measure a result. For blood tests only, tick urine and the rest.",
        "uk": "Позначте зразок, і всі аналізи, яким він потрібен, зникнуть зі списку й плану, навіть якщо показник інакше не виміряти. Щоб лишити тільки кров, позначте сечу та решту.",
    },
    "plan.sample_blood": {"en": "Blood", "uk": "Кров"},
    "plan.sample_blood_hint": {"en": "From a vein or a finger", "uk": "З вени чи з пальця"},
    "plan.sample_blood_short": {"en": "blood", "uk": "кров"},
    "plan.sample_urine": {"en": "Urine", "uk": "Сеча"},
    "plan.sample_urine_hint": {"en": "Morning or 24-hour collection", "uk": "Ранкова або добова"},
    "plan.sample_urine_short": {"en": "urine", "uk": "сеча"},
    "plan.sample_stool": {"en": "Stool", "uk": "Кал"},
    "plan.sample_stool_hint": {"en": "Collected at home", "uk": "Збирають удома"},
    "plan.sample_stool_short": {"en": "stool", "uk": "кал"},
    "plan.sample_swab": {"en": "Swabs and scrapings", "uk": "Мазки й зішкріби"},
    "plan.sample_swab_hint": {"en": "Throat, nose, genital tract, cervix", "uk": "Із зіва, носа, статевих шляхів, шийки матки"},
    "plan.sample_swab_short": {"en": "swabs", "uk": "мазки"},
    "plan.sample_saliva": {"en": "Saliva", "uk": "Слина"},
    "plan.sample_saliva_hint": {"en": "Some DNA tests", "uk": "Для деяких ДНК-тестів"},
    "plan.sample_saliva_short": {"en": "saliva", "uk": "слина"},
    "plan.sample_semen": {"en": "Semen and prostate fluid", "uk": "Сперма й секрет простати"},
    "plan.sample_semen_hint": {"en": "Fertility and urology tests", "uk": "Для аналізів на фертильність і урологічних"},
    "plan.sample_semen_short": {"en": "semen", "uk": "сперма"},
    "plan.sample_other": {"en": "Other samples", "uk": "Інші зразки"},
    "plan.sample_other_hint": {"en": "Biopsy, spinal fluid, hair, nails and the like", "uk": "Біопсія, спинномозкова рідина, волосся, нігті тощо"},
    "plan.sample_other_short": {"en": "other samples", "uk": "інші зразки"},
    "plan.sum_without": {"en": "leaving out {samples}", "uk": "без: {samples}"},
    "plan.samples_out_one": {"en": "{count} result left off your list:", "uk": "Зі списку знято {count} показник:"},
    "plan.samples_out_few": {"en": "{count} results left off your list:", "uk": "Зі списку знято {count} показники:"},
    "plan.samples_out_many": {"en": "{count} results left off your list:", "uk": "Зі списку знято {count} показників:"},
    "plan.tile_edited": {"en": "Changed by you", "uk": "Змінено вами"},
    "plan.order_missing": {
        "en": "This order does not cover: {names}.",
        "uk": "Це замовлення не охоплює: {names}.",
    },
    "plan.order_cut": {"en": "Remove from the order", "uk": "Прибрати із замовлення"},
    "plan.order_cut_heading": {"en": "Removed", "uk": "Прибрано"},
    "plan.order_put_back": {"en": "Put back", "uk": "Повернути"},
    "plan.order_reset": {"en": "Undo my changes", "uk": "Скасувати мої зміни"},
    "plan.order_search_label": {"en": "Find or add a test", "uk": "Знайти або додати аналіз"},
    "plan.order_search_hint": {
        "en": "Filters this order and finds more {lab} tests to add: a name, abbreviation or code.",
        "uk": "Фільтрує це замовлення й знаходить інші аналізи {lab}, щоб додати: назва, скорочення або код.",
    },
    "plan.order_list_none": {"en": "Nothing in this order matches.", "uk": "У замовленні збігів немає."},
    "plan.order_found": {"en": "{lab} also sells", "uk": "Ще є в {lab}"},
    "plan.order_add": {"en": "Add", "uk": "Додати"},
    "plan.order_more": {
        "en": "Showing {shown} of {total}. Type more of the name to narrow it down.",
        "uk": "Показано {shown} з {total}. Уточніть назву, щоб звузити пошук.",
    },
    "plan.order_none": {"en": "{lab} sells nothing by that name.", "uk": "У {lab} нічого з такою назвою немає."},
    "plan.where_heading": {"en": "Plan settings", "uk": "Налаштування плану"},
    "plan.where_lead": {
        "en": "Prices and collection points depend on the city.",
        "uk": "Від міста залежать ціни й пункти забору.",
    },
    "plan.submit": {"en": "Build the plan", "uk": "Скласти план"},
    "plan.building": {"en": "Building the plan...", "uk": "Складаю план..."},
    "plan.stale": {
        "en": "The list has changed since this plan was built. Press Build the plan to update it.",
        "uk": "Список змінився після того, як план склали. Натисніть «Скласти план», щоб оновити.",
    },
    "plan.ordering": {"en": "Creating the Esculab order...", "uk": "Створюю замовлення в Esculab..."},
    "plan.carting": {"en": "Adding to the Synevo cart...", "uk": "Додаю в кошик Synevo..."},
    "plan.result_heading": {"en": "Your plan", "uk": "Ваш план"},
    "plan.result_empty": {"en": "Nothing is selected. Tick at least one result above.", "uk": "Нічого не обрано. Позначте вище хоча б один показник."},
    "plan.result_no_catalog": {
        "en": "The labs' price lists have not loaded yet. Try again in a few minutes.",
        "uk": "Прайси лабораторій ще не завантажено. Спробуйте за кілька хвилин.",
    },
    "plan.best": {"en": "Cheapest", "uk": "Найдешевше"},
    "plan.filter_section_placeholder": {"en": "Type to find a section", "uk": "Почніть вводити назву розділу"},
    "plan.shelf_count_one": {"en": "{count} item", "uk": "{count} позиція"},
    "plan.shelf_count_few": {"en": "{count} items", "uk": "{count} позиції"},
    "plan.shelf_count_many": {"en": "{count} items", "uk": "{count} позицій"},
    "plan.city_one_label": {"en": "City", "uk": "Місто"},
    "plan.no_city": {
        "en": "{lab} has no collection point in {city}, so it is left out.",
        "uk": "У місті {city} немає пунктів забору {lab}, тому цю лабораторію не враховано.",
    },
    "plan.prefs_legend": {"en": "What matters more", "uk": "Що важливіше"},
    "plan.mode_cheapest": {"en": "Cheapest first", "uk": "Спершу найдешевше"},
    "plan.mode_cheapest_hint": {
        "en": " The lowest total for everything you picked. A slightly dearer option that adds many more results is shown beside it.",
        "uk": " Найменша сума за все обране. Якщо трохи дорожчий варіант дає набагато більше показників, його покажемо поруч.",
    },
    "plan.mode_complete": {"en": "Most complete", "uk": "Найповніше"},
    "plan.mode_complete_hint": {
        "en": " Everything you picked, plus every other result the lab's packages can add, whatever the price. Cheaper versions are listed under each lab.",
        "uk": " Усе обране й усі інші показники, які можуть додати пакети лабораторії, незалежно від ціни. Дешевші варіанти є під кожною лабораторією.",
    },
    "plan.pref_label": {"en": "Labs", "uk": "Лабораторії"},
    "plan.pref_any": {"en": "All labs", "uk": "Усі лабораторії"},
    "plan.pref_only": {"en": "Only {lab}", "uk": "Лише {lab}"},
    "plan.mixed_saving": {
        "en": "{saving} cheaper than a single lab, but you visit two labs and pay for sample collection twice.",
        "uk": "На {saving} дешевше, ніж в одній лабораторії, але доведеться відвідати дві лабораторії й двічі заплатити за забір біоматеріалу.",
    },
    "plan.repeats_one": {
        "en": "Also measures {count} result another test in the plan already gives.",
        "uk": "Також вимірює {count} показник, який уже дає інший аналіз у плані.",
    },
    "plan.repeats_few": {
        "en": "Also measures {count} results other tests in the plan already give.",
        "uk": "Також вимірює {count} показники, які вже дають інші аналізи в плані.",
    },
    "plan.repeats_many": {
        "en": "Also measures {count} results other tests in the plan already give.",
        "uk": "Також вимірює {count} показників, які вже дають інші аналізи в плані.",
    },
    "plan.needed_for": {
        "en": "It is in the plan for {names}: nothing else in it covers them.",
        "uk": "Він у плані заради: {names}. Інші позиції плану їх не дають.",
    },
    "plan.duplicate_cost": {
        "en": "Some results are measured twice in this plan: there is no cheaper way to cover everything you picked.",
        "uk": "Деякі показники в цьому плані визначаються двічі: дешевшого способу отримати все обране немає.",
    },
    "plan.option_current": {"en": "Shown now", "uk": "Зараз показано"},
    # plan page: inputs (needs, panels, where) -- new keys go below this line
    "plan.why_label": {"en": "Why listed", "uk": "Причина"},
    "plan.why_all": {"en": "All", "uk": "Усі"},
    "plan.why_flagged": {"en": "Out of range", "uk": "Поза нормою"},
    "plan.why_due": {"en": "Due again", "uk": "Час повторити"},
    "plan.needs_show_all": {"en": "Show all {count}", "uk": "Показати всі {count}"},
    "plan.needs_show_less": {"en": "Show fewer", "uk": "Згорнути"},
    "plan.presets_toggle": {"en": "Ready-made sets", "uk": "Готові набори"},
    "plan.preset_checkup": {"en": "Full check-up", "uk": "Повне обстеження"},
    "plan.preset_checkup_hint": {
        "en": "Every set below together, plus what the labs add to their most complete yearly check-ups: amylase, rheumatoid factor, ASO, total IgE, cortisol, and the AFP and CEA tumour markers. Untick what you do not need.",
        "uk": "Усі набори нижче разом, а також те, що лабораторії додають у свої найповніші щорічні check-up: амілаза, ревматоїдний фактор, АСЛ-О, загальний IgE, кортизол та онкомаркери АФП і РЕА. Зніміть позначки з того, що вам не потрібно.",
    },
    "plan.preset_basic": {"en": "Basic check", "uk": "Базове обстеження"},
    "plan.preset_basic_hint": {
        "en": "Full blood count, urinalysis, C-reactive protein, glucose, creatinine, urea, liver enzymes, bilirubin, potassium and sodium. For feeling unwell or a long gap since the last tests.",
        "uk": "Загальні аналізи крові й сечі, С-реактивний білок, глюкоза, креатинін, сечовина, печінкові ферменти, білірубін, калій і натрій. Коли нездужаєте або давно не перевірялися.",
    },
    "plan.preset_blood": {"en": "Full blood count", "uk": "Загальний аналіз крові"},
    "plan.preset_blood_hint": {
        "en": "Red cells with their indices, haemoglobin, platelets, white cells with the full differential and the erythrocyte sedimentation rate (ESR).",
        "uk": "Еритроцити та їхні індекси, гемоглобін, тромбоцити, лейкоцити з повною лейкоцитарною формулою і швидкість осідання еритроцитів (ШОЕ).",
    },
    "plan.preset_sugar": {"en": "Blood sugar", "uk": "Цукор крові"},
    "plan.preset_sugar_hint": {
        "en": "Glucose, HbA1c (average sugar over about three months), insulin and the HOMA-IR insulin resistance index, C-peptide and GAD antibodies (a sign of type 1 diabetes).",
        "uk": "Глюкоза, глікований гемоглобін (середній цукор приблизно за три місяці), інсулін та індекс інсулінорезистентності HOMA-IR, С-пептид і антитіла до GAD (ознака діабету 1 типу).",
    },
    "plan.preset_heart": {"en": "Heart and vessels", "uk": "Серце й судини"},
    "plan.preset_heart_hint": {
        "en": "Full lipid profile with apolipoproteins A1 and B and lipoprotein(a), homocysteine, C-reactive protein, creatine kinase, LDH, potassium, sodium, magnesium and fibrinogen.",
        "uk": "Повний ліпідний профіль з аполіпопротеїнами A1 і B та ліпопротеїном(а), гомоцистеїн, С-реактивний білок, креатинкіназа, ЛДГ, калій, натрій, магній і фібриноген.",
    },
    "plan.preset_thyroid": {"en": "Thyroid", "uk": "Щитоподібна залоза"},
    "plan.preset_thyroid_hint": {
        "en": "TSH (thyroid-stimulating hormone), free T4 and T3, antibodies to TPO and thyroglobulin (signs of autoimmune thyroiditis), thyroglobulin and calcitonin (checked when there is a nodule).",
        "uk": "Тиреотропний гормон (ТТГ), вільні Т4 і Т3, антитіла до ТПО й тиреоглобуліну (ознаки аутоімунного тиреоїдиту), тиреоглобулін і кальцитонін (їх перевіряють, коли є вузол).",
    },
    "plan.preset_liver": {"en": "Liver", "uk": "Печінка"},
    "plan.preset_liver_hint": {
        "en": "Liver enzymes (ALT, AST, GGT, alkaline phosphatase), bilirubin, total protein and albumin, prothrombin time and INR (how well the liver makes clotting factors), hepatitis B and C screening.",
        "uk": "Печінкові ферменти (АЛТ, АСТ, ГГТ, лужна фосфатаза), білірубін, загальний білок і альбумін, протромбіновий час і МНВ (наскільки печінка виробляє фактори згортання), скринінг гепатитів B і C.",
    },
    "plan.preset_kidneys": {"en": "Kidneys", "uk": "Нирки"},
    "plan.preset_kidneys_hint": {
        "en": "Creatinine with the filtration rate (eGFR), cystatin C, urea, uric acid, electrolytes, calcium, protein, urinalysis and the urine albumin-to-creatinine ratio (the earliest sign of kidney damage).",
        "uk": "Креатинін зі швидкістю клубочкової фільтрації, цистатин С, сечовина, сечова кислота, електроліти, кальцій, білок, загальний аналіз сечі та альбумін-креатинінове співвідношення в сечі (найраніша ознака ураження нирок).",
    },
    "plan.preset_iron": {"en": "Iron and anaemia", "uk": "Залізо й анемія"},
    "plan.preset_iron_hint": {
        "en": "Full blood count, ferritin (the body's iron stores), serum iron, transferrin and its saturation, iron-binding capacity, vitamin B12, folate and C-reactive protein (inflammation raises ferritin).",
        "uk": "Загальний аналіз крові, феритин (запаси заліза в організмі), сироваткове залізо, трансферин і його насичення, залізозв’язувальна здатність, вітамін B12, фолієва кислота та С-реактивний білок (запалення підвищує феритин).",
    },
    "plan.preset_vitamins": {"en": "Vitamins and minerals", "uk": "Вітаміни й мінерали"},
    "plan.preset_vitamins_hint": {
        "en": "Vitamin D, B12 and folate, ferritin and iron, magnesium, calcium, phosphorus, zinc, potassium, sodium and parathyroid hormone (which keeps calcium in balance).",
        "uk": "Вітамін D, B12 і фолієва кислота, феритин і залізо, магній, кальцій, фосфор, цинк, калій, натрій і паратгормон (він утримує баланс кальцію).",
    },
    "plan.preset_clotting": {"en": "Blood clotting", "uk": "Згортання крові"},
    "plan.preset_clotting_hint": {
        "en": "Prothrombin time and INR, APTT, thrombin time, fibrinogen and D-dimer. Before surgery, on blood thinners, or with easy bruising or bleeding.",
        "uk": "Протромбіновий час і МНВ, АЧТЧ, тромбіновий час, фібриноген і D-димер. Перед операцією, під час прийому антикоагулянтів або коли легко з’являються синці чи кровотечі.",
    },
    "plan.preset_men": {"en": "Men's health", "uk": "Чоловіче здоров’я"},
    "plan.preset_men_hint": {
        "en": "PSA, total and free (prostate), testosterone with SHBG, LH, FSH, prolactin, estradiol and DHEA-S.",
        "uk": "ПСА загальний і вільний (передміхурова залоза), тестостерон із ГЗСГ, ЛГ, ФСГ, пролактин, естрадіол і ДГЕА-С.",
    },
    "plan.preset_women": {"en": "Women's health", "uk": "Жіноче здоров’я"},
    "plan.preset_women_hint": {
        "en": "FSH, LH, estradiol, progesterone, prolactin, testosterone with SHBG, DHEA-S, and the CA-125, HE4 and CA 15-3 tumour markers. Hormones are best taken on the cycle day your doctor names.",
        "uk": "ФСГ, ЛГ, естрадіол, прогестерон, пролактин, тестостерон із ГЗСГ, ДГЕА-С та онкомаркери CA-125, HE4 і CA 15-3. Гормони краще здавати в день циклу, який назве лікар.",
    },
    "busy.loading": {"en": "Loading", "uk": "Завантаження"},
    "plan.untick_all": {"en": "Untick all", "uk": "Зняти всі"},
    "plan.preset_recent_one": {
        "en": "{count} more left out: measured in the last {days} days",
        "uk": "Ще {count} пропущено: здано за останні {days} днів",
    },
    "plan.preset_recent_few": {
        "en": "{count} more left out: measured in the last {days} days",
        "uk": "Ще {count} пропущено: здано за останні {days} днів",
    },
    "plan.preset_recent_many": {
        "en": "{count} more left out: measured in the last {days} days",
        "uk": "Ще {count} пропущено: здано за останні {days} днів",
    },
    "plan.recent_hint_many": {
        "en": "Leaves unticked {count} results on the list measured in the last {days} days.",
        "uk": "Не позначає {count} показників зі списку, зданих за останні {days} днів.",
    },
    "plan.recent_hint_few": {
        "en": "Leaves unticked {count} results on the list measured in the last {days} days.",
        "uk": "Не позначає {count} показники зі списку, здані за останні {days} днів.",
    },
    "plan.recent_hint_one": {
        "en": "Leaves unticked {count} result on the list measured in the last {days} days.",
        "uk": "Не позначає {count} показник зі списку, зданий за останні {days} днів.",
    },
    "plan.list_none": {
        "en": "Nothing on your list matches.",
        "uk": "У вашому списку збігів немає.",
    },
    "plan.preset_on": {"en": "Selected: all {total}", "uk": "Обрано: усі {total}"},
    "plan.preset_part": {"en": "Selected: {n} of {total}", "uk": "Обрано: {n} з {total}"},
    "plan.recent_switch": {
        "en": "Skip last {days} days",
        "uk": "Без зданого за {days} днів",
    },
    "plan.recent_today": {"en": "measured today", "uk": "здано сьогодні"},
    "plan.recent_ago_one": {"en": "measured {count} day ago", "uk": "здано {count} день тому"},
    "plan.recent_ago_few": {"en": "measured {count} days ago", "uk": "здано {count} дні тому"},
    "plan.recent_ago_many": {"en": "measured {count} days ago", "uk": "здано {count} днів тому"},
    "plan.never_measured": {"en": "Not in your record yet", "uk": "У вашій картці ще немає"},
    "plan.trend_label": {"en": "Trend of {name}", "uk": "Динаміка: {name}"},
    "plan.reset": {"en": "Reset", "uk": "Скинути"},
    "plan.results_capped": {
        "en": "Showing the {shown} closest of {total}. Narrow the search to see the rest.",
        "uk": "Показано {shown} найближчих із {total}. Уточніть запит, щоб побачити інші.",
    },
    "plan.search_failed": {
        "en": "Search did not respond. Check the connection and type again.",
        "uk": "Пошук не відповів. Перевірте з’єднання й спробуйте ввести ще раз.",
    },
    "plan.selected_label": {"en": "Selected:", "uk": "Обрано:"},
    "plan.sum_no_city": {"en": "No city chosen", "uk": "Місто не обрано"},
    "plan.sum_cheapest": {"en": "cheapest first", "uk": "спершу найдешевше"},
    "plan.sum_complete": {"en": "most complete", "uk": "найповніше"},
    "plan.sum_all_labs": {"en": "all labs", "uk": "усі лабораторії"},
    "plan.sum_only": {"en": "only {lab}", "uk": "лише {lab}"},
    # plan page: result (plan cards, options) -- new keys go below this line
    "plan.tile_items_one": {"en": "{count} item", "uk": "{count} позиція"},
    "plan.tile_items_few": {"en": "{count} items", "uk": "{count} позиції"},
    "plan.tile_items_many": {"en": "{count} items", "uk": "{count} позицій"},
    "plan.tile_saving": {"en": "discount {saving}", "uk": "знижка {saving}"},
    "plan.tile_options_one": {"en": "{count} fuller option", "uk": "Є {count} повніший варіант"},
    "plan.tile_options_few": {"en": "{count} fuller options", "uk": "Є {count} повніші варіанти"},
    "plan.tile_options_many": {"en": "{count} fuller options", "uk": "Є {count} повніших варіантів"},
    "plan.tile_complete": {"en": "{delta} more than the cheapest", "uk": "На {delta} дорожче за найдешевший"},
    "plan.tile_switched": {"en": "Fuller option shown, +{delta}", "uk": "Показано повніший варіант, +{delta}"},
    "plan.alts_heading": {"en": "More results for a little more", "uk": "Більше показників за невелику доплату"},
    "plan.alt_first": {"en": "Cheapest plan", "uk": "Найдешевший план"},
    "plan.alt_first_complete": {"en": "Most complete", "uk": "Найповніший"},
    "plan.alts_heading_complete": {
        "en": "Cheaper options, from the most complete down to the cheapest",
        "uk": "Дешевші варіанти: від найповнішого до найдешевшого",
    },
    "plan.tile_options_cheaper_one": {"en": "{count} cheaper option", "uk": "Є {count} дешевший варіант"},
    "plan.tile_options_cheaper_few": {"en": "{count} cheaper options", "uk": "Є {count} дешевші варіанти"},
    "plan.tile_options_cheaper_many": {"en": "{count} cheaper options", "uk": "Є {count} дешевших варіантів"},
    "plan.tile_switched_cheaper": {"en": "Cheaper option shown, {total}", "uk": "Показано дешевший варіант, {total}"},
    "plan.alt_gain_one": {"en": "{count} more result", "uk": "ще {count} показник"},
    "plan.alt_gain_few": {"en": "{count} more results", "uk": "ще {count} показники"},
    "plan.alt_gain_many": {"en": "{count} more results", "uk": "ще {count} показників"},
    "plan.alt_tracked": {"en": "{count} of them measured before", "uk": "з них {count} ви вже здавали"},
    "plan.alt_total": {"en": "Total {total}", "uk": "Разом {total}"},
    "plan.alt_which": {"en": "Which results", "uk": "Які саме показники"},
    "plan.alt_in_record": {"en": "measured before", "uk": "уже здавали"},
    "plan.alt_lost": {"en": "Leaves out: {names}", "uk": "Не ввійде: {names}"},
    "plan.option_use": {"en": "Show this plan", "uk": "Показати цей план"},
    "plan.total": {"en": "Total", "uk": "Разом"},
    "plan.covers": {"en": "Covers {covered} of {total}", "uk": "Охоплює {covered} з {total}"},
    "plan.list_price": {"en": "Price without discount", "uk": "Ціна без знижки"},
    "plan.code": {"en": "code {code}", "uk": "код {code}"},
    "plan.item_covers": {"en": "covers {names}", "uk": "з обраного: {names}"},
    "plan.extra_one": {"en": "{count} more result included", "uk": "ще {count} показник у складі"},
    "plan.extra_few": {"en": "{count} more results included", "uk": "ще {count} показники у складі"},
    "plan.extra_many": {"en": "{count} more results included", "uk": "ще {count} показників у складі"},
    "plan.discount": {"en": "{pct}% off today", "uk": "сьогодні знижка {pct}%"},
    "plan.fee_note": {"en": "Paid once per visit, however many tests you take.", "uk": "Сплачується один раз за візит, незалежно від кількості аналізів."},
    "plan.sum_tests": {"en": "Tests and panels", "uk": "Аналізи й пакети"},
    "plan.sum_fees": {"en": "Sample collection", "uk": "Забір біоматеріалу"},
    "plan.saving": {"en": "Saved by today's discounts", "uk": "Економія на сьогоднішніх знижках"},
    "plan.separately": {
        "en": "If each test were bought singly",
        "uk": "Якби брати кожен аналіз окремо",
    },
    "plan.missing": {
        "en": "Not available at this lab: {names}. You would need another lab for those.",
        "uk": "Тут не роблять: {names}. Їх доведеться здати в іншій лабораторії.",
    },
    "plan.not_exact": {
        "en": "So many combinations were possible that the search stopped after two minutes: this is the best plan found, not proven to be the best possible.",
        "uk": "Варіантів так багато, що пошук зупинився через дві хвилини: це найкращий зі знайдених планів, але не доведено, що кращого немає.",
    },
    "plan.prices_read": {"en": "Prices as of {date}.", "uk": "Ціни станом на {date}."},
    "plan.order_heading": {"en": "Order at Esculab", "uk": "Замовлення в Esculab"},
    "plan.order_lead": {
        "en": "The order goes to your Esculab account. Nothing is paid here: pay online on Esculab's page or at the collection point. You can cancel it in the Esculab app.",
        "uk": "Замовлення з’явиться у вашому обліковому записі Esculab. Тут нічого не сплачується: оплатіть онлайн на сторінці Esculab або в пункті забору. Скасувати замовлення можна в застосунку Esculab.",
    },
    "plan.order_point": {"en": "Collection point", "uk": "Пункт забору"},
    "plan.order_date": {"en": "Visit date", "uk": "Дата візиту"},
    "plan.order_payment": {"en": "Payment", "uk": "Оплата"},
    "plan.order_pay_online": {"en": "Online, on Esculab's page", "uk": "Онлайн на сторінці Esculab"},
    "plan.order_pay_point": {"en": "At the collection point", "uk": "У пункті забору"},
    "plan.order_submit": {"en": "Order at Esculab for {total}", "uk": "Замовити в Esculab за {total}"},
    "plan.order_no_person": {
        "en": "Esculab is connected, but you have not said which person on that account is you.",
        "uk": "Esculab підключено, але ще не вказано, хто з людей у цьому обліковому записі ви.",
    },
    "plan.order_connect": {"en": "Open connections", "uk": "Відкрити підключення"},
    "plan.order_not_connected": {
        "en": "To order from here, connect your {lab} account on your profile. Until then, each item above links to its page on the lab's site.",
        "uk": "Щоб замовляти звідси, підключіть обліковий запис {lab} у профілі. А поки кожна позиція вище має посилання на свою сторінку на сайті лабораторії.",
    },
    "plan.cart_heading": {"en": "Synevo cart", "uk": "Кошик Synevo"},
    "plan.cart_lead": {
        "en": "The tests go into the cart of your Synevo account. Nothing is ordered or paid here: you pick the collection point and pay on the Synevo site.",
        "uk": "Аналізи потраплять у кошик вашого облікового запису Synevo. Тут нічого не замовляється й не сплачується: пункт забору й оплату ви оберете на сайті Synevo.",
    },
    "plan.cart_submit": {"en": "Add to my Synevo cart", "uk": "Додати в мій кошик Synevo"},
    "plan.mixed_order": {
        "en": "Order each part from that lab's own plan on this page.",
        "uk": "Кожну частину замовляйте з плану відповідної лабораторії на цій сторінці.",
    },
    "plan.done_title": {"en": "{lab} order", "uk": "Замовлення {lab}"},
    "plan.done_order_heading": {"en": "Order {number} created", "uk": "Замовлення {number} створено"},
    "plan.done_cart_heading": {"en": "Added to your cart", "uk": "Додано до кошика"},
    "plan.done_order_lead": {
        "en": "The order is on your {lab} account and is not paid yet.",
        "uk": "Замовлення вже у вашому обліковому записі {lab}, але ще не оплачене.",
    },
    "plan.done_cart_lead": {
        "en": "These tests are in your {lab} cart. Finish the order on the {lab} site.",
        "uk": "Аналізи вже в кошику {lab}. Оформіть замовлення на сайті {lab}.",
    },
    "plan.done_total": {"en": "Total: {total}", "uk": "Разом: {total}"},
    "plan.done_total_note": {
        "en": "Before any loyalty bonus or promo code, which the lab applies when you pay.",
        "uk": "Без бонусів і промокодів: їх лабораторія врахує під час оплати.",
    },
    "plan.done_failed_lead": {
        "en": "These did not go into the cart. Add them on the lab's site, or leave them out:",
        "uk": "Ці позиції не потрапили в кошик. Додайте їх на сайті лабораторії або обійдіться без них:",
    },
    "synevo_cart.in_package": {
        "en": "already part of a panel in your cart",
        "uk": "уже входить до пакета у вашому кошику",
    },
    "synevo_cart.refused": {
        "en": "Synevo does not take it online: it may need a doctor's referral or ordering at a collection point",
        "uk": "Synevo не приймає його онлайн: можливо, потрібне направлення лікаря або замовлення в пункті забору",
    },
    "synevo_cart.promo": {
        "en": "the offer has ended: add it on the site at the regular price",
        "uk": "акція вже закінчилася: додайте його на сайті за звичайною ціною",
    },
    "synevo_cart.needs_confirmation": {
        "en": "Synevo asks you to confirm it on its site first",
        "uk": "Synevo просить спершу підтвердити його на сайті",
    },
    "synevo_cart.not_added": {
        "en": "Synevo replied, but it is not in the cart",
        "uk": "Synevo відповіла, але в кошику його немає",
    },
    "plan.done_pay": {"en": "Pay on the {lab} site","uk": "Оплатити на сайті {lab}"},
    "plan.done_open_cart": {"en": "Open the {lab} cart", "uk": "Відкрити кошик {lab}"},
    "plan.done_open_site": {"en": "Open the {lab} site", "uk": "Відкрити сайт {lab}"},
    "plan.done_back": {"en": "Back to the plan", "uk": "Назад до плану"},
    "plan.done_pay_later": {
        "en": "Pay at the collection point, or online from the order in the {lab} app.",
        "uk": "Оплатити можна в пункті забору або онлайн у застосунку {lab}.",
    },
    "plan.search_fuzzy": {
        "en": "No exact match. These are spelled similarly.",
        "uk": "Точних збігів немає. Ось схожі за написанням.",
    },
    "plan.sets_heading": {"en": "Panels and special tests", "uk": "Пакети та спеціальні дослідження"},
    "plan.sets_lead": {
        "en": "Check-ups, panels and genetic tests. An included one is bought at its own lab, and the rest of the plan is built around it.",
        "uk": "Чекапи, пакети й генетичні дослідження. Додане дослідження план бере в тій лабораторії, де воно є, а решту обраного доповнює іншими аналізами.",
    },
    "plan.sets_search_label": {"en": "Find a panel or special test", "uk": "Знайти пакет або спеціальне дослідження"},
    "plan.sets_in_shelf": {"en": "In \"{shelf}\"", "uk": "У розділі «{shelf}»"},
    "plan.sets_none": {
        "en": "Nothing matches \"{query}\" with these filters. Try another word, the test code or fewer filters.",
        "uk": "За запитом «{query}» з такими фільтрами нічого не знайдено. Спробуйте інше слово, код аналізу або приберіть фільтри.",
    },
    "plan.sets_prompt": {
        "en": "Search by name or code, or pick a lab section.",
        "uk": "Шукайте за назвою чи кодом або оберіть розділ лабораторії.",
    },
    "plan.sets_count_one": {"en": "{count} match", "uk": "{count} збіг"},
    "plan.sets_count_few": {"en": "{count} matches", "uk": "{count} збіги"},
    "plan.sets_count_many": {"en": "{count} matches", "uk": "{count} збігів"},
    "plan.filters_legend": {"en": "Filters", "uk": "Фільтри"},
    "plan.filter_section": {"en": "Lab section", "uk": "Розділ лабораторії"},
    "plan.filter_lab": {"en": "Lab", "uk": "Лабораторія"},
    "plan.filter_any_lab": {"en": "All labs", "uk": "Усі лабораторії"},
    "plan.filter_kind": {"en": "Type", "uk": "Тип"},
    "plan.filter_any_kind": {"en": "All types", "uk": "Усі типи"},
    "plan.filter_kind_genetic": {"en": "Genetic tests", "uk": "Генетичні дослідження"},
    "plan.filter_kind_set": {"en": "Panels and check-ups", "uk": "Пакети та чекапи"},
    "plan.filter_max": {"en": "Max price, UAH", "uk": "Ціна до, грн"},
    "plan.filter_sort": {"en": "Sort", "uk": "Сортування"},
    "plan.sort_relevance": {"en": "Best match first", "uk": "За відповідністю"},
    "plan.sort_price": {"en": "Cheapest first", "uk": "Від дешевших до дорожчих"},
    "plan.filter_apply": {"en": "Show", "uk": "Показати"},
    "plan.pager_label": {"en": "Pages of results", "uk": "Сторінки результатів"},
    "plan.pager_prev": {"en": "Previous", "uk": "Попередні"},
    "plan.pager_next": {"en": "Next", "uk": "Наступні"},
    "plan.pager_range": {"en": "{start}-{end} of {total}", "uk": "{start}-{end} із {total}"},
    "plan.kind_genetic": {"en": "Genetic test", "uk": "Генетичне дослідження"},
    "plan.kind_set": {"en": "Panel", "uk": "Пакет"},
    "plan.kind_single": {"en": "Single test", "uk": "Окремий аналіз"},
    "plan.analytes_one": {"en": "{count} result", "uk": "{count} показник"},
    "plan.analytes_few": {"en": "{count} results", "uk": "{count} показники"},
    "plan.analytes_many": {"en": "{count} results", "uk": "{count} показників"},
    "plan.lab_page": {"en": "On {lab}'s site", "uk": "На сайті {lab}"},
    "plan.include_gone": {
        "en": "An included item ({value}) is no longer in the lab's price list, so the plan leaves it out.",
        "uk": "Доданої позиції ({value}) уже немає в прайсі лабораторії, тому план її не враховує.",
    },
    "plan.included_already": {"en": "Already included", "uk": "Уже додано"},
    "plan.item_chosen": {"en": "Added by you", "uk": "Ви додали"},
    "plan.not_here": {
        "en": "{lab} does not sell: {names}. Its results are planned here from other tests.",
        "uk": "У {lab} немає: {names}. Їхні показники тут добрано з інших аналізів.",
    },
    "plan.missing_included_one": {
        "en": "{count} more result from your included panels is not available here.",
        "uk": "Ще {count} показник із доданих пакетів тут недоступний.",
    },
    "plan.missing_included_few": {
        "en": "{count} more results from your included panels are not available here.",
        "uk": "Ще {count} показники з доданих пакетів тут недоступні.",
    },
    "plan.missing_included_many": {
        "en": "{count} more results from your included panels are not available here.",
        "uk": "Ще {count} показників із доданих пакетів тут недоступні.",
    },
    "plan.ready_days_one": {"en": "Ready in about {count} day", "uk": "Термін виконання: {count} день"},
    "plan.ready_days_few": {"en": "Ready in about {count} days", "uk": "Термін виконання: {count} дні"},
    "plan.ready_days_many": {"en": "Ready in about {count} days", "uk": "Термін виконання: {count} днів"},
    "plan.ready_minutes": {"en": "Ready in about {count} min", "uk": "Термін виконання: {count} хв"},
    "plan.sample": {"en": "Sample:", "uk": "Біоматеріал:"},
    "plan.prep_heading": {"en": "How to prepare", "uk": "Як підготуватися"},
    "plan.prep_lab": {"en": "{lab}:", "uk": "{lab}:"},
    "plan.prep_none": {
        "en": "The labs list no special preparation for these tests. Each test's page on the lab's site has the details.",
        "uk": "Лабораторії не вказують особливої підготовки до цих аналізів. Подробиці є на сторінці кожного аналізу на сайті лабораторії.",
    },
    "plan.prep_source": {
        "en": "Gathered from the labs' own instructions for the tests in this plan; where they differ, the strictest is shown. The full text is on each test's page on the lab's site.",
        "uk": "Зведено з інструкцій лабораторій до аналізів цього плану; там, де вимоги різняться, показано найсуворішу. Повний текст є на сторінці кожного аналізу на сайті лабораторії.",
    },
    "plan.prep_group_general": {"en": "For the whole visit", "uk": "Для всього візиту"},
    "plan.prep_group_samples": {"en": "Samples you bring", "uk": "Що принести з собою"},
    "plan.prep_group_tests": {"en": "For specific tests", "uk": "Для окремих аналізів"},
    "plan.prep_topic_psa": {"en": "PSA", "uk": "ПСА"},
    "plan.prep_topic_thyroglobulin": {"en": "Thyroglobulin", "uk": "Тиреоглобулін"},
    "plan.prep_topic_cortisol": {"en": "Cortisol", "uk": "Кортизол"},
    "plan.prep_topic_prolactin": {"en": "Prolactin", "uk": "Пролактин"},
    "plan.prep_topic_coprogram": {"en": "Coprogram", "uk": "Копрограма"},
    "plan.prep_topic_urine_culture": {"en": "Urine culture", "uk": "Посів сечі"},
    "plan.prep_topic_swab": {"en": "Urogenital swab", "uk": "Урогенітальний мазок"},
    "plan.prep_topic_urine_24h": {"en": "24-hour urine", "uk": "Добова сеча"},
    "plan.prep_topic_acr": {"en": "Urine albumin", "uk": "Альбумін у сечі"},
    "plan.prep_topic_urinalysis": {"en": "Urinalysis", "uk": "Аналіз сечі"},
    "plan.prep_topic_hormones": {"en": "Sex hormones", "uk": "Статеві гормони"},
    "plan.prep_and": {"en": "or", "uk": "і"},
    "plan.prep_or": {"en": "or", "uk": "або"},
    "plan.prep_hours": {"en": "{n} h", "uk": "{n} год"},
    "plan.prep_minutes": {"en": "{n} min", "uk": "{n} хв"},
    "plan.prep_days_one": {"en": "{n} day", "uk": "{n} день"},
    "plan.prep_days_few": {"en": "{n} days", "uk": "{n} дні"},
    "plan.prep_days_many": {"en": "{n} days", "uk": "{n} днів"},
    "plan.prep_weeks_one": {"en": "{n} week", "uk": "{n} тиждень"},
    "plan.prep_weeks_few": {"en": "{n} weeks", "uk": "{n} тижні"},
    "plan.prep_weeks_many": {"en": "{n} weeks", "uk": "{n} тижнів"},
    "plan.prep_weekday_0": {"en": "Mon", "uk": "пн"},
    "plan.prep_weekday_1": {"en": "Tue", "uk": "вт"},
    "plan.prep_weekday_2": {"en": "Wed", "uk": "ср"},
    "plan.prep_weekday_3": {"en": "Thu", "uk": "чт"},
    "plan.prep_weekday_4": {"en": "Fri", "uk": "пт"},
    "plan.prep_weekday_5": {"en": "Sat", "uk": "сб"},
    "plan.prep_weekday_6": {"en": "Sun", "uk": "нд"},
    "plan.prep_gist_fasting": {"en": "fasting {d}", "uk": "натщесерце {d}"},
    "plan.prep_gist_fasting_plain": {"en": "fasting", "uk": "натщесерце"},
    "plan.prep_gist_morning": {"en": "in the morning", "uk": "зранку"},
    "plan.prep_gist_urine": {"en": "urine sample", "uk": "зразок сечі"},
    "plan.prep_gist_stool": {"en": "stool sample", "uk": "зразок калу"},
    "plan.prep_rule_fasting": {"en": "Fasting: last meal {d} before the test.", "uk": "Натщесерце: останній прийом їжі за {d} до аналізу."},
    "plan.prep_rule_fasting_plain": {"en": "Come fasting.", "uk": "Приходьте натщесерце."},
    "plan.prep_rule_water": {"en": "Plain still water is fine.", "uk": "Чисту негазовану воду пити можна."},
    "plan.prep_rule_abstain": {"en": "For {d} before the test: no {list}.", "uk": "За {d} до аналізу: без {list}."},
    "plan.prep_noun_alcohol": {"en": "alcohol", "uk": "алкоголю"},
    "plan.prep_noun_smoking": {"en": "smoking", "uk": "паління"},
    "plan.prep_noun_heat": {"en": "sauna", "uk": "сауни"},
    "plan.prep_noun_sex": {"en": "sex", "uk": "статевих контактів"},
    "plan.prep_noun_cycling": {"en": "cycling", "uk": "велосипеда"},
    "plan.prep_noun_exercise": {"en": "exercise or stress", "uk": "навантажень і стресу"},
    "plan.prep_rule_medicines": {
        "en": "Medicines: skip them before the test only if your doctor agrees; tell the staff what you take.",
        "uk": "Ліки: перед аналізом пропускайте лише з дозволу лікаря; скажіть персоналу, що приймаєте.",
    },
    "plan.prep_rule_when": {"en": "Come {parts}.", "uk": "Приходьте {parts}."},
    "plan.prep_when_morning": {"en": "in the morning", "uk": "зранку"},
    "plan.prep_rule_topic": {"en": "{topic}: {parts}.", "uk": "{topic}: {parts}."},
    "plan.prep_part_fasting": {"en": "fasting {d}", "uk": "натщесерце {d}"},
    "plan.prep_part_time": {"en": "sample taken {times}", "uk": "забір {times}"},
    "plan.prep_part_wake_within": {"en": "within {d} of waking", "uk": "не пізніше ніж через {d} після пробудження"},
    "plan.prep_part_wake_after": {"en": "{d} after waking", "uk": "через {d} після пробудження"},
    "plan.prep_part_rest": {"en": "after {d} at rest", "uk": "після {d} спокою"},
    "plan.prep_part_psa": {"en": "{d} after a prostate exam or massage", "uk": "{d} після обстеження чи масажу простати"},
    "plan.prep_part_psa_biopsy": {"en": "{d} after a biopsy", "uk": "{d} після біопсії"},
    "plan.prep_part_thyroid_scan": {"en": "{d} after a thyroid scan or biopsy", "uk": "{d} після сканування чи пункції щитоподібної залози"},
    "plan.prep_part_thyroid_surgery": {"en": "{d} after surgery or radioiodine", "uk": "{d} після операції чи радіойоду"},
    "plan.prep_part_abstain": {"en": "no {list} for {d}", "uk": "{d} без {list}"},
    "plan.prep_rule_urine": {"en": "Urine: {parts}.", "uk": "Сеча: {parts}."},
    "plan.prep_rule_stool": {"en": "Stool: {parts}.", "uk": "Кал: {parts}."},
    "plan.prep_sample_home": {"en": "collect at home", "uk": "зберіть удома"},
    "plan.prep_sample_sterile": {"en": "in a sterile container", "uk": "у стерильний контейнер"},
    "plan.prep_sample_within": {"en": "deliver within {d}", "uk": "доставте протягом {d}"},
    "plan.prep_sample_now": {"en": "deliver straight away", "uk": "доставте одразу"},
    "plan.prep_urine_morning": {"en": "the first urine of the morning", "uk": "ранкова порція"},
    "plan.prep_urine_midstream": {"en": "midstream", "uk": "середня порція"},
    "plan.prep_urine_morning_midstream": {"en": "midstream first-morning urine", "uk": "середня порція ранкової сечі"},
    "plan.prep_urine_wash": {"en": "wash first", "uk": "перед збором підмийтеся"},
    "plan.prep_urine_tampon": {"en": "women: insert a tampon first", "uk": "жінкам: перед збором ввести тампон"},
    "plan.prep_urine_food": {"en": "the day before, no beetroot or bright fruit and vegetables", "uk": "напередодні без буряка, яскравих овочів і фруктів"},
    "plan.prep_stool_fresh": {"en": "freshly passed", "uk": "свіжий"},
    "plan.prep_stool_enema": {"en": "not after enemas, suppositories or laxatives", "uk": "не після клізми, свічок чи проносних"},
    "plan.prep_stool_procedures": {"en": "at least {d} after a colonoscopy", "uk": "не раніше ніж через {d} після колоноскопії"},
    "plan.prep_stool_diet": {"en": "{d} of the diet on the test's page", "uk": "{d} дієти зі сторінки аналізу"},
    "plan.prep_rule_urine_24h": {
        "en": "24-hour urine: collect all urine over a full day; the steps are on the test's page.",
        "uk": "Добова сеча: збирайте всю сечу протягом доби; порядок збору є на сторінці аналізу.",
    },
    "plan.prep_rule_urine_first": {
        "en": "First-catch urine: fill the container with the very first portion.",
        "uk": "Перша порція сечі: наповніть контейнер найпершою порцією.",
    },
    "plan.prep_rule_antibiotics": {
        "en": "{tests}: before antibiotics or antifungals, or {d} after the course. Never delay a prescribed course: ask your doctor.",
        "uk": "{tests}: до антибіотиків чи протигрибкових або через {d} після курсу. Призначений курс не відкладайте: запитайте лікаря.",
    },
    "plan.prep_rule_antibiotics_plain": {
        "en": "{tests}: before starting antibiotics or antifungals. Never delay a prescribed course: ask your doctor.",
        "uk": "{tests}: до початку антибіотиків чи протигрибкових. Призначений курс не відкладайте: запитайте лікаря.",
    },
    "plan.prep_rule_biotin": {
        "en": "Biotin over {mg} mg a day: last dose at least {d} before the draw; if prescribed, ask your doctor.",
        "uk": "Біотин понад {mg} мг на добу: остання доза щонайменше за {d} до забору; якщо призначив лікар, запитайте його.",
    },
    "plan.prep_rule_biotin_plain": {"en": "High-dose biotin: tell the staff.", "uk": "Біотин у високих дозах: скажіть персоналу."},
    "plan.prep_rule_menstruation": {
        "en": "Women: not during menstruation, and {d} after it ends.",
        "uk": "Жінкам: не під час менструації і через {d} після її закінчення.",
    },
    "plan.prep_rule_menstruation_plain": {"en": "Women: not during menstruation.", "uk": "Жінкам: не під час менструації."},
    "plan.prep_rule_cycle_day": {
        "en": "Women: on day {days} of the cycle, unless the doctor says otherwise.",
        "uk": "Жінкам: на {days} день циклу, якщо лікар не призначив інше.",
    },
    "plan.prep_rule_infant_fasting": {"en": "Babies under 1: no food for {d} before the test.", "uk": "Дітям до 1 року: не годувати за {d} до аналізу."},
    "plan.prep_rule_toddler_fasting": {"en": "Children aged 1 to 5: no food for {d} before the test.", "uk": "Дітям від 1 до 5 років: не їсти за {d} до аналізу."},
    "plan.prep_rule_child_water": {
        "en": "Children under 5: still water, {ml} ml at a time, over the {d} before the draw.",
        "uk": "Дітям до 5 років: негазована вода порціями по {ml} мл протягом {d} перед забором.",
    },
    "plan.prep_rule_infant_feed": {
        "en": "Babies: as long a gap as you can between the last feed and the draw.",
        "uk": "Немовлятам: якомога довша перерва між останнім годуванням і забором.",
    },
    "plan.prep_rule_weekdays": {"en": "{tests}: only on {days}.", "uk": "{tests}: лише {days}."},
    "plan.prep_rule_some_points": {
        "en": "{tests}: not every collection point takes it; check the test's page.",
        "uk": "{tests}: не кожен пункт забору приймає; перевірте сторінку аналізу.",
    },
    "plan.prep_rule_referral": {"en": "{tests}: needs a doctor's referral.", "uk": "{tests}: потрібне направлення лікаря."},
    "plan.prep_rule_doctor": {"en": "{tests}: a doctor takes the sample.", "uk": "{tests}: біоматеріал бере лікар."},
    "plan.prep_rule_bring": {"en": "{tests}: you collect the sample yourself and bring it.", "uk": "{tests}: біоматеріал збираєте самі й приносите."},
    "plan.material_serum": {"en": "blood serum", "uk": "сироватка крові"},
    "plan.material_whole_blood": {"en": "whole blood", "uk": "цільна кров"},
    "plan.material_plasma": {"en": "blood plasma", "uk": "плазма крові"},
    "plan.material_urine": {"en": "urine", "uk": "сеча"},
    "plan.material_urine_24h": {"en": "24-hour urine", "uk": "сеча (добова)"},
    "plan.material_stool": {"en": "stool", "uk": "кал"},
    "plan.material_csf": {"en": "cerebrospinal fluid", "uk": "ліквор"},
    "plan.material_semen": {"en": "semen", "uk": "сперма"},
    "plan.material_saliva": {"en": "saliva", "uk": "слина"},
    "plan.material_capillary_serum": {"en": "capillary blood serum", "uk": "сироватка капілярної крові"},
    "plan.material_capillary_blood": {"en": "capillary blood", "uk": "капілярна кров"},
    "plan.material_venous_blood": {"en": "venous blood", "uk": "венозна кров"},
    "plan.material_prostate": {"en": "prostate secretion", "uk": "секрет простати"},
    # --- the planner's special tests (testplan_special) ---
    "special.switch": {"en": "Special tests", "uk": "Спеціальні аналізи"},
    "special.switch_apply": {"en": "Switch", "uk": "Перемкнути"},
    "special.lead_off": {
        "en": "Built from your record: what is out of range or due again.",
        "uk": "Складено з вашої картки: що поза нормою або час повторити.",
    },
    "special.lead_on": {
        "en": "Start from a question: an allergy, your DNA, an infection, a long-term condition, or feeling unwell now.",
        "uk": "Почніть із питання: алергія, ваша ДНК, інфекція, хронічний стан чи погане самопочуття зараз.",
    },
    "special.topics": {"en": "Topics", "uk": "Теми"},
    "special.tests_one": {"en": "{count} test", "uk": "{count} аналіз"},
    "special.tests_few": {"en": "{count} tests", "uk": "{count} аналізи"},
    "special.tests_many": {"en": "{count} tests", "uk": "{count} аналізів"},
    "special.list_label": {"en": "Tests by topic", "uk": "Аналізи за темами"},
    "special.list_empty": {
        "en": "Pick a topic above or search for a test.",
        "uk": "Оберіть тему вище або знайдіть аналіз.",
    },
    "special.search_label": {"en": "Find a test or a package", "uk": "Знайти аналіз або пакет"},
    "special.search_hint": {
        "en": "A question, a disease, a gene or a package name: «лактоза», «HPV», «Check-UP».",
        "uk": "Питання, хвороба, ген чи назва пакета: «лактоза», «HPV», «Check-UP».",
    },
    "special.found_legend": {"en": "Tests for that", "uk": "Аналізи для цього"},
    "special.packages_legend": {"en": "Lab packages and named tests", "uk": "Пакети та окремі аналізи лабораторій"},
    "special.done": {"en": "Measured {date}", "uk": "Зроблено {date}"},
    "special.done_once": {
        "en": "Done {date}. Your DNA does not change, so it never needs repeating.",
        "uk": "Зроблено {date}. ДНК не змінюється, тож повторювати не потрібно.",
    },
    "special.once_note": {
        "en": "Your DNA does not change, so it never needs repeating.",
        "uk": "ДНК не змінюється, тож повторювати не потрібно.",
    },
    "special.once_note_lifetime": {
        "en": "European guidance advises measuring it at least once in adult life. The level is set mostly by your genes and changes little, though a doctor may repeat it in some situations.",
        "uk": "Європейські настанови радять виміряти його принаймні раз у дорослому житті. Рівень здебільшого визначають гени, і він мало змінюється, хоча в окремих ситуаціях лікар може призначити аналіз повторно.",
    },
    "special.done_once_lifetime": {
        "en": "Done {date}. The level is set mostly by your genes and changes little, so it is rarely repeated; a doctor may still ask for it again in some situations.",
        "uk": "Зроблено {date}. Рівень здебільшого визначають гени, і він мало змінюється, тому аналіз рідко повторюють; в окремих ситуаціях лікар може призначити його ще раз.",
    },
    "special.covered_one": {
        "en": "Your allergy test of {date} already measured {count} allergen.",
        "uk": "Ваш алерготест від {date} уже виміряв {count} алерген.",
    },
    "special.covered_few": {
        "en": "Your allergy test of {date} already measured {count} allergens.",
        "uk": "Ваш алерготест від {date} уже виміряв {count} алергени.",
    },
    "special.covered_many": {
        "en": "Your allergy test of {date} already measured {count} allergens.",
        "uk": "Ваш алерготест від {date} уже виміряв {count} алергенів.",
    },
    "special.only_at": {"en": "Only at {lab}", "uk": "Лише в {lab}"},
    "special.open_allergy": {"en": "Your allergy results", "uk": "Ваші результати алерготесту"},
    "special.open_genetics": {"en": "About this DNA test", "uk": "Про цей ДНК-тест"},
    "panels.overviews_aria": {"en": "Overviews", "uk": "Огляди"},
    "panels.overview_allergy_lead": {
        "en": "Every allergen tested, searchable, and what the results and protein families mean.",
        "uk": "Усі досліджені алергени з пошуком і пояснення результатів та родин білків.",
    },
    "panels.overview_genetics_lead": {
        "en": "Tests of your own genes, and what common DNA tests can answer, with prices.",
        "uk": "Аналізи ваших генів і те, на що можуть відповісти поширені ДНК-тести, з цінами.",
    },
    "special.overview_allergy": {"en": "Allergy overview", "uk": "Огляд алергії"},
    "special.overview_genetics": {"en": "Your DNA overview", "uk": "Огляд вашої ДНК"},
    "special.topic_allergy": {"en": "Allergy", "uk": "Алергія"},
    "special.topic_allergy_hint": {
        "en": "What you react to: pollen, mites, pets, foods, stings.",
        "uk": "На що реакція: пилок, кліщі, тварини, їжа, укуси комах.",
    },
    "special.topic_genetics": {"en": "Your DNA", "uk": "Ваша ДНК"},
    "special.topic_genetics_hint": {
        "en": "Inherited traits and risks. Done once: your genes do not change.",
        "uk": "Спадкові ознаки й ризики. Робиться раз: гени не змінюються.",
    },
    "special.topic_infections": {"en": "Infections and immunity", "uk": "Інфекції та імунітет"},
    "special.topic_infections_hint": {
        "en": "Hidden infections worth ruling out, and whether vaccines still protect you.",
        "uk": "Приховані інфекції, які варто виключити, і чи захищають вас щеплення.",
    },
    "special.topic_chronic": {"en": "Long-term conditions", "uk": "Хронічні стани"},
    "special.topic_chronic_hint": {
        "en": "Early signs of diabetes and of kidney, thyroid, joint and bowel disease.",
        "uk": "Ранні ознаки діабету та хвороб нирок, щитоподібної залози, суглобів і кишківника.",
    },
    "special.topic_urgent": {"en": "Feeling unwell now", "uk": "Погано почуваєтеся зараз"},
    "special.topic_urgent_hint": {
        "en": "Fever, sore throat, cough, diarrhoea, painful urination.",
        "uk": "Температура, біль у горлі, кашель, діарея, біль під час сечовипускання.",
    },
    "special.total-ige": {"en": "Total IgE", "uk": "Загальний IgE"},
    "special.total-ige_what": {
        "en": "How active the allergic side of the immune system is overall; it does not say to what.",
        "uk": "Наскільки активна алергічна ланка імунітету загалом; не показує, на що саме.",
    },
    "special.allergy-phadiatop": {"en": "Airborne allergy screen (Phadiatop)", "uk": "Скринінг інгаляційної алергії (Phadiatop)"},
    "special.allergy-phadiatop_what": {
        "en": "One result: are you sensitised to any common airborne allergen at all.",
        "uk": "Один результат: чи є сенсибілізація хоч до одного поширеного повітряного алергену.",
    },
    "special.allergy-multiplex": {"en": "Molecular allergy test, about 300 allergens (ALEX)", "uk": "Молекулярний алерготест, близько 300 алергенів (ALEX)"},
    "special.allergen_t4": {"en": "Hazel pollen (t4)", "uk": "Пилок ліщини (t4)"},
    "special.allergen_t2": {"en": "Grey alder pollen (t2)", "uk": "Пилок вільхи сірої (t2)"},
    "special.allergen_t3": {"en": "Birch pollen (t3)", "uk": "Пилок берези (t3)"},
    "special.allergen_t11": {"en": "Plane tree pollen (t11)", "uk": "Пилок платана (t11)"},
    "special.allergen_t23": {"en": "Italian cypress pollen (t23)", "uk": "Пилок кипариса (t23)"},
    "special.allergen_g6": {"en": "Timothy grass pollen (g6)", "uk": "Пилок тимофіївки лучної (g6)"},
    "special.allergen_t9": {"en": "Olive tree pollen (t9)", "uk": "Пилок оливкового дерева (t9)"},
    "special.allergen_w6": {"en": "Mugwort pollen (w6)", "uk": "Пилок полину (w6)"},
    "special.allergen_w1": {"en": "Common ragweed pollen (w1)", "uk": "Пилок амброзії (w1)"},
    "special.allergen_w21": {"en": "Wall pellitory pollen (w21)", "uk": "Пилок парієтарії (w21)"},
    "special.allergen_m6": {"en": "Alternaria mould (m6)", "uk": "Пліснява Alternaria (m6)"},
    "special.allergen_m2": {"en": "Cladosporium mould (m2)", "uk": "Пліснява Cladosporium (m2)"},
    "special.allergen_m3": {"en": "Aspergillus fumigatus mould (m3)", "uk": "Пліснява Aspergillus fumigatus (m3)"},
    "special.allergen_d1": {"en": "House dust mite D. pteronyssinus (d1)", "uk": "Кліщ домашнього пилу D. pteronyssinus (d1)"},
    "special.allergen_d2": {"en": "House dust mite D. farinae (d2)", "uk": "Кліщ домашнього пилу D. farinae (d2)"},
    "special.allergen_e1": {"en": "Cat dander (e1)", "uk": "Лупа кота (e1)"},
    "special.allergen_e5": {"en": "Dog dander (e5)", "uk": "Лупа собаки (e5)"},
    "special.allergen_i6": {"en": "German cockroach (i6)", "uk": "Тарган рудий (i6)"},
    "special.allergen_i1": {"en": "Honey bee venom (i1)", "uk": "Отрута бджоли (i1)"},
    "special.allergen_i3": {"en": "Common wasp venom (i3)", "uk": "Отрута оси (i3)"},
    "special.allergy-multiplex_what": {
        "en": "Pollen, mites, pets, moulds, foods and venoms from one draw, down to the single protein.",
        "uk": "Пилок, кліщі, тварини, пліснява, їжа й отрути комах з одного забору, до окремого білка.",
    },
    "special.allergy-inhalant": {"en": "Hay fever and asthma panel", "uk": "Панель при алергічному риніті й астмі"},
    "special.allergy-inhalant_what": {
        "en": "Pollen, mites, moulds and pets: the usual causes of a runny nose and wheeze.",
        "uk": "Пилок, кліщі, пліснява й тварини: звичні причини нежитю та свистячого дихання.",
    },
    "special.allergy-food": {"en": "Food allergy panel", "uk": "Панель харчової алергії"},
    "special.allergy-food_what": {
        "en": "Milk, egg, wheat, nuts, fish and other common food allergens.",
        "uk": "Молоко, яйце, пшениця, горіхи, риба та інші поширені харчові алергени.",
    },
    "special.allergy-pets": {"en": "Cat and dog allergy", "uk": "Алергія на кота й собаку"},
    "special.allergy-pets_what": {
        "en": "Specific IgE to cat (e1) and dog (e5) dander.",
        "uk": "Специфічні IgE до епідермісу кота (e1) і собаки (e5).",
    },
    "special.allergy-mites": {"en": "House dust mite allergy", "uk": "Алергія на кліщів домашнього пилу"},
    "special.allergy-mites_what": {
        "en": "Specific IgE to the two common dust mites (d1, d2).",
        "uk": "Специфічні IgE до двох поширених кліщів (d1, d2).",
    },
    "special.allergy-venom": {"en": "Bee and wasp venom allergy", "uk": "Алергія на отруту бджоли й оси"},
    "special.allergy-venom_what": {
        "en": "Specific IgE to bee (i1) and wasp (i3) venom, after a strong reaction to a sting.",
        "uk": "Специфічні IgE до отрути бджоли (i1) та оси (i3), після сильної реакції на укус.",
    },
    "special.tryptase": {"en": "Tryptase", "uk": "Триптаза"},
    "special.tryptase_what": {
        "en": "A mast cell marker: checked after a severe allergic reaction, or when mastocytosis is suspected.",
        "uk": "Маркер тучних клітин: після тяжкої алергічної реакції або при підозрі на мастоцитоз.",
    },
    "special.gen-lactose": {"en": "Lactose intolerance gene (LCT)", "uk": "Ген непереносимості лактози (LCT)"},
    "special.gen-lactose_what": {
        "en": "Whether your lactase is genetically set to fade after childhood.",
        "uk": "Чи генетично запрограмоване згасання лактази після дитинства.",
    },
    "special.gen-celiac": {"en": "Celiac predisposition (HLA-DQ2/DQ8)", "uk": "Схильність до целіакії (HLA-DQ2/DQ8)"},
    "special.gen-celiac_what": {
        "en": "A negative result practically rules celiac disease out; a positive one alone means little.",
        "uk": "Негативний результат практично виключає целіакію; позитивний сам по собі мало що означає.",
    },
    "special.gen-hemochromatosis": {"en": "Hereditary haemochromatosis (HFE)", "uk": "Спадковий гемохроматоз (HFE)"},
    "special.gen-hemochromatosis_what": {
        "en": "The C282Y variant, which in two copies is behind most inherited iron overload, and H63D, which is also reported but rarely causes it; for a high ferritin and transferrin saturation.",
        "uk": "Варіант C282Y, дві копії якого спричиняють більшість випадків спадкового перевантаження залізом, і H63D, який теж визначають, але він рідко його спричиняє; при високих феритині й насиченні трансферину.",
    },
    "special.gen-thrombophilia": {"en": "Inherited clotting risk (F5 Leiden, F2)", "uk": "Спадковий ризик тромбозів (F5 Лейден, F2)"},
    "special.gen-thrombophilia_what": {
        "en": "The two common gene variants that raise the risk of blood clots.",
        "uk": "Два поширені варіанти генів, що підвищують ризик тромбів.",
    },
    "special.gen-f5": {"en": "Factor V Leiden (F5)", "uk": "Лейденська мутація фактора V (F5)"},
    "special.gen-f2": {"en": "Prothrombin variant (F2 G20210A)", "uk": "Варіант протромбіну (F2 G20210A)"},
    "special.gen-mthfr": {"en": "MTHFR gene variants", "uk": "Варіанти гена MTHFR"},
    "special.gen-mthfr_what": {
        "en": "Common folate metabolism variants; guidelines advise against testing them to judge clotting risk.",
        "uk": "Поширені варіанти фолатного обміну; настанови не радять перевіряти їх для оцінки ризику тромбів.",
    },
    "special.gen-gilbert": {"en": "Gilbert syndrome gene (UGT1A1)", "uk": "Ген синдрому Жильбера (UGT1A1)"},
    "special.gen-gilbert_what": {
        "en": "Explains a mildly raised indirect bilirubin; the condition itself is harmless.",
        "uk": "Пояснює помірно підвищений непрямий білірубін; сам стан не шкодить.",
    },
    "special.gen-hla-b27": {"en": "HLA-B27", "uk": "HLA-B27"},
    "special.gen-hla-b27_what": {
        "en": "A gene marker linked to spondyloarthritis; checked for inflammatory back pain.",
        "uk": "Генетичний маркер, пов'язаний зі спондилоартритом; перевіряють при запальному болю в спині.",
    },
    "special.gen-brca": {"en": "Inherited breast and ovarian cancer genes (BRCA1/2)", "uk": "Гени спадкового раку грудей і яєчників (BRCA1/2)"},
    "special.gen-brca_what": {
        "en": "For a strong family history; best ordered with genetic counselling.",
        "uk": "При обтяженій сімейній історії; краще разом із генетичним консультуванням.",
    },
    "special.gen-lynch": {"en": "Lynch syndrome genes", "uk": "Гени синдрому Лінча"},
    "special.gen-lynch_what": {
        "en": "Inherited bowel and womb cancer risk; for relatives who had them young.",
        "uk": "Спадковий ризик раку кишківника й матки; якщо в родині хворіли в молодому віці.",
    },
    "special.gen-cftr": {"en": "Cystic fibrosis carrier (CFTR)", "uk": "Носійство муковісцидозу (CFTR)"},
    "special.gen-cftr_what": {
        "en": "Whether you carry a variant you could pass on; for couples planning a child.",
        "uk": "Чи несете ви варіант, який можна передати дитині; для пар, що планують дитину.",
    },
    "special.gen-carrier": {"en": "Expanded carrier screening (hundreds of genes)", "uk": "Розширений скринінг носійства (сотні генів)"},
    "special.gen-carrier_what": {
        "en": "Hidden recessive diseases a couple could pass on to a child; it does not test clotting, lactose or cancer risk.",
        "uk": "Приховані рецесивні хвороби, які пара може передати дитині; не перевіряє ризик тромбозів, лактозу чи рак.",
    },
    "special.standards": {"en": "Standards", "uk": "Стандарти"},
    "special.std_acmg-tier1": {"en": "Carrier screening, ACMG Tier 1", "uk": "Скринінг носійства, ACMG рівень 1"},
    "special.std_acmg-tier1_hint": {
        "en": "Cystic fibrosis and spinal muscular atrophy, where every carrier screen starts.",
        "uk": "Муковісцидоз і спінальна м'язова атрофія, з яких починається будь-який скринінг носійства.",
    },
    "special.std_acmg-tier2": {"en": "Carrier screening, ACMG Tier 2", "uk": "Скринінг носійства, ACMG рівень 2"},
    "special.std_acmg-tier2_hint": {
        "en": "Conditions carried by 1 in 100 people or more; no lab here sells it alone, a Tier 3 panel covers it.",
        "uk": "Стани, носієм яких є 1 зі 100 людей або частіше; окремо його тут не продають, його охоплює панель рівня 3.",
    },
    "special.std_acmg-tier3": {"en": "Carrier screening, ACMG Tier 3", "uk": "Скринінг носійства, ACMG рівень 3"},
    "special.std_acmg-tier3_hint": {
        "en": "Carried by 1 in 200 or more, plus X-linked conditions: what ACMG advises offering before a pregnancy.",
        "uk": "Носійство 1 на 200 або частіше та X-зчеплені стани: те, що ACMG радить пропонувати перед вагітністю.",
    },
    "special.std_ga2len": {"en": "European airborne allergen set (GA²LEN)", "uk": "Європейський набір повітряних алергенів (GA²LEN)"},
    "special.std_ga2len_hint": {
        "en": "The 18 pollens, moulds, mites and animals of the European skin test standard, measured in blood.",
        "uk": "18 пилкових, пліснявих, кліщових і тваринних алергенів європейського стандарту шкірних проб, у крові.",
    },
    "special.gen-carrier-t1": {"en": "Carrier screening: cystic fibrosis and SMA (ACMG Tier 1)", "uk": "Скринінг носійства: муковісцидоз і СМА (ACMG рівень 1)"},
    "special.gen-carrier-t1_what": {
        "en": "Whether you carry cystic fibrosis or spinal muscular atrophy, the commonest serious recessive conditions.",
        "uk": "Чи є ви носієм муковісцидозу або спінальної м'язової атрофії, найчастіших тяжких рецесивних станів.",
    },
    "special.gen-carrier-t2": {"en": "Carrier screening, ACMG Tier 2", "uk": "Скринінг носійства, ACMG рівень 2"},
    "special.gen-carrier-t2_what": {
        "en": "Recessive conditions carried by 1 in 100 people or more; a panel that states Tier 3 covers it.",
        "uk": "Рецесивні стани, носієм яких є 1 зі 100 людей або частіше; його охоплює панель, що заявляє рівень 3.",
    },
    "special.gen-carrier-t3": {"en": "Expanded carrier screening, ACMG Tier 3", "uk": "Розширений скринінг носійства, ACMG рівень 3"},
    "special.gen-carrier-t3_what": {
        "en": "Hundreds of recessive and X-linked conditions a couple could pass on; it does not test clotting, lactose or cancer risk.",
        "uk": "Сотні рецесивних і X-зчеплених станів, які пара може передати дитині; не перевіряє ризик тромбозів, лактозу чи рак.",
    },
    "special.gen-sma": {"en": "Spinal muscular atrophy carrier (SMN1)", "uk": "Носійство спінальної м'язової атрофії (SMN1)"},
    "special.gen-tier2": {"en": "Carrier panel, ACMG Tier 2", "uk": "Панель носійства, ACMG рівень 2"},
    "special.gen-tier3": {"en": "Carrier panel, ACMG Tier 3", "uk": "Панель носійства, ACMG рівень 3"},
    "special.allergy-ga2len": {"en": "European airborne allergen set (GA²LEN, 18 sources)", "uk": "Європейський набір повітряних алергенів (GA²LEN, 18 джерел)"},
    "special.allergy-ga2len_what": {
        "en": "Specific IgE to 18 pollens, moulds, mites, cat, dog and cockroach; the ALEX test reads all of them.",
        "uk": "Специфічні IgE до 18 пилкових, пліснявих, кліщових алергенів, кота, собаки й таргана; тест ALEX читає їх усі.",
    },
    "special.gen-warfarin": {"en": "Warfarin dose genes (CYP2C9, VKORC1)", "uk": "Гени дозування варфарину (CYP2C9, VKORC1)"},
    "special.gen-warfarin_what": {
        "en": "How fast you clear warfarin and how much of it you need.",
        "uk": "Як швидко організм виводить варфарин і скільки його потрібно.",
    },
    "special.hbv": {"en": "Hepatitis B (HBsAg)", "uk": "Гепатит B (HBsAg)"},
    "special.hbv_what": {
        "en": "Whether hepatitis B virus is in your blood now.",
        "uk": "Чи є зараз вірус гепатиту B у крові.",
    },
    "special.hcv": {"en": "Hepatitis C antibodies", "uk": "Антитіла до гепатиту C"},
    "special.hcv_what": {
        "en": "Whether you have ever had hepatitis C; advised once for every adult.",
        "uk": "Чи був колись гепатит C; радять зробити раз кожному дорослому.",
    },
    "special.hiv": {"en": "HIV", "uk": "ВІЛ"},
    "special.hiv_what": {
        "en": "Antigen and antibody screen; advised at least once for every adult.",
        "uk": "Скринінг антигену й антитіл; радять зробити хоча б раз кожному дорослому.",
    },
    "special.syphilis": {"en": "Syphilis antibodies", "uk": "Антитіла до сифілісу"},
    "special.syphilis_what": {
        "en": "Treponemal antibodies; they stay positive after an infection, even a cured one.",
        "uk": "Трепонемні антитіла; лишаються позитивними після інфекції, навіть вилікуваної.",
    },
    "special.hbv-immunity": {"en": "Hepatitis B protection (anti-HBs)", "uk": "Захист від гепатиту B (anti-HBs)"},
    "special.hbv-immunity_what": {
        "en": "Whether vaccination or a past infection protects you.",
        "uk": "Чи захищає вас щеплення або перенесена інфекція.",
    },
    "special.measles-immunity": {"en": "Measles protection (IgG)", "uk": "Захист від кору (IgG)"},
    "special.measles-immunity_what": {
        "en": "Whether you have antibodies against measles from a vaccine or the illness.",
        "uk": "Чи є антитіла до кору після щеплення або хвороби.",
    },
    "special.rubella-immunity": {"en": "Rubella protection (IgG)", "uk": "Захист від краснухи (IgG)"},
    "special.rubella-immunity_what": {
        "en": "Whether you are protected against rubella; matters most before a pregnancy.",
        "uk": "Чи є захист від краснухи; найважливіше перед вагітністю.",
    },
    "special.vzv-immunity": {"en": "Chickenpox protection (IgG)", "uk": "Захист від вітряної віспи (IgG)"},
    "special.vzv-immunity_what": {
        "en": "Whether you have had chickenpox or the vaccine.",
        "uk": "Чи ви перехворіли на вітряну віспу або щеплені.",
    },
    "special.ebv": {"en": "Epstein-Barr virus (mononucleosis)", "uk": "Вірус Епштейна-Барр (мононуклеоз)"},
    "special.ebv_what": {
        "en": "Three antibodies that tell apart never infected, infected now and infected in the past.",
        "uk": "Три види антитіл розрізняють: інфекції не було, інфекція зараз, інфекція в минулому.",
    },
    "special.cmv": {"en": "Cytomegalovirus", "uk": "Цитомегаловірус"},
    "special.cmv_what": {
        "en": "IgG says you have met the virus; IgM points to a recent infection.",
        "uk": "IgG показує, що контакт із вірусом був; IgM вказує на нещодавню інфекцію.",
    },
    "special.hsv": {"en": "Herpes simplex antibodies", "uk": "Антитіла до вірусу простого герпесу"},
    "special.hsv_what": {
        "en": "Whether you carry herpes simplex virus; this test does not tell type 1 from type 2.",
        "uk": "Чи є у вас вірус простого герпесу; цей аналіз не розрізняє 1 і 2 типи.",
    },
    "special.h-pylori": {"en": "Helicobacter pylori (stool antigen)", "uk": "Helicobacter pylori (антиген у калі)"},
    "special.h-pylori_what": {
        "en": "Shows an active stomach infection, unlike a blood antibody test.",
        "uk": "Показує активну інфекцію шлунка, на відміну від аналізу крові на антитіла.",
    },
    "special.borrelia": {"en": "Lyme disease antibodies (Borrelia)", "uk": "Антитіла до бореліозу (Borrelia)"},
    "special.borrelia_what": {
        "en": "Weeks after a tick bite with a rash or joint pain; too early it reads negative.",
        "uk": "Через кілька тижнів після укусу кліща з висипом чи болем у суглобах; зарано результат негативний.",
    },
    "special.sti-pcr": {"en": "Sexually transmitted infections (PCR)", "uk": "Інфекції, що передаються статевим шляхом (ПЛР)"},
    "special.sti-pcr_what": {
        "en": "Chlamydia, gonorrhoea, trichomonas, mycoplasma and ureaplasma from one sample.",
        "uk": "Хламідії, гонорея, трихомонади, мікоплазми й уреаплазми з одного зразка.",
    },
    "special.hpv": {"en": "High-risk HPV", "uk": "ВПЛ високого ризику"},
    "special.hpv_what": {
        "en": "The virus types that can lead to cervical cancer; part of cervical screening.",
        "uk": "Типи вірусу, що можуть призвести до раку шийки матки; частина цервікального скринінгу.",
    },
    "special.hpv-hr": {"en": "High-risk HPV", "uk": "ВПЛ високого ризику"},
    "special.hba1c": {"en": "HbA1c (glycated haemoglobin)", "uk": "HbA1c (глікований гемоглобін)"},
    "special.hba1c_what": {
        "en": "Average blood sugar over about three months: finds diabetes and prediabetes.",
        "uk": "Середній рівень цукру приблизно за три місяці: виявляє діабет і переддіабет.",
    },
    "special.kidney-acr": {"en": "Urine albumin to creatinine ratio", "uk": "Співвідношення альбумін/креатинін у сечі"},
    "special.kidney-acr_what": {
        "en": "The earliest sign of kidney damage, before creatinine rises.",
        "uk": "Найраніша ознака ураження нирок, ще до зростання креатиніну.",
    },
    "special.lipoprotein-a": {"en": "Lipoprotein(a)", "uk": "Ліпопротеїн(a)"},
    "special.lipoprotein-a_what": {
        "en": "Inherited heart and vessel risk; European guidance advises measuring it once in adult life.",
        "uk": "Спадковий серцево-судинний ризик; європейські настанови радять виміряти раз у дорослому віці.",
    },
    "special.thyroid-tpo": {"en": "Thyroid antibodies (anti-TPO)", "uk": "Антитіла до щитоподібної залози (анти-ТПО)"},
    "special.thyroid-tpo_what": {
        "en": "Autoimmune thyroid disease, often years before the hormones change.",
        "uk": "Автоімунне ураження щитоподібної залози, часто за роки до зміни гормонів.",
    },
    "special.celiac-serology": {"en": "Celiac disease antibodies (tTG IgA, total IgA)", "uk": "Антитіла при целіакії (tTG IgA, загальний IgA)"},
    "special.celiac-serology_what": {
        "en": "The first test for celiac disease; only valid while you still eat gluten.",
        "uk": "Перший аналіз на целіакію; достовірний лише поки ви їсте глютен.",
    },
    "special.rheumatoid": {"en": "Rheumatoid arthritis markers (anti-CCP, RF)", "uk": "Маркери ревматоїдного артриту (анти-CCP, РФ)"},
    "special.rheumatoid_what": {
        "en": "For joint pain and morning stiffness.",
        "uk": "При болю в суглобах і ранковій скутості.",
    },
    "special.ana": {"en": "Antinuclear antibodies (ANA, IFT)", "uk": "Антинуклеарні антитіла (ANA, IFT)"},
    "special.ana_what": {
        "en": "A screen for lupus and related diseases; a low positive is common in healthy people.",
        "uk": "Скринінг на вовчак і споріднені хвороби; слабкопозитивний результат буває і у здорових.",
    },
    "special.calprotectin": {"en": "Faecal calprotectin", "uk": "Кальпротектин у калі"},
    "special.calprotectin_what": {
        "en": "Tells bowel inflammation (as in Crohn disease) apart from irritable bowel.",
        "uk": "Відрізняє запалення кишківника (як при хворобі Крона) від синдрому подразненого кишківника.",
    },
    "special.blood-count": {"en": "Complete blood count with ESR", "uk": "Загальний аналіз крові з ШОЕ"},
    "special.blood-count_what": {
        "en": "Signs of infection, inflammation, anaemia or bleeding.",
        "uk": "Ознаки інфекції, запалення, анемії чи кровотечі.",
    },
    "special.crp": {"en": "C-reactive protein", "uk": "С-реактивний білок"},
    "special.crp_what": {
        "en": "How strong inflammation is now; high in most bacterial infections.",
        "uk": "Наскільки сильне запалення зараз; високий при більшості бактеріальних інфекцій.",
    },
    "special.urinalysis": {"en": "Urinalysis", "uk": "Загальний аналіз сечі"},
    "special.urinalysis_what": {
        "en": "For painful or frequent urination: signs of a urinary infection.",
        "uk": "При болісному чи частому сечовипусканні: ознаки інфекції сечових шляхів.",
    },
    "special.procalcitonin": {"en": "Procalcitonin", "uk": "Прокальцитонін"},
    "special.procalcitonin_what": {
        "en": "Helps tell a bacterial infection from a viral one.",
        "uk": "Допомагає відрізнити бактеріальну інфекцію від вірусної.",
    },
    "special.flu-covid": {"en": "COVID-19 and flu", "uk": "COVID-19 і грип"},
    "special.flu-covid_what": {
        "en": "Swab tests (antigen or PCR) during a fever and cough.",
        "uk": "Тести з мазка (антиген або ПЛР) при температурі й кашлі.",
    },
    "special.covid": {"en": "COVID-19 swab test", "uk": "Тест на COVID-19 (мазок)"},
    "special.flu": {"en": "Flu A and B swab test", "uk": "Тест на грип A і B (мазок)"},
    "special.strep-a": {"en": "Throat culture for group A streptococcus", "uk": "Посів із зіву на стрептокок групи А"},
    "special.strep-a_what": {
        "en": "For a sore throat with fever: decides whether antibiotics will help.",
        "uk": "При болю в горлі з температурою: вирішує, чи допоможуть антибіотики.",
    },
    "special.urine-culture": {"en": "Urine culture", "uk": "Посів сечі"},
    "special.urine-culture_what": {
        "en": "Finds the germ behind a urinary infection and the antibiotics it responds to.",
        "uk": "Знаходить збудника інфекції сечових шляхів і антибіотики, до яких він чутливий.",
    },
    "special.gut-infection": {"en": "Gut infection PCR (bacteria and viruses)", "uk": "ПЛР на кишкові інфекції (бактерії й віруси)"},
    "special.gut-infection_what": {
        "en": "For diarrhoea lasting more than a few days, or with blood or fever.",
        "uk": "При діареї довше кількох днів або з кров'ю чи температурою.",
    },
    "special.gut-bacteria": {"en": "Gut bacteria PCR", "uk": "ПЛР на кишкові бактерії"},
    "special.gut-viruses": {"en": "Gut viruses PCR", "uk": "ПЛР на кишкові віруси"},
    "special.d-dimer": {"en": "D-dimer", "uk": "Д-димер"},
    "special.d-dimer_what": {
        "en": "A clot breakdown product; a normal result helps rule out a blood clot.",
        "uk": "Продукт розпаду тромбу; нормальний результат допомагає виключити тромб.",
    },
}
