# Changes

## 0.14.2 native mouse editing and quick copy/paste — 2026-11-13

- Distinguish an actual native mouse click from a host drag selection, including
  while the CLI requests mouse events. Clicks use the negotiated SGR protocol,
  never generated arrows or editing the application buffer.
- Copy selected terminal text to the clipboard on left-button release; plain
  clicks do not overwrite clipboard data. Right-click pastes into the current
  draft without submitting; Shift+right-click and the Menu key retain commands.
- Add per-window switches for automatic copy and quick paste; preserve colours,
  custom frame, keyboard shortcuts and explicit Alt native mouse gestures.
- Exercise actual Codex mouse positioning across Unicode and multiple lines,
  right-click text/image paste and API text/image payloads in the existing Qt
  fixture. Keep independent Windows/API and Docker isolation checks.

## 0.14.1 smart terminal usability and updated CLI paste — 2026-11-13

- Remove the exact CLI version allowlist and per-import version subprocess.
  Require each image to produce a new native attachment marker in the live TUI;
  cancel all Enter keys queued before a failed import and preserve the draft.
- Add a genuine copy/paste/select-all context menu, Unicode word and history
  selection snapshots, mouse selection mode and font zoom. Keep ordinary Ctrl+C
  and Ctrl+A behavior when no host selection applies; remove the header copy button.
- Reuse the app custom Qt title bar with native move/maximize/resize. Preserve
  the warm charcoal/clay style; handle ANSI/256/RGB colours, faint/bold/underline
  and strike, safe colour queries and public terminal capability hints.
- Exercise actual Qt Ctrl+V through Codex 0.169.0 and the bundled CLI versions,
  recording executable versions and native visual payloads via a synthetic API.
  Keep physical Windows/real-model acceptance separate. No new dependencies,
  image recipes, mounts, privileges, proxy changes or license changes.

## 0.14.0 Smart Clipboard Paste — 2026-11-13

- Add an owned Qt/ConPTY display for the existing Claude/Codex TUI. Handle
  Ctrl+V locally, preserve native bracketed text paste, IME and draft editing;
  serialize typing, imports and user Enter without a separate chat/upload UI.
- Read Unicode, CF_HDROP, registered PNG and DIB/V5 on demand. Stream selected
  files into the existing bind, or private project-container tmp for read-only
  grants; validate hashes, limits, paths, live sessions and native image chips.
- Keep explicit external terminal settings and existing headless CLI behavior.
  Do not claim image clipboard support for opaque terminal paste bindings.
- Add bounded caches, inactive-only retention, failure recovery, API/PTY tests,
  repeatable Windows acceptance fixtures, dependency notices and documentation.
  Physical Windows/Desktop and real model acceptance remain separately tracked.

## 0.13.6 implicit WSL2 configuration exit fix — 2026-11-13

- Recognize Docker's documented WSL2 default in valid sparse settings instead
  of requiring an explicit enabled user override. Resolve known user, installer
  and admin settings; reject disabled, malformed, conflicting or other backends.
  Do not infer that an ambiguous managed policy is active offline.
- For implicit selections require current-user Docker distribution registration
  with Version=2, plus the existing complete process, pipe and WSL stop proof.
  Recheck configuration/registration before final process/pipe observations.
- Add fixed configuration failure codes without exporting settings or paths;
  bound transient read/sharing retries and avoid spinning on explicit rejection.
- Add real sparse-file, policy/default/invalid-value tests and an owned Windows
  registry/process/pipe Engine.shutdown regression. WSL query results remain
  fixtures in Windows CI, not physical Docker Desktop acceptance.
- Keep Codex/Claude update and terminal behavior, runtime recipes, data formats,
  permissions, dependencies and licenses unchanged.

## 0.13.5 exit budgets and rootless tool updates — 2026-11-13

- Capture Desktop management output in bounded private temporary files instead
  of inherited PIPEs, so a timed-out Windows CLI cannot block while draining
  a descendant plugin. Only the owned CLI is reaped; do not kill Desktop/WSL.
- Reserve independent offline proof time inside a 20-second workspace budget,
  distinguish unsupported platforms from expired budgets, and keep complete
  stopped evidence plus the existing 60-second optional joint-exit deadline.
- Use the selected identity's existing home volume for the npm user prefix
  and prefer its binaries. Keep root-owned image tools as the initial fallback,
  without changing system ownership, identities, images or container privileges.
- GUI AI/login tools leave the protected container shell open with an exit
  status after completion/update/failure. Preserve ordinary CLI exit codes,
  separate argv handling and generic custom-terminal behavior; never auto-retry.
- Add native inherited-handle, budget, shell/argument, actual protected npm
  install, persistent-version and cross-identity update-data regression checks.
  No production dependencies, runtime recipes or license changes.

## 0.13.4 teardown race and exit diagnostics — 2026-11-13

- Wait boundedly when Desktop reports stopping, and repeat complete offline
  observations when the engine pipe disappears before process/WSL teardown.
  Preserve all stop evidence requirements, local context restrictions and the
  optional Desktop exit deadline; never turn a timeout or missing pipe into success.
- Add a workspace-failure dialog with return/retry and direct Copy diagnostics.
  Include the actual running version and safe check stages; copying never
  contacts Docker and remains available when settings cannot be read.
- Save at most 64 thread-scoped, allowlisted checks in a local schema-1 report.
  Omit raw errors, command output, paths and distro/account/node data; report
  write failure cannot mask the original shutdown failure. Keep unverified
  workspace exits blocked and explicit keep-workspace consent unchanged.
- Add delayed-process teardown, deadline, clipboard, report-redaction and
  recovery/DPI coverage. The reporter's actual trigger is still unconfirmed;
  simulated/native-owned fixtures are not physical Docker/WSL acceptance.
- No runtime recipe, production dependency, privilege, terminal or license change.

## 0.13.3 fully closed Desktop exit fix — 2026-11-12

- Fix the missing-pipe exit failure when Docker Desktop and its background
  management API were both closed before ENGE SPX. Preserve explicit stopped
  status as the primary path; add independent read-only WSL2 evidence only for
  the exact local Desktop Linux context when the management API is unavailable.
- Require explicit WSL2 settings, a complete Desktop process snapshot, Win32
  file-not-found for the engine pipe, the registered Docker distro absent from
  WSL's running list, and repeated process/pipe observations. Denied, partial,
  running, restarted, Hyper-V and unknown evidence still cannot claim stopped.
- Reuse lease revocation, runtime-secret cleanup and owned service waits;
  handle the same management-endpoint disappearance during optional joint exit.
  Never start/force Docker or stop other WSL distributions. No data migration,
  runtime recipe, dependency, terminal behavior or license change.

## 0.13.2 verified Desktop exit fixes — 2026-11-11

- Request normal Docker Desktop shutdown with `--detach`, then independently
  verify its stopped status within the existing global deadline. Tolerate
  transient management endpoint gaps; retain a bounded normal-stop fallback
  only when an older CLI explicitly rejects the detach flag.
- Allow verified local cleanup after Desktop was manually closed: require both
  the exact local Desktop Linux pipe context and an explicit stopped management
  status. Revoke the lease, clear runtime secret references and wait for owned
  host services; a missing pipe or unknown state alone is never success.
- When only Desktop confirmation fails after a verified workspace stop, offer
  retry, return, or a guarded one-time app-only exit. Keep saved preferences and
  user data unchanged; do not force Desktop or shut down other WSL distributions.
- Cover source and frozen Windows GUI exits, the manually-closed-first case,
  stale stop proofs, timeout recovery and high-DPI recovery controls. Keep
  terminal launch behavior, network policy, recipes, dependencies and license.

## 0.13.1 formal release — 2026-11-11

- Publish the current feature set as a full GitHub release and mark it Latest
  after the existing Windows/Linux, packaging and Docker gates pass.
- Remove Preview from the application footer, About page and Windows product
  metadata, and clear the executable prerelease flags. Keep versioned assets
  immutable and reject a release that belongs to another source commit.
- Keep the 0.13.0 network, sandbox, credential, identity, resource and exit
  behavior, data formats, image recipes and dependencies unchanged.
- Retain the unsigned executable and real-device acceptance limitations; gather
  actual-use feedback before further feature or performance changes.

## 0.13.0 bounded network measurement preview — 2026-11-11

- Add explicit GUI/CLI final-chain HTTPS first-byte and bounded download tests.
  Keep existing multi-request first-hop/final-exit verification durations separate
  from RTT, bandwidth and AI/noVNC performance. Never auto-run a speed test.
- Use the existing audited session/gateway, fixed HTTPS destination, certificate
  and hostname verification, three requests and about 1 MiB payload. Reject
  redirects, compression, oversized responses and unbounded drip-fed headers.
  Proxy configuration is passed on exec stdin; no target/body/credential upload.
- Revalidate exits/topology before and after, release the guard's operation lock
  during transfer, and discard changed-session results without stopping the new
  workspace. TLS or verification failure requests verified owned shutdown;
  target refusal/timeouts remain incomplete samples if the connection is healthy.
- Add allowlisted local reports, failure-aware exit codes, lazy UI controls,
  cached export and genuine-exit queueing; retain optional Desktop exit and data.
- Add real TLS/CONNECT/adapter fault fixtures under network-none, actual Engine
  scope checks, frozen/DPI regressions and a physical Windows acceptance guide.
  No production dependency, permission, listener, image recipe or license change.

## 0.12.1 optional Docker Desktop exit preview — 2026-11-11

- Add a separate, versioned exit preference, off by default. Explicit Windows
  genuine exit may normally close local Docker Desktop after verified owner
  workspace shutdown and all resource-recording/query work has finished.
- Keep X-to-tray, explicit keep-workspace exit, Engine.stop/shutdown, budget and
  identity changes scoped to the existing behavior. Explain that the opt-in
  Desktop shutdown also interrupts other Docker workloads, without deleting data.
- Use bounded official Desktop management and require explicit stopped status;
  unknown status/permissions/unsupported versions preserve the GUI for retry.
  Never force Desktop or invoke global WSL shutdown. Pending preference-save
  failures cancel exit instead of using a stale global choice. A failed status
  confirmation can be retried/disabled without restarting a verified stopped
  workspace; further Engine activity invalidates that prior proof.
- Add native Windows owned-process fixtures for source/frozen X, Ctrl+Q, opt-in
  and default behavior, plus lifecycle, recording-save and DPI regressions.
  No production dependencies, image recipes, privileges or license changes.

## 0.12.0 field recording preview — 2026-11-11

- Add explicit bounded resource recording in GUI/CLI using the existing monitor.
  Reports separate app, containers, host and shared Desktop/WSL counters, use
  per-recording process/container aliases and omit paths, names, credentials,
  command lines, environment and AI input. Activities are user labels.
- Serialize sampling, queue behind an in-flight query/operation, continue only
  user-started recording in the tray, and cancel/save before genuine exit or
  data migration. Preserve partial evidence if final output cannot be replaced.
- Bound duration, sample count and report size; unavailable is not zero usage,
  sampled maxima are not guaranteed peaks, and shared groups are not additive.
- Reuse strict local IPC context validation for resource access and startup.
  Reject SSH/TCP, remote named pipes and Unix URI authorities before daemon
  queries. Retain manual Docker startup and all existing security/lifecycle rules.
- No production dependencies, image recipes, privileges, listening ports,
  configuration migrations or license changes.

## 0.11.0 workspace identity and diagnostics preview — 2026-11-10

- Add versioned, opt-in workspace identities with separate tool HOME, Chromium
  Profile and downloads. Keep legacy shared volumes and login data. Verify owned
  shutdown before switching; never copy credentials between identities.
- Require explicit project identity and recursive read-only/read-write grants;
  audit names, mounts, users and capabilities before start. Reject stale attach
  and missing/corrupt initialized config without falling back to shared accounts.
- Add lazy GUI/CLI network diagnostics with read-only host routes, controlled
  IPv4/IPv6/UDP observations, real browser language/timezone/local WebRTC checks,
  first-hop/final-exit timings and per-report sanitized export. No debug ports,
  automatic browser startup, fingerprint changes or new production dependencies.
- Request bounded graceful Chromium exit before container stop so rapid identity
  switching can flush pending Profile data. Keep gateway revocation and forced
  shutdown even if graceful close fails. Escape CLI JSON for non-CJK Windows
  pipes; preserve Unicode names without encoding crashes.
- Preserve sandbox, DPAPI, protocol backends, fail-closed guard, resource modes,
  manual Docker startup and X-to-tray/default verified-stop exit behavior.
  See docs/validation-workspaces.zh-CN.md for measured scope and remaining limits.

## 0.10.0 resource management preview — 2026-11-10

- Add schema-1 role/project CPU and memory budgets, normal/low/custom modes and
  previous-settings restore. Missing settings preserve 0.9.0 defaults. Apply
  changes while stopped and reuse project IDs/layers; failures never start an
  unapplied budget. Replace only the data-free gateway to clear a memory limit,
  because Docker update ignores memory=0. Do not change host/WSL global limits.
- Add read-only Win32/Linux process counters and owner-scoped Docker stats with
  explicit application, container, Desktop and WSL2 sources. Register only public
  PID/creation metadata; telemetry failure cannot stop guard. Sample only when
  the resource overview is visible, never overlap samples or start Docker for it.
- Add independent Chromium/display stop and optional browser startup with tools.
  Explicit login still prepares the sandboxed browser. Preserve CLI processes,
  Profile and protected networking; do not fall back to a host browser.
- Reduce background UI polling and duplicate project-list writes without
  reducing safety-check frequency. Keep tray lifecycle and manual Docker startup.
- Default genuine GUI exit to verified workspace shutdown; X still hides to tray.
  Queue exit during work, cancel preparation safely, preserve migration handoff,
  suppress follow-up dialogs, finish resource queries and wait for services.
  Failed/incomplete stop retains a retryable interface; keep-workspace exit needs
  explicit confirmation. Restore existing tray instances through Qt so widget
  visibility and input stay synchronized. Exercise public Ctrl+Q in source and
  frozen GUI tests.
- Add real cgroup/rollback/foreign-workload tests, native process-handle and UI
  lifecycle checks, browser pause/restart regression and same-runner stage
  measurements. No new production dependency, runtime image or capability.

## 0.9.0 proxy and network preview — 2026-11-10

- Extract a Proxy Backend Adapter around the existing sing-box 1.14.3 core;
  retain fixed routing, independent line/final checks, leases and fail-closed
  shutdown. Add VLESS Reality/Vision, VLESS/Trojan/VMess WS/gRPC and Hysteria2
  QUIC/UDP with optional salamander; reject unverified TCP-only detours for QUIC.
- Validate protocol parameters without TLS downgrade, file-path imports or
  credential echo. Preserve 0.8.4 canonical nodes and IDs. Convert common
  Clash/Mihomo nodes while ignoring their routing/providers with explicit notice.
- Upgrade internal bridges to isolated mode using a versioned, stopped-only
  migration journal. Preserve container IDs/layers, recover interruption and
  rollback metadata without starting a weaker policy. Audit DNS and IPv6.
- Wait for the previous guard before approving a new policy, including upgrades
  within the current product name. Interrupt monitor sleep with a public stop
  signal while preserving the network-check cadence and lease deadlines.
- Close the Windows window to the tray; expose restore, keep-workspace interface
  exit and stop-workspace exit. Preserve manual Docker startup, generic terminal
  selection, 0.8.4 browser retirement, sandbox and DPAPI protections.
- Add real TLS/Reality/QUIC/UDP and fixed-chain fixtures, fault injection,
  DNS/IPv6/host-path, migration, identity and native Windows tray regressions.
  No new production dependency, proxy core, host listening port or capability.

## 0.8.4 startup hotfix preview — 2026-11-10

- Retire this installation's stopped browser before connection review and
  confirmation. A pre-sandbox browser left by an upgrade must not block the new
  policy audit; the replacement still passes container and renderer checks.
  Remove no volumes, do not force-remove a running browser, and preserve project
  writable layers, browser Profile, downloads and tool accounts.
- Accept Docker's equivalent equals/colon security-option representations while
  rejecting missing/false no-new-privileges, conflicting duplicates, unconfined
  and altered seccomp policies. Name failed checks without dumping inspect data
  or secrets. No sandbox, capability, TLS or network-isolation relaxation.
- Add current/legacy naming migration regressions, real Docker upgrade markers
  and kernel no-new-privileges checks. Reuse the unchanged runtime recipes and
  existing versioned credential format. Protocol batch 2 remains paused.
- Default to Windows Terminal / PowerShell and use one generic custom-executable
  path for third-party terminals. Remove the Pebrel preset and discovery
  priority; normalize saved legacy selections without losing their executable
  or effective arguments. Document terminal-injected welcome commands without
  adding terminal-specific input filtering or editing external settings.

## 0.8.3 P0 security preview — 2026-11-10

- Require non-root Chromium namespace/PID/network and Seccomp-BPF sandbox
  evidence, including the real display renderer's additional kernel filter and
  nested PID namespace. Use a browser-only, pinned Moby-derived allowlist with
  bounded namespace syscall additions. Keep all capabilities dropped and
  no-new-privileges; make the root filesystem read-only. Unsupported hosts fail
  closed; an explicit CLI-only option is available without a browser fallback.
- Keep browser and CLI filesystems, PIDs and identity volumes separate. Move
  VNC to a private Unix socket, disable X11 TCP and authorize X11 with a private
  cookie so the shared OAuth network namespace does not expose display control.
- Protect Windows application proxy configuration and internal descriptors with
  versioned current-user DPAPI envelopes. Preserve old node IDs/settings, verify
  before migration, resume interrupted writes and reject silent plaintext
  downgrade. Keep POSIX private-file behavior explicitly distinct from encryption.
- Transfer gateway and browser credentials on Docker exec stdin into private RAM
  files, remove the handoff files, and run sing-box with a sealed anonymous memfd.
  Bind only the public lease journal. Pass internal CLI capabilities by environment
  name; third-party terminals attach through a public CLI command without secrets.
- Redact application error/log boundaries, add node deletion and proxy-reference
  cleanup, and support private explicit legacy export for rollback. Preserve
  project writable layers, tool accounts and browser volumes; gateway and browser
  images must upgrade. No TLS/capability/direct-egress relaxation or new Python
  dependency. Moby Apache-2.0 notices are included; the project license is unchanged.
- Add real Windows DPAPI, renderer/privilege, stdin, migration/failure, terminal
  handoff and Cookie/Local Storage regressions plus a same-runner overhead harness.
  Physical Docker Desktop/WSL2 acceptance and real service-account login remain
  separately scoped; subsequent protocol/resource/Profile batches are not included.

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
