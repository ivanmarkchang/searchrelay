import os
import subprocess
import sys


def test_cli_init_status_and_no_provider_search(tmp_path):
    env = {**os.environ, "SEARCHRELAY_HOME": str(tmp_path)}
    def run(*args):
        return subprocess.run([sys.executable, "-m", "searchrelay.cli", *args],
                              env=env, capture_output=True, text=True, timeout=10)
    assert run("init").returncode == 0
    original = (tmp_path / "config.toml").read_text()
    assert run("init").returncode == 1
    assert (tmp_path / "config.toml").read_text() == original
    assert run("status").returncode == 0
    response = run("search", "test")
    assert response.returncode == 3
    assert '"status": "unavailable"' in response.stdout
    assert run("clear-cache").returncode == 0
