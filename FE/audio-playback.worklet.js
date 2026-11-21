// Based on openai-agents-python examples/realtime/app/static/audio-playback.worklet.js (MIT License), with
// `hold` and `resume` added: a hold fades Zippy out and keeps the rest of its reply until resume or stop.
// Runs in the browser's audio thread: 24 kHz 16-bit PCM in/out.
class PCMPlaybackProcessor extends AudioWorkletProcessor {
    constructor() {
        super();

        this.buffers = [];
        this.currentBuffer = null;
        this.currentIndex = 0;
        this.isCurrentlyPlaying = false;
        this.fadeSamples = Math.round(sampleRate * 0.02);
        this.held = false;
        this.gain = 1;

        this.port.onmessage = (event) => {
            const message = event.data;
            if (!message || typeof message !== 'object') return;

            if (message.type === 'chunk') {
                const payload = message.payload;
                if (!(payload instanceof ArrayBuffer)) {
                    return;
                }

                const int16Data = new Int16Array(payload);
                if (int16Data.length === 0) {
                    return;
                }

                const scale = 1 / 32768;
                const floatData = new Float32Array(int16Data.length);
                for (let i = 0; i < int16Data.length; i++) {
                    floatData[i] = Math.max(-1, Math.min(1, int16Data[i] * scale));
                }

                if (!this.hasPendingAudio()) {
                    const fadeSamples = Math.min(this.fadeSamples, floatData.length);
                    for (let i = 0; i < fadeSamples; i++) {
                        const gain = fadeSamples <= 1 ? 1 : (i / fadeSamples);
                        floatData[i] *= gain;
                    }
                }

                this.buffers.push(floatData);

            } else if (message.type === 'hold') {
                this.held = true;

            } else if (message.type === 'resume') {
                this.held = false;
                this.port.postMessage({ type: this.hasPendingAudio() ? 'playing' : 'drained' });

            } else if (message.type === 'stop') {
                this.reset();
                this.port.postMessage({ type: 'drained' });

            } else if (message.type === 'config') {
                const fadeSamples = message.fadeSamples;
                if (Number.isFinite(fadeSamples) && fadeSamples >= 0) {
                    this.fadeSamples = fadeSamples >>> 0;
                }
            }
        };
    }

    reset() {
        this.buffers = [];
        this.currentBuffer = null;
        this.currentIndex = 0;
        this.isCurrentlyPlaying = false;
        this.held = false;
        this.gain = 1;
    }

    hasPendingAudio() {
        if (this.currentBuffer && this.currentIndex < this.currentBuffer.length) {
            return true;
        }
        return this.buffers.length > 0;
    }

    pullSample() {
        if (this.currentBuffer && this.currentIndex < this.currentBuffer.length) {
            return this.currentBuffer[this.currentIndex++];
        }

        if (this.currentBuffer && this.currentIndex >= this.currentBuffer.length) {
            this.currentBuffer = null;
            this.currentIndex = 0;
        }

        while (this.buffers.length > 0) {
            this.currentBuffer = this.buffers.shift();
            this.currentIndex = 0;
            if (this.currentBuffer && this.currentBuffer.length > 0) {
                return this.currentBuffer[this.currentIndex++];
            }
        }

        this.currentBuffer = null;
        this.currentIndex = 0;
        return 0;
    }

    process(inputs, outputs) {
        const output = outputs[0];
        if (!output || output.length === 0) {
            return true;
        }

        const channel = output[0];
        let wroteSamples = false;
        const step = this.fadeSamples > 0 ? 1 / this.fadeSamples : 1;

        for (let i = 0; i < channel.length; i++) {
            if (this.held && this.gain === 0) {
                channel[i] = 0; // Held: the rest of the reply waits, unplayed.
                continue;
            }
            this.gain = this.held ? Math.max(0, this.gain - step) : Math.min(1, this.gain + step);
            const sample = this.pullSample() * this.gain;
            channel[i] = sample;
            if (sample !== 0) {
                wroteSamples = true;
            }
        }

        if (this.held) {
            return true;
        }
        if (this.hasPendingAudio()) {
            this.isCurrentlyPlaying = true;
        } else if (!wroteSamples && this.isCurrentlyPlaying) {
            this.isCurrentlyPlaying = false;
            this.port.postMessage({ type: 'drained' });
        }

        return true;
    }
}

registerProcessor('pcm-playback', PCMPlaybackProcessor);
