import asyncio
import base64
import itertools
import re
from time import monotonic
from typing import Literal
from urllib.parse import urlencode, urlsplit


class DemoPhone:
    def validate(self, phone):
        pass

    async def start(self, service, booking):
        await asyncio.sleep(2)
        if booking["shop_id"] == "s_easy_health":
            await service.finish_call(booking["id"], "no_answer", 40)
            return
        service.call_connected(booking["id"])
        await asyncio.sleep(3)
        booking["quote"] = "Yes, 7pm for one."
        await service.finish_call(booking["id"], "booked", 34)


class TwilioPhone:
    def __init__(self, account, token, caller_id, public_url, verified_numbers, ring_timeout, max_seconds):
        from twilio.request_validator import RequestValidator
        from twilio.rest import Client

        if not all((account, token, caller_id, public_url, verified_numbers)) or not public_url.startswith("https://"):
            raise ValueError("Live calls require Twilio credentials, a public HTTPS origin and verified team numbers.")
        self.client = Client(account, token)
        self.validator = RequestValidator(token)
        self.caller_id = caller_id
        self.public_url = public_url.rstrip("/")
        self.media_url = "wss://" + urlsplit(public_url).netloc + "/media-stream"
        self.verified_numbers = verified_numbers
        self.ring_timeout = ring_timeout
        self.max_seconds = max_seconds

    def validate(self, phone):
        if not re.fullmatch(r"\+[1-9][0-9]{7,14}", phone) or phone not in self.verified_numbers:
            raise ValueError("This listing has no verified team test number.")

    async def start(self, service, booking):
        from twilio.twiml.voice_response import Connect, Stream, VoiceResponse

        self.validate(booking["phone"])
        response = VoiceResponse()
        connect = Connect()
        stream = Stream(url=self.media_url)
        stream.parameter(name="purpose", value="book_table")
        stream.parameter(name="booking_id", value=booking["id"])
        connect.append(stream)
        response.append(connect)
        query = urlencode({"booking_id": booking["id"]})
        call = await asyncio.to_thread(
            self.client.calls.create, to=booking["phone"], from_=self.caller_id, twiml=str(response),
            timeout=self.ring_timeout, machine_detection="Enable",
            status_callback=f"{self.public_url}/call-status?{query}",
            status_callback_event=["completed"], status_callback_method="POST", time_limit=self.max_seconds,
        )
        booking["call_sid"] = call.sid
        service.store.save()

    async def hang_up(self, call_sid):
        await asyncio.to_thread(self.client.calls(call_sid).update, status="completed")


class RealtimeFactory:
    def __init__(self, prompts, model, voice, language, languages):
        self.prompts, self.model, self.voice = prompts, model, voice
        self.language, self.languages = language, languages

    async def open(self, booking, end_requested, tracker):
        from agents import function_tool
        from agents.realtime import RealtimeAgent, RealtimeRunner

        @function_tool
        async def report_booking_result(outcome: Literal["booked", "full", "other"],
                                        confirmed_time: str | None, quote: str, notes: str) -> str:
            """Record the restaurant's confirmed reservation result once."""
            if "result" not in booking:
                booking["result"] = outcome if outcome != "booked" or confirmed_time else "other"
                booking["confirmed_time"] = confirmed_time
                booking["quote"] = quote[:300]
            return "Result recorded."

        @function_tool
        async def end_call() -> str:
            """Request hang-up after saying goodbye."""
            end_requested.set()
            return "Ending the call."

        instructions = self.prompts.render("phone.rules", language=self.language) + "\n" + self.prompts.render(
            "phone.book_table", restaurant_name=booking["restaurant_name"],
            party_size=booking["party_size"], time=booking["time"], name=booking["name"],
        )
        agent = RealtimeAgent(name="Book a table", instructions=instructions, tools=[report_booking_result, end_call])
        output = {"format": "g711_ulaw"}
        if self.voice:
            output["voice"] = self.voice
        runner = RealtimeRunner(agent, config={"model_settings": {"model_name": self.model, "audio": {
            "input": {"format": "g711_ulaw", "transcription": {"model": "gpt-live-transcribe", "languages": self.languages},
                      "turn_detection": {"type": "semantic_vad", "interrupt_response": True, "create_response": True}},
            "output": output,
        }}})
        return await runner.run(model_config={"playback_tracker": tracker})


async def bridge(socket, service, factory, booking, start):
    from agents.realtime.model import RealtimePlaybackTracker
    from agents.realtime.model_inputs import RealtimeModelSendRawMessage
    from starlette.websockets import WebSocketDisconnect

    stream_id, call_sid = start["streamSid"], start["callSid"]
    tracker = RealtimePlaybackTracker()
    end_requested = asyncio.Event()
    audio = asyncio.Queue(maxsize=250)
    marks = {}
    numbers = itertools.count()
    last_audio = monotonic()

    async def send(event, **fields):
        await socket.send_json({"event": event, "streamSid": stream_id, **fields})

    async def receive():
        try:
            while True:
                packet = await socket.receive_json()
                if packet["event"] == "media":
                    await audio.put(base64.b64decode(packet["media"]["payload"], validate=True))
                elif packet["event"] == "mark":
                    played = marks.pop(packet["mark"]["name"], None)
                    if played:
                        tracker.on_play_bytes(*played)
                elif packet["event"] == "stop":
                    return
        except WebSocketDisconnect:
            return

    async def relay(session):
        buffer = bytearray()
        while True:
            try:
                buffer.extend(await asyncio.wait_for(audio.get(), timeout=0.05))
                if len(buffer) < 400:
                    continue
            except TimeoutError:
                if not buffer:
                    continue
            await session.send_audio(bytes(buffer))
            buffer.clear()

    async def play(session):
        nonlocal last_audio
        async for event in session:
            if event.type == "audio":
                data = event.audio.data
                name = str(next(numbers))
                marks[name] = (event.item_id, event.content_index, data)
                last_audio = monotonic()
                await send("media", media={"payload": base64.b64encode(data).decode()})
                await send("mark", mark={"name": name})
            elif event.type == "audio_interrupted":
                marks.clear()
                await send("clear")
            elif event.type == "error":
                raise RuntimeError("The Realtime call encountered an error.")

    async def hang_up():
        await end_requested.wait()
        started = monotonic()
        while monotonic() - started < 15:
            if not marks and monotonic() - max(last_audio, started) >= 1.5:
                break
            await asyncio.sleep(0.05)
        service.store.save()
        await service.phone.hang_up(call_sid)

    service.call_connected(booking["id"])
    session = await factory.open(booking, end_requested, tracker)
    async with session:
        await session.model.send_event(RealtimeModelSendRawMessage({"type": "response.create"}))
        tasks = [asyncio.create_task(task) for task in (receive(), relay(session), play(session), hang_up())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
