"""Regression suite for the CRAMC advanced monitor."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cramc_advanced as monitor


def sample(**kwargs):
    values = dict(timestamp=100.0, memory_total=1000, memory_used=300,
                  memory_available=700, memory_percent=30.0,
                  disk_total=1000, disk_used=500, disk_percent=50.0)
    values.update(kwargs)
    return monitor.SystemSample(**values)


def process(**kwargs):
    values = dict(pid=77, name="editor", username="tester", status="running",
                  cpu_percent=1.2, memory_rss=4096, memory_percent=0.4,
                  threads=3, created=90.0, executable="/usr/bin/editor")
    values.update(kwargs)
    return monitor.ProcessRecord(**values)


class FormattingTests(unittest.TestCase):
    def test_byte_format_boundaries(self):
        self.assertEqual(monitor.format_bytes(0), "0 B")
        self.assertEqual(monitor.format_bytes(1), "1 B")
        self.assertEqual(monitor.format_bytes(1024), "1.0 KB")
        self.assertEqual(monitor.format_bytes(1024 ** 2), "1.0 MB")
        self.assertEqual(monitor.format_bytes(1024 ** 3), "1.0 GB")

    def test_negative_bytes_are_clamped(self):
        self.assertEqual(monitor.format_bytes(-1), "0 B")

    def test_rate_format(self):
        self.assertEqual(monitor.format_rate(1024), "1.0 KB/s")


class HistoryTests(unittest.TestCase):
    def test_history_is_bounded(self):
        history = monitor.HistoryBuffer(3)
        for stamp in range(5):
            history.add(sample(timestamp=float(stamp), cpu_percent=stamp * 10))
        self.assertEqual(len(history), 3)
        self.assertEqual([item.timestamp for item in history.samples()], [2, 3, 4])

    def test_history_summary(self):
        history = monitor.HistoryBuffer(10)
        for stamp, cpu in enumerate((10, 30, 50, 70)):
            history.add(sample(timestamp=stamp, cpu_percent=cpu))
        summary = history.summary("cpu_percent")
        self.assertEqual(summary["min"], 10)
        self.assertEqual(summary["max"], 70)
        self.assertEqual(summary["average"], 40)
        self.assertEqual(summary["latest"], 70)

    def test_history_rejects_unknown_series(self):
        with self.assertRaises(ValueError):
            monitor.HistoryBuffer().series("cmdline")

    def test_history_rejects_non_sample(self):
        with self.assertRaises(TypeError):
            monitor.HistoryBuffer().add({"cpu_percent": 4})

    def test_history_handles_clock_rollback(self):
        history = monitor.HistoryBuffer()
        history.add(sample(timestamp=20))
        history.add(sample(timestamp=10))
        self.assertEqual(history.samples()[-1].timestamp, 20)

    def test_history_can_be_cleared(self):
        history = monitor.HistoryBuffer()
        history.add(sample())
        history.clear()
        self.assertEqual(len(history), 0)


class HealthTests(unittest.TestCase):
    def codes(self, item):
        return {finding.code for finding in monitor.analyze_health(item)}

    def test_healthy_status(self):
        findings = monitor.analyze_health(sample())
        self.assertEqual([finding.severity for finding in findings], ["ok"])

    def test_memory_warning(self):
        self.assertIn("memory_high", self.codes(sample(memory_percent=88)))

    def test_memory_critical(self):
        self.assertIn("memory_critical", self.codes(sample(memory_percent=96)))

    def test_disk_warning(self):
        self.assertIn("disk_high", self.codes(sample(disk_percent=92)))

    def test_disk_critical(self):
        self.assertIn("disk_critical", self.codes(sample(disk_percent=98)))

    def test_swap_warning(self):
        self.assertIn("swap_high", self.codes(sample(swap_total=500, swap_percent=85)))

    def test_cpu_warning(self):
        self.assertIn("cpu_saturated", self.codes(sample(cpu_percent=98)))

    def test_multiple_findings(self):
        codes = self.codes(sample(memory_percent=99, disk_percent=99,
                                  swap_total=100, swap_percent=90, cpu_percent=99))
        self.assertTrue({"memory_critical", "disk_critical", "swap_high",
                         "cpu_saturated"}.issubset(codes))


class ReportTests(unittest.TestCase):
    def test_json_report_is_parseable_and_private(self):
        report = monitor.build_report(sample(hostname="workstation"), [process()])
        self.assertEqual(report["schema"], "cramc-system-report")
        self.assertFalse(report["privacy"]["command_line_arguments_included"])
        self.assertNotIn("cmdline", report["processes"][0])
        json.dumps(report, allow_nan=False)

    def test_json_export_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "report.json"
            result = monitor.export_report(path, sample(hostname="host-a"), [process()])
            self.assertTrue(result.ok, result.message)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["system"]["hostname"], "host-a")
            self.assertEqual(data["processes"][0]["pid"], 77)

    def test_csv_export(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "processes.csv"
            result = monitor.export_report(path, sample(), [process()])
            self.assertTrue(result.ok, result.message)
            content = path.read_text(encoding="utf-8")
            self.assertIn("pid,name,username", content)
            self.assertIn("editor", content)

    def test_unknown_extension_is_rejected(self):
        result = monitor.export_report("report.exe", sample(), [process()])
        self.assertFalse(result.ok)

    def test_failed_export_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "report.json"
            with mock.patch("json.dump", side_effect=OSError("disk full")):
                result = monitor.export_report(path, sample(), [process()])
            self.assertFalse(result.ok)
            self.assertFalse(path.exists())
            self.assertEqual(list(Path(folder).glob("*.tmp")), [])


class SafetyTests(unittest.TestCase):
    def test_os_processes_are_protected(self):
        for name in ("systemd", "System", "csrss.exe", "kworker/0:1"):
            self.assertTrue(monitor._protected_name(name))

    def test_regular_app_is_not_name_protected(self):
        self.assertFalse(monitor._protected_name("text-editor"))

    def test_pid_one_is_rejected_before_lookup(self):
        fake = mock.Mock()
        with mock.patch.object(monitor, "psutil", fake):
            result = monitor.SystemProbe().terminate_user_process(1)
        self.assertFalse(result.ok)
        fake.Process.assert_not_called()

    def test_current_pid_is_protected(self):
        fake = mock.Mock()
        with mock.patch.object(monitor, "psutil", fake):
            result = monitor.SystemProbe().terminate_user_process(os.getpid())
        self.assertFalse(result.ok)
        fake.Process.assert_not_called()

    def test_invalid_pid_is_rejected(self):
        result = monitor.SystemProbe().terminate_user_process("bad")
        self.assertFalse(result.ok)

    def test_no_psutil_is_handled(self):
        with mock.patch.object(monitor, "psutil", None):
            result = monitor.SystemProbe().terminate_user_process(100)
        self.assertFalse(result.ok)
        self.assertIn("unavailable", result.message)


class ProbeTests(unittest.TestCase):
    def test_probe_degrades_without_psutil(self):
        with mock.patch.object(monitor, "psutil", None):
            item = monitor.SystemProbe().sample()
        self.assertTrue(item.errors)
        self.assertGreaterEqual(item.cpu_count, 0)

    def test_process_list_without_psutil(self):
        with mock.patch.object(monitor, "psutil", None):
            self.assertEqual(monitor.SystemProbe().processes(), [])

    def test_nan_is_normalized_for_json(self):
        item = sample(cpu_percent=float("nan"))
        self.assertIsNone(item.to_dict()["cpu_percent"])
        json.dumps(item.to_dict(), allow_nan=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
