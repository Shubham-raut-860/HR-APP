"""
Export service – PDF and Excel report generation
"""
from __future__ import annotations
import io
from datetime import datetime, timezone
from typing import Any
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable
)


# ─── Excel ────────────────────────────────────────────────────────────────────

def generate_excel_report(candidates: list[dict], job_title: str) -> bytes:
    rows = []
    for c in candidates:
        rows.append({
            "Rank": c.get("rank", ""),
            "Name": c.get("name", ""),
            "Email": c.get("email", ""),
            "Tag": c.get("tag", ""),
            "Skills": ", ".join(c.get("normalized_skills", [])),
            "Experience (yrs)": c.get("experience_years", 0),
            "Skill Match %": c.get("skill_match_pct", 0),
            "Experience Match %": c.get("experience_match_pct", 0),
            "Resume Score": c.get("resume_score", 0),
            "Quiz Score": c.get("quiz_score", ""),
            "Final Score": c.get("final_score", ""),
            "Pass/Fail": "Pass" if c.get("passed") else ("Fail" if c.get("passed") is False else ""),
        })

    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Candidates")
        ws = writer.sheets["Candidates"]
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 50)
    buf.seek(0)
    return buf.read()


# ─── PDF ──────────────────────────────────────────────────────────────────────

def generate_pdf_report(
    candidates: list[dict],
    job_title: str,
    analytics: dict[str, Any],
) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        rightMargin=1.5 * cm, leftMargin=1.5 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Title"], fontSize=18, spaceAfter=12)
    h2_style = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=13, spaceAfter=6)
    normal = styles["Normal"]

    story = []

    story.append(Paragraph(f"HR Analytics Report – {job_title}", title_style))
    story.append(Paragraph(
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        normal,
    ))
    story.append(Spacer(1, 0.4 * cm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.grey))
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("Summary", h2_style))
    summary_data = [
        ["Metric", "Value"],
        ["Total Applicants", analytics.get("total_applicants", 0)],
        ["Shortlisted", analytics.get("shortlisted_count", 0)],
        ["Shortlisted %", f"{analytics.get('shortlisted_pct', 0):.1f}%"],
        ["Strong", analytics.get("strong_count", 0)],
        ["Medium", analytics.get("medium_count", 0)],
        ["Rejected", analytics.get("reject_count", 0)],
        ["Avg Resume Score", f"{analytics.get('avg_resume_score', 0):.1f}"],
        ["Avg Quiz Score", f"{analytics.get('avg_quiz_score', 0) or 'N/A'}"],
        ["Passed", analytics.get("pass_count", 0)],
    ]
    t = Table(summary_data, colWidths=[5 * cm, 4 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a73e8")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f4ff")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.6 * cm))

    story.append(Paragraph("Candidate Rankings", h2_style))
    # FIX (Bug #4 - MEDIUM): was `candidates[:50]` — silently dropped everyone
    # ranked 51+.  ReportLab's `repeatRows=1` already handles multi-page tables,
    # so there's no layout reason to cap the rows.  We now include all candidates.
    headers = ["Rank", "Name", "Email", "Tag", "Resume %", "Quiz Score", "Final %", "Pass?"]
    rows = [headers]
    for c in candidates:
        r_score = float(c.get('resume_score') or 0)
        f_score = c.get('final_score')
        f_score_str = f"{float(f_score):.1f}" if f_score not in (None, "") else ""
        
        rows.append([
            str(c.get("rank", "")),
            c.get("name") or "",
            c.get("email") or "",
            c.get("tag") or "",
            f"{r_score:.1f}",
            f"{c.get('quiz_score', '')}" if c.get("quiz_score") is not None else "",
            f_score_str,
            "✓" if c.get("passed") else ("✗" if c.get("passed") is False else ""),
        ])

    col_widths = [1.5 * cm, 4 * cm, 5.5 * cm, 2 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm, 2 * cm]
    ct = Table(rows, colWidths=col_widths, repeatRows=1)
    ct.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a73e8")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f4ff")]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("PADDING", (0, 0), (-1, -1), 5),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ALIGN", (1, 1), (2, -1), "LEFT"),
    ]))
    story.append(ct)

    doc.build(story)
    buf.seek(0)
    return buf.read()
