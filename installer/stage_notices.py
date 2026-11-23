"""Collect the notices that accompany the Windows installer payload."""

import platform
import shutil
import sys
from importlib.metadata import distribution
from pathlib import Path

RUNTIME_PACKAGES = (
    "brotli",
    "certifi",
    "charset-normalizer",
    "customtkinter",
    "darkdetect",
    "idna",
    "packaging",
    "pillow",
    "pycryptodomex",
    "pyinstaller",
    "requests",
    "setuptools",
    "urllib3",
    "websockets",
    "yt-dlp",
    "yt-dlp-ejs",
)


def copy_notice(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def package_notices(package: str, output: Path) -> str:
    installed = distribution(package)
    for file in installed.files or ():
        path = Path(file)
        if not path.name.lower().startswith(("license", "copying", "notice")):
            continue
        if not any(part.endswith(".dist-info") for part in path.parts):
            continue
        copy_notice(Path(installed.locate_file(file)), output / package / path)
    return f"{package} {installed.version}   https://pypi.org/project/{package}/{installed.version}/#files"


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    output = root / "build" / "installer-payload" / "YouTube Downloader" / "licenses"
    compiler = Path(sys.argv[1]).resolve()
    python = Path(sys.base_prefix)
    version = platform.python_version()
    copy_notice(python / "LICENSE.txt", output / "python" / "LICENSE.txt")
    for path in (python / "tcl").glob("*/license.terms"):
        copy_notice(path, output / path.parent.name / path.name)
    copy_notice(compiler.with_name("license.txt"), output / "inno-setup" / "LICENSE.txt")

    index = [
        "Third-party software in this installation",
        "",
        f"Python {version}   https://www.python.org/downloads/release/python-{version.replace('.', '')}/",
        "Tcl and Tk   https://www.tcl-lang.org/software/tcltk/",
        "Setup built with Inno Setup   https://jrsoftware.org/isinfo.php",
        "",
        "Bundled Python package releases and source downloads",
        "",
    ]
    index.extend(package_notices(package, output) for package in RUNTIME_PACKAGES)
    index.extend((
        "",
        "Setup downloads FFmpeg and FFprobe directly from Gyan's FFmpeg release:",
        "https://github.com/GyanD/codexffmpeg/releases",
        "FFmpeg source: https://ffmpeg.org/download.html#get-sources",
        "",
        "Setup downloads Deno directly from the Deno release:",
        "https://github.com/denoland/deno/releases",
        "Deno license and notices: https://github.com/denoland/deno/blob/main/LICENSE.md",
    ))
    (output / "THIRD-PARTY-NOTICES.txt").write_text("\n".join(index) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
