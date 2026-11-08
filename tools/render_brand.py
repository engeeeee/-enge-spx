"""Rebuild ENGE SPX icons from its original vector mark; development only."""
from pathlib import Path
import io

import cairosvg
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "src/enge_spx/resources/icons"


def main():
    source = (ROOT / "assets/logo.svg").read_bytes()
    ICONS.mkdir(parents=True, exist_ok=True)
    for size in (32, 64, 128, 256, 512):
        cairosvg.svg2png(bytestring=source, write_to=str(ICONS / f"logo-{size}.png"), output_width=size, output_height=size)
    image = Image.open(io.BytesIO(cairosvg.svg2png(bytestring=source, output_width=256, output_height=256)))
    image.save(ICONS / "app.ico", sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
    print("ENGE SPX vector, PNG variants and Windows ICO are ready.")


if __name__ == "__main__":
    main()
