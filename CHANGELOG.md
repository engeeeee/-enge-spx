# Changes

## 0.3.0 Preview — 2026-11-08

- Introduce ENGE SPX as engeeeee's separately maintained personal project.
- Replace the previous public identity with a new vector mark, Windows icons,
  GUI title, executable metadata, installer, shortcuts and `spx` command.
- Organize the Python implementation under `src/enge_spx`, package its resources
  and separate Windows build files under `packaging/windows`.
- Move source and release links to `engeeeee/-enge-spx` and publish verified
  Windows and runtime packages through the independent repository's CI.
- Preserve supported earlier Windows installations through explicit data,
  resource, runtime-protocol and browser-profile compatibility handling.
- Retain project files, tools and browser state while handing over the previous
  background controller before confirming a new connection.
- Keep SOCKS5 / HTTP / HTTPS import, local line-to-landing proxy chains,
  exit checks, download resume and Docker image-store compatibility.
- Rewrite project documentation; retain license terms, third-party notices and
  an accurate historical attribution record.
