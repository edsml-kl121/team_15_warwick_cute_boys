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
  end() { this.onend(); }
}

function startVoice() {
  const window = { SpeechRecognition: FakeRecognition };
  vm.runInNewContext(script, {
    window, document: { documentElement: { lang: 'en' } },
    setTimeout: (...args) => setTimeout(...args), clearTimeout: id => clearTimeout(id),
  });
  const calls = { paused: 0, states: [] };
  const voice = window.createZippyVoice({
    onState: (state, message) => calls.states.push(state),
    onTranscript: () => {},
    onPause: () => { calls.paused += 1; },
  });
  voice.start();
  return { recognition: FakeRecognition.last, calls };
}

test('a pause after speaking signals that the message is ready to send', () => {
  mock.timers.enable({ apis: ['setTimeout'] });
  try {
    const { recognition, calls } = startVoice();
    recognition.hear('book a table');
    mock.timers.tick(1000);
    recognition.hear('book a table for two');
    mock.timers.tick(1000);
    assert.equal(calls.paused, 0, 'still speaking: words kept arriving');
    mock.timers.tick(600);
    assert.equal(calls.paused, 1);
  } finally {
    mock.timers.reset();
  }
});

test('recognition ending on its own after speech also signals ready to send', () => {
  const { recognition, calls } = startVoice();
  recognition.hear('book a table');
  recognition.end();
  assert.equal(calls.paused, 1);
});

test('silence without any words never signals ready to send', () => {
  mock.timers.enable({ apis: ['setTimeout'] });
  try {
    const { recognition, calls } = startVoice();
    mock.timers.tick(5000);
    recognition.end();
    assert.equal(calls.paused, 0);
    assert.equal(calls.states.at(-1), 'idle');
  } finally {
    mock.timers.reset();
  }
});
