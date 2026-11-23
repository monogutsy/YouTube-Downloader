"""Local preferences and a bounded, URL-free download history."""

import ctypes
import json
import logging
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

HISTORY_LIMIT = 30
APP_FOLDER = "YouTubeDownloader"


def data_directory() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    return (Path(local) if local else Path.home() / "AppData" / "Local") / APP_FOLDER


def default_download_directory() -> Path:
    if os.name == "nt":
        folder_id = uuid.UUID("374de290-123f-4565-9164-39c4925e467b")
        guid = (ctypes.c_ubyte * 16).from_buffer_copy(folder_id.bytes_le)
        result = ctypes.c_void_p()
        try:
            get_path = ctypes.windll.shell32.SHGetKnownFolderPath
            get_path.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
            get_path.restype = ctypes.c_long
            if get_path(ctypes.byref(guid), 0, None, ctypes.byref(result)) == 0 and result.value:
                folder = Path(ctypes.wstring_at(result))
                if folder.is_dir():
                    return folder
        except OSError:
            pass
        finally:
            if result.value:
                free = ctypes.windll.ole32.CoTaskMemFree
                free.argtypes = [ctypes.c_void_p]
                free.restype = None
                free(result)
    folder = Path.home() / "Downloads"
    return folder if folder.is_dir() else Path.home()


@dataclass(frozen=True)
class Preferences:
    folder: Path
    single_video: bool = True


@dataclass(frozen=True)
class HistoryEntry:
    title: str
    status: str
    created_at: str
    path: str = ""

    @classmethod
    def finished(cls, title: str, status: str, path: Path | None = None) -> "HistoryEntry":
        return cls(title, status, datetime.now().astimezone().isoformat(timespec="seconds"), str(path or ""))


class LocalStore:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or data_directory()

    def load_preferences(self) -> Preferences:
        stored = self._read("settings.json")
        folder = default_download_directory()
        single_video = True
        if isinstance(stored, dict):
            saved_folder = stored.get("folder")
            if isinstance(saved_folder, str) and saved_folder and "\0" not in saved_folder:
                candidate = Path(saved_folder)
                if candidate.is_absolute():
                    folder = candidate
            if isinstance(stored.get("single_video"), bool):
                single_video = stored["single_video"]
        return Preferences(folder, single_video)

    def save_preferences(self, preferences: Preferences) -> None:
        self._write(
            "settings.json",
            {"folder": str(preferences.folder), "single_video": preferences.single_video},
        )

    def load_history(self) -> list[HistoryEntry]:
        saved = self._read("history.json")
        if not isinstance(saved, list):
            return []
        entries = []
        for item in saved[:HISTORY_LIMIT]:
            if not isinstance(item, dict):
                continue
            values = [item.get(key, "") for key in ("title", "status", "created_at", "path")]
            if all(isinstance(value, str) and "\0" not in value for value in values):
                if values[0] and values[1] in {"Completed", "Failed", "Canceled"}:
                    entries.append(HistoryEntry(*values))
        return entries

    def save_history(self, entries: list[HistoryEntry]) -> None:
        self._write("history.json", [asdict(entry) for entry in entries[:HISTORY_LIMIT]])

    def _read(self, filename: str):
        try:
            return json.loads((self.directory / filename).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _write(self, filename: str, payload) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.directory, suffix=".tmp", delete=False
            ) as stream:
                temporary = Path(stream.name)
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            temporary.replace(self.directory / filename)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def logger(self) -> logging.Logger:
        logger = logging.getLogger(APP_FOLDER)
        if logger.handlers:
            return logger
        logger.setLevel(logging.INFO)
        logger.propagate = False
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(
                self.directory / "app.log", maxBytes=256_000, backupCount=1, encoding="utf-8"
            )
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        except OSError:
            handler = logging.NullHandler()
        logger.addHandler(handler)
        return logger
