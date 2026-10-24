import io
import os
from datetime import date, datetime

import pyotp
import qrcode
import qrcode.image.svg
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

import auth
import backup
import crud
import emailer
import exports
import models
from database import Base, engine, get_db
from scheduler import (
    TZ,
    reschedule,
    run_send_reminder_emails,
    run_tauglichkeit_check,
    run_weekly_report,
    start_scheduler,
)

app = FastAPI(title="AGENT")
app.add_middleware(
    SessionMiddleware, secret_key=os.environ.get("SECRET_KEY", "change-me-please")
)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/sw.js")
def service_worker():
    # aus dem Root-Pfad statt /static/sw.js ausgeliefert, damit der Scope
    # die ganze App abdeckt und nicht nur /static/
    with open("static/sw.js", encoding="utf-8") as f:
        js = f.read().replace("__APP_VERSION__", APP_VERSION)
    return Response(js, media_type="application/javascript", headers={"Cache-Control": "no-cache"})

MESSAGES = {
    "tauglichkeit_ok": "Tauglichkeitsprüfung wurde ausgeführt.",
    "emails_ok": "Erinnerungsmails wurden verschickt.",
    "schedule_ok": "Zeitplan gespeichert.",
    "email_ok": "E-Mail-Einstellungen gespeichert.",
    "weekly_ok": "Wochenreport wurde verschickt.",
    "user_created": "Benutzer wurde angelegt.",
    "user_exists": "Dieser Benutzername existiert bereits.",
    "user_deleted": "Benutzer wurde gelöscht.",
    "user_self": "Du kannst dich nicht selbst löschen.",
    "user_last_admin": "Der letzte Admin kann nicht gelöscht oder herabgestuft werden.",
    "user_role_updated": "Rolle wurde geändert.",
    "user_role_self": "Du kannst deine eigene Rolle nicht ändern.",
    "password_updated": "Passwort wurde geändert.",
    "password_wrong": "Aktuelles Passwort ist falsch.",
    "password_mismatch": "Die neuen Passwörter stimmen nicht überein.",
    "backup_ok": "Backup wurde erstellt.",
    "backup_error": "Backup fehlgeschlagen, siehe Server-Log.",
    "backup_deleted": "Backup wurde gelöscht.",
    "restore_ok": "Backup wurde eingespielt.",
    "restore_error": "Wiederherstellung fehlgeschlagen, siehe Server-Log.",
    "restore_not_confirmed": "Wiederherstellung abgebrochen: Bestätigung fehlt.",
    "termin_created": "Termin wurde angelegt.",
    "termin_updated": "Termin wurde gespeichert.",
    "termin_deleted": "Termin wurde gelöscht.",
    "teilnahme_added": "AGT wurde zugewiesen.",
    "teilnahme_removed": "Zuweisung wurde entfernt.",
    "teilnahme_exists": "Dieser AGT ist diesem Termin bereits zugewiesen.",
    "teilnahme_full": "Diese Gruppe ist bereits voll.",
    "member_deleted": "Geräteträger wurde gelöscht.",
    "totp_enabled": "Zwei-Faktor-Authentifizierung wurde aktiviert.",
    "totp_disabled": "Zwei-Faktor-Authentifizierung wurde deaktiviert.",
    "totp_invalid": "Code ungültig, bitte erneut versuchen.",
    "totp_disable_wrong_password": "Passwort falsch, 2FA wurde nicht deaktiviert.",
}
templates.env.globals["MESSAGES"] = MESSAGES

def load_changelog():
    """Liest CHANGELOG.md (Abschnitte "## <Version> (<Datum>)" mit "- " Punkten)."""
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.join(here, "CHANGELOG.md"), os.path.join(here, "..", "CHANGELOG.md")):
        if os.path.exists(path):
            break
    else:
        return []
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("## "):
                head = line[3:].strip()
                version, _, date = head.partition(" ")
                entries.append({"version": version, "date": date.strip("()"), "items": []})
            elif line.startswith("- ") and entries:
                entries[-1]["items"].append(line[2:].strip())
    return entries


CHANGELOG = load_changelog()
APP_VERSION = CHANGELOG[0]["version"] if CHANGELOG else "unbekannt"
templates.env.globals["APP_VERSION"] = APP_VERSION
templates.env.globals["CHANGELOG"] = CHANGELOG

# Optionale Links im Footer, je Installation über .env gesetzt
templates.env.globals["IMPRESSUM_URL"] = os.environ.get("IMPRESSUM_URL", "").strip()
templates.env.globals["DATENSCHUTZ_URL"] = os.environ.get("DATENSCHUTZ_URL", "").strip()
templates.env.globals["TIMEZONE"] = TZ


def parse_date(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def current_user(request: Request, db: Session):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.query(models.User).filter(models.User.id == user_id).first()


def require_admin(user):
    if not user or user.role != models.Role.admin:
        raise HTTPException(403, "Nur für Admins")


def _ensure_column(table: str, column: str, ddl_type: str):
    """Fügt eine fehlende Spalte an einer bestehenden Tabelle hinzu.

    create_all() legt neue Tabellen an, ändert aber bestehende nicht ab.
    """
    insp = inspect(engine)
    existing = [c["name"] for c in insp.get_columns(table)]
    if column not in existing:
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
        print(f"Spalte {table}.{column} wurde ergänzt.")


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    _ensure_column("settings", "g26_reminder_bcc", "VARCHAR(255)")
    _ensure_column("settings", "belastung_assign_subject", "TEXT")
    _ensure_column("settings", "belastung_assign_body", "TEXT")
    _ensure_column("settings", "belastung_reminder_subject", "TEXT")
    _ensure_column("settings", "belastung_reminder_body", "TEXT")
    _ensure_column("belastung_teilnahmen", "reminder_sent", "BOOLEAN NOT NULL DEFAULT FALSE")
    _ensure_column("users", "totp_secret", "VARCHAR(32)")
    _ensure_column("users", "totp_enabled", "BOOLEAN NOT NULL DEFAULT FALSE")
    _ensure_column("members", "uvv_unterweisung", "DATE")

    db = next(get_db())
    try:
        if db.query(models.User).count() == 0:
            admin_user = os.environ.get("ADMIN_USERNAME", "admin")
            admin_pw = os.environ.get("ADMIN_PASSWORD", "changeme")
            db.add(
                models.User(
                    username=admin_user,
                    password_hash=auth.hash_password(admin_pw),
                    role=models.Role.admin,
                )
            )
            db.commit()
            print(f"Admin-Benutzer '{admin_user}' angelegt.")

        settings = crud.get_settings(db)
        if not settings.admin_email:
            env_admin_email = os.environ.get("ADMIN_EMAIL")
            if env_admin_email:
                settings.admin_email = env_admin_email
                db.commit()
        if not settings.belastung_assign_subject:
            settings.belastung_assign_subject = models.DEFAULT_BELASTUNG_ASSIGN_SUBJECT
        if not settings.belastung_assign_body:
            settings.belastung_assign_body = models.DEFAULT_BELASTUNG_ASSIGN_BODY
        if not settings.belastung_reminder_subject:
            settings.belastung_reminder_subject = models.DEFAULT_BELASTUNG_REMINDER_SUBJECT
        if not settings.belastung_reminder_body:
            settings.belastung_reminder_body = models.DEFAULT_BELASTUNG_REMINDER_BODY
        db.commit()

        crud.update_all_tauglichkeit(db)
    finally:
        db.close()

    app.state.scheduler = start_scheduler()


# ---------------------------------------------------------------- Auth ----

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user or not auth.verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Benutzername oder Passwort falsch"},
            status_code=401,
        )

    if user.totp_enabled:
        request.session["pending_2fa_user_id"] = user.id
        return RedirectResponse("/login/2fa", status_code=303)

    request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=303)


@app.get("/login/2fa", response_class=HTMLResponse)
def login_2fa_form(request: Request):
    if not request.session.get("pending_2fa_user_id"):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse("login_2fa.html", {"request": request, "error": None})


@app.post("/login/2fa")
def login_2fa(request: Request, code: str = Form(...), db: Session = Depends(get_db)):
    user_id = request.session.get("pending_2fa_user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user or not user.totp_enabled or not pyotp.TOTP(user.totp_secret).verify(code, valid_window=1):
        return templates.TemplateResponse(
            "login_2fa.html",
            {"request": request, "error": "Code ungültig"},
            status_code=401,
        )

    del request.session["pending_2fa_user_id"]
    request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/about", response_class=HTMLResponse)
def about_page(request: Request, db: Session = Depends(get_db)):
    # bewusst ohne Login-Zwang, erreichbar auch aus dem Footer der Login-Seite
    user = current_user(request, db)
    return templates.TemplateResponse("about.html", {"request": request, "user": user})


# -------------------------------------------------------------- Profil ----

def _totp_qr_svg(uri: str) -> str:
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=8)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse("profile.html", {"request": request, "user": user})


@app.post("/profile/password")
def profile_change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    new_password_confirm: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    if not auth.verify_password(current_password, user.password_hash):
        return RedirectResponse("/profile?msg=password_wrong", status_code=303)
    if new_password != new_password_confirm:
        return RedirectResponse("/profile?msg=password_mismatch", status_code=303)

    user.password_hash = auth.hash_password(new_password)
    db.commit()
    return RedirectResponse("/profile?msg=password_updated", status_code=303)


@app.get("/profile/2fa/setup", response_class=HTMLResponse)
def profile_2fa_setup_form(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if user.totp_enabled:
        return RedirectResponse("/profile", status_code=303)

    secret = request.session.get("pending_totp_secret")
    if not secret:
        secret = pyotp.random_base32()
        request.session["pending_totp_secret"] = secret

    uri = pyotp.TOTP(secret).provisioning_uri(name=user.username, issuer_name="AGENT")
    return templates.TemplateResponse(
        "profile_2fa_setup.html",
        {
            "request": request,
            "user": user,
            "secret": secret,
            "qr_svg": _totp_qr_svg(uri),
            "error": None,
        },
    )


@app.post("/profile/2fa/setup")
def profile_2fa_setup(request: Request, code: str = Form(...), db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    secret = request.session.get("pending_totp_secret")
    if not secret or not pyotp.TOTP(secret).verify(code, valid_window=1):
        return RedirectResponse("/profile/2fa/setup?msg=totp_invalid", status_code=303)

    user.totp_secret = secret
    user.totp_enabled = True
    db.commit()
    del request.session["pending_totp_secret"]
    return RedirectResponse("/profile?msg=totp_enabled", status_code=303)


@app.post("/profile/2fa/disable")
def profile_2fa_disable(
    request: Request, current_password: str = Form(...), db: Session = Depends(get_db)
):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    if not auth.verify_password(current_password, user.password_hash):
        return RedirectResponse("/profile?msg=totp_disable_wrong_password", status_code=303)

    user.totp_secret = None
    user.totp_enabled = False
    db.commit()
    return RedirectResponse("/profile?msg=totp_disabled", status_code=303)


# ---------------------------------------------------------- Dashboard ----

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    stats = crud.get_stats(db)
    expiring = crud.members_g26_expiring(db, 90)
    expired = crud.members_g26_expired(db)
    missing = crud.members_missing_belastung(db)
    missing_uvv = crud.members_missing_uvv(db)
    tauglich = crud.members_tauglich(db)
    untauglich = crud.members_untauglich(db)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "stats": stats,
            "expiring": expiring,
            "expired": expired,
            "missing": missing,
            "missing_uvv": missing_uvv,
            "tauglich": tauglich,
            "untauglich": untauglich,
        },
    )


@app.post("/admin/run-tauglichkeit-check")
def admin_run_tauglichkeit_check(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)
    run_tauglichkeit_check()
    return RedirectResponse("/?msg=tauglichkeit_ok", status_code=303)


@app.post("/admin/run-send-emails")
def admin_run_send_emails(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)
    run_send_reminder_emails()
    return RedirectResponse("/?msg=emails_ok", status_code=303)


# ------------------------------------------------------------ Members ----

@app.get("/members", response_class=HTMLResponse)
def members_list(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    members = (
        db.query(models.Member)
        .order_by(models.Member.name, models.Member.vorname)
        .all()
    )
    return templates.TemplateResponse(
        "members_list.html", {"request": request, "user": user, "members": members}
    )


@app.get("/members/export.csv")
def members_export_csv(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    members = db.query(models.Member).order_by(models.Member.name, models.Member.vorname).all()
    csv_data = exports.members_to_csv(members)
    filename = f"agt_geraetetraeger_{datetime.now().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([csv_data.encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/members/new", response_class=HTMLResponse)
def member_new_form(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)
    return templates.TemplateResponse(
        "member_form.html", {"request": request, "user": user, "member": None}
    )


@app.post("/members/new")
def member_new(
    request: Request,
    name: str = Form(...),
    vorname: str = Form(...),
    email: str = Form(""),
    agtlehrgang: str = Form(""),
    csalehrgang: str = Form(""),
    lastbelastung: str = Form(""),
    nextbelastung: str = Form(""),
    g26_ausstellung: str = Form(""),
    g26_ablauf: str = Form(""),
    lasteinsatz_agt: str = Form(""),
    lasteinsatz_csa: str = Form(""),
    uvv_unterweisung: str = Form(""),
    csatauglich: str = Form(None),
    agtaktiv: str = Form(None),
    kommentar: str = Form(""),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)

    m = models.Member(
        name=name,
        vorname=vorname,
        email=email or None,
        agtlehrgang=parse_date(agtlehrgang),
        csalehrgang=parse_date(csalehrgang),
        lastbelastung=parse_date(lastbelastung),
        nextbelastung=parse_date(nextbelastung),
        g26_ausstellung=parse_date(g26_ausstellung),
        g26_ablauf=parse_date(g26_ablauf),
        lasteinsatz_agt=parse_date(lasteinsatz_agt),
        lasteinsatz_csa=parse_date(lasteinsatz_csa),
        uvv_unterweisung=parse_date(uvv_unterweisung),
        csatauglich=bool(csatauglich),
        agtaktiv=bool(agtaktiv) if agtaktiv is not None else True,
        kommentar=kommentar or None,
    )
    m.patauglich = crud.compute_patauglich(m)
    db.add(m)
    db.commit()
    return RedirectResponse(f"/members/{m.id}", status_code=303)


@app.get("/members/{member_id}", response_class=HTMLResponse)
def member_detail(member_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    member = db.query(models.Member).filter(models.Member.id == member_id).first()
    if not member:
        raise HTTPException(404, "Nicht gefunden")
    return templates.TemplateResponse(
        "member_detail.html", {"request": request, "user": user, "member": member}
    )


@app.get("/members/{member_id}/edit", response_class=HTMLResponse)
def member_edit_form(member_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)
    member = db.query(models.Member).filter(models.Member.id == member_id).first()
    if not member:
        raise HTTPException(404, "Nicht gefunden")
    return templates.TemplateResponse(
        "member_form.html", {"request": request, "user": user, "member": member}
    )


@app.post("/members/{member_id}/edit")
def member_edit(
    member_id: int,
    request: Request,
    name: str = Form(...),
    vorname: str = Form(...),
    email: str = Form(""),
    agtlehrgang: str = Form(""),
    csalehrgang: str = Form(""),
    lastbelastung: str = Form(""),
    nextbelastung: str = Form(""),
    g26_ausstellung: str = Form(""),
    g26_ablauf: str = Form(""),
    lasteinsatz_agt: str = Form(""),
    lasteinsatz_csa: str = Form(""),
    uvv_unterweisung: str = Form(""),
    csatauglich: str = Form(None),
    agtaktiv: str = Form(None),
    kommentar: str = Form(""),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)

    member = db.query(models.Member).filter(models.Member.id == member_id).first()
    if not member:
        raise HTTPException(404, "Nicht gefunden")

    old_g26_ablauf = member.g26_ablauf

    member.name = name
    member.vorname = vorname
    member.email = email or None
    member.agtlehrgang = parse_date(agtlehrgang)
    member.csalehrgang = parse_date(csalehrgang)
    member.lastbelastung = parse_date(lastbelastung)
    member.nextbelastung = parse_date(nextbelastung)
    member.g26_ausstellung = parse_date(g26_ausstellung)
    member.g26_ablauf = parse_date(g26_ablauf)
    member.lasteinsatz_agt = parse_date(lasteinsatz_agt)
    member.lasteinsatz_csa = parse_date(lasteinsatz_csa)
    member.uvv_unterweisung = parse_date(uvv_unterweisung)
    member.csatauglich = bool(csatauglich)
    member.agtaktiv = bool(agtaktiv) if agtaktiv is not None else False
    member.kommentar = kommentar or None

    if member.g26_ablauf != old_g26_ablauf:
        member.g26_reminder_sent_for = None

    member.patauglich = crud.compute_patauglich(member)
    db.commit()
    return RedirectResponse(f"/members/{member_id}", status_code=303)


@app.post("/members/{member_id}/toggle_active")
def member_toggle_active(member_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)

    member = db.query(models.Member).filter(models.Member.id == member_id).first()
    if not member:
        raise HTTPException(404, "Nicht gefunden")

    member.agtaktiv = not member.agtaktiv
    db.commit()
    return RedirectResponse(f"/members/{member_id}", status_code=303)


@app.post("/members/{member_id}/delete")
def member_delete(member_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)

    member = db.query(models.Member).filter(models.Member.id == member_id).first()
    if not member:
        raise HTTPException(404, "Nicht gefunden")

    db.delete(member)
    db.commit()
    return RedirectResponse("/members?msg=member_deleted", status_code=303)


# ------------------------------------------------------------ Reports ----

@app.get("/reports", response_class=HTMLResponse)
def reports(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    expiring = crud.members_g26_expiring(db, 90)
    expired = crud.members_g26_expired(db)
    missing = crud.members_missing_belastung(db)
    missing_uvv = crud.members_missing_uvv(db)

    return templates.TemplateResponse(
        "reports.html",
        {
            "request": request,
            "user": user,
            "expiring": expiring,
            "expired": expired,
            "missing": missing,
            "missing_uvv": missing_uvv,
        },
    )


@app.get("/reports/pdf")
def reports_pdf(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    stats = crud.get_stats(db)
    expiring = crud.members_g26_expiring(db, 90)
    expired = crud.members_g26_expired(db)
    missing = crud.members_missing_belastung(db)
    missing_uvv = crud.members_missing_uvv(db)
    tauglich = crud.members_tauglich(db)
    untauglich = crud.members_untauglich(db)

    pdf_bytes = exports.build_reports_pdf(
        stats, expiring, expired, missing, tauglich, untauglich, missing_uvv
    )
    filename = f"agt_bericht_{datetime.now().strftime('%Y%m%d')}.pdf"
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --------------------------------------------------- Belastungsübung ----

SICHER_LIMIT = 6
RUECKFRAGE_LIMIT = 4


def _render_belastung_list(request: Request, db: Session, year: int):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    termine = crud.belastung_termine_for_year(db, year)
    for t in termine:
        t.sicher = [x for x in t.teilnahmen if x.status == models.TeilnahmeStatus.sicher]
        t.rueckfrage = [x for x in t.teilnahmen if x.status == models.TeilnahmeStatus.rueckfrage]
    years = [y for y in crud.belastung_years(db) if y != year]

    return templates.TemplateResponse(
        "belastung_list.html",
        {
            "request": request,
            "user": user,
            "termine": termine,
            "year": year,
            "now_year": date.today().year,
            "years": years,
            "sicher_limit": SICHER_LIMIT,
            "rueckfrage_limit": RUECKFRAGE_LIMIT,
        },
    )


@app.get("/belastung", response_class=HTMLResponse)
def belastung_current_year(request: Request, db: Session = Depends(get_db)):
    return _render_belastung_list(request, db, date.today().year)


@app.get("/belastung/jahr/{year}", response_class=HTMLResponse)
def belastung_year(year: int, request: Request, db: Session = Depends(get_db)):
    return _render_belastung_list(request, db, year)


@app.get("/belastung/termin/new", response_class=HTMLResponse)
def belastung_termin_new_form(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)
    return templates.TemplateResponse(
        "belastung_form.html", {"request": request, "user": user, "termin": None}
    )


@app.post("/belastung/termin/new")
def belastung_termin_new(
    request: Request,
    datum: str = Form(...),
    uhrzeit: str = Form(""),
    ort: str = Form(""),
    bemerkung: str = Form(""),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)

    t = models.BelastungTermin(
        datum=parse_date(datum),
        uhrzeit=uhrzeit or None,
        ort=ort or None,
        bemerkung=bemerkung or None,
    )
    db.add(t)
    db.commit()
    return RedirectResponse(f"/belastung/jahr/{t.datum.year}?msg=termin_created", status_code=303)


@app.get("/belastung/termin/{termin_id}/edit", response_class=HTMLResponse)
def belastung_termin_edit_form(termin_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)
    termin = db.query(models.BelastungTermin).filter(models.BelastungTermin.id == termin_id).first()
    if not termin:
        raise HTTPException(404, "Nicht gefunden")
    return templates.TemplateResponse(
        "belastung_form.html", {"request": request, "user": user, "termin": termin}
    )


@app.post("/belastung/termin/{termin_id}/edit")
def belastung_termin_edit(
    termin_id: int,
    request: Request,
    datum: str = Form(...),
    uhrzeit: str = Form(""),
    ort: str = Form(""),
    bemerkung: str = Form(""),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)

    termin = db.query(models.BelastungTermin).filter(models.BelastungTermin.id == termin_id).first()
    if not termin:
        raise HTTPException(404, "Nicht gefunden")

    termin.datum = parse_date(datum)
    termin.uhrzeit = uhrzeit or None
    termin.ort = ort or None
    termin.bemerkung = bemerkung or None
    db.commit()
    return RedirectResponse(f"/belastung/jahr/{termin.datum.year}?msg=termin_updated", status_code=303)


@app.post("/belastung/termin/{termin_id}/delete")
def belastung_termin_delete(termin_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)

    termin = db.query(models.BelastungTermin).filter(models.BelastungTermin.id == termin_id).first()
    if not termin:
        raise HTTPException(404, "Nicht gefunden")

    year = termin.datum.year
    db.delete(termin)
    db.commit()
    return RedirectResponse(f"/belastung/jahr/{year}?msg=termin_deleted", status_code=303)


@app.get("/belastung/termin/{termin_id}", response_class=HTMLResponse)
def belastung_termin_detail(termin_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    termin = (
        db.query(models.BelastungTermin)
        .filter(models.BelastungTermin.id == termin_id)
        .first()
    )
    if not termin:
        raise HTTPException(404, "Nicht gefunden")

    sicher = [t for t in termin.teilnahmen if t.status == models.TeilnahmeStatus.sicher]
    rueckfrage = [t for t in termin.teilnahmen if t.status == models.TeilnahmeStatus.rueckfrage]
    assigned_ids = {t.member_id for t in termin.teilnahmen}
    available = [m for m in crud.members_active(db) if m.id not in assigned_ids]

    return templates.TemplateResponse(
        "belastung_detail.html",
        {
            "request": request,
            "user": user,
            "termin": termin,
            "sicher": sicher,
            "rueckfrage": rueckfrage,
            "available": available,
            "sicher_limit": SICHER_LIMIT,
            "rueckfrage_limit": RUECKFRAGE_LIMIT,
        },
    )


@app.post("/belastung/termin/{termin_id}/assign")
def belastung_termin_assign(
    termin_id: int,
    request: Request,
    member_id: int = Form(...),
    status: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)

    termin = db.query(models.BelastungTermin).filter(models.BelastungTermin.id == termin_id).first()
    if not termin:
        raise HTTPException(404, "Nicht gefunden")
    member = db.query(models.Member).filter(models.Member.id == member_id).first()
    if not member:
        raise HTTPException(404, "Nicht gefunden")

    status_enum = (
        models.TeilnahmeStatus.sicher if status == "sicher" else models.TeilnahmeStatus.rueckfrage
    )

    already = (
        db.query(models.BelastungTeilnahme)
        .filter(
            models.BelastungTeilnahme.termin_id == termin_id,
            models.BelastungTeilnahme.member_id == member_id,
        )
        .first()
    )
    if already:
        return RedirectResponse(f"/belastung/termin/{termin_id}?msg=teilnahme_exists", status_code=303)

    limit = SICHER_LIMIT if status_enum == models.TeilnahmeStatus.sicher else RUECKFRAGE_LIMIT
    current_count = (
        db.query(models.BelastungTeilnahme)
        .filter(
            models.BelastungTeilnahme.termin_id == termin_id,
            models.BelastungTeilnahme.status == status_enum,
        )
        .count()
    )
    if current_count >= limit:
        return RedirectResponse(f"/belastung/termin/{termin_id}?msg=teilnahme_full", status_code=303)

    db.add(
        models.BelastungTeilnahme(termin_id=termin_id, member_id=member_id, status=status_enum)
    )
    member.nextbelastung = termin.datum
    db.commit()

    if member.email:
        settings = crud.get_settings(db)
        subject = settings.belastung_assign_subject
        try:
            body = settings.belastung_assign_body.format(
                vorname=member.vorname,
                name=member.name,
                datum=termin.datum.strftime("%d.%m.%Y"),
                uhrzeit=termin.uhrzeit or "-",
                ort=termin.ort or "-",
                bemerkung=termin.bemerkung or "-",
                status="Sicher" if status_enum == models.TeilnahmeStatus.sicher else "Auf Rückfrage",
            )
        except Exception:
            body = settings.belastung_assign_body
        emailer.send_mail(member.email, subject, body)

    return RedirectResponse(f"/belastung/termin/{termin_id}?msg=teilnahme_added", status_code=303)


@app.post("/belastung/termin/{termin_id}/unassign/{member_id}")
def belastung_termin_unassign(
    termin_id: int, member_id: int, request: Request, db: Session = Depends(get_db)
):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)

    teilnahme = (
        db.query(models.BelastungTeilnahme)
        .filter(
            models.BelastungTeilnahme.termin_id == termin_id,
            models.BelastungTeilnahme.member_id == member_id,
        )
        .first()
    )
    if teilnahme:
        db.delete(teilnahme)
        db.commit()
    return RedirectResponse(f"/belastung/termin/{termin_id}?msg=teilnahme_removed", status_code=303)


@app.get("/belastung/pdf")
def belastung_pdf_current_year(request: Request, db: Session = Depends(get_db)):
    return _belastung_pdf(request, db, date.today().year)


@app.get("/belastung/jahr/{year}/pdf")
def belastung_pdf_year(year: int, request: Request, db: Session = Depends(get_db)):
    return _belastung_pdf(request, db, year)


def _belastung_pdf(request: Request, db: Session, year: int):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    termine = crud.belastung_termine_for_year(db, year)
    pdf_bytes = exports.build_belastung_pdf(year, termine)
    filename = f"belastungsuebung_{year}.pdf"
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ----------------------------------------------------------- Settings ----

@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)

    settings = crud.get_settings(db)
    users = db.query(models.User).order_by(models.User.username).all()
    backups = backup.list_backups()

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "user": user,
            "settings": settings,
            "users": users,
            "backups": backups,
            "weekdays": crud.WEEKDAYS,
        },
    )


@app.post("/settings/schedule")
def settings_schedule(
    request: Request,
    tauglichkeit_check_time: str = Form(...),
    email_send_time: str = Form(...),
    weekly_report_day: str = Form(...),
    weekly_report_time: str = Form(...),
    backup_time: str = Form(...),
    backup_retention: int = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)

    settings = crud.get_settings(db)
    settings.tauglichkeit_check_time = tauglichkeit_check_time
    settings.email_send_time = email_send_time
    settings.weekly_report_day = weekly_report_day
    settings.weekly_report_time = weekly_report_time
    settings.backup_time = backup_time
    settings.backup_retention = max(1, backup_retention)
    db.commit()

    reschedule(app.state.scheduler)
    return RedirectResponse("/settings?msg=schedule_ok#zeitplan", status_code=303)


@app.post("/settings/email-texts")
def settings_email_texts(
    request: Request,
    admin_email: str = Form(""),
    g26_reminder_subject: str = Form(...),
    g26_reminder_body: str = Form(...),
    g26_reminder_bcc: str = Form(""),
    belastung_assign_subject: str = Form(...),
    belastung_assign_body: str = Form(...),
    belastung_reminder_subject: str = Form(...),
    belastung_reminder_body: str = Form(...),
    weekly_report_subject: str = Form(...),
    weekly_report_intro: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)

    settings = crud.get_settings(db)
    settings.admin_email = admin_email or None
    settings.g26_reminder_subject = g26_reminder_subject
    settings.g26_reminder_body = g26_reminder_body
    settings.g26_reminder_bcc = g26_reminder_bcc or None
    settings.belastung_assign_subject = belastung_assign_subject
    settings.belastung_assign_body = belastung_assign_body
    settings.belastung_reminder_subject = belastung_reminder_subject
    settings.belastung_reminder_body = belastung_reminder_body
    settings.weekly_report_subject = weekly_report_subject
    settings.weekly_report_intro = weekly_report_intro
    db.commit()

    return RedirectResponse("/settings?msg=email_ok#email", status_code=303)


@app.post("/settings/send-weekly-report-now")
def settings_send_weekly_report_now(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)
    run_weekly_report()
    return RedirectResponse("/settings?msg=weekly_ok#email", status_code=303)


# ------------------------------------------------------ Benutzerverwaltung

@app.post("/settings/users/new")
def settings_user_new(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)

    if db.query(models.User).filter(models.User.username == username).first():
        return RedirectResponse("/settings?msg=user_exists#benutzer", status_code=303)

    role_enum = models.Role.admin if role == "admin" else models.Role.viewer
    new_user = models.User(
        username=username,
        password_hash=auth.hash_password(password),
        role=role_enum,
    )
    db.add(new_user)
    db.commit()
    return RedirectResponse("/settings?msg=user_created#benutzer", status_code=303)


@app.post("/settings/users/{user_id}/role")
def settings_user_role(
    user_id: int,
    request: Request,
    role: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)

    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(404, "Nicht gefunden")
    if target.id == user.id:
        return RedirectResponse("/settings?msg=user_role_self#benutzer", status_code=303)

    role_enum = models.Role.admin if role == "admin" else models.Role.viewer
    if target.role == models.Role.admin and role_enum == models.Role.viewer:
        remaining_admins = (
            db.query(models.User)
            .filter(models.User.role == models.Role.admin, models.User.id != target.id)
            .count()
        )
        if remaining_admins == 0:
            return RedirectResponse("/settings?msg=user_last_admin#benutzer", status_code=303)

    target.role = role_enum
    db.commit()
    return RedirectResponse("/settings?msg=user_role_updated#benutzer", status_code=303)


@app.post("/settings/users/{user_id}/delete")
def settings_user_delete(user_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)

    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(404, "Nicht gefunden")
    if target.id == user.id:
        return RedirectResponse("/settings?msg=user_self#benutzer", status_code=303)

    remaining_admins = (
        db.query(models.User)
        .filter(models.User.role == models.Role.admin, models.User.id != target.id)
        .count()
    )
    if target.role == models.Role.admin and remaining_admins == 0:
        return RedirectResponse("/settings?msg=user_last_admin#benutzer", status_code=303)

    db.delete(target)
    db.commit()
    return RedirectResponse("/settings?msg=user_deleted#benutzer", status_code=303)


@app.post("/settings/users/{user_id}/2fa/disable")
def settings_user_2fa_disable(user_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)

    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(404, "Nicht gefunden")

    target.totp_secret = None
    target.totp_enabled = False
    db.commit()
    return RedirectResponse("/settings?msg=totp_disabled#benutzer", status_code=303)


# ------------------------------------------------------------- Backups ----

@app.post("/settings/backups/run")
def settings_backup_run(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)

    settings = crud.get_settings(db)
    try:
        backup.run_backup(retention=settings.backup_retention)
        return RedirectResponse("/settings?msg=backup_ok#backups", status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/settings?msg=backup_error#backups", status_code=303)


@app.get("/settings/backups/{filename}/download")
def settings_backup_download(filename: str, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)

    try:
        path = backup.backup_path(filename)
    except FileNotFoundError:
        raise HTTPException(404, "Backup nicht gefunden")
    return FileResponse(path, filename=filename, media_type="application/gzip")


@app.post("/settings/backups/{filename}/restore")
def settings_backup_restore(
    filename: str,
    request: Request,
    confirm: str = Form(""),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)

    if confirm != "JA":
        return RedirectResponse("/settings?msg=restore_not_confirmed#backups", status_code=303)

    try:
        backup.restore_backup(filename)
        return RedirectResponse("/settings?msg=restore_ok#backups", status_code=303)
    except Exception:
        return RedirectResponse("/settings?msg=restore_error#backups", status_code=303)


@app.post("/settings/backups/{filename}/delete")
def settings_backup_delete(filename: str, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_admin(user)

    backup.delete_backup(filename)
    return RedirectResponse("/settings?msg=backup_deleted#backups", status_code=303)
