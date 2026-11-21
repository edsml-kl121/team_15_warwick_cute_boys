const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

const window = {};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../realtime.js'), 'utf8'), { window });
const tools = { cards: card => [{ type: card.kind }], waitingMessage: name => name ? `Using ${name}…` : 'On it…' };
const apply = (thread, event) => window.zippyVoiceThread.apply(thread, event, tools);
const newThread = () => ({ messages: [] });

test('what the visitor says becomes one bubble that fills in as they speak', () => {
  const thread = newThread();
  assert.equal(apply(thread, { type: 'user', item_id: 'u1', text: '' }), 'render');
  apply(thread, { type: 'user', item_id: 'u1', text: 'I need' });
  apply(thread, { type: 'user', item_id: 'u1', text: 'I need an eye mask' });
  assert.deepEqual(thread.messages.map(message => [message.role, message.text]), [['user', 'I need an eye mask']]);
});

test('the spoken reply streams as a live reply, then joins the chat with its cards when done', () => {
  const thread = newThread();
  apply(thread, { type: 'user', item_id: 'u1', text: 'I need an eye mask' });
  assert.equal(apply(thread, { type: 'tool', name: 'show_products' }), 'render');
  assert.equal(thread.response.waiting, 'Using show_products…');
  assert.ok(thread.pending, 'the chat shows Zippy is replying');
  assert.equal(apply(thread, { type: 'delta', text: 'Here are ' }), 'stream');
  apply(thread, { type: 'delta', text: 'some masks.' });
  apply(thread, { type: 'card', card: { kind: 'product_compare' } });
  apply(thread, { type: 'quick_replies', options: ['Show more', ''] });
  assert.equal(apply(thread, { type: 'done' }), 'render');
  assert.equal(thread.response, undefined);
  assert.equal(thread.pending, undefined);
  const reply = thread.messages.at(-1);
  assert.deepEqual(JSON.parse(JSON.stringify([reply.role, reply.text, reply.cards, reply.replies])),
    ['assistant', 'Here are some masks.', [{ type: 'product_compare' }], ['Show more']]);
  assert.equal('waiting' in reply, false);
});

test('talking over Zippy keeps the conversation in order', () => {
  const thread = newThread();
  apply(thread, { type: 'user', item_id: 'u1', text: 'How did I sleep?' });
  apply(thread, { type: 'delta', text: 'You slept' });
  apply(thread, { type: 'user', item_id: 'u2', text: 'Actually, what should I eat?' });
  apply(thread, { type: 'done' });
  apply(thread, { type: 'delta', text: 'Try a salad.' });
  apply(thread, { type: 'done' });
  assert.deepEqual(thread.messages.map(message => message.text),
    ['How did I sleep?', 'You slept', 'Actually, what should I eat?', 'Try a salad.']);
});

test('ending the conversation keeps a half-spoken reply and drops bubbles that never got words', () => {
  const thread = newThread();
  apply(thread, { type: 'user', item_id: 'u1', text: 'Hello' });
  apply(thread, { type: 'delta', text: 'Hi the' });
  apply(thread, { type: 'user', item_id: 'u2', text: '' });
  window.zippyVoiceThread.finish(thread);
  assert.deepEqual(thread.messages.map(message => message.text), ['Hello', 'Hi the']);
  assert.equal(thread.pending, undefined);
});
