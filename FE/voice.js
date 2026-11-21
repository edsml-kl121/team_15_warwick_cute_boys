(() => {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const speechErrors = {
    'not-allowed': 'Microphone access was denied. You can still type your message.',
    'audio-capture': 'No microphone was found. You can still type your message.',
    'no-speech': 'I didn’t hear anything. Try again, or type your message.',
    network: 'Speech recognition couldn’t connect. Try again, or type your message.',
  };

  // How long the speaker must pause after their last words before the message counts as finished.
  const PAUSE_MS = 2500;
  // Once the browser marks the words as a finished sentence (Chrome does; Safari often doesn't), send almost
  // at once. The short buffer only catches the speaker carrying straight on.
  const FINAL_PAUSE_MS = 300;

  window.createZippyVoice = ({ onState, onTranscript, onPause, transcribe }) => {
    let cancel = () => {};
    let finish = () => {};
    let current = 0;

    function recognize(session) {
      let text = '';
      let pauseTimer;
      let stopping = false;

      function listen() {
        const recognition = new SpeechRecognition();
        recognition.lang = document.documentElement.lang || 'en';
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.onstart = () => {
          if (session === current) onState('listening', 'Listening… I’ll send when you pause.');
        };
        const earlier = text;
        recognition.onresult = ({ results }) => {
          if (session !== current) return;
          const latest = Array.from(results, result => result[0].transcript).join(' ').trim();
          text = [earlier, latest].filter(Boolean).join(' ');
          onTranscript(text);
          clearTimeout(pauseTimer);
          const finished = Boolean(results[results.length - 1]?.isFinal);
          if (text) pauseTimer = setTimeout(() => { if (session === current) onPause?.(); }, finished ? FINAL_PAUSE_MS : PAUSE_MS);
        };
        let errorMessage;
        recognition.onerror = ({ error }) => {
          // Words heard before a restart still count, so silence afterwards is not "no speech".
          if (error === 'no-speech' && text) return;
          errorMessage = speechErrors[error] || 'Voice input is unavailable. You can still type.';
        };
        recognition.onend = () => {
          if (session !== current) return clearTimeout(pauseTimer);
          // Safari on iPhone ends recognition by itself after a short silence, even in continuous mode.
          // Keep listening; the pause timer keeps running and still sends the message.
          if (!stopping && text && !errorMessage) {
            try {
              return listen();
            } catch { /* Send what was heard instead. */ }
          }
          clearTimeout(pauseTimer);
          if (text && !errorMessage) onPause?.();
          onState('idle', errorMessage || (text ? 'Tap the waveform to send.' : speechErrors['no-speech']));
        };
        recognition.start();
        cancel = () => { clearTimeout(pauseTimer); recognition.abort(); };
        finish = () => { stopping = true; recognition.stop(); };
      }

      listen();
    }

    async function record(session) {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const release = () => stream.getTracks().forEach(track => track.stop());
      if (session !== current) return release();
      let recorder;
      try {
        recorder = new MediaRecorder(stream);
      } catch (error) {
        release();
        throw error;
      }
      const chunks = [];
      let timer;
      recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
      recorder.onstop = async () => {
        clearTimeout(timer);
        release();
        if (session !== current) return;
        onState('transcribing', 'Turning your recording into text…');
        try {
          const blob = new Blob(chunks, { type: recorder.mimeType });
          const text = blob.size ? await transcribe(blob) : '';
          if (session !== current) return;
          if (text) onTranscript(text);
          onState('idle', text ? 'Tap the waveform to send.' : speechErrors['no-speech']);
        } catch {
          if (session === current) onState('idle', 'Transcription is unavailable. You can still type.');
        }
      };
      recorder.onerror = () => {
        clearTimeout(timer);
        release();
        if (session === current) onState('idle', 'Recording stopped. You can still type.');
      };
      finish = () => { if (recorder.state === 'recording') recorder.stop(); };
      cancel = () => {
        clearTimeout(timer);
        finish();
        release();
      };
      try {
        recorder.start();
        onState('listening', 'Recording… tap the waveform when you’re done.');
        timer = setTimeout(finish, 30000);
      } catch (error) {
        release();
        throw error;
      }
    }

    return {
      async start() {
        const session = ++current;
        onState('starting', 'Opening microphone…');
        try {
          if (SpeechRecognition) {
            recognize(session);
          } else if (transcribe && navigator.mediaDevices?.getUserMedia && window.MediaRecorder) {
            await record(session);
          } else {
            onState('idle', 'Voice input is unavailable in this browser. You can still type.');
          }
        } catch (error) {
          if (session !== current) return;
          onState('idle', error.name === 'NotAllowedError' ? speechErrors['not-allowed'] : 'Couldn’t open the microphone. You can still type.');
        }
      },
      stop() {
        onState('transcribing', 'Finishing your transcript…');
        try {
          finish();
        } catch {
          onState('idle', 'Couldn’t finish recording. Try again, or type your message.');
        }
      },
      cancel() {
        current++;
        try { cancel(); } catch { /* The browser may have already stopped capture. */ }
        cancel = () => {};
        finish = () => {};
      },
    };
  };

  // Reads Zippy's reply aloud with the browser's own voice, a sentence at a time as the text streams in.
  window.createZippySpeaker = ({ synth = window.speechSynthesis, Utterance = window.SpeechSynthesisUtterance } = {}) => {
    let pending = '';
    let speaking = 0;
    let onDone = null;
    // Cancelling bumps the generation, so sentences from an interrupted reply can't finish the next one.
    let generation = 0;

    function settle() {
      if (onDone && speaking === 0) {
        const done = onDone;
        onDone = null;
        done();
      }
    }

    function say(text, volume = 1) {
      const words = text.replace(/[*_`#>~]/g, '').replace(/\s+/g, ' ').trim();
      if ((!words && volume) || !synth || !Utterance) return;
      const utterance = new Utterance(words);
      utterance.lang = 'en-US';
      utterance.volume = volume;
      if (volume) {
        const mine = generation;
        speaking += 1;
        utterance.onend = utterance.onerror = () => {
          if (mine !== generation) return;
          speaking = Math.max(0, speaking - 1);
          settle();
        };
      }
      synth.speak(utterance);
    }

    return {
      feed(text) {
        pending += text;
        // A sentence ends at . ! ? or … followed by a space, so "0.3 km" stays whole.
        const ends = [...pending.matchAll(/[.!?…](?=\s)/g)];
        if (!ends.length) return;
        const cut = ends.at(-1).index + 1;
        say(pending.slice(0, cut));
        pending = pending.slice(cut);
      },
      // onDone runs once everything has been spoken, so a conversation can start listening again.
      finish(done) {
        say(pending);
        pending = '';
        onDone = done || null;
        settle();
      },
      cancel() {
        pending = '';
        onDone = null;
        speaking = 0;
        generation += 1;
        synth?.cancel();
      },
      // iPhone Safari only speaks after a tap, so a silent utterance during the tap allows later replies.
      unlock() {
        say('', 0);
      },
    };
  };
})();
