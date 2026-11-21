(() => {
  const service = window.zippyService;
  const chat = document.querySelector('.chat');
  const log = document.querySelector('.live-turns');
  const dock = document.querySelector('.dock');
  const input = dock.querySelector('.chat-input');
  const keyboard = dock.querySelector('.dock-keyboard');
  const voiceDock = dock.querySelector('.dock-voice');
  const waveform = dock.querySelector('[data-action="voice"]');
  const transcript = voiceDock.querySelector('.voice-transcript');
  const voiceStatus = voiceDock.querySelector('.voice-status');
  const history = document.querySelector('.history-modal');
  const historyList = history.querySelector('.history-list');
  const order = document.querySelector('.order-dialog');
  const photo = document.querySelector('#meal-photo');
  const feedback = document.querySelector('#feedback');
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const storageKey = 'zippy-chats';
  let threads = readThreads();
  let active = threads[0] || newThread();
  let mode = 'idle';
  let voiceState = 'idle';
  let sendingVoice = false;
  let voiceText = '';
  let feedbackTimer;
  let reviewedOrder;
  let pendingOrder;
  let checkingUpdates = false;

  const voice = window.createZippyVoice({
    transcribe: service.transcribe,
    onState: updateVoiceState,
    onTranscript(text) {
      voiceText = text.slice(0, 1500);
      transcript.textContent = voiceText;
      transcript.scrollTop = transcript.scrollHeight;
    },
  });

  function readThreads() {
    try {
      const stored = JSON.parse(sessionStorage.getItem(storageKey) || '[]');
      return Array.isArray(stored) ? stored : [];
    } catch {
      return [];
    }
  }

  function newThread() {
    return { id: crypto.randomUUID?.() || Date.now().toString(36), draft: '', messages: [] };
  }

  function saveThreads() {
    try {
      const serializable = threads.map(({ pending, response, ...thread }) => ({
        ...thread,
        messages: thread.messages.map(message => pending != null && message.id === pending
          ? { ...message, error: 'This request was interrupted. You can retry it.' }
          : message),
      }));
      sessionStorage.setItem(storageKey, JSON.stringify(serializable));
    } catch {
      // Storage can be disabled in private previews. The current tab still retains its history.
    }
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
    if (mode === 'voice' && next !== 'voice') voice.cancel();
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
      input.focus({ preventScroll: true });
      scrollToLatest();
    } else if (restoreFocus) {
      dock.querySelector(previous === 'voice' ? '[data-action="voice"]' : '[data-action="type"]').focus();
    }
  }

  function openVoice() {
    if (mode === 'voice') return finishVoice();
    if (active.pending) return showFeedback('Wait for the current reply before sending another message.');
    voiceText = '';
    transcript.textContent = '';
    sendingVoice = false;
    setMode('voice');
    waveform.focus({ preventScroll: true });
    voice.start();
  }

  function updateVoiceState(state, message) {
    if (mode !== 'voice') return;
    voiceState = state;
    dock.dataset.voiceState = state;
    voiceStatus.textContent = message;
    waveform.disabled = state === 'transcribing';
    waveform.setAttribute('aria-label', state === 'starting' ? 'Cancel voice message' : 'Finish voice message');
    if (state !== 'idle') return;
    if (sendingVoice && voiceText.trim()) return submitVoice();
    sendingVoice = false;
    if (!voiceText.trim()) transcript.textContent = message;
  }

  function finishVoice() {
    if (voiceState === 'listening') {
      sendingVoice = true;
      return voice.stop();
    }
    if (voiceState === 'idle' && voiceText.trim()) return submitVoice();
    setMode('idle', true);
  }

  function submitVoice() {
    const text = voiceText.trim();
    setMode('idle', true);
    sendMessage(text);
  }

  function scrollToLatest(animate = false) {
    chat.scrollTo({ top: chat.scrollHeight, behavior: animate && !reducedMotion.matches ? 'smooth' : 'instant' });
  }

  function createCard(data) {
    if (!data || typeof data !== 'object' || typeof data.title !== 'string' || !data.title.trim()) return null;
    const card = node('article', 'card result-card');
    if (data.source === 'shopee') card.append(node('span', 'shp', 'Shopee'));
    card.append(node('h2', '', data.title));
    if (typeof data.value === 'string') card.append(node('p', 'hero', data.value));
    if (typeof data.description === 'string') card.append(node('p', 'lbl', data.description));
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
    if (data.imageUrl) {
      const url = safeURL(data.imageUrl);
      if (url) {
        const img = node('img', 'result-image');
        img.src = url.href;
        img.alt = '';
        img.loading = 'lazy';
        img.referrerPolicy = 'no-referrer';
        img.addEventListener('error', () => img.remove(), { once: true });
        card.prepend(img);
      }
    }
    if (data.type === 'product' && typeof data.productId === 'string' && data.productId) {
      const button = node('button', 'sbtn', 'Review order');
      button.type = 'button';
      button.dataset.action = 'quote';
      button.dataset.productId = data.productId;
      card.append(button);
    }
    const href = data.link && safeURL(data.link);
    if (href) {
      const link = node('a', 'btn2', 'Open walking route');
      link.href = href.href;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      card.append(link);
    }
    return card;
  }

  function createMessage(message) {
    if (message.role === 'assistant') {
      const group = node('div', 'assistant-turn');
      if (message.text) {
        const row = node('div', 'zm');
        const avatar = node('img', 'av live-avatar');
        avatar.src = './assets/zippy-face.png';
        avatar.alt = 'Zippy';
        row.append(avatar, node('span', 'zt', message.text));
        group.append(row);
      }
      const cardGroup = node('div', 'card-group');
      if (message.cards?.length > 1 && message.cards.every(card => card.type === 'product')) cardGroup.classList.add('carousel');
      for (const data of message.cards || []) {
        const card = createCard(data);
        if (card) cardGroup.append(card);
      }
      if (cardGroup.childElementCount) group.append(cardGroup);
      if (message.replies?.length) {
        const replies = node('div', 'quick-replies');
        for (const text of message.replies) {
          const reply = node('button', 'chip', text);
          reply.type = 'button';
          reply.dataset.action = 'quick-reply';
          reply.disabled = Boolean(active.pending);
          replies.append(reply);
        }
        group.append(replies);
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

  function renderMessages(animate = false) {
    document.querySelector('.empty-chat').hidden = active.messages.length > 0;
    const messages = active.messages.map(createMessage);
    if (animate) messages.at(-1)?.classList.add('message-enter');
    if (active.response?.text || active.response?.cards.length || active.response?.replies.length) {
      messages.push(createMessage(active.response));
    }
    if (active.pending && !active.response?.text) {
      const dots = node('div', 'typing-dots');
      dots.setAttribute('role', 'status');
      dots.setAttribute('aria-label', 'Waiting for Zippy');
      dots.append(node('i'), node('i'), node('i'));
      messages.push(dots);
    }
    log.replaceChildren(...messages);
    dock.querySelector('.send-message').disabled = Boolean(active.pending);
    scrollToLatest(animate);
  }

  async function requestReply(thread, message) {
    if (thread.pending) return;
    thread.pending = message.id;
    const reply = { role: 'assistant', text: '', cards: [], replies: [] };
    thread.response = reply;
    delete message.error;
    if (thread === active) renderMessages(true);
    try {
      await service.chat(thread.id, message.text, event => {
        if (event.type === 'delta' && typeof event.text === 'string') reply.text += event.text;
        if (event.type === 'card') reply.cards.push(...service.cards(event.card));
        if (event.type === 'quick_replies' && Array.isArray(event.options)) {
          reply.replies = event.options.filter(text => typeof text === 'string' && text.trim());
        }
        if (thread === active) renderMessages();
      });
      if (!reply.text.trim() && !reply.cards.length && !reply.replies.length) throw new Error('Zippy returned an empty reply. Try again.');
      thread.messages.push(reply);
      thread.connected = true;
    } catch (error) {
      message.error = error.message || 'Couldn’t send this message.';
    } finally {
      delete thread.pending;
      delete thread.response;
      saveThreads();
      if (thread === active) renderMessages(true);
    }
  }

  function sendMessage(text) {
    if (!text || active.pending) return;
    const thread = active;
    const id = String(thread.messages.length);
    const message = { id, role: 'user', text };
    thread.messages.push(message);
    threads = [thread, ...threads.filter(item => item !== thread)];
    requestReply(thread, message);
    saveThreads();
  }

  function drawHistory() {
    history.querySelector('.history-empty').hidden = threads.length > 0;
    historyList.replaceChildren(...threads.map(thread => {
      const item = node('li');
      const button = node('button', 'history-chat', thread.messages.find(message => message.role === 'user')?.text?.slice(0, 140) || 'Chat');
      button.type = 'button';
      button.dataset.action = 'select-chat';
      button.dataset.threadId = thread.id;
      if (thread === active) button.setAttribute('aria-current', 'true');
      item.append(button);
      return item;
    }));
  }

  function openHistory() {
    setMode('idle');
    drawHistory();
    history.showModal();
  }

  function closeHistory() {
    if (!history.open || history.classList.contains('closing')) return;
    if (reducedMotion.matches) return history.close();
    history.classList.add('closing');
    history.querySelector('.history-drawer').addEventListener('animationend', () => {
      if (history.classList.contains('closing')) history.close();
    }, { once: true });
  }

  function selectThread(thread) {
    active = thread;
    closeHistory();
    setMode('idle');
    renderMessages();
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

  async function reviewOrder(productId, control) {
    if (pendingOrder) return showFeedback('There is already a ShopeePay checkout in progress.');
    const threadId = active.id;
    control.disabled = true;
    try {
      const quote = await service.json('actions/buy', { item_id: productId, session_id: threadId });
      if (!quote.order_id || !quote.item?.name || !Number.isFinite(quote.total_thb)) throw new Error('The backend didn’t return a complete order.');
      if (active.id !== threadId || order.open) {
        await service.json('actions/cancel', { order_id: quote.order_id, session_id: threadId });
        return;
      }
      reviewedOrder = { id: quote.order_id, threadId };
      order.querySelector('.order-link').hidden = true;
      order.querySelector('[data-action="checkout"]').hidden = false;
      const quoteCard = createCard({
        title: quote.item.name, source: 'shopee', description: quote.item.shop,
        rows: [
          ['Item', Number.isFinite(quote.item.price_thb) ? `${quote.item.price_thb} THB` : null],
          ['Shipping', Number.isFinite(quote.shipping_thb) ? `${quote.shipping_thb} THB` : null],
          ['Total', `${quote.total_thb} THB`],
          ['Delivery', quote.arrival_date],
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
      const link = order.querySelector('.order-link');
      link.href = approval.href;
      link.hidden = false;
      control.hidden = true;
      link.focus();
    } catch (error) {
      showFeedback(error.message);
    } finally {
      control.disabled = false;
    }
  }

  async function checkUpdates() {
    if (checkingUpdates || document.hidden) return;
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
          sessionStorage.removeItem('zippy-pending-order');
        }
      }
      if (!thread.connected) return;
      const query = new URLSearchParams({ session_id: thread.id, after: thread.lastFeedId || 0 });
      const items = await service.json('feed?' + query);
      if (!Array.isArray(items)) return;
      for (const item of items) {
        if (!Number.isInteger(item.id) || item.id <= (thread.lastFeedId || 0)) continue;
        thread.lastFeedId = item.id;
        const cards = service.cards(item.card);
        if (!item.text && !cards.length && !item.quick_replies?.length) continue;
        thread.messages.push({ role: 'assistant', text: item.text, cards, replies: item.quick_replies });
      }
      if (items.length) {
        saveThreads();
        if (thread === active) renderMessages(true);
      }
    } catch {
      // Keep the conversation intact during transient feed or payment polling failures.
    } finally {
      checkingUpdates = false;
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
    voice: openVoice,
    'quick-reply': control => sendMessage(control.textContent.trim()),
    attach: () => {
      if (mode === 'voice') setMode('idle');
      photo.click();
    },
    retry(control) {
      const message = active.messages.find(item => item.id === control.dataset.messageId && item.role === 'user');
      if (message) requestReply(active, message);
    },
    quote: control => reviewOrder(control.dataset.productId, control),
    checkout,
  };

  document.addEventListener('click', event => {
    const control = event.target.closest('[data-action]');
    if (control) actions[control.dataset.action]?.(control);
    else if (event.target === history) closeHistory();
  });
  history.addEventListener('cancel', event => {
    event.preventDefault();
    closeHistory();
  });
  history.addEventListener('close', () => history.classList.remove('closing'));
  order.querySelector('.order-link').addEventListener('click', () => {
    if (!reviewedOrder) return;
    pendingOrder = reviewedOrder;
    try { sessionStorage.setItem('zippy-pending-order', JSON.stringify(pendingOrder)); } catch {
      // Order polling still works until the current tab closes.
    }
  });
  order.addEventListener('close', () => {
    const current = reviewedOrder;
    reviewedOrder = null;
    if (current && current !== pendingOrder) {
      service.json('actions/cancel', { order_id: current.id, session_id: current.threadId })
        .catch(error => showFeedback(error.message));
    }
  });
  photo.addEventListener('change', async () => {
    const file = photo.files[0];
    photo.value = '';
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) return showFeedback('Choose a photo under 10 MB.');
    const thread = active;
    try {
      await service.photo(file, thread.id);
      thread.connected = true;
      if (!threads.includes(thread)) threads.unshift(thread);
      saveThreads();
      checkUpdates();
    } catch (error) {
      showFeedback(error.message);
    }
  });
  input.addEventListener('input', () => { active.draft = input.value; });
  keyboard.addEventListener('submit', event => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text || active.pending) return;
    active.draft = '';
    input.value = '';
    sendMessage(text);
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !history.open && !order.open && mode !== 'idle') setMode('idle', true);
  });
  window.addEventListener('pagehide', () => voice.cancel());

  renderMessages();
  try { pendingOrder = JSON.parse(sessionStorage.getItem('zippy-pending-order') || 'null'); } catch { pendingOrder = null; }
  checkUpdates();
  setInterval(checkUpdates, 2500);
})();
