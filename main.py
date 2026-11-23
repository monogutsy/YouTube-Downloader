"""Windows desktop application entry point."""

import customtkinter as ctk

from app.ui import DownloaderApp


def main() -> None:
    ctk.set_appearance_mode("Light")
    app = DownloaderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
