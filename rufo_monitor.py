import base64
import csv
import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

import paramiko


CONFIG_PATH = Path(__file__).with_name("RufoConfig.json")
CSV_DIRECTORY = Path(__file__).parent
CSV_COLUMNS = ("index", "time", "cpu", "ram", "tasks", "thr", "kthr", "custom_process_cpu")
CSV_PREFIXES = {"IHM primaria": "Primary", "IHM secundaria": "Secondary"}
REMOTE_COMMAND = (
    "LC_ALL=C top -b -n1 && "
    "printf '\\n__RUFO_MEMORY__\\n' && "
    "LC_ALL=C free -m && "
    "printf '\\n__RUFO_THREADS__\\n' && "
    """LC_ALL=C awk '
    {
        sub(/^.*\\) /, "")
        if (NF < 18 || $7 !~ /^[0-9]+$/ || $18 !~ /^[0-9]+$/ || $18 < 1) {
            invalid = 1
            next
        }
        processes++
        # PF_KTHREAD is bit 21 in /proc/PID/stat flags.
        if (int($7 / 2097152) % 2 == 1)
            kernel += $18
        else
            user += $18 - 1
    }
    END {
        if (invalid || processes == 0)
            exit 1
        printf "thr: %.0f\\nkthr: %.0f\\n", user, kernel
    }' /proc/[0-9]*/stat"""
)
PROCESS_COMMAND = (
    "LC_ALL=C awk '/^cpu/ {print}' /proc/stat && cat /proc/[0-9]*/stat && "
    "sleep 1 && printf '\\n__RUFO_SECOND_SAMPLE__\\n' && "
    "LC_ALL=C awk '/^cpu/ {print}' /proc/stat && cat /proc/[0-9]*/stat"
)


@dataclass(frozen=True)
class Metrics:
    cpu: str
    ram: str
    tasks: str
    thr: str
    kthr: str
    custom_process_cpu: str = "Não configurado"


def load_config(path=CONFIG_PATH):
    with path.open(encoding="utf-8") as config_file:
        config = json.load(config_file)
    if not isinstance(config, dict):
        raise ValueError("A raiz do RufoConfig.json deve ser um objeto JSON.")

    required = (
        "sshIpPrimary",
        "sshIpSecondary",
        "sshPort",
        "sshUser",
        "sshPrivateKeyPath",
        "timerSeconds",
        "custom_process",
    )
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError(f"Campos ausentes no RufoConfig.json: {', '.join(missing)}")

    for key in ("sshIpPrimary", "sshIpSecondary", "sshUser", "sshPrivateKeyPath", "custom_process"):
        if not isinstance(config[key], str) or not config[key].strip():
            raise ValueError(f"O campo {key} deve ser um texto não vazio.")

    for key in ("sshPort", "timerSeconds"):
        if isinstance(config[key], bool) or not isinstance(config[key], int) or config[key] < 1:
            raise ValueError(f"O campo {key} deve ser um inteiro positivo.")

    config["sshPrivateKeyPath"] = str(
        (path.parent / config["sshPrivateKeyPath"]).resolve()
    )
    return config


def _find_line(lines, pattern):
    for line in lines:
        if re.match(pattern, line.strip(), re.IGNORECASE):
            return line.strip()
    return "Não informado pelo top"


def parse_metrics(top_output, memory_output, thread_output=None):
    top_lines = top_output.splitlines()

    cpu_line = _find_line(top_lines, r"%?cpu(?:\(s\))?:")
    idle_match = re.search(r"(\d+(?:\.\d+)?)\s*%?\s*id(?:le)?\b", cpu_line, re.IGNORECASE)
    if idle_match:
        cpu = f"{100 - float(idle_match.group(1)):.1f}%"
    elif cpu_line != "Não informado pelo top":
        cpu = cpu_line
    else:
        cpu = "Não informado pelo top"

    memory_match = re.search(r"^Mem:\s+(\d+)\s+(\d+)", memory_output, re.MULTILINE)
    if memory_match:
        total, used = (int(value) for value in memory_match.groups())
        ram = f"{used / total * 100:.1f}% ({used}/{total} MB)" if total else "0.0%"
    else:
        ram = "Não informado por free"

    if thread_output is None:
        thr = _find_line(top_lines, r"(?:thr|threads?):")
        kthr = _find_line(top_lines, r"kthr:")
    else:
        thread_match = re.fullmatch(r"thr: (\d+)\nkthr: (\d+)\s*", thread_output.strip())
        if not thread_match:
            raise RuntimeError("Contagens de threads ausentes ou inválidas na saída remota.")
        thr, kthr = thread_match.groups()

    return Metrics(
        cpu=cpu,
        ram=ram,
        tasks=_find_line(top_lines, r"tasks?:"),
        thr=thr,
        kthr=kthr,
    )


class ConfirmHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    def __init__(self, known_hosts_path):
        self.known_hosts_path = known_hosts_path

    def missing_host_key(self, client, hostname, key):
        fingerprint = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode("ascii").rstrip("=")
        print(f"Chave SSH desconhecida para {hostname} ({key.get_name()}).")
        print(f"Impressão digital: SHA256:{fingerprint}")
        print("Confirme a impressão digital por um canal confiável antes de aceitar.")
        try:
            answer = input("Confiar nesta chave e salvá-la em known_hosts? Digite sim: ")
        except EOFError as error:
            raise paramiko.SSHException("Confirmação da chave SSH indisponível.") from error
        if answer.strip().lower() != "sim":
            raise paramiko.SSHException(f"Chave SSH de {hostname} não foi aceita.")

        if any(character.isspace() for character in hostname):
            raise paramiko.SSHException("Nome de host inválido para known_hosts.")
        self.known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
        entry = f"{hostname} {key.get_name()} {key.get_base64()}\n".encode("utf-8")
        with self.known_hosts_path.open("a+b") as host_file:
            host_file.seek(0, 2)
            if host_file.tell():
                host_file.seek(-1, 2)
                if host_file.read(1) != b"\n":
                    entry = b"\n" + entry
            host_file.write(entry)
        client.get_host_keys().add(hostname, key.get_name(), key)
        print(f"Chave SSH salva em {self.known_hosts_path}.")


def connect(host, config):
    client = paramiko.SSHClient()
    try:
        known_hosts_path = Path.home() / ".ssh" / "known_hosts"
        client.load_system_host_keys()
        try:
            client.load_host_keys(str(known_hosts_path))
        except FileNotFoundError:
            pass
        client.set_missing_host_key_policy(ConfirmHostKeyPolicy(known_hosts_path))
        client.connect(
            hostname=host,
            port=config["sshPort"],
            username=config["sshUser"],
            key_filename=config["sshPrivateKeyPath"],
            timeout=10,
            banner_timeout=10,
            auth_timeout=10,
            allow_agent=False,
            look_for_keys=False,
        )
    except (OSError, ValueError, paramiko.SSHException, KeyboardInterrupt):
        client.close()
        raise
    return client


def parse_process_cpu(output: str, process_name: str) -> str:
    try:
        first, separator, second = output.partition("__RUFO_SECOND_SAMPLE__")
        if not separator:
            raise ValueError("segunda amostra ausente")
        def parse_sample(sample: str) -> tuple[int, int, dict[tuple[int, int], int]]:
            lines = sample.strip().splitlines()
            total_ticks = None
            cores = set()
            processes = {}
            for line in lines:
                if line.startswith("cpu"):
                    counters = line.split()
                    if len(counters) < 5:
                        raise ValueError("contadores de CPU incompletos")
                    values = [int(value) for value in counters[1:]]
                    if any(value < 0 for value in values):
                        raise ValueError("contadores de CPU negativos")
                    if counters[0] == "cpu":
                        # guest and guest_nice are already included in user and nice.
                        total_ticks = sum(values[:8])
                    elif re.fullmatch(r"cpu\d+", counters[0]):
                        cores.add(counters[0])
                    else:
                        raise ValueError("identificador de CPU inválido")
                    continue
                match = re.fullmatch(r"(\d+) \((.*)\) (.*)", line)
                if match is None:
                    raise ValueError("registro de processo inválido")
                pid, name, stat = match.groups()
                fields = stat.split()
                if len(fields) < 20:
                    raise ValueError("registro de processo incompleto")
                if name == process_name:
                    identity = (int(pid), int(fields[19]))
                    processes[identity] = int(fields[11]) + int(fields[12])
            if total_ticks is None or not cores:
                raise ValueError("contadores de CPU ou núcleos ausentes")
            return total_ticks, len(cores), processes

        first_total, first_cores, before = parse_sample(first)
        second_total, second_cores, after = parse_sample(second)
        elapsed_ticks = second_total - first_total
        if elapsed_ticks <= 0:
            raise ValueError("intervalo de contadores de CPU inválido")
        if first_cores != second_cores:
            raise ValueError("quantidade de núcleos mudou durante a coleta")
        if not after:
            return "Não está em execução"
        if any(identity not in before for identity in after):
            return "Amostra indisponível: processo iniciado durante a coleta"
        delta = sum(ticks - before[identity] for identity, ticks in after.items())
        if any(ticks < before[identity] for identity, ticks in after.items()):
            raise ValueError("contadores de CPU regressivos")
        return f"{delta / elapsed_ticks * second_cores * 100:.1f}%"
    except (ValueError, IndexError) as error:
        raise RuntimeError(f"Falha ao calcular CPU de {process_name}: {error}") from error


def collect_metrics(client, custom_process=None):
    command = REMOTE_COMMAND
    if custom_process is not None:
        command += " && printf '\\n__RUFO_PROCESS__\\n' && " + PROCESS_COMMAND
    _, stdout, stderr = client.exec_command(command, timeout=10)
    output = stdout.read().decode("utf-8", errors="replace")
    error_output = stderr.read().decode("utf-8", errors="replace").strip()
    exit_status = stdout.channel.recv_exit_status()

    if exit_status != 0 or error_output:
        detail = error_output or f"o comando remoto terminou com código {exit_status}"
        raise RuntimeError(f"Falha ao coletar indicadores: {detail}")

    top_output, separator, memory_output = output.partition("__RUFO_MEMORY__")
    if not separator:
        raise RuntimeError("A saída remota não contém os dados de memória esperados.")
    memory_output, separator, thread_output = memory_output.partition("__RUFO_THREADS__")
    if not separator:
        raise RuntimeError("A saída remota não contém as contagens de threads esperadas.")
    thread_output, process_separator, process_output = thread_output.partition("__RUFO_PROCESS__")
    metrics = parse_metrics(top_output, memory_output, thread_output)
    if custom_process is None:
        return metrics
    if not process_separator:
        raise RuntimeError("A saída remota não contém as amostras do processo.")
    return replace(
        metrics,
        custom_process_cpu=parse_process_cpu(process_output.strip(), custom_process),
    )


def display_snapshot(connections, custom_process=None):
    with ThreadPoolExecutor(max_workers=len(connections)) as executor:
        pending = {
            executor.submit(collect_metrics, client, custom_process): name
            for name, client in connections.items()
        }
        results = {}
        for future in as_completed(pending):
            name = pending[future]
            try:
                results[name] = future.result()
            except (OSError, paramiko.SSHException, RuntimeError) as error:
                print(
                    f"Falha na coleta de {name}: {error}. "
                    "Nova tentativa após o intervalo configurado.",
                    file=sys.stderr,
                )

    print(f"\n--- Indicadores | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
    for name, metrics in results.items():
        print(f"\n{name}")
        print(f"  CPU:   {metrics.cpu}")
        print(f"  RAM:   {metrics.ram}")
        print(f"  Tasks: {metrics.tasks}")
        print(f"  thr:   {metrics.thr}")
        print(f"  kthr:  {metrics.kthr}")
        if custom_process is not None:
            print(f"  CPU de {custom_process}: {metrics.custom_process_cpu}")
    return results


def monitor(connections, timer_seconds, custom_process=None):
    try:
        with ExitStack() as stack:
            started_at = datetime.now().strftime("%y%m%d_%H%M%S")
            logs = {}
            for name in connections:
                path = CSV_DIRECTORY / f"{CSV_PREFIXES[name]}_{started_at}.csv"
                stream = stack.enter_context(path.open("x", newline="", encoding="utf-8"))
                writer = csv.writer(stream)
                writer.writerow(CSV_COLUMNS)
                stream.flush()
                logs[name] = (writer, stream)
                print(f"CSV de {name}: {path}")

            index = 1
            while True:
                results = display_snapshot(connections, custom_process)
                timestamp = datetime.now().isoformat(sep=" ", timespec="seconds")
                for name, metrics in results.items():
                    writer, stream = logs[name]
                    writer.writerow((
                        index, timestamp, metrics.cpu, metrics.ram,
                        metrics.tasks, metrics.thr, metrics.kthr, metrics.custom_process_cpu,
                    ))
                    stream.flush()
                index += 1
                time.sleep(timer_seconds)
    except KeyboardInterrupt:
        print("\nMonitoramento interrompido.")


def main():
    try:
        config = load_config()
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Erro na configuração: {error}", file=sys.stderr)
        return 1

    options = {
        "1": ("IHM primaria", [("IHM primaria", config["sshIpPrimary"])]),
        "2": ("IHM secundaria", [("IHM secundaria", config["sshIpSecondary"])]),
        "3": (
            "IHM primaria e secundaria",
            [
                ("IHM primaria", config["sshIpPrimary"]),
                ("IHM secundaria", config["sshIpSecondary"]),
            ],
        ),
    }

    while True:
        print("\n=== Rufo Monitor ===")
        print("1. Conectar à IHM primaria")
        print("2. Conectar à IHM secundaria")
        print("3. Conectar às duas IHMs")
        print("0. Sair")
        choice = input("Selecione uma opção: ").strip()

        if choice == "0":
            return 0
        if choice not in options:
            print("Opção inválida.")
            continue

        description, targets = options[choice]
        connections = {}
        try:
            for name, host in targets:
                print(f"Conectando à {name} ({host})...")
                connections[name] = connect(host, config)
            print(
                f"Conectado. Atualização a cada {config['timerSeconds']} segundos. "
                "Pressione Ctrl+C para voltar ao menu."
            )
            monitor(connections, config["timerSeconds"], config["custom_process"])
        except (OSError, paramiko.SSHException, RuntimeError) as error:
            print(f"Falha na conexão/monitoramento de {description}: {error}", file=sys.stderr)
        finally:
            for client in connections.values():
                client.close()


if __name__ == "__main__":
    raise SystemExit(main())
