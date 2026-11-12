"""The Qualifi Test: every question comes from the company's own files. No AI, no internet, no paid services.

Two ways, both on the company's "Add test files" screen:
  1. Import: the company uploads its own question bank (PDF, Word or text) and the questions are copied in
     exactly as written (see parse_question_bank for the format).
  2. Build from files: the company uploads guides, policies or manuals, and simple built-in rules turn the
     facts in them (numbers, rules, named tools and terms) into multiple-choice questions.
Every question records the file and page it came from, and the company reviews all of them before publishing.
"""
import random
import re
import zlib
from collections import Counter

from .skills import SKILLS, canonical, category, extract_skills, same_category_skills


def doc_title(filename):
    base = re.sub(r"\.[A-Za-z0-9]+$", "", filename or "")
    return re.sub(r"[_-]+", " ", base).strip() or "the document"


def generate_questions(job, documents, count=40):
    """documents: list of dicts {filename, path, pages: [text, ...]}. Returns a list of questions."""
    return generate_locally(job, documents, count)


# --------------------------------------------------------------------------- 1. import the company's own questions
Q_START = re.compile(r"^(?:Q(?:uestion)?\s*)?(\d{1,3})\s*[.):\-]\s*(.+)$", re.I)
OPTION = re.compile(r"^\(?([A-Da-d])\s*[.):\]]\s*(.+)$")
ANSWER = re.compile(r"^(?:correct\s+answer|answer|ans|key)\s*[:\-=]?\s*\(?([A-Da-d])\)?(?:[.)\s]|$)", re.I)
TOPIC = re.compile(r"^topic\s*[:\-]\s*(.+)$", re.I)
KEY_HEADING = re.compile(r"^(?:answer\s*key|answers|correct\s+answers)\s*:?$", re.I)
KEY_ITEM = re.compile(r"(\d{1,3})\s*[.):\-=]?\s*\(?([A-Da-d])\)?(?![A-Za-z])")
STAR = re.compile(r"\s*(?:\*|\(correct\)|\[correct\]|✓|✔)\s*$", re.I)


def parse_question_bank(pages, filename):
    """Read a company's own question file.

    Expected format (one question after another; PDF, Word or text):

        1. How many approvals does a pull request need?
        A) None
        B) One
        C) Two
        D) Three
        Answer: B
        Topic: Code reviews        (optional)

    The correct option can also be marked with a * at the end of its line, or listed in an
    "Answer key" section at the end (e.g. "1-B, 2-C, 3-A").
    Returns (questions, problems) where problems lists the question numbers that could not be read.
    """
    items, current, in_key, key = [], None, False, {}

    def close():
        if current is not None:
            items.append(current)

    for page_no, page in enumerate(pages, start=1):
        for raw in page.splitlines():
            line = raw.strip()
            if not line:
                continue
            if KEY_HEADING.match(line):
                close()
                current, in_key = None, True
                continue
            if in_key:
                for num, letter in KEY_ITEM.findall(line):
                    key[int(num)] = "ABCD".index(letter.upper())
                continue
            m_ans = ANSWER.match(line)
            m_opt = OPTION.match(line)
            m_topic = TOPIC.match(line)
            m_q = Q_START.match(line)
            if current is not None and m_ans:
                current["answer"] = "ABCD".index(m_ans.group(1).upper())
            elif current is not None and m_topic:
                current["topic"] = m_topic.group(1).strip()[:60]
            elif current is not None and m_opt and len(current["options"]) < 5:
                text = m_opt.group(2).strip()
                if STAR.search(text):
                    text = STAR.sub("", text).strip()
                    current["answer"] = len(current["options"])
                current["options"].append(text)
            elif m_q:
                close()
                current = {"num": int(m_q.group(1)), "text": m_q.group(2).strip(), "options": [],
                           "answer": None, "topic": "", "page": page_no}
            elif current is not None:
                # a wrapped line: continue the question text or the last option
                if current["options"]:
                    current["options"][-1] += " " + line
                else:
                    current["text"] += " " + line
    close()

    questions, problems = [], []
    for it in items:
        if it["answer"] is None and it["num"] in key:
            it["answer"] = key[it["num"]]
        options = [o.strip() for o in it["options"]]
        ok = (len(options) == 4 and it["answer"] is not None and 0 <= it["answer"] < 4
              and len({o.lower() for o in options}) == 4 and it["text"])
        if not ok:
            problems.append(it["num"])
            continue
        questions.append({"text": it["text"], "options": options, "answer_index": it["answer"],
                          "source_doc": filename, "source_page": it["page"],
                          "topic": it["topic"] or doc_title(filename), "origin": "imported"})
    return questions, problems


# --------------------------------------------------------------------------- 2. build questions from the facts in the files
NUMBER_WORDS = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "twelve",
                "fifteen", "twenty", "thirty"]
UNIT = (r"(?:%|percent|hours?|days?|minutes?|weeks?|months?|years?|seconds?|mg|mcg|ml|mmhg|°c|times|"
        r"approvals?|reviewers?|characters?|people|members|steps|patients|items|lines|points|working days|"
        r"business days|milliseconds|dollars|rows|columns|beds|shifts)")
NUM_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s?(" + UNIT + r")\b", re.I)
WORDNUM_RE = re.compile(r"\b(?:in|within|for|of|than|least|to|after|before|under|over|by|with|has|have|needs?|"
                        r"at|lasts|the|is|are|takes?|every)\s+(" + "|".join(NUMBER_WORDS) + r")\s+([a-z]{3,})\b", re.I)
CAP_PHRASE_RE = re.compile(r"(?<!^)(?<![.!?]\s)\b([A-Z][a-zA-Z0-9]+(?:[ -][A-Z][a-zA-Z0-9]+){0,3})\b")
QUOTED_RE = re.compile(r"[\"“']([^\"”']{3,40})[\"”']")
RULE_WORDS = re.compile(r"\b(must|should|always|never|required|only|before|after|within|at least|no more than|"
                        r"every|each|minimum|maximum)\b", re.I)
STOP = set("""the and for with that this from into your their have will must should when where which while about
after before every each other there these those then than what them they been being only also more most such
some same very just over under within without between because could would shall might upon onto per via""".split())


def _is_heading(line):
    s = line.strip()
    if not s or len(s) > 60 or s.endswith((".", ",", ";", ":")) and not s.endswith(":"):
        return False
    words = s.rstrip(":").split()
    if not 1 <= len(words) <= 8 or not words[0][:1].isalpha() or not words[0][:1].isupper():
        return False
    return s.isupper() or s.endswith(":") or re.match(r"^\d+(\.\d+)*\s", s) or \
        sum(w[:1].isupper() for w in words if len(w) > 3) >= max(1, len([w for w in words if len(w) > 3]) - 1)


def _sentences(documents):
    """Yield dicts: text, doc, page, heading."""
    out = []
    for d in documents:
        for p_i, page in enumerate(d["pages"]):
            heading = doc_title(d["filename"])
            buf = []

            def flush():
                para = " ".join(buf).strip()
                buf.clear()
                for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9“\"])", para):
                    s = s.strip()
                    words = s.split()
                    if 7 <= len(words) <= 42 and not s.endswith("?"):
                        out.append({"text": s if s.endswith((".", "!")) else s + ".", "doc": d["filename"],
                                    "page": p_i + 1, "heading": heading})

            for raw in page.splitlines():
                line = raw.strip()
                if not line:
                    flush()
                    continue
                bullet = re.match(r"^(?:[-•*▪●◦]|\d+[.)])\s+(.*)$", line)
                if bullet:
                    flush()
                    buf.append(bullet.group(1))
                    flush()
                elif _is_heading(line):
                    flush()
                    heading = re.sub(r"^\d+(\.\d+)*\s+", "", line.rstrip(":")).strip().title() \
                        if line.isupper() else re.sub(r"^\d+(\.\d+)*\s+", "", line.rstrip(":")).strip()
                else:
                    buf.append(line)
            flush()
    return out


def _find_terms(sentence, job_skill_names):
    """Candidate answer terms inside one sentence: (surface, kind, extra)."""
    text = sentence["text"]
    terms = []
    for m in NUM_RE.finditer(text):
        terms.append((m.group(0), "number", (m.group(1), m.group(2))))
    for m in WORDNUM_RE.finditer(text):
        if m.group(2).split()[0].lower() not in STOP:
            terms.append((text[m.start(1):m.end(2)], "wordnum", (m.group(1).lower(), m.group(2))))
    low = text.lower()
    for skill in set(extract_skills(text)) | {s for s in job_skill_names if s.lower() in low}:
        canon = canonical(skill)
        variants = [canon] + (SKILLS[canon][1] if canon in SKILLS else [])
        for v in sorted(variants, key=len, reverse=True):
            m = re.search(r"(?<![A-Za-z0-9])" + re.escape(v) + r"(?![A-Za-z0-9])", text, re.I)
            if m:
                terms.append((m.group(0), "skill", canon))
                break
    for m in QUOTED_RE.finditer(text):
        terms.append((m.group(1), "phrase", None))
    first_word = text.split()[0] if text.split() else ""
    for m in CAP_PHRASE_RE.finditer(text):
        phrase = m.group(1)
        if phrase == first_word or phrase.lower() in STOP or len(phrase) < 3:
            continue
        if any(phrase.lower() in t[0].lower() or t[0].lower() in phrase.lower() for t in terms):
            continue
        terms.append((phrase, "phrase", None))
    return terms


def _keywords(sentences):
    """Domain words that repeat across the files (good blanks when nothing better exists)."""
    counts = Counter()
    for s in sentences:
        for w in set(re.findall(r"\b[a-z][a-z-]{5,}\b", s["text"].lower())):
            if w not in STOP:
                counts[w] += 1
    return {w: c for w, c in counts.items() if 2 <= c <= max(3, len(sentences) // 3)}


def _unit_for(n, unit):
    """'1 approvals' -> '1 approval', '3 hour' -> '3 hours'."""
    u = unit
    if u.lower() in ("%", "percent", "mg", "mcg", "ml", "mmhg", "°c"):
        return u
    plural = u if u.endswith("s") else u + "s"
    singular = u[:-1] if u.endswith("s") else u
    return singular if n == 1 else plural


def _nice(x):
    if x >= 100:
        return round(x / 10) * 10
    if x >= 20:
        return round(x / 5) * 5
    if x >= 10:
        return round(x)
    return x


def _number_distractors(value, unit, pool):
    try:
        n = float(value)
    except ValueError:
        return []
    is_int = n.is_integer()
    if n >= 10:
        raw = [n * 2, n / 2, n * 1.5, n * 3, n * 0.75, n + 10]
    else:
        raw = [n + 1, n * 2, n - 1, n + 2, n + 3, n * 3]
    raw += sorted(p for p in pool if p != n)
    seen, out = set(), []
    for x in raw:
        x = _nice(x)
        if x <= 0 or x == n or (is_int and not float(x).is_integer()):
            continue
        x = int(x) if is_int else round(x, 1)
        if x in seen:
            continue
        seen.add(x)
        sep = "" if unit == "%" else " "
        out.append(f"{x}{sep}{_unit_for(x, unit)}")
    return out


def _wordnum_distractors(word, noun):
    idx = NUMBER_WORDS.index(word) if word in NUMBER_WORDS else 1
    picks = [i for i in (idx + 1, idx - 1, idx + 2, idx - 2, idx + 3) if 0 <= i < len(NUMBER_WORDS) and i != idx]
    out = []
    for i in picks:
        w = NUMBER_WORDS[i]
        n = noun
        if w == "one" and noun.endswith("s"):
            n = noun[:-1]
        elif word == "one" and not noun.endswith("s"):
            n = noun + "s"
        out.append(f"{w} {n}")
    return out


def _match_case(answer, option):
    return option[:1].upper() + option[1:] if answer[:1].isupper() else option


def generate_locally(job, documents, count=40, seed=None):
    rng = random.Random(seed if seed is not None else zlib.crc32((job["title"] + str(len(documents))).encode()))
    sentences = _sentences(documents)
    if not sentences:
        return []
    job_skill_names = [canonical(s) for s in re.split(r"[,;\n]+", job["skills"] or "") if s.strip()]
    keywords = _keywords(sentences)

    # pools for distractors, built from the company's own files
    pools = {"phrase": Counter(), "skill": Counter(), "word": Counter()}
    numbers_by_unit = {}
    per_sentence = []
    for s in sentences:
        terms = _find_terms(s, job_skill_names)
        for surface, kind, extra in terms:
            if kind in ("phrase", "skill"):
                pools[kind][extra if kind == "skill" else surface] += 1
            if kind == "number":
                try:
                    numbers_by_unit.setdefault(extra[1].lower(), set()).add(float(extra[0]))
                except ValueError:
                    pass
        words = [w for w in re.findall(r"\b[a-z][a-z-]{5,}\b", s["text"].lower()) if w in keywords]
        for w in words:
            pools["word"][w] += 1
        per_sentence.append((s, terms, words))

    level = job["level"]
    candidates = []
    for s, terms, words in per_sentence:
        options = []
        for surface, kind, extra in terms:
            if kind == "number":
                d = _number_distractors(extra[0], extra[1], numbers_by_unit.get(extra[1].lower(), set()))
            elif kind == "wordnum":
                d = _wordnum_distractors(extra[0], extra[1])
            elif kind == "skill":
                d = [k for k, _ in pools["skill"].most_common() if k != extra] + same_category_skills(extra, [extra])
                if category(extra) == "other":
                    d += [k for k, _ in pools["phrase"].most_common()]
            else:
                d = [k for k, _ in pools["phrase"].most_common() if k.lower() != surface.lower()]
            options.append((surface, kind, d))
        for w in words:
            d = [k for k, _ in pools["word"].most_common() if k != w]
            options.append((w, "word", d))
        for surface, kind, d in options:
            low_sentence = s["text"].lower()
            d = [x for x in d if x.lower() != surface.lower() and x.lower() not in low_sentence]
            uniq = []
            for x in d:
                if x.lower() not in {u.lower() for u in uniq}:
                    uniq.append(x)
            if kind in ("word", "phrase"):
                same_form = [x for x in uniq if x.endswith("s") == surface.endswith("s")]
                if len(same_form) >= 3:
                    uniq = same_form
            if len(uniq) < 3:
                continue
            priority = {"number": 5, "wordnum": 5, "skill": 4, "phrase": 3, "word": 1}[kind]
            freq = keywords.get(surface.lower(), 1)
            score = priority + (1.5 if RULE_WORDS.search(s["text"]) else 0)
            if level == "fresh":
                score += min(freq, 4) * 0.4
            elif level == "senior":
                score += len(s["text"].split()) / 15 - min(freq, 4) * 0.2
            else:
                score += 1 if kind in ("number", "wordnum") else 0
            candidates.append({"s": s, "answer": surface, "kind": kind, "distractors": uniq, "score": score})
            break  # one question per sentence: the best term found first

    # pick the best questions, spread across files and sections
    candidates.sort(key=lambda c: -c["score"])
    chosen, used_sent, answer_uses, per_heading = [], set(), Counter(), Counter()
    cap_heading = max(3, count // max(1, len({c["s"]["heading"] for c in candidates})) + 2)
    for c in candidates:
        key = c["s"]["text"]
        if key in used_sent or answer_uses[c["answer"].lower()] >= 2 or per_heading[c["s"]["heading"]] >= cap_heading:
            continue
        used_sent.add(key)
        answer_uses[c["answer"].lower()] += 1
        per_heading[c["s"]["heading"]] += 1
        chosen.append(c)
        if len(chosen) >= count:
            break

    questions = []
    for i, c in enumerate(chosen):
        s, answer = c["s"], c["answer"]
        wrong = rng.sample(c["distractors"][:8], 3) if len(c["distractors"]) >= 3 else c["distractors"][:3]
        wrong = [_match_case(answer, w) for w in wrong]
        title = doc_title(s["doc"])
        if level == "senior" and i % 2 == 0:
            # Senior: pick the one correct statement (tests reading for exact rules)
            correct = s["text"]
            pattern = re.compile(re.escape(answer), re.I)
            options = [correct] + [pattern.sub(lambda _m, w=w: w, correct, count=1) for w in wrong]
            if len(set(options)) < 4:
                continue
            text = f"According to {title}, which statement is correct?"
            answer_text = correct
        else:
            blanked = re.sub(re.escape(answer), "_____", s["text"], count=1, flags=re.I)
            if "_____" not in blanked:
                continue
            text = f"According to {title}, which option completes this statement?\n“{blanked}”"
            options = [answer] + wrong
            answer_text = answer
        rng.shuffle(options)
        questions.append({
            "text": text, "options": options, "answer_index": options.index(answer_text),
            "source_doc": s["doc"], "source_page": s["page"], "topic": s["heading"][:60], "origin": "local",
        })
    return questions
