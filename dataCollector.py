"""Collect and normalize monitoring metrics from a connected SSH client."""

import re
import shlex

from rufo_monitor import parse_metrics, parse_process_cpu


COMMAND_MARKERS = {
    "getTotalCPUComsumption": "__RUFO_CPU__",
    "getMemoryConsumption": "__RUFO_MEMORY__",
    "getProcessCPUConsumption": "__RUFO_PROCESS_CPU__",
    "getDiskConsumption": "__RUFO_DISK__",
    "getThreadsCount": "__RUFO_THREADS__",
    "getKThreadsCount": "__RUFO_KTHREADS__",
    "getProcessPID": "__RUFO_PID__",
}
PERCENTAGE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def _build_command(commands, custom_process):
    sections = []
    for key, marker in COMMAND_MARKERS.items():
        command = commands[key].replace(
            "{customProcess}", shlex.quote(custom_process)
        )
        sections.append(f"printf '\\n{marker}\\n' && {command}")
    return " && ".join(sections)


def _parse_sections(output):
    items = list(COMMAND_MARKERS.items())
    markers = [marker for _, marker in items]
    parts = re.split("|".join(re.escape(marker) for marker in markers), output)
    if len(parts) != len(markers) + 1:
        raise RuntimeError("A saída remota não contém todas as seções esperadas.")
    return {
        key: section.strip()
        for (key, _), section in zip(items, parts[1:])
    }


def _first_percentage(value, fallback):
    match = PERCENTAGE.search(value)
    return f"{float(match.group(1)):.1f}%" if match else fallback


def _parse_disk(output):
    lines = [line.split() for line in output.splitlines() if line.strip()]
    for fields in reversed(lines):
        if len(fields) >= 6 and fields[-2].endswith("%"):
            return f"{fields[-2]} ({fields[-1]})"
    return "Não informado por df"


def collect_metrics(client, device_config, commands):
    """Run configured commands together and return one serializable sample."""
    process_name = device_config["customProcess"]
    command = _build_command(commands, process_name)
    _, stdout, stderr = client.exec_command(command, timeout=15)
    output = stdout.read().decode("utf-8", errors="replace")
    error_output = stderr.read().decode("utf-8", errors="replace").strip()
    exit_status = stdout.channel.recv_exit_status()
    if exit_status != 0 or error_output:
        detail = error_output or f"o comando remoto terminou com código {exit_status}"
        raise RuntimeError(f"Falha ao coletar indicadores: {detail}")

    sections = _parse_sections(output)
    thread_output = (
        f"thr: {sections['getThreadsCount']}\n"
        f"kthr: {sections['getKThreadsCount']}"
    )
    metrics = parse_metrics(
        sections["getTotalCPUComsumption"],
        sections["getMemoryConsumption"],
        thread_output,
    )
    process_cpu = parse_process_cpu(
        sections["getProcessCPUConsumption"], process_name
    )
    pid_match = re.search(r"\b\d+\b", sections["getProcessPID"])

    return {
        "cpu": _first_percentage(metrics.cpu, metrics.cpu),
        "customProcessCpu": process_cpu,
        "ram": _first_percentage(metrics.ram, metrics.ram),
        "ramDetails": metrics.ram,
        "tasks": metrics.tasks,
        "threads": metrics.thr,
        "kthreads": metrics.kthr,
        "disk": _parse_disk(sections["getDiskConsumption"]),
        "pid": pid_match.group(0) if pid_match else "Não está em execução",
    }
