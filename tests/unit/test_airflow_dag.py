import importlib.util
import io
import json
import sys
import types
import urllib.error
from pathlib import Path
from unittest import mock

DAG_FILE = Path(__file__).resolve().parents[2] / "orchestration" / "dags" / "ledger_maintenance.py"


class FakeTask:
    registry: list = []

    def __init__(self, function):
        self.function = function
        self.name = function.__name__
        self.downstream = []
        FakeTask.registry.append(self)

    def __call__(self):
        return self

    def __rshift__(self, other):
        self.downstream.append(other)
        return other


def load_dag_module(environ=None):
    """Imports the DAG file against a stand-in for airflow.sdk, so no Airflow install is needed."""
    FakeTask.registry = []
    captured = {}

    def fake_dag(**kwargs):
        def wrap(function):
            captured.update(kwargs)
            return function
        return wrap

    sdk = types.ModuleType("airflow.sdk")
    sdk.dag, sdk.task = fake_dag, FakeTask
    package = types.ModuleType("airflow")
    package.sdk = sdk
    spec = importlib.util.spec_from_file_location("ledger_maintenance_under_test", DAG_FILE)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"airflow": package, "airflow.sdk": sdk}), \
            mock.patch.dict("os.environ", environ or {}, clear=False):
        spec.loader.exec_module(module)
    module.captured_dag_kwargs = captured
    return module


def test_dag_definition_and_task_order():
    module = load_dag_module()
    kwargs = module.captured_dag_kwargs
    assert kwargs["dag_id"] == "ledger_maintenance"
    assert kwargs["schedule"] == "17 3 * * *" and kwargs["catchup"] is False
    assert kwargs["default_args"]["retries"] == 2
    tasks = {item.name: item for item in FakeTask.registry}
    assert set(tasks) == {"purge_guest_data", "reprofile_datasets", "snapshot_metrics"}
    assert tasks["purge_guest_data"].downstream == [tasks["reprofile_datasets"]]
    assert tasks["reprofile_datasets"].downstream == [tasks["snapshot_metrics"]]
    assert tasks["snapshot_metrics"].downstream == []


def test_each_task_calls_its_internal_endpoint():
    module = load_dag_module()
    paths = []
    with mock.patch.object(module, "call_api", side_effect=lambda path: paths.append(path) or {"ok": True}):
        for item in FakeTask.registry:
            assert item.function() == {"ok": True}
    assert paths == [
        "/internal/maintenance/purge-guest-data",
        "/internal/maintenance/reprofile",
        "/internal/maintenance/snapshot-metrics",
    ]


def test_call_api_sends_the_secret_and_returns_json():
    module = load_dag_module({"LEDGER_INTERNAL_SECRET": "s3cret", "LEDGER_API_URL": "http://api:8000/"})
    response = mock.MagicMock()
    response.read.return_value = json.dumps({"datasets_deleted": 2}).encode()
    response.__enter__.return_value = response
    with mock.patch.object(module.urllib.request, "urlopen", return_value=response) as urlopen:
        assert module.call_api("/internal/maintenance/purge-guest-data") == {"datasets_deleted": 2}
    request = urlopen.call_args[0][0]
    assert request.full_url == "http://api:8000/internal/maintenance/purge-guest-data"
    assert request.get_method() == "POST"
    assert request.get_header("X-internal-secret") == "s3cret"


def test_call_api_fails_loudly_so_airflow_can_retry():
    module = load_dag_module({"LEDGER_INTERNAL_SECRET": "s3cret"})
    error = urllib.error.HTTPError("http://x", 401, "Unauthorized", {}, io.BytesIO(b"nope"))
    with mock.patch.object(module.urllib.request, "urlopen", side_effect=error):
        try:
            module.call_api("/internal/maintenance/reprofile")
        except RuntimeError as exc:
            assert "HTTP 401" in str(exc) and "s3cret" not in str(exc)
        else:
            raise AssertionError("Expected RuntimeError")

    missing = load_dag_module({})
    with mock.patch.object(missing, "INTERNAL_SECRET", ""):
        try:
            missing.call_api("/x")
        except RuntimeError as exc:
            assert "LEDGER_INTERNAL_SECRET" in str(exc)
        else:
            raise AssertionError("Expected RuntimeError without a secret")