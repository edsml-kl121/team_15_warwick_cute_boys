import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from demo import seed


class JsonStore:
    def __init__(self, directory, date):
        self.path = Path(directory) / "demo.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state = json.loads(self.path.read_text()) if self.path.exists() else seed(date)

    def save(self):
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as temporary:
            try:
                json.dump(self.state, temporary, ensure_ascii=False)
                temporary.flush()
                os.fsync(temporary.fileno())
                os.replace(temporary.name, self.path)
            finally:
                Path(temporary.name).unlink(missing_ok=True)

    def reset(self, date):
        previous = self.state
        self.state = seed(date)
        try:
            self.save()
        except OSError:
            self.state = previous
            raise


class DemoHealth:
    def today(self, state, date):
        return state["day_data"].get(date, state["day_data"][state["date"]])
