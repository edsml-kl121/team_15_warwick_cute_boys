(() => {
  const base = document.querySelector('meta[name="zippy-api"]')?.content;
  const transcription = document.querySelector('meta[name="zippy-transcribe"]')?.content;
  const page = new URL(location.href);
  const demo = page.searchParams.get('demo') === 'ploy' || page.pathname.endsWith('/presenter.html');

  async function send(url, body, method = body == null ? 'GET' : 'POST') {
    if (location.protocol === 'file:' && new URL(url, location.href).protocol === 'file:') {
      throw new Error('Open the served Zippy app to connect to the backend.');
    }
    const form = body instanceof FormData;
    let response;
    try {
      const target = new URL(url, page);
      const headers = {};
      if (demo && base && target.origin === page.origin && target.href.startsWith(urlFor('').href)) headers['X-Zippy-Demo'] = '1';
      if (body != null && !form) headers['Content-Type'] = 'application/json';
      response = await fetch(target, {
        method,
        headers,
        body: form || body == null ? body : JSON.stringify(body),
      });
    } catch {
      throw new Error('Couldn’t reach Zippy. Check your connection and try again.');
    }
    if (response.ok) return response;
    const { detail } = await response.json().catch(() => ({}));
    throw new Error(typeof detail === 'string' ? detail : 'Zippy couldn’t complete this request. Please try again.');
  }

  function urlFor(path) {
    if (!base) throw new Error('Zippy isn’t connected to a chat server yet.');
    return new URL(path, new URL(base.replace(/\/?$/, '/'), location.href));
  }

  async function json(path, body, method) {
    return (await send(urlFor(path), body, method)).json();
  }

  async function chat(sessionId, message, onEvent) {
    const response = await send(urlFor('chat'), { session_id: sessionId, message });
    if (!response.body || !response.headers.get('content-type')?.includes('application/x-ndjson')) {
      throw new Error('Zippy did not receive a chat stream from the server.');
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    try {
      for (;;) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        const lines = buffer.split('\n');
        buffer = done ? '' : lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          const event = JSON.parse(line);
          if (event.type === 'done') return;
          if (event.type === 'error') throw new Error(event.message || 'Zippy couldn’t finish this response.');
          onEvent(event);
        }
        if (done) throw new Error('The reply was interrupted. You can retry it.');
      }
    } finally {
      await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }

  const amount = (number, unit) => Number.isFinite(number) ? `${number.toLocaleString()} ${unit}` : null;
  const row = (label, value) => ({ label, value });
  const duration = minutes => !Number.isFinite(minutes) ? null
    : minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h${minutes % 60 ? ` ${minutes % 60} m` : ''}`;
  const GOAL_LABELS = {
    sleep_minutes: ['Sleep', duration], deep_minutes: ['Deep sleep', duration],
    protein_g: ['Protein', n => amount(n, 'g')], kcal: ['Calories', n => amount(n, 'kcal')],
    active_minutes: ['Active minutes', n => amount(n, 'min')], steps: ['Steps', n => amount(n, '')?.trim()],
    carbs_g: ['Carbs', n => amount(n, 'g')], fat_g: ['Fat', n => amount(n, 'g')],
  };

  function productCards(data) {
    const products = data.products || [];
    const more = data.more?.count > 0 && Array.isArray(data.more.price_range)
      ? `${data.more.count} more · ฿${data.more.price_range[0]} to ฿${data.more.price_range[1]}` : null;
    return products.map((product, index) => ({
      type: 'product', title: product.name, productId: product.item_id, source: 'shopee', sourceLabel: 'Shopee Mall',
      description: product.shop, imageUrl: product.image_url, value: amount(product.price_thb, 'THB'),
      badge: product.item_id === data.best_item_id ? 'Best value for you' : null,
      rows: [row('Rating', amount(product.rating, '/ 5')), row('Details', product.note)],
      note: index === 0 ? more : null,
    }));
  }

  function callCard(data) {
    const states = {
      calling: ['call', `Calling ${data.restaurant}…`], no_answer: ['phone_missed', `Called ${data.restaurant}`],
      ended: ['phone_in_talk', `${data.restaurant} · call ended`],
    };
    const [icon, title] = states[data.status] || ['call', data.restaurant];
    const outcome = data.status === 'no_answer' ? 'No answer' : data.outcome === 'booked' ? 'Table booked' : null;
    return [{ icon, title, value: outcome, description: data.quote ? `“${data.quote}”` : null,
      rows: [row('Duration', amount(data.duration_s, 's'))] }];
  }

  function cards(data) {
    if (!data) return [];
    switch (data.kind) {
      case 'product_compare':
        return productCards(data);
      case 'places':
        return [{ title: 'Places nearby', source: 'shopee', sourceLabel: 'Shopee Food', icon: 'restaurant',
          items: (data.places || []).map(place => ({
            title: place.name,
            detail: [place.dish, amount(place.price_thb, 'THB'), amount(place.distance_km, 'km')].filter(Boolean).join(' · '),
            value: amount(place.protein_g, 'g protein'),
          })), note: 'Menus and nutrition from Shopee Food' }];
      case 'sleep_insight':
        return [{ title: 'Deep sleep', icon: 'bedtime', value: duration(data.deep_minutes),
          description: data.shortfall_minutes > 0 ? `${duration(data.shortfall_minutes)} short of your ${duration(data.goal_minutes)} goal` : 'Deep sleep goal met',
          timeline: (data.timeline || []).filter(([stage, minutes]) => typeof stage === 'string' && Number.isFinite(minutes))
            .map(([stage, minutes]) => ({ stage, minutes })),
          chips: (data.events || []).map(event => `${event.at} ${event.label}`),
          rows: Object.entries(data.totals || {}).map(([stage, minutes]) => row(stage === 'rem' ? 'REM' : stage[0].toUpperCase() + stage.slice(1), duration(minutes))),
          note: [data.source, data.minutes && `${duration(data.minutes)} asleep`, data.start && data.end && `${data.start} – ${data.end}`].filter(Boolean).join(' · ') }];
      case 'meal':
        return [{ title: data.dish, icon: 'restaurant', value: amount(data.protein_g, 'g protein'), description: data.why,
          rows: [row('Energy', amount(data.kcal, 'kcal'))] }];
      case 'activity':
        return [{ title: 'Steps today', icon: 'directions_walk', value: amount(data.steps, '')?.trim(),
          meters: Number.isFinite(data.steps_goal_pct) ? [{ label: 'Steps goal', text: `${data.steps_goal_pct}%`, value: data.steps_goal_pct, max: 100 }] : [],
          rows: [row('Active time', amount(data.active_minutes, 'min')), row('Sitting', amount(data.sitting_hours, 'h'))] }];
      case 'call':
        return callCard(data);
      case 'walk_route':
        return [{ title: 'Walking route', icon: 'directions_walk', value: duration(data.minutes),
          rows: [row('Leave by', data.leave_by)], link: data.maps_url, linkLabel: 'Open walking route' }];
      case 'daily_summary': {
        const goals = (data.goals || []).filter(goal => Number.isFinite(goal.value) && Number.isFinite(goal.goal) && GOAL_LABELS[goal.key]);
        const met = goals.filter(goal => goal.met).length;
        return [{ title: 'Your day', icon: 'check_circle', value: goals.length ? `${met} of ${goals.length} goals hit` : null,
          meters: goals.map(goal => {
            const [label, format] = GOAL_LABELS[goal.key];
            return { label, text: `${format(goal.value)} / ${format(goal.goal)}`, value: goal.value, max: goal.goal, met: goal.met };
          }) }];
      }
      case 'payment_status':
        return [{ title: data.paid === true ? 'Paid ✓' : 'Payment status', icon: data.paid === true ? 'check' : 'hourglass_top',
          source: 'shopee', description: data.item?.name, value: amount(data.total_thb, 'THB'),
          rows: [row('Arrival', data.arrival_date)], chips: Array.isArray(data.chips) ? data.chips : [] }];
      case 'reminder':
        return [{ title: `Reminder set · ${data.at}`, icon: 'alarm', description: data.message }];
      default:
        return [];
    }
  }

  async function photo(file, sessionId) {
    const body = new FormData();
    body.append('file', file);
    return json('food-log/photo?' + new URLSearchParams({ session_id: sessionId }), body);
  }

  async function transcribe(audio) {
    const body = new FormData();
    body.append('audio', audio);
    const { text } = await (await send(transcription, body)).json();
    return typeof text === 'string' ? text : '';
  }

  window.zippyService = {
    chat, cards, json, photo, demo, transcribe: transcription ? transcribe : null,
  };
})();
