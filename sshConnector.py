"""Connections to the configured monitoring devices."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import paramiko

from rufo_monitor import ConfirmHostKeyPolicy


DEVICE_NAMES = ("Primary", "Secondary", "Tertiary")
KNOWN_HOSTS_PATH = Path.home() / ".ssh" / "rufo_the_spy_known_hosts"


def reset_known_hosts(path=KNOWN_HOSTS_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def _connect_device(name, device, config_path):
    client = paramiko.SSHClient()
    try:
        known_hosts_path = KNOWN_HOSTS_PATH
        try:
            client.load_host_keys(str(known_hosts_path))
        except FileNotFoundError:
            pass
        client.set_missing_host_key_policy(
            ConfirmHostKeyPolicy(known_hosts_path, auto_accept=True)
        )

        auth = {}
        if device["isPasswordRequired"]:
            if not device["password"]:
                raise ValueError(f"A senha de {name} está vazia na configuração.")
            auth["password"] = device["password"]
        if device["isKeyRequired"]:
            key_path = (config_path.parent / device["privateKeyPath"]).resolve()
            if not key_path.is_file():
                raise FileNotFoundError(f"Chave SSH de {name} não encontrada: {key_path}")
            auth["pkey"] = paramiko.PKey.from_path(key_path)

        use_default_keys = not (
            device["isPasswordRequired"] or device["isKeyRequired"]
        )

        client.connect(
            hostname=device["ip"],
            port=device["sshPort"],
            username=device["sshUser"],
            timeout=10,
            banner_timeout=10,
            auth_timeout=10,
            allow_agent=use_default_keys,
            look_for_keys=use_default_keys,
            **auth,
        )
        return client
    except (OSError, ValueError, paramiko.SSHException, KeyboardInterrupt):
        client.close()
        raise


def connect_devices(config, names, config_path):
    """Connect independently and return (connected clients, per-device errors)."""
    connections = {}
    errors = {}
    with ThreadPoolExecutor(max_workers=len(names)) as executor:
        futures = {
            executor.submit(
                _connect_device, name, config[name], config_path
            ): name
            for name in names
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                connections[name] = future.result()
            except (OSError, ValueError, paramiko.SSHException) as error:
                errors[name] = f"{type(error).__name__}: {error}"
    return connections, errors


def disconnect_devices(connections):
    errors = {}
    for name, client in connections.items():
        try:
            client.close()
        except (OSError, paramiko.SSHException) as error:
            errors[name] = str(error)
    return errors
