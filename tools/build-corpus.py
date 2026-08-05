#!/usr/bin/env python3
"""
VIIM — corpus builder.

Downloads each document in data/manifest.json, extracts text with page numbers,
splits it into sections, harvests cross-references and auto-tags topics, then
writes:

    data/corpus/<slug>.json     full text + sections, one file per document
    data/search-index.json      compact inverted index for instant client search
    data/manifest.json          enriched in place (xrefs, pages, sha256, text flag)

Why this exists: fetching a 24-page PDF at question time is the single biggest
source of latency. Extract once, ship the text, and the assistant answers from
context instead of the network.

    pip install requests pymupdf
    python3 tools/build-corpus.py                 # everything missing or changed
    python3 tools/build-corpus.py --only IIM-LD-242
    python3 tools/build-corpus.py --force         # re-extract everything
"""
import argparse, hashlib, json, pathlib, re, sys, time
from collections import Counter, defaultdict

import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CORPUS = DATA / "corpus"
UA = {"User-Agent": "VIIM-corpus/2.0 (+public-record indexing)"}
PAUSE = 1.0
MAX_BYTES = 40 * 1024 * 1024

# IIM-LD-242, IIM-S&B-27.14, IIM-TE-384.1 …
XREF_RE = re.compile(r"\bIIM[-\s]?(LD|S&B|SB|TE|TO|ED|TMPD|MD|CD|RW)[-\s]?(\d+)(?:\.(\d+))?\b", re.I)
# 24VAC30-92, 9VAC25-870, 23 CFR 650, §33.2-241
AUTH_RE = re.compile(r"\b(\d+VAC\d+-\d+|\d+\s?CFR\s?§?\s?\d+(?:\.\d+)?|§\s?\d+\.\d+-\d+(?:\.\d+)?)\b", re.I)
# 1.2, 2.3.4, Section 5, Appendix B — used to find section starts
SEC_RE = re.compile(r"^\s*((?:\d+\.){0,3}\d+|Appendix\s+[A-Z]|Section\s+\d+)[\s.:—-]+(\S.{2,90})$")

TOPIC_CUES = {
    "stormwater & drainage": ["stormwater", "ms4", "drainage", "culvert", "bmp", "erosion", "sediment", "hydraulic", "outfall"],
    "environmental": ["nepa", "environmental", "wetland", "permit", "categorical exclusion", "section 106", "hazardous"],
    "structures & bridges": ["bridge", "load rating", "superstructure", "girder", "abutment", "lrfd", "inspection"],
    "traffic & safety": ["guardrail", "signal", "signing", "pavement marking", "crash", "speed", "barrier", "mutcd"],
    "pedestrian & ADA": ["pedestrian", "curb ramp", "ada", "sidewalk", "crosswalk", "accessib"],
    "work zones": ["work zone", "temporary traffic control", "flagger", "lane closure", "rumble strip"],
    "geometrics & design": ["geometric", "cross section", "superelevation", "sight distance", "typical section", "alignment"],
    "right of way": ["right of way", "acquisition", "relocation", "easement", "condemnation"],
    "utilities": ["utility", "utilities", "relocation of utilities", "pole"],
    "materials": ["material", "concrete", "asphalt", "reinforc", "corrosion", "aggregate"],
    "survey & CADD": ["cadd", "survey", "microstation", "openroads", "title sheet", "plan sheet", "uas", "drone"],
    "planning & access": ["access management", "entrance", "subdivision street", "traffic impact", "comprehensive plan"],
    "maintenance": ["maintenance", "resurfacing", "preventive", "asset management"],
    "program delivery": ["locally administered", "agreement", "authorization", "federal aid", "obligation", "invoice"],
}

STOP = set("""a an and are as at be by for from has have if in into is it its of on or that the their there this to was were
will with which when where how what may shall should must not no all any each per than then these those such other""".split())


def slug(doc_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", doc_id.lower()).strip("-")


def get(url: str) -> requests.Response:
    time.sleep(PAUSE)
    r = requests.get(url, headers=UA, timeout=90)
    r.raise_for_status()
    return r


def extract(raw: bytes):
    """Return (pages, meta). pages = [{page, text}]."""
    import fitz
    with fitz.open(stream=raw, filetype="pdf") as doc:
        pages = [{"page": i + 1, "text": p.get_text()} for i, p in enumerate(doc)]
        meta = {"pages": doc.page_count, "pdf_title": (doc.metadata or {}).get("title") or None}
    scanned = sum(1 for p in pages if len(p["text"].strip()) < 40)
    meta["needs_ocr"] = scanned > max(1, len(pages) // 2)
    return pages, meta


def sectionize(pages):
    """Split into sections on numbered headings, keeping the page each starts on."""
    secs, cur = [], {"heading": "Preamble", "page": 1, "text": ""}
    for p in pages:
        for line in p["text"].splitlines():
            m = SEC_RE.match(line.strip())
            if m and len(line.strip()) < 110:
                if cur["text"].strip():
                    secs.append(cur)
                cur = {"heading": f"{m.group(1)} {m.group(2)}".strip(), "page": p["page"], "text": ""}
            else:
                cur["text"] += line + "\n"
    if cur["text"].strip():
        secs.append(cur)
    return secs


def find_xrefs(text: str, self_id: str):
    out = set()
    for m in XREF_RE.finditer(text):
        div = m.group(1).upper().replace("SB", "S&B")
        ref = f"IIM-{div}-{m.group(2)}"
        if ref != self_id:
            out.add(ref)
    return sorted(out)


def find_authority(text: str):
    return sorted({re.sub(r"\s+", " ", m.group(1)).strip() for m in AUTH_RE.finditer(text)})[:25]


def auto_topics(text: str):
    low = text.lower()
    scored = [(t, sum(low.count(c) for c in cues)) for t, cues in TOPIC_CUES.items()]
    return [t for t, n in sorted(scored, key=lambda x: -x[1]) if n >= 3][:4]


def tokenize(text: str):
    return [w for w in re.findall(r"[a-z0-9][a-z0-9\-&.]{1,}", text.lower())
            if w not in STOP and len(w) > 2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="single document id")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    CORPUS.mkdir(parents=True, exist_ok=True)
    man = json.loads((DATA / "manifest.json").read_text())
    docs = man["documents"]
    index = defaultdict(list)   # term -> [[doc_idx, tf], ...]

    for i, doc in enumerate(docs):
        if a.only and doc["id"] != a.only:
            continue
        url = doc.get("pdf_url") or doc.get("url")
        out = CORPUS / f"{slug(doc['id'])}.json"

        if out.exists() and not a.force:
            body = json.loads(out.read_text())
        else:
            if not url or not url.lower().endswith(".pdf"):
                print(f"· {doc['id']:34} landing page only — leaving to live fetch")
                doc["text"] = False
                continue
            try:
                r = get(url)
            except requests.RequestException as e:
                print(f"! {doc['id']:34} {e}")
                doc["text"] = False
                continue
            if len(r.content) > MAX_BYTES:
                print(f"! {doc['id']:34} too large ({len(r.content)//1024//1024} MB)")
                continue
            pages, meta = extract(r.content)
            full = "\n".join(p["text"] for p in pages)
            body = {
                "id": doc["id"], "title": doc["title"], "url": url,
                "sha256": hashlib.sha256(r.content).hexdigest(),
                "pages": meta["pages"], "needs_ocr": meta["needs_ocr"],
                "sections": [{"heading": s["heading"], "page": s["page"], "text": s["text"].strip()}
                             for s in sectionize(pages)],
                "text": full,
            }
            out.write_text(json.dumps(body))
            print(f"✓ {doc['id']:34} {meta['pages']:>3}p  {len(full)//1000:>4}k chars"
                  f"{'  [NEEDS OCR]' if meta['needs_ocr'] else ''}")

        full = body["text"]
        doc["text"] = True
        doc["pages"] = body["pages"]
        doc["sha256"] = body["sha256"]
        doc["sections"] = [{"heading": s["heading"], "page": s["page"]} for s in body["sections"]][:80]
        doc["xrefs"] = find_xrefs(full, doc["id"])
        found_auth = find_authority(full)
        if found_auth:
            doc["authority"] = sorted(set(doc.get("authority", []) + found_auth))[:25]
        auto = auto_topics(full)
        doc["topic"] = sorted(set(doc.get("topic", []) + auto))

        for term, tf in Counter(tokenize(doc["title"] + " " + full[:200000])).items():
            if tf >= 2 or term in doc["id"].lower():
                index[term].append([i, min(tf, 255)])

    # back-links: if A references B, B lists A under referenced_by
    by_id = {d["id"]: d for d in docs}
    for d in docs:
        for ref in d.get("xrefs", []):
            if ref in by_id:
                by_id[ref].setdefault("referenced_by", [])
                if d["id"] not in by_id[ref]["referenced_by"]:
                    by_id[ref]["referenced_by"].append(d["id"])

    man["generated"] = time.strftime("%Y-%m-%d")
    (DATA / "manifest.json").write_text(json.dumps(man, indent=2))

    trimmed = {t: p for t, p in index.items() if len(p) <= len(docs) * 0.6}
    (DATA / "search-index.json").write_text(json.dumps(
        {"docs": [d["id"] for d in docs], "terms": trimmed}, separators=(",", ":")))

    have = sum(1 for d in docs if d.get("text"))
    print(f"\ncorpus: {have}/{len(docs)} documents with full text")
    print(f"search index: {len(trimmed)} terms")
    print("manifest enriched with xrefs, sections, authority citations and auto-topics")


if __name__ == "__main__":
    sys.exit(main())
