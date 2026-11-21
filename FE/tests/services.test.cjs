const assert = require('node:assert/strict');
const fs = require('node:fs');
const { test } = require('node:test');
const vm = require('node:vm');

const script = fs.readFileSync(require('node:path').join(__dirname, '../services.js'), 'utf8');

function loadService(fetch) {
  const window = {};
  vm.runInNewContext(script, {
    window, fetch, URL, URLSearchParams, TextDecoder, FormData,
    location: { href: 'https://zippy.example/', protocol: 'https:' },
    document: { querySelector: name => name.includes('zippy-api') ? { content: '/api/' } : null },
  });
  return window.zippyService;
}

test('chat buffers split lines and forwards the backend session and message', async () => {
  const service = loadService(async (url, options) => {
    assert.equal(url.href, 'https://zippy.example/api/chat');
    assert.deepEqual(JSON.parse(options.body), { session_id: 'session-1', message: 'Find a sleep mask' });
    const chunks = ['{"type":"del', 'ta","text":"Result"}\n{"type":"done"}'];
    const stream = new ReadableStream({
      start(controller) {
        for (const text of chunks) controller.enqueue(new TextEncoder().encode(text));
        controller.close();
      },
    });
    return new Response(stream, { headers: { 'content-type': 'application/x-ndjson' } });
  });
  const events = [];
  await service.chat('session-1', 'Find a sleep mask', event => events.push(event.type + ':' + event.text));
  assert.deepEqual(events, ['delta:Result']);
});

test('empty product results have no cards and a price comes from the backend', () => {
  const service = loadService();
  assert.equal(service.cards({ kind: 'product_compare', products: [] }).length, 0);
  const [card] = service.cards({ kind: 'product_compare', products: [
    { item_id: 'fixture-mask', name: 'Fixture mask', price_thb: 321 },
  ] });
  assert.equal(card.productId, 'fixture-mask');
  assert.equal(card.value, '321 THB');
});

test('photo uploads multipart data and returns the saved estimate after progress', async () => {
  const file = new File(['photo'], 'meal.jpg', { type: 'image/jpeg' });
  const service = loadService(async (url, options) => {
    assert.equal(url.href, 'https://zippy.example/api/food-log/photo?session_id=session-1&stream=true');
    assert.equal(options.body.get('file').name, 'meal.jpg');
    return new Response([
      '{"type":"progress","stage":"analyzing"}',
      '{"type":"progress","stage":"saving"}',
      '{"type":"done","meal":{"kcal":350}}',
    ].join('\n'), { headers: { 'content-type': 'application/x-ndjson' } });
  });
  const stages = [];
  const meal = await service.photo(file, 'session-1', event => stages.push(event.stage));
  assert.deepEqual(stages, ['analyzing', 'saving']);
  assert.equal(meal.kcal, 350);
});

test('a truncated stream and backend error reject instead of generating a fallback reply', async () => {
  const headers = { 'content-type': 'application/x-ndjson' };
  const broken = loadService(async () => new Response('{"type":"delta","text":"Partial"}', { headers }));
  await assert.rejects(broken.chat('session-1', 'Hi', () => {}), /interrupted/);
  const failed = loadService(async () => new Response('{"type":"error","message":"Source unavailable"}', { headers }));
  await assert.rejects(failed.chat('session-1', 'Hi', () => {}), /Source unavailable/);
});
