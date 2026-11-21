const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { test, mock } = require('node:test');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '../voice.js'), 'utf8');

// Stands in for the browser's SpeechRecognition; the test drives its events.
class FakeRecognition {
  constructor() { FakeRecognition.last = this; this.stopped = false; }
  start() { this.onstart?.(); }
  stop() { this.stopped = true; }
  abort() {}
  hear(text) { this.onresult({ results: [[{ transcript: text }]] }); }
  hearFinal(text) { this.onresult({ results: [Object.assign([{ transcript: text }], { isFinal: true })] }); }
  fail(error) { this.onerror({ error }); }
  end() { this.onend(); }
}

function startVoice() {
  const window = { SpeechRecognition: FakeRecognition };
  vm.runInNewContext(script, {
    window, document: { documentElement: { lang: 'en' } },
    setTimeout: (...args) => setTimeout(...args), clearTimeout: id => clearTimeout(id),
  });
  const calls = { paused: 0, states: [], transcript: '' };
  const voice = window.createZippyVoice({
    onState: (state, message) => calls.states.push(state),
    onTranscript: text => { calls.transcript = text; },
    onPause: () => { calls.paused += 1; },
  });
  voice.start();
  return { voice, recognition: FakeRecognition.last, calls };
}

function withTimers(run) {
  mock.timers.enable({ apis: ['setTimeout'] });
  try {
    run();
  } finally {
    mock.timers.reset();
  }
}

test('a pause after speaking signals that the message is ready to send', () => withTimers(() => {
  const { recognition, calls } = startVoice();
  recognition.hear('book a table');
  mock.timers.tick(2000);
  recognition.hear('book a table for two');
  mock.timers.tick(2000);
  assert.equal(calls.paused, 0, 'a two-second pause to think is not the end of the message');
  mock.timers.tick(600);
  assert.equal(calls.paused, 1);
}));

test('recognition ending on its own after speech keeps listening and keeps the words', () => withTimers(() => {
  const { recognition, calls } = startVoice();
  recognition.hear('book a table');
  recognition.end();
  assert.equal(calls.paused, 0, 'Safari ended recognition, not the speaker');
  assert.notEqual(FakeRecognition.last, recognition, 'a fresh recognition picks up listening');
  assert.notEqual(calls.states.at(-1), 'idle');
  FakeRecognition.last.hear('for two');
  assert.equal(calls.transcript, 'book a table for two');
}));

test('silence after recognition restarts still sends once the pause elapses', () => withTimers(() => {
  const { recognition, calls } = startVoice();
  recognition.hear('book a table');
  mock.timers.tick(1000);
  recognition.end();
  assert.equal(calls.paused, 0);
  mock.timers.tick(1600);
  assert.equal(calls.paused, 1, 'the pause counts from the last words, across the restart');
}));

test('a no-speech error after the speaker has already talked does not drop their words', () => withTimers(() => {
  const { recognition, calls } = startVoice();
  recognition.hear('book a table');
  recognition.end();
  FakeRecognition.last.fail('no-speech');
  FakeRecognition.last.end();
  assert.notEqual(calls.states.at(-1), 'idle');
  mock.timers.tick(2500);
  assert.equal(calls.paused, 1);
  assert.equal(calls.transcript, 'book a table');
}));

test('finishing the message stops recognition instead of restarting it', () => {
  const { voice, recognition, calls } = startVoice();
  recognition.hear('book a table');
  voice.stop();
  assert.ok(recognition.stopped);
  recognition.end();
  assert.equal(FakeRecognition.last, recognition);
  assert.equal(calls.states.at(-1), 'idle');
});

test('silence without any words never signals ready to send', () => withTimers(() => {
  const { recognition, calls } = startVoice();
  mock.timers.tick(5000);
  recognition.end();
  assert.equal(calls.paused, 0);
  assert.equal(calls.states.at(-1), 'idle');
}));

test('a finished sentence sends almost immediately instead of after the full wait', () => withTimers(() => {
  const { recognition, calls } = startVoice();
  recognition.hearFinal('book a table for two');
  assert.equal(calls.paused, 0);
  mock.timers.tick(400);
  assert.equal(calls.paused, 1, 'sent as soon as the speaker stopped');
}));

function startSpeaker() {
  const window = {};
  vm.runInNewContext(script, { window, document: { documentElement: { lang: 'en' } }, setTimeout, clearTimeout });
  const spoken = [];
  const utterances = [];
  const synth = {
    speak: utterance => { spoken.push(utterance.text); utterances.push(utterance); },
    cancel: () => spoken.push('<stopped>'),
  };
  function Utterance(text) { this.text = text; }
  return { speaker: window.createZippySpeaker({ synth, Utterance }), spoken, utterances };
}

test('replies are read aloud a sentence at a time as they stream, without markdown', () => {
  const { speaker, spoken } = startSpeaker();
  speaker.feed('Ploy, try **grilled chicken');
  assert.deepEqual(spoken, [], 'no finished sentence yet');
  speaker.feed(' salad**. Easy Health is 0.3 km');
  assert.deepEqual(spoken, ['Ploy, try grilled chicken salad.'], 'decimals do not end a sentence');
  speaker.feed(' away.');
  speaker.finish();
  assert.deepEqual(spoken, ['Ploy, try grilled chicken salad.', 'Easy Health is 0.3 km away.']);
});

test('stopping the speaker drops unread text', () => {
  const { speaker, spoken } = startSpeaker();
  speaker.feed('Half a sentence');
  speaker.cancel();
  speaker.finish();
  assert.deepEqual(spoken, ['<stopped>']);
});

test('the speaker says when it has finished reading the reply aloud', () => {
  const { speaker, utterances } = startSpeaker();
  let done = 0;
  speaker.feed('First sentence. Second');
  speaker.finish(() => { done += 1; });
  assert.equal(done, 0, 'still speaking');
  utterances[0].onend();
  assert.equal(done, 0, 'one sentence left');
  utterances[1].onend();
  assert.equal(done, 1);
});

test('a reply with nothing to read counts as finished straight away', () => {
  const { speaker } = startSpeaker();
  let done = 0;
  speaker.finish(() => { done += 1; });
  assert.equal(done, 1);
});

test('interrupting the speaker never reports it as finished, even when old sentences end late', () => {
  const { speaker, utterances } = startSpeaker();
  let done = 0;
  speaker.feed('Some words. More words.');
  speaker.finish(() => { done += 1; });
  speaker.cancel();
  utterances.forEach(utterance => utterance.onend?.());
  assert.equal(done, 0);
});
