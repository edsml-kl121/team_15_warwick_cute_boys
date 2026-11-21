(() => {
  // Web push needs a service worker, the Push API and HTTPS (localhost counts).
  // On iPhone it also needs iOS 16.4+ and Zippy opened from the Home Screen.
  const supported = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window && window.isSecureContext;
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const standalone = matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;

  function keyBytes(base64url) {
    const base64 = (base64url + '='.repeat((4 - base64url.length % 4) % 4)).replace(/-/g, '+').replace(/_/g, '/');
    return Uint8Array.from(atob(base64), char => char.charCodeAt(0));
  }

  window.createZippyPush = ({ service, showFeedback }) => {
    const registration = supported
      ? navigator.serviceWorker.register('./sw.js').catch(() => null)
      : Promise.resolve(null);
    const button = document.querySelector('[data-action="enable-push"]');
    const hint = document.querySelector('.push-hint');

    async function currentSubscription() {
      const worker = await registration;
      return worker ? worker.pushManager.getSubscription() : null;
    }

    async function refresh() {
      if (isIOS && !standalone) {
        hint.textContent = 'To get notifications on iPhone, tap Share, then Add to Home Screen, and open Zippy from there.';
        button.hidden = true;
        return;
      }
      if (!supported) {
        hint.textContent = 'This browser can’t show Zippy notifications.';
        button.hidden = true;
        return;
      }
      const on = Notification.permission === 'granted' && Boolean(await currentSubscription());
      button.hidden = on;
      hint.textContent = on ? 'Notifications are on.'
        : Notification.permission === 'denied' ? 'Notifications are blocked. Turn them on in your device settings.' : '';
    }

    async function send(sessionId, subscription) {
      await service.json('push/subscribe', { session_id: sessionId, subscription: subscription.toJSON() });
    }

    async function enable(sessionId, control) {
      if (isIOS && !standalone) return showFeedback('Add Zippy to your Home Screen first, then open it from there.');
      if (!supported) return showFeedback('This browser can’t show notifications.');
      control.disabled = true;
      try {
        // Ask first, while the tap still counts as a user gesture (required on iOS).
        const permission = await Notification.requestPermission();
        if (permission !== 'granted') return showFeedback('Notifications stay off. You can change this in Settings.');
        const worker = await registration;
        if (!worker) throw new Error('The notification worker didn’t start.');
        const { public_key: publicKey } = await service.json('push/key');
        if (typeof publicKey !== 'string' || !publicKey) throw new Error('The server has no push key yet.');
        const subscription = await worker.pushManager.getSubscription()
          || await worker.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(publicKey) });
        await send(sessionId, subscription);
        showFeedback('Notifications are on.');
      } catch (error) {
        showFeedback(`Couldn’t turn on notifications. ${error.message}`);
      } finally {
        control.disabled = false;
        refresh();
      }
    }

    // Link a newly connected chat to this device's existing subscription. Silent: push is optional.
    async function sync(sessionId) {
      if (!supported || Notification.permission !== 'granted') return;
      try {
        const subscription = await currentSubscription();
        if (subscription) await send(sessionId, subscription);
      } catch {
        // The chat works without push; the next enable or sync retries.
      }
    }

    refresh();
    return { enable, refresh, sync };
  };
})();
