"""Qualifi Match: how well a candidate's skills fit a job, out of 100%.

Match % = 60% skill coverage + 25% meaning similarity + 15% experience/level fit.
Every part is explainable, so the candidate sees exactly which skills are missing.
"""
import math
import re
from collections import Counter

from .skills import expand, extract_skills, split_skills, text_has_skill

WEIGHTS = {"skills": 0.60, "similarity": 0.25, "level": 0.15}
LEVEL_YEARS = {"fresh": (0, 1), "junior": (1, 3), "senior": (5, 40)}
STOPWORDS = set("""a an and are as at be by for from has have in is it its of on or that the to was were will with
you your our we they this these those their can may must should not but if then than so such into over under
about across after before during within without per via job role team work working years year experience
looking candidate candidates ability strong good great excellent knowledge skills skill using use used""".split())


def job_skills(job):
    """The skills the company listed (or, if none, those found in the description)."""
    return split_skills(job["skills"]) or extract_skills(job["description"] or "")


def compute_match(job, profile, corpus=()):
    """Return {score, matched, missing, breakdown} for a job row and a candidate profile row."""
    required = job_skills(job)
    cand_text = " ".join([
        profile["skills"] or "", profile["headline"] or "", profile["experience"] or "",
        profile["education"] or "", profile["cv_text"] or "",
    ])
    cand_lower = cand_text.lower()
    cand_skills = split_skills(profile["skills"]) + extract_skills(profile["cv_text"] or "")
    cand_skill_names = {s.lower() for s in expand(cand_skills)}

    matched, missing = [], []
    for skill in required:
        if skill.lower() in cand_skill_names or text_has_skill(cand_lower, skill):
            matched.append(skill)
        else:
            missing.append(skill)
    coverage = len(matched) / len(required) if required else 0.5

    job_text = " ".join([job["title"], job["description"] or "", job["skills"] or ""])
    cosine = tfidf_cosine(job_text, cand_text, corpus)
    similarity = min(1.0, cosine / 0.35)   # typical CV/job cosines sit between 0.05 and 0.4

    level = level_fit(job["level"], profile["experience_years"] or 0)

    score = round(100 * (WEIGHTS["skills"] * coverage + WEIGHTS["similarity"] * similarity + WEIGHTS["level"] * level))
    return {
        "score": max(0, min(100, score)),
        "matched": matched,
        "missing": missing,
        "breakdown": {
            "skills": round(coverage * 100),
            "similarity": round(similarity * 100),
            "level": round(level * 100),
        },
    }


def level_fit(level, years):
    low, high = LEVEL_YEARS.get(level, (0, 40))
    if low <= years <= high:
        return 1.0
    if years < low:
        return max(0.0, 1 - (low - years) / max(low, 1) * 0.8)
    # over-qualified: a gentle penalty only
    return max(0.6, 1 - (years - high) * 0.05)


def _tokens(text):
    return [t for t in re.findall(r"[a-z][a-z0-9+#.]{1,}", (text or "").lower()) if t not in STOPWORDS]


def tfidf_cosine(a, b, corpus=()):
    docs = [_tokens(a), _tokens(b)] + [_tokens(c) for c in corpus]
    n = len(docs)
    df = Counter()
    for d in docs:
        df.update(set(d))

    def vec(tokens):
        tf = Counter(tokens)
        return {t: (1 + math.log(c)) * (math.log((1 + n) / (1 + df[t])) + 1) for t, c in tf.items()}

    va, vb = vec(docs[0]), vec(docs[1])
    dot = sum(w * vb.get(t, 0) for t, w in va.items())
    na = math.sqrt(sum(w * w for w in va.values()))
    nb = math.sqrt(sum(w * w for w in vb.values()))
    return dot / (na * nb) if na and nb else 0.0
