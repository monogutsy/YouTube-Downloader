import shutil
from pathlib import Path
from tempfile import gettempdir
from threading import Event
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from yt_dlp import YoutubeDL
from yt_dlp.extractor.common import InfoExtractor

from app.dependencies import Dependencies
from app.downloader import (
    PLAYLIST_PREVIEW_LIMIT,
    Cancelled,
    Downloader,
    DownloaderError,
    validate_url,
)
from app.formats import DownloadOptions


class URLTests(TestCase):
    def test_accepts_an_http_link_with_parameters(self):
        url = 'https://example.test/watch?v=abc&list=xyz&name=space%20here'
        self.assertEqual(validate_url(f'\t{url}\n'), url)

    def test_rejects_malformed_links_and_embedded_credentials(self):
        for url in ('youtube.com/watch?v=abc', 'file:///C:/test.mp4', 'https://example.test:bad/file',
                    'https://name:secret@example.test/watch', 'https://example.test/a\nb'):
            with self.subTest(url=url), self.assertRaises(DownloaderError):
                validate_url(url)


class PlaylistTests(TestCase):
    def test_playlist_preview_only_requests_first_fifty_positions(self):
        visited = []

        class FixtureIE(InfoExtractor):
            _VALID_URL = r'https://media\.example\.test/(?P<id>\w+)'

            def _real_extract(self, url):
                ident = self._match_id(url)
                if ident != 'playlist':
                    raise AssertionError('Preview should not resolve an individual video')

                def entries():
                    for index in range(75):
                        visited.append(index)
                        yield self.url_result(f'https://media.example.test/item{index}', FixtureIE,
                                              video_id=f'item{index}', video_title=f'Item {index}')

                return self.playlist_result(entries(), playlist_id=ident, playlist_title='Test playlist', playlist_count=75)

        def make_ydl(params):
            ydl = YoutubeDL(params, auto_init=False)
            ydl.add_info_extractor(FixtureIE())
            return ydl

        downloader = Downloader(Dependencies())
        url = 'https://media.example.test/playlist'
        with patch('app.downloader.YoutubeDL', make_ydl):
            with self.assertLogs('YouTubeDownloader.downloader', level='WARNING'):
                with self.assertRaisesRegex(DownloaderError, 'Clear Single video only'):
                    downloader.analyze(url)
            self.assertEqual(visited, [0])
            visited.clear()
            result = downloader.analyze(url, single_video=False)

        self.assertTrue(result.is_playlist)
        self.assertEqual(result.playlist_count, 75)
        self.assertEqual(len(result.entries), PLAYLIST_PREVIEW_LIMIT)
        self.assertEqual(visited, list(range(PLAYLIST_PREVIEW_LIMIT)))
        self.assertEqual(result.entries[-1].url, 'https://media.example.test/item49')


class FileLifecycleTests(TestCase):
    def setUp(self):
        self.folder = Path(gettempdir()) / f'youtube-downloader-test-{uuid4().hex}'
        self.folder.mkdir()
        self.addCleanup(shutil.rmtree, self.folder)
        self.downloader = Downloader(Dependencies(ffmpeg=Path('ffmpeg.exe'), ffprobe=Path('ffprobe.exe')))
        self.url = 'https://media.example.test/clip'
        self.options = DownloadOptions('video', 'MP4')
        self.events = []

    def test_cancel_discards_staged_files_before_publication(self):
        cancel = Event()

        def finish_after_cancel(_url, scratch, _params, _plan, _progress, cancel_flag):
            staged = scratch / 'clip.mp4'
            staged.write_bytes(b'test')
            cancel_flag.set()
            return staged

        with patch.object(self.downloader, '_download_into', finish_after_cancel):
            with self.assertRaises(Cancelled):
                self.downloader.download(self.url, self.folder, self.options, self.events.append, cancel)

        self.assertEqual(list(self.folder.iterdir()), [])
        self.assertFalse(any(event.phase == 'completed' for event in self.events))

    def test_publishes_with_a_suffix_and_preserves_the_original(self):
        existing = self.folder / 'clip.mp4'
        existing.write_bytes(b'original')

        def stage_file(_url, scratch, _params, _plan, _progress, _cancel):
            staged = scratch / 'clip.mp4'
            staged.write_bytes(b'new')
            return staged

        with patch.object(self.downloader, '_download_into', stage_file), patch.object(self.downloader, '_verify_file'):
            result = self.downloader.download(self.url, self.folder, self.options, self.events.append, Event())

        self.assertEqual(result.name, 'clip (2).mp4')
        self.assertEqual(existing.read_bytes(), b'original')
        self.assertEqual(result.read_bytes(), b'new')
        self.assertEqual({path.name for path in self.folder.iterdir()}, {'clip.mp4', 'clip (2).mp4'})
        self.assertEqual(self.events[-1].phase, 'completed')

    def test_refuses_an_output_outside_the_staging_folder(self):
        existing = self.folder / 'clip.mp4'
        existing.write_bytes(b'original')

        with patch.object(self.downloader, '_download_into', return_value=existing):
            with self.assertLogs('YouTubeDownloader.downloader', level='WARNING'):
                with self.assertRaisesRegex(DownloaderError, 'did not produce a local media file'):
                    self.downloader.download(self.url, self.folder, self.options, self.events.append, Event())

        self.assertEqual(list(self.folder.iterdir()), [existing])
        self.assertEqual(existing.read_bytes(), b'original')
