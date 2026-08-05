# VIIM — VDOT guidance console

A working reference console for Virginia DOT guidance: **Instructional & Informational Memoranda** (IIM-LD, IIM-S&B, IIM-TE/TO, IIM-ED, IIM-TMPD), the **manuals and standards** (Road Design Manual, Drainage Manual, Road & Bridge Standards and Specifications, Structure & Bridge Manual), the **regulations** (Access Management, SSAR, Land Use Permits), and the **local program** (LAP Manual, LLGs, DM 8-7).

Filter by division, topic, project phase, delivery type or document type. Search full text. Ask. Every answer cites the document, revision, section and page, and links back to VDOT.

> **Unofficial.** Not a VDOT product, not an approval, not engineering judgment. All sources are public record published by VDOT. Confirm the current revision on the official page before relying on anything for design or submittal.

---

## Deploy

1. Unzip, then create the repo (don't upload the zip — GitHub's uploader won't unpack it):
   ```
   git init && git add -A && git commit -m "initial"
   git remote add origin <your-repo-url> && git push -u origin main
   ```
2. Vercel → **Add New → Project → import**. Preset **Other**, no build command, no output directory.
3. **Settings → Environment Variables → `ANTHROPIC_API_KEY`**, then redeploy.
4. The head block already points at `viim.si` — change it if the hostname differs.

Netlify works identically; `netlify.toml` is included.

---

## Build the corpus (this is what makes it fast)

```bash
pip install requests pymupdf
python3 tools/build-manifest.py     # parse VDOT's index PDFs → full document list
python3 tools/build-corpus.py       # download, extract text, tag, cross-reference
```

`build-corpus.py` does the heavy lifting:

- downloads each PDF and records **sha256, page count, ETag**
- extracts text **per page**, splits into **sections with page numbers**
- harvests **cross-references** (`IIM-LD-242` → every memo it cites) and builds **back-links**
- harvests **authority citations** (`24VAC30-92`, `23 CFR 650`, `§33.2-241`)
- **auto-tags topics** from term frequency against a controlled vocabulary
- writes a compact **inverted search index** for instant client-side full-text search
- flags scanned documents that **need OCR**

Weekly change detection:

```bash
python3 tools/build-manifest.py --check   # exits 1 when a revision moved — wire to an alert
```

### Why this is the speed fix

Before: every question fetched a 24-page PDF over the network, then the model read it cold. After: the text ships with the app, the browser hands it to the assistant directly, and `api/chat.js` marks it `cache_control: ephemeral` so repeat questions on the same document skip re-processing those tokens entirely — much faster first token, roughly 90% cheaper on the cached portion. Answers are also cached per document + question for the session. Live `web_fetch` remains as the fallback for anything not yet in the corpus, and for "is there a newer revision?"

---

## Does VDOT have an API?

**For spatial data, yes. For the memoranda, no.**

- **[Virginia Roads](https://www.virginiaroads.org/)** is VDOT's ArcGIS Hub open data portal — every dataset exposes an ArcGIS REST endpoint returning JSON/GeoJSON, no key, no registration. Districts, road inventory, traffic volumes, crashes, Six-Year Improvement Program.
- **[data.virginia.gov](https://data.virginia.gov/)** is CKAN, with its own API over much of the same.
- **IIMs, manuals, LLGs** — no API, no feed, no index endpoint. Just PDFs on a CMS. Hence the scraper.

`tools/virginia-roads.py` is a thin ArcGIS REST client for the spatial side. Service URLs are left blank on purpose — copy them from a dataset page rather than trusting a hardcoded path that may have been republished.

---

## The data model

```json
{
  "id": "IIM-S&B-27",
  "div": "sb",
  "title": "Inventory and Inspection Requirements for Bridges and Large Culverts",
  "kind": "IIM",
  "revision": "27.14",
  "effective": "2025-03-14",
  "status": "current",
  "topic": ["structures & bridges", "maintenance"],
  "phase": ["maintenance"],
  "delivery": ["VDOT-administered"],
  "authority": ["23 CFR 650 Subpart C"],
  "supersedes": [], "superseded_by": [],
  "xrefs": ["IIM-S&B-86"], "referenced_by": ["IIM-S&B-104"],
  "sections": [{ "heading": "3.2 Inspection Intervals", "page": 7 }],
  "pages": 24, "sha256": "…", "text": true,
  "url": "https://www.vdot.virginia.gov/…"
}
```

Facet vocabularies live in `manifest.facets` — **topic** (14 values), **phase** (7), **delivery** (3), **kind** (7). Edit them there and the filter UI follows.

`status` matters: a `voided` or `superseded` document stays in the index so the assistant can tell you a memo was rescinded instead of silently losing it.

---

## Using it

| | |
|---|---|
| `⌘K` / `Ctrl-K` | command palette — jump to any document or division |
| `/` | focus search |
| `esc` | close palette, detail panel, or drawer |
| Topic / Phase / Delivery / Type tabs | multi-select facets, counts update live |
| Document detail (▤ in the header) | sections, cross-reference graph, lineage, authority |
| Section rows | click to ask about that section specifically |

## Editing

- **Catalog & facets** — `data/manifest.json`
- **Assistant behavior** — `BASE_SYS` in `index.html`
- **Quick questions** — the `ASKS` array in `index.html`
- **Brand** — `brand/*.svg`, then `python3 build-icons.py`, then copy `assets/favicon.ico` to root

## Local development

`vercel dev` (or `netlify dev`) with `ANTHROPIC_API_KEY` set. Opening `index.html` from disk renders the UI but the assistant reports the backend offline by design — the key never touches the browser.

## Sources

- [VDOT technical guidance documents](https://www.vdot.virginia.gov/doing-business/technical-guidance-and-support/)
- [Road Design Manual](https://www.vdot.virginia.gov/doing-business/technical-guidance-and-support/technical-guidance-documents/road-design-manual/) · [Road & Bridge Standards](https://www.vdot.virginia.gov/doing-business/technical-guidance-and-support/technical-guidance-documents/road-and-bridge-standards/) · [Road & Bridge Specifications](https://www.vdot.virginia.gov/doing-business/technical-guidance-and-support/technical-guidance-documents/road-and-bridge-specifications/)
- [VDOT Local Assistance](https://www.vdot.virginia.gov/doing-business/for-localities/local-assistance/)
- [Virginia Roads open data](https://www.virginiaroads.org/) · [Virginia Open Data Portal](https://data.virginia.gov/)
