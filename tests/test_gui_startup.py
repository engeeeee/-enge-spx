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

from desktop_harness import environment, exercise_entry_point, exercise_desktop_exit, fake_desktop


def run_child():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QPushButton
    from enge_spx.ui import style
    from enge_spx.ui.controller import Controller
    from enge_spx.ui.window import Window
    from enge_spx.state import Store
    faulthandler.enable()
    base = Path(os.environ["SPX_TEST_FAKE_ROOT"])
    root = QApplication([])
    style.apply(root)
    errors, ticks = [], []
    store = Store(base / "data")
    store.write("settings.json", {"auto_start_docker": True})
    controller = Controller(store)
    controller.notice.connect(lambda title, text, error: errors.append(text))
    app = Window(controller)
    app.show()
    os.environ["SPX_TEST_MAIN_HWND"] = str(int(app.winId()))
    QTimer.singleShot(500, controller.check_docker)
    manual_started = False
    def pulse():
        nonlocal manual_started
        ticks.append(1)
        if not manual_started and controller.startup_error == "docker_stopped" and not controller.busy:
            assert not (base / "launches").exists(), "Opening the GUI launched Desktop"
            manual_started = True
            app.show_page("downloads")
            next(item for item in app.findChildren(QPushButton) if item.text() == "启动并检测").click()
        if len(ticks) % 10 == 0:
            controller.events.put(("log", "Isolated cold-start UI heartbeat"))
    timer = QTimer()
    timer.setInterval(20)
    timer.timeout.connect(pulse)
    timer.start()
    stopped = threading.Event()
    def collect():
        while not stopped.wait(.03):
            gc.collect()
    worker = threading.Thread(target=collect)
    worker.start()
    outcome = {}
    def finish():
        outcome.update({"ready": controller.docker_ready, "busy": controller.busy, "errors": errors, "ticks": len(ticks), "manual_started": manual_started})
        app.finish_close()
    QTimer.singleShot(5500, finish)
    try:
        root.exec()
    finally:
        stopped.set()
        worker.join(2)
    assert outcome.get("ready"), outcome
    assert outcome["manual_started"], outcome
    assert not outcome["busy"], outcome
    assert not outcome["errors"], outcome
    assert outcome["ticks"] > 30, outcome
    print(json.dumps(outcome))


@unittest.skipUnless(os.name == "nt", "Windows GUI and Desktop cold-start subprocess")
class GUIColdStartTests(unittest.TestCase):
    def test_optional_desktop_exit_is_opt_in_and_graceful(self):
        command = [os.environ["SPX_TEST_PACKAGED_GUI"]] if "SPX_TEST_PACKAGED_GUI" in os.environ else [sys.executable, "-X", "faulthandler", "-m", "enge_spx"]
        with fake_desktop() as (base, cli):
            for enabled in (False, True):
                with self.subTest(enabled=enabled):
                    exercise_desktop_exit(command, base, cli, enabled)

    def test_real_entry_point_never_starts_desktop_on_open(self):
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
        unittest.main(argv=[sys.argv[0], "GUIColdStartTests.test_real_entry_point_never_starts_desktop_on_open", "GUIColdStartTests.test_optional_desktop_exit_is_opt_in_and_graceful", "-v"])
    else:
        unittest.main()
