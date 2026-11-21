(() => {
  const base = document.querySelector('meta[name="zippy-api"]')?.content;
  const transcription = document.querySelector('meta[name="zippy-transcribe"]')?.content;

  async function send(url, body) {
    if (location.protocol === 'file:' && new URL(url, location.href).protocol === 'file:') {
      throw new Error('Open the served Zippy app to connect to the backend.');
    }
    const form = body instanceof FormData;
    let response;
    try {
      response = await fetch(url, body == null ? undefined : {
        method: 'POST',
        headers: form ? undefined : { 'Content-Type': 'application/json' },
        body: form ? body : JSON.stringify(body),
      });
    } catch {
      throw new Error('Couldn’t reach Zippy. Check your connection and try again.');
    }
    if (response.ok) return response;
    if (response.status === 401 || response.status === 403) throw new Error('Zippy could not authenticate with the server.');
    const { detail } = await response.json().catch(() => ({}));
    throw new Error(typeof detail === 'string' ? detail : 'Zippy couldn’t complete this request. Please try again.');
  }

  function urlFor(path) {
    if (!base) throw new Error('Zippy isn’t connected to a chat server yet.');
    return new URL(path, new URL(base.replace(/\/?$/, '/'), location.href));
  }

  async function json(path, body) {
    return (await send(urlFor(path), body)).json();
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

  function cards(data) {
    if (!data) return [];
    switch (data.kind) {
      case 'product_compare':
        return (data.products || []).map(product => ({
          type: 'product', title: product.name, productId: product.item_id, source: 'shopee',
          description: product.shop, imageUrl: product.image_url, value: amount(product.price_thb, 'THB'),
          rows: [row('Rating', amount(product.rating, '/ 5')), row('Details', product.note)],
        }));
      case 'places':
        return (data.places || []).map(place => ({
          title: place.name, description: place.dish, source: 'shopee',
          value: amount(place.protein_g, 'g protein'),
          rows: [row('Price', amount(place.price_thb, 'THB')), row('Distance', amount(place.distance_km, 'km'))],
        }));
      case 'sleep_insight':
        return [{ title: 'Deep sleep', value: amount(data.deep_minutes, 'min'), rows: [
          row('Total sleep', amount(data.minutes, 'min')), row('Deep sleep goal', amount(data.goal_minutes, 'min')),
          row('Below goal', amount(data.shortfall_minutes, 'min')),
        ] }];
      case 'meal':
        return [{ title: data.dish, value: amount(data.protein_g, 'g protein'), description: data.why,
          rows: [row('Energy', amount(data.kcal, 'kcal'))] }];
      case 'activity':
        return [{ title: 'Activity', value: amount(data.steps, 'steps'), rows: [
          row('Steps goal', amount(data.steps_goal_pct, '%')), row('Active time', amount(data.active_minutes, 'min')),
        ] }];
      case 'call':
        return [{ title: data.restaurant, description: data.quote, rows: [
          row('Status', data.status?.replaceAll('_', ' ')), row('Duration', amount(data.duration_s, 's')),
        ] }];
      case 'walk_route':
        return [{ title: 'Walking route', value: amount(data.minutes, 'min'),
          rows: [row('Leave by', data.leave_by)], link: data.maps_url }];
      case 'daily_summary':
        return [{ title: 'Daily summary', rows: (data.goals || []).filter(goal => Number.isFinite(goal.value) && Number.isFinite(goal.goal))
          .map(goal => row(goal.key.replaceAll('_', ' '), `${goal.value} / ${goal.goal}`)) }];
      case 'payment_status':
        return [{ title: data.paid === true ? 'Payment confirmed' : 'Payment status', source: 'shopee', description: data.item?.name,
          value: amount(data.total_thb, 'THB'), rows: [row('Arrival', data.arrival_date)] }];
      case 'reminder':
        return [{ title: 'Reminder', description: data.message, rows: [row('Time', data.at)] }];
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
    chat, cards, json, photo, transcribe: transcription ? transcribe : null,
  };
})();
