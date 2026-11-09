"""Run the real GUI cold-start path in a child process with an isolated Desktop."""
import faulthandler
import gc
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest

from desktop_harness import environment, exercise_entry_point, fake_desktop


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
    def test_real_entry_point_survives_desktop_launch(self):
        command = [os.environ["SPX_TEST_PACKAGED_GUI"]] if "SPX_TEST_PACKAGED_GUI" in os.environ else [sys.executable, "-X", "faulthandler", "-m", "enge_spx"]
        with fake_desktop() as (base, cli):
            for mode in ("legacy", "cli"):
                with self.subTest(mode=mode):
                    exercise_entry_point(command, base, cli, mode)

    def test_real_gui_survives_desktop_focus_and_worker_completion(self):
        with fake_desktop() as (base, cli):
            for mode in ("legacy", "cli"):
                with self.subTest(mode=mode):
                    env = environment(base, cli, mode)
                    result = subprocess.run([sys.executable, "-X", "faulthandler", str(Path(__file__).resolve()), "--child"], env=env, capture_output=True, text=True, timeout=25)
                    self.assertEqual(result.returncode, 0, f"{mode}: exit={result.returncode}\n{result.stdout}\n{result.stderr}")
                    self.assertEqual((base / "launches").read_text().splitlines(), ["launch"])


if __name__ == "__main__":
    if "--child" in sys.argv:
        run_child()
    elif "--packaged" in sys.argv:
        os.environ["SPX_TEST_PACKAGED_GUI"] = str(Path(sys.argv[sys.argv.index("--packaged") + 1]).resolve(strict=True))
        unittest.main(argv=[sys.argv[0], "GUIColdStartTests.test_real_entry_point_survives_desktop_launch", "-v"])
    else:
        unittest.main()
