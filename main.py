"""Start the local web UI and coordinate monitoring sessions."""

import copy
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import paramiko
from flask import Flask, jsonify, request

import dataCollector
import dataPlotter
import sshConnector
from dataStorage import SessionStorage


CONFIG_PATH = Path(__file__).with_name("config.json")
DEVICE_NAMES = sshConnector.DEVICE_NAMES
COMMAND_NAMES = tuple(dataCollector.COMMAND_MARKERS)


def load_config(path=CONFIG_PATH):
    with path.open(encoding="utf-8") as config_file:
        config = json.load(config_file)
    if not isinstance(config, dict):
        raise ValueError("A raiz do config.json deve ser um objeto JSON.")
    for key in ("timerSeconds", "durationHours"):
        value = config.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"O campo {key} deve ser um número positivo.")
    for name in DEVICE_NAMES:
        device = config.get(name)
        if not isinstance(device, dict):
            raise ValueError(f"A configuração de {name} deve ser um objeto.")
        for key in ("ip", "customProcess", "sshUser"):
            if not isinstance(device.get(key), str) or not device[key].strip():
                raise ValueError(f"O campo {name}.{key} deve ser um texto não vazio.")
        port = device.get("sshPort")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError(f"O campo {name}.sshPort deve ser uma porta válida.")
        for key in ("isPasswordRequired", "isKeyRequired"):
            if not isinstance(device.get(key), bool):
                raise ValueError(f"O campo {name}.{key} deve ser verdadeiro ou falso.")
        for key in ("password", "privateKeyPath"):
            if not isinstance(device.get(key), str):
                raise ValueError(f"O campo {name}.{key} deve ser um texto.")
        if device["isPasswordRequired"] and not device["password"].strip():
            raise ValueError(f"O campo {name}.password é obrigatório para autenticação por senha.")
        if device["isKeyRequired"] and not device["privateKeyPath"].strip():
            raise ValueError(f"O campo {name}.privateKeyPath é obrigatório para autenticação por chave.")
    commands = config.get("Commands")
    if not isinstance(commands, dict):
        raise ValueError("O campo Commands deve ser um objeto.")
    for key in COMMAND_NAMES:
        if not isinstance(commands.get(key), str) or not commands[key].strip():
            raise ValueError(f"O comando {key} está ausente ou vazio no config.json.")
    return config


class MonitorSession:
    def __init__(self, config, config_path):
        self.config = config
        self.config_path = config_path
        self.output_directory = config_path.parent / "output"
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.storage = None
        self.state = {
            "status": "idle",
            "devices": [],
            "history": {},
            "latest": {},
            "errors": {},
            "sessionId": None,
            "timerSeconds": config["timerSeconds"],
            "durationHours": config["durationHours"],
            "message": "",
            "customProcesses": {
                name: config[name]["customProcess"] for name in DEVICE_NAMES
            },
        }

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def start(self, requested_devices):
        if (
            not isinstance(requested_devices, list)
            or not requested_devices
            or any(name not in DEVICE_NAMES for name in requested_devices)
            or len(set(requested_devices)) != len(requested_devices)
        ):
            raise ValueError("Selecione um ou mais dispositivos válidos.")

        with self.lock:
            if self.state["status"] in ("connecting", "running", "stopping"):
                raise RuntimeError("Já existe uma coleta em andamento.")
            self.stop_event = threading.Event()
            stop_event = self.stop_event
            self.state = {
                "status": "connecting",
                "devices": requested_devices,
                "history": {name: [] for name in requested_devices},
                "latest": {},
                "errors": {},
                "sessionId": None,
                "timerSeconds": self.config["timerSeconds"],
                "durationHours": self.config["durationHours"],
                "message": "",
                "customProcesses": {
                    name: self.config[name]["customProcess"] for name in DEVICE_NAMES
                },
            }

        connections, errors = sshConnector.connect_devices(
            self.config, requested_devices, self.config_path
        )
        if not connections:
            with self.lock:
                self.state["status"] = "error"
                self.state["errors"] = errors
                self.state["message"] = "Não foi possível conectar a nenhum dispositivo."
            return self.snapshot()

        if stop_event.is_set():
            sshConnector.disconnect_devices(connections)
            with self.lock:
                self.state["status"] = "stopped"
                self.state["errors"] = errors
            return self.snapshot()

        try:
            storage = SessionStorage(self.output_directory, connections)
        except OSError:
            sshConnector.disconnect_devices(connections)
            with self.lock:
                self.state["status"] = "error"
                self.state["message"] = "Não foi possível criar os arquivos CSV de saída."
            raise

        with self.lock:
            self.storage = storage
            self.state["status"] = "running"
            self.state["devices"] = list(connections)
            self.state["errors"] = errors
            self.state["sessionId"] = storage.session_id
            self.thread = threading.Thread(
                target=self._collect,
                args=(connections, storage, stop_event),
                name="rufo-monitor",
                daemon=True,
            )
            self.thread.start()
        return self.snapshot()

    def stop(self):
        with self.lock:
            if self.state["status"] not in ("connecting", "running"):
                return self.snapshot()
            self.state["status"] = "stopping"
            self.stop_event.set()
            return copy.deepcopy(self.state)

    def _collect(self, connections, storage, stop_event):
        timer = self.config["timerSeconds"]
        duration = self.config["durationHours"] * 3600
        started = time.monotonic()
        deadline = started + duration
        index = 1
        try:
            while not stop_event.is_set() and time.monotonic() < deadline:
                cycle_started = time.monotonic()
                with ThreadPoolExecutor(max_workers=len(connections)) as executor:
                    futures = {
                        executor.submit(
                            dataCollector.collect_metrics,
                            client,
                            self.config[name],
                            self.config["Commands"],
                        ): name
                        for name, client in connections.items()
                    }
                    for future in as_completed(futures):
                        name = futures[future]
                        try:
                            sample = future.result()
                            timestamp = datetime.now().isoformat(
                                sep=" ", timespec="seconds"
                            )
                            storage.append(name, index, timestamp, sample)
                            sample["time"] = timestamp
                            with self.lock:
                                self.state["history"][name].append(sample)
                                self.state["latest"][name] = sample
                                self.state["errors"].pop(name, None)
                        except (
                            OSError,
                            ValueError,
                            RuntimeError,
                            paramiko.SSHException,
                        ) as error:
                            with self.lock:
                                self.state["errors"][name] = str(error)
                index += 1
                wait_seconds = min(
                    max(0, timer - (time.monotonic() - cycle_started)),
                    max(0, deadline - time.monotonic()),
                )
                if stop_event.wait(wait_seconds):
                    break
        finally:
            disconnect_errors = sshConnector.disconnect_devices(connections)
            with self.lock:
                self.state["errors"].update(
                    {
                        name: f"Falha ao desconectar: {error}"
                        for name, error in disconnect_errors.items()
                    }
                )
                self.state["status"] = "stopped" if stop_event.is_set() else "completed"
                self.state["message"] = (
                    "Coleta encerrada pelo usuário."
                    if stop_event.is_set()
                    else "Duração da coleta concluída."
                )


def create_app(config_path=CONFIG_PATH):
    config_path = Path(config_path).resolve()
    config = load_config(config_path)
    monitor = MonitorSession(config, config_path)
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 7_000_000

    @app.get("/")
    def dashboard():
        return dataPlotter.render_dashboard()

    @app.get("/api/status")
    def status():
        return jsonify(monitor.snapshot())

    @app.post("/api/start")
    def start():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"error": "O corpo da solicitação deve ser um objeto JSON."}), 400
        try:
            state = monitor.start(payload.get("devices"))
        except (ValueError, RuntimeError) as error:
            return jsonify({"error": str(error)}), 400
        except OSError as error:
            return jsonify({"error": str(error)}), 500
        if state["status"] == "error":
            return jsonify({"error": state["message"], "devices": state["errors"]}), 502
        return jsonify(state)

    @app.post("/api/stop")
    def stop():
        return jsonify(monitor.stop())

    @app.post("/api/chart")
    def save_chart():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"error": "O corpo da solicitação deve ser um objeto JSON."}), 400
        state = monitor.snapshot()
        if (
            payload.get("sessionId") != state["sessionId"]
            or payload.get("device") not in state["devices"]
        ):
            return jsonify({"error": "Sessão ou dispositivo inválido."}), 403
        try:
            path = dataPlotter.save_chart_image(
                monitor.output_directory,
                payload["device"],
                payload["sessionId"],
                payload["image"],
            )
        except (KeyError, TypeError, ValueError) as error:
            return jsonify({"error": str(error)}), 400
        except OSError as error:
            return jsonify({"error": f"Não foi possível salvar a imagem: {error}"}), 500
        return jsonify({"saved": path.name})

    return app


app = create_app()


if __name__ == "__main__":
    try:
        sshConnector.reset_known_hosts()
    except OSError as error:
        print(f"Não foi possível limpar o known_hosts do Rufo: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print("Rufo Monitor disponível em http://127.0.0.1:2402")
    app.run(host="127.0.0.1", port=2402, threaded=True, use_reloader=False)
