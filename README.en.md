<p align="center"><img src="assets/logo.svg" width="76" alt="ENGE SPX"></p>
<h1 align="center">ENGE SPX</h1>
<p align="center"><strong>An isolated AI coding workspace for Windows</strong></p>
<p align="center">Run Claude Code, Codex and a workspace browser in Linux containers with a chosen, verified proxy exit.</p>
<p align="center"><a href="README.md">简体中文</a> · <strong>English</strong> · <a href="https://github.com/engeeeee/ENGE-SPX/releases/tag/v0.7.0-windows">Download</a></p>

**ENGE SPX brings AI coding tools, a workspace browser and proxy routing into one Windows desktop workflow.** Select a project, configure a route, review the exits, then open your tools. Commands run inside Linux containers while your selected project stays on your own disk and your preferred terminal hosts the interactive window.

It is intended for people who want to reduce exposure of their everyday Windows environment, keep workspace dependencies and browser data separate, and control how the workspace reaches external services. You supply the AI accounts, line and landing proxies.

## Core capabilities

| Capability | What it provides |
| --- | --- |
| **Containerized coding tools** | Claude Code, Codex and Linux commands run in containers with the selected project mounted, keeping tool dependencies apart from everyday Windows applications |
| **A workspace browser** | A persistent Chromium profile for login and authorization, separate from the host browser; the workspace profile is shared between projects |
| **A fixed line-to-landing chain** | A supported encrypted first hop followed by a SOCKS5, HTTP or HTTPS landing proxy, plus an explicitly labeled local-v2ray compatibility mode |
| **Exit review and monitoring** | Separate first-hop and final-exit checks, explicit confirmation before use, and environment shutdown when monitoring detects a connection, exit or topology problem |

```mermaid
flowchart LR
    W["Windows controller"] -. "Selected project, read-write" .-> T
    subgraph C["Docker Linux workspace"]
        T["Claude Code / Codex / Linux shell"]
        B["Workspace Chromium"]
        G["Controlled network and gateway"]
        T --> G
        B --> G
    end
    G --> L["Fixed encrypted line"]
    L --> P["SOCKS5 / HTTP / HTTPS landing"]
    P --> S["Destination"]
```

This diagram shows managed chaining. The browser does not mount the project or tool-account volume. Other host directories are not mounted by default.

## Typical uses

- Run Claude Code or Codex on Windows with container-managed Linux dependencies, a workspace browser and your existing project directory.
- Add a stable landing proxy behind a supported encrypted line, or reuse your existing local v2ray client as the first-hop transport.
- Limit the directories exposed to tools, review the actual workspace exits and stop the environment when detected conditions change.

## Download and start

Current release: **[0.7.0 Preview](https://github.com/engeeeee/ENGE-SPX/releases/tag/v0.7.0-windows)**. Windows x64 requires Docker Desktop with Linux containers / WSL 2 and Docker Engine 28+. Packaged builds do not require a separate Python installation. Executables are currently unsigned.

- **[Windows installer](https://github.com/engeeeee/ENGE-SPX/releases/download/v0.7.0-windows/ENGE-SPX-Windows-x64-0.7.0-Setup.exe)**: per-user setup with shortcuts.
- **[Portable ZIP](https://github.com/engeeeee/ENGE-SPX/releases/download/v0.7.0-windows/ENGE-SPX-Windows-x64-0.7.0-Portable.zip)**: extract everything, run `ENGE-SPX.exe` and keep `_internal` beside it.
- Both packages contain `spx.exe`. Checksums and the matching runtime are on the release page.

1. Install [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) once and complete its license, WSL and Linux-engine initialization.
2. Click **一键准备环境** in ENGE SPX. It starts the installed Desktop, waits for actual readiness, then reuses or installs matching runtime images.
3. Add a landing and choose a managed encrypted line or the local-proxy compatibility mode.
4. Check the route, review both exits and the time zone, confirm, then select a project and open a tool.

The first runtime download is about 1 GB and starts after you click; existing images are reused. Download progress is visible and cancellation preserves data. There is no need to handle the runtime archive manually. The UI is currently Chinese; see the [quick start](docs/quickstart.zh-CN.md) and [installation troubleshooting](docs/installation-troubleshooting.zh-CN.md).

<details>
<summary>See the preparation interface</summary>

![ENGE SPX preparation interface](docs/images/spx-startup.png)

This is the actual source UI captured in native Windows CI. It does not replace interactive acceptance on each user's display and DPI configuration.

</details>

## Use your existing line and landing

| Mode | When to use it | Control and limitations |
| --- | --- | --- |
| **Managed chaining, recommended** | Import a supported encrypted share link and select the landing separately | ENGE SPX configures the fixed chain without DIRECT or automatic fallback. Domain-based line servers require their IPv4; TLS verification and SNI are preserved |
| **Local v2ray compatibility** | Keep the existing client or use a transport not supported by the importer | The external client controls per-destination routing to the landing. Matching diagnostic exits cannot prove that every destination followed the same route |

With the first hop disabled, the host connects to the landing; this does not provide a fixed encrypted first hop. ENGE SPX does not rewrite the Windows system proxy. A system-level TUN may still change the outer path to the line server.

Landings support authenticated or unauthenticated SOCKS5 / HTTP / HTTPS. Import URI lists, JSON, Clash, local files or explicitly fetched HTTPS subscriptions. Unsupported transport parameters are rejected. See [proxy configuration](docs/proxies.zh-CN.md) and [line protection](docs/line-protection.zh-CN.md).

Runtime and subscription downloads use a separate local download proxy. Selecting proxy downloads fails if the proxy is unavailable; direct downloads require explicitly disabling the option. Source builds use Docker Desktop's networking.

## Isolation and its boundaries

- **Files and privileges**: selected projects are mounted read-write. Tools can read secrets, modify code and delete real files in those projects. Tool containers do not mount Docker's management interface; capabilities are dropped and `no-new-privileges` is enabled.
- **Accounts and browser data**: the workspace browser profile is separate from the everyday host browser. Tool accounts and the workspace profile are shared between projects. Separate data directories create separate managed instances; changing projects alone does not change identity.
- **Network paths**: tools use an internal network and gateway. Managed chaining has no direct fallback; local compatibility still depends on the external client's routing and the service providers.
- **Monitoring**: changes stop the environment when detected. IP monitoring has an interval and request timeouts, so exit changes are not detected instantaneously.

Containers depend on the host, Docker and WSL. Chromium currently uses `--no-sandbox`, and proxy credentials are not encrypted with the Windows credential store. The preview has not had an independent security audit or full acceptance testing on the user's Windows + Docker Desktop + v2ray + Pebrel combination. It does not guarantee anonymity, speed or account acceptance. Read the [security model](docs/security-model.zh-CN.md) for the full scope.

## Terminal, downloads and storage

The interface uses warm-black surfaces and amber accents, with custom title bars
for the main window and in-app dialogs. The Windows frame retains native
minimize, maximize, restore and resize behavior. System file pickers remain native.

Use Pebrel, Windows Terminal, PowerShell or a custom executable and argument template. The selected terminal hosts the window; tools still run in their container.

Downloads support pause, resume, speed/progress display, SHA-256 and exact image-recipe validation. App configuration, logs and download caches can move to another drive. Docker's images, containers and volumes use a separate disk-migration assistant and require applying the move in Docker Desktop. Project and program directories remain separate. See [storage and terminal settings](docs/storage-terminal.zh-CN.md).

Closing the window leaves the confirmed environment and monitor running. Use **停止环境** or `spx stop` to finish. Stopping or uninstalling does not intentionally delete project files or Docker volumes; backups remain the user's responsibility.

## Documentation and community

Most detailed guides are in Chinese:

| Topic | Guide |
| --- | --- |
| Installation and first workspace | [Quick start](docs/quickstart.zh-CN.md) |
| Protocols and routing | [Proxies](docs/proxies.zh-CN.md) · [Line protection](docs/line-protection.zh-CN.md) |
| Common questions and security | [FAQ](docs/faq.zh-CN.md) · [Security model](docs/security-model.zh-CN.md) |
| Upgrading existing data | [Migration](docs/migration.zh-CN.md) |
| Reports and contributions | [Support](SUPPORT.md) · [Contributing](CONTRIBUTING.md) · [Security reporting](SECURITY.md) |

## Development and status

Maintained by [engeeeee](https://github.com/engeeeee). Source use requires Python 3.12+ with Tk. Install with `python -m pip install -e .` and launch `spx`, or use `Start-Windows.cmd` on Windows. Windows packaging uses PyInstaller and Inno Setup. See [development instructions](docs/development.md), [0.7.0 validation](docs/validation-0.7.zh-CN.md) and [CHANGELOG](CHANGELOG.md).

The current focus is Windows x64, controlled proxy paths and existing-data compatibility. There is no Windows ARM64 package or automatic updater. Unsupported WS / gRPC / Reality / XTLS / uTLS parameters cannot be imported as managed lines.

## License and attribution

The project uses [PolyForm Noncommercial 1.0.0](LICENSE). It is source-available under a noncommercial license, not an OSI open-source license. Separate branding does not remove third-party obligations. See [NOTICE](NOTICE.md) for provenance and [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md) for component terms.
