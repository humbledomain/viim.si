# VIIM — VDOT guidance, answered

A working reference console for Virginia DOT guidance: **Instructional & Informational Memoranda** (IIM-LD, IIM-S&B, IIM-TE/TO, IIM-ED, IIM-TMPD), the **manuals, standards and specifications**, the **regulations** (Access Management, SSAR, Land Use Permits), and the **local program** (LAP Manual, LLGs, DM 8-7).

Pick a role, filter the index, ask. Every answer cites the document, revision and section, and links back to VDOT.

> **Unofficial.** Not a VDOT product, not an approval, not engineering judgment. All sources are public record published by VDOT. Confirm the current revision on the official page before relying on anything for design or submittal.

---

## Built for the people who actually deal with this

Pick a role in the top bar and the console retunes — default filters, the four quick questions, and how answers are framed:

| Role | Answers lead with |
|---|---|
| **Locality staff** | Your obligations, VDOT review and approval points, agreements and invoicing, LAP Manual |
| **Consultant** | Design criteria and thresholds, plan-sheet and submittal expectations, the deviation path |
| **Contractor / Inspector** | Field steps and hold points, spec sections, sampling and testing, documentation, change orders |
| **Developer / Permits** | What triggers a requirement, the submittal path, entrance and subdivision-street standards |
| **VDOT staff** | Delegation and approval authority, internal process, which division owns the decision |
| **New to VDOT** | Plain language, acronyms defined on first use, where a document fits and what to read next |

## What it does

- **Search** — ranked full-text across the corpus with highlighted snippets, plus `⌘K` for documents, divisions and acronyms in one box
- **Filter** — topic · phase · delivery · district · type, multi-select with live counts
- **Read** — a context panel with actions, record, clickable classification, section map, cross-reference graph, related guidance, lineage and authority citations
- **Upload** — drag a PDF, image or text file in; it becomes an indexed document you can question and compare against the guidance
- **Compare** — any two documents, requirement by requirement
- **Glossary** — 50 VDOT acronyms, underlined in every answer, hover to define
- **Keep** — threads, pins, recents, role and filters persist across reloads
- **Share** — `viim.si/#doc=IIM-LD-242` deep links; copy-link button
- **Export** — Markdown export and a real print stylesheet with citation, revision, timestamp and disclaimer
- **Keyboard** — `⌘K` search · `/` filter · `J`/`K` move · `↵` open · `esc` back

## Deploy

```
git init && git add -A && git commit -m "initial"
git remote add origin <your-repo-url> && git push -u origin main
```

Vercel → **Add New → Project → import**. Preset **Other**, no build command. Then **Settings → Environment Variables**:

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | **yes** | The API key. Never reaches the browser. |
| `ALLOWED_ORIGINS` | strongly recommended | `https://viim.si,https://www.viim.si` — blocks other sites from using your endpoint |
| `VIIM_PASSWORD` | optional | Shared key for a private pilot; the client sends it as `x-viim-key` |
| `RATE_MAX` / `RATE_WINDOW_MS` | optional | Default 20 requests per minute per IP |
| `MAX_CHARS` / `MAX_TURNS` | optional | Request size and history caps |

**Set `ALLOWED_ORIGINS` before you make the URL public.** A live endpoint with your key behind it is a spending risk, and a monthly spend alert in the Anthropic console is worth five minutes.

## Fill the catalog

`data/manifest.json` ships as a curated seed — **97 documents across 15 divisions**, every entry checked. VDOT publishes several hundred more.

```bash
pip install requests pymupdf
python3 tools/build-manifest.py     # merge VDOT's full published library
python3 tools/build-corpus.py       # download, extract text, sections, cross-references
```

`build-manifest.py` tries three public paths in order — **sitemap XML**, **CMS search API**, **paginated HTML** — because VDOT's listing renders client-side. It preserves every curated facet when merging, and tells you plainly if it comes up short.

`build-corpus.py` is what makes it fast: text ships with the app, so questions skip the network, and `api/chat.js` marks the document block `cache_control: ephemeral` so follow-ups on the same document are dramatically cheaper and quicker.

`.github/workflows/refresh.yml` runs `--check` weekly and opens an issue when a revision moves.

## Server tools

`api/chat.js` enables two Anthropic server tools, domain-locked to VDOT:

| Tool | Type string | Header |
|---|---|---|
| Web fetch | `web_fetch_20250910` | `anthropic-beta: web-fetch-2025-09-10` (beta) |
| Web search | `web_search_20250305` | none (GA) |

These strings must match the API exactly — a wrong value returns **400 for the entire request**. The proxy therefore retries once **without tools** on a 400 and logs the upstream message, so a tool-definition problem degrades to a plain answer instead of a dead end. Real error messages are passed through to the UI rather than a bare status code.

## Speed

Fixed in this build: tool use is capped (2 fetches, 1 search, 60k content tokens) so the model can't chain PDF fetches until the function times out; short questions route to Haiku while document analysis stays on Sonnet; streaming paints once per frame; there's a 100-second client timeout with an honest message; empty responses retry automatically.

## Editing

- **Catalog, facets, divisions** — `data/manifest.json`
- **Glossary** — `data/glossary.json`
- **Roles, prompts, quick questions** — the `ROLES` object at the top of the script in `index.html`
- **Assistant rules** — `SYS_BASE` in `index.html`
- **Brand** — `brand/*.svg`, then `python3 build-icons.py`

## Sources

- [VDOT technical guidance documents](https://www.vdot.virginia.gov/doing-business/technical-guidance-and-support/)
- [VDOT Local Assistance](https://www.vdot.virginia.gov/doing-business/for-localities/local-assistance/)
- [Road Design Manual](https://www.vdot.virginia.gov/doing-business/technical-guidance-and-support/technical-guidance-documents/road-design-manual/) · [Road & Bridge Standards](https://www.vdot.virginia.gov/doing-business/technical-guidance-and-support/technical-guidance-documents/road-and-bridge-standards/) · [Specifications](https://www.vdot.virginia.gov/doing-business/technical-guidance-and-support/technical-guidance-documents/road-and-bridge-specifications/)
- [Virginia Roads open data](https://www.virginiaroads.org/) · [Virginia Open Data Portal](https://data.virginia.gov/)
