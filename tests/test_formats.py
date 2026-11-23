from unittest import TestCase

from app.formats import (
    BEST_ORIGINAL,
    OGG_OPUS,
    OGG_VORBIS,
    DownloadOptions,
    FormatError,
    discover_formats,
    download_plan,
    selection_note,
)


def stream(identifier, ext, video, audio, **fields):
    return {
        "format_id": identifier,
        "ext": ext,
        "vcodec": video,
        "acodec": audio,
        "protocol": "https",
        **fields,
    }


class FormatTests(TestCase):
    def setUp(self):
        self.context = {"formats": [
            stream("avc-720", "mp4", "avc1.64001f", "none", height=720, width=1280, fps=30),
            stream("av1-720", "mp4", "av01.0.05M.08", "none", height=720, width=1280, fps=30),
            stream("vp9-4k", "webm", "vp09", "none", height=2160, width=3840, fps=60),
            stream("aac", "m4a", "none", "mp4a.40.2"),
            stream("opus", "webm", "none", "opus"),
        ]}

    def test_mp4_cap_falls_back_and_prefers_h264_at_equal_height_and_fps(self):
        options = DownloadOptions("video", "MP4", "1080p")
        plan = download_plan(options)
        self.assertEqual(plan.format_selector(self.context)[0]["format_id"], "avc-720+aac")
        self.assertIn("below the 1080p cap", selection_note(self.context, options))
        self.assertNotIn("480p", discover_formats(self.context).resolutions("MP4"))

    def test_webm_uses_compatible_video_and_audio(self):
        options = DownloadOptions("video", "WebM", "2160p (4K)")
        plan = download_plan(options)
        self.assertEqual(plan.format_selector(self.context)[0]["format_id"], "vp9-4k+opus")
        with self.assertRaisesRegex(FormatError, "cap"):
            download_plan(DownloadOptions("video", "WebM", "480p")).format_selector(self.context)

    def test_portrait_video_uses_shorter_dimension_for_cap(self):
        context = {"formats": [stream("portrait", "mp4", "avc1", "aac", width=720, height=1280)]}
        options = DownloadOptions("video", "MP4", "720p")
        self.assertEqual(download_plan(options).format_selector(context)[0]["format_id"], "portrait")
        self.assertIn("720", selection_note(context, options))
        self.assertIn("1280", selection_note(context, options))

    def test_audio_encoder_availability_and_original_choice(self):
        audio = discover_formats(self.context, audio_encoders={"libmp3lame"}).audio
        self.assertEqual(audio, (BEST_ORIGINAL, "MP3"))
        plan = download_plan(DownloadOptions("audio", BEST_ORIGINAL))
        self.assertEqual(plan.format_selector(self.context)[0]["format_id"], "opus")
        self.assertIsNone(plan.extension)
        with self.assertRaisesRegex(FormatError, "encoding target"):
            download_plan(DownloadOptions("audio", "MP3", "999"))

    def test_ogg_options_require_the_matching_encoder(self):
        for encoder, option in (("libopus", OGG_OPUS), ("libvorbis", OGG_VORBIS)):
            with self.subTest(encoder=encoder):
                availability = discover_formats(self.context, audio_encoders={encoder})
                self.assertEqual(availability.audio, (BEST_ORIGINAL, option))
                options = DownloadOptions("audio", option, "192")
                self.assertEqual(download_plan(options).extension, "ogg")
                self.assertIn("192 kbps encoding target", selection_note(self.context, options))
        self.assertEqual(download_plan(DownloadOptions("audio", "OGG", "192")).extension, "ogg")

    def test_combined_stream_can_be_remuxed_without_a_merge(self):
        context = {"formats": [stream("combined", "mp4", "avc1", "aac", height=480)]}
        plan = download_plan(DownloadOptions("video", "MOV", "480p"))
        self.assertEqual(plan.format_selector(context)[0]["format_id"], "combined")
        self.assertEqual(plan.extension, "mov")
        self.assertIn("MKA", selection_note(context, DownloadOptions("audio", BEST_ORIGINAL)))

    def test_excludes_drm_and_nonmedia_extensions(self):
        context = {"formats": [
            stream("protected", "mp4", "avc1", "aac", has_drm=True),
            stream("unsafe", "exe", "none", "mp3"),
        ]}
        availability = discover_formats(context)
        self.assertEqual(availability.video, ())
        self.assertEqual(availability.audio, ())
