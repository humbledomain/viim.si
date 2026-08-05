# Corpus

`tools/build-corpus.py` writes one JSON file per document here:

```json
{ "id": "IIM-S&B-27", "title": "...", "url": "...", "sha256": "...",
  "pages": 24, "needs_ocr": false,
  "sections": [{ "heading": "3.2 Inspection Intervals", "page": 7, "text": "..." }],
  "text": "full extracted text" }
```

The browser loads the file for whichever document you select and hands the text
to the assistant, so answers come from context instead of a live PDF fetch.

Not committed by default beyond this note — run the builder to populate.
