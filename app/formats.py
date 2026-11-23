"""Source-aware media choices and yt-dlp download plans."""

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
import os
from typing import Any
from uuid import uuid4

from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor
from yt_dlp.utils import MEDIA_EXTENSIONS, PostProcessingError


VIDEO_FORMATS = ("MP4", "MKV", "WebM", "MOV")
BEST_ORIGINAL = "Best original audio"
OGG_OPUS = "OGG (Opus)"
OGG_VORBIS = "OGG (Vorbis)"
AUDIO_FORMATS = (BEST_ORIGINAL, "MP3", "WAV", "FLAC", OGG_OPUS, OGG_VORBIS, "M4A")
BITRATES = ("128", "192", "256", "320")
LOSSY_AUDIO_FORMATS = frozenset(("MP3", "OGG", OGG_OPUS, OGG_VORBIS, "M4A"))

BEST_RESOLUTION = "Best available"
_RESOLUTION_CAPS = {
    BEST_RESOLUTION: None,
    "360p": 360,
    "480p": 480,
    "720p": 720,
    "1080p": 1080,
    "1440p (2K)": 1440,
    "2160p (4K)": 2160,
}
RESOLUTIONS = tuple(_RESOLUTION_CAPS)

_VIDEO_CODECS = {
    "avc": "H.264", "avc1": "H.264", "avc3": "H.264", "h264": "H.264",
    "hev1": "HEVC", "hvc1": "HEVC", "h265": "HEVC", "hevc": "HEVC",
    "av01": "AV1", "av1": "AV1", "vp08": "VP8", "vp8": "VP8",
    "vp09": "VP9", "vp9": "VP9", "vp9_2": "VP9", "mp4v": "MPEG-4",
    "mpeg4": "MPEG-4", "mjpeg": "MJPEG", "jpeg": "MJPEG", "prores": "ProRes",
    "ap4h": "ProRes", "ap4x": "ProRes", "apch": "ProRes", "apcn": "ProRes",
    "apcs": "ProRes", "apco": "ProRes",
}
_AUDIO_CODECS = {
    "mp4a": "AAC", "aac": "AAC", "opus": "Opus", "vorbis": "Vorbis",
    "mp3": "MP3", "alac": "ALAC", "flac": "FLAC", "ac-3": "AC-3",
    "ac3": "AC-3", "ec-3": "E-AC-3", "eac3": "E-AC-3", "ipcm": "PCM",
    "fpcm": "PCM", "lpcm": "PCM", "sowt": "PCM", "twos": "PCM",
}
_MUX_CODECS = {
    "MP4": (
        frozenset(("H.264", "HEVC", "AV1", "VP9", "MPEG-4")),
        frozenset(("AAC", "MP3", "ALAC", "AC-3", "E-AC-3")),
    ),
    "MOV": (
        frozenset(("H.264", "HEVC", "MPEG-4", "MJPEG", "ProRes")),
        frozenset(("AAC", "MP3", "ALAC", "PCM", "AC-3")),
    ),
    "WebM": (
        frozenset(("VP8", "VP9", "AV1")),
        frozenset(("Opus", "Vorbis")),
    ),
}
_AUDIO_EXTS = frozenset((*MEDIA_EXTENSIONS.audio, "aif", "ac3", "caf", "eac3"))
_MEDIA_EXTS = _AUDIO_EXTS.union(MEDIA_EXTENSIONS.video, ("m2ts", "mpeg", "ts"))

_AUDIO_ENCODINGS = {
    "MP3": ("libmp3lame", "mp3", "mp3"),
    "WAV": ("pcm_s24le", "wav", "wav"),
    "FLAC": ("flac", "flac", "flac"),
    OGG_OPUS: ("libopus", "ogg", "ogg"),
    OGG_VORBIS: ("libvorbis", "ogg", "ogg"),
    "M4A": ("aac", "ipod", "m4a"),
}
_AUDIO_ENCODINGS["OGG"] = _AUDIO_ENCODINGS[OGG_OPUS]
AUDIO_ENCODERS = frozenset(encoder for encoder, _, _ in _AUDIO_ENCODINGS.values())

_Stream = Mapping[str, Any]


class FormatError(ValueError):
    """The source cannot satisfy the requested download options."""


@dataclass(frozen=True)
class DownloadOptions:
    kind: str
    output_format: str
    quality: str | int | None = None


@dataclass(frozen=True)
class FormatAvailability:
    video: tuple[str, ...]
    audio: tuple[str, ...]
    source_summary: str
    _streams: tuple[_Stream, ...] = field(repr=False)

    def resolutions(self, container: str) -> tuple[str, ...]:
        return tuple(
            label for label, cap in _RESOLUTION_CAPS.items()
            if _video_choice(self._streams, container, cap)
        )


@dataclass(frozen=True)
class DownloadPlan:
    format_selector: Callable[[_Stream], Sequence[_Stream]]
    merge_output_format: str | None
    postprocessors: tuple[dict[str, str], ...]
    extension: str | None
    _audio_format: str | None = field(default=None, repr=False)
    _bitrate: str | None = field(default=None, repr=False)

    def make_audio_postprocessor(self, ydl) -> "EncodeAudioPP | None":
        if self._audio_format is None:
            return None
        return EncodeAudioPP(ydl, self._audio_format, self._bitrate)


def _ext(stream: _Stream) -> str:
    return str(stream.get("ext") or "").lower()


def _codec(stream: _Stream, *, video: bool) -> str:
    codec = str(stream.get("vcodec" if video else "acodec") or "").lower()
    prefix = codec.split(".", 1)[0]
    if not video and prefix.startswith("pcm_"):
        return "PCM"
    if not video and codec.startswith(("mp4a.69", "mp4a.6b")):
        return "MP3"
    aliases = _VIDEO_CODECS if video else _AUDIO_CODECS
    return aliases.get(prefix, prefix)


def _has_video(stream: _Stream) -> bool:
    codec = _codec(stream, video=True)
    return codec != "none" and (bool(codec) or _ext(stream) not in _AUDIO_EXTS)


def _has_audio(stream: _Stream) -> bool:
    return _codec(stream, video=False) != "none"


def _streams(info: _Stream) -> tuple[_Stream, ...]:
    streams = info.get("formats") or (info,)
    return tuple(
        stream for stream in streams
        if isinstance(stream, Mapping)
        and stream.get("format_id") is not None
        and not stream.get("has_drm")
        and _ext(stream) in _MEDIA_EXTS
    )


def _number(stream: _Stream, key: str) -> float:
    try:
        number = float(stream.get(key) or 0)
    except (ValueError, TypeError, OverflowError):
        return 0
    return number if 0 < number < float("inf") else 0


def _resolution(stream: _Stream) -> float:
    height = _number(stream, "height")
    width = _number(stream, "width")
    return min(height, width) if width else height


def _compatible(stream: _Stream, container: str, *, video: bool) -> bool:
    if container == "MKV":
        return True
    rules = _MUX_CODECS.get(container)
    if rules is None:
        return False
    codec = _codec(stream, video=video)
    return codec in rules[0 if video else 1] if codec else _ext(stream) == container.lower()


@dataclass(frozen=True)
class _VideoChoice:
    video: _Stream
    external_audio: _Stream | None = None

    @property
    def audio(self) -> _Stream | None:
        if self.external_audio is not None:
            return self.external_audio
        return self.video if _has_audio(self.video) else None


def _video_choice(
    streams: tuple[_Stream, ...], container: str, cap: int | None
) -> _VideoChoice | None:
    prefer_common_codecs = container in ("MP4", "MOV")
    has_source_audio = any(_has_audio(stream) for stream in streams)
    compatible_audio = (
        stream for stream in reversed(streams)
        if not _has_video(stream) and _has_audio(stream)
        and _compatible(stream, container, video=False)
    )
    external_audio = max(
        compatible_audio,
        key=lambda stream: prefer_common_codecs and _codec(stream, video=False) == "AAC",
        default=None,
    )
    candidates = []
    for index, stream in enumerate(streams):
        resolution = _resolution(stream)
        if not _has_video(stream) or not _compatible(stream, container, video=True):
            continue
        if cap is not None and not 0 < resolution <= cap:
            continue
        if _has_audio(stream):
            if not _compatible(stream, container, video=False):
                continue
            choice = _VideoChoice(stream)
        elif external_audio is not None or not has_source_audio:
            choice = _VideoChoice(stream, external_audio)
        else:
            continue
        h264 = prefer_common_codecs and _codec(stream, video=True) == "H.264"
        aac = (
            prefer_common_codecs and choice.audio is not None
            and _codec(choice.audio, video=False) == "AAC"
        )
        native_container = _ext(stream) == container.lower()
        candidates.append(((resolution, _number(stream, "fps"), h264, aac, native_container, index), choice))

    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate[0])[1]


def _audio_choice(streams: tuple[_Stream, ...]) -> _Stream | None:
    with_audio = [stream for stream in reversed(streams) if _has_audio(stream)]
    return next(
        (stream for stream in with_audio if not _has_video(stream)),
        with_audio[0] if with_audio else None,
    )


def supported_audio_outputs(audio_encoders: Collection[str] | None = None) -> tuple[str, ...]:
    return tuple(
        label for label in AUDIO_FORMATS
        if label == BEST_ORIGINAL or audio_encoders is None
        or _AUDIO_ENCODINGS[label][0] in audio_encoders
    )


def discover_formats(
    info: _Stream, *, audio_encoders: Collection[str] | None = None
) -> FormatAvailability:
    streams = _streams(info)
    video = tuple(container for container in VIDEO_FORMATS if _video_choice(streams, container, None))
    audio = supported_audio_outputs(audio_encoders) if _audio_choice(streams) is not None else ()

    resolutions = sorted({_resolution(stream) for stream in streams if _has_video(stream)} - {0})
    if resolutions:
        labels = ", ".join(f"{resolution:g}p" for resolution in resolutions[-6:])
        source_summary = f"Source resolutions · {labels}"
    elif any(_has_video(stream) for stream in streams):
        source_summary = "Source resolution unavailable"
    elif audio:
        source_summary = "Audio-only source"
    else:
        source_summary = "No downloadable media formats"
    return FormatAvailability(video, audio, source_summary, streams)


def _validated_quality(options: DownloadOptions) -> tuple[int | None, str | None]:
    if options.kind == "video" and options.output_format in VIDEO_FORMATS:
        quality = options.quality if options.quality is not None else BEST_RESOLUTION
        if isinstance(quality, int) and quality in _RESOLUTION_CAPS.values():
            return quality, None
        if quality in _RESOLUTION_CAPS:
            return _RESOLUTION_CAPS[quality], None
        raise FormatError("Choose one of the available resolution presets.")
    if options.kind == "audio" and (options.output_format == BEST_ORIGINAL or options.output_format in _AUDIO_ENCODINGS):
        if options.output_format not in LOSSY_AUDIO_FORMATS:
            return None, None
        bitrate = "192" if options.quality is None else str(options.quality)
        if bitrate in BITRATES:
            return None, bitrate
        raise FormatError("Choose an encoding target from 128, 192, 256, or 320 kbps.")
    raise FormatError("Choose a supported video or audio format.")


def _pick(
    streams: tuple[_Stream, ...], options: DownloadOptions, cap: int | None
) -> _Stream | _VideoChoice:
    if options.kind == "video":
        choice = _video_choice(streams, options.output_format, cap)
        if choice is not None:
            return choice
        if cap and _video_choice(streams, options.output_format, None):
            raise FormatError(
                f"No {options.output_format} video fits the {cap}p cap. Choose a higher cap or Best available."
            )
        raise FormatError(
            f"No source streams fit {options.output_format}. Try another container, such as MKV."
        )
    audio = _audio_choice(streams)
    if audio is None:
        raise FormatError("This source has no downloadable audio stream.")
    return audio


def _note(choice: _Stream | _VideoChoice, options: DownloadOptions, cap: int | None, bitrate: str | None) -> str:
    if isinstance(choice, _VideoChoice):
        height = _number(choice.video, "height")
        width = _number(choice.video, "width")
        resolution = _resolution(choice.video)
        video = _codec(choice.video, video=True)
        audio = _codec(choice.audio, video=False) if choice.audio is not None else "silent"
        details = " · ".join(part for part in (
            f"{resolution:g}p" if resolution else "Source resolution unknown",
            f"{width:g} × {height:g}" if 0 < width < height else "",
            " + ".join(codec for codec in (video, audio) if codec),
        ) if part)
        if cap and resolution < cap:
            return f"{details} · below the {cap}p cap"
        return details
    if options.output_format == BEST_ORIGINAL:
        if _has_video(choice):
            return "Copies the original audio into an MKA container."
        return f"Preserves the original {_ext(choice).upper()} audio stream."
    if bitrate:
        return f"{bitrate} kbps encoding target. Source quality limits the result."
    return f"Encodes audio as {options.output_format}."


def selection_note(info: _Stream, options: DownloadOptions) -> str:
    cap, bitrate = _validated_quality(options)
    return _note(_pick(_streams(info), options, cap), options, cap, bitrate)


def download_plan(
    options: DownloadOptions, on_selection: Callable[[str], None] | None = None
) -> DownloadPlan:
    cap, bitrate = _validated_quality(options)
    container = options.output_format.lower()

    def selector(context: _Stream) -> Sequence[_Stream]:
        selected = _pick(_streams(context), options, cap)
        if on_selection is not None:
            on_selection(_note(selected, options, cap, bitrate))
        if not isinstance(selected, _VideoChoice):
            return (selected,)
        video, audio = selected.video, selected.external_audio
        if audio is None:
            return (video,)
        return ({
            "format_id": f"{video['format_id']}+{audio['format_id']}",
            "ext": container,
            "requested_formats": [video, audio],
            "protocol": "+".join(stream["protocol"] for stream in (video, audio)),
        },)

    if options.kind == "video":
        return DownloadPlan(
            selector, container,
            ({"key": "FFmpegVideoRemuxer", "preferedformat": container},),
            container,
        )
    encoding = _AUDIO_ENCODINGS.get(options.output_format)
    return DownloadPlan(selector, None, (), encoding[2] if encoding else None, options.output_format, bitrate)


class EncodeAudioPP(FFmpegPostProcessor):
    """Encode to an explicit target or stream-copy audio from a combined source."""

    def __init__(self, ydl, output_format: str, bitrate: str | None):
        super().__init__(ydl)
        self.output_format = output_format
        self.bitrate = bitrate

    def run(self, info):
        if self.output_format == BEST_ORIGINAL:
            if not _has_video(info):
                return [], info
            codec, muxer, extension = "copy", "matroska", "mka"
        else:
            codec, muxer, extension = _AUDIO_ENCODINGS[self.output_format]

        source = Path(info["filepath"])
        destination = source.with_suffix(f".{extension}")
        if destination != source and destination.exists():
            raise PostProcessingError("The audio output already exists in the download's temporary folder.")

        temp = source.with_name(f".audio-{uuid4().hex}.{extension}")
        arguments = ["-map", "0:a:0", "-vn", "-c:a", codec, "-f", muxer]
        if self.bitrate:
            arguments.extend(("-b:a", f"{self.bitrate}k"))
        if self.output_format in ("MP3", "M4A", OGG_VORBIS):
            arguments.extend(("-ar", "48000"))
        # Stereo at 48 kHz supports all offered Vorbis bitrates.
        if self.output_format in ("MP3", OGG_VORBIS) or self.bitrate == "320":
            arguments.extend(("-ac", "2"))

        try:
            self.run_ffmpeg(os.fspath(source), os.fspath(temp), arguments)
            os.replace(temp, destination)
        finally:
            temp.unlink(missing_ok=True)

        info["filepath"] = os.fspath(destination)
        info["ext"] = extension
        return ([os.fspath(source)] if source != destination else []), info
