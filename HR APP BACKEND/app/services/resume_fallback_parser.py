from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.constants.scoring import MAX_RESUME_EXPERIENCE_YEARS


_EMAIL_RE = re.compile(r"([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[A-Za-z]{2,})")
_PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{8,}\d)")
_EXP_RE = re.compile(r"(\d{1,2}(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)", re.IGNORECASE)
_EXP_CAREER_RE = re.compile(r"\b(\d{1,2}(?:\.\d+)?)\s*-\s*year(?:s)?\s+career\b", re.IGNORECASE)
_EXP_SINCE_RE = re.compile(r"\bsince\s+((?:19|20)\d{2})\b", re.IGNORECASE)
_DATE_RANGE_RE = re.compile(
    r"(?P<start>(?:[A-Za-z]{3,9}\s+\d{4})|(?:\d{1,2}/\d{4})|(?:\d{4}))\s*"
    r"(?:-|to|–|—)\s*"
    r"(?P<end>(?:present|current|till date|ongoing)|(?:[A-Za-z]{3,9}\s+\d{4})|(?:\d{1,2}/\d{4})|(?:\d{4}))",
    re.IGNORECASE,
)
_GAP_LINE_RE = re.compile(
    r"\b(career break|employment gap|sabbatical|maternity break|paternity break|gap year|unemployed)\b",
    re.IGNORECASE,
)

_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "work_experience": (
        "work experience",
        "professional experience",
        "employment history",
        "experience",
    ),
    "projects": (
        "projects",
        "project experience",
        "key projects",
        "personal projects",
    ),
    "education": (
        "education",
        "academic background",
        "qualifications",
        "academics",
    ),
}

_STOP_SECTION_HEADINGS = {
    "skills",
    "technical skills",
    "core skills",
    "certifications",
    "achievements",
    "awards",
    "languages",
    "interests",
    "summary",
    "profile",
    "objective",
    "strengths",
}

_COMMON_SKILLS = [
    "python", "java", "javascript", "typescript", "react", "angular", "vue",
    "node", "node.js", "fastapi", "django", "flask", "spring", "dotnet",
    ".net", "asp.net", "asp.net core", "c#", "sql", "sql server",
    "postgresql", "mysql", "mongodb", "redis", "azure", "aws", "gcp",
    "docker", "kubernetes", "git", "rest api", "web api", "microservices",
    "tensorflow", "pytorch", "pandas", "numpy",
]

_EDU_HINTS = (
    "bachelor", "master", "b.e", "b.tech", "m.tech", "m.e", "phd",
    "diploma", "university", "college", "institute",
)

_ROLE_KEYWORDS = (
    "engineer", "developer", "analyst", "manager", "architect", "consultant",
    "lead", "intern", "specialist", "administrator", "director", "officer",
)

_DESCRIPTION_START_RE = re.compile(
    r"^(developed|designed|implemented|ensured|worked|responsible|collaborated|built|created|led|maintained|optimized|technologies used)\b",
    re.IGNORECASE,
)

_PROJECT_HINTS = (
    "project", "platform", "system", "application", "app", "portal",
    "dashboard", "engine", "tool", "service",
)

_COMPANY_NAME_HINTS = (
    "labs", "technologies", "technology", "solutions", "systems",
    "software", "consulting", "private", "pvt", "ltd", "llp", "inc",
)


def _clean_line(line: str) -> str:
    cleaned = re.sub(r"\s+", " ", (line or "").strip())
    cleaned = cleaned.lstrip("-*•")
    return cleaned.strip()


def _normalize_skill_token(skill: str) -> str:
    return re.sub(r"\s+", " ", (skill or "").strip().lower())


def _parse_date_token(token: str) -> datetime | None:
    value = (token or "").strip().lower()
    if not value:
        return None
    if value in {"present", "current", "till date", "ongoing"}:
        return datetime.utcnow()

    for fmt in ("%b %Y", "%B %Y", "%m/%Y", "%Y"):
        try:
            return datetime.strptime(value.title() if " " in value else value, fmt)
        except ValueError:
            continue
    return None


def _extract_date_ranges(lines: list[str]) -> list[tuple[datetime, datetime, str, str]]:
    ranges: list[tuple[datetime, datetime, str, str]] = []
    for line in lines:
        for match in _DATE_RANGE_RE.finditer(line):
            start_raw = match.group("start")
            end_raw = match.group("end")
            start_dt = _parse_date_token(start_raw)
            end_dt = _parse_date_token(end_raw)
            if start_dt is None or end_dt is None:
                continue
            if end_dt < start_dt:
                start_dt, end_dt = end_dt, start_dt
                start_raw, end_raw = end_raw, start_raw
            ranges.append((start_dt, end_dt, start_raw, end_raw))
    ranges.sort(key=lambda item: item[0])
    return ranges


def _match_section_heading(line: str) -> str | None:
    if not line:
        return None
    if any(ch.isdigit() for ch in line):
        return None
    if len(line) > 48:
        return None

    normalized = re.sub(r"[^a-z ]+", "", line.lower()).strip()
    if not normalized:
        return None

    for key, aliases in _SECTION_ALIASES.items():
        if normalized in aliases:
            return key
    return None


def _extract_sections(raw_lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {
        "work_experience": [],
        "projects": [],
        "education": [],
    }
    current: str | None = None
    for raw in raw_lines:
        line = _clean_line(raw)
        if not line:
            continue
        normalized = re.sub(r"[^a-z ]+", "", line.lower().rstrip(":")).strip()
        if normalized in _STOP_SECTION_HEADINGS:
            current = None
            continue
        heading = _match_section_heading(line.rstrip(":"))
        if heading:
            current = heading
            continue
        if current and len(sections[current]) < 80:
            sections[current].append(line)
    return sections


def _extract_skills_from_text(text: str, lexicon: list[str]) -> list[str]:
    lowered = (text or "").lower()
    found: list[str] = []
    for skill in lexicon:
        token = re.escape(skill)
        if re.search(rf"(?<![a-z0-9]){token}(?![a-z0-9])", lowered):
            found.append(skill)
    deduped: list[str] = []
    seen: set[str] = set()
    for skill in found:
        norm = _normalize_skill_token(skill)
        if norm in seen:
            continue
        seen.add(norm)
        deduped.append(skill)
    return deduped


def _word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", (text or "").strip()) if w])


def _strip_date_range(text: str) -> str:
    return _DATE_RANGE_RE.sub("", text or "").strip(" -|:,")


def _looks_like_description_line(line: str) -> bool:
    candidate = (line or "").strip()
    if not candidate:
        return False
    if candidate.endswith(".") and _word_count(candidate) >= 8:
        return True
    if _DESCRIPTION_START_RE.search(candidate):
        return True
    return False


def _looks_like_role_title(text: str) -> bool:
    candidate = (text or "").strip()
    if not candidate:
        return False
    wc = _word_count(candidate)
    low = candidate.lower()
    if _looks_like_description_line(candidate) and wc > 4:
        return False
    if wc > 12:
        return False
    if any(k in low for k in _ROLE_KEYWORDS):
        return True
    return wc <= 6 and not candidate.endswith(".")


def _looks_like_role_anchor(line: str) -> bool:
    candidate = (line or "").strip()
    if not candidate:
        return False
    wc = _word_count(candidate)
    low = candidate.lower()
    if _looks_like_description_line(candidate):
        return False
    if " at " in low:
        return True
    if any(k in low for k in _ROLE_KEYWORDS) and wc <= 10:
        return True
    if wc <= 6 and not candidate.endswith("."):
        return True
    return False


def _split_role_company(anchor: str) -> tuple[str, str]:
    text = (anchor or "").strip(" -|:,")
    if not text:
        return "", ""

    if re.search(r"\s+at\s+", text, flags=re.IGNORECASE):
        parts = re.split(r"\s+at\s+", text, maxsplit=1, flags=re.IGNORECASE)
        role = _clean_line(parts[0]) if parts else ""
        company = _clean_line(parts[1]) if len(parts) > 1 else ""
        return role, company

    if " - " in text:
        left, right = text.split(" - ", 1)
        left_c = _clean_line(left)
        right_c = _clean_line(right)
        if any(k in left_c.lower() for k in _ROLE_KEYWORDS):
            return left_c, right_c
        if any(k in right_c.lower() for k in _ROLE_KEYWORDS):
            return right_c, left_c
        return left_c, right_c

    return _clean_line(text), ""


def _looks_like_project_anchor(line: str) -> bool:
    candidate = (line or "").strip()
    if not candidate:
        return False
    if candidate[0].islower():
        return False
    low = candidate.lower()
    if _looks_like_description_line(candidate):
        return False
    if _word_count(candidate) > 10:
        return False
    if candidate.endswith("."):
        return False
    if any(h in low for h in _PROJECT_HINTS):
        return True
    return _word_count(candidate) <= 7 and len(candidate) <= 90


def _clean_project_title(line: str) -> str:
    title = _clean_line(line)
    title = re.sub(r"^(project\s*[:\-]\s*)", "", title, flags=re.IGNORECASE)
    return title[:120]


def _looks_like_company_name(text: str) -> bool:
    candidate = (text or "").strip().lower()
    if not candidate:
        return False
    if any(h in candidate for h in _COMPANY_NAME_HINTS):
        return True
    if _word_count(candidate) <= 4 and not any(k in candidate for k in _ROLE_KEYWORDS):
        return True
    return False


def _build_work_experience(section_lines: list[str], lexicon: list[str]) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for line in section_lines:
        if len(anchors) >= 12:
            break
        clean = _clean_line(line)
        if len(clean) < 4:
            continue
        if _match_section_heading(clean):
            continue

        match = _DATE_RANGE_RE.search(clean)
        anchor_text = _strip_date_range(clean)
        is_anchor = bool(match) or _looks_like_role_anchor(anchor_text)

        if is_anchor:
            if match and not anchor_text and current:
                start_raw = match.group("start")
                end_raw = match.group("end")
                start_dt = _parse_date_token(start_raw or "")
                end_dt = _parse_date_token(end_raw or "")
                duration_years: float | None = None
                if start_dt and end_dt and end_dt >= start_dt:
                    months = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month)
                    if months > 0:
                        duration_years = round(months / 12.0, 2)
                current["start_date"] = start_raw
                current["end_date"] = end_raw
                current["duration_years"] = duration_years
                continue

            if current:
                anchors.append(current)

            role, company = _split_role_company(anchor_text)
            if not role and company:
                role = company
                company = ""
            if not role:
                current = None
                continue
            role = role[:120]
            company = company[:120]
            if _looks_like_description_line(role) and not match:
                current = None
                continue
            if _word_count(role) > 10 and not match:
                current = None
                continue
            if not _looks_like_role_title(role):
                current = None
                continue
            if role.lower() == company.lower():
                company = ""
            if role and company and role.lower() in company.lower():
                role = role.replace(company, "").strip(" -|:,")

            skills = _extract_skills_from_text(clean, lexicon)[:10]
            start_raw = match.group("start") if match else None
            end_raw = match.group("end") if match else None
            start_dt = _parse_date_token(start_raw or "")
            end_dt = _parse_date_token(end_raw or "")
            duration_years: float | None = None
            if start_dt and end_dt and end_dt >= start_dt:
                months = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month)
                if months > 0:
                    duration_years = round(months / 12.0, 2)

            current = {
                "company": company,
                "role": role,
                "start_date": start_raw,
                "end_date": end_raw,
                "duration_years": duration_years,
                "skills": skills,
                "_detail_lines": [],
            }
            continue

        if current is None:
            continue
        if _looks_like_role_anchor(clean):
            continue
        if len(clean) <= 220 and len(current["_detail_lines"]) < 4:
            current["_detail_lines"].append(clean)
            for skill in _extract_skills_from_text(clean, lexicon):
                if skill not in current["skills"]:
                    current["skills"].append(skill)

    if current:
        anchors.append(current)

    items: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for entry in anchors:
        role = _clean_line(str(entry.get("role") or ""))
        company = _clean_line(str(entry.get("company") or ""))
        start_raw = entry.get("start_date")
        end_raw = entry.get("end_date")
        duration_years = entry.get("duration_years")

        if role and _looks_like_description_line(role) and not start_raw and not end_raw:
            continue
        if role and _word_count(role) > 10 and not start_raw and not end_raw:
            continue
        if not _looks_like_role_title(role):
            continue

        dedup_key = f"{role.lower()}|{company.lower()}|{start_raw or ''}|{end_raw or ''}"
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        summary_lines = [ln for ln in entry.get("_detail_lines", []) if ln and not _looks_like_role_anchor(ln)]
        summary = " ".join(summary_lines).strip()
        item = {
            "company": company,
            "role": role,
            "start_date": start_raw,
            "end_date": end_raw,
            "duration_years": duration_years,
            "skills": (entry.get("skills") or [])[:10],
        }
        if summary:
            item["summary"] = summary[:320]
        items.append(item)

    merged: list[dict[str, Any]] = []
    idx = 0
    while idx < len(items):
        cur = dict(items[idx])
        nxt = items[idx + 1] if idx + 1 < len(items) else None
        if (
            nxt
            and not cur.get("start_date")
            and not cur.get("end_date")
            and not cur.get("company")
            and _looks_like_company_name(str(cur.get("role") or ""))
            and any(k in str(nxt.get("role") or "").lower() for k in _ROLE_KEYWORDS)
        ):
            nxt_copy = dict(nxt)
            nxt_copy["company"] = str(cur.get("role") or "")[:120]
            merged.append(nxt_copy)
            idx += 2
            continue
        merged.append(cur)
        idx += 1

    return merged[:10]


def _build_projects(section_lines: list[str], lexicon: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for line in section_lines:
        if len(items) >= 12:
            break
        clean = _clean_line(line)
        if len(clean) < 4:
            continue
        if _match_section_heading(clean):
            continue

        if _looks_like_project_anchor(clean):
            if current:
                items.append(current)
            current = {
                "title": _clean_project_title(clean),
                "description": "",
                "skills": _extract_skills_from_text(clean, lexicon)[:10],
            }
            continue

        if current is None:
            continue

        if len(current["description"]) < 420:
            current["description"] = (current["description"] + " " + clean).strip()[:420]
        for skill in _extract_skills_from_text(clean, lexicon):
            if skill not in current["skills"]:
                current["skills"].append(skill)

    if current:
        items.append(current)

    deduped: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for item in items:
        title = _clean_line(str(item.get("title") or ""))
        if not title:
            continue
        if _looks_like_description_line(title):
            continue
        key = title.lower()
        if key in seen_titles:
            continue
        seen_titles.add(key)
        deduped.append(
            {
                "title": title,
                "description": (item.get("description") or title)[:420],
                "skills": (item.get("skills") or [])[:10],
            }
        )
    return deduped[:10]


def _sanitize_work_experience_payload(value: list[Any], lexicon: list[str]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in value:
        if not isinstance(entry, dict):
            continue
        role = _clean_line(str(entry.get("role") or ""))
        company = _clean_line(str(entry.get("company") or ""))
        start_raw = entry.get("start_date")
        end_raw = entry.get("end_date")
        if not role and company:
            role, company = company, ""
        if not role:
            continue
        if _looks_like_description_line(role) and not start_raw and not end_raw:
            continue
        if _word_count(role) > 10 and not start_raw and not end_raw:
            continue
        if not _looks_like_role_title(role):
            continue
        duration = entry.get("duration_years")
        try:
            duration_years = float(duration) if duration is not None else None
            if duration_years is not None and duration_years <= 0:
                duration_years = None
        except (TypeError, ValueError):
            duration_years = None
        skills = entry.get("skills") if isinstance(entry.get("skills"), list) else []
        if not skills:
            skills = _extract_skills_from_text(f"{role} {company}", lexicon)[:10]
        key = f"{role.lower()}|{company.lower()}|{start_raw or ''}|{end_raw or ''}"
        if key in seen:
            continue
        seen.add(key)
        item = {
            "company": company,
            "role": role[:120],
            "start_date": start_raw,
            "end_date": end_raw,
            "duration_years": duration_years,
            "skills": skills[:10],
        }
        summary = _clean_line(str(entry.get("summary") or entry.get("description") or ""))
        if summary:
            item["summary"] = summary[:320]
        cleaned.append(item)
    return cleaned[:10]


def _sanitize_projects_payload(value: list[Any], lexicon: list[str]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in value:
        if not isinstance(entry, dict):
            continue
        title = _clean_project_title(str(entry.get("title") or ""))
        if not title:
            continue
        if _looks_like_description_line(title):
            continue
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        desc = _clean_line(str(entry.get("description") or ""))
        skills = entry.get("skills") if isinstance(entry.get("skills"), list) else []
        if not skills:
            skills = _extract_skills_from_text(f"{title} {desc}", lexicon)[:10]
        cleaned.append(
            {
                "title": title,
                "description": (desc or title)[:420],
                "skills": skills[:10],
            }
        )
    return cleaned[:10]


def _build_education(section_lines: list[str], all_lines: list[str]) -> list[dict[str, Any]]:
    lines = list(section_lines)
    if not lines:
        lines = [ln for ln in all_lines if any(h in ln.lower() for h in _EDU_HINTS)]
    items: list[dict[str, Any]] = []
    for line in lines:
        if len(items) >= 8:
            break
        if len(line) < 4:
            continue
        year_match = re.search(r"\b(19|20)\d{2}\b", line)
        items.append(
            {
                "degree": line[:140],
                "institute": "",
                "year": year_match.group(0) if year_match else "",
                "gpa": None,
            }
        )
    return items


def _build_career_breaks(lines: list[str], work_experience: list[dict[str, Any]]) -> list[dict[str, Any]]:
    breaks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in lines:
        if not _GAP_LINE_RE.search(line):
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        breaks.append(
            {
                "start": None,
                "end": None,
                "duration_months": None,
                "reason": None,
                "notes": line[:240],
            }
        )

    ranges = _extract_date_ranges(lines)
    for idx in range(len(ranges) - 1):
        _, end_dt, _, end_raw = ranges[idx]
        next_start_dt, _, next_start_raw, _ = ranges[idx + 1]
        gap_months = (next_start_dt.year - end_dt.year) * 12 + (next_start_dt.month - end_dt.month)
        if gap_months > 6:
            key = f"{end_raw}|{next_start_raw}|{gap_months}"
            if key in seen:
                continue
            seen.add(key)
            breaks.append(
                {
                    "start": end_raw,
                    "end": next_start_raw,
                    "duration_months": gap_months,
                    "reason": None,
                    "notes": "Inferred timeline gap from resume dates",
                }
            )

    if not breaks and work_experience:
        return []
    return breaks[:6]


def _fallback_experience_years(raw_text: str) -> float:
    values: list[float] = []
    for match in _EXP_RE.finditer(raw_text or ""):
        try:
            values.append(float(match.group(1)))
        except (TypeError, ValueError):
            continue
    for match in _EXP_CAREER_RE.finditer(raw_text or ""):
        try:
            values.append(float(match.group(1)))
        except (TypeError, ValueError):
            continue
    current_year = datetime.utcnow().year
    for match in _EXP_SINCE_RE.finditer(raw_text or ""):
        try:
            since_year = int(match.group(1))
        except (TypeError, ValueError):
            continue
        if since_year <= current_year:
            values.append(float(current_year - since_year))
    return max(values) if values else 0.0


def fast_parse_resume_text(text: str, jd_skills: list[str] | None = None) -> dict[str, Any]:
    raw = text or ""
    raw_lines = raw.splitlines()
    lines = [_clean_line(ln) for ln in raw_lines if _clean_line(ln)]
    lowered = raw.lower()

    email_match = _EMAIL_RE.search(raw)
    phone_match = _PHONE_RE.search(raw)
    years = [float(m.group(1)) for m in _EXP_RE.finditer(raw)]
    exp_years = max(years) if years else 0.0
    if exp_years <= 0.0:
        # Fallback regex for BUG-014 — improve precision with real corpus tests.
        exp_years = _fallback_experience_years(raw)
    exp_years = max(0.0, min(exp_years, min(50.0, float(MAX_RESUME_EXPERIENCE_YEARS))))

    name = None
    for ln in lines[:8]:
        if "@" in ln or len(ln) < 2 or len(ln) > 80:
            continue
        if re.search(r"\d", ln):
            continue
        if any(k in ln.lower() for k in ("resume", "curriculum vitae", "profile summary")):
            continue
        name = ln
        break

    jd_skill_tokens = [_normalize_skill_token(s) for s in (jd_skills or []) if s]
    lexicon = sorted(set(jd_skill_tokens + _COMMON_SKILLS), key=len, reverse=True)
    found_skills = _extract_skills_from_text(lowered, lexicon)
    normalized = sorted(set(_normalize_skill_token(s) for s in found_skills if s))

    sections = _extract_sections(raw_lines)
    work_experience = _build_work_experience(sections["work_experience"], lexicon)
    projects = _build_projects(sections["projects"], lexicon)

    # Fallback when explicit headings are missing: recover structure from
    # global resume lines instead of returning empty work/project sections.
    if not work_experience:
        global_work_lines: list[str] = []
        for ln in lines:
            low = ln.lower()
            if (
                _DATE_RANGE_RE.search(ln)
                or " at " in low
                or any(k in low for k in _ROLE_KEYWORDS)
            ):
                global_work_lines.append(ln)
            if len(global_work_lines) >= 180:
                break
        if global_work_lines:
            work_experience = _build_work_experience(global_work_lines, lexicon)

    if not projects:
        global_project_lines: list[str] = []
        for idx, ln in enumerate(lines):
            low = ln.lower()
            if any(h in low for h in _PROJECT_HINTS):
                global_project_lines.append(ln)
                # Include nearby detail lines so the builder can capture descriptions.
                for off in (1, 2):
                    ni = idx + off
                    if ni < len(lines):
                        global_project_lines.append(lines[ni])
            if len(global_project_lines) >= 220:
                break
        if global_project_lines:
            projects = _build_projects(global_project_lines, lexicon)

    education = _build_education(sections["education"], lines)
    career_breaks = _build_career_breaks(lines, work_experience)

    if exp_years > 0:
        per_skill = min(exp_years, 6.0)
        skill_years = {s: per_skill for s in normalized[:25]}
    else:
        skill_years = {}

    return {
        "name": name,
        "email": email_match.group(1) if email_match else None,
        "phone": phone_match.group(1).strip() if phone_match else None,
        "location": None,
        "skills": found_skills,
        "normalized_skills": normalized,
        "experience_years": exp_years,
        "education": education,
        "projects": projects,
        "work_experience": work_experience,
        "career_breaks": career_breaks,
        "skill_years": skill_years,
        "summary": "",
    }


def coerce_parsed_resume(
    parsed: dict[str, Any] | None,
    text: str,
    jd_skills: list[str] | None = None,
) -> dict[str, Any]:
    """
    Ensure a parser payload always contains the structured keys expected by UI/API.
    Uses fallback extraction for missing sections when AI output is partial.
    """
    jd_skill_tokens = [_normalize_skill_token(s) for s in (jd_skills or []) if s]
    lexicon = sorted(set(jd_skill_tokens + _COMMON_SKILLS), key=len, reverse=True)
    fallback = fast_parse_resume_text(text, jd_skills=jd_skills)
    if not isinstance(parsed, dict):
        return fallback

    result = dict(fallback)

    for key in ("name", "email", "phone", "location", "summary"):
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()

    exp_val = parsed.get("experience_years")
    try:
        parsed_exp = float(exp_val)
    except (TypeError, ValueError):
        parsed_exp = None
    if parsed_exp is not None and parsed_exp >= 0:
        result["experience_years"] = min(parsed_exp, float(MAX_RESUME_EXPERIENCE_YEARS))

    for key in ("skills", "normalized_skills", "education", "career_breaks"):
        value = parsed.get(key)
        if isinstance(value, list):
            if key in {"education", "career_breaks"}:
                result[key] = value if value else result[key]
            else:
                result[key] = value

    parsed_projects = parsed.get("projects")
    if isinstance(parsed_projects, list):
        sanitized_projects = _sanitize_projects_payload(parsed_projects, lexicon)
        if sanitized_projects:
            result["projects"] = sanitized_projects

    parsed_work = parsed.get("work_experience")
    if isinstance(parsed_work, list):
        sanitized_work = _sanitize_work_experience_payload(parsed_work, lexicon)
        if sanitized_work:
            result["work_experience"] = sanitized_work

    skill_years = parsed.get("skill_years")
    if isinstance(skill_years, dict):
        result["skill_years"] = skill_years

    return result
