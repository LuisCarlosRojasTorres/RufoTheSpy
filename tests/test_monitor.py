import csv
import io
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import dataCollector
import main
from dataStorage import SessionStorage


def _process_stat(user_ticks, system_ticks):
    fields = ["0"] * 20
    fields[10] = str(user_ticks)
    fields[11] = str(system_ticks)
    fields[18] = "1"
    return f"123 (worker) S {' '.join(fields)}"


def _remote_output():
    sections = {
        "getTotalCPUComsumption": "%Cpu(s): 2.0 us, 1.0 sy, 97.0 id\nTasks: 5 total",
        "getMemoryConsumption": "Mem: 1000 250 0 0 0 0",
        "getProcessCPUConsumption": (
            "cpu 100 0 0 900 0 0 0 0\n"
            "cpu0 100 0 0 900 0 0 0 0\n"
            f"{_process_stat(10, 1)}\n"
            "__RUFO_SECOND_SAMPLE__\n"
            "cpu 120 0 0 980 0 0 0 0\n"
            "cpu0 120 0 0 980 0 0 0 0\n"
            f"{_process_stat(15, 2)}"
        ),
        "getDiskConsumption": (
            "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
            "/dev/root 1000 250 750 25% /"
        ),
        "getThreadsCount": "42",
        "getKThreadsCount": "3",
        "getProcessPID": "123",
    }
    return "\n".join(
        f"{dataCollector.COMMAND_MARKERS[key]}\n{value}"
        for key, value in sections.items()
    )


class FakeChannel:
    def recv_exit_status(self):
        return 0


class FakeStdout(io.BytesIO):
    channel = FakeChannel()


class FakeSSHClient:
    def __init__(self):
        self.closed = False

    def exec_command(self, command, timeout):
        return None, FakeStdout(_remote_output().encode()), io.BytesIO()

    def close(self):
        self.closed = True


class DataCollectorTests(unittest.TestCase):
    def test_collect_metrics_parses_each_configured_section(self):
        sample = dataCollector.collect_metrics(
            FakeSSHClient(),
            {"customProcess": "worker"},
            {key: "placeholder" for key in dataCollector.COMMAND_MARKERS},
        )
        self.assertEqual(sample["cpu"], "3.0%")
        self.assertEqual(sample["customProcessCpu"], "6.0%")
        self.assertEqual(sample["ram"], "25.0%")
        self.assertEqual(sample["threads"], "42")
        self.assertEqual(sample["kthreads"], "3")
        self.assertEqual(sample["disk"], "25% (/)")
        self.assertEqual(sample["pid"], "123")


class StorageTests(unittest.TestCase):
    def test_session_csv_is_created_and_appended(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = SessionStorage(Path(directory), ["Primary"])
            sample = {
                "cpu": "3.0%",
                "customProcessCpu": "6.0%",
                "ramDetails": "25.0% (250/1000 MB)",
                "tasks": "Tasks: 5 total",
                "threads": "42",
                "kthreads": "3",
                "disk": "25% (/)",
                "pid": "123",
            }
            storage.append("Primary", 1, "2026-11-27 00:00:00", sample)
            with storage.paths["Primary"].open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["custom_process_cpu"], "6.0%")


class DashboardTests(unittest.TestCase):
    def test_dashboard_and_validation_routes(self):
        client = main.app.test_client()
        self.assertEqual(client.get("/").status_code, 200)
        self.assertEqual(client.get("/api/status").json["status"], "idle")
        response = client.post("/api/start", json={"devices": ["Unknown"]})
        self.assertEqual(response.status_code, 400)

    def test_collection_stops_at_duration_and_persists_samples(self):
        config = main.load_config()
        config["timerSeconds"] = 0.02
        config["durationHours"] = 0.0001
        client = FakeSSHClient()
        with tempfile.TemporaryDirectory() as directory:
            session = main.MonitorSession(config, Path(directory) / "config.json")
            with patch.object(
                main.sshConnector,
                "connect_devices",
                return_value=({"Primary": client}, {}),
            ):
                state = session.start(["Primary"])
                deadline = time.monotonic() + 3
                while state["status"] == "running" and time.monotonic() < deadline:
                    time.sleep(0.01)
                    state = session.snapshot()
            self.assertEqual(state["status"], "completed")
            csv_path = Path(directory) / "output" / f"Primary_{state['sessionId']}.csv"
            with csv_path.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertGreaterEqual(len(rows), 1)
            self.assertTrue(client.closed)

    def test_partial_connection_failure_keeps_available_device(self):
        app = main.create_app()
        client = app.test_client()
        state = {
            "status": "running",
            "devices": ["Primary"],
            "history": {"Primary": []},
            "latest": {},
            "errors": {"Secondary": "offline"},
            "sessionId": "261127_000000",
            "timerSeconds": 5,
            "durationHours": 0.25,
            "message": "",
        }
        with patch.object(
            main.sshConnector,
            "connect_devices",
            return_value=({"Primary": FakeSSHClient()}, {"Secondary": "offline"}),
        ), patch("main.SessionStorage") as storage_factory, patch.object(
            main.MonitorSession, "_collect", autospec=True
        ):
            storage_factory.return_value.session_id = "261127_000000"
            response = client.post("/api/start", json={"devices": ["Primary", "Secondary"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["devices"], ["Primary"])
        self.assertEqual(response.json["errors"], {"Secondary": "offline"})


if __name__ == "__main__":
    unittest.main()
