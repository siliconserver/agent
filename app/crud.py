from datetime import date, timedelta

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

def compute_patauglich(member: "models.Member", today: date = None) -> bool:
    """
    Ein Geräteträger ist PA-tauglich, wenn:
    - die G26 nicht abgelaufen ist, UND
    - eine Belastungsübung im aktuellen oder letzten Kalenderjahr stattfand, UND
    - eine UVV-Unterweisung im aktuellen oder letzten Kalenderjahr stattfand.
    """
    today = today or date.today()
    valid_years = (today.year, today.year - 1)

    if member.g26_ablauf is None or member.g26_ablauf < today:
        return False

    if member.lastbelastung is None or member.lastbelastung.year not in valid_years:
        return False

    if member.uvv_unterweisung is None or member.uvv_unterweisung.year not in valid_years:
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
    today = date.today()
    valid_years = (today.year, today.year - 1)
    result = []
    for m in db.query(models.Member).filter(models.Member.agtaktiv.is_(True)).all():
        if m.lastbelastung is None or m.lastbelastung.year not in valid_years:
            result.append(m)
    return result


def members_missing_uvv(db: Session):
    """Aktive Geräteträger ohne UVV-Unterweisung im aktuellen oder letzten Kalenderjahr.

    Deckungsgleich mit dem Kriterium in compute_patauglich().
    """
    today = date.today()
    valid_years = (today.year, today.year - 1)
    result = []
    for m in db.query(models.Member).filter(models.Member.agtaktiv.is_(True)).all():
        if m.uvv_unterweisung is None or m.uvv_unterweisung.year not in valid_years:
            result.append(m)
    return result


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
