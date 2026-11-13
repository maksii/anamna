"""Which of the person's medicines and supplements belong to a diagnosis, and why.

A medicine belongs to a diagnosis when the person linked it to that diagnosis, or when its
ATC group is one the WHO ATC classification names for that kind of condition and the person
has not said otherwise.  The match is by group and is shown with its reason (basis), never as
advice: the page says which group matched and that the person can remove it.

The functions take an open connection whose rows are ``sqlite3.Row`` and never commit: the
caller does.  They return keys and data; pages translate.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import NamedTuple

from anamna import factors
from anamna.db import utc_now

SOURCE_URL = "https://atcddd.fhi.no/atc_ddd_index/"
_KINDS = ("medicine", "supplement")


class Group(NamedTuple):
    key: str  # message key suffix: t("dx.atc." + key) is the group's name
    atc: tuple[str, ...]  # ATC code prefixes, upper case
    icd: tuple[str, ...]  # ICD-10 code prefixes, e.g. "I10", "E79.0"


# ATC groups from the WHO ATC/DDD Index (SOURCE_URL) and the ICD-10 categories each group is used for.  A group here names its use in its own title or is a first-line class for the condition.
GROUPS: tuple[Group, ...] = (
    Group("c02", ("C02",), ("I10", "I11", "I12", "I13", "I15")),
    Group("c03", ("C03",), ("I10", "I11", "I12", "I13", "I15", "I50")),
    Group("c07", ("C07",), ("I10", "I11", "I12", "I13", "I15", "I20", "I25", "I48", "I50")),
    Group("c08", ("C08",), ("I10", "I11", "I12", "I13", "I15", "I20")),
    Group("c09", ("C09",), ("I10", "I11", "I12", "I13", "I15", "I50")),
    Group("c10", ("C10",), ("E78",)),
    Group("a10", ("A10",), ("E10", "E11", "E13", "E14")),
    Group("h03a", ("H03A",), ("E02", "E03", "E89.0")),
    Group("h03b", ("H03B",), ("E05",)),
    Group("m04", ("M04",), ("M10", "E79.0")),
    Group("b03a", ("B03A",), ("D50", "E61.1")),
    Group("b03b", ("B03B",), ("D51", "D52", "E53.8")),
    Group("a11cc", ("A11CC",), ("E55",)),
    Group("r03", ("R03",), ("J44", "J45", "J46")),
    Group("a02b", ("A02B",), ("K21", "K25", "K26", "K27", "K28")),
    Group("b01a", ("B01A",), ("I20", "I21", "I25", "I26", "I48", "I63", "I80", "I82")),
    Group("m05b", ("M05B",), ("M80", "M81")),
    Group("n06a", ("N06A",), ("F32", "F33")),
    Group("n03a", ("N03A",), ("G40",)),
    Group("g04c", ("G04C",), ("N40",)),
    Group("s01e", ("S01E",), ("H40",)),
    Group("r06a", ("R06A",), ("J30", "L50")),
    Group("a08a", ("A08A",), ("E66",)),
    Group("n02c", ("N02C",), ("G43",)),
    Group("n04", ("N04",), ("G20",)),
    Group("n06d", ("N06D",), ("F00", "G30")),
)


def _match(atc_code: str, icd_code: str) -> tuple[Group, str] | None:
    """The first group whose ATC and ICD prefixes both match, with the ATC prefix that matched."""
    atc = (atc_code or "").strip().upper()
    icd = (icd_code or "").strip().upper()
    if not atc or not icd:
        return None
    for group in GROUPS:
        prefix = next((p for p in group.atc if atc.startswith(p)), None)
        if prefix and any(icd.startswith(p) for p in group.icd):
            return group, prefix
    return None


def group_for(atc_code: str, icd_code: str) -> Group | None:
    """The group a medicine with this ATC code belongs to for a diagnosis with this ICD-10 code."""
    found = _match(atc_code, icd_code)
    return found[0] if found else None


def _links(connection, owner_id: str, diagnosis_id: str) -> dict[str, int]:
    """The person's own choices for one diagnosis: factor id -> linked (1 or 0)."""
    rows = connection.execute(
        "SELECT factor_id, linked FROM diagnosis_medicines WHERE diagnosis_id=? AND owner_user_id=?",
        (diagnosis_id, owner_id),
    ).fetchall()
    return {row["factor_id"]: row["linked"] for row in rows}


def medicines(connection, owner_id: str, diagnosis: Mapping, *, today: date) -> list[dict]:
    """The owner's medicines and supplements that belong to the diagnosis, in listing order.

    Each item: ``{"factor", "basis", "group", "atc_prefix"}``.  ``basis`` is ``"linked"`` when the
    person linked it, else ``"atc"`` when its ATC group matches.  ``group`` and ``atc_prefix`` are
    empty when the ATC group does not match (a linked medicine without a matching group).
    """
    links = _links(connection, owner_id, diagnosis["id"])
    found: list[dict] = []
    for factor in factors.listing(connection, owner_id, today=today):
        if factor["kind"] not in _KINDS:
            continue
        state = links.get(factor["id"])
        if state == 0:
            continue
        match = _match(factor["atc_code"], diagnosis["code"])
        if state == 1:
            basis = "linked"
        elif match is not None:
            basis = "atc"
        else:
            continue
        group, prefix = match if match else (None, "")
        found.append({
            "factor": factor,
            "basis": basis,
            "group": group.key if group else "",
            "atc_prefix": prefix,
        })
    return found


def choices(connection, owner_id: str, diagnosis: Mapping, *, today: date) -> list[dict]:
    """The owner's medicines and supplements that ``medicines`` does not return for the diagnosis."""
    shown = {item["factor"]["id"] for item in medicines(connection, owner_id, diagnosis, today=today)}
    return [
        factor
        for factor in factors.listing(connection, owner_id, today=today)
        if factor["kind"] in _KINDS and factor["id"] not in shown
    ]


def _write_link(connection, owner_id: str, diagnosis_id: str, factor_id: str, linked: int) -> bool:
    """Record the person's choice; False when the diagnosis or the factor is not theirs or of another kind."""
    if connection.execute(
        "SELECT 1 FROM diagnoses WHERE id=? AND owner_user_id=?", (diagnosis_id, owner_id)
    ).fetchone() is None:
        return False
    row = connection.execute(
        "SELECT kind FROM factors WHERE id=? AND owner_user_id=?", (factor_id, owner_id)
    ).fetchone()
    if row is None or row["kind"] not in _KINDS:
        return False
    connection.execute(
        "INSERT INTO diagnosis_medicines (diagnosis_id, factor_id, owner_user_id, linked, updated_at) "
        "VALUES (?,?,?,?,?) ON CONFLICT(diagnosis_id, factor_id) "
        "DO UPDATE SET linked=excluded.linked, updated_at=excluded.updated_at",
        (diagnosis_id, factor_id, owner_id, linked, utc_now()),
    )
    return True


def link(connection, owner_id: str, diagnosis_id: str, factor_id: str) -> bool:
    """The person says this medicine is for this diagnosis."""
    return _write_link(connection, owner_id, diagnosis_id, factor_id, 1)


def unlink(connection, owner_id: str, diagnosis_id: str, factor_id: str) -> bool:
    """The person says this medicine is not for this diagnosis, hiding an ATC match."""
    return _write_link(connection, owner_id, diagnosis_id, factor_id, 0)


def names(connection, owner_id: str, diagnosis: Mapping, *, today: date) -> list[str]:
    """The names of the diagnosis's medicines that are not over."""
    return [
        item["factor"]["name"]
        for item in medicines(connection, owner_id, diagnosis, today=today)
        if item["factor"]["effective_status"] != "past"
    ]
