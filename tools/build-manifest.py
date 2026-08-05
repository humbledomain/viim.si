#!/usr/bin/env python3
"""
VIIM — manifest builder.

Parses VDOT's published IIM index PDFs into data/manifest.json, resolving each
memorandum to a live URL and recording the revision + effective date so changes
can be detected later.

    pip install requests pymupdf
    python3 tools/build-manifest.py            # full rebuild
    python3 tools/build-manifest.py --check    # change detection only

Nothing here scrapes anything that is not already published for free on
vdot.virginia.gov. Be polite: requests are rate limited.
"""
import argparse, hashlib, json, pathlib, re, sys, time
from datetime import date

import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = ROOT / "cache"
UA = {"User-Agent": "VIIM-manifest/1.0 (+public-record indexing; contact: you@example.com)"}
PAUSE = 1.0  # seconds between requests

# VDOT's CMS exposes its entire guidance library as a paginated listing. This is
# the highest-yield source: titles and canonical URLs come straight out of the
# HTML, no PDF parsing and no slug guessing required.
LISTING = "https://www.vdot.virginia.gov/doing-business/technical-guidance-and-support/technical-guidance-documents/"
LISTING_MAX_PAGES = 40

INDEX_PDFS = {
    "index": "https://www.vdot.virginia.gov/media/vdotvirginiagov/doing-business/technical-guidance-and-support/"
             "technical-guidance-documents/location-and-design/migrated/iim/IIM-INDEX_12_01_2025acc12012025.pdf",
    "changelog": "https://www.vdot.virginia.gov/media/vdotvirginiagov/doing-business/technical-guidance-and-support/"
                 "technical-guidance-documents/location-and-design/migrated/iim/New-and-Revised-IIM_12_08_2025acc12082025.pdf",
}

# IIM-LD-242, IIM-S&B-27.14, IIM-TE-384.1, IIM-TO-99, IIM-ED-1202 ...
ID_RE = re.compile(r"\bIIM[- ]?(LD|S&B|SB|TE|TO|ED|TMPD|MD|CD|RW|LD-RW)[- ]?(\d+)(?:\.(\d+))?\b", re.I)
DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")


def get(url, **kw):
    time.sleep(PAUSE)
    r = requests.get(url, headers=UA, timeout=60, **kw)
    r.raise_for_status()
    return r


def pdf_text(raw: bytes) -> str:
    import fitz  # pymupdf
    with fitz.open(stream=raw, filetype="pdf") as doc:
        return "\n".join(p.get_text() for p in doc)


LINK_RE = re.compile(
    r'<a[^>]+href="(/doing-business/technical-guidance-and-support/technical-guidance-documents/[^"#?]+)"[^>]*>(.*?)</a>',
    re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")


def crawl_listing(max_pages: int = LISTING_MAX_PAGES) -> dict:
    """Walk the CMS listing and pull every guidance document it publishes."""
    found, seen_pages = {}, 0
    for page in range(1, max_pages + 1):
        url = LISTING if page == 1 else f"{LISTING}?page={page}"
        try:
            html = get(url).text
        except requests.RequestException as e:
            print(f"  listing page {page}: {e}")
            break
        hits = LINK_RE.findall(html)
        fresh = 0
        for href, label in hits:
            title = re.sub(r"\s+", " ", TAG_RE.sub("", label)).strip()
            if not title or len(title) < 4:
                continue
            full = "https://www.vdot.virginia.gov" + href
            if full.rstrip("/") == LISTING.rstrip("/"):
                continue
            m = ID_RE.search(title)
            if m:
                div = m.group(1).upper().replace("SB", "S&B")
                doc_id = f"IIM-{div}-{m.group(2)}"
                rev = f"{m.group(2)}.{m.group(3)}" if m.group(3) else None
                clean = re.sub(r"^\s*IIM[-\s]?[A-Z&]+[-\s]?[\d.]+\s*[:–—-]?\s*", "", title)
            else:
                doc_id, rev, clean = title, None, title
                div = None
            if doc_id in found and found[doc_id].get("url"):
                continue
            found[doc_id] = {
                "id": doc_id,
                "div": (div or "").lower().replace("&", "") or None,
                "title": clean or title,
                "revision": rev,
                "url": full,
                "kind": "IIM" if m else "guide",
            }
            fresh += 1
        seen_pages = page
        print(f"  listing page {page}: {len(hits)} links, {fresh} new  (running total {len(found)})")
        if not hits:
            break
    print(f"crawled {seen_pages} listing pages -> {len(found)} documents")
    return found


def parse_index(text: str) -> dict:
    """Pull every IIM id out of the index, keeping the highest revision seen."""
    found = {}
    for line in text.splitlines():
        m = ID_RE.search(line)
        if not m:
            continue
        div = m.group(1).upper().replace("SB", "S&B")
        num, rev = m.group(2), m.group(3)
        doc_id = f"IIM-{div}-{num}"
        title = ID_RE.sub("", line).strip(" .\t-–—")
        d = DATE_RE.search(line)
        eff = None
        if d:
            mm, dd, yy = d.groups()
            yy = int(yy) + (2000 if len(yy) == 2 else 0)
            try:
                eff = date(int(yy), int(mm), int(dd)).isoformat()
            except ValueError:
                pass
        prev = found.get(doc_id, {})
        rev_full = f"{num}.{rev}" if rev else prev.get("revision")
        found[doc_id] = {
            "id": doc_id,
            "div": div.lower().replace("&", ""),
            "title": title or prev.get("title", ""),
            "revision": rev_full,
            "effective": eff or prev.get("effective"),
        }
    return found


def resolve_url(doc_id: str, title: str) -> str | None:
    """VDOT's CMS uses a predictable slug for current documents."""
    slug_id = doc_id.lower().replace("&", "").replace(" ", "-")
    slug_title = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:90]
    base = "https://www.vdot.virginia.gov/doing-business/technical-guidance-and-support/technical-guidance-documents/"
    for candidate in (f"{base}{slug_id}-{slug_title}/", f"{base}{slug_id}/"):
        try:
            time.sleep(PAUSE)
            if requests.head(candidate, headers=UA, timeout=30, allow_redirects=True).status_code == 200:
                return candidate
        except requests.RequestException:
            pass
    return None


def fingerprint(url: str) -> dict:
    """Cheap change detection: conditional GET metadata + content hash."""
    try:
        r = get(url)
    except requests.RequestException as e:
        return {"status": "unreachable", "error": str(e)}
    return {
        "sha256": hashlib.sha256(r.content).hexdigest(),
        "etag": r.headers.get("ETag"),
        "last_modified": r.headers.get("Last-Modified"),
        "bytes": len(r.content),
    }


def build():
    CACHE.mkdir(exist_ok=True)

    print("crawling the VDOT guidance listing …")
    docs = crawl_listing()

    print("\nparsing the IIM index PDFs for revisions and dates …")
    for name, url in INDEX_PDFS.items():
        try:
            raw = get(url).content
        except requests.RequestException as e:
            print(f"  {name}: {e}")
            continue
        (CACHE / f"{name}.pdf").write_bytes(raw)
        for doc_id, rec in parse_index(pdf_text(raw)).items():
            if doc_id in docs:
                # listing wins on URL and title; the index PDF wins on revision/date
                docs[doc_id]["revision"] = rec.get("revision") or docs[doc_id].get("revision")
                docs[doc_id]["effective"] = rec.get("effective") or docs[doc_id].get("effective")
            else:
                docs[doc_id] = rec
    print(f"\ntotal: {len(docs)} documents")

    old = json.loads((DATA / "manifest.json").read_text()) if (DATA / "manifest.json").exists() else {}
    divisions = old.get("divisions", [])

    # preserve hand-curated facets from the existing manifest
    curated = {d["id"]: d for d in old.get("documents", [])}
    facet_keys = ("topic", "phase", "delivery", "kind", "authority", "note",
                  "status", "supersedes", "superseded_by")

    out = []
    for doc_id, rec in sorted(docs.items()):
        if not rec.get("url"):
            rec["url"] = resolve_url(doc_id, rec["title"])
        prev = curated.get(doc_id)
        if prev:
            for k in facet_keys:
                if prev.get(k) and not rec.get(k):
                    rec[k] = prev[k]
        rec = {k: v for k, v in rec.items() if v is not None}
        out.append(rec)
        print(f"  {doc_id:16} {rec.get('revision') or '-':8} {(rec['url'] or 'unresolved')[:70]}")

    manifest = {
        "generated": date.today().isoformat(),
        "schema": 2,
        "source_indexes": list(INDEX_PDFS.values()) + [LISTING],
        "facets": old.get("facets", {}),
        "divisions": divisions,
        "documents": out,
    }
    (DATA / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nwrote data/manifest.json — {len(out)} documents")


def check():
    """Re-parse the indexes and report anything whose revision moved."""
    man = json.loads((DATA / "manifest.json").read_text())
    known = {d["id"]: d for d in man["documents"]}
    fresh = crawl_listing()
    for name, url in INDEX_PDFS.items():
        try:
            for k, v in parse_index(pdf_text(get(url).content)).items():
                if k in fresh:
                    fresh[k]["revision"] = v.get("revision") or fresh[k].get("revision")
                else:
                    fresh[k] = v
        except requests.RequestException:
            pass

    added = [k for k in fresh if k not in known]
    revised = [k for k in fresh if k in known and fresh[k]["revision"] != known[k].get("revision")]
    missing = [k for k in known if k not in fresh]

    for label, items in (("NEW", added), ("REVISED", revised), ("GONE (check voided list)", missing)):
        if items:
            print(f"\n{label}: {len(items)}")
            for k in items:
                if label == "REVISED":
                    print(f"  {k}: {known[k].get('revision')} -> {fresh[k]['revision']}")
                else:
                    print(f"  {k}")
    if not (added or revised or missing):
        print("no changes since last build")
    return 1 if (added or revised) else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report changes without rewriting the manifest")
    a = ap.parse_args()
    sys.exit(check() if a.check else build())
