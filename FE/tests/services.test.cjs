const assert = require('node:assert/strict');
const fs = require('node:fs');
const { test } = require('node:test');
const vm = require('node:vm');

const script = fs.readFileSync(require('node:path').join(__dirname, '../services.js'), 'utf8');

function loadService(fetch, { geolocation, href = 'https://zippy.example/' } = {}) {
  const window = {};
  vm.runInNewContext(script, {
    window, fetch, URL, URLSearchParams, TextDecoder, FormData,
    location: { href, protocol: 'https:' },
    navigator: { geolocation },
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

test('meal suggestions request fresh catalog images by ID or saved dish name', () => {
  const service = loadService();
  const meal = { kind: 'meal', dish: 'Chicken & rice', protein_g: 35, kcal: 400, why: 'Fits your protein goal.' };
  const [current] = service.cards({ ...meal, food_id: 'chicken-rice' });
  const [saved] = service.cards(meal);
  assert.equal(current.imageUrl, 'https://zippy.example/api/food-log/catalog-image?food_id=chicken-rice');
  assert.equal(saved.imageUrl, 'https://zippy.example/api/food-log/catalog-image?dish=Chicken+%26+rice');
  assert.equal(current.description, meal.why);
});

test('places cards preserve restaurant photos and work with older results', () => {
  const service = loadService();
  const image_url = 'https://sim.example/static/restaurants/s_easy_health.jpg';
  const image_credit = { representative: true, caption: 'Chicken Caesar salad' };
  const [card] = service.cards({ kind: 'places', places: [
    { name: 'Easy Health', stock_image_url: image_url, stock_image_credit: image_credit, protein_g: 45 },
    { name: 'Older listing' },
  ] });
  assert.equal(card.items[0].imageUrl, image_url);
  assert.equal(card.items[0].imageCredit, image_credit);
  assert.equal(card.items[1].title, 'Older listing');
  assert.equal(card.items[1].imageUrl, undefined);
  const [uploaded] = service.cards({ kind: 'places', places: [
    { name: 'Easy Health', image_url: 'https://photos.example/upload.jpg',
      stock_image_url: image_url, stock_image_credit: image_credit },
  ] });
  assert.equal(uploaded.items[0].imageUrl, 'https://photos.example/upload.jpg');
  assert.equal(uploaded.items[0].imageCredit, undefined);
});

test('only orderable Shopee Food results expose their dish as a checkout action', () => {
  const service = loadService();
  const places = [{ name: 'Easy Health', item_id: 'm_easy_health_5', dish: 'Caesar salad' }];
  const [guest] = service.cards({ kind: 'places', places, orderable: true, location_source: 'current' });
  assert.equal(guest.items[0].orderItemId, 'm_easy_health_5');
  assert.equal(guest.description, 'Near your current location');
  const [demo] = service.cards({ kind: 'places', places, orderable: false, location_source: 'silom' });
  assert.equal(demo.items[0].orderItemId, undefined);
});

test('chat can attach a rounded device location and falls back when access is denied', async () => {
  const service = loadService(async (_url, options) => {
    assert.deepEqual(JSON.parse(options.body), {
      session_id: 'guest', message: 'Find food near me', location: { lat: 13.747, lng: 100.54 },
    });
    return new Response('{"type":"done"}\n', { headers: { 'content-type': 'application/x-ndjson' } });
  }, { geolocation: { getCurrentPosition: ok => ok({ coords: { latitude: 13.74678, longitude: 100.53961 } }) } });
  await service.chat('guest', 'Find food near me', () => {}, await service.currentLocation());

  const blocked = loadService(undefined, { geolocation: { getCurrentPosition: (_ok, fail) => fail() } });
  assert.equal(await blocked.currentLocation(), null);
  const demo = loadService(undefined, { href: 'https://zippy.example/?demo=ploy',
    geolocation: { getCurrentPosition: () => assert.fail('Ploy demo must not request device location') } });
  assert.equal(await demo.currentLocation(), null);
});

test('recommendation references only link to supported Zippy pages', () => {
  const service = loadService();
  const links = service.referenceLinks(['food_log', 'https://example.org', 'profile', 'health_data', 'today']);
  assert.equal(Array.from(links, link => link.href).join(' '), '#food #profile #profile #today');
  assert.equal(links[0].label, 'Food log');
  assert.equal(service.referenceLinks(undefined).length, 0);
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

test('waiting messages follow the tool Zippy is using and fall back to a general one', () => {
  const service = loadService();
  const first = () => 0;
  const last = () => 0.999;
  const general = service.waitingMessage(undefined, first);
  assert.ok(general);
  assert.notEqual(service.waitingMessage('show_products', first), general);
  assert.notEqual(service.waitingMessage('find_similar_dishes', first), service.waitingMessage('show_products', first));
  assert.equal(service.waitingMessage('some_new_tool', first), general);
  assert.notEqual(service.waitingMessage(undefined, last), general, 'the random pick reaches every message');
});

test('the voice address is a WebSocket on the API, carrying the chat and where to search', () => {
  const guest = loadService();
  assert.equal(guest.voiceUrl('chat-1', { lat: 13.72, lng: 100.53 }),
    'wss://zippy.example/api/voice?session_id=chat-1&lat=13.72&lng=100.53');
  assert.equal(guest.voiceUrl('chat-1'), 'wss://zippy.example/api/voice?session_id=chat-1');
});

test('sleep card charts last night and flags a poor night', () => {
  const service = loadService(async () => { throw new Error('offline'); });
  const [card] = service.cards({ kind: 'sleep_insight', minutes: 310, deep_minutes: 58, goal_minutes: 90,
    sleep_goal_minutes: 420, quality: 'poor' });
  assert.equal(card.title, "Last night's sleep");
  assert.equal(card.badge, 'Poor night');
  assert.equal(JSON.stringify(card.timeline.map(part => [part.stage, part.minutes])), '[["deep",58],["other",252]]');
  assert.equal(card.meters.map(meter => meter.met).join(), 'false,false');
  const [staged] = service.cards({ kind: 'sleep_insight', minutes: 300, deep_minutes: 50,
    totals: { deep: 50, rem: 60, light: 185, awake: 5 } });
  assert.equal(staged.timeline.map(part => part.stage).join(), 'deep,rem,light,awake');
});
