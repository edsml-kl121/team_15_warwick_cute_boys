# Zippy web frontend

Run `docker compose up --build frontend` from the repository root, then open [localhost:3000](http://localhost:3000). For a frontend-only preview, run `python3 -m http.server 8765 --bind 127.0.0.1 --directory FE` and open [localhost:8765](http://localhost:8765).

The keyboard replaces the three dock controls with a message bar and **Back**. **Talk to Zippy** starts microphone capture and displays detected words below the three buttons. It sends the message when you pause for about 2.5 seconds, or tap the middle waveform to send sooner. If the browser ends dictation on its own, as Safari on iPhone does after a short silence, it starts listening again and keeps the words so far. Browser dictation needs microphone permission and a supported speech recognition engine, such as Google Chrome's. Open **Chat history** for the left drawer. History is stored for the current browser tab.

Tap the top-right **Profile** icon to open your profile. **New chat** is in the **Chat history** drawer, alongside **Today**, **Food log**, **Profile** and **Connect apps**. These pages read the backend's `/today`, `/food-log` and `/profile` routes. The drawer's **Presenter** section triggers demo moments and opens `presenter.html`, a dashboard for every trigger flow. To install on iPhone, open the HTTPS site in Safari, tap Share, then **Add to Home Screen**. Web push setup and the presenter key are described in [CHAT_API.md](CHAT_API.md#web-push).

Use the camera button in chat or on the Food log page to upload a meal photo (JPG, PNG or WebP, up to 10 MB). When the backend has an OpenAI key, the scan shows upload, analysis and saving progress, then displays the estimated calories, macros and portions. **View Food log** opens the saved day.

Read [CHAT_API.md](CHAT_API.md) for the FastAPI connection, checkout, optional transcription, and original demo values. The static preview opens with an empty conversation. Sending requires the API.

Open `/presenter.html` or `/presentor.html` on the Caddy-served app. Enter the phone's guest display name and the presenter key, then click **Trigger** beside **Recommend food** or **Recommend an item**. The recommendation appears in the guest’s chat.

## Verification

From the repository root, run `node --test FE/tests/*.cjs`, `node --check` on `FE/app.js`, `FE/markdown.js`, `FE/pages.js`, `FE/push.js`, `FE/presenter.js`, `FE/sw.js` and `FE/voice.js`, and `docker compose config --quiet`. In the browser, open and close the keyboard and history drawer, open each page from the menu, trigger each presenter flow, then verify message sending and how the app handles missing data. On a microphone-enabled browser, verify that dictation updates during speech, sends after a pause, and sends at once when you tap the waveform.
