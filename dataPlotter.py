"""Web dashboard and chart-image output."""

import base64
import binascii
import re
from pathlib import Path


DEVICE_NAMES = ("Primary", "Secondary", "Tertiary")
IMAGE_DATA = re.compile(r"^data:image/png;base64,([A-Za-z0-9+/=]+)$")


def render_dashboard():
    cards = []
    for name in DEVICE_NAMES:
        cards.append(
            f"""
            <section class="device" data-device="{name}">
              <h2>{name}</h2>
              <p class="device-status" id="status-{name}">Aguardando</p>
              <h3>CPU usage</h3>
              <canvas id="cpu-{name}" aria-label="{name}: CPU total e processo"></canvas>
              <h3>Memory usage</h3>
              <canvas id="ram-{name}" aria-label="{name}: uso de memória"></canvas>
              <div class="labels">
                <span>Threads: <b id="threads-{name}">--</b></span>
                <span>Kthreads: <b id="kthreads-{name}">--</b></span>
                <span>Disk: <b id="disk-{name}">--</b></span>
                <span>Process PID: <b id="pid-{name}">--</b></span>
              </div>
            </section>"""
        )
    return """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Rufo Monitor</title>
  <style>
    :root { color-scheme: light; font-family: system-ui, sans-serif; color: #172033; }
    body { margin: 0; background: #f3f5f8; }
    header { padding: 1.25rem 2rem; background: #172033; color: white; }
    header h1 { margin: 0 0 .25rem; font-size: 1.5rem; }
    main { padding: 1.25rem; }
    .controls { display: flex; flex-wrap: wrap; align-items: center; gap: 1rem; padding: 1rem; background: white; border-radius: .6rem; }
    button { border: 0; border-radius: .4rem; padding: .65rem 1rem; color: white; background: #1769aa; font: inherit; cursor: pointer; }
    button.secondary { background: #555f70; }
    button:disabled { opacity: .5; cursor: not-allowed; }
    #message { min-height: 1.5rem; color: #a12c2c; }
    .devices { display: grid; grid-template-columns: repeat(3, minmax(270px, 1fr)); gap: 1rem; margin-top: 1rem; }
    .device { min-width: 0; padding: 1rem; background: white; border-radius: .6rem; box-shadow: 0 1px 5px #17203312; }
    .device h2 { margin: 0; }
    .device h3 { margin: 1.1rem 0 .25rem; font-size: 1rem; }
    .device-status { margin: .2rem 0; color: #536176; }
    canvas { width: 100%; height: 170px; }
    .labels { display: grid; grid-template-columns: 1fr 1fr; gap: .55rem; margin-top: 1rem; font-size: .9rem; }
    .labels span { overflow-wrap: anywhere; }
    @media (max-width: 1050px) { .devices { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <header><h1>Rufo Monitor</h1><div>Monitoramento remoto de dispositivos</div></header>
  <main>
    <div class="controls">
      <strong>Dispositivos:</strong>
      <label><input type="checkbox" name="device" value="Primary"> Primary</label>
      <label><input type="checkbox" name="device" value="Secondary"> Secondary</label>
      <label><input type="checkbox" name="device" value="Tertiary"> Tertiary</label>
      <button id="start">Iniciar coleta</button>
      <button class="secondary" id="stop" disabled>Parar coleta</button>
      <span id="session"></span>
    </div>
    <p id="message" role="status"></p>
    <div class="devices">""" + "".join(cards) + """</div>
  </main>
  <script>
    const names = ["Primary", "Secondary", "Tertiary"];
    const series = Object.fromEntries(names.map(name => [name, []]));
    let activeDevices = [];
    let savedSession = null;
    let lastStatus = "idle";

    function number(value) {
      const match = String(value ?? "").match(/[0-9]+(?:\\.[0-9]+)?/);
      return match ? Number(match[0]) : null;
    }

    function draw(canvas, samples, firstKey, secondKey = null, secondLabel = "Processo") {
      const rect = canvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, rect.width * ratio);
      canvas.height = Math.max(1, rect.height * ratio);
      const ctx = canvas.getContext("2d");
      ctx.scale(ratio, ratio);
      const width = rect.width, height = rect.height;
      const pad = { left: 36, right: 10, top: 12, bottom: 24 };
      const values = samples.flatMap(s => [number(s[firstKey]), secondKey ? number(s[secondKey]) : null]).filter(v => v !== null);
      const ceiling = Math.max(100, Math.ceil(Math.max(...values, 1) / 10) * 10);
      ctx.clearRect(0, 0, width, height);
      ctx.font = "11px system-ui";
      ctx.strokeStyle = "#d9dee7";
      ctx.fillStyle = "#536176";
      for (let i = 0; i <= 4; i++) {
        const y = pad.top + (height - pad.top - pad.bottom) * i / 4;
        ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke();
        ctx.fillText(`${Math.round(ceiling * (4 - i) / 4)}%`, 0, y + 4);
      }
      const colors = ["#1769aa", "#d27a16"];
      [firstKey, secondKey].filter(Boolean).forEach((key, seriesIndex) => {
        ctx.beginPath(); ctx.strokeStyle = colors[seriesIndex]; ctx.lineWidth = 2;
        let started = false;
        samples.forEach((sample, index) => {
          const value = number(sample[key]);
          if (value === null) { started = false; return; }
          const x = pad.left + (width - pad.left - pad.right) * (samples.length < 2 ? .5 : index / (samples.length - 1));
          const y = pad.top + (height - pad.top - pad.bottom) * (1 - value / ceiling);
          if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
        });
        ctx.stroke();
      });
      ctx.fillStyle = colors[0]; ctx.fillText(firstKey === "cpu" ? "Total" : "RAM", pad.left, height - 5);
      if (secondKey) { ctx.fillStyle = colors[1]; ctx.fillText(secondLabel, pad.left + 50, height - 5); }
    }

    function updateCards(status) {
      activeDevices = status.devices || [];
      names.forEach(name => {
        const samples = status.history?.[name] || [];
        series[name] = samples;
        document.getElementById(`status-${name}`).textContent =
          status.errors?.[name] || (activeDevices.includes(name) ? status.status : "Não selecionado");
        const latest = samples.at(-1);
        for (const key of ["threads", "kthreads", "disk", "pid"]) {
          document.getElementById(`${key}-${name}`).textContent = latest?.[key] ?? "--";
        }
        if (latest) {
          document.getElementById(`status-${name}`).textContent =
            status.errors?.[name] || (activeDevices.includes(name) ? status.status : "Não selecionado");
        }
        draw(
          document.getElementById(`cpu-${name}`), samples, "cpu", "customProcessCpu",
          status.customProcesses?.[name] || "Processo"
        );
        draw(document.getElementById(`ram-${name}`), samples, "ram");
      });
      document.getElementById("start").disabled =
        ["connecting", "running", "stopping"].includes(status.status);
      document.getElementById("stop").disabled =
        !["connecting", "running"].includes(status.status);
      document.getElementById("session").textContent =
        status.sessionId ? `Sessão ${status.sessionId}` : "";
      if (status.status === "error") {
        document.getElementById("message").textContent = status.message || "Falha ao iniciar a coleta.";
      } else if (status.status === "running") {
        document.getElementById("message").textContent =
          `Coletando a cada ${status.timerSeconds}s; encerramento automático ao fim de ${status.durationHours}h.`;
      } else if (status.status === "completed" || status.status === "stopped") {
        document.getElementById("message").textContent =
          status.status === "completed" ? "Duração concluída." : "Coleta encerrada.";
      }
      if (["completed", "stopped"].includes(status.status) &&
          ["running", "stopping"].includes(lastStatus) && savedSession !== status.sessionId) {
        savedSession = status.sessionId;
        saveCharts(status.sessionId);
      }
      lastStatus = status.status;
    }

    async function poll() {
      try {
        const response = await fetch("/api/status");
        updateCards(await response.json());
      } catch (error) {
        document.getElementById("message").textContent = `Erro de comunicação: ${error}`;
      }
    }

    async function saveCharts(sessionId) {
      for (const name of activeDevices) {
        const cpu = document.getElementById(`cpu-${name}`);
        const ram = document.getElementById(`ram-${name}`);
        const image = document.createElement("canvas");
        image.width = Math.max(cpu.width, ram.width);
        image.height = cpu.height + ram.height;
        const context = image.getContext("2d");
        context.fillStyle = "white"; context.fillRect(0, 0, image.width, image.height);
        context.drawImage(cpu, 0, 0, image.width, cpu.height);
        context.drawImage(ram, 0, cpu.height, image.width, ram.height);
        try {
          const response = await fetch("/api/chart", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ device: name, sessionId, image: image.toDataURL("image/png") })
          });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
        } catch (error) {
          document.getElementById("message").textContent = `Não foi possível salvar gráfico de ${name}: ${error}`;
        }
      }
    }

    document.getElementById("start").addEventListener("click", async () => {
      const devices = [...document.querySelectorAll('input[name="device"]:checked')].map(el => el.value);
      document.getElementById("message").textContent = "";
      try {
        const response = await fetch("/api/start", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ devices })
        });
        const result = await response.json();
        if (!response.ok) document.getElementById("message").textContent = result.error;
        else { activeDevices = result.devices; savedSession = null; }
        await poll();
      } catch (error) {
        document.getElementById("message").textContent = `Falha ao iniciar: ${error}`;
      }
    });
    document.getElementById("stop").addEventListener("click", async () => {
      await fetch("/api/stop", { method: "POST" });
      await poll();
    });
    window.addEventListener("resize", poll);
    poll();
    setInterval(poll, 1000);
  </script>
</body>
</html>"""


def save_chart_image(output_directory, device, session_id, data_url):
    if device not in DEVICE_NAMES or not re.fullmatch(r"\d{6}_\d{6}", session_id):
        raise ValueError("Dispositivo ou identificador de sessão inválido.")
    match = IMAGE_DATA.fullmatch(data_url)
    if not match:
        raise ValueError("A imagem do gráfico não está em formato PNG válido.")
    try:
        image = base64.b64decode(match.group(1), validate=True)
    except binascii.Error as error:
        raise ValueError("A imagem do gráfico não está em base64 válido.") from error
    if not image.startswith(b"\x89PNG\r\n\x1a\n") or len(image) > 5_000_000:
        raise ValueError("A imagem PNG está inválida ou excede 5 MB.")
    path = Path(output_directory) / f"{device}_{session_id}.png"
    Path(output_directory).mkdir(parents=True, exist_ok=True)
    path.write_bytes(image)
    return path
