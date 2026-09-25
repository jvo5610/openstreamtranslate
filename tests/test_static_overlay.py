import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class OverlayTransparencyTests(unittest.TestCase):
    def test_embed_root_and_body_are_transparent(self) -> None:
        embed_html = (ROOT / "app/static/embed.html").read_text(encoding="utf-8")
        styles = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")

        self.assertIn('class="embed-root"', embed_html)
        self.assertIn(
            ".embed-root, .embed-page { overflow: hidden; background: transparent; }",
            styles,
        )


if __name__ == "__main__":
    unittest.main()
