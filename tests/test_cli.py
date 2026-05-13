import pytest

from hv_vm_tools.cli import main


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "0.1.0" in out


def test_cli_ping_missing_subcommand():
    with pytest.raises(SystemExit) as e:
        main([])
    assert e.value.code != 0
