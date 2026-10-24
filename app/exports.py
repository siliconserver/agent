import csv
import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

CSV_COLUMNS = [
    ("name", "Name"),
    ("vorname", "Vorname"),
    ("email", "E-Mail"),
    ("agtlehrgang", "AGT Lehrgang"),
    ("csalehrgang", "CSA Lehrgang"),
    ("lastbelastung", "Letzte Belastungsübung"),
    ("nextbelastung", "Nächste Belastungsübung"),
    ("g26_ausstellung", "G26 Ausstellung"),
    ("g26_ablauf", "G26 Ablauf"),
    ("lasteinsatz_agt", "Letzter AGT Einsatz"),
    ("lasteinsatz_csa", "Letzter CSA Einsatz"),
    ("uvv_unterweisung", "UVV Unterweisung"),
    ("patauglich", "PA tauglich"),
    ("csatauglich", "CSA tauglich"),
    ("agtaktiv", "AGT aktiv"),
    ("kommentar", "Kommentar"),
]


def _fmt(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Ja" if value else "Nein"
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    return str(value)


def members_to_csv(members) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow([label for _, label in CSV_COLUMNS])
    for m in members:
        writer.writerow([_fmt(getattr(m, field)) for field, _ in CSV_COLUMNS])
    return buf.getvalue()


def _member_rows(members, date_field, date_label):
    rows = [["Name", "Vorname", date_label]]
    for m in members:
        rows.append([m.name, m.vorname, _fmt(getattr(m, date_field))])
    return rows


def _member_rows_status(members, status_label):
    rows = [["Name", "Vorname", "Status"]]
    for m in members:
        rows.append([m.name, m.vorname, status_label])
    return rows


def _styled_table(rows, col_widths=None):
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2b2f38")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f4f4")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return t


def build_reports_pdf(
    stats, expiring, expired, missing, tauglich, untauglich, missing_uvv=None
) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title="Atemschutz-Bericht",
    )
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("Atemschutz-Bericht", styles["Title"]))
    story.append(
        Paragraph(f"Stand: {date.today().strftime('%d.%m.%Y')}", styles["Normal"])
    )
    story.append(Spacer(1, 14))

    stats_rows = [
        ["Kennzahl", "Anzahl", "Anteil"],
        ["AGT insgesamt", str(stats["total"]), "-"],
        ["AGT aktiv", str(stats["active"]), f"{stats['active_pct']}%"],
        ["davon tauglich", str(stats["tauglich"]), f"{stats['tauglich_pct']}%"],
        ["davon untauglich", str(stats["untauglich"]), f"{stats['untauglich_pct']}%"],
    ]
    story.append(Paragraph("Übersicht", styles["Heading2"]))
    story.append(_styled_table(stats_rows, col_widths=[7 * cm, 4 * cm, 4 * cm]))
    story.append(Spacer(1, 18))

    story.append(
        Paragraph(f"G26 läuft in den nächsten 3 Monaten ab ({len(expiring)})", styles["Heading2"])
    )
    if expiring:
        story.append(_styled_table(_member_rows(expiring, "g26_ablauf", "G26 Ablauf"), col_widths=[6 * cm, 6 * cm, 4 * cm]))
    else:
        story.append(Paragraph("Keine.", styles["Normal"]))
    story.append(Spacer(1, 18))

    story.append(Paragraph(f"G26 bereits abgelaufen ({len(expired)})", styles["Heading2"]))
    if expired:
        story.append(_styled_table(_member_rows(expired, "g26_ablauf", "G26 Ablauf"), col_widths=[6 * cm, 6 * cm, 4 * cm]))
    else:
        story.append(Paragraph("Keine.", styles["Normal"]))
    story.append(Spacer(1, 18))

    story.append(
        Paragraph(f"Keine Belastungsübung dieses/letztes Jahr ({len(missing)})", styles["Heading2"])
    )
    if missing:
        story.append(_styled_table(_member_rows(missing, "lastbelastung", "Letzte Belastung"), col_widths=[6 * cm, 6 * cm, 4 * cm]))
    else:
        story.append(Paragraph("Keine.", styles["Normal"]))
    story.append(Spacer(1, 18))

    missing_uvv = missing_uvv or []
    story.append(
        Paragraph(f"Keine UVV-Unterweisung dieses/letztes Jahr ({len(missing_uvv)})", styles["Heading2"])
    )
    if missing_uvv:
        story.append(_styled_table(_member_rows(missing_uvv, "uvv_unterweisung", "Letzte UVV"), col_widths=[6 * cm, 6 * cm, 4 * cm]))
    else:
        story.append(Paragraph("Keine.", styles["Normal"]))
    story.append(Spacer(1, 18))

    story.append(Paragraph(f"AGT tauglich ({len(tauglich)})", styles["Heading2"]))
    if tauglich:
        story.append(_styled_table(_member_rows_status(tauglich, "Tauglich"), col_widths=[6 * cm, 6 * cm, 4 * cm]))
    else:
        story.append(Paragraph("Keine.", styles["Normal"]))
    story.append(Spacer(1, 18))

    story.append(Paragraph(f"AGT untauglich ({len(untauglich)})", styles["Heading2"]))
    if untauglich:
        story.append(_styled_table(_member_rows_status(untauglich, "Untauglich"), col_widths=[6 * cm, 6 * cm, 4 * cm]))
    else:
        story.append(Paragraph("Keine.", styles["Normal"]))

    doc.build(story)
    return buf.getvalue()


def build_belastung_pdf(year, termine) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title=f"Belastungsübung {year}",
    )
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(f"Belastungsübung {year}", styles["Title"]))
    story.append(
        Paragraph(f"Stand: {date.today().strftime('%d.%m.%Y')}", styles["Normal"])
    )
    story.append(Spacer(1, 14))

    if not termine:
        story.append(Paragraph(f"Keine Termine in {year}.", styles["Normal"]))
    else:
        for termin in termine:
            heading = termin.datum.strftime("%d.%m.%Y")
            if termin.uhrzeit:
                heading += f", {termin.uhrzeit} Uhr"
            if termin.ort:
                heading += f" – {termin.ort}"
            story.append(Paragraph(heading, styles["Heading2"]))

            sicher = [t for t in termin.teilnahmen if t.status == "sicher"]
            rueckfrage = [t for t in termin.teilnahmen if t.status == "rueckfrage"]
            rows = [["Name", "Vorname", "Status"]]
            for t in sicher:
                rows.append([t.member.name, t.member.vorname, "Sicher"])
            for t in rueckfrage:
                rows.append([t.member.name, t.member.vorname, "Auf Rückfrage"])

            if len(rows) > 1:
                story.append(_styled_table(rows, col_widths=[6 * cm, 6 * cm, 4 * cm]))
            else:
                story.append(Paragraph("Keine Zuweisungen.", styles["Normal"]))
            story.append(Spacer(1, 18))

    doc.build(story)
    return buf.getvalue()
