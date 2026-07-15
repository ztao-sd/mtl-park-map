"""Run the FastAPI backend and the Vite frontend together.

    uv run python dev.py

Ctrl+C stops both.
"""

import os
import subprocess
import sys
import time

IS_WIN = os.name == "nt"

BACKEND = [
    sys.executable, "-m", "uvicorn", "mtl_park_map.main:app",
    "--host", "127.0.0.1", "--port", "8000",
]
FRONTEND = "npm --prefix frontend run dev"


def _kill(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if IS_WIN:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
    else:
        proc.terminate()


def main() -> None:
    procs = [
        subprocess.Popen(BACKEND),
        subprocess.Popen(FRONTEND, shell=True),
    ]
    print("backend  -> http://localhost:8000  (docs at /docs)")
    print("frontend -> http://localhost:5173")
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            _kill(p)


if __name__ == "__main__":
    main()
