"""Owned Windows fake Desktop; never launches or changes the real Docker."""
from contextlib import contextmanager
import ctypes
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
            timer.Tick += delegate { form.Close(); };
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
    for name in ("ready", "launches", "main-hwnd", "notified"):
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


def exercise_entry_point(command, base, cli, mode):
    data = base / ("entry-" + mode)
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
            if "docker-check-ready" in text and ready_at is None:
                ready_at = time.monotonic()
            if ready_at and time.monotonic() - ready_at > 3:
                break
            time.sleep(.05)
        assert process.poll() is None, f"GUI exited during Desktop startup: {process.returncode}"
        assert hwnd and ready_at, "Real GUI never completed Docker preparation"
        assert (base / "notified").is_file(), "Desktop never notified the real GUI window"
        result = ctypes.c_size_t()
        assert user.SendMessageTimeoutW(hwnd, 0, 0, 0, 2, 1500, ctypes.byref(result)), "GUI stopped responding after Desktop startup"
        user.PostMessageW(hwnd, 0x0010, 0, 0)
        stdout, stderr = process.communicate(timeout=6)
        assert process.returncode == 0, f"GUI close failed: {process.returncode}\n{stdout}\n{stderr}"
        text = log_path.read_text(encoding="utf-8")
        assert "gui-stop normal" in text and "-error" not in text, text
        assert (base / "launches").read_text().splitlines() == ["launch"], "Desktop started multiple times"
        print(f"Real entry point: {Path(command[0]).name} / {mode}; cold start, responsive window and normal close passed", flush=True)
    except BaseException as error:
        if process.poll() is None:
            process.kill()
        stdout, stderr = process.communicate(timeout=6)
        fault = data / "logs/gui-fault.log"
        details = fault.read_text(encoding="utf-8") if fault.is_file() else "No native fault file"
        raise AssertionError(f"{error}\n{text}\n{details}\n{stdout}\n{stderr}") from error
