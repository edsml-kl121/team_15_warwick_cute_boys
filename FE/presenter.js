(() => {
  const service = window.zippyService;
  const SESSION_PATTERN = /^[A-Za-z0-9_-]{1,80}$/;
  // Every proactive or scheduled moment the backend can push. `preview` is sample copy for a local test only;
  // the real notification text comes from the backend's feed item.
  const FLOWS = [
    { scene: 'Scene 1 · 07:02', name: 'Morning sleep insight', body: { moment: 'morning_sleep' },
      preview: ['Sleep insight', 'You slept 5 h 10 m, your 3rd short night this week. Light woke you up at 5:40. Want help?'] },
    { scene: 'Scene 1 · 22:30', name: 'Eye mask reminder', body: { reminder: '22:30' },
      needs: 'Needs a paid eye mask order first.', preview: ['Reminder', 'Wear your eye mask'] },
    { scene: 'Scene 2 · 18:15', name: 'Dinner tip', body: { moment: 'dinner_tip' },
      preview: ['Dinner tip', 'You’re 40 g short on protein today. A grilled chicken salad for dinner would fix it.'] },
    { scene: 'Scene 2 · leave by', name: 'Time to walk to dinner', reminderTime: '18:49',
      needs: 'Needs a booked table first. Use the leave-by time shown in the chat.',
      preview: ['Time to go', 'Time to go. 10 min walk, route is on your lock screen.'] },
    { scene: 'Scene 2 · 19:40', name: 'Daily summary', body: { moment: 'daily_summary' },
      preview: ['Daily summary', 'That’s your day, Ploy.'] },
  ];

  const sessionInput = document.querySelector('#session');
  const list = document.querySelector('.pr-flows');
  const log = document.querySelector('.pr-log');
  const worker = 'serviceWorker' in navigator && window.isSecureContext
    ? navigator.serviceWorker.register('./sw.js').catch(() => null) : Promise.resolve(null);

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text != null) element.textContent = text;
    return element;
  }

  function note(message, isError = false) {
    const item = node('li', isError ? 'error' : '');
    item.append(node('time', 'tk', new Date().toLocaleTimeString('en-GB')), node('span', '', message));
    log.prepend(item);
  }

  function session() {
    const value = sessionInput.value.trim();
    if (!SESSION_PATTERN.test(value)) throw new Error('Enter the chat’s session ID first.');
    return value;
  }

  async function run(control, label, task) {
    control.disabled = true;
    try {
      note(`${label}: ${await task()}`);
    } catch (error) {
      note(`${label}: ${error.message}`, true);
    } finally {
      control.disabled = false;
    }
  }

  async function trigger(flow, row) {
    const body = flow.reminderTime ? { reminder: row.querySelector('input[type="time"]').value } : flow.body;
    if (flow.reminderTime && !/^\d{2}:\d{2}$/.test(body.reminder)) throw new Error('Choose a reminder time.');
    await service.json('demo/trigger', { session_id: session(), ...body });
    return 'sent.';
  }

  async function preview(flow) {
    if (!('Notification' in window)) throw new Error('This browser can’t show notifications.');
    if (await Notification.requestPermission() !== 'granted') throw new Error('Notifications are blocked for this page.');
    const registration = await worker;
    if (!registration) throw new Error('The notification worker didn’t start.');
    const [title, body] = flow.preview;
    await registration.showNotification(`Zippy · ${title}`, { body, icon: './assets/icon-192.png', data: { url: './' } });
    return 'preview shown on this device.';
  }

  function button(className, text, label, onClick) {
    const element = node('button', className, text);
    element.type = 'button';
    element.setAttribute('aria-label', label);
    element.addEventListener('click', () => onClick(element));
    return element;
  }

  function flowRow(flow) {
    const row = node('li', 'card pr-flow');
    const text = node('div', 'pr-flow-text');
    text.append(node('span', 'eb', flow.scene.toUpperCase()), node('b', '', flow.name));
    if (flow.needs) text.append(node('span', 'mut', flow.needs));
    const actions = node('div', 'pr-actions');
    if (flow.reminderTime) {
      const time = node('input');
      time.type = 'time';
      time.value = flow.reminderTime;
      time.setAttribute('aria-label', `${flow.name} time`);
      actions.append(time);
    }
    actions.append(
      button('btn', 'Trigger', `Trigger ${flow.name}`, control => run(control, flow.name, () => trigger(flow, row))),
      button('btn2', 'Preview here', `Preview ${flow.name} notification on this device`, control => run(control, flow.name, () => preview(flow))),
    );
    row.append(text, actions);
    return row;
  }

  document.querySelector('[data-action="reset"]').addEventListener('click', event => {
    if (!confirm('Reset the demo? This clears chats, orders, bookings and reminders on the server.')) return;
    run(event.currentTarget, 'Reset', async () => {
      await service.json('demo/reset', {});
      return 'done. Start a new chat on the phone, then reopen this page from it.';
    });
  });

  sessionInput.value = new URLSearchParams(location.search).get('session') || '';
  list.replaceChildren(...FLOWS.map(flowRow));
})();
