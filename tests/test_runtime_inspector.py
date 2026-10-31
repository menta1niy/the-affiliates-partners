"""Read-only VPS inspector reports DB identity without leaking token values."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "deployment" / "inspect_runtime.py"
spec = importlib.util.spec_from_file_location("inspect_runtime", PATH)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class RuntimeInspectorTests(unittest.TestCase):
    def test_same_live_file_and_token_report_only_comparisons(self):
        with tempfile.TemporaryDirectory() as folder:
            location = Path(folder) / "database.sqlite3"
            location.write_bytes(b"fixture")
            with patch.object(runtime, "properties", side_effect=[
                    {"MainPID": "120", "ActiveState": "active", "WorkingDirectory": folder},
                    {"MainPID": "121", "ActiveState": "active", "WorkingDirectory": folder},
            ]), patch.object(runtime, "process_env", side_effect=[
                    {"PARTNERS_DB_PATH": str(location).encode(),
                     "TELEGRAM_BOT_TOKEN": b"private-test-value"},
                    {"PARTNERS_DB_PATH": str(location).encode(),
                     "TELEGRAM_BOT_TOKEN": b"private-test-value"},
            ]):
                info = runtime.inspect()
            self.assertTrue(info["comparisons"]["same_db_file"])
            self.assertTrue(info["comparisons"]["same_telegram_token"])
            self.assertNotIn("private-test-value", str(info))

    def test_different_process_database_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            a, b = Path(folder) / "a.db", Path(folder) / "b.db"
            a.write_bytes(b"a")
            b.write_bytes(b"b")
            with patch.object(runtime, "properties", side_effect=[
                    {"MainPID": "120", "ActiveState": "active", "WorkingDirectory": folder},
                    {"MainPID": "121", "ActiveState": "active", "WorkingDirectory": folder},
            ]), patch.object(runtime, "process_env", side_effect=[
                    {"PARTNERS_DB_PATH": str(a).encode()},
                    {"PARTNERS_DB_PATH": str(b).encode()},
            ]):
                info = runtime.inspect()
            self.assertFalse(info["comparisons"]["same_db_file"])
            self.assertFalse(info["comparisons"]["same_db_path"])


if __name__ == "__main__":
    unittest.main()
