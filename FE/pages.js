(() => {
  const PAGES = ['today', 'food', 'profile', 'apps'];
  const FILTERS = [
    ['all', 'All'], ['health', 'Health & wearables'], ['calendar', 'Email & calendar'], ['shopping', 'Shopping & food'],
  ];
  const share = (label, why, on = true) => ({ label, why, on });
  // App catalog is UI content: what each service is for and what it can share. Connection state comes from /profile.
  const CATALOG = {
    Shopee: { cat: 'shopping', logo: 'shopee.webp', desc: 'Mall, Food and ShopeePay. Payments always need your PIN.' },
    WHOOP: { cat: 'health', logo: 'whoop.webp', desc: 'Reads sleep and recovery each morning' },
    'Apple Health': { cat: 'health', logo: 'apple.webp', desc: 'Reads steps and workouts' },
    'Apple Fitness': { cat: 'health', logo: 'apple.webp', desc: 'Reads workout summaries' },
    'Apple Calendar': { cat: 'calendar', logo: 'apple.webp', desc: 'Adds bookings to your calendar' },
    'Google Calendar': { cat: 'calendar', icon: 'event', desc: 'Adds bookings to your calendar' },
    'Google Maps': { cat: 'other', icon: 'map', desc: 'Plans walking routes' },
    Boditrax: { cat: 'health', logo: 'boditrax.webp', desc: 'Body composition from your gym scale', shares: [
      share('Weight and body fat', 'Sets your calorie goal'), share('Muscle mass', 'Sets your protein goal'),
      share('Visceral fat', 'Optional', false),
    ] },
    Gmail: { cat: 'calendar', logo: 'gmail.webp', desc: 'Reads booking and delivery emails', shares: [
      share('Booking confirmations', 'Keeps your plans up to date'), share('Delivery updates', 'Tracks Shopee parcels'),
    ] },
    Fitbit: { cat: 'health', logo: 'fitbit.webp', desc: 'Reads steps, sleep and heart rate', shares: [
      share('Steps', 'Counts toward your activity goal'), share('Sleep', 'Adds to your sleep insights'),
      share('Heart rate', 'Optional', false),
    ] },
    Garmin: { cat: 'health', logo: 'garmin.webp', desc: 'Reads workouts and Body Battery', shares: [
      share('Workouts', 'Counts toward active minutes'), share('Body Battery', 'Adds to recovery'),
    ] },
  };
  const MACROS = [['Protein', 'protein_g', '#3a6758'], ['Carbs', 'carbs_g', '#a8661b'], ['Fat', 'fat_g', '#5d74a3']];

  const fmt = number => Number.isFinite(number) ? number.toLocaleString('en-US') : '–';
  const pct = (value, max) => `${Math.max(0, Math.min(100, max > 0 ? 100 * value / max : 0))}%`;
  const parseDay = iso => new Date(`${iso}T00:00:00`);
  const isoDay = date => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  const addDays = (iso, days) => { const date = parseDay(iso); date.setDate(date.getDate() + days); return isoDay(date); };
  const dayLabel = (iso, options) => parseDay(iso).toLocaleDateString('en-GB', options);

  function duration(minutes) {
    if (!Number.isFinite(minutes)) return '–';
    const hours = Math.floor(minutes / 60);
    const rest = minutes % 60;
    if (!hours) return `${rest} min`;
    return rest ? `${hours} h ${rest} m` : `${hours} h`;
  }

  function h(tag, props = {}, ...children) {
    const element = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (value == null || value === false) continue;
      if (key === 'class') element.className = value;
      else if (key === 'text') element.textContent = value;
      else if (key === 'style') element.style.cssText = value;
      else if (key === 'value') element.value = value;
      else if (key.startsWith('on')) element.addEventListener(key.slice(2), value);
      else element.setAttribute(key, value === true ? '' : value);
    }
    element.append(...children.flat(Infinity).filter(child => child != null && child !== false));
    return element;
  }

  const icon = (name, style) => h('i', { class: 'material-icons', 'aria-hidden': 'true', style, text: name });
  const bar = (width, color) => h('span', { class: 'bar' }, h('span', { style: `width:${width}${color ? `;background:${color}` : ''}` }));

  function appLogo(name, size = 48) {
    const app = CATALOG[name] || {};
    const box = h('span', { class: 'app-logo', style: `width:${size}px;height:${size}px` });
    box.append(app.logo ? h('img', { src: `./assets/${app.logo}`, alt: '' }) : icon(app.icon || 'apps', 'font-size:22px'));
    return box;
  }

  window.createZippyPages = ({ service, showFeedback, onPhoto, onVoice }) => {
    const root = document.querySelector('.ph');
    const consent = document.querySelector('.consent-dialog');
    const mealPhoto = document.querySelector('.meal-photo-dialog');
    const previewImage = mealPhoto.querySelector('img');
    const previewStatus = mealPhoto.querySelector('[role="status"]');
    previewImage.addEventListener('load', () => { previewImage.hidden = false; });
    previewImage.addEventListener('error', () => { previewStatus.hidden = false; });
    mealPhoto.addEventListener('close', () => previewImage.removeAttribute('src'));
    let renderId = 0;
    let foodDate = null;
    let baseDate = null;
    let appFilter = 'all';
    let appQuery = '';

    function header(left, title, subtitle, right) {
      const titleBox = h('span', { class: 'gt page-title' }, h('h2', { text: title }), subtitle && h('span', { class: 'mut', text: subtitle }));
      return h('div', { class: 'gh' }, left || h('span', { style: 'width:40px' }), titleBox, right || h('span', { style: 'width:40px' }));
    }

    const linkButton = (href, label, name) => h('a', { class: 'ib', href, 'aria-label': label }, icon(name, 'font-size:22px'));
    // Back: returns to the previous page; href is the fallback when the page was opened directly.
    const backButton = (fallback, label = 'Back', name = 'arrow_back') => h('a', {
      class: 'ib', href: fallback, 'aria-label': label, 'data-action': 'back',
    }, icon(name, 'font-size:22px'));

    function askBar(text, actionIcon, onAction, actionLabel) {
      return h('div', { class: 'ask' },
        h('a', { class: 'ask-main', href: '#' },
          h('span', { class: 'av', style: 'width:40px;height:40px' }, h('img', { src: './assets/zippy-face.png', alt: '' })),
          h('span', { text })),
        h('button', { type: 'button', class: 'ask-icon', 'aria-label': actionLabel, onclick: onAction }, icon(actionIcon, 'font-size:20px')));
    }

    function status(section, message, retry) {
      section.replaceChildren(h('div', { class: 'page-status' },
        h('p', { text: message }),
        retry && h('button', { type: 'button', class: 'btn2', text: 'Try again', onclick: retry })));
    }

    async function load(section, id, build) {
      if (!section.childElementCount) status(section, 'Loading…');
      try {
        const content = await build();
        if (id === renderId) section.replaceChildren(...content);
      } catch (error) {
        if (id === renderId) status(section, error.message || 'Couldn’t load this page.', () => render(section.dataset.page));
      }
    }

    // Today ----------------------------------------------------------------
    async function today() {
      const data = await service.json('today');
      const { sleep, recovery, activity, goals, totals } = data;
      const dinner = data.upcoming?.find(item => /dinner/i.test(item.message));
      const proteinLeft = Math.max(0, goals.protein_g - totals.protein_g);
      const rows = [
        ['Sleep', duration(sleep.minutes), `of ${duration(goals.sleep_minutes)}`, pct(sleep.minutes, goals.sleep_minutes),
          `Deep ${duration(sleep.deep_minutes)} of ${duration(goals.deep_minutes)}`],
        ['Protein', `${fmt(totals.protein_g)} g`, `of ${fmt(goals.protein_g)} g`, pct(totals.protein_g, goals.protein_g),
          proteinLeft ? `${proteinLeft} g to go${dinner ? ` · dinner idea at ${dinner.at}` : ''}` : 'Goal reached'],
        ['Calories', fmt(totals.kcal), `of ${fmt(goals.kcal)} kcal`, pct(totals.kcal, goals.kcal),
          `${fmt(Math.max(0, goals.kcal - totals.kcal))} kcal left`],
        ['Active minutes', fmt(activity.active_minutes), `of ${fmt(goals.active_minutes)} min`, pct(activity.active_minutes, goals.active_minutes),
          `${fmt(activity.steps)} steps${Number.isFinite(activity.sitting_hours) ? ` · ${activity.sitting_hours} h sitting` : ''}`],
      ];
      const bars = recovery.bars || [];
      const [mood, ...why] = (recovery.note || '').split(' · ');
      const days = bars.map((_, index) => dayLabel(addDays(data.date, index - bars.length + 1), { weekday: 'narrow' }));
      const upcoming = (data.upcoming || []).map(item => h('div', { class: 'gr' },
        h('span', { class: 'tk when', text: /^\d{4}-\d{2}-\d{2}$/.test(item.at) ? dayLabel(item.at, { weekday: 'short' }) : item.at }),
        h('span', { style: 'flex:1', text: item.message })));

      return [
        header(backButton('#', 'Back to chat'),
          'Today', dayLabel(data.date, { weekday: 'long', day: 'numeric', month: 'short' }),
          linkButton('#apps', 'Connected apps', 'watch')),
        h('div', { class: 'gb page-body' },
          h('div', { class: 'card pad' },
            h('div', { class: 'split' },
              h('div', {}, h('span', { class: 'lbl', text: 'Recovery' }), h('span', { class: 'hero', text: `${recovery.percent}%` })),
              h('div', { class: 'split-end' },
                h('span', { class: 'mood' }, icon('self_improvement', 'font-size:16px;color:#715c16'), mood),
                h('span', { class: 'mut', text: [sleep.source, ...why].filter(Boolean).join(' · ') }))),
            h('div', { class: 'rec-bars', role: 'img', 'aria-label': `Recovery over ${bars.length} days: ${bars.join(', ')} percent` },
              bars.map((value, index) => h('span', { style: `height:${value}%;background:${index === bars.length - 1 ? '#3a6758' : '#cfe3da'}` }))),
            h('div', { class: 'rec-days', 'aria-hidden': 'true' }, days.map(day => h('span', { class: 'tk', text: day })))),
          h('div', { class: 'card progress-card' }, rows.map(([name, value, of, width, sub]) =>
            h('div', { class: 'progress-row', role: 'img', 'aria-label': `${name}: ${value} ${of}. ${sub}` },
              h('div', { class: 'split' }, h('b', { text: name }), h('span', { class: 'num' }, `${value} `, h('span', { class: 'mut', text: of }))),
              bar(width), h('span', { class: 'mut small', text: sub }))),
            h('a', { class: 'card-link', href: '#food' }, 'See food log', icon('chevron_right', 'font-size:18px'))),
          h('span', { class: 'sec', text: 'Zippy is on it' }),
          h('div', { class: 'card list-card' }, upcoming.length ? upcoming : h('p', { class: 'mut empty-row', text: 'Nothing scheduled yet.' }))),
        askBar('Ask Zippy', 'mic', onVoice, 'Talk to Zippy'),
      ];
    }

    // Food log -------------------------------------------------------------
    const MEAL_SOURCES = {
      photo: ['photo_camera', () => 'From your photo'],
      chat: ['chat', () => 'From chat'],
      shopee_food: ['storefront', meal => ['Shopee Food', meal.place].filter(Boolean).join(' · ')],
    };

    function mealThumb(meal) {
      const placeholder = icon(meal.source === 'photo' ? 'photo_camera' : 'restaurant', 'font-size:20px');
      if (typeof meal.photo_url !== 'string' || !meal.photo_url.trim()) {
        return h('span', { class: 'meal-thumb' }, placeholder);
      }

      let url;
      try { url = new URL(meal.photo_url, location.href); } catch { /* Keep the placeholder. */ }
      if (!url || (url.protocol !== 'https:' && !(url.protocol === 'http:' && url.origin === location.origin))) {
        return h('span', { class: 'meal-thumb' }, placeholder);
      }

      const label = meal.dish || 'Logged meal';
      const thumbnail = h('button', {
        class: 'meal-thumb meal-thumb-button', type: 'button',
        'aria-label': `View meal photo: ${label}`, disabled: true,
        onclick: () => {
          mealPhoto.querySelector('h2').textContent = label;
          previewImage.hidden = true;
          previewStatus.hidden = true;
          previewImage.alt = label;
          previewImage.src = url.href;
          mealPhoto.showModal();
        },
      }, placeholder);
      thumbnail.append(h('img', {
        alt: '', loading: 'lazy', decoding: 'async', referrerpolicy: 'no-referrer',
        onload: event => {
          event.target.classList.add('loaded');
          thumbnail.disabled = false;
        },
        onerror: event => event.target.remove(),
        src: url.href,
      }));
      return thumbnail;
    }

    function mealRow(meal) {
      const [sourceIcon, sourceText] = MEAL_SOURCES[meal.source] || MEAL_SOURCES.chat;
      return h('div', { class: 'gr' },
        mealThumb(meal),
        h('span', { class: 'meal-text' },
          h('span', { class: 'mut small', text: `${meal.meal} · ${meal.time}` }),
          h('b', { text: meal.dish }),
          h('span', { class: 'mut small' }, icon(sourceIcon, 'font-size:12px'), sourceText(meal))),
        h('span', { class: 'meal-num' }, h('b', { text: fmt(meal.kcal) }), h('span', { class: 'mut small', text: `${fmt(meal.protein_g)} g protein` })));
    }

    async function food() {
      const [log, profile] = await Promise.all([
        service.json('food-log' + (foodDate ? `?date=${encodeURIComponent(foodDate)}` : '')), service.json('profile'),
      ]);
      baseDate ||= log.date;
      foodDate = log.date;
      const goals = profile.goals;
      const week = Array.from({ length: 7 }, (_, index) => addDays(baseDate, index - 6));
      const meals = log.meals.map(mealRow);
      const suggested = log.suggested && h('div', { class: 'gr' },
        h('span', { class: 'meal-thumb dashed' }, icon('restaurant', 'font-size:20px')),
        h('span', { class: 'meal-text' }, h('span', { class: 'mut small', text: 'Dinner · suggested by Zippy' }), h('b', { text: log.suggested.dish })),
        h('span', { class: 'meal-num' }, h('b', { text: `~${fmt(log.suggested.kcal)}` }), h('span', { class: 'mut small', text: `+${fmt(log.suggested.protein_g)} g protein` })));

      return [
        header(backButton('#today'), 'Food log', dayLabel(log.date, { weekday: 'long', day: 'numeric', month: 'short' })),
        h('div', { class: 'gb page-body' },
          h('div', { class: 'week', role: 'group', 'aria-label': 'Choose a day' }, week.map(day => h('button', {
            type: 'button', class: 'day', 'aria-pressed': String(day === log.date),
            'aria-label': dayLabel(day, { weekday: 'long', day: 'numeric', month: 'long' }),
            onclick: () => { foodDate = day; render('food'); },
          }, h('span', { text: dayLabel(day, { weekday: 'short' }) }), h('b', { text: String(parseDay(day).getDate()) })))),
          h('div', { class: 'card pad' },
            h('div', { class: 'split' },
              h('div', {}, h('span', { class: 'lbl', text: log.date === baseDate ? 'Eaten today' : 'Eaten' }), h('span', { class: 'hero', text: fmt(log.totals.kcal) })),
              h('div', { class: 'split-end' },
                h('b', { text: `${fmt(Math.max(0, goals.kcal - log.totals.kcal))} kcal left` }),
                h('span', { class: 'mut', text: `goal ${fmt(goals.kcal)}` }))),
            MACROS.map(([name, key, color]) => h('div', { class: 'macro', role: 'img', 'aria-label': `${name}: ${log.totals[key]} of ${goals[key]} grams` },
              h('b', { text: name }), bar(pct(log.totals[key], goals[key]), color),
              h('span', { class: 'num' }, `${fmt(log.totals[key])} `, h('span', { class: 'mut', text: `/ ${fmt(goals[key])} g` }))))),
          h('div', { class: 'card list-card' }, meals.length || suggested ? [meals, suggested] : h('p', { class: 'mut empty-row', text: 'No meals logged on this day.' }))),
        askBar('Snap a meal or ask Zippy', 'photo_camera', onPhoto, 'Log a meal from a photo'),
      ];
    }

    // Profile --------------------------------------------------------------
    // Health data: the visitor's own history file, stored by the backend and used for recommendations.
    const MAX_PERSONA_BYTES = 5 * 1024 * 1024;
    const joined = (...parts) => parts.filter(part => part != null && part !== '').join(' · ') || null;

    async function importPersona(input) {
      const file = input.files[0];
      input.value = '';
      if (!file) return;
      if (file.size > MAX_PERSONA_BYTES) return showFeedback('Choose a file under 5 MB.');
      let body;
      try {
        body = JSON.parse(await file.text());
      } catch {
        return showFeedback('That file isn’t valid JSON.');
      }
      try {
        const saved = await service.json('persona', body, 'PUT');
        showFeedback(`Imported ${saved.meals} meals for ${saved.profile.name}.`);
        render('profile');
      } catch (error) {
        showFeedback(`Couldn’t import that file. ${error.message}`);
      }
    }

    function healthSection(persona) {
      const input = h('input', { type: 'file', accept: 'application/json,.json', hidden: true, onchange: event => importPersona(event.target) });
      const pick = h('button', { type: 'button', class: 'btn2 import-btn', onclick: () => input.click() },
        icon('upload_file', 'font-size:18px'), persona ? 'Replace health data' : 'Import health data');
      if (!persona) {
        return [h('span', { class: 'sec', text: 'Health data' }), h('div', { class: 'card pad' },
          h('p', { class: 'mut', text: 'Import your meal, wearable and body history (JSON) so Zippy can tailor its suggestions.' }), pick, input)];
      }
      const p = persona.profile;
      const s = p.summary_30d || {};
      const intake = s.avg_daily_intake || {};
      const rows = [
        ['Body', joined(p.age && `${p.age}`, p.sex, p.height_cm && `${p.height_cm} cm`, p.weight_kg && `${p.weight_kg} kg`)],
        ['Goal', joined(p.body_goal?.replaceAll('_', ' '), p.pace_kg_per_week && `${p.pace_kg_per_week} kg/week`)],
        ['30-day intake', joined(intake.calories && `${fmt(intake.calories)} kcal`, intake.protein_g && `${fmt(intake.protein_g)} g protein`)],
        ['Movement · sleep', joined(s.avg_steps != null && `${fmt(Math.round(s.avg_steps))} steps`, s.avg_sleep_hours && `${s.avg_sleep_hours} h sleep`)],
        ['Shopee Food', joined(s.shopee_orders && `${s.shopee_orders} orders`, s.shopee_spend_thb && `฿${fmt(s.shopee_spend_thb)}`)],
      ].filter(([, value]) => value);
      return [h('span', { class: 'sec', text: 'Health data' }), h('div', { class: 'card list-card' },
        rows.map(([label, value]) => h('div', { class: 'gr' }, h('span', { style: 'flex:1', text: label }), h('span', { class: 'gv', text: value }))),
        h('p', { class: 'mut small health-note', text: joined(`${persona.food_history_log.length} meals`, s.window || persona.as_of?.slice(0, 10)) }),
        pick, input)];
    }

    async function profile() {
      const [data, persona] = await Promise.all([
        service.json('profile'),
        service.json('persona').catch(() => null), // 404 until the visitor imports a file
      ]);
      const { goals, preferences } = data;
      const connected = data.connections.filter(item => item.connected);
      const calendars = connected.filter(item => /calendar/i.test(item.app)).map(item => item.app.replace(/\s*calendar/i, ''));
      const goal = (name, label, value) => h('div', { class: 'gr' }, h('span', { class: 'gi' }, icon(name, 'font-size:18px')),
        h('span', { style: 'flex:1', text: label }), h('span', { class: 'gv', text: value }));
      const about = (label, value) => h('div', { class: 'gr' }, h('span', { style: 'flex:1', text: label }), h('span', { class: 'gv', text: value }));

      return [
        header(backButton('#'), 'Profile'),
        h('div', { class: 'gb page-body' },
          h('div', { class: 'profile-head' },
            h('span', { class: 'av', style: 'width:64px;height:64px' }, h('img', { src: './assets/ploy.webp', alt: '' })),
            h('span', {}, h('b', { class: 'profile-name', text: data.name }),
              h('span', { class: 'mut', text: `${data.location} · with Zippy since ${data.member_since}` }))),
          h('span', { class: 'sec', text: 'Daily goals' }),
          h('div', { class: 'card list-card' },
            goal('bedtime', 'Sleep', `${duration(goals.sleep_minutes)} · deep ${duration(goals.deep_minutes)}`),
            goal('egg_alt', 'Protein', `${fmt(goals.protein_g)} g`),
            goal('local_fire_department', 'Calories', `${fmt(goals.kcal)} kcal`),
            goal('directions_walk', 'Active minutes', `${fmt(goals.active_minutes)} min · ${fmt(goals.steps)} steps`)),
          h('span', { class: 'sec', text: 'About you' }),
          h('div', { class: 'card list-card' },
            about('Food', preferences.food), about('Home · work', `${preferences.home} · ${preferences.work}`),
            about('Budget per meal', `up to ${fmt(preferences.budget_thb)} THB`)),
          healthSection(persona),
          h('span', { class: 'sec', text: 'Connected' }),
          h('div', { class: 'card list-card' },
            h('a', { class: 'gr', href: '#apps' }, h('span', { class: 'gi' }, icon('apps', 'font-size:18px')),
              h('span', { style: 'flex:1', text: 'Connected apps' }), h('span', { class: 'gv', text: `${connected.length} connected` }),
              icon('chevron_right', 'font-size:18px;color:#717975')),
            h('div', { class: 'gr' }, h('span', { class: 'gi' }, icon('event', 'font-size:18px')),
              h('span', { style: 'flex:1', text: 'Calendar' }), h('span', { class: 'gv', text: calendars.join(', ') || 'Not connected' })),
            h('div', { class: 'gr' }, appLogo('Shopee', 32),
              h('span', { class: 'meal-text' }, h('span', { text: 'Shopee' }), h('span', { class: 'mut small', text: CATALOG.Shopee.desc }))))),
        askBar('Ask Zippy', 'mic', onVoice, 'Talk to Zippy'),
      ];
    }

    // Connect apps ---------------------------------------------------------
    async function saveConnections(data, app, connected, shares) {
      const connections = [...data.connections.filter(item => item.app !== app), { app, connected, shares }];
      await service.json('profile', { ...data, connections }, 'PUT');
      showFeedback(connected ? `${app} connected.` : `${app} disconnected.`);
      await render('apps');
    }

    function askConsent(data, app) {
      const items = CATALOG[app]?.shares || [share('Basic data', 'Needed to connect')];
      const state = items.map(item => item.on);
      consent.querySelector('#consent-title').textContent = `Connect ${app}`;
      const logo = consent.querySelector('.consent-logo');
      logo.hidden = !CATALOG[app]?.logo;
      if (CATALOG[app]?.logo) logo.src = `./assets/${CATALOG[app].logo}`;
      consent.querySelector('.consent-items').replaceChildren(...items.map((item, index) => h('div', { class: 'gr' },
        h('span', { class: 'meal-text' }, h('span', { text: item.label }), h('span', { class: 'mut small', text: item.why })),
        h('button', {
          type: 'button', class: `sw ${item.on ? 'on' : 'off'}`, 'aria-pressed': String(item.on), 'aria-label': `Share ${item.label}`,
          onclick: event => {
            state[index] = !state[index];
            event.currentTarget.className = `sw ${state[index] ? 'on' : 'off'}`;
            event.currentTarget.setAttribute('aria-pressed', String(state[index]));
          },
        }, h('span')))));
      consent.returnValue = '';
      consent.onclose = () => {
        if (consent.returnValue !== 'allow') return;
        const shares = items.filter((_, index) => state[index]).map(item => item.label);
        if (!shares.length) return showFeedback('Choose at least one item to share.');
        saveConnections(data, app, true, shares).catch(error => showFeedback(error.message));
      };
      consent.showModal();
    }

    async function apps() {
      const data = await service.json('profile');
      const known = new Map(data.connections.map(item => [item.app, item]));
      const names = [...new Set([...Object.keys(CATALOG), ...known.keys()])];
      const query = appQuery.trim().toLowerCase();
      const visible = names.filter(name => (appFilter === 'all' || CATALOG[name]?.cat === appFilter) && name.toLowerCase().includes(query));
      const isOn = name => known.get(name)?.connected === true;
      const forYou = visible.filter(name => !isOn(name));
      const connected = visible.filter(isOn);
      const appRow = (name, detail, action) => h('div', { class: 'app-row' }, appLogo(name),
        h('span', { class: 'meal-text' }, h('b', { text: name }), h('span', { class: 'mut small', text: detail })), action);
      const search = h('input', {
        'aria-label': 'Search apps', placeholder: 'Search apps and services', value: appQuery,
        oninput: async event => {
          appQuery = event.target.value;
          await render('apps');
          const input = root.querySelector('[data-page="apps"] input');
          input?.focus();
          input?.setSelectionRange(appQuery.length, appQuery.length);
        },
      });

      return [
        h('div', { class: 'gh' }, backButton('#profile', 'Close', 'close'), h('h2', { class: 'apps-title', text: 'Connect apps' }),
          h('span', { class: 'count-pill', text: `${names.filter(isOn).length} connected` })),
        h('div', { class: 'filters', role: 'group', 'aria-label': 'Filter apps' }, FILTERS.map(([key, label]) => h('button', {
          type: 'button', class: `chip${appFilter === key ? ' on' : ''}`, 'aria-pressed': String(appFilter === key), text: label,
          onclick: () => { appFilter = key; render('apps'); },
        }))),
        h('div', { class: 'gb page-body apps-body' },
          forYou.length > 0 && h('span', { class: 'sec big', text: 'For you' }),
          forYou.map(name => appRow(name, CATALOG[name]?.desc || 'Available to connect',
            h('button', { type: 'button', class: 'connect', 'aria-label': `Connect ${name}`, text: 'Connect', onclick: () => askConsent(data, name) }))),
          connected.length > 0 && h('span', { class: 'sec big', text: 'Connected' }),
          connected.map(name => appRow(name, known.get(name).shares.join(' · ') || CATALOG[name]?.desc,
            h('button', {
              type: 'button', class: 'connected', 'aria-label': `Disconnect ${name}`,
              onclick: () => saveConnections(data, name, false, []).catch(error => showFeedback(error.message)),
            }, icon('check', 'font-size:16px'), 'On'))),
          !visible.length && h('p', { class: 'mut empty-row', text: 'No apps match your search.' })),
        h('label', { class: 'app-search' }, icon('search', 'font-size:22px'), search),
      ];
    }

    const builders = { today, food, profile, apps };

    function render(page) {
      const section = root.querySelector(`[data-page="${page}"]`);
      if (!section) return Promise.resolve();
      renderId += 1;
      return load(section, renderId, builders[page]);
    }

    return { pages: PAGES, render };
  };
})();
