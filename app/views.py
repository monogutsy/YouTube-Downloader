"""The main window, display helpers, and secondary dialogs."""

from io import BytesIO
from tkinter import BooleanVar, Misc, StringVar

import customtkinter as ctk
from PIL import Image, ImageOps

from app.utils import duration_text, one_line

BG = "#F2F5FA"
WHITE = "#FFFFFF"
INK = "#17243A"
MUTED = "#53637B"
LINE = "#DCE3EF"
TINT = "#EEF3FC"
BLUE = "#2459C9"
BLUE_HOVER = "#1946A8"
GREEN = "#19714A"
RED = "#A82639"


def font(size=13, weight="normal"):
    return ctk.CTkFont(family="Segoe UI", size=size, weight=weight)


def label(parent, text="", *, size=13, weight="normal", color=INK, height=22, **kwargs):
    return ctk.CTkLabel(
        parent, text=text, text_color=color, font=font(size, weight), height=height, **kwargs
    )


def button(parent, text, command, *, primary=False, width=84, height=34):
    return ctk.CTkButton(
        parent, text=text, command=command, width=width, height=height, corner_radius=6,
        fg_color=BLUE if primary else WHITE, hover_color=BLUE_HOVER if primary else TINT,
        text_color=WHITE if primary else INK,
        text_color_disabled="#D6E0F5" if primary else "#808CA0",
        border_width=0 if primary else 1, border_color=LINE, font=font(13, "bold"),
    )


def surface(parent):
    return ctk.CTkFrame(parent, fg_color=WHITE, corner_radius=8, border_width=1, border_color=LINE)


def rule(parent):
    return ctk.CTkFrame(parent, fg_color=LINE, height=1, corner_radius=0)


def option_menu(parent, command):
    return ctk.CTkOptionMenu(
        parent, values=["—"], command=command, width=126, height=34, corner_radius=6,
        font=font(), dropdown_font=font(), fg_color=TINT, button_color=TINT,
        button_hover_color="#DCE8FC", text_color=INK, text_color_disabled=MUTED,
        dropdown_fg_color=WHITE, dropdown_text_color=INK, dropdown_hover_color=TINT,
        dynamic_resizing=False,
    )


def checkbox(parent, text, variable, command=None):
    return ctk.CTkCheckBox(
        parent, text=text, variable=variable, command=command, text_color=MUTED,
        font=font(), height=20, checkbox_width=17, checkbox_height=17, corner_radius=4,
        border_width=1, border_color="#8B9AB2", fg_color=BLUE, hover_color=BLUE_HOVER,
    )


def wrap_to_width(widget, minimum=100):
    def resize(event):
        width = max(minimum, round(event.width / widget._get_widget_scaling()) - 4)
        if width != widget.cget("wraplength"):
            widget.configure(wraplength=width)

    # Bind to the frame around the label so the internal canvas and text
    # do not issue competing measurements when they resize.
    Misc.bind(widget, "<Configure>", resize, add="+")


class MainView:
    def __init__(self, root, controller, preferences):
        self.root = root
        self.url = StringVar()
        self.folder = StringVar(value=str(preferences.folder))
        self.single = BooleanVar(value=preferences.single_video)
        self.preview_image = None
        self.indeterminate = False

        root.configure(fg_color=BG)
        root.grid_columnconfigure(0, weight=1)
        root.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(root, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(17, 13))
        label(header, "YouTube Downloader", size=25, weight="bold").pack(side="left")
        button(header, "Settings", controller.show_settings, width=88).pack(side="right")

        link = surface(root)
        link.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 14))
        link.grid_columnconfigure(0, weight=1)
        label(link, "Video or playlist link", weight="bold").grid(
            row=0, column=0, sticky="w", padx=15, pady=(8, 3)
        )
        entry = ctk.CTkEntry(
            link, textvariable=self.url, fg_color=WHITE, border_color=LINE, text_color=INK,
            height=36, border_width=1, font=font(), corner_radius=6,
        )
        entry.grid(row=1, column=0, sticky="ew", padx=(15, 7))
        entry.bind("<Return>", lambda _: controller.analyze())
        button(link, "Paste", controller.paste, width=72, height=36).grid(row=1, column=1, padx=(0, 7))
        self.analyze_button = button(link, "Analyze", controller.analyze, primary=True, width=92, height=36)
        self.analyze_button.grid(row=1, column=2, padx=(0, 15))
        checkbox(link, "Single video only", self.single, controller.single_changed).grid(
            row=2, column=0, sticky="w", padx=15, pady=(8, 9)
        )
        self.link_status = label(link, color=MUTED, anchor="e", size=12)
        self.link_status.grid(row=2, column=0, columnspan=3, sticky="e", padx=15, pady=(8, 9))

        body = ctk.CTkFrame(root, fg_color="transparent")
        body.grid(row=2, column=0, sticky="nsew", padx=24, pady=(0, 20))
        body.grid_columnconfigure(0, weight=3, minsize=470)
        body.grid_columnconfigure(1, weight=2, minsize=242)
        body.grid_rowconfigure(0, weight=1)

        work_panel = surface(body)
        work_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        work_panel.grid_columnconfigure(0, weight=1)
        work_panel.grid_rowconfigure(0, weight=1)
        workspace = ctk.CTkScrollableFrame(
            work_panel, fg_color=WHITE, scrollbar_button_color=LINE,
            scrollbar_button_hover_color="#B8C5DB", corner_radius=0,
        )
        workspace.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        workspace.grid_columnconfigure(0, weight=1)
        self._build_preview(workspace)
        rule(workspace).grid(row=1, column=0, sticky="ew", padx=15)
        self._build_options(workspace, controller)
        rule(workspace).grid(row=3, column=0, sticky="ew", padx=15)
        self._build_progress(workspace, controller)
        self._build_queue(body)
        entry.focus_set()

    def _build_preview(self, parent):
        preview = ctk.CTkFrame(parent, fg_color="transparent")
        preview.grid(row=0, column=0, sticky="ew", padx=15, pady=(13, 12))
        preview.grid_columnconfigure(1, weight=1, minsize=140)
        image_box = ctk.CTkFrame(preview, fg_color=TINT, width=168, height=94, corner_radius=6)
        image_box.grid(row=0, column=0, rowspan=3, sticky="w", padx=(0, 13))
        image_box.grid_propagate(False)
        image_box.grid_rowconfigure(0, weight=1)
        image_box.grid_columnconfigure(0, weight=1)
        self.thumbnail = label(image_box, "Preview", color=MUTED)
        self.thumbnail.grid(row=0, column=0, sticky="nsew")
        self.preview_title = label(preview, size=17, weight="bold", justify="left", anchor="sw", height=24)
        self.preview_title.grid(row=0, column=1, sticky="sew", pady=(2, 0))
        self.preview_meta = label(preview, size=12, color=MUTED, justify="left", anchor="w", height=18)
        self.preview_meta.grid(row=1, column=1, sticky="ew")
        self.preview_formats = label(preview, size=12, color=MUTED, justify="left", anchor="nw", height=18)
        self.preview_formats.grid(row=2, column=1, sticky="new")
        for item in (self.preview_title, self.preview_meta, self.preview_formats):
            wrap_to_width(item)
        self.preview("", "", "")

    def _build_options(self, parent, controller):
        form = ctk.CTkFrame(parent, fg_color="transparent")
        form.grid(row=2, column=0, sticky="ew", padx=15, pady=(9, 11))
        form.grid_columnconfigure((0, 1), weight=1, uniform="form")
        form.grid_columnconfigure(2, weight=1, uniform="form")
        label(form, "Download options", size=15, weight="bold").grid(row=0, column=0, columnspan=2, sticky="w")

        label(form, "Media", color=MUTED, size=12).grid(row=1, column=0, sticky="w")
        label(form, "Format", color=MUTED, size=12).grid(row=1, column=1, sticky="w")
        self.quality_label = label(form, "Resolution cap", color=MUTED, size=12)
        self.quality_label.grid(row=1, column=2, sticky="w")
        self.kind = ctk.CTkSegmentedButton(
            form, values=["Video", "Audio"], command=controller.kind_changed, height=34,
            fg_color=TINT, selected_color="#C6D8FB", selected_hover_color="#B8CEFA",
            unselected_color=TINT, unselected_hover_color="#DCE8FC", text_color=INK,
            font=font(13, "bold"), corner_radius=6, dynamic_resizing=False,
        )
        self.kind.set("Video")
        self.kind.grid(row=2, column=0, sticky="ew", padx=(0, 8))
        self.output_format = option_menu(form, controller.option_changed)
        self.output_format.grid(row=2, column=1, sticky="ew", padx=(0, 8))
        self.quality = option_menu(form, controller.quality_changed)
        self.quality.grid(row=2, column=2, sticky="ew")
        self.option_note = label(form, color=MUTED, size=11, anchor="w", justify="left")
        self.option_note.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(1, 1))
        wrap_to_width(self.option_note, 200)
        label(form, "Save to", color=MUTED, size=12).grid(row=4, column=0, sticky="w")
        folder = ctk.CTkEntry(
            form, textvariable=self.folder, state="readonly", fg_color=WHITE, border_color=LINE,
            text_color=INK, height=34, border_width=1, font=font(), corner_radius=6,
        )
        folder.grid(row=5, column=0, columnspan=2, sticky="ew", padx=(0, 8))
        button(form, "Browse…", controller.browse).grid(row=5, column=2, sticky="ew")
        self.download_button = button(form, "Download", controller.enqueue, primary=True, height=36)
        self.download_button.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(9, 0))

    def _build_progress(self, parent, controller):
        panel = ctk.CTkFrame(parent, fg_color="transparent")
        panel.grid(row=4, column=0, sticky="new", padx=15, pady=(8, 11))
        panel.grid_columnconfigure(0, weight=1)
        self.phase = label(panel, "Ready", weight="bold", anchor="w")
        self.phase.grid(row=0, column=0, sticky="ew")
        self.percent = label(panel, color=MUTED, size=12)
        self.percent.grid(row=0, column=1, sticky="e")
        self.cancel = button(panel, "Cancel", controller.cancel, width=66, height=27)
        self.cancel.grid(row=0, column=2, sticky="e", padx=(9, 0))
        self.cancel.configure(state="disabled")
        self.bar = ctk.CTkProgressBar(panel, height=7, corner_radius=4, fg_color=TINT, progress_color=BLUE)
        self.bar.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(6, 2))
        self.bar.set(0)
        self.metrics = label(panel, "Waiting for a download.", color=MUTED, size=12, anchor="w")
        self.metrics.grid(row=2, column=0, columnspan=3, sticky="ew")
        self.detail = label(panel, color=MUTED, size=12, anchor="w", justify="left")
        wrap_to_width(self.detail, 200)
        self.result_actions = ctk.CTkFrame(panel, fg_color="transparent")
        self.result_actions.grid(row=4, column=0, columnspan=3, sticky="ew")
        self.open_file = button(self.result_actions, "Open File", controller.open_last_file, width=80, height=28)
        self.open_folder = button(self.result_actions, "Open Folder", controller.open_last_folder, width=95, height=28)

    def _build_queue(self, parent):
        panel = surface(parent)
        panel.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(2, weight=1)
        heading = ctk.CTkFrame(panel, fg_color="transparent")
        heading.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 5))
        label(heading, "Queue & history", size=16, weight="bold").pack(side="left")
        self.queue_count = label(heading, color=MUTED, size=12)
        self.queue_count.pack(side="right")
        rule(panel).grid(row=1, column=0, sticky="ew", padx=14)
        self.queue_rows = ctk.CTkScrollableFrame(
            panel, fg_color=WHITE, scrollbar_button_color=LINE,
            scrollbar_button_hover_color="#B8C5DB", corner_radius=0,
        )
        self.queue_rows.grid(row=2, column=0, sticky="nsew", padx=(9, 5), pady=(4, 6))
        self.queue_rows.grid_columnconfigure(0, weight=1)

    def preview(self, title, meta, formats, thumbnail=None):
        self.preview_title.configure(text=one_line(title, 95) or "No media selected")
        self.preview_meta.configure(text=one_line(meta, 100))
        self.preview_formats.configure(text=one_line(formats, 112) or (" " if title else "Analyze a link to see its available formats."))
        self.preview_image = None
        if thumbnail:
            try:
                with Image.open(BytesIO(thumbnail)) as source:
                    if source.width * source.height <= 16_000_000:
                        picture = ImageOps.fit(source.convert("RGB"), (336, 188), Image.Resampling.LANCZOS)
                        self.preview_image = ctk.CTkImage(light_image=picture, size=(168, 94))
            except (OSError, ValueError, Image.DecompressionBombError):
                pass
        # An empty image name clears the Tk image when the previous thumbnail is released.
        self.thumbnail.configure(
            image=self.preview_image or "", text="" if self.preview_image else ("No thumbnail" if title else "Preview")
        )

    def update_progress(self, phase, percent=None, *, metrics="", detail="", busy=False, bad=False, completed=False):
        self.phase.configure(text=phase, text_color=RED if bad else GREEN if completed else INK)
        self.percent.configure(text=f"{percent:.0f}%" if percent is not None else "")
        waiting = busy and percent is None
        if waiting != self.indeterminate:
            self.bar.stop()
            self.bar.configure(mode="indeterminate" if waiting else "determinate")
            if waiting:
                self.bar.start()
            self.indeterminate = waiting
        if not waiting:
            self.bar.set((percent or 0) / 100)
        self.metrics.configure(text=metrics or " ", text_color=MUTED)
        self.detail.configure(text=detail, text_color=RED if bad else MUTED)
        if detail:
            self.detail.grid(row=3, column=0, columnspan=3, sticky="ew")
        else:
            self.detail.grid_remove()
        if completed:
            self.open_file.pack(side="left", padx=(0, 7), pady=(3, 0))
            self.open_folder.pack(side="left", pady=(3, 0))
        else:
            self.open_file.pack_forget()
            self.open_folder.pack_forget()

    def render_queue(self, rows, pending):
        for child in self.queue_rows.winfo_children():
            child.destroy()
        self.queue_count.configure(text=f"{pending} pending" if pending else "")
        if not rows:
            label(self.queue_rows, "Your downloads will appear here.", color=MUTED, anchor="w").grid(
                row=0, column=0, sticky="ew", padx=5, pady=5
            )
            return
        for index, (title, status, color, detail, actions) in enumerate(rows):
            row = ctk.CTkFrame(self.queue_rows, fg_color=TINT if index % 2 == 0 else WHITE, corner_radius=5)
            row.grid(row=index, column=0, sticky="ew", padx=4, pady=2)
            row.grid_columnconfigure(0, weight=1)
            name = label(row, one_line(title, 72), weight="bold", anchor="w", justify="left")
            name.grid(row=0, column=0, sticky="ew", padx=8, pady=(3, 0))
            wrap_to_width(name, 130)
            info = f"{status}  ·  {detail}" if detail else status
            label(row, info, color=color, size=12, anchor="w").grid(row=1, column=0, sticky="w", padx=8, pady=(0, 3))
            if actions:
                bar = ctk.CTkFrame(row, fg_color="transparent")
                bar.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 5))
                for action, command in actions:
                    button(bar, action, command, width=66, height=26).pack(side="left", padx=(0, 5))


def dialog(parent, title, size):
    window = ctk.CTkToplevel(parent, fg_color=BG)
    window.title(title)
    window.geometry(size)
    window.transient(parent)
    window.grab_set()
    window.bind("<Escape>", lambda _: window.destroy())
    return window


def choose_playlist(parent, media, submit):
    window = dialog(parent, "Select playlist items", "570x440")
    window.minsize(410, 300)
    window.grid_columnconfigure(0, weight=1)
    window.grid_rowconfigure(2, weight=1)
    label(window, one_line(media.title, 70), size=18, weight="bold", anchor="w").grid(
        row=0, column=0, sticky="ew", padx=16, pady=(12, 0)
    )
    total = f" of {media.playlist_count}" if media.playlist_count and media.playlist_count > len(media.entries) else ""
    label(window, f"Showing {len(media.entries)}{total} items. Clear any you want to skip.", color=MUTED).grid(
        row=1, column=0, sticky="w", padx=16, pady=(0, 8)
    )
    items = ctk.CTkScrollableFrame(window, fg_color=WHITE)
    items.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 8))
    items.grid_columnconfigure(0, weight=1)
    selected = []

    def update_actions():
        count = sum(value.get() for _, value in selected)
        queue_button.configure(
            text=f"Add {count} to Queue", state="normal" if count else "disabled"
        )
        select_button.configure(text="Clear All" if count else "Select All")

    def toggle_all():
        enable = not any(value.get() for _, value in selected)
        for _, value in selected:
            value.set(enable)
        update_actions()

    for entry in media.entries:
        value = BooleanVar(master=window, value=True)
        selected.append((entry, value))
        duration = duration_text(entry.duration)
        text = one_line(entry.title, 57)
        if duration:
            text += f"  ·  {duration}"
        checkbox(items, text, value, update_actions).pack(anchor="w", padx=6, pady=4)

    actions = ctk.CTkFrame(window, fg_color="transparent")
    actions.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 12))

    def add():
        entries = [entry for entry, value in selected if value.get()]
        if entries:
            window.destroy()
            submit(entries)

    button(actions, "Close", window.destroy).pack(side="left")
    select_button = button(actions, "Clear All", toggle_all)
    select_button.pack(side="left", padx=7)
    queue_button = button(actions, "Add to Queue", add, primary=True, width=130)
    queue_button.pack(side="right")
    update_actions()
