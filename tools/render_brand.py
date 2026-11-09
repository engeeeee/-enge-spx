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
    glyphs = {
        "overview": '<rect x="3" y="3" width="6" height="6" rx="1"/><rect x="15" y="3" width="6" height="6" rx="1"/><rect x="3" y="15" width="6" height="6" rx="1"/><rect x="15" y="15" width="6" height="6" rx="1"/>',
        "connection": '<circle cx="5" cy="5" r="3"/><circle cx="19" cy="19" r="3"/><path d="m7.5 7.5 9 9"/>',
        "workspace": '<path d="M3 7h7l2 3h9v10H3z"/><path d="M3 7V4h7l2 3h7v3"/>',
        "downloads": '<path d="M12 3v12m-5-5 5 5 5-5M4 15v6h16v-6"/>',
        "logs": '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
        "settings": '<path d="M3 6h18M3 12h18M3 18h18"/><path d="M8 3v6m9 0v6m-10 0v6"/>',
    }
    for name, paths in glyphs.items():
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#B3ADA2" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' + paths + '</svg>'
        cairosvg.svg2png(bytestring=svg.encode(), write_to=str(ICONS / (name + ".png")), output_width=22, output_height=22)
    print("ENGE SPX vector, PNG variants and Windows ICO are ready.")


if __name__ == "__main__":
    main()
