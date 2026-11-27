import csv
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import dataCollector
import main
import sshConnector
from rufo_monitor import ConfirmHostKeyPolicy
from sshConnector import reset_known_hosts
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

    def test_rufo_host_keys_reset_without_touching_global_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rufo_known_hosts"
            path.write_text("old key\n", encoding="utf-8")
            reset_known_hosts(path)
            self.assertEqual(path.read_text(encoding="utf-8"), "")

    def test_host_key_policy_auto_accepts_without_prompt(self):
        class FakeKey:
            def asbytes(self):
                return b"fake ssh key"

            def get_name(self):
                return "ssh-ed25519"

            def get_base64(self):
                return "ZmFrZS1zc2gta2V5"

        class FakeHostKeys:
            def add(self, hostname, key_type, key):
                self.entry = (hostname, key_type, key)

        class FakeClient:
            def __init__(self):
                self.host_keys = FakeHostKeys()

            def get_host_keys(self):
                return self.host_keys

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rufo_known_hosts"
            client = FakeClient()
            policy = ConfirmHostKeyPolicy(path, auto_accept=True)
            with patch("builtins.input", side_effect=AssertionError("unexpected prompt")):
                policy.missing_host_key(client, "test-device", FakeKey())
            self.assertIn("test-device ssh-ed25519", path.read_text(encoding="utf-8"))
            self.assertEqual(client.host_keys.entry[0], "test-device")


class SSHAuthenticationTests(unittest.TestCase):
    class FakeSSHClient:
        def load_host_keys(self, path):
            pass

        def set_missing_host_key_policy(self, policy):
            self.policy = policy

        def connect(self, **kwargs):
            self.options = kwargs

        def close(self):
            pass

    def test_config_accepts_each_authentication_mode(self):
        config = main.load_config()
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            for password_required, key_required in (
                (False, False),
                (True, False),
                (False, True),
                (True, True),
            ):
                with self.subTest(
                    password=password_required, key=key_required
                ):
                    config["Primary"]["isPasswordRequired"] = password_required
                    config["Primary"]["isKeyRequired"] = key_required
                    config["Primary"]["password"] = "secret" if password_required else ""
                    config["Primary"]["privateKeyPath"] = (
                        "private.pem" if key_required else ""
                    )
                    config_path.write_text(json.dumps(config), encoding="utf-8")
                    main.load_config(config_path)

    def test_connector_uses_only_configured_authentication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            known_hosts_path = root / "known_hosts"
            known_hosts_path.write_text("", encoding="utf-8")
            key_path = root / "private.pem"
            key_path.write_text("test key", encoding="utf-8")
            config_path = root / "config.json"
            fake_pkey = object()

            modes = (
                (
                    {"isPasswordRequired": False, "isKeyRequired": False},
                    {"allow_agent": True, "look_for_keys": True},
                ),
                (
                    {
                        "isPasswordRequired": True,
                        "isKeyRequired": False,
                        "password": "secret",
                    },
                    {
                        "allow_agent": False,
                        "look_for_keys": False,
                        "password": "secret",
                    },
                ),
                (
                    {
                        "isPasswordRequired": False,
                        "isKeyRequired": True,
                        "privateKeyPath": "private.pem",
                    },
                    {
                        "allow_agent": False,
                        "look_for_keys": False,
                        "pkey": fake_pkey,
                    },
                ),
                (
                    {
                        "isPasswordRequired": True,
                        "isKeyRequired": True,
                        "password": "secret",
                        "privateKeyPath": "private.pem",
                    },
                    {
                        "allow_agent": False,
                        "look_for_keys": False,
                        "password": "secret",
                        "pkey": fake_pkey,
                    },
                ),
            )
            for auth_config, expected in modes:
                device = {
                    "ip": "192.0.2.1",
                    "sshPort": 22,
                    "sshUser": "tester",
                    "password": "",
                    "privateKeyPath": "",
                    "isPasswordRequired": False,
                    "isKeyRequired": False,
                    **auth_config,
                }
                fake_client = self.FakeSSHClient()
                with self.subTest(auth=auth_config):
                    with patch.object(
                        sshConnector, "KNOWN_HOSTS_PATH", known_hosts_path
                    ), patch.object(
                        sshConnector.paramiko, "SSHClient", return_value=fake_client
                    ), patch.object(
                        sshConnector.paramiko.PKey, "from_path", return_value=fake_pkey
                    ) as load_key:
                        sshConnector._connect_device("Primary", device, config_path)
                if auth_config["isKeyRequired"]:
                    load_key.assert_called_once_with(key_path)
                for key, value in expected.items():
                    self.assertEqual(fake_client.options[key], value)
                if "password" not in expected:
                    self.assertNotIn("password", fake_client.options)
                if "pkey" not in expected:
                    self.assertNotIn("pkey", fake_client.options)


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
