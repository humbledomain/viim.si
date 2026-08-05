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
// max_uses is deliberately small: each extra fetch of a multi-megabyte PDF is
// several seconds of wall clock, and unbounded tool loops were the timeout.
function toolsFor(grounded) {
  return [
    {
      type: 'web_fetch_20260209',
      name: 'web_fetch',
      // When the corpus already has the text, one fetch is a revision check at most.
      max_uses: grounded ? 1 : 2,
      max_content_tokens: 60000,
      allowed_domains: ['vdot.virginia.gov', 'virginiadot.org', 'law.lis.virginia.gov'],
      citations: { enabled: true },
    },
    {
      type: 'web_search_20260318',
      name: 'web_search',
      max_uses: 1,
      allowed_domains: ['vdot.virginia.gov', 'virginiadot.org', 'law.lis.virginia.gov'],
    },
  ];
}

export default async function handler(req) {
  if (req.method !== 'POST') return new Response('Method not allowed', { status: 405 });

  const {
    messages,
    system,
    max_tokens = 2048,
    tier = 'strong',
    grounded = false,   // true when the full document text is already in context
    tools = true,
  } = await req.json();

  // Prompt caching: the document text rides in the system prompt. Marking it
  // ephemeral means the second question about the same document skips
  // re-processing those tokens entirely.
  const sysBlocks =
    typeof system === 'string' && system.length > 4000
      ? [{ type: 'text', text: system, cache_control: { type: 'ephemeral' } }]
      : system;

  const chain = TIERS[tier] || TIERS.strong;
  let last = null;

  for (const model of chain) {
    for (let attempt = 0; attempt <= RETRIES_PER_MODEL; attempt++) {
      let upstream;
      try {
        upstream = await fetch('https://api.anthropic.com/v1/messages', {
          method: 'POST',
          headers: {
            'content-type': 'application/json',
            'x-api-key': process.env.ANTHROPIC_API_KEY,
            'anthropic-version': '2023-06-01',
          },
          body: JSON.stringify({
            model,
            max_tokens,
            system: sysBlocks,
            messages,
            stream: true,
            ...(tools ? { tools: toolsFor(grounded) } : {}),
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
      if (upstream.status === 529 || upstream.status === 429) {
        if (attempt < RETRIES_PER_MODEL) await sleep(400);
        continue;
      }
      return new Response(upstream.body, {
        status: upstream.status,
        headers: { 'content-type': 'application/json' },
      });
    }
  }

  return new Response(
    last ? last.body : JSON.stringify({ error: { message: 'Upstream unavailable' } }),
    { status: last ? last.status : 503, headers: { 'content-type': 'application/json' } },
  );
}
