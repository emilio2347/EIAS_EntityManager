#!/usr/bin/env python3
"""
EIAS Entity Manager — App Launcher

Double-click this file (or run it) to start the server and open the browser.
No terminal required.
"""

import os
import sys
import time
import signal
import socket
import threading
import webbrowser
import subprocess
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}"


def resolve_python(script_dir: str) -> str:
    """Use the project virtualenv when present so app dependencies are available."""
    root = Path(script_dir)
    candidates = [
        root / ".venv" / "bin" / "python",
        root / "venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def find_free_port(start: int = 8000, end: int = 8100) -> int:
    """Find the first available port in a range."""
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((HOST, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port found between {start} and {end}")


def wait_for_server(port: int, timeout: float = 15.0):
    """Block until the server is accepting connections, or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.connect((HOST, port))
                return True
            except ConnectionRefusedError:
                time.sleep(0.25)
    return False


def main():
    # Resolve paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    python_executable = resolve_python(script_dir)

    # Find a free port
    port = find_free_port(PORT)
    url = f"http://{HOST}:{port}"

    print(f"EIAS Entity Manager")
    print(f"Starting server on {url} ...")
    print(f"Using Python: {python_executable}")
    print(f"Press Ctrl+C to stop.\n")

    # Start uvicorn as a subprocess
    server = subprocess.Popen(
        [
            python_executable, "-m", "uvicorn",
            "app.main:app",
            "--host", HOST,
            "--port", str(port),
            "--log-level", "info",
        ],
        cwd=script_dir,
    )

    # Open the browser once the server is ready
    def open_browser():
        if wait_for_server(port):
            webbrowser.open(url)
        else:
            print("Warning: server did not start within 15 seconds.")

    browser_thread = threading.Thread(target=open_browser, daemon=True)
    browser_thread.start()

    # Wait for the server process and handle clean shutdown
    try:
        server.wait()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.send_signal(signal.SIGTERM)
        server.wait(timeout=5)
        print("Server stopped.")


if __name__ == "__main__":
    main()
