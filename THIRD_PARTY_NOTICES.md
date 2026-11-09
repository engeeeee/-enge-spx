# Third-party components

ENGE SPX is maintained by engeeeee. The implementation's historical design references are acknowledged in NOTICE.md. The ENGE SPX mark is a new vector asset; earlier upstream logos, screenshots, macOS documentation and protected binaries are not distributed here.

The project retains its PolyForm Noncommercial license. The following independently distributed components retain their respective authorship, licenses and terms:

- Python: https://www.python.org/psf/license/
- Qt / PySide6 Essentials / Shiboken6 6.12.0 (LGPL-3.0 and applicable third-party notices): https://doc.qt.io/qt-6/lgpl.html and https://doc.qt.io/qtforpython-6/licenses.html. Exact source links, license texts and notices are supplied in `licenses/Qt-SOURCES.md`, `licenses/LGPL-3.0.txt`, `licenses/GPL-3.0.txt` and `licenses/qt-6.12.0-notices.zip`. Windows builds expand the bundle into `THIRD-PARTY-LICENSES/Qt`; the dynamically loaded libraries remain replaceable. The application's restrictions do not apply to these LGPL-covered parts or to reverse engineering for debugging modifications to them.
- PyYAML (MIT): https://github.com/yaml/pyyaml/blob/main/LICENSE
- tzdata (Apache-2.0, IANA time-zone data public-domain notices): https://github.com/python/tzdata
- websockets (BSD-3-Clause): https://github.com/python-websockets/websockets
- HTTPX and httpcore (BSD-3-Clause): https://github.com/encode/httpx/blob/master/LICENSE.md and https://github.com/encode/httpcore/blob/master/LICENSE.md
- AnyIO, sniffio, h11, socksio and idna (MIT or BSD notices in the installed distributions): https://github.com/agronholm/anyio, https://github.com/python-trio/sniffio, https://github.com/python-hyper/h11, https://github.com/sethmlarson/socksio and https://github.com/kjd/idna
- certifi (Mozilla Public License 2.0): https://github.com/certifi/python-certifi
- PyInstaller bootloader (GPL with distribution exception): https://pyinstaller.org/en/stable/license.html
- Inno Setup and its Simplified Chinese messages (copyright and redistribution terms retained in the supplied language source): https://github.com/jrsoftware/issrc and https://jrsoftware.org/files/is/license.txt
- sing-box (GPL-3.0 and its project notices): https://github.com/SagerNet/sing-box
- Node.js and npm: https://github.com/nodejs/node/blob/main/LICENSE and https://github.com/npm/cli/blob/latest/LICENSE
- Codex CLI (Apache-2.0 and bundled notices): https://github.com/openai/codex
- Claude Code: https://code.claude.com/docs/en/legal-and-compliance
- Chromium, TigerVNC, noVNC, websockify, Openbox, Debian/Alpine packages and fonts: their upstream and installed package copyright notices apply; Linux package notices are retained in the images.

The Windows setup and portable ZIP contain the host application and container recipes. A separate, versioned Linux runtime archive contains the verified gateway, tools and browser images, including their installed license notices. Tool/browser dependencies are fetched during a source build, or the archive is downloaded and verified during normal installation. The application does not redistribute the original macOS release package or claim affiliation with its author or the third-party providers.
