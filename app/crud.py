from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session, joinedload

import models


# --------------------------------------------------------------- Settings

def get_settings(db: Session) -> "models.Settings":
    """Holt die (einzige) Settings-Zeile, legt sie mit Defaults an falls nötig."""
    settings = db.query(models.Settings).filter(models.Settings.id == 1).first()
    if not settings:
        settings = models.Settings(id=1)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


WEEKDAYS = [
    ("mon", "Montag"),
    ("tue", "Dienstag"),
    ("wed", "Mittwoch"),
    ("thu", "Donnerstag"),
    ("fri", "Freitag"),
    ("sat", "Samstag"),
    ("sun", "Sonntag"),
]


# --------------------------------------------------------- Tauglichkeit
#
# Fristregel für UVV-Unterweisung und Belastungsübung: „jährlich“ heißt
# einmal pro Kalenderjahr, nicht 12 Monate ab Datum. Ein Nachweis gilt im
# Jahr, in dem er absolviert wurde, und im ganzen folgenden Kalenderjahr,
# also bis zum 31.12.(Jahr + 1). Ab dem 01.01. des übernächsten Jahres ist
# er ungültig. Alle Stellen (Tauglichkeitslauf, Dashboard, Mitgliederliste,
# Berichte, PDF/CSV-Export, Wochenreport) nutzen ausschließlich die
# folgenden Hilfsfunktionen.

def is_valid_calendar_year(d: Optional[date], today: Optional[date] = None) -> bool:
    """True, wenn `d` im aktuellen oder im vorherigen Kalenderjahr liegt.
    Fehlt das Datum, ist der Nachweis ungültig."""
    if d is None:
        return False
    today = today or date.today()
    return d.year in (today.year, today.year - 1)


def calendar_year_valid_until(d: Optional[date]) -> Optional[date]:
    """Letzter gültiger Tag eines Nachweises: 31.12.(Jahr + 1)."""
    if d is None:
        return None
    return date(d.year + 1, 12, 31)


def expires_end_of_year(d: Optional[date], today: Optional[date] = None) -> bool:
    """True, wenn der Nachweis noch gilt, aber nur bis zum 31.12. des
    aktuellen Jahres (er stammt also aus dem Vorjahr)."""
    today = today or date.today()
    return is_valid_calendar_year(d, today) and d.year == today.year - 1


def compute_patauglich(member: "models.Member", today: date = None) -> bool:
    """
    Ein Geräteträger ist PA-tauglich, wenn:
    - die G26 nicht abgelaufen ist, UND
    - die letzte Belastungsübung im aktuellen oder vorherigen Kalenderjahr liegt, UND
    - die letzte UVV-Unterweisung im aktuellen oder vorherigen Kalenderjahr liegt.
    Fehlt eines der Daten, ist der Geräteträger untauglich.
    """
    today = today or date.today()

    if member.g26_ablauf is None or member.g26_ablauf < today:
        return False

    if not is_valid_calendar_year(member.lastbelastung, today):
        return False

    if not is_valid_calendar_year(member.uvv_unterweisung, today):
        return False

    return True


def update_all_tauglichkeit(db: Session):
    """Berechnet patauglich für alle Geräteträger neu und speichert Änderungen."""
    today = date.today()
    changed = []
    for m in db.query(models.Member).all():
        new_val = compute_patauglich(m, today)
        if m.patauglich != new_val:
            m.patauglich = new_val
            changed.append(m)
    db.commit()
    return changed


def members_g26_expiring(db: Session, days: int = 90):
    today = date.today()
    limit = today + timedelta(days=days)
    return (
        db.query(models.Member)
        .filter(
            models.Member.agtaktiv.is_(True),
            models.Member.g26_ablauf.isnot(None),
            models.Member.g26_ablauf >= today,
            models.Member.g26_ablauf <= limit,
        )
        .order_by(models.Member.g26_ablauf)
        .all()
    )


def members_g26_expired(db: Session):
    today = date.today()
    return (
        db.query(models.Member)
        .filter(
            models.Member.agtaktiv.is_(True),
            models.Member.g26_ablauf.isnot(None),
            models.Member.g26_ablauf < today,
        )
        .order_by(models.Member.g26_ablauf)
        .all()
    )


def members_missing_belastung(db: Session):
    """Aktive Geräteträger ohne gültige Belastungsübung (Kalenderjahr-Regel)."""
    today = date.today()
    return [m for m in members_active(db) if not is_valid_calendar_year(m.lastbelastung, today)]


def members_missing_uvv(db: Session):
    """Aktive Geräteträger ohne gültige UVV-Unterweisung (Kalenderjahr-Regel).

    Deckungsgleich mit dem Kriterium in compute_patauglich().
    """
    today = date.today()
    return [m for m in members_active(db) if not is_valid_calendar_year(m.uvv_unterweisung, today)]


def members_expiring_year_end(db: Session):
    """Aktive Geräteträger, deren UVV-Unterweisung oder Belastungsübung nur
    noch bis zum 31.12. des aktuellen Jahres gültig ist (aus dem Vorjahr)."""
    today = date.today()
    return [
        m
        for m in members_active(db)
        if expires_end_of_year(m.uvv_unterweisung, today)
        or expires_end_of_year(m.lastbelastung, today)
    ]


def members_active(db: Session):
    return (
        db.query(models.Member)
        .filter(models.Member.agtaktiv.is_(True))
        .order_by(models.Member.name, models.Member.vorname)
        .all()
    )


def members_tauglich(db: Session):
    return (
        db.query(models.Member)
        .filter(models.Member.agtaktiv.is_(True), models.Member.patauglich.is_(True))
        .order_by(models.Member.name, models.Member.vorname)
        .all()
    )


def members_untauglich(db: Session):
    return (
        db.query(models.Member)
        .filter(models.Member.agtaktiv.is_(True), models.Member.patauglich.is_(False))
        .order_by(models.Member.name, models.Member.vorname)
        .all()
    )


def get_stats(db: Session):
    all_members = db.query(models.Member).all()
    total = len(all_members)
    active = [m for m in all_members if m.agtaktiv]
    active_count = len(active)
    tauglich = [m for m in active if m.patauglich]
    untauglich = [m for m in active if not m.patauglich]

    def pct(n, d):
        return round(n / d * 100, 1) if d else 0.0

    return {
        "total": total,
        "active": active_count,
        "active_pct": pct(active_count, total),
        "tauglich": len(tauglich),
        "tauglich_pct": pct(len(tauglich), active_count),
        "untauglich": len(untauglich),
        "untauglich_pct": pct(len(untauglich), active_count),
    }


# ---------------------------------------------------------- Belastungsübung

def belastung_years(db: Session):
    years = {
        d.year for (d,) in db.query(models.BelastungTermin.datum).all()
    }
    return sorted(years, reverse=True)


def belastung_termine_for_year(db: Session, year: int):
    return (
        db.query(models.BelastungTermin)
        .options(
            joinedload(models.BelastungTermin.teilnahmen).joinedload(
                models.BelastungTeilnahme.member
            )
        )
        .filter(
            models.BelastungTermin.datum >= date(year, 1, 1),
            models.BelastungTermin.datum <= date(year, 12, 31),
        )
        .order_by(models.BelastungTermin.datum)
        .all()
    )


def run_belastung_transfer(db: Session):
    """Schreibt bei abgelaufenen Terminen nextbelastung -> lastbelastung
    für alle zugewiesenen AGT (sicher wie auf Rückfrage)."""
    today = date.today()
    faellige = (
        db.query(models.BelastungTermin)
        .options(joinedload(models.BelastungTermin.teilnahmen))
        .filter(
            models.BelastungTermin.datum < today,
            models.BelastungTermin.transferred.is_(False),
        )
        .all()
    )
    for termin in faellige:
        for teilnahme in termin.teilnahmen:
            m = teilnahme.member
            if not m.lastbelastung or termin.datum > m.lastbelastung:
                m.lastbelastung = termin.datum
            if m.nextbelastung == termin.datum:
                m.nextbelastung = None
        termin.transferred = True
    db.commit()


def belastung_termine_upcoming(db: Session, days: int = 3):
    """Termine, die innerhalb der nächsten `days` Tage stattfinden (inkl. heute)."""
    today = date.today()
    limit = today + timedelta(days=days)
    return (
        db.query(models.BelastungTermin)
        .options(
            joinedload(models.BelastungTermin.teilnahmen).joinedload(
                models.BelastungTeilnahme.member
            )
        )
        .filter(
            models.BelastungTermin.datum >= today,
            models.BelastungTermin.datum <= limit,
        )
        .all()
    )
