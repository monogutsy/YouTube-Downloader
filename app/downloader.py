"""Run yt-dlp on a worker thread and publish only finished media files."""

from __future__ import annotations

import errno
import logging
import math
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from time import monotonic
from typing import TYPE_CHECKING, Any
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from yt_dlp import YoutubeDL

from .formats import DownloadOptions, DownloadPlan, FormatError, download_plan

if TYPE_CHECKING:
    from .dependencies import Dependencies


PLAYLIST_PREVIEW_LIMIT = 50
THUMBNAIL_MAX_BYTES = 4 * 1024 * 1024
LOG = logging.getLogger('YouTubeDownloader.downloader')

# Keep expiring stream URLs, cookies, headers and extractor internals on the worker.
PREVIEW_FORMAT_FIELDS = frozenset({
    'format_id', 'ext', 'protocol', 'height', 'width', 'resolution', 'fps',
    'vcodec', 'acodec', 'tbr', 'vbr', 'abr', 'asr', 'audio_channels', 'filesize',
    'filesize_approx', 'has_drm', 'format', 'format_note', 'language',
})


class DownloaderError(RuntimeError):
    """A download or analysis error suitable for showing in the interface."""


class Cancelled(DownloaderError):
    """The worker stopped at a cancellation boundary."""


@dataclass(frozen=True)
class PlaylistEntry:
    url: str
    title: str
    duration: float | None = None


@dataclass(frozen=True)
class MediaInfo:
    url: str
    title: str
    uploader: str | None
    duration: float | None
    thumbnail: str | None
    formats: list[dict[str, Any]]
    entries: tuple[PlaylistEntry, ...] = ()
    playlist_count: int | None = None
    is_playlist: bool = False


@dataclass(frozen=True)
class Progress:
    phase: str
    percent: float | None = None
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    speed: float | None = None
    eta: float | None = None
    detail: str = ''


def validate_url(value: str) -> str:
    """Accept a single HTTP(S) URL without embedded credentials."""
    url = value.strip()
    if any(char.isspace() or ord(char) < 32 for char in url):
        raise DownloaderError('Paste a single video or playlist link without spaces.')
    try:
        parts = urlsplit(url)
        valid = parts.scheme in {'http', 'https'} and bool(parts.hostname)
        port = parts.port
        valid = valid and port != 0 and '\\' not in parts.netloc
    except ValueError:
        valid = False
    if not valid:
        raise DownloaderError('Paste a complete link starting with https:// or http://.')
    if parts.username is not None or parts.password is not None:
        raise DownloaderError('Use a link without a username or password.')
    return url


def _usable_url(value: Any) -> str | None:
    if isinstance(value, str):
        try:
            return validate_url(value)
        except DownloaderError:
            pass
    return None


def _check_cancel(cancel: Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise Cancelled('Canceled.')


def fetch_thumbnail(info: MediaInfo, cancel: Event | None = None) -> bytes | None:
    """Fetch a bounded preview without forwarding website credentials."""
    _check_cancel(cancel)
    thumbnail = _usable_url(info.thumbnail)
    if not thumbnail:
        return None
    try:
        request = Request(thumbnail, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'image/*'})
        with urlopen(request, timeout=5) as response:
            if not response.headers.get('Content-Type', '').lower().startswith('image/'):
                return None
            data = bytearray()
            deadline = monotonic() + 8
            while len(data) <= THUMBNAIL_MAX_BYTES and monotonic() < deadline:
                _check_cancel(cancel)
                chunk = response.read1(65536)
                if not chunk:
                    return bytes(data) or None
                data.extend(chunk)
    except (OSError, URLError, ValueError):
        LOG.info('Thumbnail preview was unavailable.')
    return None


def _friendly_error(error: Exception | str, action: str) -> str:
    """Classify errors using raw text without copying it to the UI or logs."""
    if isinstance(error, (DownloaderError, FormatError)):
        return str(error)
    note = str(error).lower()
    if 'javascript runtime' in note or 'challenge solving' in note or 'challenge solver' in note:
        return 'YouTube needs a working Deno runtime and yt-dlp EJS. Check Settings and try again.'
    if 'ffmpeg not found' in note or 'ffprobe not found' in note or 'ffmpeg is not installed' in note:
        return 'FFmpeg or FFprobe could not be run. Check their locations in Settings.'
    if isinstance(error, OSError) and (error.errno == errno.ENOSPC or getattr(error, 'winerror', None) == 112):
        return 'The save drive is full. Free disk space or choose another folder.'
    if 'no space left' in note or 'disk full' in note or 'not enough space' in note:
        return 'The save drive is full. Free disk space or choose another folder.'
    if isinstance(error, PermissionError) or 'permission denied' in note or 'access is denied' in note:
        return 'Windows denied access to a file or folder. Choose a writable save folder and try again.'
    if 'file name too long' in note or 'filename or extension is too long' in note or 'winerror 206' in note:
        return 'The output path is too long. Choose a save folder closer to the drive root.'
    if 'unsupported url' in note or 'no suitable extractor' in note:
        return 'This site or link is unsupported. Try the full page URL for the video.'
    if 'drm' in note:
        return 'This media is DRM-protected and cannot be downloaded by this app.'
    if 'region' in note or 'country' in note or 'geo restricted' in note:
        return 'The source does not make this media available in your region.'
    if any(word in note for word in ('private video', 'sign in', 'login required', 'members-only', 'age-restricted', 'not a bot')):
        return 'The site requires sign-in or access to this media. Try a publicly accessible link.'
    if any(word in note for word in ('requested format', 'no video formats', 'no formats', 'no playable formats')):
        return 'No usable format matched the selection. Analyze the link and try another format or quality.'
    if 'http error 403' in note or 'http error 401' in note:
        return 'The source refused the request. Check that the link is available and try analyzing again.'
    if 'http error 429' in note or 'too many requests' in note:
        return 'The site is rate limiting requests. Wait a few minutes and try again.'
    if any(word in note for word in ('timed out', 'timeout', 'connection', 'network', 'getaddrinfo', 'certificate', 'http error 5')):
        return 'The network request failed. Check your internet connection and try again.'
    if 'postprocessing' in note or 'conversion failed' in note or 'ffmpeg exited' in note:
        return 'FFmpeg could not finish the file. Check Settings, then try another output format.'
    if any(word in note for word in ('unavailable', 'not available', 'removed', 'http error 404', 'does not exist')):
        return 'The media is unavailable. Check that the link still opens in your browser.'
    if isinstance(error, OSError):
        return 'A file or program could not be opened. Check your save folder and the dependencies in Settings.'
    return f'The app could not {action} this media. Try another link or open the diagnostic log in Settings.'


class _YtDlpLogger:
    def debug(self, _message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        summary = _friendly_error(message, 'process')
        if not summary.startswith('The app could not'):
            LOG.warning('yt-dlp: %s', summary)

    def error(self, _message: str) -> None:
        # Errors are classified and logged by the worker once the operation returns.
        pass


def _duration(value: Any) -> float | None:
    if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
        return float(value)
    return None


def _playlist_entries(info: dict[str, Any]) -> tuple[PlaylistEntry, ...]:
    entries = []
    seen: set[str] = set()
    for item in info.get('entries') or ():
        if not item or item.get('_type') in {'playlist', 'multi_video'}:
            continue
        url = _usable_url(item.get('webpage_url')) or _usable_url(item.get('url'))
        if not url and item.get('ie_key') == 'Youtube':
            video_id = item.get('id')
            if isinstance(video_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
                url = f'https://www.youtube.com/watch?v={video_id}'
        if url and url not in seen:
            seen.add(url)
            entries.append(PlaylistEntry(url, item.get('title') or 'Untitled video', _duration(item.get('duration'))))
    return tuple(entries)


def _publish_file(staged_file: Path, destination: Path) -> Path:
    """Choose a free name and publish without overwriting another process's file."""
    for index in range(1, 10_001):
        name = staged_file.name if index == 1 else f'{staged_file.stem} ({index}){staged_file.suffix}'
        target = destination / name
        try:
            if os.name == 'nt':
                staged_file.rename(target)
            else:
                # Windows rename refuses existing files. POSIX rename would overwrite them.
                os.link(staged_file, target)
        except FileExistsError:
            continue
        except PermissionError:
            if target.is_dir():
                continue
            raise
        return target
    raise DownloaderError('Too many files share this name. Choose another save folder.')


class Downloader:
    def __init__(self, dependencies: Dependencies) -> None:
        self.dependencies = dependencies
        os.environ['YTDLP_NO_PLUGINS'] = '1'

    def _base_options(self, url: str) -> dict[str, Any]:
        host = (urlsplit(url).hostname or '').rstrip('.').lower()
        if host == 'youtu.be' or host == 'youtube.com' or host.endswith(('.youtube.com', '.youtu.be')):
            if not self.dependencies.deno or not self.dependencies.ejs_version:
                raise DownloaderError('YouTube needs Deno and yt-dlp EJS. Check Settings before trying again.')
        return {
            'quiet': True,
            'noprogress': True,
            'logger': _YtDlpLogger(),
            'ignoreerrors': False,
            'socket_timeout': 12,
            'retries': 3,
            'fragment_retries': 3,
            'extractor_retries': 2,
            'skip_unavailable_fragments': False,
            'cachedir': False,
            'allow_playlist_files': False,
            'js_runtimes': {'deno': {'path': str(self.dependencies.deno)}} if self.dependencies.deno else {},
            'remote_components': [],
            'ffmpeg_location': str(self.dependencies.ffmpeg_path) if self.dependencies.ffmpeg_path else None,
        }

    @staticmethod
    def _filter(info: dict[str, Any], cancel: Event | None, *, download: bool) -> None:
        _check_cancel(cancel)
        if info.get('is_live') or info.get('live_status') in {'is_live', 'is_upcoming'}:
            raise DownloaderError('Live or upcoming streams are unavailable here. Try the recording after it is published.')
        if download and info.get('playlist_index') is not None:
            raise DownloaderError('Analyze the playlist and queue its individual videos first.')

    def analyze(self, url: str, single_video: bool = True, cancel: Event | None = None) -> MediaInfo:
        _check_cancel(cancel)
        url = validate_url(url)
        params = self._base_options(url)
        params.update({
            'noplaylist': single_video,
            'extract_flat': 'in_playlist',
            'playlist_items': f'1:{1 if single_video else PLAYLIST_PREVIEW_LIMIT}',
            'match_filter': lambda info, **_: self._filter(info, cancel, download=False),
        })
        try:
            with YoutubeDL(params) as ydl:
                info = ydl.extract_info(url, download=False)
            _check_cancel(cancel)
            if not info:
                raise DownloaderError('The link returned no video information. Check that it opens in your browser.')
            is_playlist = info.get('_type') in {'playlist', 'multi_video', 'compat_list'}
            if is_playlist and single_video:
                raise DownloaderError('This link opens a playlist. Clear Single video only and analyze it again.')
            entries = _playlist_entries(info) if is_playlist else ()
            if is_playlist and not entries:
                raise DownloaderError('No individual video links were available in the playlist preview.')
            formats = [
                {key: value for key, value in item.items() if key in PREVIEW_FORMAT_FIELDS}
                for item in info.get('formats') or ()
            ]
            count = info.get('playlist_count')
            return MediaInfo(
                url=_usable_url(info.get('webpage_url')) or url,
                title=info.get('title') or ('Untitled playlist' if is_playlist else 'Untitled video'),
                uploader=info.get('channel') or info.get('uploader') or None,
                duration=_duration(info.get('duration')),
                thumbnail=_usable_url(info.get('thumbnail')),
                formats=formats,
                entries=entries,
                playlist_count=count if isinstance(count, int) and count > 0 else None,
                is_playlist=is_playlist,
            )
        except Cancelled:
            raise
        except Exception as error:
            _check_cancel(cancel)
            message = _friendly_error(error, 'analyze')
            LOG.warning('Analysis failed (%s). %s', type(error).__name__, message)
            raise DownloaderError(message) from None

    def download(
        self,
        url: str,
        destination: Path,
        settings: DownloadOptions,
        progress: Callable[[Progress], None],
        cancel: Event,
    ) -> Path:
        _check_cancel(cancel)
        url = validate_url(url)
        if not self.dependencies.media_tools_ready:
            raise DownloaderError('Downloads need FFmpeg and FFprobe from the same folder. Check Settings.')
        params = self._base_options(url)
        progress(Progress('fetching', detail='Fetching current media information…'))
        try:
            plan = download_plan(settings, on_selection=lambda note: progress(Progress('fetching', detail=note)))
            destination = Path(destination).expanduser().resolve()
            if not destination.is_dir():
                raise DownloaderError('The save folder is unavailable. Choose an existing folder and try again.')
            directory = destination / f'.youtube-downloader-{uuid4().hex[:12]}'
            directory.mkdir()
            try:
                staged = self._download_into(url, directory, params, plan, progress, cancel)
                _check_cancel(cancel)
                progress(Progress('finalizing', detail='Verifying the saved media with FFprobe…'))
                if staged.is_symlink() or staged.resolve().parent != directory.resolve():
                    raise DownloaderError('The download did not produce a local media file.')
                self._verify_file(staged, settings.kind, plan.extension)
                _check_cancel(cancel)
                result = _publish_file(staged, destination)
            finally:
                try:
                    shutil.rmtree(directory)
                except OSError:
                    LOG.warning('The temporary download folder could not be removed.')
            progress(Progress('completed', percent=100, detail='Saved successfully.'))
            LOG.info('Download completed.')
            return result
        except Cancelled:
            LOG.info('Download canceled.')
            raise
        except Exception as error:
            _check_cancel(cancel)
            message = _friendly_error(error, 'download')
            LOG.warning('Download failed (%s). %s', type(error).__name__, message)
            raise DownloaderError(message) from None

    def _verify_file(self, file: Path, kind: str, extension: str | None) -> None:
        error = 'The output could not be verified as playable media. Try another format or link.'
        if not file.is_file() or file.stat().st_size <= 0:
            raise DownloaderError(error)
        if extension and file.suffix.lower() != f'.{extension}':
            raise DownloaderError(error)
        try:
            result = subprocess.run(
                [str(self.dependencies.ffprobe), '-v', 'error', '-protocol_whitelist', 'file',
                 '-select_streams', 'V' if kind == 'video' else 'a',
                 '-show_entries', 'stream=index', '-of', 'csv=p=0', str(file)],
                capture_output=True, timeout=12, check=False,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
        except subprocess.TimeoutExpired:
            raise DownloaderError('Checking the output timed out. Try another format or link.') from None
        if result.returncode or not result.stdout.strip():
            raise DownloaderError(error)

    def _download_into(
        self,
        url: str,
        directory: Path,
        params: dict[str, Any],
        plan: DownloadPlan,
        progress: Callable[[Progress], None],
        cancel: Event,
    ) -> Path:
        final_paths: list[str] = []
        last_update = 0.0
        last_postprocessor = ''

        def transfer_hook(event: dict[str, Any]) -> None:
            nonlocal last_update
            _check_cancel(cancel)
            status = event.get('status')
            if status not in {'downloading', 'finished'}:
                return
            now = monotonic()
            if status == 'downloading' and now - last_update < 0.15:
                return
            last_update = now if status == 'downloading' else 0.0
            info = event.get('info_dict') or {}
            label = 'Audio stream' if info.get('vcodec') == 'none' else (
                'Video stream' if info.get('acodec') == 'none' else 'Media stream'
            )
            downloaded = event.get('downloaded_bytes')
            total = event.get('total_bytes') or event.get('total_bytes_estimate')
            percent = min(100.0, max(0.0, 100.0 * downloaded / total)) if downloaded is not None and total else None
            progress(Progress(
                'downloading', percent, downloaded, total, event.get('speed'), event.get('eta'),
                f'{label} received.' if status == 'finished' else f'Downloading {label.lower()}…',
            ))

        def postprocessor_hook(event: dict[str, Any]) -> None:
            nonlocal last_postprocessor
            _check_cancel(cancel)
            if event.get('status') != 'started':
                return
            name = event.get('postprocessor') or ''
            if name == last_postprocessor or name == 'MoveFiles':
                return
            last_postprocessor = name
            info = event.get('info_dict') or {}
            if name == 'VideoRemuxer' and info.get('ext') == plan.extension:
                return
            if name == 'EncodeAudio' and plan.extension is None and info.get('vcodec') == 'none':
                return
            if name == 'Merger':
                progress(Progress('merging', detail='Merging video and audio with FFmpeg…'))
            else:
                detail = 'Preparing the output with FFmpeg…'
                if name in {'EncodeAudio', 'ExtractAudio'}:
                    detail = 'Preparing the audio output with FFmpeg…'
                elif name == 'VideoRemuxer':
                    detail = 'Remuxing into the selected container…'
                progress(Progress('converting', detail=detail))

        params.update({
            'noplaylist': True,
            'extract_flat': 'in_playlist',
            'playlist_items': '1',
            'match_filter': lambda info, **_: self._filter(info, cancel, download=True),
            'paths': {'home': str(directory)},
            'outtmpl': '%(title).120B [%(id).40B].%(ext)s',
            'windowsfilenames': True,
            'overwrites': False,
            'format': plan.format_selector,
            'postprocessors': plan.postprocessors,
            'progress_hooks': [transfer_hook],
            'postprocessor_hooks': [postprocessor_hook],
            'post_hooks': [final_paths.append],
        })
        if plan.merge_output_format:
            params['merge_output_format'] = plan.merge_output_format
        with YoutubeDL(params) as ydl:
            processor = plan.make_audio_postprocessor(ydl)
            if processor:
                ydl.add_post_processor(processor)
            info = ydl.extract_info(url, download=True)
        _check_cancel(cancel)
        if info and info.get('_type') in {'playlist', 'multi_video', 'compat_list'}:
            raise DownloaderError('Analyze the playlist and queue its individual videos first.')
        if len(final_paths) != 1:
            raise DownloaderError('The download did not produce a single output file. Try another link or format.')
        return Path(final_paths[0])
