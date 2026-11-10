from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from enge_spx.__main__ import main
from enge_spx.resource_limits import preset
from enge_spx.state import Store


class ResourceCLITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = Store(self.root / "data")

    def invoke(self, *arguments):
        out, error = io.StringIO(), io.StringIO()
        with patch("sys.argv", ["spx", "--data", str(self.store.home), "resources", *arguments]), redirect_stdout(out), redirect_stderr(error):
            code = main()
        return code, out.getvalue(), error.getvalue()

    def test_show_settings_never_queries_or_starts_docker(self):
        with patch("enge_spx.engine.Docker.run", side_effect=AssertionError("Unexpected Docker query")):
            code, out, error = self.invoke("--show-settings")
        self.assertEqual(code, 0, error)
        self.assertEqual(json.loads(out), preset())

    def test_apply_and_restore_work_without_installing_or_starting_docker(self):
        path = self.root / "budget.json"
        path.write_text(json.dumps(preset("low")), encoding="utf-8")
        with patch("enge_spx.engine.Docker.run", side_effect=AssertionError("Unexpected Docker query")):
            code, out, error = self.invoke("--apply", str(path))
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(out), preset("low"))
            code, out, error = self.invoke("--restore")
        self.assertEqual(code, 0, error)
        self.assertEqual(json.loads(out), preset())

    def test_bad_encoding_json_or_null_rejects_without_echoing_input_or_stopping(self):
        path = self.root / "invalid.json"
        for content in (b'\xffsynthetic-secret', b'{"synthetic-secret":', b'null'):
            with self.subTest(content=content):
                path.write_bytes(content)
                with patch("enge_spx.engine.Engine._stop") as stop:
                    code, out, error = self.invoke("--apply", str(path))
                self.assertEqual(code, 1)
                self.assertNotIn("synthetic-secret", error)
                stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
