import re
import socket
import sys

import pytest
from typer.testing import CliRunner

from pptkit.cli.app import app
from pptkit.gui.server import find_available_port


def test_find_available_port_direct() -> None:
    # Ephemeral free check
    port = find_available_port(host="127.0.0.1", start_port=18900)
    assert port == 18900


def test_find_available_port_increments_when_busy() -> None:
    # Occupy port 18901
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform != "win32":
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    elif hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    s.bind(("127.0.0.1", 18901))
    s.listen(1)

    try:
        port = find_available_port(host="127.0.0.1", start_port=18901, max_tries=5)
        assert port == 18902
    finally:
        s.close()


def test_find_available_port_exhaustion_raises() -> None:
    # Occupy ports
    sockets = []
    base_port = 18910
    max_tries = 3
    try:
        for i in range(max_tries):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if sys.platform != "win32":
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            elif hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            s.bind(("127.0.0.1", base_port + i))
            s.listen(1)
            sockets.append(s)

        with pytest.raises(RuntimeError, match="No available port"):
            find_available_port(host="127.0.0.1", start_port=base_port, max_tries=max_tries)
    finally:
        for s in sockets:
            s.close()


def test_cli_gui_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["gui", "--help"], color=False)
    assert result.exit_code == 0
    clean_output = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    assert "--port" in clean_output
    assert "--host" in clean_output
    assert "--no-browser" in clean_output
