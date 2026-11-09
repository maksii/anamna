# Lab and clinic names

Every laboratory and clinic appears in the app under the name it gives itself: the Latin brand as the
provider writes it (exact capitalisation) for English and identifiers, the provider's own Ukrainian
name for Ukrainian. Not a transliteration we made up, not a description we wrote. Checked on
2026-11-09 against each provider's own website, its app-store developer listing, and for state
institutions the Unified State Register (ЄДР, read through opendatabot.ua).

When a name changes, the vendor's id changes with it (`pipeline.stable_id("vendor", name)`), so a
rename needs a migration that re-keys the `vendors` row and every row pointing at it; see
`migrations/050_lab_official_names.sql`.

## Lab-sync providers

| Provider key | English / Latin (as written by the provider) | Ukrainian | Legal entity | Proof |
|---|---|---|---|---|
| `esculab` | Esculab | Ескулаб (Медична лабораторія «Ескулаб») | not published on the site | [esculab.com](https://esculab.com) (`og:site_name` "Esculab"; page title «Медична лабораторія Ескулаб»; social handles `esculab.official`) |
| `synevo` | Synevo | Сінево | ТОВ «Сінево Україна» | [synevo.ua](https://www.synevo.ua) (title «Європейська медична лабораторія Сінево ... Synevo.ua»; `og:site_name` «Сінево»; footer «Сінево, 2026»; financial reports of ТОВ «Сінево Україна») |
| `expert` | Expert Hospital (logo and app: EXPERT) | Лікарня «Експерт» (also «Медична мережа ЕКСПЕРТ») | ТОВ «Експерт Медікал Груп» (site); app developer LIKARNIA EKSPERT TOV | [experthospital.com.ua](https://experthospital.com.ua/pro-nas/) (logo alt «ЕКСПЕРТ - медична мережа», footer © ТОВ «Експерт Медікал Груп»); [Google Play](https://play.google.com/store/apps/details?id=com.mobile.medexpert) («Лікарня ЕКСПЕРТ», "EXPERT hospital is your virtual ally..."); handles `expert_hospital`, `LikarniaEXPERT` |
| `paraskeva` | St. Paraskeva Medical Center | Медичний центр Святої Параскеви | ТОВ «Медичний Центр Святої Параскеви» (ST. PARASKEVA MEDICAL CENTRE, LLC) | [medcenter.lviv.ua](https://medcenter.lviv.ua/) (title, footer); [Google Play](https://play.google.com/store/apps/details?id=com.eleks.stparaskeva) (developer "St. Paraskeva Medical Center") |
| `veselka` | Veselka | Веселка (Приватна лікарня Веселка, мережа медичних центрів) | ТзОВ «Повноділ» | [veselka.clinic](https://veselka.clinic) (`og:site_name` "Veselka", «Центр сучасної медицини Veselka», footer © ТзОВ "ПОВНОДІЛ"); [Google Play](https://play.google.com/store/apps/details?id=com.eleks.veselka) (developer «ВЕСЕЛКА, ТОВ Повноділ») |
| (platform) | Doctor Eleks, by ELEKS | Doctor Eleks | ELEKS | [doctor.eleks.com](https://doctor.eleks.com/) (`og:site_name` "Doctor Eleks", footer © Doctor Eleks 2026) |

What was wrong before 2026-11-09:

- **EskuLab / `eskulab`**: our spelling. The laboratory writes Esculab (its domain, `og:site_name`
  and social handles) and «Ескулаб».
- **Ekspert / `ekspert`**: a transliteration of «Експерт» the hospital never uses as a brand. It
  appears only in the legal name of the app's developer company (LIKARNIA EKSPERT TOV, the
  passport-style transliteration of ТОВ «Лікарня Експерт»). The hospital itself writes EXPERT /
  Expert Hospital in Latin and «Лікарня «Експерт»» / «ЕКСПЕРТ» in Ukrainian.
- **Veselka Medical Center**: our English description. The clinic writes Veselka / «Веселка».
- **Doctor ELEKS**: the product writes itself Doctor Eleks; ELEKS in capitals is the company.
- «Медичний центр св. Параскеви»: the centre writes «Медичний центр Святої Параскеви».

Kept on purpose: files lab sync downloaded before the rename are named `eskulab-<order>.pdf` and
`ekspert-<order>.pdf` on disk, and the owner's archive uses `__eskulab__` in file names. Those are the
person's source files; the classifier (`LAB_SYNC_FILENAME_RE`, the Esculab vendor rule) recognises
both spellings. `audit_events` keeps the keys used at the time. "SILAB" in the parsers is not a lab:
it is the laboratory information system Synevo prints from, named in its report footers.

## Clinics recognised from documents

| Vendor name in the app | Ukrainian (phrases.py) | What the provider writes | Proof |
|---|---|---|---|
| MD Clinics | Медичний центр «Мати та дитина» | MD Clinics (JSON-LD), «Мати та дитина»; ТОВ «НЕОМЕД 2007» | [mdclinics.com.ua](https://mdclinics.com.ua/) |
| Oxford Medical Lviv | (brand, untranslated) | «Оксфорд Медікал Львів» (page title), Oxford Medical | [lviv.oxford-med.com.ua](https://lviv.oxford-med.com.ua/) |
| Medicover | (brand) | Medicover; ТОВ «Медікавер Україна» | [medicover.ua](https://medicover.ua/) |
| GastroLife | (brand) | GastroLife (title, footer) | [gastrolife.ua](https://gastrolife.ua/) |
| Ultramed | УльтраМед | Ultramed (`og:site_name`, footer «Copyright 2026 © Ultramed»), «УльтраМед» | [ultramed.lviv.ua](https://ultramed.lviv.ua/) |
| Parens | (brand) | Parens / Parens-Ukraine, «ПАРЕНС Україна» | [parens.com.ua](https://parens.com.ua/en/) |
| Lviv Medical Center | Львів Медікал Центр | Lviv Medical Center (`og:site_name`), LMC; ЄДРПОУ 44237940 | [lvivmedicalcenter.com](https://lvivmedicalcenter.com/), [ЄДР 44237940](https://opendatabot.ua/c/44237940) |
| LONO Clinic | Клініка «ЛОНО» | «Клініка "ЛОНО"», LONO in Latin text | [lono.clinic](https://lono.clinic/) |
| Lviv Regional Clinical Perinatal Center | Львівський обласний клінічний перинатальний центр | no Latin name published; КНП ЛОР «Львівський обласний клінічний перинатальний центр», ЄДРПОУ 20761103 | [perinatal.center](https://www.perinatal.center/), [ЄДР 20761103](https://opendatabot.ua/c/20761103) |
| Second Clinical Territorial Medical Association of Lviv | КНТ «Друге клінічне територіальне медичне об'єднання м. Львова» | no Latin name published; Комунальне некомерційне товариство, ЄДРПОУ 44625774 | [ЄДР 44625774](https://opendatabot.ua/c/44625774) |
| First Clinical Territorial Medical Association of Lviv, St. Luke's Hospital | КНТ «Перше клінічне територіальне медичне об'єднання м. Львова», лікарня Святого Луки | no Latin name published; Комунальне некомерційне товариство, ЄДРПОУ 44496574 | [ЄДР 44496574](https://opendatabot.ua/c/44496574) |
| InMed | (unchanged) | no website found for the Lviv centre; directory listing «ІнМед» | [list.in.ua](https://list.in.ua/) |
| Lviv Territorial Medical Association | (unchanged) | no register entry under this exact name; prints «Львівське територіальне медичне об'єднання» | - |
| Center of Medical 3D Diagnostics | Центр медичної 3D-діагностики | no website; directory listing «Центр Медичної 3D Діагностики» | [list.in.ua](https://list.in.ua/) |

English names for state institutions are translations of the register name, since none publishes
one. The register calls the two Lviv associations *товариства* (КНТ), not *підприємства* (КНП).
