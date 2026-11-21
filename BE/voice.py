"""Bridge the browser's microphone and speaker (WS /voice) to the voice coach's Realtime session.

The browser already speaks the Realtime API's audio format (24 kHz 16-bit PCM), so audio passes through unchanged.

Browser → server   binary frames: raw PCM16 microphone audio
Server → browser   binary frames: raw PCM16 coach audio
                   text frames (JSON), using the chat stream's vocabulary where it applies:
                     {"type": "ready"}                          the session is open; start sending audio
                     {"type": "user", "item_id", "text"}        what the visitor has said so far ("" reserves the bubble)
                     {"type": "delta", "text"}                  the coach's words as it speaks
                     {"type": "tool", "name"}                   the coach started a tool
                     {"type": "card" | "quick_replies", ...}    shown after the reply's words, like chat
                     {"type": "done"}                           the reply is complete
                     {"type": "hold"}                           something that may be speech started: pause the coach
                     {"type": "resume"}                         it had no words: carry on from where the coach paused
                     {"type": "interrupted"}                    the visitor said words over the coach: drop unplayed audio
                     {"type": "error", "message"}

Each finished reply is saved to the chat session exactly like a typed turn, so it is there when the chat reloads.

Background noise often sounds like speech to turn detection, so a detected turn only pauses the coach. The bridge
answers, and drops the rest of the coach's reply, only once the visitor's words are transcribed. The first words
arrive about a tenth of a second after they stop talking, well before a reply's first audio would.
"""
import asyncio
import json
import logging
import re

from starlette.websockets import WebSocketDisconnect, WebSocketState

logger = logging.getLogger(__name__)
MAX_AUDIO_BYTES = 64 * 1024  # per frame; the recorder sends about 8 KB at a time
TRANSCRIPTION_MODEL = "gpt-live-transcribe"
WORDS = re.compile(r"\w")


async def open_voice_session(agent, *, model, voice=None, languages=("en",), threshold=0.7, silence_ms=500,
                             noise_reduction="near_field"):
    """An entered Realtime session that takes and returns browser audio.

    Noise reduction filters the microphone before turn detection hears it; near_field suits a phone or headset held
    close and strips distant voices. `threshold` (0 to 1) is how sure turn detection must be that it hears speech.
    The model never answers by itself: VoiceBridge asks for a reply once the visitor's words are transcribed.
    """
    from agents.realtime import RealtimeRunner

    output = {"format": "pcm16"}
    if voice:
        output["voice"] = voice
    audio_in = {"format": "pcm16", "transcription": {"model": TRANSCRIPTION_MODEL, "languages": list(languages)},
                "turn_detection": {"type": "server_vad", "threshold": threshold, "prefix_padding_ms": 300,
                                   "silence_duration_ms": silence_ms, "interrupt_response": True,
                                   "create_response": False}}
    if noise_reduction:
        audio_in["noise_reduction"] = {"type": noise_reduction}
    runner = RealtimeRunner(agent, config={"model_settings": {"model_name": model, "audio": {
        "input": audio_in, "output": output}}})
    session = await runner.run()
    await session.enter()
    return session


def user_transcript(item):
    """What a visitor's message says so far ("" if nothing yet), or None when the item isn't theirs."""
    if getattr(item, "type", None) != "message" or getattr(item, "role", None) != "user":
        return None
    return " ".join(text for content in item.content
                    if (text := getattr(content, "transcript", None) or getattr(content, "text", None)))


class VoiceBridge:
    def __init__(self, socket, service, session_id, cards):
        self.socket, self.service, self.session_id, self.cards = socket, service, session_id, cards
        self.heard = {}        # item_id -> what the visitor said, in the order they said it
        self.saved = set()     # visitor messages already saved with a reply
        self.reply = []        # the coach's words for the reply in progress, one entry per model turn
        self.tools = []        # tools the coach used for this reply
        self.turn_called_tool = False  # a model turn that calls a tool is followed by another that finishes the reply
        self.unsaved = None    # a finished reply waiting for the visitor's words to be transcribed
        self.turns = {}        # item_id -> {"words", "ended"} for detected speech not yet answered or dismissed
        self.paused = False    # the browser holds the coach's audio until we know whether they said anything
        self.session = None

    async def send(self, **message):
        try:
            await self.socket.send_text(json.dumps(message, ensure_ascii=False))
        except (WebSocketDisconnect, RuntimeError):
            pass

    async def run(self, session):
        self.session = session
        tasks = [asyncio.create_task(self.from_browser(session)), asyncio.create_task(self.from_model(session))]
        try:
            await self.send(type="ready")
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if not task.cancelled() and task.exception():
                    logger.error("Voice session loop failed: %r", task.exception())
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.save(final=True)

    async def from_browser(self, session):
        while True:
            message = await self.socket.receive()
            if message["type"] == "websocket.disconnect":
                return
            audio = message.get("bytes")
            if audio is None:
                continue
            if len(audio) > MAX_AUDIO_BYTES or len(audio) % 2:
                await self.socket.close(code=1008)
                return
            await session.send_audio(audio)

    async def from_model(self, session):
        async for event in session:
            if event.type == "audio":
                await self.socket.send_bytes(event.audio.data)
            elif event.type == "audio_interrupted":
                await self.pause()
            elif event.type == "history_added":
                if getattr(event.item, "type", None) == "function_call":
                    self.turn_called_tool = True  # The reply continues after the tool, so keep its bubble open.
                await self.hear(event.item)
            elif event.type == "history_updated":
                for item in event.history:
                    await self.hear(item)
            elif event.type == "tool_start":
                self.tools.append(event.tool.name)
                await self.send(type="tool", name=event.tool.name)
            elif event.type == "agent_start":
                self.turn_called_tool = False
            elif event.type == "raw_model_event":
                await self.words(event.data)
            elif event.type == "agent_end":
                await self.finish_reply()
            elif event.type == "error":
                logger.error("Voice session error: %s", event.error)

    async def hear(self, item, text=None):
        """Send the visitor's words whenever they change. The first send can be "" to hold the bubble's place."""
        item_id = getattr(item, "item_id", item if isinstance(item, str) else None)
        text = user_transcript(item) if text is None else text
        if text is None or item_id is None:
            return
        if self.heard.get(item_id) == text or (not text and item_id in self.heard):
            return  # Unchanged, or the history hasn't caught up with words that already streamed.
        self.heard[item_id] = text
        await self.send(type="user", item_id=item_id, text=text)
        if WORDS.search(text):
            await self.said_something(item_id)
        await self.save()

    async def words(self, data):
        kind = getattr(data, "type", None)
        if kind == "transcript_delta" and data.delta:  # the coach speaking
            delta = data.delta
            if self.reply and self.reply[-1][0] == data.item_id:
                self.reply[-1][1] += delta
            else:
                delta = (" " if self.reply else "") + delta  # a new model turn continues the same reply
                self.reply.append([data.item_id, delta])
            await self.send(type="delta", text=delta)
        elif kind == "raw_server_event" and isinstance(data.data, dict):
            await self.server_event(data.data.get("type"), data.data)

    async def server_event(self, kind, data):
        """Turn detection and transcription of the visitor's speech."""
        item_id = data.get("item_id")
        if not item_id:
            return
        if kind == "input_audio_buffer.speech_started":
            self.turns[item_id] = {"words": False, "ended": False}
            await self.pause()
        elif kind == "input_audio_buffer.committed":  # they stopped talking
            if item_id in self.turns:
                self.turns[item_id]["ended"] = True
                await self.answer_when_ready(item_id)
        elif kind == "conversation.item.input_audio_transcription.delta":  # the visitor speaking
            if data.get("delta"):
                await self.hear(item_id, self.heard.get(item_id, "") + data["delta"])
        elif kind == "conversation.item.input_audio_transcription.completed":
            transcript = (data.get("transcript") or "").strip()
            if WORDS.search(transcript):
                await self.hear(item_id, transcript)
            else:
                await self.dismiss(item_id)
        elif kind == "conversation.item.input_audio_transcription.failed":
            await self.said_something(item_id)  # Unheard isn't noise: answer from the audio rather than ignore them.

    async def pause(self):
        if not self.paused:
            self.paused = True
            await self.send(type="hold")

    async def said_something(self, item_id):
        """Their words drop the rest of the coach's reply and earn an answer once they finish."""
        turn = self.turns.get(item_id)
        if turn is None or turn["words"]:
            return
        turn["words"] = True
        if self.paused:
            self.paused = False
            await self.send(type="interrupted")
        await self.answer_when_ready(item_id)

    async def answer_when_ready(self, item_id):
        turn = self.turns.get(item_id)
        if turn and turn["words"] and turn["ended"]:
            del self.turns[item_id]
            from agents.realtime.model_inputs import RealtimeModelSendRawMessage

            await self.session.model.send_event(RealtimeModelSendRawMessage(message={"type": "response.create"}))

    async def dismiss(self, item_id):
        """Detected speech with no words, such as a voice across the room: the coach carries on."""
        if self.turns.pop(item_id, None) is None:
            return
        if self.paused and not self.turns:
            self.paused = False
            await self.send(type="resume")

    async def finish_reply(self):
        """A model turn ended. The reply is complete unless this turn called a tool: the tool may run before or
        after the turn ends, and either way another turn follows with the rest of the reply."""
        called_tool, self.turn_called_tool = self.turn_called_tool, False
        if called_tool or not (self.reply or not self.cards.empty()):
            return
        text = "".join(part for _, part in self.reply)
        events = [{"type": "tool", "name": name} for name in self.tools]
        if text:
            events.append({"type": "delta", "text": text})
        while not self.cards.empty():
            shown = self.cards.get_nowait()
            event = {"type": "quick_replies", "options": shown["quick_replies"]} if "quick_replies" in shown \
                else {"type": "card", "card": shown}
            events.append(event)
            await self.send(**event)
        await self.send(type="done")
        await self.save(final=True)  # An earlier reply still waiting for its transcript is saved as it is.
        self.unsaved = {"text": text, "events": events}
        self.reply, self.tools = [], []
        await self.save()

    async def save(self, final=False):
        """Save the finished reply with what the visitor said, once their words are transcribed."""
        if self.unsaved is None:
            return
        said = {item_id: text for item_id, text in self.heard.items() if item_id not in self.saved}
        message = " ".join(text for text in said.values() if text).strip()
        if not message and not final:
            return  # Transcription can finish after the reply; wait for it.
        turn, self.unsaved = self.unsaved, None
        self.saved.update(said)
        async with self.service.mutation:
            session = self.service.session(self.session_id)
            session["offered"] = next((event["options"] for event in turn["events"] if event["type"] == "quick_replies"), [])
            session["history"].extend([{"role": "user", "content": message or "(voice message)"},
                                       {"role": "assistant", "content": turn["text"]}])
            self.service.record_event(session, type="turn", message=message or "(voice message)", events=turn["events"])
            self.service.store.save()


async def close_quietly(socket, session=None):
    if session is not None:
        try:
            await session.close()
        except Exception:
            logger.exception("Error closing voice session")
    if socket.application_state != WebSocketState.DISCONNECTED:
        try:
            await socket.close()
        except (WebSocketDisconnect, RuntimeError):
            pass
