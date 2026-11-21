// Live voice conversation with Zippy over WS /voice (OpenAI Realtime on the backend).
// The browser streams the microphone as 24 kHz 16-bit PCM and plays the coach's audio the same way.
(() => {
  const REPLY_EVENTS = new Set(['delta', 'tool', 'card', 'quick_replies']);

  // Turns /voice events into chat messages. Pure, so it can be tested without audio.
  const thread = {
    // Returns 'render' when the message list changed and 'stream' when only the live reply did.
    apply(chat, event, { cards, waitingMessage }) {
      if (event.type === 'user') {
        let message = chat.messages.find(item => item.voiceId === event.item_id);
        if (!message) {
          // They spoke again while Zippy was mid-reply: that reply ends here, so the order stays right.
          if (chat.response) this.finish(chat, { keepSilent: true });
          message = { id: String(chat.messages.length), role: 'user', text: '', voiceId: event.item_id };
          chat.messages.push(message);
        }
        message.text = event.text;
        return 'render';
      }
      if (REPLY_EVENTS.has(event.type)) {
        const started = !chat.response;
        if (started) {
          chat.response = { role: 'assistant', text: '', cards: [], replies: [], waiting: waitingMessage() };
          chat.pending = 'voice';
        }
        const reply = chat.response;
        if (event.type === 'tool' && typeof event.name === 'string') reply.waiting = waitingMessage(event.name);
        if (event.type === 'delta' && typeof event.text === 'string') reply.text += event.text;
        if (event.type === 'card') reply.cards.push(...cards(event.card));
        if (event.type === 'quick_replies' && Array.isArray(event.options)) {
          reply.replies = event.options.filter(text => typeof text === 'string' && text.trim());
        }
        return started ? 'render' : 'stream';
      }
      if (event.type === 'done') {
        this.finish(chat, { keepSilent: true });
        return 'render';
      }
      return null;
    },

    // Moves the live reply into the chat. Bubbles that never received any words are dropped unless kept.
    finish(chat, { keepSilent = false } = {}) {
      const reply = chat.response;
      delete chat.response;
      delete chat.pending;
      if (reply && (reply.text.trim() || reply.cards.length || reply.replies.length)) {
        delete reply.waiting;
        chat.messages.push(reply);
      }
      if (!keepSilent) chat.messages = chat.messages.filter(message => !message.voiceId || message.text.trim());
    },
  };

  // One live conversation. `url` may be async; it is resolved after the audio is set up, inside the tap.
  function createRealtime({ url, onEvent, onState, onEnd }) {
    let socket;
    let stream;
    let playContext;
    let micContext;
    let player;
    let ready = false;
    let stopped = false;

    function release() {
      ready = false;
      stream?.getTracks().forEach(track => track.stop());
      micContext?.close().catch(() => {});
      playContext?.close().catch(() => {});
    }

    function receive(event) {
      if (event.data instanceof ArrayBuffer) {
        player.port.postMessage({ type: 'chunk', payload: event.data }, [event.data]);
        onState('replying');
        return;
      }
      const message = JSON.parse(event.data);
      // Something that might be speech: pause Zippy, keeping the rest of its reply. If it was only noise, carry on;
      // if they said words over Zippy, drop the audio that hasn't played yet.
      if (message.type === 'hold') {
        player.port.postMessage({ type: 'hold' });
        onState('listening');
      }
      if (message.type === 'resume') player.port.postMessage({ type: 'resume' });
      if (message.type === 'interrupted') player.port.postMessage({ type: 'stop' });
      onEvent(message);
    }

    return {
      // Resolves once the backend says the session is ready; rejects if it can't start.
      async start() {
        // Both contexts are created before any await so the tap that opened voice still counts on iPhone.
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        playContext = new AudioContext({ sampleRate: 24000, latencyHint: 'interactive' });
        micContext = new AudioContext({ sampleRate: 24000, latencyHint: 'interactive' });
        await playContext.audioWorklet.addModule('./audio-playback.worklet.js');
        player = new AudioWorkletNode(playContext, 'pcm-playback', { outputChannelCount: [1] });
        player.port.onmessage = event => {
          if (event.data?.type === 'drained' && ready) onState('listening');
          if (event.data?.type === 'playing' && ready) onState('replying');
        };
        player.connect(playContext.destination);

        stream = await navigator.mediaDevices.getUserMedia({
          audio: { channelCount: 1, sampleRate: 24000, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
        await micContext.audioWorklet.addModule('./audio-recorder.worklet.js');
        const recorder = new AudioWorkletNode(micContext, 'pcm-recorder');
        recorder.port.onmessage = event => {
          // An Int16Array of microphone samples; its raw bytes go to the backend once the session is ready.
          if (ready && socket?.readyState === WebSocket.OPEN) socket.send(event.data.buffer);
        };
        micContext.createMediaStreamSource(stream).connect(recorder);
        recorder.connect(micContext.destination); // Keeps the worklet running; it outputs silence.
        await Promise.all([playContext.resume(), micContext.resume()]);

        const address = await url();
        if (stopped) return release();
        socket = new WebSocket(address);
        socket.binaryType = 'arraybuffer';
        await new Promise((resolve, reject) => {
          socket.onerror = () => reject(new Error('Voice couldn’t connect.'));
          socket.onclose = () => reject(new Error('Voice couldn’t connect.'));
          socket.onmessage = event => {
            const message = typeof event.data === 'string' ? JSON.parse(event.data) : null;
            if (message?.type === 'ready') return resolve();
            reject(new Error(message?.message || 'Voice couldn’t start.'));
          };
        });
        ready = true;
        socket.onmessage = receive;
        socket.onerror = null;
        socket.onclose = () => {
          if (stopped) return;
          stopped = true;
          release();
          onEnd();
        };
        onState('listening');
      },

      stop() {
        if (stopped) return;
        stopped = true;
        if (socket) {
          socket.onclose = null;
          socket.close();
        }
        release();
      },
    };
  }

  window.zippyVoiceThread = thread;
  window.createZippyRealtime = createRealtime;
  window.zippyRealtimeSupported = () => Boolean(
    (window.AudioContext || window.webkitAudioContext) && window.AudioWorkletNode && window.WebSocket
    && typeof navigator !== 'undefined' && navigator.mediaDevices?.getUserMedia);
})();
