from unittest.mock import patch

from hv_vm_tools import network


def test_tcp_open_refuses(monkeypatch):
    def boom(*_a, **_k):
        raise OSError("nope")

    monkeypatch.setattr(network.socket, "create_connection", boom)
    assert network.tcp_open("127.0.0.1", 9, timeout=0.1) is False


@patch("hv_vm_tools.network.subprocess.run")
def test_ping_host_success(mock_run):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "line1\nReply from 1.1.1.1: bytes=32 time=1ms TTL=55"
    mock_run.return_value.stderr = ""
    r = network.ping_host("1.1.1.1", count=1)
    assert r.ok is True
    assert "Reply" in r.detail or "line1" in r.detail
