from io import BytesIO
from pathlib import Path
from tkinter import TclError
from unittest import TestCase
from unittest.mock import Mock

import customtkinter as ctk
from PIL import Image

from app.settings import Preferences
from app.views import MainView


class ThumbnailPreviewTests(TestCase):
    def test_new_preview_after_clearing_previous_thumbnail(self):
        try:
            root = ctk.CTk()
        except TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        self.addCleanup(root.destroy)
        root.withdraw()

        view = MainView(root, Mock(), Preferences(Path.cwd()))
        with BytesIO() as stream:
            Image.new("RGB", (16, 9)).save(stream, format="PNG")
            thumbnail = stream.getvalue()

        view.preview("First video", "", "", thumbnail)
        view.preview("", "", "")
        view.preview("Second video", "", "")
        self.assertEqual(view.thumbnail.cget("image"), "")

        view.preview("Second video", "", "", thumbnail)
        self.assertIsNotNone(view.preview_image)
        self.assertEqual(view.preview_title.cget("text"), "Second video")
