"""E-Mail-Abruf: liest neue Mails aus einem Postfach und legt daraus ToDos an.

Die Auswertung arbeitet bewusst nur mit Stichworten und einem Namensabgleich
gegen die Geräteträger-Liste, damit keine Daten den eigenen Server verlassen.

Zugangsdaten zum Postfach kommen aus der .env:
    IMAP_HOST, IMAP_PORT (993), IMAP_USER, IMAP_PASSWORD,
    IMAP_FOLDER (INBOX), IMAP_DONE_FOLDER (optional), IMAP_SSL (true)
"""

import email
import email.policy
import imaplib
import io
import logging
import os
import re
import threading
import unicodedata
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime
from html import unescape

import models

logger = logging.getLogger("mailimport")

# maximale Größe eines Anhangs, der am ToDo gespeichert wird
MAX_ANHANG_BYTES = 15 * 1024 * 1024
# maximale Zahl an ToDos, die aus einer einzelnen Mail entstehen dürfen
MAX_TODOS_PRO_MAIL = 10
# Anhänge, die gespeichert werden (alles andere, z.B. Signatur-Logos, wird ignoriert)
ANHANG_ENDUNGEN = (".pdf", ".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff", ".doc", ".docx", ".odt")
# Bilder darunter sind meist Logos aus Signaturen
MIN_BILD_BYTES = 30 * 1024

_lock = threading.Lock()


# ------------------------------------------------------------ Konfiguration

def get_config():
    return {
        "host": (os.environ.get("IMAP_HOST") or "").strip(),
        "port": int(os.environ.get("IMAP_PORT") or "993"),
        "user": os.environ.get("IMAP_USER") or "",
        "password": os.environ.get("IMAP_PASSWORD") or "",
        "folder": (os.environ.get("IMAP_FOLDER") or "INBOX").strip(),
        "done_folder": (os.environ.get("IMAP_DONE_FOLDER") or "").strip(),
        "ssl": (os.environ.get("IMAP_SSL") or "true").lower() == "true",
    }


def is_configured() -> bool:
    cfg = get_config()
    return bool(cfg["host"] and cfg["user"])


# ------------------------------------------------------------ Normalisieren

def normalize(text: str) -> str:
    """Kleinbuchstaben, Umlaute ausgeschrieben, Akzente weg, nur Buchstaben/Ziffern."""
    text = (text or "").lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(a, b)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9.]+", " ", text)
    return f" {text.strip()} "


# ---------------------------------------------------------- Stichwort-Regeln

# Reihenfolge = Priorität. Die Muster laufen auf normalisiertem Text
# (Umlaute als ae/oe/ue, Satzzeichen als Leerzeichen).
KATEGORIE_REGELN = [
    ("G26-Nachweis", [
        r" g ?26", r" g 26 3", r"arbeitsmedizin", r"atemschutztauglichkeit", r"eignungsuntersuchung",
        r"vorsorgeuntersuchung", r"betriebsarzt", r"dguv vorsorge", r"tauglichkeitsbescheinigung",
    ]),
    ("Belastungsübung", [
        r"belastungsuebung", r"belastungs ?strecke", r"atemschutz ?strecke", r"uebungsstrecke",
        r"belastungstest", r"finnentest",
    ]),
    ("UVV-Unterweisung", [
        r" uvv", r"unterweisung", r"sicherheitsbelehrung",
    ]),
    ("AGT-/CSA-Lehrgang", [
        r"lehrgang", r" csa ", r"chemikalienschutz", r"atemschutzgeraetetraeger ?ausbildung",
        r"teilnahmebescheinigung", r"teilnahmebestaetigung",
    ]),
    ("Einsatz", [
        r"einsatzbericht", r"einsatznachweis", r"atemschutzeinsatz", r"atemschutz ?nachweis",
    ]),
]
_KATEGORIE_RE = [(k, [re.compile(p) for p in pats]) for k, pats in KATEGORIE_REGELN]


def find_kategorien(text: str):
    norm = normalize(text)
    return [k for k, pats in _KATEGORIE_RE if any(p.search(norm) for p in pats)]


# ------------------------------------------------------------ Namensabgleich

def _word_re(phrase: str):
    return re.compile(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])")


def find_members(text: str, members, absender_email: str = ""):
    """Liefert (gefundene Mitglieder, sicher?).

    1. Vor- und Nachname zusammen („Max Muster“, „Muster, Max“, „Muster Max“)
    2. sonst Absender-Adresse = hinterlegte E-Mail eines Geräteträgers
    3. sonst eindeutiger Nachname (nur ein AGT heißt so) → unsicher, bitte prüfen
    """
    norm = normalize(text)
    found = []
    for m in members:
        vn, nn = normalize(m.vorname).strip(), normalize(m.name).strip()
        if not vn or not nn:
            continue
        if _word_re(f"{vn} {nn}").search(norm) or _word_re(f"{nn} {vn}").search(norm):
            found.append(m)
    if found:
        return found, True

    absender_email = (absender_email or "").strip().lower()
    if absender_email:
        by_mail = [m for m in members if m.email and m.email.strip().lower() == absender_email]
        if len(by_mail) == 1:
            return by_mail, True

    nachnamen = {}
    for m in members:
        nn = normalize(m.name).strip()
        if len(nn) >= 3:
            nachnamen.setdefault(nn, []).append(m)
    by_name = [ms[0] for nn, ms in nachnamen.items() if len(ms) == 1 and _word_re(nn).search(norm)]
    if by_name:
        return by_name, False
    return [], False


# ------------------------------------------------------------- Mail zerlegen

def _decode(part) -> str:
    try:
        return part.get_content()
    except Exception:
        payload = part.get_payload(decode=True) or b""
        return payload.decode(part.get_content_charset() or "utf-8", errors="replace")


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", html)
    return unescape(re.sub(r"<[^>]+>", " ", html))


def pdf_text(data: bytes) -> str:
    """Text aus einem PDF (nur Text-PDFs; eingescannte Bilder liefern nichts)."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:20])
    except Exception as exc:
        logger.info("PDF-Text nicht lesbar: %s", exc)
        return ""


def parse_message(raw: bytes):
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    name, addr = parseaddr(str(msg.get("From", "")))
    try:
        empfangen = parsedate_to_datetime(str(msg.get("Date"))) if msg.get("Date") else None
    except Exception:
        empfangen = None

    text_plain, text_html, anhaenge = [], [], []
    for part in msg.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        ctype = part.get_content_type()
        disp = part.get_content_disposition()
        if filename or disp == "attachment":
            data = part.get_payload(decode=True) or b""
            filename = filename or "anhang"
            low = filename.lower()
            if not low.endswith(ANHANG_ENDUNGEN) or len(data) > MAX_ANHANG_BYTES:
                continue
            if ctype.startswith("image/") and len(data) < MIN_BILD_BYTES:
                continue
            text = pdf_text(data) if low.endswith(".pdf") else ""
            anhaenge.append({"dateiname": filename, "content_type": ctype, "daten": data, "text": text})
        elif ctype == "text/plain":
            text_plain.append(_decode(part))
        elif ctype == "text/html":
            text_html.append(_html_to_text(_decode(part)))

    body = "\n".join(text_plain) if text_plain else "\n".join(text_html)
    return {
        "message_id": (str(msg.get("Message-ID") or "").strip()
                       or f"ohne-id:{addr}:{msg.get('Date')}:{msg.get('Subject')}")[:512],
        "absender_name": name,
        "absender": addr,
        "betreff": str(msg.get("Subject") or "").strip(),
        "empfangen_am": empfangen,
        "body": body,
        "anhaenge": anhaenge,
    }


# ------------------------------------------------------------ Auswertung

def _sender_allowed(addr: str, allowed: str) -> bool:
    entries = [e.strip().lower() for e in re.split(r"[,;\s]+", allowed or "") if e.strip()]
    if not entries:
        return True
    addr = (addr or "").lower()
    for e in entries:
        if e.startswith("@") and addr.endswith(e):
            return True
        if "@" not in e and addr.endswith("@" + e):
            return True
        if addr == e:
            return True
    return False


def analyse(parsed, members):
    """Baut aus einer zerlegten Mail die anzulegenden ToDos.

    Jeder Anhang wird für sich geprüft (eine Mail kann z.B. drei G26-Bescheinigungen
    für drei AGT enthalten). Was im Anhang selbst nicht steht, wird aus Betreff und
    Mailtext ergänzt. Ohne Anhang zählt nur die Mail selbst.

    Liefert eine Liste von Dicts: kategorie, member, pruefen, hinweise, anhaenge.
    """
    mail_text = f"{parsed['betreff']}\n{parsed['body']}"
    mail_kats = find_kategorien(mail_text)
    mail_members, mail_sicher = find_members(mail_text, members, parsed["absender"])

    einheiten = []
    for a in parsed["anhaenge"]:
        einheiten.append((f"{a['dateiname']}\n{a['text']}", [a]))
    if not einheiten:
        einheiten.append(("", []))

    todos = {}
    for text, anhaenge in einheiten:
        kats = find_kategorien(text) if text else []
        mems, sicher = find_members(text, members) if text else ([], False)
        if not kats:
            kats = mail_kats
        if not mems:
            mems, sicher = mail_members, mail_sicher

        for kat in (kats or [None]):
            for m in (mems or [None]):
                key = (kat, m.id if m else None)
                t = todos.get(key)
                if t is None:
                    hinweise = []
                    if not kat:
                        hinweise.append("Art nicht erkannt")
                    if not m:
                        hinweise.append("Geräteträger nicht erkannt")
                    elif not sicher:
                        hinweise.append("Geräteträger nur am Nachnamen erkannt")
                    t = todos[key] = {
                        "kategorie": kat or "Sonstiges",
                        "member": m,
                        "pruefen": bool(hinweise),
                        "hinweise": hinweise,
                        "anhaenge": [],
                    }
                for a in anhaenge:
                    if a not in t["anhaenge"]:
                        t["anhaenge"].append(a)
    return list(todos.values())[:MAX_TODOS_PRO_MAIL]


def store_mail(db, parsed, members, abruf_id=None, allowed_senders=""):
    """Wertet eine Mail aus, legt ToDos und Protokolleintrag an. Liefert Anzahl ToDos
    oder None, wenn die Mail schon einmal verarbeitet wurde."""
    exists = db.query(models.MailEingang.id).filter(
        models.MailEingang.message_id == parsed["message_id"]
    ).first()
    if exists:
        return None

    eingang = models.MailEingang(
        message_id=parsed["message_id"],
        abruf_id=abruf_id,
        absender=(f"{parsed['absender_name']} <{parsed['absender']}>" if parsed["absender_name"]
                  else parsed["absender"])[:512],
        betreff=parsed["betreff"],
        empfangen_am=parsed["empfangen_am"],
        anhaenge=len(parsed["anhaenge"]),
    )
    db.add(eingang)
    db.flush()

    if not _sender_allowed(parsed["absender"], allowed_senders):
        eingang.ergebnis = "Ignoriert: Absender nicht freigegeben"
        return 0

    vorschlaege = analyse(parsed, members)
    datum = (parsed["empfangen_am"] or datetime.now(timezone.utc)).astimezone().strftime("%d.%m.%Y")
    ergebnis = []
    for v in vorschlaege:
        m = v["member"]
        titel = v["kategorie"] if v["kategorie"] != "Sonstiges" else f"E-Mail: {parsed['betreff'] or '(ohne Betreff)'}"
        bemerkung = f"Aus E-Mail von {parsed['absender_name'] or parsed['absender']} vom {datum}: „{parsed['betreff'] or '(ohne Betreff)'}“"
        if v["hinweise"]:
            bemerkung += "\nBitte prüfen: " + ", ".join(v["hinweise"]) + "."
        todo = models.Todo(
            titel=titel[:255],
            kategorie=v["kategorie"],
            member_id=m.id if m else None,
            bemerkung=bemerkung,
            status="todo",
            erstellt_von="E-Mail",
            pruefen=v["pruefen"],
            mail_id=eingang.id,
        )
        for a in v["anhaenge"]:
            todo.anhaenge.append(models.TodoAnhang(
                dateiname=a["dateiname"][:255],
                content_type=a["content_type"],
                groesse=len(a["daten"]),
                daten=a["daten"],
            ))
        db.add(todo)
        wer = f"{m.vorname} {m.name}" if m else "ohne AGT"
        ergebnis.append(f"{v['kategorie']} ({wer}{', prüfen' if v['pruefen'] else ''})")

    eingang.todos_erstellt = len(vorschlaege)
    eingang.ergebnis = "; ".join(ergebnis)
    return len(vorschlaege)


# ------------------------------------------------------------------ IMAP

def _connect(cfg):
    if cfg["ssl"]:
        conn = imaplib.IMAP4_SSL(cfg["host"], cfg["port"], timeout=30)
    else:
        conn = imaplib.IMAP4(cfg["host"], cfg["port"], timeout=30)
        try:
            conn.starttls()
        except Exception:
            pass
    conn.login(cfg["user"], cfg["password"])
    return conn


def _move(conn, uid, folder):
    typ, _ = conn.uid("MOVE", uid, folder)
    if typ != "OK":
        typ, _ = conn.uid("COPY", uid, folder)
        if typ == "OK":
            conn.uid("STORE", uid, "+FLAGS", r"(\Deleted)")
            conn.expunge()


def run_import(db):
    """Ruft neue (ungelesene) Mails ab und wertet sie aus.

    Liefert den angelegten MailAbruf oder None, wenn nichts konfiguriert ist
    oder gerade schon ein Abruf läuft.
    """
    if not is_configured():
        return None
    if not _lock.acquire(blocking=False):
        return None
    cfg = get_config()
    abruf = models.MailAbruf(zeitpunkt=datetime.now(timezone.utc))
    db.add(abruf)
    db.commit()
    try:
        settings = db.query(models.Settings).filter(models.Settings.id == 1).first()
        allowed = settings.mail_import_allowed_senders if settings else ""
        members = db.query(models.Member).all()

        conn = _connect(cfg)
        try:
            conn.select(cfg["folder"])
            typ, data = conn.uid("SEARCH", None, "UNSEEN")
            uids = data[0].split() if typ == "OK" and data and data[0] else []
            for uid in uids:
                typ, msg_data = conn.uid("FETCH", uid, "(BODY.PEEK[])")
                raw = next((p[1] for p in msg_data if isinstance(p, tuple)), None)
                if not raw:
                    continue
                parsed = None
                try:
                    parsed = parse_message(raw)
                    anzahl = store_mail(db, parsed, members, abruf.id, allowed)
                    if anzahl is not None:
                        abruf.mails_gelesen += 1
                        abruf.todos_erstellt += anzahl
                    db.commit()
                except Exception as exc:
                    # im Protokoll vermerken und als gelesen markieren, damit
                    # dieselbe kaputte Mail nicht bei jedem Abruf erneut scheitert
                    db.rollback()
                    logger.exception("Mail %s konnte nicht ausgewertet werden", uid)
                    abruf.fehler = f"Mindestens eine Mail konnte nicht ausgewertet werden: {exc}"[:1000]
                    abruf.mails_gelesen += 1
                    if parsed:
                        db.add(models.MailEingang(
                            message_id=parsed["message_id"],
                            abruf_id=abruf.id,
                            absender=parsed["absender"][:512],
                            betreff=parsed["betreff"],
                            ergebnis=f"Fehler bei der Auswertung: {exc}"[:1000],
                        ))
                    try:
                        db.commit()
                    except Exception:
                        db.rollback()
                conn.uid("STORE", uid, "+FLAGS", r"(\Seen)")
                if cfg["done_folder"]:
                    _move(conn, uid, cfg["done_folder"])
        finally:
            try:
                conn.logout()
            except Exception:
                pass
    except Exception as exc:
        db.rollback()
        logger.exception("E-Mail-Abruf fehlgeschlagen")
        abruf.fehler = f"Abruf fehlgeschlagen: {exc}"[:1000]
    finally:
        db.commit()
        _lock.release()
    logger.info("E-Mail-Abruf: %s Mails gelesen, %s ToDos erstellt", abruf.mails_gelesen, abruf.todos_erstellt)
    return abruf
