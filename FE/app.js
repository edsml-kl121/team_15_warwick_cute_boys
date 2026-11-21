(() => {
  const service = window.zippyService;
  const chat = document.querySelector('.chat');
  const log = document.querySelector('.live-turns');
  const dock = document.querySelector('.dock');
  const input = dock.querySelector('.chat-input');
  const sendButton = dock.querySelector('.send-message');
  const keyboard = dock.querySelector('.dock-keyboard');
  const voiceDock = dock.querySelector('.dock-voice');
  const waveform = dock.querySelector('[data-action="voice"]');
  const transcript = voiceDock.querySelector('.voice-transcript');
  const voiceStatus = voiceDock.querySelector('.voice-status');
  const history = document.querySelector('.history-modal');
  const historyList = history.querySelector('.history-list');
  const locationButton = history.querySelector('[data-action="toggle-location"]');
  const locationLabel = locationButton.querySelector('.location-label');
  const locationHint = history.querySelector('.location-hint');
  const order = document.querySelector('.order-dialog');
  const photo = document.querySelector('#meal-photo');
  const scan = document.querySelector('.scan-dialog');
  const scanPreview = scan.querySelector('.scan-preview');
  const scanStatus = scan.querySelector('.scan-status');
  const scanResult = scan.querySelector('.scan-result');
  const scanRetry = scan.querySelector('.scan-retry');
  const feedback = document.querySelector('#feedback');
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const main = document.querySelector('.ph');
  const headerStatus = document.querySelector('.header-status');
  const onboarding = document.querySelector('.onboarding-dialog');
  const onboardingForm = onboarding.querySelector('form');
  const pendingOrderKey = service.demo ? 'zippy-ploy-pending-order' : 'zippy-guest-pending-order';
  const HEADER_STATUS = { online: 'Online', calling: 'Calling…', in_call: 'On a call' };
  let threads = [];
  let active = newThread();
  let ready = false;
  let mode = 'idle';
  let voiceState = 'idle';
  let sendingVoice = false;
  let voiceText = '';
  // Voice is a conversation: after Zippy answers aloud the mic opens again, until silence, ✕ or typing.
  let conversing = false;
  // Each spoken reply gets a turn; interrupting moves on, so the old reply never speaks again.
  let replyTurn = 0;
  // The live Realtime conversation ({ session, thread }) while one is open.
  let realtime = null;
  let feedbackTimer;
  let reviewedOrder;
  let pendingOrder;
  let checkingUpdates = false;
  let previewUrl;
  let locationState = 'off';
  let locationVersion = 0;

  const pages = window.createZippyPages({
    service,
    showFeedback,
    onPhoto: openPhotoPicker,
    onVoice: () => {
      location.hash = '';
      openVoice();
    },
  });

  const push = window.createZippyPush({ service, showFeedback });

  function openPhotoPicker() {
    if (scan.hasAttribute('data-busy')) {
      if (!scan.open) scan.showModal();
    } else {
      photo.click();
    }
  }

  const voice = window.createZippyVoice({
    transcribe: service.transcribe,
    onState: updateVoiceState,
    // Send hands-free once the speaker pauses; tapping the waveform still sends right away.
    onPause() {
      if (voiceState === 'listening' && voiceText.trim()) finishVoice();
    },
    onTranscript(text) {
      voiceText = text.slice(0, 1500);
      transcript.textContent = voiceText;
      transcript.scrollTop = transcript.scrollHeight;
    },
  });
  // Replies to spoken messages are read aloud; typed messages stay silent.
  const speaker = window.createZippySpeaker();

  function newThread() {
    return { id: crypto.randomUUID?.() || Date.now().toString(36), draft: '', messages: [], loaded: true };
  }

  async function loadThread(thread) {
    if (thread.loaded) return;
    const { timeline, last_feed_id: lastFeedId } = await service.json('sessions/' + encodeURIComponent(thread.id));
    thread.messages = [];
    for (const entry of timeline) {
      if (entry.type === 'feed') {
        appendFeed(thread, entry.item);
      } else if (entry.type === 'turn') {
        thread.messages.push({ role: 'user', text: entry.message });
        const reply = { role: 'assistant', text: '', cards: [], replies: [] };
        for (const event of entry.events) applyReply(reply, event);
        if (reply.text || reply.cards.length || reply.replies.length) thread.messages.push(reply);
      }
    }
    Object.assign(thread, { loaded: true, connected: true, lastFeedId });
  }

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text != null) element.textContent = text;
    return element;
  }

  function showFeedback(message) {
    clearTimeout(feedbackTimer);
    feedback.textContent = message;
    feedbackTimer = setTimeout(() => { feedback.textContent = ''; }, 4500);
  }

  function setMode(next, restoreFocus = false) {
    if (mode === 'voice' && next !== 'voice') {
      stopRealtime();
      voice.cancel();
      if (conversing) {
        replyTurn += 1;
        speaker.cancel();
      }
      conversing = false;
    }
    const previous = mode;
    mode = next;
    dock.dataset.mode = next;
    dock.querySelector('.dock-default').hidden = next === 'typing';
    keyboard.hidden = next !== 'typing';
    voiceDock.hidden = next !== 'voice';
    if (next !== 'voice') {
      dock.removeAttribute('data-voice-state');
      waveform.disabled = false;
      waveform.setAttribute('aria-label', 'Talk to Zippy');
    }
    if (next === 'typing') {
      input.value = active.draft || '';
      updateSendButton();
      input.focus({ preventScroll: true });
      scrollToLatest();
    } else if (restoreFocus) {
      dock.querySelector(previous === 'voice' ? '[data-action="voice"]' : '[data-action="type"]').focus();
    }
  }

  // Empty composer: the send button offers voice instead, like most chat apps.
  function updateSendButton() {
    const empty = !input.value.trim();
    sendButton.dataset.empty = String(empty);
    sendButton.setAttribute('aria-label', empty ? 'Talk instead' : 'Send message');
    sendButton.querySelector('.material-icons').textContent = empty ? 'mic' : 'north';
  }

  function openVoice() {
    if (mode === 'voice') return finishVoice();
    if (active.pending) return showFeedback('Wait for the current reply before sending another message.');
    navigator.vibrate?.(10);
    speaker.cancel();
    speaker.unlock();
    setMode('voice');
    waveform.focus({ preventScroll: true });
    if (window.zippyRealtimeSupported?.()) return startRealtime();
    conversing = true;
    listen();
  }

  // The live conversation: the microphone stays open and Zippy answers in its own voice. When it can't start,
  // voice falls back to the browser's dictation and speech.
  function stopRealtime() {
    if (!realtime) return;
    const { session, thread } = realtime;
    realtime = null;
    session.stop();
    window.zippyVoiceThread.finish(thread);
    if (thread === active) renderMessages(false, { followLatest: pinnedToLatest });
  }

  async function startRealtime() {
    const thread = active;
    const live = () => realtime?.session === session;
    const session = window.createZippyRealtime({
      url: async () => service.voiceUrl(thread.id, await getRestaurantLocation()),
      onState(state) {
        if (!live()) return;
        updateVoiceState(state, state === 'replying' ? 'Zippy is speaking… just talk to interrupt.' : 'Listening… just talk.');
      },
      onEvent(event) {
        if (!live()) return;
        if (event.type === 'error') {
          showFeedback(event.message || 'The voice conversation stopped.');
          return setMode('idle', true);
        }
        if (event.type === 'user' && event.text) transcript.textContent = event.text;
        const change = window.zippyVoiceThread.apply(thread, event, service);
        if (event.type === 'done') {
          if (!thread.connected) push.sync(thread.id);
          thread.connected = true;
        }
        if (thread !== active || !change) return;
        if (change === 'render') renderMessages(false, { followLatest: pinnedToLatest });
        else scheduleStreamRender();
      },
      onEnd() {
        if (!live()) return;
        showFeedback('The voice conversation ended.');
        setMode('idle', true);
      },
    });
    realtime = { session, thread };
    updateVoiceState('starting', 'Connecting…');
    try {
      await session.start();
    } catch (error) {
      if (!live()) return; // Voice was closed while connecting.
      realtime = null;
      session.stop();
      if (error.name === 'NotAllowedError') {
        showFeedback('Microphone access was denied. You can still type your message.');
        return setMode('idle', true);
      }
      conversing = true;
      listen();
    }
  }

  function listen() {
    voiceText = '';
    transcript.textContent = '';
    sendingVoice = false;
    voice.start();
  }

  function updateVoiceState(state, message) {
    if (mode !== 'voice') return;
    voiceState = state;
    dock.dataset.voiceState = state;
    voiceStatus.textContent = message;
    waveform.disabled = state === 'transcribing';
    waveform.setAttribute('aria-label', realtime ? 'End voice conversation' : state === 'starting' ? 'Cancel voice message'
      : state === 'replying' ? 'Interrupt Zippy' : 'Finish voice message');
    if (state !== 'idle') return;
    if (sendingVoice && voiceText.trim()) return submitVoice();
    sendingVoice = false;
    if (!voiceText.trim()) {
      // Silence or a microphone problem ends the conversation; say why instead of closing without a word.
      if (conversing) {
        showFeedback(message);
        return setMode('idle', true);
      }
      transcript.textContent = message;
    }
  }

  function finishVoice() {
    if (realtime) return setMode('idle', true); // Tapping the mic again turns the live conversation off.
    if (voiceState === 'replying') {
      // Tapping while Zippy talks interrupts it and listens straight away.
      replyTurn += 1;
      speaker.cancel();
      return listen();
    }
    if (voiceState === 'listening') {
      sendingVoice = true;
      return voice.stop();
    }
    if (voiceState === 'idle' && voiceText.trim()) return submitVoice();
    setMode('idle', true);
  }

  function submitVoice() {
    const text = voiceText.trim();
    if (!conversing) {
      setMode('idle', true);
      return sendMessage(text, true);
    }
    if (active.pending) {
      showFeedback('Zippy is still answering. Say that again in a moment.');
      return listen();
    }
    updateVoiceState('replying', 'Zippy is answering… tap to interrupt.');
    sendMessage(text, true);
  }

  function continueConversation() {
    if (conversing && mode === 'voice' && voiceState === 'replying') listen();
  }

  function scrollToLatest(animate = false) {
    stopChatScrollFeedback();
    pinnedToLatest = true;
    chat.scrollTo({ top: chat.scrollHeight, behavior: animate && !reducedMotion.matches ? 'smooth' : 'instant' });
  }

  const STAGE_LABELS = { awake: 'Awake', rem: 'REM', light: 'Light', deep: 'Deep' };

  function icon(name, className = '') {
    const element = node('i', `material-icons ${className}`.trim(), name);
    element.setAttribute('aria-hidden', 'true');
    return element;
  }

  function meter({ label, text, value, max, met }) {
    const group = node('div', 'meter');
    const head = node('div', 'row');
    const name = node('span', '', label);
    if (met === true) name.prepend(icon('check_circle', 'met'));
    head.append(name, node('b', '', text));
    const bar = node('span', 'bar');
    const fill = node('span');
    fill.style.width = `${Math.max(0, Math.min(100, max > 0 ? 100 * value / max : 0))}%`;
    bar.append(fill);
    group.append(head, bar);
    return group;
  }

  function sleepTimeline(segments) {
    const total = segments.reduce((sum, segment) => sum + segment.minutes, 0);
    const chart = node('div', 'stages');
    chart.setAttribute('role', 'img');
    chart.setAttribute('aria-label', 'Sleep stages: ' + segments.map(s => `${STAGE_LABELS[s.stage] || s.stage} ${s.minutes} min`).join(', '));
    for (const segment of segments) {
      const part = node('span', `stage stage-${segment.stage}`);
      part.style.flexGrow = String(segment.minutes / total);
      chart.append(part);
    }
    const legend = node('div', 'stage-legend');
    legend.setAttribute('aria-hidden', 'true');
    for (const [stage, label] of Object.entries(STAGE_LABELS)) {
      const key = node('span', '', label);
      key.prepend(node('i', `stage-${stage}`));
      legend.append(key);
    }
    return [chart, legend];
  }

  // Decorative picture from the backend or bundled assets; removed if it fails to load.
  function remoteImage(value, className) {
    const url = value && safeURL(value);
    if (!url) return null;
    const img = node('img', className);
    img.src = url.href;
    img.alt = '';
    img.loading = 'lazy';
    img.decoding = 'async';
    img.referrerPolicy = 'no-referrer';
    img.addEventListener('error', () => img.remove(), { once: true });
    return img;
  }

  function cardHeader(data) {
    const head = node('div', 'card-head');
    if (data.icon) head.append(icon(data.icon, 'card-icon'));
    head.append(node('h2', '', data.title));
    if (data.source === 'shopee') head.append(node('span', 'shp', data.sourceLabel || 'Shopee'));
    return head;
  }

  function createCard(data) {
    if (!data || typeof data !== 'object' || typeof data.title !== 'string' || !data.title.trim()) return null;
    const card = node('article', 'card result-card');
    if (typeof data.badge === 'string') card.append(node('span', 'badge', data.badge));
    card.append(cardHeader(data));
    if (typeof data.value === 'string') card.append(node('p', 'hero', data.value));
    if (typeof data.description === 'string') card.append(node('p', 'lbl', data.description));
    const mapUrl = data.mapEmbedUrl && safeURL(data.mapEmbedUrl);
    if (mapUrl?.origin === 'https://www.openstreetmap.org' && mapUrl.pathname === '/export/embed.html') {
      const map = node('iframe', 'result-map');
      map.title = `Map of ${data.title}`;
      map.loading = 'lazy';
      map.referrerPolicy = 'no-referrer';
      map.src = mapUrl.href;
      card.append(map);
    }
    if (data.timeline?.length) card.append(...sleepTimeline(data.timeline));
    for (const item of data.meters || []) card.append(meter(item));
    if (data.items?.length) {
      const list = node('ul', 'result-list');
      for (const item of data.items) {
        const entry = node('li');
        const photo = remoteImage(item.imageUrl, 'list-thumb');
        if (photo) {
          photo.alt = item.imageCredit?.caption || '';
          entry.append(photo);
        }
        const text = node('div');
        text.append(node('b', '', item.title), node('span', 'mut', item.detail));
        if (photo) {
          const credit = item.imageCredit;
          const sourceUrl = credit?.source_url && safeURL(credit.source_url);
          if (sourceUrl) {
            const source = node('a', 'result-credit',
              credit.representative ? 'Representative photo' : 'Photo credit');
            source.href = sourceUrl.href;
            source.target = '_blank';
            source.rel = 'noopener noreferrer';
            source.title = [credit.author, credit.license, 'Resized and cropped for display'].filter(Boolean).join(' · ');
            text.append(source);
            photo.addEventListener('error', () => source.remove(), { once: true });
          }
        }
        if (typeof item.orderItemId === 'string' && item.orderItemId) {
          const button = node('button', 'sbtn food-order', 'Order delivery');
          button.type = 'button';
          button.dataset.action = 'order-food';
          button.dataset.itemId = item.orderItemId;
          button.setAttribute('aria-label', `Order delivery from ${item.title}`);
          text.append(button);
        }
        entry.append(text);
        if (item.value) entry.append(node('strong', '', item.value));
        list.append(entry);
      }
      card.append(list);
    }
    if (Array.isArray(data.rows)) {
      const rows = node('dl', 'result-rows');
      for (const row of data.rows) {
        if (typeof row?.label !== 'string' || typeof row.value !== 'string') continue;
        const group = node('div', 'row');
        group.append(node('dt', '', row.label), node('dd', '', row.value));
        rows.append(group);
      }
      if (rows.childElementCount) card.append(rows);
    }
    if (data.chips?.length) {
      const chips = node('div', 'card-chips');
      for (const text of data.chips) if (typeof text === 'string') chips.append(node('span', 'tag', text));
      card.append(chips);
    }
    const image = remoteImage(data.imageUrl, 'result-image');
    if (image) card.prepend(image);
    if (data.type === 'product' && typeof data.productId === 'string' && data.productId) {
      const button = node('button', 'sbtn', 'Buy');
      button.type = 'button';
      button.dataset.action = 'quote';
      button.dataset.productId = data.productId;
      button.setAttribute('aria-label', `Buy ${data.title}`);
      card.append(button);
    }
    const href = data.link && safeURL(data.link);
    if (href) {
      const link = node('a', 'btn2', data.linkLabel || 'Open link');
      link.href = href.href;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      card.append(link);
    }
    if (typeof data.note === 'string' && data.note) card.append(node('p', 'mut card-note', data.note));
    return card;
  }

  function actionButton(action, icon, label, index, pressed) {
    const button = node('button');
    button.type = 'button';
    button.dataset.action = action;
    button.dataset.index = index;
    button.setAttribute('aria-label', label);
    if (pressed !== undefined) button.setAttribute('aria-pressed', String(pressed));
    const glyph = node('i', 'material-icons', icon);
    glyph.setAttribute('aria-hidden', 'true');
    button.append(glyph);
    return button;
  }

  function createMessageActions(message, index, isLast) {
    const up = actionButton('rate-message', 'thumb_up', 'Good answer', index, message.rating === 'up');
    const down = actionButton('rate-message', 'thumb_down', 'Bad answer', index, message.rating === 'down');
    up.dataset.rating = 'up';
    down.dataset.rating = 'down';
    const bar = node('div', 'msg-actions');
    bar.append(actionButton('copy-message', message.copied ? 'check' : 'content_copy', 'Copy message', index), up, down);
    if (isLast) bar.append(actionButton('regenerate', 'refresh', 'Regenerate', index));
    return bar;
  }

  function createMessage(message, index) {
    if (message.role === 'assistant') {
      const group = node('div', 'assistant-turn');
      if (message.text) {
        const row = node('div', 'zm');
        const avatar = node('img', 'av live-avatar');
        avatar.src = './assets/zippy-face.png';
        avatar.alt = 'Zippy';
        const text = node('div', 'zt md');
        text.append(window.zippyMarkdown.render(message.text));
        row.append(avatar, text);
        group.append(row);
      }
      const cardGroup = node('div', 'card-group');
      if (message.cards?.length > 1 && message.cards.every(card => card.type === 'product')) cardGroup.classList.add('carousel');
      for (const data of message.cards || []) {
        const card = createCard(data);
        if (card) cardGroup.append(card);
      }
      if (cardGroup.childElementCount) group.append(cardGroup);
      const references = service.referenceLinks(message.references);
      if (references.length) {
        const links = node('div', 'recommendation-references');
        for (const reference of references) {
          const link = node('a', '', reference.label);
          link.href = reference.href;
          links.append(link);
        }
        group.append(links);
      }
      if (message.replies?.length) {
        const replies = node('div', 'quick-replies');
        for (const text of message.replies) {
          const reply = node('button', 'chip', text);
          reply.type = 'button';
          reply.dataset.action = 'quick-reply';
          if (message.replyMessages?.[text]) reply.dataset.reply = message.replyMessages[text];
          reply.disabled = Boolean(active.pending);
          replies.append(reply);
        }
        group.append(replies);
      }
      if (message.text && Number.isInteger(index) && !active.pending) {
        const canRegenerate = index === active.messages.length - 1 && active.messages[index - 1]?.role === 'user';
        group.append(createMessageActions(message, index, canRegenerate));
      }
      return group;
    }
    const group = node('div', 'user-turn');
    group.append(node('p', 'um', message.text));
    if (message.error) {
      const status = node('div', 'message-error');
      const retry = node('button', 'chip', 'Retry');
      retry.type = 'button';
      retry.dataset.action = 'retry';
      retry.dataset.messageId = message.id;
      status.append(node('span', '', message.error), retry);
      group.append(status);
    }
    return group;
  }

  function renderMessages(animate = false, { followLatest = true } = {}) {
    headerStatus.textContent = active.pending ? 'Replying…' : HEADER_STATUS[active.headerStatus] || HEADER_STATUS.online;
    document.querySelector('.empty-chat').hidden = active.messages.length > 0;
    const messages = active.messages.map(createMessage);
    if (animate) messages.at(-1)?.classList.add('message-enter');
    if (active.pending && active.response) messages.push(createLiveReply(active.response));
    log.replaceChildren(...messages);
    dock.querySelector('.send-message').disabled = Boolean(active.pending);
    if (followLatest) scrollToLatest(animate);
    drawHistory(); // The sidebar stays visible on wide screens, so keep its list current.
  }

  // The reply being streamed. Its shape (text / cards / chips present) decides when it must be rebuilt;
  // otherwise only its text is patched so photos and the avatar don't reload on every token.
  function liveShape(reply) {
    return `${Boolean(reply.text)}:${reply.cards.length}:${reply.replies.length}`;
  }

  function createLiveReply(reply) {
    let element;
    if (reply.text || reply.cards.length || reply.replies.length) {
      element = createMessage(reply);
    } else {
      element = node('div', 'typing-dots');
      element.setAttribute('role', 'status');
      element.setAttribute('aria-label', reply.waiting || 'Waiting for Zippy');
      element.append(node('i'), node('i'), node('i'));
      if (reply.waiting) element.append(node('span', 'typing-status', reply.waiting));
    }
    element.classList.add('live-reply');
    element.dataset.shape = liveShape(reply);
    return element;
  }

  let streamFrame = 0;
  function scheduleStreamRender() {
    streamFrame ||= requestAnimationFrame(() => {
      streamFrame = 0;
      const reply = active.response;
      const live = log.querySelector('.live-reply');
      if (!reply || !live) return;
      if (live.dataset.shape !== liveShape(reply)) return live.replaceWith(createLiveReply(reply));
      if (reply.text) {
        live.querySelector('.zt')?.replaceChildren(window.zippyMarkdown.render(reply.text));
      } else if (reply.waiting && live.getAttribute('aria-label') !== reply.waiting) {
        live.setAttribute('aria-label', reply.waiting);
        live.querySelector('.typing-status').textContent = reply.waiting;
      }
    });
  }

  async function requestReply(thread, message, spoken = false) {
    if (thread.pending) return;
    thread.pending = message.id;
    const turn = spoken ? ++replyTurn : 0;
    const speaking = () => spoken && turn === replyTurn;
    const reply = { role: 'assistant', text: '', cards: [], replies: [], waiting: service.waitingMessage() };
    thread.response = reply;
    delete message.error;
    if (thread === active) renderMessages(true);
    try {
      const restaurantLocation = await getRestaurantLocation();
      await service.chat(thread.id, message.text, event => {
        applyReply(reply, event);
        if (speaking() && event.type === 'delta' && typeof event.text === 'string') speaker.feed(event.text);
        if (thread === active) scheduleStreamRender();
      }, restaurantLocation);
      if (!reply.text.trim() && !reply.cards.length && !reply.replies.length) throw new Error('Zippy returned an empty reply. Try again.');
      if (speaking()) speaker.finish(continueConversation);
      delete reply.waiting;
      thread.messages.push(reply);
      if (!thread.connected) push.sync(thread.id);
      thread.connected = true;
    } catch (error) {
      if (speaking()) {
        speaker.cancel();
        if (conversing) setMode('idle', true);
      }
      message.error = error.message || 'Couldn’t send this message.';
    } finally {
      delete thread.pending;
      delete thread.response;
      if (thread === active) renderMessages(false, { followLatest: pinnedToLatest });
    }
  }

  function applyReply(reply, event) {
    if (event.type === 'tool' && typeof event.name === 'string' && 'waiting' in reply) reply.waiting = service.waitingMessage(event.name);
    if (event.type === 'delta' && typeof event.text === 'string') reply.text += event.text;
    if (event.type === 'card') reply.cards.push(...service.cards(event.card));
    if (event.type === 'quick_replies' && Array.isArray(event.options)) {
      reply.replies = event.options.filter(text => typeof text === 'string' && text.trim());
    }
  }

  function sendMessage(text, spoken = false) {
    if (!text || active.pending) return;
    const thread = active;
    const id = String(thread.messages.length);
    const message = { id, role: 'user', text };
    thread.messages.push(message);
    threads = [thread, ...threads.filter(item => item !== thread)];
    requestReply(thread, message, spoken);
  }

  function drawHistory() {
    history.querySelector('.presenter-link').href = `./presenter.html?session=${encodeURIComponent(active.id)}`;
    history.querySelector('.history-empty').hidden = threads.length > 0;
    historyList.replaceChildren(...threads.map(thread => {
      const item = node('li');
      const title = thread.messages?.find(message => message.role === 'user')?.text?.slice(0, 140) || thread.title || 'Chat';
      const button = node('button', 'history-chat', title);
      button.type = 'button';
      button.dataset.action = 'select-chat';
      button.dataset.threadId = thread.id;
      if (thread === active) button.setAttribute('aria-current', 'true');
      item.append(button);
      return item;
    }));
  }

  const wideLayout = window.matchMedia('(min-width: 900px)'); // Matches the sidebar breakpoint in styles.css.

  function syncHistoryLayout() {
    if (history.open) history.close();
    history.classList.remove('closing');
    if (wideLayout.matches && ready) {
      drawHistory();
      history.show();
      push.refresh();
    }
  }

  wideLayout.addEventListener('change', syncHistoryLayout);

  function openHistory() {
    if (wideLayout.matches) return; // Already shown as a sidebar.
    setMode('idle');
    drawHistory();
    push.refresh();
    history.showModal();
  }

  function closeHistory() {
    if (wideLayout.matches || !history.open || history.classList.contains('closing')) return;
    if (reducedMotion.matches) return history.close();
    history.classList.add('closing');
    history.querySelector('.history-drawer').addEventListener('animationend', () => {
      if (history.classList.contains('closing')) history.close();
    }, { once: true });
  }

  async function selectThread(thread) {
    try {
      await loadThread(thread);
      active = thread;
      closeHistory();
      setMode('idle');
      renderMessages();
      checkUpdates();
    } catch (error) {
      showFeedback(error.message);
    }
  }

  function safeURL(value) {
    try {
      const url = new URL(value, location.href);
      const loopback = ['localhost', '127.0.0.1', '[::1]'];
      if (url.protocol === 'https:' || (url.protocol === 'http:' &&
        (url.origin === location.origin || loopback.includes(location.hostname) && loopback.includes(url.hostname)))) return url;
    } catch {
      return null;
    }
    return null;
  }

  function setLocationState(state) {
    locationState = state;
    locationVersion += 1;
    const enabled = state === 'on';
    locationButton.setAttribute('aria-pressed', String(enabled));
    locationLabel.textContent = enabled ? 'Using my location ✓' : 'Use my location';
    locationHint.textContent = {
      off: 'Restaurant searches use Silom, Bangkok.',
      on: 'Restaurants near you',
      failed: 'Searching from Silom',
    }[state];
  }

  async function getRestaurantLocation() {
    if (locationState !== 'on') return null;
    const version = locationVersion;
    const position = await service.currentLocation().catch(() => null);
    if (version !== locationVersion) return null;
    if (!position) {
      setLocationState('failed');
      showFeedback('Location unavailable. Searching near Silom, Bangkok.');
    }
    return position;
  }

  async function toggleLocation(control) {
    if (locationState === 'on') {
      setLocationState('off');
      return;
    }
    control.disabled = true;
    try {
      const position = await service.currentLocation().catch(() => null);
      setLocationState(position ? 'on' : 'failed');
    } finally {
      control.disabled = false;
    }
  }

  async function reviewOrder(itemId, control, kind = 'mall') {
    if (pendingOrder) return showFeedback('There is already a ShopeePay checkout in progress.');
    const threadId = active.id;
    control.disabled = true;
    try {
      const restaurantLocation = kind === 'food' ? await getRestaurantLocation() : null;
      const body = { item_id: itemId, session_id: threadId };
      if (kind === 'food') body.kind = kind;
      if (restaurantLocation) body.location = restaurantLocation;
      const quote = await service.json('actions/buy', body);
      if (!quote.order_id || !quote.item?.name || !Number.isFinite(quote.total_thb)) throw new Error('The backend didn’t return a complete order.');
      if (active.id !== threadId || order.open) {
        await service.json('actions/cancel', { order_id: quote.order_id, session_id: threadId });
        return;
      }
      reviewedOrder = { id: quote.order_id, threadId };
      const quoteCard = createCard({
        title: quote.item.name, source: 'shopee', sourceLabel: kind === 'food' ? 'Shopee Food' : 'Shopee Mall',
        description: quote.item.shop, imageUrl: quote.item.image_url,
        rows: [
          ['Item', Number.isFinite(quote.item.price_thb) ? `${quote.item.price_thb} THB` : null],
          [kind === 'food' ? 'Delivery fee' : 'Shipping', Number.isFinite(quote.shipping_thb) ? `${quote.shipping_thb} THB` : null],
          ['Total', `${quote.total_thb} THB`],
          ['Delivery', Number.isFinite(quote.eta_min) ? `${quote.eta_min} min` : quote.arrival_date],
          ['Delivery area', quote.delivery_area],
          ['Address', quote.address],
        ].map(([label, value]) => ({ label, value })),
      });
      order.querySelector('.order-details').replaceChildren(quoteCard);
      order.showModal();
    } catch (error) {
      showFeedback(error.message);
    } finally {
      control.disabled = false;
    }
  }

  async function checkout(control) {
    if (!reviewedOrder) return;
    control.disabled = true;
    try {
      const current = reviewedOrder;
      const payment = await service.json('actions/pay', { order_id: current.id, session_id: current.threadId });
      if (reviewedOrder !== current) return;
      const approval = payment.approve_url && safeURL(payment.approve_url);
      if (!approval) throw new Error('ShopeePay didn’t return a checkout link.');
      pendingOrder = current;
      try { sessionStorage.setItem(pendingOrderKey, JSON.stringify(pendingOrder)); } catch {
        // Order polling still works until the current tab closes.
      }
      location.assign(approval.href);
    } catch (error) {
      showFeedback(error.message);
    } finally {
      control.disabled = false;
    }
  }

  async function checkUpdates() {
    if (!ready || checkingUpdates || document.hidden) return;
    const thread = active;
    if (!thread.connected && !pendingOrder) return;
    checkingUpdates = true;
    try {
      if (pendingOrder) {
        const query = new URLSearchParams({ session_id: pendingOrder.threadId });
        const result = await service.json('shopee-orders/' + encodeURIComponent(pendingOrder.id) + '?' + query);
        if (['paid', 'cancelled'].includes(result.status)) {
          if (reviewedOrder?.id === pendingOrder.id) {
            reviewedOrder = null;
            if (order.open) order.close();
          }
          pendingOrder = null;
          sessionStorage.removeItem(pendingOrderKey);
        }
      }
      if (!thread.connected && !service.demo) return;
      const query = new URLSearchParams({ session_id: thread.id, after: thread.lastFeedId || 0 });
      const items = await service.json('feed?' + query);
      if (!Array.isArray(items)) return;
      for (const item of items) {
        if (!Number.isInteger(item.id) || item.id <= (thread.lastFeedId || 0)) continue;
        thread.lastFeedId = item.id;
        appendFeed(thread, item);
      }
      if (items.length) {
        if (!threads.includes(thread)) threads.unshift(thread);
        if (thread === active) renderMessages(true);
      }
    } catch {
      // Keep the conversation intact during transient feed or payment polling failures.
    } finally {
      checkingUpdates = false;
    }
  }

  function appendFeed(thread, item) {
    if (HEADER_STATUS[item.header_status]) thread.headerStatus = item.header_status;
    const cards = service.cards(item.card);
    if (item.text || cards.length || item.quick_replies?.length) {
      thread.messages.push({
        role: 'assistant', text: item.text, cards, replies: item.quick_replies, references: item.references,
        replyMessages: item.quick_reply_messages,
      });
    }
  }


  // Depth decides slide direction; the stack lets Back return to wherever you came from.
  const DEPTH = { chat: 0, today: 1, profile: 1, food: 2, apps: 2 };
  let navStack = [];

  function route() {
    if (!ready) return;
    const page = location.hash.slice(1);
    const view = pages.pages.includes(page) ? page : 'chat';
    const previous = main.dataset.view;
    const isBack = navStack.at(-2) === view;
    if (isBack) navStack = navStack.slice(0, -1);
    else if (navStack.at(-1) !== view) navStack = [...navStack, view];
    main.dataset.navDir = !previous || previous === view ? ''
      : isBack || DEPTH[view] < DEPTH[previous] ? 'back' : 'forward';
    main.dataset.view = view;
    for (const section of main.querySelectorAll('.page')) section.hidden = section.dataset.page !== view;
    if (view === 'chat') return renderMessages();
    setMode('idle');
    pages.render(view);
  }

  function goBack(fallback = '#') {
    if (navStack.length > 1) return window.history.back();
    location.hash = fallback;
  }

  // Swipe right from the left edge goes back, since a Home Screen app has no browser Back button.
  function enableEdgeSwipe() {
    let start = null;
    main.addEventListener('touchstart', event => {
      const touch = event.touches[0];
      const left = main.getBoundingClientRect().left;
      start = main.dataset.view !== 'chat' && touch.clientX - left < 28 ? { x: touch.clientX, y: touch.clientY } : null;
    }, { passive: true });
    main.addEventListener('touchend', event => {
      if (!start) return;
      const touch = event.changedTouches[0];
      const dx = touch.clientX - start.x;
      const dy = Math.abs(touch.clientY - start.y);
      start = null;
      if (dx < 70 || dy > 60) return;
      const back = main.querySelector('.page:not([hidden]) [data-action="back"]');
      goBack(back?.getAttribute('href') || '#');
    }, { passive: true });
  }

  async function triggerDemo(control) {
    const thread = active;
    control.disabled = true;
    try {
      await service.json('demo/trigger', { session_id: thread.id, moment: control.dataset.moment });
      if (!thread.connected) push.sync(thread.id);
      thread.connected = true;
      if (!threads.includes(thread)) threads = [thread, ...threads];
      closeHistory();
      location.hash = '';
      await checkUpdates();
    } catch (error) {
      showFeedback(error.message);
    } finally {
      control.disabled = false;
    }
  }

  async function resetDemo(control) {
    if (!confirm('Reset the demo? This clears chats, orders and bookings on the server.')) return;
    control.disabled = true;
    try {
      await service.json('demo/reset', {});
      threads = [];
      active = newThread();
      pendingOrder = null;
      sessionStorage.removeItem(pendingOrderKey);
      closeHistory();
      location.hash = '';
      renderMessages();
      showFeedback('Demo reset.');
    } catch (error) {
      showFeedback(error.message);
    } finally {
      control.disabled = false;
    }
  }

  async function leaveGuest(control) {
    if (service.demo) return;
    if (!confirm('Leave this guest session? You’ll start a new profile. A guest profile cannot be recovered by name.')) return;
    const status = history.querySelector('.guest-exit-status');
    status.hidden = true;
    control.disabled = true;
    try {
      await service.json('visitor', undefined, 'DELETE');
      ready = false;
      try { sessionStorage.removeItem(pendingOrderKey); } catch { /* Storage can be disabled. */ }
      location.replace('./');
    } catch (error) {
      status.textContent = error.message;
      status.hidden = false;
      control.disabled = false;
    }
  }

  const actions = {
    'open-history': openHistory,
    'close-history': closeHistory,
    'new-chat': () => selectThread(newThread()),
    'select-chat': control => {
      const thread = threads.find(item => item.id === control.dataset.threadId);
      if (thread) selectThread(thread);
    },
    type: () => setMode('typing'),
    'dock-back': () => setMode('idle', true),
    'voice-cancel': () => setMode('idle', true),
    voice: openVoice,
    'quick-reply': control => sendMessage(control.dataset.reply || control.textContent.trim()),
    attach: () => {
      if (mode === 'voice') setMode('idle');
      openPhotoPicker();
    },
    async 'copy-message'(control) {
      const message = active.messages[Number(control.dataset.index)];
      if (!message?.text) return;
      try {
        await navigator.clipboard.writeText(message.text);
        message.copied = true;
        renderMessages();
        setTimeout(() => { delete message.copied; renderMessages(); }, 1500);
      } catch {
        showFeedback('Couldn’t copy this message.');
      }
    },
    'rate-message'(control) {
      const message = active.messages[Number(control.dataset.index)];
      if (!message) return;
      // ponytail: rating stays on the client; add a feedback endpoint when someone reads the ratings.
      message.rating = message.rating === control.dataset.rating ? undefined : control.dataset.rating;
      renderMessages();
    },
    regenerate(control) {
      const index = Number(control.dataset.index);
      const user = active.messages[index - 1];
      if (active.pending || index !== active.messages.length - 1 || user?.role !== 'user') return;
      active.messages.splice(index);
      requestReply(active, user);
    },
    retry(control) {
      const message = active.messages.find(item => item.id === control.dataset.messageId && item.role === 'user');
      if (message) requestReply(active, message);
    },
    quote: control => reviewOrder(control.dataset.productId, control),
    'order-food': control => reviewOrder(control.dataset.itemId, control, 'food'),
    'toggle-location': toggleLocation,
    checkout,
    demo: triggerDemo,
    back: control => goBack(control.getAttribute('href')),
    'enable-push': control => push.enable(active.id, control),
    'demo-reset': resetDemo,
    'leave-guest': leaveGuest,
  };

  document.addEventListener('click', event => {
    const control = event.target.closest('[data-action]');
    if (control?.dataset.action === 'back') event.preventDefault();
    if (control) actions[control.dataset.action]?.(control);
    else if (event.target === history) closeHistory();
  });
  history.addEventListener('cancel', event => {
    event.preventDefault();
    closeHistory();
  });
  history.addEventListener('close', () => history.classList.remove('closing'));
  order.addEventListener('close', () => {
    const current = reviewedOrder;
    reviewedOrder = null;
    if (current && current !== pendingOrder) {
      service.json('actions/cancel', { order_id: current.id, session_id: current.threadId })
        .catch(error => showFeedback(error.message));
    }
  });
  function showScanResult(meal) {
    scanResult.querySelector('h3').textContent = meal.dish;
    scanResult.querySelector('.scan-kcal').textContent = `≈ ${meal.kcal.toLocaleString()} kcal`;
    scanResult.querySelector('.scan-macros').textContent
      = `${meal.protein_g} g protein · ${meal.carbs_g} g carbs · ${meal.fat_g} g fat`;
    scanResult.querySelector('.scan-items').replaceChildren(...(meal.items || []).map(item => {
      const row = document.createElement('li');
      const portion = document.createElement('span');
      const calories = document.createElement('span');
      portion.textContent = `${item.name} · ${item.portion}`;
      calories.textContent = `≈ ${item.kcal.toLocaleString()} kcal`;
      row.append(portion, calories);
      return row;
    }));
    scanResult.querySelector('.scan-uncertainty').textContent = meal.uncertainty
      ? `Photo-based estimate. ${meal.uncertainty}` : 'Nutrition is estimated from the photo.';
    scanResult.hidden = false;
  }

  function clearScanPreview() {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = undefined;
    scanPreview.removeAttribute('src');
  }

  scan.addEventListener('close', () => {
    if (!scan.hasAttribute('data-busy')) clearScanPreview();
  });
  scanRetry.addEventListener('click', openPhotoPicker);
  scan.querySelector('.scan-log').addEventListener('click', () => scan.close());

  photo.addEventListener('change', async () => {
    const file = photo.files[0];
    photo.value = '';
    if (!file || scan.hasAttribute('data-busy')) return;
    if (file.size > 10 * 1024 * 1024) return showFeedback('Choose a photo under 10 MB.');
    const thread = active;
    clearScanPreview();
    previewUrl = URL.createObjectURL(file);
    scanPreview.src = previewUrl;
    scanResult.hidden = true;
    scanRetry.hidden = true;
    scan.setAttribute('data-busy', '');
    scanStatus.textContent = 'Uploading photo…';
    if (!scan.open) scan.showModal();
    try {
      const meal = await service.photo(file, thread.id, event => {
        if (event.stage === 'analyzing') scanStatus.textContent = 'Identifying foods and estimating portions…';
        if (event.stage === 'saving') scanStatus.textContent = 'Saving to your Food log…';
      });
      showScanResult(meal);
      scanStatus.textContent = 'Meal logged';
      pages.setFoodDate(meal.date);
      if (['food', 'today'].includes(location.hash.slice(1))) pages.render(location.hash.slice(1));
      thread.connected = true;
      if (!threads.includes(thread)) threads.unshift(thread);
      checkUpdates();
    } catch (error) {
      scanStatus.textContent = error.message;
      scanRetry.hidden = false;
      if (!scan.open) showFeedback(error.message);
    } finally {
      scan.removeAttribute('data-busy');
      if (!scan.open) clearScanPreview();
    }
  });
  input.addEventListener('input', () => {
    active.draft = input.value;
    updateSendButton();
  });
  keyboard.addEventListener('submit', event => {
    event.preventDefault();
    const text = input.value.trim();
    if (active.pending) return;
    if (!text) return openVoice();
    active.draft = '';
    input.value = '';
    updateSendButton();
    sendMessage(text);
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && (wideLayout.matches || !history.open) && !order.open && !scan.open && mode !== 'idle') {
      setMode('idle', true);
    }
  });
  window.addEventListener('pagehide', () => voice.cancel());

  function showOnboarding(error, showForm) {
    onboardingForm.hidden = !showForm;
    onboarding.querySelector('.onboarding-description').hidden = !showForm;
    onboarding.querySelector('.onboarding-retry').hidden = !error || showForm;
    onboarding.querySelector('.onboarding-status').hidden = !error;
    onboarding.querySelector('.onboarding-status').textContent = error || '';
    onboarding.querySelector('.demo-entry').hidden = service.demo;
    if (!onboarding.open) onboarding.showModal();
  }

  async function start() {
    try {
      const visitor = await service.json('visitor');
      if (!visitor.ready && !service.demo) {
        showOnboarding(null, true);
        return;
      }
      if (!visitor.ready) await service.json('visitor', undefined, 'POST');
      threads = await service.json('sessions');
      active = threads[0] || { ...newThread(), id: 'presenter', connected: true };
      await loadThread(active);
      try { pendingOrder = JSON.parse(sessionStorage.getItem(pendingOrderKey) || 'null'); } catch { pendingOrder = null; }
      ready = true;
      main.inert = false;
      if (onboarding.open) onboarding.close();
      route();
      syncHistoryLayout();
      checkUpdates();
    } catch (error) {
      showOnboarding(error.message, false);
    }
  }

  onboardingForm.addEventListener('submit', async event => {
    event.preventDefault();
    const fields = new FormData(onboardingForm);
    const body = { name: fields.get('name').trim(), food: fields.get('food').trim() };
    if (!body.name) return showOnboarding('Enter a display name.', true);
    const button = onboardingForm.querySelector('button[type="submit"]');
    button.disabled = true;
    try {
      await service.json('visitor', body);
      await start();
    } catch (error) {
      showOnboarding(error.message, true);
    } finally {
      button.disabled = false;
    }
  });
  onboarding.addEventListener('cancel', event => event.preventDefault());
  onboarding.querySelector('.onboarding-retry').addEventListener('click', start);
  history.querySelector('.demo-controls').hidden = !service.demo;
  history.querySelector('.location-box').hidden = service.demo;
  history.querySelector('.demo-entry').hidden = service.demo;
  document.querySelectorAll('.demo-exit').forEach(link => { link.hidden = !service.demo; });
  history.querySelector('.guest-exit').hidden = service.demo;
  // iOS overlays the keyboard instead of resizing the page; track the visible height so the composer stays above it.
  function fitViewport() {
    const viewport = window.visualViewport;
    if (!viewport) return;
    document.documentElement.style.setProperty('--app-height', `${Math.round(viewport.height)}px`);
    if (viewport.offsetTop) window.scrollTo(0, 0);
  }
  window.visualViewport?.addEventListener('resize', fitViewport);
  window.visualViewport?.addEventListener('scroll', fitViewport);
  fitViewport();

  // Keep the newest message in view while the chat area shrinks or grows (keyboard, dock modes),
  // unless the person scrolled up to read older messages.
  const PIN_DISTANCE = 80;
  const SCROLL_IDLE_MS = 180;
  const MIN_TICK_GAP_MS = 45;
  const scrollKeys = new Set(['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' ']);
  let scrollAudio;
  let lastUserScroll = -Infinity;
  let lastScrollTick = -Infinity;
  let messageAtFade;

  function unlockScrollAudio() {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext || scrollAudio?.state === 'running') return;
    try {
      scrollAudio ??= new AudioContext();
      scrollAudio.resume().catch(() => {});
    } catch { /* Scrolling still works if audio is unavailable. */ }
  }

  function tickChatScroll() {
    navigator.vibrate?.(8);
    if (scrollAudio?.state !== 'running') return;
    const at = scrollAudio.currentTime;
    const tone = scrollAudio.createOscillator();
    const volume = scrollAudio.createGain();
    tone.type = 'triangle';
    tone.frequency.setValueAtTime(850, at);
    tone.frequency.exponentialRampToValueAtTime(440, at + .022);
    volume.gain.setValueAtTime(.075, at);
    volume.gain.exponentialRampToValueAtTime(.001, at + .022);
    tone.connect(volume).connect(scrollAudio.destination);
    tone.start(at);
    tone.stop(at + .023);
  }

  function topChatMessage() {
    const fadeEdge = chat.getBoundingClientRect().top + parseFloat(getComputedStyle(chat).paddingTop);
    let top = null;
    for (const message of log.children) {
      if (message.classList.contains('typing-dots') || message.getBoundingClientRect().top > fadeEdge) break;
      top = message;
    }
    return top;
  }

  function beginChatScroll() {
    const now = performance.now();
    if (now - lastUserScroll > SCROLL_IDLE_MS) messageAtFade = topChatMessage();
    lastUserScroll = now;
  }

  function stopChatScrollFeedback() {
    lastUserScroll = -Infinity;
    messageAtFade = null;
  }

  for (const event of ['click', 'touchend', 'keydown']) {
    document.addEventListener(event, unlockScrollAudio, { capture: true, passive: true });
  }
  chat.addEventListener('wheel', beginChatScroll, { passive: true });
  chat.addEventListener('touchmove', beginChatScroll, { passive: true });
  chat.addEventListener('keydown', event => {
    if (event.target === chat && scrollKeys.has(event.key)) beginChatScroll();
  });

  let pinnedToLatest = true;
  let chatHeight = chat.clientHeight;
  chat.addEventListener('scroll', () => {
    if (chat.clientHeight !== chatHeight) return; // Caused by the resize, not by the person scrolling.
    const now = performance.now();
    if (now - lastUserScroll > SCROLL_IDLE_MS) return; // Programmatic scroll (e.g. smooth scroll on send).
    pinnedToLatest = chat.scrollHeight - chat.scrollTop - chat.clientHeight < PIN_DISTANCE;
    lastUserScroll = now;
    const top = topChatMessage();
    if (top === messageAtFade) return;
    messageAtFade = top;
    if (now - lastScrollTick < MIN_TICK_GAP_MS) return;
    lastScrollTick = now;
    tickChatScroll();
  }, { passive: true });
  // Watch both the chat area (keyboard, dock modes) and its content (card photos loading, streamed text).
  const keepPinned = new ResizeObserver(() => {
    chatHeight = chat.clientHeight;
    if (pinnedToLatest && chat.scrollHeight - chat.clientHeight - chat.scrollTop > 1) {
      stopChatScrollFeedback();
      chat.scrollTop = chat.scrollHeight;
    }
  });
  keepPinned.observe(chat);
  keepPinned.observe(log);

  window.addEventListener('hashchange', route);
  enableEdgeSwipe();
  main.inert = true;
  start();
  setInterval(checkUpdates, 2500);
})();
