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

// The playback worklet, run outside the audio thread with a stand-in for its globals.
function createPlayer() {
  let Processor;
  const posted = [];
  class AudioWorkletProcessor {
    constructor() { this.port = { postMessage: message => posted.push(message.type) }; }
  }
  const context = vm.createContext({
    AudioWorkletProcessor, sampleRate: 24000, registerProcessor: (name, cls) => { Processor = cls; },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../audio-playback.worklet.js'), 'utf8'), context);
  // Audio arrives as the worklet's own ArrayBuffer, as it does in the browser.
  const tone = vm.runInContext('seconds => new Int16Array(24000 * seconds).fill(8192).buffer', context);
  const player = new Processor();
  const send = message => player.port.onmessage({ data: message.seconds ? { type: 'chunk', payload: tone(message.seconds) } : message });
  const play = frames => {
    const out = [];
    for (let i = 0; i < frames; i++) {
      const channel = new Float32Array(128);
      player.process([], [[channel]]);
      out.push(...channel);
    }
    return out;
  };
  return { send, play, posted };
}
const reply = seconds => ({ seconds }); // a steady quarter-level tone

test('a hold pauses Zippy and resume plays the rest of the reply instead of throwing it away', () => {
  const { send, play, posted } = createPlayer();
  send(reply(1));
  assert.ok(play(40).at(-1) > 0.2, 'Zippy is speaking');
  send({ type: 'hold' });
  const held = play(40);
  assert.equal(held.at(-1), 0, 'silent while held');
  assert.ok(!posted.includes('drained'), 'a held reply is not finished');
  send({ type: 'resume' });
  assert.equal(posted.at(-1), 'playing');
  assert.ok(play(40).at(-1) > 0.2, 'the reply carries on');
  play(200);
  assert.equal(posted.at(-1), 'drained', 'and plays to the end');
});

test('stop drops the rest of the reply, even while held', () => {
  const { send, play, posted } = createPlayer();
  send(reply(1));
  play(10);
  send({ type: 'hold' });
  play(10);
  send({ type: 'stop' });
  assert.equal(posted.at(-1), 'drained');
  assert.ok(play(40).every(sample => sample === 0), 'nothing left to play');
  send(reply(0.2));
  assert.ok(play(20).some(sample => sample > 0.2), 'the next reply plays normally');
});
