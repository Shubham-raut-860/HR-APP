"""
RenderCV service — converts structured resume JSON into a high-quality PDF
using rendercv (https://rendercv.com).
"""
from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def _sanitize_latex(val: str) -> str:
    """Escape LaTeX control characters to prevent injection."""
    if not isinstance(val, str):
        return val
    # Single-pass replacements to avoid double escaping (e.g. escaping the \ in \textbackslash{})
    mapping = {
        '\\': r'\textbackslash{}',
        '{': r'\{',
        '}': r'\}',
        '$': r'\$',
        '&': r'\&',
        '%': r'\%',
        '#': r'\#',
        '_': r'\_',
        '^': r'\textasciicircum{}',
        '~': r'\textasciitilde{}',
    }
    return "".join(mapping.get(c, c) for c in val)

def _sanitize_dict_recursive(data):
    if isinstance(data, dict):
        return {k: _sanitize_dict_recursive(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_sanitize_dict_recursive(item) for item in data]
    elif isinstance(data, str):
        return _sanitize_latex(data)
    return data

def _resume_json_to_rendercv_yaml(resume: dict, theme: str = "classic") -> dict:
    """
    Map our internal resume JSON schema (output of build_resume_from_form)
    to the rendercv YAML/JSON schema.

    RenderCV schema reference:
    https://docs.rendercv.com/user_guide/structure/
    """
    resume = _sanitize_dict_recursive(resume)
    contact = resume.get("contact") or {}
    cv: dict = {
        "name": contact.get("name") or "Candidate",
    }
    if contact.get("location"):
        cv["location"] = contact["location"]
    if contact.get("email"):
        cv["email"] = contact["email"]
    if contact.get("phone"):
        cv["phone"] = contact["phone"]

    # Add optional links
    linkedin = contact.get("linkedin") or ""
    github = contact.get("github") or ""
    website = contact.get("website") or ""
    profiles = []
    if linkedin:
        profiles.append({"network": "LinkedIn", "username": linkedin, "url": linkedin if linkedin.startswith(
            "http") else f"https://linkedin.com/in/{linkedin}"})
    if github:
        profiles.append({"network": "GitHub", "username": github, "url": github if github.startswith(
            "http") else f"https://github.com/{github}"})
    if website:
        profiles.append({"network": "Website", "username": website, "url": website})
    if profiles:
        cv["social_networks"] = profiles

    sections: dict[str, list] = {}

    summary = resume.get("summary") or ""
    if summary:
        sections["summary"] = [summary]

    # Skills
    skills_raw = resume.get("skills") or {}
    skill_entries: list[dict] = []
    if isinstance(skills_raw, dict):
        for category, items in skills_raw.items():
            if items and isinstance(items, list):
                skill_entries.append({
                    "label": category.replace("_", " ").title(),
                    "details": ", ".join(str(s) for s in items),
                })
    elif isinstance(skills_raw, list):
        skill_entries.append({"label": "Technical Skills",
                             "details": ", ".join(str(s) for s in skills_raw)})
    if skill_entries:
        sections["skills"] = [{"type": "OneLineEntry", **e} for e in skill_entries]

    # Work Experience
    work_exp = resume.get("work_experience") or []
    if work_exp:
        entries = []
        for job in work_exp:
            bullets = job.get("bullets") or job.get("achievements") or []
            entry: dict = {
                "type": "ExperienceEntry",
                "company": job.get("company") or "",
                "position": job.get("role") or job.get("position") or "",
                "start_date": job.get("start_date") or "",
                "end_date": job.get("end_date") or "present",
                "highlights": [str(b) for b in bullets] if bullets else [],
            }
            if job.get("location"):
                entry["location"] = job["location"]
            entries.append(entry)
        if entries:
            sections["experience"] = entries

    # Education
    education = resume.get("education") or []
    if education:
        edu_entries = []
        for edu in education:
            e: dict = {
                "type": "EducationEntry",
                "institution": edu.get("institution") or edu.get("institute") or "",
                "area": edu.get("degree") or edu.get("area") or "",
                "date": edu.get("year") or edu.get("date") or "",
            }
            gpa = edu.get("gpa")
            if gpa:
                e["gpa"] = str(gpa)
            highlights = edu.get("highlights") or []
            if highlights:
                e["highlights"] = [str(h) for h in highlights]
            edu_entries.append(e)
        if edu_entries:
            sections["education"] = edu_entries

    # Projects
    projects = resume.get("projects") or []
    if projects:
        proj_entries = []
        for proj in projects:
            tech = proj.get("technologies") or proj.get("tech") or []
            highlights = [proj.get("description") or ""]
            if tech:
                highlights.append(f"Tech Stack: {', '.join(str(t) for t in tech)}")
            link = proj.get("link") or proj.get("url") or ""
            p: dict = {
                "type": "NormalEntry",
                "name": proj.get("title") or proj.get("name") or "",
                "highlights": [h for h in highlights if h],
            }
            if link:
                p["url"] = link
            proj_entries.append(p)
        if proj_entries:
            sections["projects"] = proj_entries

    # Certifications
    certs = resume.get("certifications") or []
    if certs:
        cert_entries = []
        for cert in certs:
            if isinstance(cert, str):
                cert_entries.append(
                    {"type": "OneLineEntry", "label": "Certification", "details": cert})
            elif isinstance(cert, dict):
                cert_entries.append({
                    "type": "OneLineEntry",
                    "label": cert.get("name") or cert.get("title") or "Certification",
                    "details": cert.get("issuer") or cert.get("date") or "",
                })
        if cert_entries:
            sections["certifications"] = cert_entries

    cv["sections"] = sections

    return {
        "cv": cv,
        "design": {
            "theme": theme,
        },
    }


async def generate_pdf_from_resume(resume: dict, theme: str = "classic") -> bytes:
    """
    Take our structured resume dict, convert it to RenderCV format, run
    rendercv render in a temp directory, and return the PDF bytes.

    Returns the raw PDF bytes on success.
    Raises RuntimeError on failure.
    """
    rendercv_data = _resume_json_to_rendercv_yaml(resume, theme=theme)

    def _run_rendercv() -> bytes:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "resume.json"
            input_path.write_text(json.dumps(rendercv_data, ensure_ascii=False), encoding="utf-8")

            import subprocess
            import sys
            import os
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"

            try:
                result = subprocess.run(
                    [sys.executable, "-m", "rendercv", "render", str(input_path)],
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    env=env,
                    timeout=120,  # 2 minutes — first run downloads TinyTeX
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("PDF generation timed out (>120s). Please try again.") from exc

            if result.returncode != 0:
                logger.error("[RenderCV] render failed:\nSTDOUT: %s\nSTDERR: %s",
                             result.stdout, result.stderr)
                raise RuntimeError(
                    f"RenderCV render failed: {result.stderr[-500:] or result.stdout[-500:]}")

            logger.info("[RenderCV] render succeeded:\n%s", result.stdout[:500])

            # Find the generated PDF
            output_dir = Path(tmpdir) / "rendercv_output"
            pdf_files = list(output_dir.glob("*.pdf"))
            if not pdf_files:
                # Sometimes the output goes to the cwd
                pdf_files = list(Path(tmpdir).glob("*.pdf"))
            if not pdf_files:
                raise RuntimeError("RenderCV succeeded but no PDF file was generated.")

            return pdf_files[0].read_bytes()

    # Run the blocking subprocess in a thread pool
    try:
        pdf_bytes = await asyncio.to_thread(_run_rendercv)
        return pdf_bytes
    except RuntimeError:
        raise
    except Exception as exc:
        logger.error("[RenderCV] generate_pdf_from_resume failed: %s", exc)
        raise
