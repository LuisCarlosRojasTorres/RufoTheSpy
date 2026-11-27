# RufoTheSpy

## Others

### Windows
```
python -m venv todoEnv
.\todoEnv\Scripts\Activate.ps1
```

### Linux
```
python3 -m venv todoEnv
$ source todoEnv/bin/activate
```

## Rufo Monitor

Install the Python dependencies and start the local dashboard:

```powershell
python -m pip install -r requirements.txt
python main.py
```

Open `http://127.0.0.1:2402`, select the devices, and start a monitoring session.
The SSH addresses, credentials, collection interval, duration, and remote commands
are configured in `config.json`. The sample configuration uses private-key
authentication; set each device's authentication fields to match your setup.
When a server's SSH host key is unknown, verify its fingerprint in a trusted
channel before accepting it in the terminal.

CSV files and chart images are saved in the `output` directory. A session stops
automatically after `durationHours`; it can also be stopped from the dashboard.