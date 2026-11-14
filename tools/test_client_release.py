"""Focused Windows client regression; Linux retains the complete unit suite."""
from pathlib import Path
import sys
import unittest

tests = str(Path(__file__).resolve().parents[1] / 'tests')
loader, suite = unittest.TestLoader(), unittest.TestSuite()
for pattern in ('test_app_update*.py', 'test_exit_timezone.py', 'test_workspace_timezone.py',
                'test_terminal_preferences.py', 'test_monitor_reliability.py', 'test_exit_lifecycle.py',
                'test_exit_recovery_ui.py', 'test_gui_diagnostics.py', 'test_windows_runtime.py'):
    suite.addTests(loader.discover(tests, pattern=pattern))
raise SystemExit(0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1)
