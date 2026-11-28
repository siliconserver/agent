import enum

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import deferred, relationship
from sqlalchemy.sql import func

from database import Base


class Role(str, enum.Enum):
    admin = "admin"
    viewer = "viewer"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum(Role), nullable=False, default=Role.viewer)

    # nullable, da nachträglich per _ensure_column zu einer bestehenden
    # Tabelle hinzugefügt (siehe main.py on_startup)
    totp_secret = Column(String(32), nullable=True)
    totp_enabled = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Member(Base):
    __tablename__ = "members"

    id = Column(Integer, primary_key=True)

    name = Column(String(128), nullable=False)
    vorname = Column(String(128), nullable=False)
    email = Column(String(255), nullable=True)

    agtlehrgang = Column(Date, nullable=True)
    csalehrgang = Column(Date, nullable=True)

    lastbelastung = Column(Date, nullable=True)
    nextbelastung = Column(Date, nullable=True)

    g26_ausstellung = Column(Date, nullable=True)
    g26_ablauf = Column(Date, nullable=True)

    lasteinsatz_agt = Column(Date, nullable=True)
    lasteinsatz_csa = Column(Date, nullable=True)

    patauglich = Column(Boolean, nullable=False, default=False)
    csatauglich = Column(Boolean, nullable=False, default=False)
    agtaktiv = Column(Boolean, nullable=False, default=True)

    # Datum der letzten UVV-Unterweisung. Gilt im Jahr der Unterweisung und
    # im ganzen folgenden Kalenderjahr (siehe crud.is_valid_calendar_year).
    # nullable, da nachträglich per _ensure_column zu einer bestehenden
    # Tabelle hinzugefügt (siehe main.py on_startup)
    uvv_unterweisung = Column(Date, nullable=True)

    kommentar = Column(Text, nullable=True)

    # merkt sich, für welches Ablaufdatum bereits eine Erinnerungsmail
    # verschickt wurde, damit nicht jeden Tag erneut gemailt wird
    g26_reminder_sent_for = Column(Date, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


DEFAULT_G26_REMINDER_SUBJECT = "G26-Untersuchung läuft bald ab"
DEFAULT_G26_REMINDER_BODY = (
    "Hallo {vorname} {name},\n\n"
    "deine G26-Untersuchung läuft am {ablauf} ab.\n"
    "Bitte kümmere dich rechtzeitig um einen neuen Termin.\n\n"
    "Viele Grüße\nAGENT"
)
DEFAULT_G26_REMINDER_BCC = None  # optional, unter Einstellungen → E-Mail-Texte
DEFAULT_WEEKLY_REPORT_SUBJECT = "Wöchentlicher Atemschutz-Report"
DEFAULT_WEEKLY_REPORT_INTRO = (
    "Hallo,\n\nhier der wöchentliche Überblick über die Atemschutzgeräteträger:\n"
)
DEFAULT_BELASTUNG_ASSIGN_SUBJECT = "Du wurdest für eine Belastungsübung eingetragen"
DEFAULT_BELASTUNG_ASSIGN_BODY = (
    "Hallo {vorname} {name},\n\n"
    "du wurdest für folgende Belastungsübung eingetragen:\n\n"
    "Datum: {datum}\n"
    "Uhrzeit: {uhrzeit}\n"
    "Ort: {ort}\n"
    "Status: {status}\n"
    "Bemerkung: {bemerkung}\n\n"
    "Viele Grüße\nAGENT"
)
DEFAULT_BELASTUNG_REMINDER_SUBJECT = "Erinnerung: Belastungsübung in 3 Tagen"
DEFAULT_BELASTUNG_REMINDER_BODY = (
    "Hallo {vorname} {name},\n\n"
    "Erinnerung: In wenigen Tagen findet deine Belastungsübung statt.\n\n"
    "Datum: {datum}\n"
    "Uhrzeit: {uhrzeit}\n"
    "Ort: {ort}\n"
    "Status: {status}\n"
    "Bemerkung: {bemerkung}\n\n"
    "Weitere Teilnehmer:\n{teilnehmer}\n\n"
    "Viele Grüße\nAGENT"
)


class Settings(Base):
    """Singleton-Tabelle (immer nur die Zeile mit id=1) mit allen konfigurierbaren Einstellungen."""

    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, default=1)

    # Empfänger des wöchentlichen Reports
    admin_email = Column(String(255), nullable=True)

    # Zeitplan (jeweils "HH:MM", 24h)
    tauglichkeit_check_time = Column(String(5), nullable=False, default="06:00")
    email_send_time = Column(String(5), nullable=False, default="06:30")
    weekly_report_day = Column(String(3), nullable=False, default="mon")  # mon..sun
    weekly_report_time = Column(String(5), nullable=False, default="07:00")
    backup_time = Column(String(5), nullable=False, default="03:00")
    backup_retention = Column(Integer, nullable=False, default=14)

    # E-Mail-Texte
    g26_reminder_subject = Column(Text, nullable=False, default=DEFAULT_G26_REMINDER_SUBJECT)
    g26_reminder_body = Column(Text, nullable=False, default=DEFAULT_G26_REMINDER_BODY)
    g26_reminder_bcc = Column(String(255), nullable=True, default=DEFAULT_G26_REMINDER_BCC)
    weekly_report_subject = Column(Text, nullable=False, default=DEFAULT_WEEKLY_REPORT_SUBJECT)
    weekly_report_intro = Column(Text, nullable=False, default=DEFAULT_WEEKLY_REPORT_INTRO)

    # nullable, da nachträglich per _ensure_column zu einer bestehenden Tabelle
    # hinzugefügt (siehe main.py on_startup) – Default wird dort per Python befüllt
    belastung_assign_subject = Column(Text, nullable=True, default=DEFAULT_BELASTUNG_ASSIGN_SUBJECT)
    belastung_assign_body = Column(Text, nullable=True, default=DEFAULT_BELASTUNG_ASSIGN_BODY)
    belastung_reminder_subject = Column(Text, nullable=True, default=DEFAULT_BELASTUNG_REMINDER_SUBJECT)
    belastung_reminder_body = Column(Text, nullable=True, default=DEFAULT_BELASTUNG_REMINDER_BODY)

    # E-Mail-Abruf (Zugangsdaten zum Postfach stehen in der .env, siehe mailimport.py)
    # Abstand zwischen zwei Abrufen in Minuten, 0 = automatischer Abruf aus
    mail_import_interval = Column(Integer, nullable=True, default=60)
    # nur Mails dieser Absender auswerten (Adressen oder @domain, kommagetrennt); leer = alle
    mail_import_allowed_senders = Column(Text, nullable=True)
    # Mails ignorieren, wenn eines dieser Wörter im Betreff oder Text steht (eins pro Zeile)
    mail_import_ignore_words = Column(Text, nullable=True)

    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TeilnahmeStatus(str, enum.Enum):
    sicher = "sicher"
    rueckfrage = "rueckfrage"


class BelastungTermin(Base):
    __tablename__ = "belastung_termine"

    id = Column(Integer, primary_key=True)
    datum = Column(Date, nullable=False)
    uhrzeit = Column(String(5), nullable=True)
    ort = Column(String(255), nullable=True)
    bemerkung = Column(Text, nullable=True)

    # verhindert, dass der tägliche Transfer-Job nextbelastung/lastbelastung
    # bei bereits abgeschlossenen Terminen erneut anfasst
    transferred = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    teilnahmen = relationship(
        "BelastungTeilnahme", back_populates="termin", cascade="all, delete-orphan"
    )


class BelastungTeilnahme(Base):
    __tablename__ = "belastung_teilnahmen"
    __table_args__ = (UniqueConstraint("termin_id", "member_id", name="uq_termin_member"),)

    id = Column(Integer, primary_key=True)
    termin_id = Column(Integer, ForeignKey("belastung_termine.id", ondelete="CASCADE"), nullable=False)
    member_id = Column(Integer, ForeignKey("members.id", ondelete="CASCADE"), nullable=False)
    status = Column(Enum(TeilnahmeStatus), nullable=False)
    reminder_sent = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    termin = relationship("BelastungTermin", back_populates="teilnahmen")
    member = relationship("Member")


# ---------------------------------------------------------------- ToDo ----

TODO_STATUS = {
    "todo": "ToDo",
    "in_arbeit": "In Arbeit",
    "erledigt": "Erledigt",
}

TODO_KATEGORIEN = [
    "G26-Nachweis",
    "Belastungsübung",
    "UVV-Unterweisung",
    "AGT-/CSA-Lehrgang",
    "Einsatz",
    "Sonstiges",
]


class Todo(Base):
    """Eingegangener Nachweis o.ä., der noch ins Verwaltungsprogramm muss.

    Erledigte Einträge verschwinden einen Tag nach dem Erledigen aus der
    Liste (siehe crud.todos_visible); sie bleiben aber in der Datenbank.
    """

    __tablename__ = "todos"

    id = Column(Integer, primary_key=True)
    titel = Column(String(255), nullable=False)
    kategorie = Column(String(64), nullable=True)
    member_id = Column(Integer, ForeignKey("members.id", ondelete="SET NULL"), nullable=True)
    bemerkung = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, default="todo")  # siehe TODO_STATUS
    erledigt_am = Column(DateTime(timezone=True), nullable=True)
    erstellt_von = Column(String(64), nullable=True)

    # gesetzt, wenn das ToDo automatisch aus einer E-Mail entstanden ist
    mail_id = Column(Integer, ForeignKey("mail_eingang.id", ondelete="SET NULL"), nullable=True)
    # automatisch erzeugt, aber Art oder Geräteträger nicht sicher erkannt
    pruefen = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    member = relationship("Member")
    mail = relationship("MailEingang")
    anhaenge = relationship(
        "TodoAnhang", back_populates="todo", cascade="all, delete-orphan", order_by="TodoAnhang.id"
    )


class TodoAnhang(Base):
    """Datei (meist PDF) aus einer E-Mail, die an einem ToDo hängt.

    Liegt bewusst in der Datenbank, damit sie mit im Backup (pg_dump) ist.
    """

    __tablename__ = "todo_anhaenge"

    id = Column(Integer, primary_key=True)
    todo_id = Column(Integer, ForeignKey("todos.id", ondelete="CASCADE"), nullable=False, index=True)
    dateiname = Column(String(255), nullable=False)
    content_type = Column(String(128), nullable=True)
    groesse = Column(Integer, nullable=False, default=0)
    # deferred: wird erst beim Download geladen, nicht bei jeder ToDo-Liste
    daten = deferred(Column(LargeBinary, nullable=False))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    todo = relationship("Todo", back_populates="anhaenge")


# ---------------------------------------------------------- E-Mail-Abruf ----

class MailEingang(Base):
    """Protokoll jeder abgerufenen E-Mail. Die Message-ID verhindert,
    dass dieselbe Mail zweimal ausgewertet wird."""

    __tablename__ = "mail_eingang"

    id = Column(Integer, primary_key=True)
    message_id = Column(String(512), nullable=False, unique=True, index=True)
    abruf_id = Column(Integer, ForeignKey("mail_abrufe.id", ondelete="SET NULL"), nullable=True)
    absender = Column(String(512), nullable=True)
    betreff = Column(Text, nullable=True)
    empfangen_am = Column(DateTime(timezone=True), nullable=True)
    anhaenge = Column(Integer, nullable=False, default=0)
    todos_erstellt = Column(Integer, nullable=False, default=0)
    ergebnis = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MailAbruf(Base):
    """Ein Durchlauf des E-Mail-Abrufs, für den Hinweis im Dashboard."""

    __tablename__ = "mail_abrufe"

    id = Column(Integer, primary_key=True)
    zeitpunkt = Column(DateTime(timezone=True), server_default=func.now())
    mails_gelesen = Column(Integer, nullable=False, default=0)
    todos_erstellt = Column(Integer, nullable=False, default=0)
    fehler = Column(Text, nullable=True)
