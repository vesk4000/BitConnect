#!/usr/bin/env python3
"""Start 3 Lab3 nodes in parallel with live output prefixing and log files."""

import asyncio
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# Repo root holds the key files, team config and recovered group_id. This
# script lives at src/lab3_blockchain/run_lab3_nodes.py, so the root is two
# levels up. Resolving here lets the runner work from any working directory.
REPO_ROOT = Path(__file__).resolve().parents[2]


class NodeRunner:
    """Run a single Lab3 node and handle its output."""

    def __init__(self, name: str, pem_file: str, port: int, register: bool = False):
        self.name = name
        self.pem_file = pem_file
        self.port = port
        self.register = register
        # Create log filename without spaces, written under the repo root.
        log_name = name.split()[0].lower()  # "VESK (A)" -> "vesk"
        self.log_file = str(REPO_ROOT / f"{log_name}_node.log")
        self.process = None
        self.threads = []

    def start(self):
        """Start the node subprocess."""
        # Clear log file
        Path(self.log_file).unlink(missing_ok=True)

        cmd = [
            "uv",
            "run",
            "lab3-node",
            "--pem",
            str(REPO_ROOT / self.pem_file),
            "--team-config",
            str(REPO_ROOT / "lab2_team.json"),
            "--ipv8-port",
            str(self.port),
        ]
        if self.register:
            # One node registers the blockchain with the Lab 3 server, which
            # triggers the server to join our community and submit its test
            # transaction. group_id is auto-loaded from lab2_group_id.json.
            cmd.append("--register")

        print(f"[{self.name}] Starting node on port {self.port}...")

        self.process = subprocess.Popen(
            cmd,
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,  # line buffered
        )

        # Start thread to read output
        thread = threading.Thread(target=self._read_output, daemon=True)
        thread.start()
        self.threads.append(thread)

    def _read_output(self):
        """Read output from the process and print with prefix."""
        with open(self.log_file, "a", encoding="utf-8") as log_f:
            for line in self.process.stdout:
                line = line.rstrip("\n")
                # Print to console with prefix
                print(f"[{self.name}] {line}")
                # Write to log file
                log_f.write(line + "\n")
                log_f.flush()

    def stop(self):
        """Stop the node subprocess and its whole tree.

        `uv run lab3-node` spawns a child python process, so terminating the uv
        wrapper alone leaves the actual node running (a zombie that keeps its
        UDP port and chain state alive across runs). On Windows we kill the
        entire process tree with taskkill /T; elsewhere we fall back to the
        normal terminate/kill.
        """
        if self.process and self.process.poll() is None:
            print(f"[{self.name}] Stopping...")
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                    capture_output=True,
                )
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print(f"[{self.name}] Force killing...")
                self.process.kill()
                self.process.wait()

    def wait(self):
        """Wait for the process to finish."""
        if self.process:
            self.process.wait()


def main():
    """Start all three nodes and handle cleanup."""
    # Clean up ALL old log files first
    import glob

    for log_file in glob.glob(str(REPO_ROOT / "*_node.log")):
        try:
            Path(log_file).unlink()
        except Exception:
            pass

    nodes = [
        NodeRunner("VESK (A)", "lab1_identity.pem", 5010, register=True),
        NodeRunner("MIRO (B)", "miro_key.pem", 5011),
        NodeRunner("DANIEL (C)", "daniel.pem", 5012),
    ]

    print("\n" + "=" * 80)
    print("Lab3 Blockchain - 3 Node Runner")
    print("=" * 80)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("\nLog files:")
    for node in nodes:
        print(f"  - {node.log_file}")
    print("\nPress Ctrl+C to stop all nodes\n")
    print("=" * 80 + "\n")

    # Optional auto-stop after N seconds (for bounded/agentic test runs).
    duration = None
    if len(sys.argv) > 1:
        try:
            duration = float(sys.argv[1])
        except ValueError:
            duration = None

    try:
        # Start all nodes
        for node in nodes:
            node.start()

        # Give nodes time to start and discover peers
        print("\n" + "=" * 80)
        print("Nodes are starting... Peer discovery can take 30-90 seconds!")
        print("=" * 80)
        print("\nWatch the logs above for consensus to converge.")
        print("Once all nodes reach the same tip_hash and height, they're synced.\n")
        if duration:
            print(f"Auto-stop after {duration:.0f}s.\n")
        print("=" * 80 + "\n")

        if duration:
            time.sleep(duration)
            raise KeyboardInterrupt
        # Wait for all processes (will be interrupted by Ctrl+C)
        for node in nodes:
            node.wait()

    except KeyboardInterrupt:
        print("\n\n" + "=" * 80)
        print("Stopping all nodes...")
        print("=" * 80 + "\n")

        # Stop all nodes in parallel
        for node in nodes:
            node.stop()

        print("\n" + "=" * 80)
        print("All nodes stopped")
        print("=" * 80 + "\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
