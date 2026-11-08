# Changes

## 0.3.1 Preview — 2026-11-08

- Fix Docker credential-helper lookup when ENGE SPX inherits a PATH that does
  not include the Docker Desktop tools. Docker subprocesses receive the CLI's
  directory and available Desktop helper directories while retaining the user's
  Docker credential configuration.
- Let runtime downloads use the system's loopback proxy when proxy downloads
  are enabled and no explicit line proxy is selected. An explicit line takes
  priority; disabling proxy downloads keeps a direct connection.
- Show the chosen download route without credentials, and distinguish timeouts,
  HTTP status errors and incompatible runtime manifests in installation feedback.
- Wait for the guest forwarding listener to accept connections before measuring
  the exit, instead of relying on a fixed delay after the host heartbeat.
- Add regression coverage for Windows credential-helper resolution and download
  routing. Container recipes are unchanged, preserving compatible installed images.

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
