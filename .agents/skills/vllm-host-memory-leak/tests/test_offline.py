"""Host-only regression cases; never attach to a process or import torch/BCC."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OfflineDiagnostics(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def cli(self, script, *args):
        return subprocess.run(
            [sys.executable, "-X", "utf8", str(SCRIPTS / script), *map(str, args)],
            capture_output=True, text=True, encoding="utf-8", check=False,
        )

    def write_jsonl(self, rows):
        path = self.root / "samples.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return path

    def sample(self, at, ticks=10):
        return {"at": at, "processes": [{
            "pid": 42, "start_ticks": ticks, "boot_id": "fixture-boot",
            "uss_kib": 1024, "pss_kib": 2048, "rss_kib": 3072,
        }]}

    def notify(self, at, reads, polls, pid=42):
        return {"at": at, "pid": pid, "queues": [{
            "queue": "fixture", "socket_pointer": 123, "notify_address": "ipc://fixture",
            "created_mono": 1, "reader": True,
            "totals": {"shm_reads": reads, "poll_calls": polls},
        }]}

    def test_bcc_uses_mapping_file_offset(self):
        reports = load("bcc_parse").parse_reports(
            "[12:00:00] Top 10 stacks with outstanding allocations:\n"
            "  1312 bytes in 2 allocations from stack\n"
            "    0x1123 zmq::mailbox_t::send\n",
            "1000-2000 r-xp 00003000 00:00 0 /lib/libzmq.so\n",
        )
        self.assertEqual(len(reports), 1)
        stack = reports[0]["stacks"][0]
        self.assertEqual((stack["bytes"], stack["blocks"]), (1312, 2))
        self.assertEqual(stack["frames"][0]["file_offset"], "0x3123")

    def test_memory_rejects_pid_reuse(self):
        source = self.write_jsonl([self.sample(100), self.sample(160, ticks=20)])
        plot = load("plot_memory")
        with self.assertRaisesRegex(ValueError, "Multiple process lifetimes"):
            plot.read_rows(source, "jsonl", 42)
        rows, skipped = plot.read_rows(source, "jsonl", 42, start_ticks=20)
        self.assertEqual((len(rows), skipped, rows[0]["USS"]), (1, 0, 1.0))

    def test_stale_data_does_not_produce_chart(self):
        source = self.write_jsonl([self.sample(100), self.sample(160)])
        prefix = self.root / "chart"
        result = self.cli("plot_memory.py", "--input", source, "--pid", 42, "--output", prefix)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Data stale or host clock skew", result.stderr)
        self.assertFalse(list(self.root.glob("chart.*")))

    def test_notify_reports_interval_deltas(self):
        source = self.write_jsonl([self.notify(100, 10, 2), self.notify(160, 15, 2)])
        output = self.root / "summary.json"
        result = self.cli("notify_report.py", "--input", source, "--output", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        queue = json.loads(output.read_text())["queues"][0]
        self.assertEqual(queue["delta"], {"shm_reads": 5, "poll_calls": 0})
        self.assertTrue(queue["observed_reads_without_poll"])

    def test_notify_rejects_counter_reset(self):
        source = self.write_jsonl([self.notify(100, 10, 2), self.notify(160, 1, 2)])
        output = self.root / "summary.json"
        result = self.cli("notify_report.py", "--input", source, "--output", output)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Counter reset/object reuse", result.stderr)
        self.assertFalse(output.exists())

    def test_notify_rejects_mixed_processes(self):
        source = self.write_jsonl([self.notify(100, 10, 2), self.notify(160, 15, 2, pid=43)])
        output = self.root / "summary.json"
        result = self.cli("notify_report.py", "--input", source, "--output", output)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Expected one process session", result.stderr)
        self.assertFalse(output.exists())

    def test_instrumentation_wrong_hash_preserves_source(self):
        target = self.root / "shm_broadcast.py"
        original = b"# Unrelated version must never be patched.\n"
        target.write_bytes(original)
        output = self.root / "installation"
        result = self.cli(
            "instrument_notify.py", "--target", target, "--output", output,
            "--apply", "--expected-sha256", "0" * 64,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("matching --expected-sha256", result.stderr)
        self.assertEqual(target.read_bytes(), original)
        self.assertFalse(output.exists())
        self.assertFalse((self.root / "_notify_diagnostics.py").exists())


if __name__ == "__main__":
    unittest.main()
