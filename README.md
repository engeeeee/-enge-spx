<p align="center"><img src="assets/logo.svg" width="88" alt="ENGE SPX"></p>
<h1 align="center">ENGE SPX</h1>
<p align="center">Your projects. A separate workspace. A verifiable proxy exit.</p>
<p align="center"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

ENGE SPX is a personal project maintained by [engeeeee](https://github.com/engeeeee). It runs Claude Code, Codex and a shared Chromium browser in Linux containers, controlled by a Windows desktop client.

The client supports a fixed encrypted first hop followed by a SOCKS5, HTTP or HTTPS landing proxy, plus a compatibility mode for a local v2ray proxy. First-hop and final exit IPs are checked separately before confirmation and monitored while the environment runs.

![ENGE SPX workspace](docs/images/spx-overview.png)

The screenshot shows the actual empty-state source UI in the Linux graphical test environment. See [branding and interface details](docs/branding.zh-CN.md).

## Download

Current version: **0.5.2 Preview**. Get the [Windows x64 release](https://github.com/engeeeee/-enge-spx/releases/tag/v0.5.2-windows).

- `ENGE-SPX-Windows-x64-0.5.2-Setup.exe`: per-user installation with shortcuts.
- `ENGE-SPX-Windows-x64-0.5.2-Portable.zip`: extract everything and run `ENGE-SPX.exe`; keep `_internal` beside it.
- `spx.exe`: the console entry point, included in both packages.

No separate Python installation is needed for packaged builds. The executables are unsigned. Install and start [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) with Linux containers and the WSL 2 backend; Docker Engine 28+ is required.

## Start working

1. Download and install the runtime from the app. Downloads support pause, resume, progress and SHA-256 verification before Docker import.
2. Add your landing proxy, including optional username and password. Import URI lists, JSON, Clash configurations or an explicitly selected HTTPS subscription.
3. Import a supported encrypted line share link from v2ray and choose managed chaining, with separate line and landing selections. A domain-based line requires its server IPv4; its TLS name and verification are preserved. Alternatively, select the explicitly labeled local-proxy compatibility mode.
4. Check the connection, review both first-hop and landing exit IPs and the configured time zone, then confirm.
5. Choose a project and open a tool. Sign in inside the shared browser when required.

```text
Tools / Chromium → fixed encrypted line → remote landing proxy → destination
```

The app does not modify the Windows system proxy. Speed depends on the actual route. A detected connection failure or exit change stops the environment; it does not switch to direct access. Monitoring has a detection interval.

Managed chaining configures no direct or automatic fallback outbound, delegates landing DNS through the line and keeps its diagnostic listener on the gateway's loopback. The external-client compatibility mode cannot prove per-destination routing from a diagnostic exit alone. See [line protection and v2ray setup](docs/line-protection.zh-CN.md).

Runtime and subscription downloads use a separately configured local proxy or the system's loopback proxy. Selecting proxy downloads now fails if no proxy is available; direct downloads require explicitly disabling the option. Source builds use Docker Desktop's own networking. The Docker launcher retains credential-helper lookup even when Windows inherited a PATH from before Docker Desktop was installed.

## Terminal and storage preferences

Choose **Pebrel** under **Preferences → Workspace terminal**, select its exe if
needed, test and save. The choice applies to workspace and login buttons for
Claude Code, Codex and Linux shells. Automatic discovery prefers Pebrel, followed
by Windows Terminal and PowerShell. Other terminals can use a custom executable
and argument template. CLI commands continue in the terminal that invoked them.

Move app settings, logs and runtime download caches to an empty folder on D: or
another drive using the application-data migration controls. Copy verification
precedes activation and source cleanup; partial downloads and the installation
identity are retained. A small location pointer remains in LocalAppData.

Use the separate **Docker Desktop disk migration assistant** for images,
containers and persistent account volumes. It records resources, guides the user
through Docker's **Settings → Resources → Advanced → Disk image location → Apply**,
and checks the target and original resources afterwards. Applying the disk move
in Docker Desktop is required. Project folders and program files are separate.
See [detailed settings and recovery steps](docs/storage-terminal.zh-CN.md).

## Data and security

New settings are stored under `%LOCALAPPDATA%\ENGE-SPX`; credentials are not encrypted with the Windows credential store yet. Persistent tool and browser data live in Docker volumes.

Selected projects are mounted read-write. Tools can modify or delete those real files and can read secrets inside them. Other host directories are not mounted by default. Project tools share account credentials, while Chromium has its own persistent profile. Closing the app leaves the confirmed environment running; use **Stop environment** or `spx stop` to end work.

Chromium currently uses `--no-sandbox`. Container isolation remains, but this preview is not a guarantee against malicious software, data disclosure, fingerprinting or account restrictions. It has not undergone an independent security audit or a complete interactive Windows Desktop acceptance test.

Existing Windows preview installations are detected and reused without moving private files or discarding project containers. See [migration details](docs/migration.zh-CN.md).

## Development

Python 3.12+ with Tk is required for source use. On Windows, run `Start-Windows.cmd`, or install with `python -m pip install -e .` and launch `spx`. Build installers using `packaging/windows/Build-Windows.ps1` after installing Inno Setup 6.

The implementation is in `src/enge_spx`, runtime resources are packaged with it, and Windows-specific build files are in `packaging/windows`. See [development instructions](docs/development.md) for tests and packaging.

## Maintainer and license

Maintained by **engeeeee**, with an original ENGE SPX vector identity. The project continues the Windows implementation previously developed for this account. Historical design references are acknowledged in [NOTICE.md](NOTICE.md); component licenses remain in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

The project retains the [PolyForm Noncommercial License 1.0.0](LICENSE). Independent hosting and branding do not imply authorship of third-party dependencies or remove their license requirements.
