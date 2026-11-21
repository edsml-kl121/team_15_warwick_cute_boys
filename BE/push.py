"""Web push: deliver Zippy notifications to a visitor's subscribed devices.

Run `python -m push` once to print a VAPID key pair for VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY.
"""
import asyncio
import base64
import json
import logging

log = logging.getLogger("zippy.push")
GONE = {404, 410}
MAX_SUBSCRIPTIONS = 10


def add_subscription(subscriptions, subscription):
    """Return a new list with this device first, deduplicated by endpoint and capped."""
    rest = [item for item in subscriptions if item["endpoint"] != subscription["endpoint"]]
    return [subscription, *rest][:MAX_SUBSCRIPTIONS]


class WebPush:
    def __init__(self, public_key, private_key, subject):
        self.public_key, self.private_key, self.subject = public_key, private_key, subject

    def _send_one(self, subscription, data):
        from pywebpush import WebPushException, webpush

        try:
            webpush(subscription_info=subscription, data=data, vapid_private_key=self.private_key,
                    vapid_claims={"sub": self.subject}, ttl=3600)
            return None
        except WebPushException as error:
            status = getattr(error.response, "status_code", None)
            if status not in GONE:
                log.warning("Push to %s failed: %s", subscription["endpoint"][:60], error)
            return status

    async def send(self, subscriptions, notification):
        """Send to every device. Returns the endpoints the push service says are gone."""
        data = json.dumps({"title": notification.get("title", ""), "body": notification.get("body", ""),
                           "url": "./", "tag": notification.get("title")})
        statuses = await asyncio.gather(*(asyncio.to_thread(self._send_one, item, data) for item in subscriptions))
        return {item["endpoint"] for item, status in zip(subscriptions, statuses) if status in GONE}


def generate_keys():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())

    def encode(raw):
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    private = encode(key.private_numbers().private_value.to_bytes(32, "big"))
    public = encode(key.public_key().public_bytes(serialization.Encoding.X962,
                                                  serialization.PublicFormat.UncompressedPoint))
    return public, private


if __name__ == "__main__":
    public, private = generate_keys()
    print(f"VAPID_PUBLIC_KEY={public}\nVAPID_PRIVATE_KEY={private}")
