import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import backup
import crud
import emailer
import models
from database import SessionLocal

logger = logging.getLogger("scheduler")
TZ = os.environ.get("TZ") or "Europe/Berlin"


def _parse_hhmm(value: str, default=(6, 0)):
    try:
        h, m = value.split(":")
        return int(h), int(m)
    except Exception:
        return default


def run_tauglichkeit_check():
    """Überträgt abgelaufene Belastungsübungs-Termine, verschickt fällige
    Belastungsübungs-Erinnerungen und berechnet patauglich für alle
    Geräteträger neu."""
    db = SessionLocal()
    try:
        crud.run_belastung_transfer(db)
        reminded = _send_belastung_reminders(db)
        changed = crud.update_all_tauglichkeit(db)
        logger.info(
            f"Tauglichkeitsprüfung abgeschlossen, {len(changed)} Änderungen, "
            f"{reminded} Belastungsübungs-Erinnerungen verschickt"
        )
    except Exception:
        logger.exception("Fehler bei der Tauglichkeitsprüfung")
        db.rollback()
    finally:
        db.close()


def _send_belastung_reminders(db):
    """Verschickt Erinnerungsmails an AGT, deren Belastungsübung in den
    nächsten 3 Tagen stattfindet, inkl. Liste der weiteren Teilnehmer."""
    settings = crud.get_settings(db)
    termine = crud.belastung_termine_upcoming(db, days=3)
    sent = 0
    for termin in termine:
        for teilnahme in termin.teilnahmen:
            m = teilnahme.member
            if teilnahme.reminder_sent or not m.email:
                continue

            andere = [t for t in termin.teilnahmen if t.member_id != m.id]
            teilnehmer_text = "\n".join(
                f"- {t.member.vorname} {t.member.name}" for t in andere
            ) or "Keine weiteren Teilnehmer."

            subject = settings.belastung_reminder_subject
            try:
                body = settings.belastung_reminder_body.format(
                    vorname=m.vorname,
                    name=m.name,
                    datum=termin.datum.strftime("%d.%m.%Y"),
                    uhrzeit=termin.uhrzeit or "-",
                    ort=termin.ort or "-",
                    bemerkung=termin.bemerkung or "-",
                    status="Sicher" if teilnahme.status == models.TeilnahmeStatus.sicher else "Auf Rückfrage",
                    teilnehmer=teilnehmer_text,
                )
            except Exception:
                body = settings.belastung_reminder_body
            emailer.send_mail(m.email, subject, body)
            teilnahme.reminder_sent = True
            sent += 1
    db.commit()
    return sent


def run_send_reminder_emails():
    """Verschickt G26-Erinnerungsmails an Personen, deren G26 in <=90 Tagen abläuft."""
    db = SessionLocal()
    try:
        settings = crud.get_settings(db)
        expiring = crud.members_g26_expiring(db, days=90)
        sent = 0
        for m in expiring:
            if m.email and m.g26_reminder_sent_for != m.g26_ablauf:
                subject = settings.g26_reminder_subject
                try:
                    body = settings.g26_reminder_body.format(
                        vorname=m.vorname,
                        name=m.name,
                        ablauf=m.g26_ablauf.strftime("%d.%m.%Y"),
                    )
                except Exception:
                    body = settings.g26_reminder_body
                emailer.send_mail(m.email, subject, body, bcc=settings.g26_reminder_bcc)
                m.g26_reminder_sent_for = m.g26_ablauf
                sent += 1
        db.commit()
        logger.info(f"Erinnerungsmails verschickt: {sent}")
    except Exception:
        logger.exception("Fehler beim Versand der Erinnerungsmails")
        db.rollback()
    finally:
        db.close()


def run_weekly_report():
    """Verschickt den wöchentlichen Statusreport per Mail an den Administrator."""
    db = SessionLocal()
    try:
        settings = crud.get_settings(db)
        admin_email = settings.admin_email
        if not admin_email:
            logger.warning("Kein admin_email in den Einstellungen gesetzt, überspringe Wochenreport")
            return

        stats = crud.get_stats(db)
        expiring = crud.members_g26_expiring(db, days=90)
        expired = crud.members_g26_expired(db)
        missing = crud.members_missing_belastung(db)
        missing_uvv = crud.members_missing_uvv(db)

        active = db.query(models.Member).filter(models.Member.agtaktiv.is_(True)).all()
        tauglich = [m for m in active if m.patauglich]
        untauglich = [m for m in active if not m.patauglich]

        def fmt(m, extra=""):
            return f"  - {m.vorname} {m.name}{extra}"

        lines = [settings.weekly_report_intro.rstrip(), ""]
        lines.append(f"AGT insgesamt:   {stats['total']}")
        lines.append(f"AGT aktiv:       {stats['active']} ({stats['active_pct']}%)")
        lines.append(f"Tauglich:        {stats['tauglich']} ({stats['tauglich_pct']}%)")
        lines.append(f"Untauglich:      {stats['untauglich']} ({stats['untauglich_pct']}%)")
        lines.append("")

        lines.append(f"Tauglich ({len(tauglich)}):")
        lines += [fmt(m) for m in tauglich] or ["  -"]
        lines.append("")

        lines.append(f"Untauglich ({len(untauglich)}):")
        lines += [fmt(m) for m in untauglich] or ["  -"]
        lines.append("")

        lines.append(f"G26 läuft in den nächsten 3 Monaten ab ({len(expiring)}):")
        lines += [
            fmt(m, f" - Ablauf {m.g26_ablauf.strftime('%d.%m.%Y')}") for m in expiring
        ] or ["  -"]
        lines.append("")

        lines.append(f"G26 bereits abgelaufen ({len(expired)}):")
        lines += [
            fmt(m, f" - Ablauf {m.g26_ablauf.strftime('%d.%m.%Y')}") for m in expired
        ] or ["  -"]
        lines.append("")

        lines.append(f"Keine Belastungsübung dieses/letztes Jahr ({len(missing)}):")
        lines += [
            fmt(m, f" - letzte: {m.lastbelastung.strftime('%d.%m.%Y') if m.lastbelastung else 'nie'}")
            for m in missing
        ] or ["  -"]
        lines.append("")

        lines.append(f"Keine UVV-Unterweisung dieses/letztes Jahr ({len(missing_uvv)}):")
        lines += [
            fmt(m, f" - letzte: {m.uvv_unterweisung.strftime('%d.%m.%Y') if m.uvv_unterweisung else 'nie'}")
            for m in missing_uvv
        ] or ["  -"]

        emailer.send_mail(admin_email, settings.weekly_report_subject, "\n".join(lines))
    except Exception:
        logger.exception("Fehler beim wöchentlichen Report")
    finally:
        db.close()


def run_backup_job():
    db = SessionLocal()
    try:
        settings = crud.get_settings(db)
        backup.run_backup(retention=settings.backup_retention)
    except Exception:
        logger.exception("Fehler beim automatischen Backup")
    finally:
        db.close()


def reschedule(scheduler: BackgroundScheduler):
    """Liest die aktuellen Einstellungen und setzt alle Cron-Jobs entsprechend neu."""
    db = SessionLocal()
    try:
        settings = crud.get_settings(db)
    finally:
        db.close()

    h, m = _parse_hhmm(settings.tauglichkeit_check_time, (6, 0))
    scheduler.add_job(
        run_tauglichkeit_check,
        CronTrigger(hour=h, minute=m, timezone=TZ),
        id="tauglichkeit_check",
        replace_existing=True,
    )

    h, m = _parse_hhmm(settings.email_send_time, (6, 30))
    scheduler.add_job(
        run_send_reminder_emails,
        CronTrigger(hour=h, minute=m, timezone=TZ),
        id="send_reminder_emails",
        replace_existing=True,
    )

    h, m = _parse_hhmm(settings.weekly_report_time, (7, 0))
    scheduler.add_job(
        run_weekly_report,
        CronTrigger(day_of_week=settings.weekly_report_day, hour=h, minute=m, timezone=TZ),
        id="weekly_report",
        replace_existing=True,
    )

    h, m = _parse_hhmm(settings.backup_time, (3, 0))
    scheduler.add_job(
        run_backup_job,
        CronTrigger(hour=h, minute=m, timezone=TZ),
        id="backup_job",
        replace_existing=True,
    )

    logger.info(
        "Zeitplan aktualisiert: Tauglichkeit=%s Mails=%s Wochenreport=%s %s Backup=%s",
        settings.tauglichkeit_check_time,
        settings.email_send_time,
        settings.weekly_report_day,
        settings.weekly_report_time,
        settings.backup_time,
    )


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=TZ)
    scheduler.start()
    reschedule(scheduler)
    return scheduler
