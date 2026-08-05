export const config = { runtime: 'edge' };

// Primary model first; fall back if Anthropic reports overload (529) or rate limit (429).
const MODELS = ['claude-sonnet-5', 'claude-haiku-4-5'];
const RETRIES_PER_MODEL = 2;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Server-side tools. web_fetch is scoped to VDOT so the assistant can pull the
// actual memorandum text instead of answering from memory.
const TOOLS = [
  {
    type: 'web_fetch_20260209',
    name: 'web_fetch',
    max_uses: 6,
    allowed_domains: ['vdot.virginia.gov', 'virginiadot.org', 'law.lis.virginia.gov'],
    citations: { enabled: true },
  },
  {
    type: 'web_search_20260318',
    name: 'web_search',
    max_uses: 4,
    allowed_domains: ['vdot.virginia.gov', 'virginiadot.org', 'law.lis.virginia.gov'],
  },
];

export default async function handler(req) {
  if (req.method !== 'POST') return new Response('Method not allowed', { status: 405 });
  const { messages, system, max_tokens = 3072, tools = true } = await req.json();

  // Prompt caching: the system prompt carries the full document text when the
  // corpus has it. Marking it ephemeral means repeat questions on the same
  // document skip re-processing those tokens — much faster first token, ~90%
  // cheaper on the cached portion. Anthropic requires a minimum block size, so
  // only cache when it is actually worth it.
  const sysBlocks =
    typeof system === 'string' && system.length > 4000
      ? [{ type: 'text', text: system, cache_control: { type: 'ephemeral' } }]
      : system;

  let last = null;

  for (const model of MODELS) {
    for (let attempt = 0; attempt <= RETRIES_PER_MODEL; attempt++) {
      const upstream = await fetch('https://api.anthropic.com/v1/messages', {
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
          ...(tools ? { tools: TOOLS } : {}),
        }),
      });

      if (upstream.ok) {
        return new Response(upstream.body, {
          headers: {
            'content-type': 'text/event-stream',
            'cache-control': 'no-cache',
            connection: 'keep-alive',
            'x-model': model,
          },
        });
      }

      last = upstream;

      if (upstream.status === 529 || upstream.status === 429) {
        if (attempt < RETRIES_PER_MODEL) await sleep(500 * (attempt + 1));
        continue;
      }

      return new Response(upstream.body, {
        status: upstream.status,
        headers: { 'content-type': 'application/json' },
      });
    }
  }

  return new Response(last ? last.body : JSON.stringify({ error: { message: 'Overloaded' } }), {
    status: last ? last.status : 529,
    headers: { 'content-type': 'application/json' },
  });
}
