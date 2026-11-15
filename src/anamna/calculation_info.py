"""Public provenance for arithmetic displayed beside a calculated result."""
from __future__ import annotations

from .lab_calculations import LAB_CALCULATIONS

BMI_SOURCE_URL = "https://www.cdc.gov/growth-chart-training/hcp/using-bmi/calculating-bmi.html"
EGFR_SOURCE_URL = "https://www.kidney.org/ckd-epi-creatinine-equation-2021"
CALCULATION_URLS = {item.method: item.source_url for item in LAB_CALCULATIONS}
CALCULATION_URLS.update(derived_ckd_epi_2021=EGFR_SOURCE_URL, derived_bmi=BMI_SOURCE_URL,
                        derived_profile_bmi=BMI_SOURCE_URL)


def calculation_source(method: object) -> str | None:
    return CALCULATION_URLS.get(str(method or ""))
