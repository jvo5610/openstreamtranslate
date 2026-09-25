import unittest

from app.main import GlossaryEntry, normalize_glossary, subtitle_timestamp, transcript_text


class TranscriptFormattingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.events = [
            {
                "final": False,
                "source_language": "es",
                "target_language": "en",
                "original": "hipótesis parcial",
                "translation": "partial hypothesis",
                "audio_start_seconds": 0,
                "audio_end_seconds": 1,
            },
            {
                "final": True,
                "source_language": "es",
                "target_language": "en",
                "original": "Kubernetes escala sesiones.",
                "translation": "Kubernetes scales sessions.",
                "audio_start_seconds": 1.25,
                "audio_end_seconds": 3.75,
            },
        ]

    def test_srt_uses_confirmed_target_caption(self) -> None:
        output = transcript_text(self.events, "en", "srt")
        self.assertIn("00:00:01,250 --> 00:00:03,750", output)
        self.assertIn("Kubernetes scales sessions.", output)
        self.assertNotIn("partial hypothesis", output)

    def test_vtt_uses_dot_milliseconds_and_header(self) -> None:
        output = transcript_text(self.events, "es", "vtt")
        self.assertTrue(output.startswith("WEBVTT\n\n"))
        self.assertIn("00:00:01.250 --> 00:00:03.750", output)

    def test_plain_text_contains_only_caption_text(self) -> None:
        self.assertEqual(
            transcript_text(self.events, "en", "txt"),
            "Kubernetes scales sessions.\n",
        )

    def test_timestamp_clamps_negative_values(self) -> None:
        self.assertEqual(subtitle_timestamp(-2), "00:00:00,000")


class GlossaryTests(unittest.TestCase):
    def test_normalization_deduplicates_case_insensitively(self) -> None:
        entries = normalize_glossary(
            [
                GlossaryEntry(source=" CloudNativePG "),
                GlossaryEntry(source="cloudnativepg", target="duplicate"),
                GlossaryEntry(source="base   de datos", target="database"),
            ]
        )
        self.assertEqual(
            entries,
            [
                {"source": "CloudNativePG", "target": "CloudNativePG"},
                {"source": "base de datos", "target": "database"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
