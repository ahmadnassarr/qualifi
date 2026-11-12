"""A small skills dictionary for many fields, with aliases (so "JS" and "JavaScript" are the same skill).

Any skill a company types that is not in this list still works: it is matched as plain text.
"""
import re

# canonical name -> (category, [aliases])
SKILLS = {
    # ---- Tech ----
    "JavaScript": ("tech", ["javascript", "js", "ecmascript", "es6"]),
    "TypeScript": ("tech", ["typescript", "ts"]),
    "Python": ("tech", ["python"]),
    "Java": ("tech", ["java"]),
    "C#": ("tech", ["c#", "csharp", "c sharp"]),
    "C++": ("tech", ["c++", "cpp"]),
    "PHP": ("tech", ["php"]),
    "Go": ("tech", ["golang"]),
    "Ruby": ("tech", ["ruby"]),
    "Kotlin": ("tech", ["kotlin"]),
    "Swift": ("tech", ["swift"]),
    "HTML": ("tech", ["html", "html5"]),
    "CSS": ("tech", ["css", "css3", "sass", "scss", "tailwind"]),
    "React": ("tech", ["react", "react.js", "reactjs"]),
    "Angular": ("tech", ["angular"]),
    "Vue": ("tech", ["vue", "vue.js", "vuejs"]),
    "Node.js": ("tech", ["node.js", "nodejs", "node"]),
    "Express": ("tech", ["express", "express.js"]),
    "Django": ("tech", ["django"]),
    "Flask": ("tech", ["flask"]),
    "Spring": ("tech", ["spring boot", "spring"]),
    ".NET": ("tech", [".net", "asp.net", "dotnet"]),
    "SQL": ("tech", ["sql", "t-sql", "pl/sql"]),
    "PostgreSQL": ("tech", ["postgresql", "postgres"]),
    "MySQL": ("tech", ["mysql"]),
    "MongoDB": ("tech", ["mongodb", "mongo"]),
    "Git": ("tech", ["git", "github", "gitlab"]),
    "Docker": ("tech", ["docker", "docker compose", "containers"]),
    "Kubernetes": ("tech", ["kubernetes", "k8s"]),
    "CI/CD": ("tech", ["ci/cd", "continuous integration", "github actions", "jenkins"]),
    "AWS": ("tech", ["aws", "amazon web services"]),
    "Azure": ("tech", ["azure"]),
    "Linux": ("tech", ["linux", "bash", "shell scripting"]),
    "REST APIs": ("tech", ["rest", "rest api", "rest apis", "restful"]),
    "GraphQL": ("tech", ["graphql"]),
    "Testing": ("tech", ["unit testing", "jest", "pytest", "test automation", "selenium"]),
    "Machine Learning": ("tech", ["machine learning", "ml", "deep learning"]),
    "Data Analysis": ("tech", ["data analysis", "data analytics", "pandas"]),
    "Power BI": ("tech", ["power bi", "powerbi"]),
    "Tableau": ("tech", ["tableau"]),
    "Cybersecurity": ("tech", ["cybersecurity", "security", "penetration testing"]),
    "Networking": ("tech", ["networking", "tcp/ip", "ccna"]),
    "Agile": ("tech", ["agile", "scrum", "kanban", "jira"]),
    "Code Review": ("tech", ["code review", "code reviews", "pull request", "pull requests"]),
    # ---- Nursing & healthcare ----
    "Patient Care": ("health", ["patient care", "bedside care"]),
    "Medication Administration": ("health", ["medication administration", "administering medication"]),
    "Vital Signs": ("health", ["vital signs", "vitals"]),
    "BLS": ("health", ["bls", "basic life support", "cpr"]),
    "ACLS": ("health", ["acls", "advanced cardiovascular life support"]),
    "Infection Control": ("health", ["infection control", "infection prevention", "hand hygiene"]),
    "Wound Care": ("health", ["wound care", "wound dressing"]),
    "IV Therapy": ("health", ["iv therapy", "iv insertion", "intravenous", "cannulation"]),
    "Electronic Health Records": ("health", ["electronic health records", "ehr", "emr"]),
    "Triage": ("health", ["triage"]),
    "Pharmacology": ("health", ["pharmacology"]),
    "Patient Education": ("health", ["patient education"]),
    "Critical Care": ("health", ["critical care", "icu", "intensive care"]),
    "Pediatrics": ("health", ["pediatrics", "paediatrics", "pediatric"]),
    "Phlebotomy": ("health", ["phlebotomy", "blood draw"]),
    "Medical Terminology": ("health", ["medical terminology"]),
    # ---- Accounting & finance ----
    "Accounting": ("finance", ["accounting", "bookkeeping"]),
    "Financial Reporting": ("finance", ["financial reporting", "financial statements"]),
    "IFRS": ("finance", ["ifrs"]),
    "GAAP": ("finance", ["gaap"]),
    "Auditing": ("finance", ["auditing", "audit", "internal audit"]),
    "Taxation": ("finance", ["taxation", "tax", "vat"]),
    "Budgeting": ("finance", ["budgeting", "forecasting"]),
    "Excel": ("finance", ["excel", "microsoft excel", "spreadsheets"]),
    "QuickBooks": ("finance", ["quickbooks"]),
    "SAP": ("finance", ["sap"]),
    "Payroll": ("finance", ["payroll"]),
    "Accounts Payable": ("finance", ["accounts payable", "ap"]),
    "Accounts Receivable": ("finance", ["accounts receivable", "ar"]),
    "Financial Analysis": ("finance", ["financial analysis", "financial modeling", "financial modelling"]),
    "Reconciliation": ("finance", ["reconciliation", "bank reconciliation"]),
    # ---- Design ----
    "Figma": ("design", ["figma"]),
    "Adobe Photoshop": ("design", ["photoshop"]),
    "Adobe Illustrator": ("design", ["illustrator"]),
    "Adobe XD": ("design", ["adobe xd"]),
    "InDesign": ("design", ["indesign"]),
    "UI Design": ("design", ["ui design", "user interface"]),
    "UX Design": ("design", ["ux design", "user experience", "ux research", "usability testing"]),
    "Wireframing": ("design", ["wireframing", "wireframes", "prototyping"]),
    "Typography": ("design", ["typography"]),
    "Branding": ("design", ["branding", "brand identity"]),
    "Graphic Design": ("design", ["graphic design"]),
    # ---- Marketing & sales ----
    "Digital Marketing": ("marketing", ["digital marketing", "online marketing"]),
    "SEO": ("marketing", ["seo", "search engine optimization"]),
    "Social Media": ("marketing", ["social media", "instagram", "tiktok", "facebook ads"]),
    "Content Writing": ("marketing", ["content writing", "copywriting", "content creation"]),
    "Google Analytics": ("marketing", ["google analytics", "ga4"]),
    "Email Marketing": ("marketing", ["email marketing", "mailchimp"]),
    "CRM": ("marketing", ["crm", "salesforce", "hubspot"]),
    "Sales": ("marketing", ["sales", "b2b sales", "lead generation"]),
    "Market Research": ("marketing", ["market research"]),
    # ---- General / soft skills ----
    "Communication": ("soft", ["communication", "communication skills"]),
    "Teamwork": ("soft", ["teamwork", "team player", "collaboration"]),
    "Leadership": ("soft", ["leadership", "team lead", "mentoring"]),
    "Problem Solving": ("soft", ["problem solving", "problem-solving"]),
    "Time Management": ("soft", ["time management"]),
    "Customer Service": ("soft", ["customer service", "customer support"]),
    "Project Management": ("soft", ["project management", "pmp"]),
    "English": ("soft", ["english"]),
    "Arabic": ("soft", ["arabic"]),
    "French": ("soft", ["french"]),
}

# Having one skill implies another (knowing PostgreSQL means you know SQL).
IMPLIES = {
    "PostgreSQL": ["SQL"], "MySQL": ["SQL"], "React": ["JavaScript"], "Angular": ["TypeScript", "JavaScript"],
    "Vue": ["JavaScript"], "TypeScript": ["JavaScript"], "Node.js": ["JavaScript"], "Express": ["Node.js", "JavaScript"],
    "Django": ["Python"], "Flask": ["Python"], "Spring": ["Java"], "Kubernetes": ["Docker"],
    "ACLS": ["BLS"], "IFRS": ["Accounting"], "GAAP": ["Accounting"], "QuickBooks": ["Accounting"],
    "Financial Reporting": ["Accounting"], "Adobe XD": ["UI Design"], "Figma": ["UI Design"],
}


def expand(skills):
    """Add implied skills: ['React'] -> ['React', 'JavaScript']."""
    out = list(skills)
    for s in skills:
        for extra in IMPLIES.get(canonical(s), []):
            if extra not in out:
                out.append(extra)
    return out


# Aliases that are too ambiguous to find inside free text (they still work when typed as a skill).
_TEXT_UNSAFE = {"go", "ts", "ap", "ar", "ml", "node", "spring", "rest", "tax", "audit", "sales", "security",
                "english", "arabic", "french", "swift", "sap", "express", "containers", "communication"}

_ALIAS_TO_CANON = {}
for canon, (_cat, aliases) in SKILLS.items():
    _ALIAS_TO_CANON[canon.lower()] = canon
    for a in aliases:
        _ALIAS_TO_CANON[a.lower()] = canon


def _pattern(term):
    return re.compile(r"(?<![a-z0-9+#./])" + re.escape(term.lower()) + r"(?![a-z0-9+#]|\.[a-z])")


_TEXT_PATTERNS = [
    (alias, canon, _pattern(alias))
    for alias, canon in sorted(_ALIAS_TO_CANON.items(), key=lambda kv: -len(kv[0]))
    if alias not in _TEXT_UNSAFE
]
# A few ambiguous ones are safe when written with their usual capitalisation.
_CASED_PATTERNS = [
    ("Go", re.compile(r"\bGo(?:lang)?\b(?! to| ahead| through| back)")),
    ("TypeScript", re.compile(r"\bTS\b")),
    ("Node.js", re.compile(r"\bNode\b")),
    ("Express", re.compile(r"\bExpress(?:\.js)?\b")),
    ("SAP", re.compile(r"\bSAP\b")),
    ("Swift", re.compile(r"\bSwift\b")),
    ("English", re.compile(r"\bEnglish\b")),
    ("Arabic", re.compile(r"\bArabic\b")),
    ("French", re.compile(r"\bFrench\b")),
    ("Communication", re.compile(r"\b[Cc]ommunication skills\b|\bCommunication\b")),
    ("Spring", re.compile(r"\bSpring(?: Boot)?\b")),
    ("REST APIs", re.compile(r"\bREST(?:ful)?\b")),
    ("Machine Learning", re.compile(r"\bML\b")),
    ("Sales", re.compile(r"\b[Ss]ales\b")),
    ("Auditing", re.compile(r"\b[Aa]udit(?:ing|s)?\b")),
    ("Taxation", re.compile(r"\b[Tt]ax(?:ation|es)?\b")),
    ("Cybersecurity", re.compile(r"\b(?:[Ii]nformation|[Cc]yber|[Nn]etwork) security\b")),
]


def canonical(skill):
    """Return the canonical display name for a typed skill."""
    s = (skill or "").strip().strip(".,;:")
    if not s:
        return ""
    return _ALIAS_TO_CANON.get(s.lower(), s[:1].upper() + s[1:] if s.islower() else s)


def category(skill):
    canon = canonical(skill)
    return SKILLS[canon][0] if canon in SKILLS else "other"


def split_skills(text):
    """'React, SQL;Git' -> ['React', 'SQL', 'Git'] with duplicates removed (canonical names)."""
    seen, out = set(), []
    for part in re.split(r"[,;\n|]+", text or ""):
        c = canonical(part)
        if c and c.lower() not in seen:
            seen.add(c.lower())
            out.append(c)
    return out


def extract_skills(text):
    """Find known skills inside free text such as a CV or a job description."""
    if not text:
        return []
    low = text.lower()
    found = []
    for _alias, canon, pat in _TEXT_PATTERNS:
        if canon not in found and pat.search(low):
            found.append(canon)
    for canon, pat in _CASED_PATTERNS:
        if canon not in found and pat.search(text):
            found.append(canon)
    return found


def text_has_skill(text_lower, skill):
    """True if a (possibly unknown) skill or any alias of it appears in lower-cased text."""
    canon = canonical(skill)
    terms = {canon.lower(), skill.lower().strip()}
    if canon in SKILLS:
        terms.update(a for a in SKILLS[canon][1] if a not in _TEXT_UNSAFE)
    return any(_pattern(t).search(text_lower) for t in terms if t)


def same_category_skills(skill, exclude=()):
    cat = category(skill)
    ex = {e.lower() for e in exclude}
    return [c for c, (k, _a) in SKILLS.items() if k == cat and c.lower() not in ex]
