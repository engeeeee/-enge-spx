# Qt, PySide6 and Shiboken6

ENGE SPX 0.8 uses unmodified Qt / PySide6 Essentials / Shiboken6 **6.12.0**
shared libraries. Qt is Copyright The Qt Company Ltd. and other contributors.
These independently licensed libraries are distributed under LGPL version 3;
their applicable notices and third-party terms remain in force.

`qt-6.12.0-notices.zip` retains the upstream license files and attribution
metadata from Qt Base, Qt SVG, Qt Image Formats and PySide/Shiboken sources.
The Windows build expands this archive into `THIRD-PARTY-LICENSES/Qt` and
includes the LGPL and GPL license texts. Notices for optional upstream modules
do not imply that every such module is used by the application.

Corresponding upstream sources for this exact version are available at:

- [Qt Base 6.12.0](https://download.qt.io/official_releases/qt/6.12/6.12.0/submodules/qtbase-everywhere-src-6.12.0.tar.xz)
- [Qt SVG 6.12.0](https://download.qt.io/official_releases/qt/6.12/6.12.0/submodules/qtsvg-everywhere-src-6.12.0.tar.xz)
- [Qt Image Formats 6.12.0](https://download.qt.io/official_releases/qt/6.12/6.12.0/submodules/qtimageformats-everywhere-src-6.12.0.tar.xz)
- [PySide6 / Shiboken6 6.12.0](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/pyside-setup-everywhere-src-6.12.0.tar.xz)
- [Complete Qt source release](https://download.qt.io/official_releases/qt/6.12/6.12.0/)

The shared libraries remain separate files in the portable/installed runtime
(`_internal/PySide6` and `_internal/shiboken6`). They may be replaced with
interface-compatible modified builds. Application source and build scripts are
available in the corresponding ENGE SPX release tag.

The application's PolyForm Noncommercial restrictions do not apply to the
LGPL-covered components or restrict reverse engineering of the combined work
for debugging modifications to those components. This notice supplies that
permission where needed; each component retains its own license.
