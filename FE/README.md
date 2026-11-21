# Zippy web frontend

Run `docker compose up --build frontend` from the repository root, then open [localhost:3000](http://localhost:3000). For a frontend-only preview, run `python3 -m http.server 8765 --bind 127.0.0.1 --directory FE` and open [localhost:8765](http://localhost:8765).

The keyboard replaces the three dock controls with a message bar and **Back**. **Talk to Zippy** starts microphone capture and displays detected words below the three buttons. Tap the middle waveform again to finish and send. Browser dictation needs microphone permission and a supported speech recognition engine. Open **Chat history** for the left drawer. History is stored for the current browser tab.

Read [CHAT_API.md](CHAT_API.md) for the FastAPI connection, checkout, optional transcription, and original demo values. The static preview opens with an empty conversation. Sending requires the API.

## Verification

From the repository root, run `node --test FE/tests/services.test.cjs`, `node --check FE/app.js`, `node --check FE/voice.js`, and `docker compose config --quiet`. In the browser, open and close the keyboard and history drawer, then verify message sending and how the app handles missing data. On a microphone-enabled browser, verify that dictation updates during speech and stops when you tap the waveform.
