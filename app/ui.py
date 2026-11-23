"""Wire the desktop controls to background analysis and a sequential queue."""

import os
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import TclError, filedialog, messagebox

import customtkinter as ctk

from app.dependencies import Dependencies, detect_dependencies
from app.downloader import (
    Cancelled, Downloader, DownloaderError, MediaInfo, Progress, fetch_thumbnail, validate_url,
)
from app.formats import (
    AUDIO_FORMATS,
    BITRATES,
    LOSSY_AUDIO_FORMATS,
    RESOLUTIONS,
    VIDEO_FORMATS,
    DownloadOptions,
    FormatAvailability,
    FormatError,
    discover_formats,
    selection_note,
    supported_audio_outputs,
)
from app.settings import HISTORY_LIMIT, HistoryEntry, LocalStore, Preferences
from app.utils import duration_text, history_time, one_line, size_text
from app.views import BLUE, GREEN, MUTED, RED, MainView, button, choose_playlist, dialog, label

MEDIA_SUFFIXES = frozenset(
    ".mp4 .mkv .webm .mov .avi .flv .m4v .ts .mpeg .mpg .wmv .ogv .3gp "
    ".mp3 .wav .flac .ogg .oga .opus .m4a .mka .aac .aiff .aif .alac .weba .wma "
    ".vorbis .ac3 .eac3 .caf .m4b .ra .m2ts".split()
)


@dataclass(eq=False)
class Job:
    url: str
    title: str
    destination: Path
    options: DownloadOptions
    status: str = "Queued"
    stop: threading.Event = field(default_factory=threading.Event)
    phase: str = "fetching"


class DownloaderApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("YouTube Downloader")
        scale = self._get_window_scaling()
        width = min(1000, max(770, int((self.winfo_screenwidth() - 40) / scale)))
        height = min(680, max(400, int((self.winfo_screenheight() - 88) / scale)))
        self.geometry(f"{width}x{height}")
        self.minsize(min(830, width), min(610, height))
        icon = Path(__file__).resolve().parent.parent / "assets" / "app.ico"
        if icon.is_file():
            self.iconbitmap(str(icon))
        self.store = LocalStore()
        self.log = self.store.logger()
        preferences = self.store.load_preferences()
        self.history = self.store.load_history()
        self.retry_jobs: dict[int, Job] = {}
        self.dependencies: Dependencies | None = None
        self.checking = False
        self.settings_window = None
        self.events = queue.Queue()
        self.analysis_stop: threading.Event | None = None
        self.thumbnail_token: threading.Event | None = None
        self.analysis_error = False
        self.media: MediaInfo | None = None
        self.availability: FormatAvailability | None = None
        self.jobs: list[Job] = []
        self.active: Job | None = None
        self.last_output: Path | None = None
        self.closing = False
        self.preferred_format = {"video": "MP4", "audio": "MP3"}
        self.preferred_quality = {"video": "1080p", "audio": "192"}
        self.view = MainView(self, self, preferences)
        self.view.url.trace_add("write", lambda *_: self.invalidate_analysis())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh_options()
        self.render_queue()
        self.check_dependencies()
        self.after(70, self.process_events)
        self.after(400, self.log_window_state)

    def log_window_state(self):
        self.log.info("Main window state=%s, visible=%s", self.state(), bool(self.winfo_viewable()))

    def report_callback_exception(self, error_type, _error, _traceback):
        self.log.error("Desktop callback failed (%s)", error_type.__name__)

    def check_dependencies(self):
        if self.checking:
            return
        self.checking = True
        self.refresh_controls()
        self.render_settings()
        def work():
            try:
                result = detect_dependencies()
            except Exception as error:
                self.log.error("Dependency check failed (%s)", type(error).__name__)
                result = Dependencies(notes=("Could not run the checks. Refresh Settings to try again.",))
            self.events.put(("dependencies", None, result))

        threading.Thread(target=work, daemon=True).start()

    def paste(self):
        try:
            self.view.url.set(self.clipboard_get().strip())
        except TclError:
            self.view.link_status.configure(text="Clipboard has no text.", text_color=RED)

    def invalidate_analysis(self):
        if self.analysis_stop:
            self.analysis_stop.set()
            self.analysis_stop = None
        if self.thumbnail_token:
            self.thumbnail_token.set()
            self.thumbnail_token = None
        if self.media is not None or self.analysis_error:
            self.view.preview("", "", "")
        if self.analysis_error and not self.active:
            self.view.update_progress("Ready", metrics="Waiting for a download.")
        self.analysis_error = False
        self.media = self.availability = None
        self.view.link_status.configure(text="", text_color=MUTED)
        self.refresh_options()

    def single_changed(self):
        self.invalidate_analysis()
        self.save_preferences()

    def analyze(self):
        if self.closing or self.dependencies is None:
            return
        if self.analysis_stop:
            self.analysis_stop.set()
            self.analysis_stop = None
            self.view.link_status.configure(text="Analysis canceled.", text_color=MUTED)
            self.refresh_controls()
            return
        try:
            url = validate_url(self.view.url.get())
        except DownloaderError as error:
            self.view.link_status.configure(text=one_line(str(error), 58), text_color=RED)
            return

        self.invalidate_analysis()
        stop = self.analysis_stop = threading.Event()
        single = self.view.single.get()
        downloader = Downloader(self.dependencies)
        self.view.link_status.configure(text="Analyzing…", text_color=BLUE)
        self.refresh_options()

        def work():
            try:
                media = downloader.analyze(url, single_video=single, cancel=stop)
                self.events.put(("media", stop, media))
                if media.thumbnail and not stop.is_set():
                    picture = fetch_thumbnail(media, stop)
                    self.events.put(("thumbnail", stop, picture))
            except Cancelled:
                self.events.put(("analysis_canceled", stop, None))
            except DownloaderError as error:
                self.events.put(("analysis_error", stop, str(error)))
            except Exception as error:
                self.log.error("Unexpected analysis error (%s)", type(error).__name__)
                self.events.put(("analysis_error", stop, "Analysis failed. Try the link again or check Settings."))

        threading.Thread(target=work, daemon=True).start()

    def read_media(self, media: MediaInfo, picture=None):
        self.media = media
        if media.is_playlist:
            total = f" of {media.playlist_count}" if media.playlist_count and media.playlist_count > len(media.entries) else ""
            metadata = "  ·  ".join(value for value in (media.uploader, f"{len(media.entries)}{total} items") if value)
            formats = "Choose playlist items when adding to the queue."
        else:
            encoders = self.dependencies.audio_encoders if self.dependencies else None
            self.availability = discover_formats({"formats": media.formats}, audio_encoders=encoders)
            metadata = "  ·  ".join(value for value in (media.uploader, duration_text(media.duration)) if value)
            formats = self.availability.source_summary
        self.view.preview(media.title, metadata, formats, picture)
        self.refresh_options()

    def kind_changed(self, _):
        self.refresh_options()

    def option_changed(self, choice):
        self.preferred_format[self.view.kind.get().lower()] = choice
        self.refresh_options()

    def quality_changed(self, choice):
        self.preferred_quality[self.view.kind.get().lower()] = choice
        self.refresh_options()

    @staticmethod
    def set_menu(widget, choices, preferred):
        value = preferred if preferred in choices else choices[0] if choices else "—"
        widget.configure(values=list(choices) or ["—"], state="normal" if len(choices) > 1 else "disabled")
        widget.set(value)

    def current_options(self) -> DownloadOptions:
        kind = self.view.kind.get().lower()
        container = self.view.output_format.get()
        quality = self.view.quality.get()
        return DownloadOptions(kind, container, None if quality == "—" else quality)

    def refresh_options(self):
        kind = self.view.kind.get().lower()
        video = kind == "video"
        playlist = self.media is not None and self.media.is_playlist
        unavailable = ()
        if playlist or self.media is None:
            encoders = self.dependencies.audio_encoders if self.dependencies else None
            choices = VIDEO_FORMATS if video else supported_audio_outputs(encoders)
        elif self.availability:
            choices = self.availability.video if video else self.availability.audio
            unavailable = tuple(option for option in (VIDEO_FORMATS if video else AUDIO_FORMATS) if option not in choices)
        else:
            choices = ()
        self.set_menu(self.view.output_format, choices, self.preferred_format[kind])
        container = self.view.output_format.get()
        if video:
            self.view.quality_label.configure(text="Resolution cap")
            qualities = (
                self.availability.resolutions(container)
                if self.availability else RESOLUTIONS if choices else ()
            )
        else:
            self.view.quality_label.configure(text="Encoding target (kbps)" if container in LOSSY_AUDIO_FORMATS else "Bitrate")
            qualities = BITRATES if container in LOSSY_AUDIO_FORMATS else ()
        self.set_menu(self.view.quality, qualities, self.preferred_quality[kind])

        active_options = self.current_options()
        if not choices:
            note = f"This source has no supported {kind} for the selected mode."
        elif video and not qualities:
            note = f"No compatible {container} streams are within the available caps."
        elif self.availability:
            try:
                note = selection_note({"formats": self.media.formats}, active_options)
            except FormatError as error:
                note = str(error)
        elif playlist:
            note = "Each item is checked for these settings when it starts."
        elif video:
            note = "Resolution caps use the best compatible stream at or below the limit."
        else:
            note = ""
        if not video and container in LOSSY_AUDIO_FORMATS and not self.availability:
            note = " ".join(part for part in (note, "A higher target cannot recover source quality.") if part)
        if unavailable and choices:
            note = " ".join(part for part in (note, f"Unavailable: {', '.join(unavailable)}.") if part)
        if self.dependencies is not None and not self.dependencies.media_tools_ready:
            note = "Use FFmpeg and FFprobe from the same folder, then refresh Settings."
        self.view.option_note.configure(text=note or " ")
        self.refresh_controls()

    def refresh_controls(self):
        self.view.analyze_button.configure(
            text="Cancel" if self.analysis_stop else "Analyze",
            state="normal" if self.dependencies and not self.closing and self.view.url.get().strip() else "disabled",
        )
        ready = (
            bool(self.media) and self.dependencies is not None and self.dependencies.media_tools_ready
            and self.view.output_format.get() != "—"
            and (self.view.kind.get() == "Audio" or self.view.quality.get() != "—")
            and (not self.media.is_playlist or bool(self.media.entries)) and not self.closing
        )
        title = "Select Playlist Items" if self.media and self.media.is_playlist else "Add to Queue" if self.active else "Download"
        self.view.download_button.configure(text=title, state="normal" if ready else "disabled")
        self.view.cancel.configure(
            state="normal" if self.active and not self.active.stop.is_set() else "disabled",
        )

    def browse(self):
        old = Path(self.view.folder.get())
        selected = filedialog.askdirectory(
            parent=self, title="Choose a download folder", initialdir=str(old if old.is_dir() else Path.home()),
            mustexist=True,
        )
        if selected:
            self.view.folder.set(selected)
            self.save_preferences()

    def save_preferences(self):
        try:
            self.store.save_preferences(Preferences(Path(self.view.folder.get()), self.view.single.get()))
        except OSError:
            self.log.warning("Unable to save preferences")
            self.view.link_status.configure(text="Could not save preferences.", text_color=RED)

    def enqueue(self):
        if not self.media or self.view.download_button.cget("state") == "disabled":
            return
        destination = Path(self.view.folder.get())
        if not destination.is_dir():
            messagebox.showerror("Download folder", "Choose an existing download folder using Browse.", parent=self)
            return
        options = self.current_options()
        if self.media.is_playlist:
            choose_playlist(self, self.media, lambda entries: self.add_jobs(
                [Job(entry.url, entry.title, destination, options) for entry in entries]
            ))
        else:
            self.add_jobs([Job(self.media.url, self.media.title, destination, options)])

    def add_jobs(self, jobs: list[Job]):
        if self.closing:
            return
        existing = {job.url for job in self.jobs}
        added = 0
        for job in jobs:
            if job.url not in existing and (not self.active or job.url != self.active.url):
                self.jobs.append(job)
                existing.add(job.url)
                added += 1
        if not added:
            self.view.link_status.configure(text="Already in the queue.", text_color=MUTED)
            return
        if len(jobs) > 1:
            self.view.link_status.configure(text=f"{added} added to queue.", text_color=MUTED)
        if not self.start_next():
            self.render_queue()

    def start_next(self):
        if self.active or not self.jobs or self.closing or self.checking:
            return False
        if not self.dependencies or not self.dependencies.media_tools_ready:
            return False
        job = self.active = self.jobs.pop(0)
        job.status = "Active"
        self.last_output = None
        self.view.update_progress("Fetching media…", detail=one_line(job.title, 90), busy=True)
        self.refresh_controls()
        self.render_queue()
        downloader = Downloader(self.dependencies)
        last_phase = None
        last_update = 0.0

        def progress(data):
            nonlocal last_phase, last_update
            now = time.monotonic()
            if data.phase != last_phase or now - last_update >= 0.10:
                self.events.put(("progress", job, data))
                last_phase, last_update = data.phase, now

        def work():
            try:
                path = downloader.download(job.url, job.destination, job.options, progress, job.stop)
                self.events.put(("job_completed", job, path))
            except Cancelled:
                self.events.put(("job_canceled", job, None))
            except DownloaderError as error:
                self.events.put(("job_failed", job, str(error)))
            except Exception as error:
                self.log.error("Unexpected download error (%s)", type(error).__name__)
                self.events.put(("job_failed", job, "Download failed. Check Settings and try again."))

        threading.Thread(target=work, daemon=True).start()
        return True

    def show_progress(self, job: Job, data: Progress):
        job.phase = data.phase
        if job.stop.is_set():
            self.show_canceling(job)
            return
        if data.phase == "completed":
            return
        phases = {
            "fetching": "Fetching media…", "downloading": "Downloading…",
            "merging": "Merging streams…", "converting": "Processing with FFmpeg…",
            "postprocessing": "Processing with FFmpeg…", "finalizing": "Verifying output…",
        }
        metrics = []
        if data.downloaded_bytes is not None:
            downloaded = size_text(data.downloaded_bytes)
            metrics.append(f"{downloaded} / {size_text(data.total_bytes)}" if data.total_bytes else downloaded)
        if data.speed:
            metrics.append(f"{size_text(data.speed)}/s")
        if data.eta is not None:
            metrics.append(f"ETA {duration_text(data.eta)}")
        self.view.update_progress(
            phases.get(data.phase, "Working…"), data.percent, metrics="  ·  ".join(metrics),
            detail=data.detail or one_line(job.title, 90), busy=True,
        )

    def show_canceling(self, job: Job):
        detail = (
            "Waiting for FFmpeg to finish. Canceled output will be discarded."
            if job.phase in {"merging", "converting", "postprocessing"}
            else "Waiting for the next safe stopping point."
        )
        self.view.update_progress("Cancel requested…", detail=detail, busy=True)

    def cancel(self):
        if self.active:
            self.active.stop.set()
            self.show_canceling(self.active)
            self.refresh_controls()

    def finish_job(self, job, status, value):
        self.active = None
        path = value if status == "Completed" else None
        entry = HistoryEntry.finished(job.title, status, path)
        self.history.insert(0, entry)
        for old in self.history[HISTORY_LIMIT:]:
            self.retry_jobs.pop(id(old), None)
        del self.history[HISTORY_LIMIT:]
        self.log.info("Download %s (%s, %s)", status.lower(), job.options.kind, job.options.output_format)
        try:
            self.store.save_history(self.history)
        except OSError:
            self.log.warning("Unable to save download history")
            self.view.link_status.configure(text="Could not save history.", text_color=RED)
        if path:
            self.last_output = path
            self.view.update_progress("Download complete", 100, detail=str(path), completed=True)
        elif status == "Failed":
            self.retry_jobs[id(entry)] = job
            self.view.update_progress("Download failed", detail=value, bad=True)
        else:
            self.retry_jobs[id(entry)] = job
            self.view.update_progress("Download canceled", detail="You can retry this item from the queue.")
        self.render_queue()
        self.refresh_controls()
        if self.closing:
            self.destroy()
        else:
            self.after(600, self.start_next)

    def process_events(self):
        while True:
            try:
                kind, token, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "dependencies":
                self.dependencies = value
                self.checking = False
                self.log.info(
                    "Dependencies: yt-dlp=%s, EJS=%s, FFmpeg=%s, FFprobe=%s, Deno=%s",
                    value.yt_dlp_version or "missing", value.ejs_version or "missing",
                    value.ffmpeg_version or "missing", value.ffprobe_version or "missing",
                    value.deno_version if value.deno else "missing or unsupported",
                )
                self.render_settings()
                if self.media and not self.media.is_playlist:
                    self.availability = discover_formats(
                        {"formats": self.media.formats}, audio_encoders=value.audio_encoders
                    )
                self.refresh_options()
                self.start_next()
            elif kind == "thumbnail":
                if self.thumbnail_token is token and self.media and value:
                    self.read_media(self.media, value)
            elif kind in {"media", "analysis_error", "analysis_canceled"} and token is self.analysis_stop:
                self.analysis_stop = None
                if kind == "media":
                    self.thumbnail_token = token
                    self.view.link_status.configure(text="Analysis complete", text_color=GREEN)
                    self.read_media(value)
                elif kind == "analysis_error":
                    self.analysis_error = True
                    self.log.info("Analysis failed")
                    self.view.link_status.configure(text="Analysis failed", text_color=RED)
                    self.view.preview("Could not analyze the link", "", value)
                    if not self.active:
                        self.view.update_progress("Analysis failed", detail=value, bad=True)
                self.refresh_controls()
            elif kind == "progress" and token is self.active:
                self.show_progress(token, value)
            elif kind.startswith("job_") and token is self.active:
                status = {"job_completed": "Completed", "job_failed": "Failed", "job_canceled": "Canceled"}[kind]
                self.finish_job(token, status, value)
                if self.closing:
                    return
        self.after(70, self.process_events)

    def render_queue(self):
        rows = []
        if self.active:
            rows.append((self.active.title, "Active", BLUE, "", []))
        for job in self.jobs:
            rows.append((job.title, "Queued", MUTED, "", [("Remove", lambda item=job: self.remove_job(item))]))
        for entry in self.history:
            actions = []
            if entry.path:
                path = Path(entry.path)
                actions = [
                    ("Open File", lambda file=path: self.open_path(file)),
                    ("Open Folder", lambda folder=path.parent: self.open_path(folder)),
                ]
            elif job := self.retry_jobs.get(id(entry)):
                actions = [("Retry", lambda item=job: self.add_jobs([Job(item.url, item.title, item.destination, item.options)]))]
            color = {"Completed": GREEN, "Failed": RED}.get(entry.status, MUTED)
            rows.append((entry.title, entry.status, color, history_time(entry.created_at), actions))
        self.view.render_queue(rows, len(self.jobs))

    def remove_job(self, job):
        self.jobs.remove(job)
        self.render_queue()

    def open_path(self, path: Path):
        try:
            if not path.is_dir():
                if not path.is_file():
                    raise FileNotFoundError
                if path.suffix.lower() not in MEDIA_SUFFIXES:
                    messagebox.showinfo("Open File", "Open this format with a media player from its folder.", parent=self)
                    return
            os.startfile(str(path))
        except OSError:
            messagebox.showerror("Could not open", "The file or folder is missing or has no associated app.", parent=self)

    def open_last_file(self):
        if self.last_output:
            self.open_path(self.last_output)

    def open_last_folder(self):
        if self.last_output:
            self.open_path(self.last_output.parent)

    def show_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        self.settings_window = dialog(self, "YouTube Downloader Settings", "565x450")
        self.settings_window.minsize(450, 345)
        self.settings_window.grid_columnconfigure(0, weight=1)
        self.settings_window.grid_rowconfigure(1, weight=1)
        label(self.settings_window, "Dependencies", size=19, weight="bold").grid(row=0, column=0, sticky="w", padx=16, pady=(12, 2))
        self.settings_rows = ctk.CTkScrollableFrame(self.settings_window)
        self.settings_rows.grid(row=1, column=0, sticky="nsew", padx=15, pady=(5, 8))
        self.settings_rows.grid_columnconfigure(0, weight=1)
        actions = ctk.CTkFrame(self.settings_window, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 13))
        self.refresh_button = button(actions, "Refresh", self.check_dependencies)
        self.refresh_button.pack(side="left")
        button(actions, "Open Data Folder", self.open_data_folder, width=134).pack(side="left", padx=7)
        button(actions, "Close", self.settings_window.destroy).pack(side="right")
        self.render_settings()

    def render_settings(self):
        if not self.settings_window or not self.settings_window.winfo_exists():
            return
        for child in self.settings_rows.winfo_children():
            child.destroy()
        self.refresh_button.configure(state="disabled" if self.checking else "normal")
        dep = self.dependencies
        if self.checking or not dep:
            label(self.settings_rows, "Checking installed tools…", color=MUTED).grid(row=0, column=0, sticky="w", padx=7)
            return
        tools = [
            ("yt-dlp Python package", dep.yt_dlp_version, None, "Install the Python requirements or rebuild the app."),
            ("YouTube EJS scripts", dep.ejs_version, None, "Install the Python requirements or rebuild the app."),
            ("FFmpeg", dep.ffmpeg_version, dep.ffmpeg, "Install FFmpeg and add it to PATH."),
            ("FFprobe", dep.ffprobe_version, dep.ffprobe, "Use an FFmpeg package that includes FFprobe."),
            ("Deno", dep.deno_version if dep.deno else "", dep.deno, "Install Deno 2.3 or later and add it to PATH."),
        ]
        wrap = max(325, self.settings_window.winfo_width() - 86)
        for index, (name, version, path, help_text) in enumerate(tools):
            status = version or "Needs attention"
            label(self.settings_rows, f"{name}  ·  {status}", weight="bold", color=GREEN if version else RED).grid(
                row=index * 2, column=0, sticky="w", padx=7, pady=(4, 0)
            )
            if path or not version:
                label(
                    self.settings_rows, str(path or help_text), color=MUTED, size=12,
                    justify="left", anchor="w", wraplength=wrap,
                ).grid(row=index * 2 + 1, column=0, sticky="ew", padx=7, pady=(0, 3))
        if dep.notes:
            label(self.settings_rows, "\n".join(dep.notes), color=MUTED, justify="left", wraplength=wrap).grid(
                row=11, column=0, sticky="w", padx=7, pady=(5, 3)
            )

    def open_data_folder(self):
        try:
            self.store.directory.mkdir(parents=True, exist_ok=True)
            self.open_path(self.store.directory)
        except OSError:
            messagebox.showerror("Data folder", "Could not create the application data folder.", parent=self)

    def close(self):
        if self.closing:
            return
        if self.active or self.jobs:
            if not messagebox.askyesno("Exit YouTube Downloader", "Cancel the current queue and exit?", parent=self):
                return
        self.closing = True
        if self.analysis_stop:
            self.analysis_stop.set()
        if self.thumbnail_token:
            self.thumbnail_token.set()
        self.jobs.clear()
        if self.active:
            self.cancel()
            self.render_queue()
        else:
            self.destroy()
