"""Read a CV and build a profile: name, contact, skills, experience and education."""
import re
from datetime import date

from .skills import extract_skills, split_skills

SECTION_WORDS = {
    "experience": ["experience", "work experience", "employment", "professional experience", "work history"],
    "education": ["education", "academic background", "qualifications", "academic"],
    "skills": ["skills", "technical skills", "core skills", "competencies"],
    "other": ["summary", "profile", "projects", "certifications", "languages", "references", "interests",
              "volunteering", "awards", "contact", "objective"],
}
DEGREE_RE = re.compile(r"\b(B\.?Sc?|B\.?A|Bachelor|M\.?Sc?|Master|MBA|Ph\.?D|Diploma|Associate|BSN|RN|"
                       r"University|College|Institute|Licen[cs]e)\b", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")
YEARS_RE = re.compile(r"(\d{1,2})\+?\s*(?:years?|yrs?)", re.I)
RANGE_RE = re.compile(r"((?:19|20)\d{2})\s*(?:-|–|—|to)\s*((?:19|20)\d{2}|present|current|now)", re.I)
MONTHS_RE = re.compile(r"(\d{1,2})\s*months?", re.I)


def parse_cv(text):
    """Return a dict with the profile fields, read with simple built-in rules (no AI)."""
    return parse_cv_locally(text)


def parse_cv_locally(text):
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    sections = _split_sections(lines)

    email_match = EMAIL_RE.search(text or "")
    email = email_match.group(0) if email_match else ""
    phone_match = PHONE_RE.search(text or "")
    phone = phone_match.group(1).strip() if phone_match else ""

    name, name_idx = "", None
    for i, line in enumerate(lines[:6]):
        if EMAIL_RE.search(line) or PHONE_RE.search(line):
            continue
        words = line.split()
        if 1 < len(words) <= 4 and all(re.match(r"^[A-Za-zÀ-ÿ'.-]+$", w) for w in words):
            name = line.title() if line.isupper() else line
            name_idx = i
            break

    headline = ""
    if name_idx is not None:
        for line in lines[name_idx + 1: name_idx + 4]:
            if not EMAIL_RE.search(line) and not PHONE_RE.search(line) and len(line) < 70 and _heading_key(line) is None:
                headline = line
                break

    location = ""
    loc = re.search(r"\b(Beirut|Tripoli|Saida|Sidon|Tyre|Zahle|Byblos|Jounieh|Dubai|Riyadh|Doha|Amman|Cairo|"
                    r"Remote|London|Paris)\b(?:,\s*[A-Z][a-z]+)?", text or "")
    if loc:
        location = loc.group(0)

    skill_text = " ".join(sections.get("skills", []))
    skills = split_skills(", ".join(extract_skills(skill_text) + extract_skills(text)))

    experience_lines = sections.get("experience", [])
    education_lines = sections.get("education", []) or [l for l in lines if DEGREE_RE.search(l)][:3]

    return {
        "name": name,
        "email": email,
        "phone": phone,
        "headline": headline,
        "location": location,
        "skills": skills[:40],
        "experience_years": estimate_years(" ".join(experience_lines) or text),
        "experience": "\n".join(experience_lines[:6]),
        "education": "\n".join(education_lines[:4]),
    }


def estimate_years(text):
    """Estimate total years of experience from '3 years' phrases or date ranges."""
    text = text or ""
    total = 0.0
    this_year = date.today().year
    for start, end in RANGE_RE.findall(text):
        end_year = this_year if not end[:1].isdigit() else int(end)
        span = end_year - int(start)
        if 0 <= span <= 45:
            total += max(span, 0.5)
    stated = [int(n) for n in YEARS_RE.findall(text) if int(n) <= 45]
    months = [int(n) for n in MONTHS_RE.findall(text) if int(n) <= 36]
    if stated:
        total = max(total, max(stated))
    if not total and months:
        total = sum(months) / 12
    return round(min(total, 45), 1)


def _heading_key(line):
    clean = re.sub(r"[^a-z ]", "", line.lower()).strip()
    if len(clean) > 30:
        return None
    for key, words in SECTION_WORDS.items():
        if clean in words:
            return key
    return None


def _split_sections(lines):
    sections, current = {}, None
    for line in lines:
        key = _heading_key(line)
        if key:
            current = key
            sections.setdefault(key, [])
            continue
        if current:
            sections[current].append(line)
    return sections
