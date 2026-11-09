# Changes

## 0.8.2 Preview — 2026-11-09

- Fix the reported Windows lease-renewal failure: new gateways read a bounded
  tail of append-only lease records instead of requiring replacement of a file
  held by Docker Desktop. Ignore incomplete records, honor explicit revocation
  and retain expiry when the host stops renewing. Reset the journal while stopped.
- Retry short Windows sharing conflicts on other atomic JSON writes. Keep the
  detached guard alive after an I/O error without extending the last valid lease;
  continue stopping Docker resources even if writing the revocation file fails.
- Reuse the existing isolated session for exit checks instead of creating a
  disposable container every tick. Check the two exit sources and direct-egress
  block in parallel; fetch supplementary geography only during setup/review.
- Add per-stream bounded receive credits to the local proxy tunnel so a slow
  connection cannot block every stream. Preserve the earlier 0.2 tunnel protocol
  when using its exact legacy gateway. Enable display reconnect, allow more time
  for WebSocket pongs and disable small-packet buffering on the local VNC socket.
- Remove the browser image's preinstalled CJK font package. Keep Latin/emoji
  fonts, the project image and UTF-8 locale unchanged. Terminal Chinese uses the
  Windows terminal's fonts; Chinese web pages may need their own web fonts.
  This reduces one font signal and does not provide an undetectable browser.
- Add Windows file-sharing regressions, partial/revoked journal checks, slow
  stream isolation, browser font inventory and real PTY Chinese round-trip tests.
  Exercise a browser-only environment for 190 seconds without any shell command
  or foreground renewal, longer than a complete production lease.

## 0.8.1 Preview — 2026-11-09

- Make Docker startup explicit. Opening the app and rechecking status never
  launch Docker Desktop, containers or downloads. Start only after a user action
  such as Prepare or Start and check. Ignore the earlier auto-start preference
  on upgrade and replace its toggle with a description of the manual behavior.
- Wait up to 30 seconds for the operation lock when opening a tool or browser,
  so the guard's immediate post-confirmation check does not fail the first click.
  Keep the UI responsive and show a waiting message. Retry only lock acquisition;
  route failures still reject the action and tool launches are never repeated.
- Prepare the tool command, project and browser in one protected operation.
  Open the prepared viewer after terminal launch without a second readiness
  probe or lock acquisition. Cover Claude Code, Codex, shell and login actions.
- Add guard-contention, launch-once, timeout and route-failure regressions. Check
  source and frozen GUI entries with fresh and older auto-start settings, and
  exercise explicit Desktop startup through the actual Windows button.

## 0.8.0 Preview — 2026-11-09

- Replace the Tk/Canvas interface with native Qt widgets, warm charcoal surfaces
  and muted clay actions. Unify cards, fields, menus, progress, logs and dialogs;
  retain the ENGE SPX mark with the matching clay palette.
- Use logical-pixel layouts and measured brand text. At narrow widths, compact
  the sidebar and move the complete product name into the title bar. Adapt the
  overview's actions, steps and metrics to the available width. Bound windows
  and scrolling dialogs to the monitor work area.
- Construct secondary pages on first use. Deliver worker output in bounded
  batches, merge progress updates and update state only when values change.
  The worker-delivery timer sleeps while idle; page switches retain their widgets.
- Keep custom title bars, native move/resize/minimize/maximize and modal dialogs
  with Cancel as the default confirmation. Return to the workbench after automatic
  Docker startup unless the user explicitly minimized it. Record process/thread
  identity and window state so focus changes and duplicate launches are clearer.
- Preserve proxy imports, explicit exit confirmation, runtime downloads, terminal
  presets, data relocation and Docker disk migration. CLI and container control
  remain independent of the GUI; container recipes are unchanged.
- Add native Qt layout/idle checks, 125% / 150% / 200% Windows scale checks,
  actual-entry cold starts and frozen Qt GUI checks. Include Qt/PySide/Shiboken
  license texts, upstream notices and corresponding-source links in the packages.

## 0.7.1 Preview — 2026-11-09

- Harden startup after reports of a silent 0.7.0 exit: keep Tk's original
  Windows window procedure instead of installing a ctypes WNDPROC callback.
  Preserve the black/amber interface, custom title bars, taskbar presence,
  minimize/maximize/restore and eight custom resize handles. Keep maximization
  inside the monitor work area. The reported user's crash stack is not yet
  available, so this does not identify every possible startup failure.
- Explicitly focus themed modal dialogs so the initial Cancel button receives
  keyboard input with the callback-free frame.
- Build with the selected Python instead of letting `py -3` pick a different
  installed interpreter. Recreate a mismatched build venv and check that the
  distributed runtime matches the Python 3.12 used by CI source tests.
- Record bounded local GUI lifecycle, exception locations and fatal stacks in
  the data directory's `logs` folder, including windowed executables without
  stderr. Omit exception messages and frame locals; suspend the files during
  verified data migration and reopen them at the committed location.
- Exercise the actual source entry point and frozen Windows GUI with automatic
  fake-Desktop startup, focus/theme notifications, engine readiness, continued
  responsiveness and orderly close. Cover both management CLI and legacy
  Desktop fallback; retain the existing GUI controls and container checks.

## 0.7.0 Preview — 2026-11-09

- Rework the desktop UI with warm-black surfaces, amber actions, rounded cards,
  grouped navigation, dark input fields, readable logs and matching application
  and navigation icons. Compact preparation into four horizontal steps and show
  line and landing exits separately on the overview.
- Replace the system title bar in the main window and in-app dialogs with
  custom chrome. On Windows, keep native shell styles and process non-client
  sizing/hit tests to retain taskbar, minimize, maximize, restore and edge resize;
  maximize within the monitor work area. Leave system file pickers native.
- Theme notices and confirmation dialogs, preserve modal grabs and focus, and
  make the initial confirmation focus the cancel action. Keep route confirmation,
  startup cancellation, terminal choices and persistent Docker resources intact.
- Add geometry tests, native Windows frame/state checks, integrated GUI control
  checks, and source screenshots plus a packaged native-frame gate in CI.

## 0.6.0 Preview — 2026-11-08

- Prepare a workspace in one flow: detect or start Docker Desktop, wait for the
  local Linux engine, verify or install runtime images, then check the configured
  route and require explicit exit confirmation. Opening the app does not start
  the first runtime download. Add cancellation, a bounded Desktop wait, startup
  preferences, actionable installation feedback and a private-data-free summary.
- Support Docker's management CLI and older Desktop installations, including
  custom-drive paths. Never switch the global Docker context or container engine;
  reuse matching images and preserve existing account and project data.
- Add `spx start` and `spx diagnostics`, plus startup, cancellation and native
  Windows fake-Desktop integration checks.
- Move all active repository and release URLs to `engeeeee/ENGE-SPX`. Make the
  default README Chinese, lead with the app's purpose and core isolation/routing
  features, and add a quick start, security model, contribution and support docs,
  issue/PR templates and a versioned Chinese About configuration.

## 0.5.2 Preview — 2026-11-08

- Prevent Docker-injected `NO_PROXY` and other proxy environment variables from
  bypassing the explicit first-hop diagnostic proxy. Clear both forms of
  `NO_PROXY` for final-exit probes as well, retaining the existing runtime images.
- Invalidate older connection evidence and test the diagnostic with poisoned
  environment variables while the gateway has no direct Internet route; the
  encrypted line remains the only path to the IP measurement providers.
- Mark the intermediate 0.5.0 / 0.5.1 preview releases with an upgrade notice after
  publishing the verified 0.5.2 packages. Existing assets and tags stay immutable.

## 0.5.1 Preview — 2026-11-08

- Keep the download proxy independent of the workspace line switch, so first
  installation and subscription imports can use an explicit v2ray loopback proxy
  before importing any line or landing. Reading the system proxy does not enable
  or switch workspace routing. Empty download-proxy fields use system detection;
  unavailable proxy downloads still fail closed.
- Use the current download controls for subscriptions, including unsaved proxy
  choices, and clearly label single-landing mode and pending routing changes.

## 0.5.0 Preview — 2026-11-08

- Add managed encrypted first-hop routing with a fixed line-to-landing chain and
  no direct or automatic fallback outbound. Import a supported line share link
  from v2ray and choose the landing separately. Pin the line server's IPv4 when
  its address is a domain, preserving TLS verification and SNI.
- Check and pin the first-hop exit separately from the final landing exit.
  Reject line mismatch or failure before querying the landing, and preserve the
  specific stop reason. Keep the diagnostic listener on the gateway's loopback
  interface so tools cannot use it to bypass the landing.
- Delegate landing-domain resolution through the first hop instead of host DNS.
  Retain a clearly labeled v2ray-compatible local-proxy mode and export v2rayN
  destination rules without credentials. A matching diagnostic exit alone does
  not prove the external client's per-destination routing.
- Stop downloads when proxy downloads are selected but no loopback proxy is
  available. Direct downloads now require explicitly disabling that option.
  Subscription downloads share the selected download proxy, reject HTTP
  redirects and bound the decompressed response size.
- Preserve existing nodes and landing selection when importing additional line
  nodes. Extend native integration with independent line pins, remote landing DNS,
  diagnostic-port isolation, and failure of a managed first hop while the landing
  remains alive. Container recipes stay compatible with the previous release.

## 0.4.0 Preview — 2026-11-08

- Add configurable workspace terminals, with a Pebrel preset, automatic discovery,
  Windows Terminal and PowerShell options, custom exe/argument templates, and a
  local terminal test. Claude Code, Codex, Linux shells and login windows share
  the saved choice. Automatic selection prefers Pebrel and does not invoke CMD.
- Add application-data relocation to a chosen drive, including partial downloads,
  settings and logs. Stop background services, verify each copied file, preserve
  the installation identity, switch the default location and release verified
  source files. Old explicit data paths redirect to the new location.
- Protect relocated credentials with a private target directory; report missing
  drives without creating a fresh environment. Recreate only the stopped gateway
  whose host bind mount changed, preserving project containers and writable layers.
- Add a Docker Desktop disk-migration assistant with a target folder, resource
  snapshot and post-move checks. Moving the VHDX itself requires confirmation in
  Docker Desktop's supported Disk image location settings.
- Extend native Docker integration to verify project, account, browser and layer
  persistence after relocation; exercise migration through the source GUI and
  native Windows process argument handling in CI.

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
- Move source and release links to `engeeeee/ENGE-SPX` and publish verified
  Windows and runtime packages through the independent repository's CI.
- Preserve supported earlier Windows installations through explicit data,
  resource, runtime-protocol and browser-profile compatibility handling.
- Retain project files, tools and browser state while handing over the previous
  background controller before confirming a new connection.
- Keep SOCKS5 / HTTP / HTTPS import, local line-to-landing proxy chains,
  exit checks, download resume and Docker image-store compatibility.
- Rewrite project documentation; retain license terms, third-party notices and
  an accurate historical attribution record.
