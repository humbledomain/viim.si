# VIIM — VDOT guidance console

A working reference console for Virginia DOT guidance: **Instructional & Informational Memoranda** (IIM-LD, IIM-S&B, IIM-TE/TO, IIM-ED, IIM-TMPD) plus the **Locally Administered Projects (LAP) Manual**, **Letters to Local Governments (LLGs)** and **Department Memoranda**.

Pick a division on the rail, pick a document from the index, ask. Every answer is produced by **fetching the actual document from vdot.virginia.gov at question time** and citing what it retrieved — document ID, revision, section, link.

> **Unofficial.** This is not a VDOT product and not an approval, a design decision, or engineering judgment. All source documents are public record published by VDOT; always confirm the current revision on the official page before relying on anything for design or submittal.

---

## Deploy: GitHub → Vercel

1. **Unzip and create a repo** (don't upload the zip itself — GitHub's web uploader won't unpack it):
   ```
   git init && git add -A && git commit -m "initial"
   git remote add origin <your-repo-url>
   git push -u origin main
   ```
2. On Vercel: **Add New → Project → import the repo.** Framework preset **Other**, no build command, no output directory.
3. **Settings → Environment Variables → add `ANTHROPIC_API_KEY`**, then redeploy. Without it the console loads but the assistant reports the backend offline.
4. Add the domain (`viim.si`), then replace every `DOMAIN` in `index.html`'s head with it so link previews resolve.
5. Paste the live URL into Slack or iMessage to confirm the share card renders.

Netlify works too — `netlify.toml` is included; same environment variable.

---

## How grounding works

`api/chat.js` enables two Anthropic server tools, **domain-locked to VDOT**:

```js
allowed_domains: ['vdot.virginia.gov', 'virginiadot.org', 'law.lis.virginia.gov']
```

- `web_fetch_20260209` — pulls the memorandum itself, with citations enabled.
- `web_search_20260318` — finds the current page when a stored URL has gone stale.

The system prompt forbids answering substantive requirements from memory, forbids inventing IIM numbers, revisions or sections, and requires the revision and effective date actually observed. In this domain a plausible fabrication is worse than an admission of uncertainty — the prompt says so explicitly.

The proxy also retries on 529/429 and falls back from `claude-sonnet-5` to `claude-haiku-4-5` so capacity blips don't surface as errors.

---

## The index

`data/manifest.json` drives the left panel. The shipped file is a **verified seed** — roughly twenty documents whose IDs, titles and URLs were confirmed against VDOT — not the complete set. The real index is built by:

```bash
pip install requests pymupdf
python3 tools/build-manifest.py          # parse VDOT's index PDFs → data/manifest.json
python3 tools/build-manifest.py --check  # report new / revised memoranda, exit 1 if any
```

It parses the two authoritative sources — the **IIM Index** PDF and the **New and Revised IIM** changelog — extracts every ID, revision and effective date, then resolves each to a live URL by probing VDOT's slug pattern.

**Document record:**

```json
{ "id": "IIM-S&B-27", "div": "sb",
  "title": "Inventory and Inspection Requirements for Bridges and Large Culverts",
  "revision": "27.14", "effective": "2025-03-14",
  "url": "https://www.vdot.virginia.gov/..." }
```

**Keeping it current.** Run `--check` on a weekly cron. It re-parses the index PDFs and diffs revision numbers, so it catches renumbering and new issuances that a URL-only check would miss. Wire the non-zero exit to an alert. VDOT also publishes a voided list — a document that disappears from the index should be marked `voided`, not deleted, so the assistant can say a memo was rescinded instead of silently losing it.

**Going further.** For a persistent corpus rather than live fetches, extend the builder to download each PDF, hash it, extract text with PyMuPDF (watch for scanned pages needing OCR), and keep page numbers in chunk metadata so citations can read "IIM-LD-242 rev 6, p. 4." Retrieval plus prompt caching is much cheaper than fetching on every question.

---

## Editing

- **Divisions** — the `divisions` array in `data/manifest.json` (code, label, hub URL, scope blurb shown in the panel).
- **Assistant behavior** — `BASE_SYS` in `index.html`.
- **The four quick questions** — the `ASKS` array in `index.html`.
- **Brand** — edit `brand/*.svg`, re-run `python3 build-icons.py` (needs `cairosvg` + `pillow`), copy `assets/favicon.ico` to the root.

## Local development

`vercel dev` (or `netlify dev`) with `ANTHROPIC_API_KEY` in your environment. Opening `index.html` from disk renders the interface, but the assistant will report the backend offline by design — the key never touches the browser.

## Sources

- [VDOT technical guidance documents](https://www.vdot.virginia.gov/doing-business/technical-guidance-and-support/)
- [VDOT Local Assistance](https://www.vdot.virginia.gov/doing-business/for-localities/local-assistance/)
- [IIM Index (PDF)](https://www.vdot.virginia.gov/media/vdotvirginiagov/doing-business/technical-guidance-and-support/technical-guidance-documents/location-and-design/migrated/iim/IIM-INDEX_12_01_2025acc12012025.pdf)
- [New and Revised IIM (PDF)](https://www.vdot.virginia.gov/media/vdotvirginiagov/doing-business/technical-guidance-and-support/technical-guidance-documents/location-and-design/migrated/iim/New-and-Revised-IIM_12_08_2025acc12082025.pdf)
