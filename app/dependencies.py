"""Locate and check the local executables used by yt-dlp."""

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


@dataclass(frozen=True)
class Dependencies:
    ffmpeg: Path | None = None
    ffprobe: Path | None = None
    deno: Path | None = None
    yt_dlp_version: str = ""
    ejs_version: str = ""
    ffmpeg_version: str = ""
    ffprobe_version: str = ""
    deno_version: str = ""
    bundled_ffmpeg: bool = False
    notes: tuple[str, ...] = ()
    audio_encoders: frozenset[str] | None = None

    @property
    def ffmpeg_path(self) -> Path | None:
        if self.ffmpeg and self.ffprobe and self.ffmpeg.parent == self.ffprobe.parent:
            # yt-dlp also resolves FFprobe relative to this executable.
            return self.ffmpeg
        return None

    @property
    def media_tools_ready(self) -> bool:
        return self.ffmpeg_path is not None


def app_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return ""


def _program_output(path: Path | None, argument: str) -> str:
    if not path:
        return ""
    try:
        result = subprocess.run(
            [str(path), argument],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout if result.returncode == 0 else ""


def _program_version(path: Path | None, name: str) -> str:
    argument = "--version" if name == "deno" else "-version"
    output = _program_output(path, argument)
    match = re.match(rf"^{name} (?:version )?(\S+)", output)
    return match.group(1) if match else ""


def _on_path(name: str, directories: tuple[Path, ...]) -> Path | None:
    return next((folder / name for folder in directories if (folder / name).is_file()), None)


def _deno_supported(version: str) -> bool:
    numbers = re.match(r"^(\d+)\.(\d+)", version)
    return bool(numbers and tuple(map(int, numbers.groups())) >= (2, 3))


def detect_dependencies() -> Dependencies:
    folder = app_directory() / "bin"
    extension = ".exe" if os.name == "nt" else ""
    names = {name: f"{name}{extension}" for name in ("ffmpeg", "ffprobe", "deno")}
    local = {name: folder / filename for name, filename in names.items()}
    # Windows can search the current directory before PATH for bare names.
    entries = (Path(entry.strip('"')) for entry in os.get_exec_path())
    path = tuple(entry for entry in entries if entry.is_absolute())
    notes = []

    ffmpeg = local["ffmpeg"]
    ffprobe = local["ffprobe"]
    ffmpeg_version = _program_version(ffmpeg, "ffmpeg") if ffmpeg.is_file() else ""
    ffprobe_version = _program_version(ffprobe, "ffprobe") if ffprobe.is_file() else ""
    bundled_ffmpeg = bool(ffmpeg_version and ffprobe_version)
    if not bundled_ffmpeg:
        if ffmpeg.exists() or ffprobe.exists():
            notes.append("The local bin folder needs a working FFmpeg and FFprobe pair. Checked PATH instead.")
        paired = tuple(
            entry for entry in path
            if (entry / names["ffmpeg"]).is_file() and (entry / names["ffprobe"]).is_file()
        )
        ffmpeg = _on_path(names["ffmpeg"], paired or path)
        ffprobe = _on_path(names["ffprobe"], paired or path)
        ffmpeg_version = _program_version(ffmpeg, "ffmpeg")
        ffprobe_version = _program_version(ffprobe, "ffprobe")
        if ffmpeg and ffprobe and ffmpeg.parent != ffprobe.parent:
            notes.append("Use FFmpeg and FFprobe from the same bin folder to enable downloads.")

    deno = local["deno"]
    deno_version = _program_version(deno, "deno") if deno.is_file() else ""
    if not _deno_supported(deno_version):
        if deno.exists():
            notes.append("The Deno executable in bin needs version 2.3 or later. Checked PATH instead.")
        deno = _on_path(names["deno"], path)
        deno_version = _program_version(deno, "deno") or deno_version
    if deno_version and not _deno_supported(deno_version):
        notes.append("Update Deno to version 2.3 or later for YouTube support.")
    encoder_output = _program_output(ffmpeg if ffmpeg_version else None, "-encoders")
    encoders = frozenset(re.findall(r"^\s*A\S{5}\s+(?![=])(\S+)", encoder_output, re.MULTILINE))

    return Dependencies(
        ffmpeg=ffmpeg if ffmpeg_version else None,
        ffprobe=ffprobe if ffprobe_version else None,
        deno=deno if _deno_supported(deno_version) else None,
        yt_dlp_version=_package_version("yt-dlp"),
        ejs_version=_package_version("yt-dlp-ejs"),
        ffmpeg_version=ffmpeg_version,
        ffprobe_version=ffprobe_version,
        deno_version=deno_version,
        bundled_ffmpeg=bundled_ffmpeg,
        notes=tuple(notes),
        audio_encoders=encoders if encoder_output else None,
    )
