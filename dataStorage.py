"""CSV output for monitoring sessions."""

import csv
from datetime import datetime, timedelta
from pathlib import Path


CSV_COLUMNS = (
    "index",
    "time",
    "cpu",
    "custom_process_cpu",
    "ram",
    "tasks",
    "thr",
    "kthr",
    "disk",
    "pid",
)


class SessionStorage:
    def __init__(self, output_directory, device_names, started_at=None):
        self.output_directory = Path(output_directory)
        self.output_directory.mkdir(parents=True, exist_ok=True)
        moment = started_at or datetime.now()
        while any(
            (self.output_directory / f"{name}_{moment:%y%m%d_%H%M%S}.csv").exists()
            for name in device_names
        ):
            moment += timedelta(seconds=1)
        self.session_id = moment.strftime("%y%m%d_%H%M%S")
        self.paths = {
            name: self.output_directory / f"{name}_{self.session_id}.csv"
            for name in device_names
        }
        created = []
        try:
            for path in self.paths.values():
                with path.open("x", newline="", encoding="utf-8") as csv_file:
                    created.append(path)
                    csv.writer(csv_file).writerow(CSV_COLUMNS)
        except OSError:
            for path in created:
                path.unlink(missing_ok=True)
            raise

    def append(self, device_name, index, timestamp, sample):
        path = self.paths[device_name]
        with path.open("a", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(
                (
                    index,
                    timestamp,
                    sample["cpu"],
                    sample["customProcessCpu"],
                    sample["ramDetails"],
                    sample["tasks"],
                    sample["threads"],
                    sample["kthreads"],
                    sample["disk"],
                    sample["pid"],
                )
            )
