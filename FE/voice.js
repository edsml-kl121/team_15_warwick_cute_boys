(() => {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const speechErrors = {
    'not-allowed': 'Microphone access was denied. You can still type your message.',
    'audio-capture': 'No microphone was found. You can still type your message.',
    'no-speech': 'I didn’t hear anything. Try again, or type your message.',
    network: 'Speech recognition couldn’t connect. Try again, or type your message.',
  };

  window.createZippyVoice = ({ onState, onTranscript, transcribe }) => {
    let cancel = () => {};
    let finish = () => {};
    let current = 0;

    function recognize(session) {
      const recognition = new SpeechRecognition();
      recognition.lang = document.documentElement.lang || 'en';
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.onstart = () => {
        if (session === current) onState('listening', 'Listening…');
      };
      let heard = false;
      recognition.onresult = ({ results }) => {
        if (session !== current) return;
        const text = Array.from(results, result => result[0].transcript).join(' ').trim();
        heard = Boolean(text);
        onTranscript(text);
      };
      let errorMessage;
      recognition.onerror = ({ error }) => {
        errorMessage = speechErrors[error] || 'Voice input is unavailable. You can still type.';
      };
      recognition.onend = () => {
        if (session === current) {
          onState('idle', errorMessage || (heard ? 'Tap the waveform to send.' : speechErrors['no-speech']));
        }
      };
      cancel = () => recognition.abort();
      finish = () => recognition.stop();
      recognition.start();
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
})();
