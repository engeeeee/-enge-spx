"""Owned Windows fake Desktop; never launches or changes the real Docker."""
from contextlib import contextmanager
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


@contextmanager
def fake_desktop():
    system = Path(os.environ["SystemRoot"])
    compiler = next(p for p in (system / "Microsoft.NET/Framework64/v4.0.30319/csc.exe", system / "Microsoft.NET/Framework/v4.0.30319/csc.exe") if p.is_file())
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        source = base / "Desktop.cs"
        source.write_text(r'''
using System;
using System.IO;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Windows.Forms;
class Desktop {
    [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr hwnd, uint msg, IntPtr wp, IntPtr lp);
    [STAThread] static int Main(string[] args) {
        string root = Environment.GetEnvironmentVariable("SPX_TEST_FAKE_ROOT");
        string marker = Path.Combine(root, "ready");
        string self = Environment.GetCommandLineArgs()[0];
        if (Path.GetFileName(self) == "Docker Desktop.exe") {
            var form = new Form();
            form.Text = "ENGE SPX isolated fake Desktop";
            form.Width = 420; form.Height = 220;
            var timer = new Timer(); timer.Interval = 1800;
            bool persistent = Environment.GetEnvironmentVariable("SPX_TEST_PERSISTENT_DESKTOP") == "1";
            if (persistent) timer.Interval = 100;
            timer.Tick += delegate {
                if (!persistent || File.Exists(Path.Combine(root, "stop-request"))) form.Close();
            };
            form.FormClosed += delegate {
                if (persistent) {
                    File.Delete(marker);
                    File.WriteAllText(Path.Combine(root, "desktop-closed"), "normal");
                }
            };
            form.Shown += delegate {
                File.AppendAllText(Path.Combine(root, "launches"), "launch\n");
                File.WriteAllText(marker, "ready");
                form.Activate();
                string handle = Environment.GetEnvironmentVariable("SPX_TEST_MAIN_HWND");
                string handleFile = Path.Combine(root, "main-hwnd");
                if (File.Exists(handleFile)) handle = File.ReadAllText(handleFile);
                if (!String.IsNullOrEmpty(handle)) {
                    IntPtr hwnd = new IntPtr(Int64.Parse(handle));
                    SendMessage(hwnd, 0x031A, IntPtr.Zero, IntPtr.Zero);
                    SendMessage(hwnd, 0x031E, IntPtr.Zero, IntPtr.Zero);
                    File.WriteAllText(Path.Combine(root, "notified"), "ready");
                }
                timer.Start();
            };
            Application.Run(form);
            return 0;
        }
        string command = String.Join(" ", args);
        if (command == "desktop status --format json") {
            Console.WriteLine(File.Exists(marker) ? "{\"Status\":\"running\"}" : "{\"Status\":\"stopped\"}");
            return 0;
        }
        if (command.StartsWith("desktop stop --timeout ")) {
            File.AppendAllText(Path.Combine(root, "stops"), "normal-stop\n");
            File.WriteAllText(Path.Combine(root, "stop-request"), "normal");
            for (int i = 0; i < 60 && File.Exists(marker); i++) System.Threading.Thread.Sleep(50);
            return File.Exists(marker) ? 1 : 0;
        }
        if (command.StartsWith("desktop start ")) {
            if (Environment.GetEnvironmentVariable("SPX_TEST_START_MODE") == "legacy") return 2;
            var start = new ProcessStartInfo(Path.Combine(root, "Docker App", "Docker Desktop.exe"));
            start.UseShellExecute = false; start.CreateNoWindow = true;
            Process.Start(start);
            return 0;
        }
        if (!command.StartsWith("--context desktop-linux ")) return 3;
        if (command.Contains(" context inspect ")) {
            Console.WriteLine("[{\"Endpoints\":{\"docker\":{\"Host\":\"npipe:////./pipe/dockerDesktopLinuxEngine\"}}}]");
            return 0;
        }
        if (command.Contains(" info ")) {
            if (!File.Exists(marker)) return 1;
            Console.WriteLine("{\"OSType\":\"linux\",\"ServerVersion\":\"29.0.0\",\"Architecture\":\"x86_64\"}");
            return 0;
        }
        return 4;
    }
}''', encoding="utf-8")
        cli = base / "Docker App/resources/bin/docker.exe"
        cli.parent.mkdir(parents=True)
        compiled = subprocess.run([str(compiler), "/nologo", "/target:exe", "/r:System.Windows.Forms.dll", "/r:System.Drawing.dll", "/out:" + str(cli), str(source)], capture_output=True, text=True)
        if compiled.returncode:
            raise AssertionError(compiled.stdout + compiled.stderr)
        shutil.copyfile(cli, base / "Docker App/Docker Desktop.exe")
        try:
            yield base, cli
        finally:
            time.sleep(2)  # A failed GUI must still allow the owned Desktop to exit.


def environment(base, cli, mode):
    for name in ("ready", "launches", "main-hwnd", "notified", "stop-request", "stops", "desktop-closed"):
        (base / name).unlink(missing_ok=True)
    return {**os.environ, "SPX_TEST_FAKE_ROOT": str(base), "SPX_TEST_START_MODE": mode, "PYTHONIOENCODING": "utf-8", "PATH": str(cli.parent) + os.pathsep + os.environ.get("PATH", "")}


def window_api():
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    user.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    user.SendMessageTimeoutW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t, ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_size_t)]
    user.SendMessageTimeoutW.restype = ctypes.c_void_p
    return user


def find_window(user, pid):
    found = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def visit(hwnd, unused):
        owner = ctypes.c_uint32()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        title = ctypes.create_unicode_buffer(256)
        if owner.value == pid and user.IsWindowVisible(hwnd):
            user.GetWindowTextW(hwnd, title, len(title))
            if title.value == "ENGE SPX":
                found.append(hwnd)
        return True
    user.EnumWindows(callback_type(visit), 0)
    return found[0] if found else None


def quit_shortcut(user, hwnd):
    """Exercise the public Ctrl+Q action; no production test-only exit hook."""
    from ctypes import wintypes as w
    class Keyboard(ctypes.Structure):
        _fields_ = [("key", w.WORD), ("scan", w.WORD), ("flags", w.DWORD), ("time", w.DWORD), ("extra", ctypes.c_size_t)]
    class Mouse(ctypes.Structure):
        _fields_ = [("x", w.LONG), ("y", w.LONG), ("data", w.DWORD), ("flags", w.DWORD), ("time", w.DWORD), ("extra", ctypes.c_size_t)]
    class Payload(ctypes.Union):
        _fields_ = [("keyboard", Keyboard), ("mouse", Mouse)]
    class Input(ctypes.Structure):
        _fields_ = [("type", w.DWORD), ("payload", Payload)]
    user.SetForegroundWindow.argtypes = [w.HWND]
    user.GetForegroundWindow.restype = w.HWND
    user.SetForegroundWindow(hwnd)
    deadline = time.monotonic() + 2
    while user.GetForegroundWindow() != hwnd and time.monotonic() < deadline:
        user.SetForegroundWindow(hwnd)
        time.sleep(.05)
    assert user.GetForegroundWindow() == hwnd, "Could not focus the isolated GUI to verify genuine exit"
    time.sleep(.15)  # Let the target consume native activation/focus messages.
    user.SendInput.argtypes = [w.UINT, ctypes.POINTER(Input), ctypes.c_int]
    user.SendInput.restype = w.UINT
    def send(keys):
        events = (Input * len(keys))()
        for event, (key, flags) in zip(events, keys):
            event.type = 1
            event.payload.keyboard.key = key
            event.payload.keyboard.flags = flags
        assert user.SendInput(len(keys), events, ctypes.sizeof(Input)) == len(keys), "Windows rejected the isolated Ctrl+Q input"
    # Hold the modifier while Qt consumes Q, as with physical keyboard input;
    # a zero-duration four-event burst can race Windows focus/key-state updates.
    send([(0xA2, 0)])
    try:
        time.sleep(.08)
        send([(ord('Q'), 0)])
        time.sleep(.15)
    finally:
        send([(ord('Q'), 2), (0xA2, 2)])


def exercise_entry_point(command, base, cli, mode):
    data = base / ("entry-" + mode)
    data.mkdir(exist_ok=True)
    if mode == "legacy":
        (data / "settings.json").write_text(json.dumps({"auto_start_docker": True}), encoding="utf-8")
    process = subprocess.Popen([*command, "--data", str(data), "gui"], env=environment(base, cli, mode), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
    user, hwnd = window_api(), None
    ready_at = None
    log_path = data / "logs/gui.log"
    text = ""
    try:
        deadline = time.monotonic() + 18
        while process.poll() is None and time.monotonic() < deadline:
            if hwnd is None:
                hwnd = find_window(user, process.pid)
                if hwnd:
                    (base / "main-hwnd").write_text(str(hwnd))
            if log_path.is_file():
                text = log_path.read_text(encoding="utf-8")
            if "docker-check-idle reason=docker_stopped" in text and ready_at is None:
                ready_at = time.monotonic()
            if ready_at and time.monotonic() - ready_at > 3:
                break
            time.sleep(.05)
        assert process.poll() is None, f"GUI exited during the read-only Docker check: {process.returncode}"
        assert hwnd and ready_at, "Real GUI never completed the read-only Docker check"
        assert not (base / "launches").exists(), "Opening the GUI launched Desktop"
        assert not (base / "ready").exists(), "Opening the GUI started the engine"
        result = ctypes.c_size_t()
        assert user.SendMessageTimeoutW(hwnd, 0, 0, 0, 2, 1500, ctypes.byref(result)), "GUI stopped responding after the read-only check"
        user.PostMessageW(hwnd, 0x0010, 0, 0)
        if "gui-tray-enabled" in text:
            deadline = time.monotonic() + 3
            while process.poll() is None and user.IsWindowVisible(hwnd) and time.monotonic() < deadline:
                time.sleep(.05)
            assert process.poll() is None and not user.IsWindowVisible(hwnd), "Close did not preserve the GUI in the tray"
            duplicate = subprocess.run([*command, "--data", str(data), "gui"], env=environment(base, cli, mode), capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            assert duplicate.returncode == 0, "Duplicate GUI could not restore the background instance"
            deadline = time.monotonic() + 3
            while not user.IsWindowVisible(hwnd) and time.monotonic() < deadline:
                time.sleep(.05)
            assert user.IsWindowVisible(hwnd), "Original GUI stayed hidden after reopening"
            assert not (base / "launches").exists(), "Tray restore launched Desktop"
            # Verify the restored widget also handles input. A native-only
            # ShowWindow can paint a window that Qt still considers hidden.
            print(f"Real entry point: {Path(command[0]).name} / {mode}; close-to-tray and duplicate-instance restore passed", flush=True)
            quit_shortcut(user, hwnd)
        stdout, stderr = process.communicate(timeout=6)
        assert process.returncode == 0, f"GUI close failed: {process.returncode}\n{stdout}\n{stderr}"
        text = log_path.read_text(encoding="utf-8")
        assert "gui-stop normal" in text and "-error" not in text, text
        assert "gui-exit-complete mode=stop" in text, "Real exit did not complete the default stopped-workspace flow"
        assert not (base / "launches").exists(), "Desktop started without a user action"
        print(f"Real entry point: {Path(command[0]).name} / {mode}; default verified shutdown without starting Desktop passed", flush=True)
    except BaseException as error:
        if process.poll() is None:
            process.kill()
        stdout, stderr = process.communicate(timeout=6)
        if log_path.is_file():
            text = log_path.read_text(encoding="utf-8")
        fault = data / "logs/gui-fault.log"
        details = fault.read_text(encoding="utf-8") if fault.is_file() else "No native fault file"
        raise AssertionError(f"{error}\n{text}\n{details}\n{stdout}\n{stderr}") from error


def exercise_desktop_exit(command, base, cli, enabled):
    """Actual Windows GUI/process shutdown against our owned Desktop fixture."""
    data = base / ("joint-exit-on" if enabled else "joint-exit-off")
    data.mkdir()
    if enabled:
        (data / "exit-preferences.json").write_text(json.dumps({"schema": 1, "close_docker_desktop": True}), encoding="utf-8")
    (data / "account-sentinel").write_text("preserved", encoding="utf-8")
    env = environment(base, cli, "cli")
    env["SPX_TEST_PERSISTENT_DESKTOP"] = "1"
    desktop = subprocess.Popen([str(base / "Docker App/Docker Desktop.exe")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    process = None
    log_path = data / "logs/gui.log"
    try:
        deadline = time.monotonic() + 5
        while not (base / "ready").exists() and time.monotonic() < deadline:
            assert desktop.poll() is None, "Owned Desktop fixture exited during startup"
            time.sleep(.05)
        assert (base / "ready").exists(), "Owned Desktop fixture did not start"
        process = subprocess.Popen([*command, "--data", str(data), "gui"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
        user, hwnd, text = window_api(), None, ""
        deadline = time.monotonic() + 18
        while process.poll() is None and time.monotonic() < deadline:
            hwnd = find_window(user, process.pid)
            if log_path.exists():
                text = log_path.read_text(encoding="utf-8")
            if hwnd and "docker-check-ready" in text:
                break
            time.sleep(.05)
        assert process.poll() is None and hwnd and "docker-check-ready" in text, "GUI did not finish its read-only check"
        assert not (base / "stops").exists(), "Opening the GUI stopped Desktop"
        if "gui-tray-enabled" in text:
            user.PostMessageW(hwnd, 0x0010, 0, 0)
            deadline = time.monotonic() + 3
            while user.IsWindowVisible(hwnd) and time.monotonic() < deadline:
                time.sleep(.05)
            assert process.poll() is None and not user.IsWindowVisible(hwnd), "X did not hide to tray"
            assert desktop.poll() is None and not (base / "stops").exists(), "X stopped Desktop"
            duplicate = subprocess.run([*command, "--data", str(data), "gui"], env=env, capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            assert duplicate.returncode == 0
            deadline = time.monotonic() + 3
            while not user.IsWindowVisible(hwnd) and time.monotonic() < deadline:
                time.sleep(.05)
            assert user.IsWindowVisible(hwnd), "Tray restore failed"
        quit_shortcut(user, hwnd)
        stdout, stderr = process.communicate(timeout=12)
        assert process.returncode == 0, f"GUI exit failed: {stdout}\n{stderr}"
        text = log_path.read_text(encoding="utf-8")
        assert "gui-exit-complete mode=stop" in text and "-error" not in text, text
        assert (data / "account-sentinel").read_text() == "preserved"
        assert (base / "launches").read_text().splitlines() == ["launch"], "App restarted the owned Desktop"
        if enabled:
            assert desktop.wait(timeout=3) == 0 and not (base / "ready").exists()
            assert (base / "stops").read_text().splitlines() == ["normal-stop"]
            assert (base / "desktop-closed").read_text() == "normal"
            assert text.index("gui-exit-workspace-stopped") < text.index("gui-exit-desktop-stopped")
        else:
            assert desktop.poll() is None and (base / "ready").exists(), "Default exit closed Desktop"
            assert not (base / "stops").exists()
        print(f"Real entry point: {Path(command[0]).name}; optional Desktop exit={enabled}, X preserves Desktop, verified workspace first and data preserved (owned fixture)", flush=True)
    except BaseException as error:
        details = log_path.read_text(encoding="utf-8") if log_path.exists() else "no GUI log"
        raise AssertionError(f"{error}\n{details}") from error
    finally:
        if process is not None and process.poll() is None:
            process.kill()  # Only this test-owned GUI, never a user's process.
            process.communicate(timeout=5)
        if desktop.poll() is None:
            (base / "stop-request").write_text("normal")
            try:
                desktop.wait(timeout=5)
            except subprocess.TimeoutExpired:
                desktop.kill()  # Only the Popen-owned fixture in this temp dir.
                desktop.wait(timeout=3)
