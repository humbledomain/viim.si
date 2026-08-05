export const config = {
  runtime: 'edge',
  // Streaming keeps the connection alive; this is the ceiling for the whole turn.
  maxDuration: 120,
};

// Fast model for short lookups, strong model for document analysis. The client
// asks for a tier; the server decides the actual model so it can fall back.
const TIERS = {
  fast:   ['claude-haiku-4-5', 'claude-sonnet-5'],
  strong: ['claude-sonnet-5', 'claude-haiku-4-5'],
};
const RETRIES_PER_MODEL = 1;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Server-side tools, domain-locked to VDOT.
//
// Tool type strings and the beta header must match the API exactly — a wrong
// value returns 400 for the whole request, which is why a tools-free retry
// exists below. web_fetch is beta and needs its header; web_search is GA.
const WEB_FETCH_BETA = 'web-fetch-2025-09-10';

// max_uses is deliberately small: each extra fetch of a multi-megabyte PDF is
// several seconds of wall clock, and unbounded tool loops caused timeouts.
function toolsFor(grounded) {
  return [
    {
      type: 'web_fetch_20250910',
      name: 'web_fetch',
      // When the corpus already has the text, one fetch is a revision check at most.
      max_uses: grounded ? 1 : 2,
      max_content_tokens: 60000,
      allowed_domains: ['vdot.virginia.gov', 'virginiadot.org', 'law.lis.virginia.gov'],
      citations: { enabled: true },
    },
    {
      type: 'web_search_20250305',
      name: 'web_search',
      max_uses: 1,
      allowed_domains: ['vdot.virginia.gov', 'virginiadot.org', 'law.lis.virginia.gov'],
    },
  ];
}

// ---- abuse & cost protection -------------------------------------------
// A public endpoint with your API key behind it is a spending risk. These are
// cheap defences; tune ALLOWED_ORIGINS and the limits for your deployment.
const ALLOWED_ORIGINS = (process.env.ALLOWED_ORIGINS || '')
  .split(',').map(s => s.trim()).filter(Boolean);   // e.g. "https://viim.si,https://www.viim.si"
const SHARED_PASSWORD = process.env.VIIM_PASSWORD || '';  // optional pilot gate
const RATE_MAX = Number(process.env.RATE_MAX || 20);      // requests per window per IP
const RATE_WINDOW_MS = Number(process.env.RATE_WINDOW_MS || 60000);
const MAX_CHARS = Number(process.env.MAX_CHARS || 600000); // whole request body
const MAX_TURNS = Number(process.env.MAX_TURNS || 40);

const hits = new Map();   // per-instance; good enough to blunt casual abuse
function rateLimited(ip) {
  const now = Date.now();
  const rec = hits.get(ip) || { n: 0, t: now };
  if (now - rec.t > RATE_WINDOW_MS) { rec.n = 0; rec.t = now; }
  rec.n++; hits.set(ip, rec);
  if (hits.size > 5000) hits.clear();
  return rec.n > RATE_MAX;
}
const deny = (msg, status) =>
  new Response(JSON.stringify({ error: { message: msg } }), {
    status, headers: { 'content-type': 'application/json' },
  });

export default async function handler(req) {
  if (req.method !== 'POST') return new Response('Method not allowed', { status: 405 });

  if (ALLOWED_ORIGINS.length) {
    const origin = req.headers.get('origin') || '';
    if (origin && !ALLOWED_ORIGINS.includes(origin)) return deny('Origin not allowed', 403);
  }
  if (SHARED_PASSWORD && req.headers.get('x-viim-key') !== SHARED_PASSWORD)
    return deny('This deployment requires an access key', 401);

  const ip = req.headers.get('x-forwarded-for')?.split(',')[0].trim()
    || req.headers.get('x-real-ip') || 'unknown';
  if (rateLimited(ip)) return deny('Too many requests — slow down a moment', 429);

  const raw = await req.text();
  if (raw.length > MAX_CHARS) return deny('Request too large', 413);

  let parsed;
  try { parsed = JSON.parse(raw); } catch { return deny('Bad JSON', 400); }
  if (!Array.isArray(parsed.messages) || !parsed.messages.length)
    return deny('No messages', 400);
  if (parsed.messages.length > MAX_TURNS) parsed.messages = parsed.messages.slice(-MAX_TURNS);

  const {
    messages,
    system,
    max_tokens = 2048,
    tier = 'strong',
    grounded = false,   // true when the full document text is already in context
    tools = true,
  } = parsed;

  // Prompt caching: the document text rides in the system prompt. Marking it
  // ephemeral means the second question about the same document skips
  // re-processing those tokens entirely.
  const sysBlocks =
    typeof system === 'string' && system.length > 4000
      ? [{ type: 'text', text: system, cache_control: { type: 'ephemeral' } }]
      : system;

  const chain = TIERS[tier] || TIERS.strong;
  const cap = Math.min(Number(max_tokens) || 2048, 4096);
  let last = null, lastText = '';

  // useTools flips to false if the API rejects the tool block, so a bad tool
  // definition degrades to a plain answer instead of failing the request.
  let useTools = !!tools;

  for (const model of chain) {
    for (let attempt = 0; attempt <= RETRIES_PER_MODEL + 1; attempt++) {
      let upstream;
      try {
        upstream = await fetch('https://api.anthropic.com/v1/messages', {
          method: 'POST',
          headers: {
            'content-type': 'application/json',
            'x-api-key': process.env.ANTHROPIC_API_KEY,
            'anthropic-version': '2023-06-01',
            ...(useTools ? { 'anthropic-beta': WEB_FETCH_BETA } : {}),
          },
          body: JSON.stringify({
            model,
            max_tokens: cap,
            system: sysBlocks,
            messages,
            stream: true,
            ...(useTools ? { tools: toolsFor(grounded) } : {}),
          }),
        });
      } catch (e) {
        last = null;
        continue;
      }

      if (upstream.ok) {
        return new Response(upstream.body, {
          headers: {
            'content-type': 'text/event-stream',
            'cache-control': 'no-cache, no-transform',
            connection: 'keep-alive',
            'x-accel-buffering': 'no',
            'x-model': model,
          },
        });
      }

      last = upstream;
      lastText = await upstream.text().catch(() => '');

      if (upstream.status === 529 || upstream.status === 429) {
        if (attempt <= RETRIES_PER_MODEL) await sleep(400);
        continue;
      }

      // 400 with tools on is almost always the tool block. Drop it and retry
      // once — an answer without live fetch beats no answer at all.
      if (upstream.status === 400 && useTools) {
        console.error('VIIM: tool block rejected, retrying without tools —', lastText.slice(0, 400));
        useTools = false;
        continue;
      }

      // Surface the real upstream message so failures are debuggable.
      let msg = lastText;
      try { msg = JSON.parse(lastText).error?.message || lastText; } catch {}
      return new Response(JSON.stringify({ error: { message: msg || ('Upstream ' + upstream.status) } }), {
        status: upstream.status,
        headers: { 'content-type': 'application/json' },
      });
    }
  }

  let msg = lastText || 'Upstream unavailable';
  try { msg = JSON.parse(lastText).error?.message || msg; } catch {}
  return new Response(JSON.stringify({ error: { message: msg } }), {
    status: last ? last.status : 503,
    headers: { 'content-type': 'application/json' },
  });
}
