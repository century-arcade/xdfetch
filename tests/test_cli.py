import pytest

from xdfetch import __version__, registry
from xdfetch.cli import main


def test_version(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_registry_loads():
    outlets = registry.load()
    assert isinstance(outlets, dict)


def test_list_runs():
    assert main(["list"]) == 0


def test_get_not_written_yet():
    assert main(["get", "lat"]) == 2
