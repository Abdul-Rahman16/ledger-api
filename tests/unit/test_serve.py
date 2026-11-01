import subprocess
import sys
from unittest import mock

from scripts import serve


def test_server_kwargs_default_port_and_proxy_headers():
    kwargs = serve.build_server_kwargs({})
    assert kwargs == {
        "host": "0.0.0.0",
        "port": 8000,
        "proxy_headers": True,
        "forwarded_allow_ips": "*",
        "log_level": "info",
    }
    assert serve.build_server_kwargs({"PORT": "10000"})["port"] == 10000


def test_a_bad_port_is_an_error_not_a_silent_default():
    try:
        serve.build_server_kwargs({"PORT": "abc"})
    except ValueError:
        return
    raise AssertionError("Expected ValueError for a non-numeric PORT")


def test_migrations_only_run_when_enabled():
    fake_uvicorn = mock.Mock()
    with mock.patch.dict(sys.modules, {"uvicorn": fake_uvicorn}), \
            mock.patch.object(serve, "run_migrations") as migrate:
        serve.main({"PORT": "9000"})
        migrate.assert_not_called()
        fake_uvicorn.run.assert_called_once_with(
            "main:app", host="0.0.0.0", port=9000, proxy_headers=True,
            forwarded_allow_ips="*", log_level="info",
        )
        serve.main({"RUN_MIGRATIONS": "1"})
        migrate.assert_called_once()
        serve.main({"RUN_MIGRATIONS": "0"})
        migrate.assert_called_once()  # "0" and anything but "1" mean off


def test_a_failed_migration_stops_the_server_from_starting():
    fake_uvicorn = mock.Mock()
    failure = subprocess.CalledProcessError(1, "alembic")
    with mock.patch.dict(sys.modules, {"uvicorn": fake_uvicorn}), \
            mock.patch.object(serve, "run_migrations", side_effect=failure):
        try:
            serve.main({"RUN_MIGRATIONS": "1"})
        except subprocess.CalledProcessError:
            fake_uvicorn.run.assert_not_called()
            return
    raise AssertionError("Expected the migration failure to propagate")


def test_run_migrations_calls_alembic_upgrade_head_and_checks_the_exit_code():
    with mock.patch("subprocess.run") as run:
        serve.run_migrations()
    command = run.call_args[0][0]
    assert command[-3:] == ["alembic", "upgrade", "head"]
    assert run.call_args[1] == {"check": True}