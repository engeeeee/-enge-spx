"""Run the real GUI cold-start path in a child process with an isolated Desktop."""
import faulthandler
import gc
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest


def run_child():
    import tkinter as tk
    from enge_spx.gui import App
    from enge_spx.platform_ui import prepare_windows
    from enge_spx.state import Store
    prepare_windows()
    faulthandler.enable()
    base = Path(os.environ["SPX_TEST_FAKE_ROOT"])
    root = tk.Tk()
    errors, ticks = [], []
    root.report_callback_exception = lambda *args: errors.append(str(args[1]))
    app = App(root, Store(base / "data"), auto_check=True)
    os.environ["SPX_TEST_MAIN_HWND"] = str(app.chrome.native.hwnd)
    def pulse():
        ticks.append(1)
        if len(ticks) % 10 == 0:
            app.add_log("Isolated cold-start UI heartbeat")
        root.after(20, pulse)
    root.after(20, pulse)
    stopped = threading.Event()
    def collect():
        while not stopped.wait(.03):
            gc.collect()
    worker = threading.Thread(target=collect)
    worker.start()
    outcome = {}
    def finish():
        outcome.update({"ready": app.docker_ready, "busy": app.busy, "errors": errors, "ticks": len(ticks)})
        root.destroy()
    root.after(5500, finish)
    try:
        root.mainloop()
    finally:
        stopped.set()
        worker.join(2)
    assert outcome.get("ready"), outcome
    assert not outcome["busy"], outcome
    assert not outcome["errors"], outcome
    assert outcome["ticks"] > 30, outcome
    print(json.dumps(outcome))


@unittest.skipUnless(os.name == "nt", "Windows GUI and Desktop cold-start subprocess")
class GUIColdStartTests(unittest.TestCase):
    def test_real_gui_survives_desktop_focus_and_worker_completion(self):
        system = Path(os.environ["SystemRoot"])
        compiler = next((p for p in (system / "Microsoft.NET/Framework64/v4.0.30319/csc.exe", system / "Microsoft.NET/Framework/v4.0.30319/csc.exe") if p.is_file()), None)
        self.assertIsNotNone(compiler)
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
                IntPtr hwnd = new IntPtr(Int64.Parse(Environment.GetEnvironmentVariable("SPX_TEST_MAIN_HWND")));
                SendMessage(hwnd, 0x031A, IntPtr.Zero, IntPtr.Zero);
                SendMessage(hwnd, 0x031E, IntPtr.Zero, IntPtr.Zero);
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
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            shutil.copyfile(cli, base / "Docker App/Docker Desktop.exe")
            for mode in ("legacy", "cli"):
                with self.subTest(mode=mode):
                    for name in ("ready", "launches"):
                        (base / name).unlink(missing_ok=True)
                    env = {**os.environ, "SPX_TEST_FAKE_ROOT": str(base), "SPX_TEST_START_MODE": mode, "PATH": str(cli.parent) + os.pathsep + os.environ.get("PATH", "")}
                    result = subprocess.run([sys.executable, "-X", "faulthandler", str(Path(__file__).resolve()), "--child"], env=env, capture_output=True, text=True, timeout=25)
                    if result.returncode:
                        time.sleep(2)  # Let the owned fake Desktop close before removing its exe.
                    self.assertEqual(result.returncode, 0, f"{mode}: exit={result.returncode}\n{result.stdout}\n{result.stderr}")
                    self.assertEqual((base / "launches").read_text().splitlines(), ["launch"])


if __name__ == "__main__":
    if "--child" in sys.argv:
        run_child()
    else:
        unittest.main()
