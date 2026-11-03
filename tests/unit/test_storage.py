import io
import uuid

from core.storage import S3Storage, StorageError, owner_prefix, raw_object_key, safe_filename


class FakeClient:
    def __init__(self):
        self.objects = {}
        self.calls = []
        self.fail = False

    def put_object(self, **kwargs):
        self.calls.append(("put", kwargs))
        if self.fail:
            raise RuntimeError("AKIASECRETKEY leaked in a message")
        self.objects[kwargs["Key"]] = kwargs["Body"]

    def get_object(self, **kwargs):
        self.calls.append(("get", kwargs))
        if self.fail:
            raise RuntimeError("boom")
        return {"Body": io.BytesIO(self.objects[kwargs["Key"]])}

    def delete_object(self, **kwargs):
        self.calls.append(("delete", kwargs))
        if self.fail:
            raise RuntimeError("boom")
        self.objects.pop(kwargs["Key"], None)


def test_safe_filename_removes_paths_and_odd_characters():
    assert safe_filename("sales.csv") == "sales.csv"
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("C:\\Users\\me\\my sales (final)?.csv") == "my_sales_final_.csv"
    assert safe_filename("..") == "upload" and safe_filename("") == "upload" and safe_filename(None) == "upload"
    assert safe_filename("x" * 300 + ".csv").startswith("xxx") and len(safe_filename("x" * 300 + ".csv")) == 100


def test_owner_prefix_groups_guests_and_hides_user_ids():
    assert owner_prefix(None) == "guest"
    first, second = owner_prefix("user-123"), owner_prefix("user-124")
    assert first.startswith("u-") and len(first) == 18 and first != second
    assert first == owner_prefix("user-123")
    assert "user-123" not in first


def test_raw_object_key_layout():
    dataset_id = uuid.UUID("c56d392e-99ea-4ecd-9e51-2fd71aff8740")
    assert raw_object_key(dataset_id, "sales.csv", None) == f"raw/guest/{dataset_id}/sales.csv"
    key = raw_object_key(dataset_id, "../sales data.csv", "user-1")
    assert key.startswith("raw/u-") and key.endswith(f"/{dataset_id}/sales_data.csv") and "user-1" not in key


def test_put_get_delete_use_the_configured_bucket():
    client = FakeClient()
    storage = S3Storage(client, "my-bucket")
    storage.put("raw/guest/x/a.csv", b"a,b\n1,2\n", "text/csv")
    assert client.calls[0] == ("put", {"Bucket": "my-bucket", "Key": "raw/guest/x/a.csv",
                                       "Body": b"a,b\n1,2\n", "ContentType": "text/csv"})
    assert storage.get("raw/guest/x/a.csv") == b"a,b\n1,2\n"
    storage.delete("raw/guest/x/a.csv")
    assert "raw/guest/x/a.csv" not in client.objects
    assert client.calls[2] == ("delete", {"Bucket": "my-bucket", "Key": "raw/guest/x/a.csv"})


def test_content_type_is_optional():
    client = FakeClient()
    S3Storage(client, "b").put("k", b"x")
    assert "ContentType" not in client.calls[0][1]


def test_client_errors_become_storage_errors_without_leaking_details():
    client = FakeClient()
    client.fail = True
    storage = S3Storage(client, "b")
    for action in (lambda: storage.put("k", b"x"), lambda: storage.get("k"), lambda: storage.delete("k")):
        try:
            action()
        except StorageError as exc:
            assert "AKIA" not in str(exc) and "RuntimeError" in str(exc)
            continue
        raise AssertionError("Expected StorageError")