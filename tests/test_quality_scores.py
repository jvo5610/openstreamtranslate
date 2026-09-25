import unittest

from scripts.score_asr import timestamp_seconds
from scripts.score_translation import chrf, normalized_text, token_f1


class QualityScoreTests(unittest.TestCase):
    def test_srt_timestamp_supports_comma_and_dot(self) -> None:
        self.assertEqual(timestamp_seconds("00:01:02,500"), 62.5)
        self.assertEqual(timestamp_seconds("00:01:02.500"), 62.5)

    def test_identical_translation_scores_one(self) -> None:
        text = normalized_text("Kubernetes escala sesiones.")
        self.assertEqual(token_f1(text, text), 1)
        self.assertEqual(chrf(text, text), 1)

    def test_unrelated_translation_scores_zero(self) -> None:
        self.assertEqual(token_f1("uno dos", "three four"), 0)
        self.assertEqual(chrf("abc", "xyz"), 0)


if __name__ == "__main__":
    unittest.main()
