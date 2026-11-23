import json
import shutil
from pathlib import Path
from tempfile import gettempdir
from unittest import TestCase
from uuid import uuid4

from app.settings import HISTORY_LIMIT, HistoryEntry, LocalStore, Preferences


class StoreTests(TestCase):
    def setUp(self):
        self.folder = Path(gettempdir()) / f"youtube-downloader-settings-test-{uuid4().hex}"
        self.folder.mkdir()
        self.addCleanup(shutil.rmtree, self.folder)
        self.store = LocalStore(self.folder)

    def test_unicode_preferences_survive_reopening(self):
        preferences = Preferences(self.folder / "日本語 at Filipino", False)
        self.store.save_preferences(preferences)
        self.assertEqual(LocalStore(self.folder).load_preferences(), preferences)
        self.assertEqual(list(self.folder.glob("*.tmp")), [])

    def test_corrupt_and_malformed_json_fall_back(self):
        baseline = self.store.load_preferences()
        settings_file = self.folder / "settings.json"
        settings_file.write_text("{broken", encoding="utf-8")
        (self.folder / "history.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.store.load_preferences(), baseline)
        self.assertEqual(self.store.load_history(), [])
        settings_file.write_text(json.dumps({"folder": "relative", "single_video": "false"}), encoding="utf-8")
        self.assertEqual(self.store.load_preferences(), baseline)

    def test_history_is_bounded_and_keeps_final_paths(self):
        entries = [
            HistoryEntry.finished(f"Video {index}", "Completed", self.folder / f"{index}.mp4")
            for index in range(HISTORY_LIMIT + 2)
        ]
        self.store.save_history(entries)
        self.assertEqual(LocalStore(self.folder).load_history(), entries[:HISTORY_LIMIT])
        payload = json.loads((self.folder / "history.json").read_text(encoding="utf-8"))
        self.assertEqual(set(payload[0]), {"title", "status", "created_at", "path"})
