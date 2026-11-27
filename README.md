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
For each device, set `isPasswordRequired` and `isKeyRequired` in `config.json`:
both false uses the SSH agent/default key files, password true uses `password`,
and key true uses `privateKeyPath`. If both are true, Paramiko tries the
configured key and password authentication.
The dashboard launcher resets its own `~/.ssh/rufo_the_spy_known_hosts` file at
startup and automatically accepts unknown host keys during that run; it does
not modify the global `known_hosts`. This convenience weakens protection against
a fake SSH server, so use it only on a trusted network.

CSV files and chart images are saved in the `output` directory. A session stops
automatically after `durationHours`; it can also be stopped from the dashboard.