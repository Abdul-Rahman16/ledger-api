"""
Verify the storage settings: writes, reads back and deletes one small object.
  python -m scripts.storage_check
"""
import uuid

from core.storage import StorageError, get_storage


def main() -> None:
    storage = get_storage()
    if storage is None:
        print("Storage is not configured (STORAGE_BUCKET is empty).")
        raise SystemExit(2)

    key = f"raw/_check/{uuid.uuid4()}.txt"
    payload = b"ledger storage check"
    try:
        storage.put(key, payload, "text/plain")
        matches = storage.get(key) == payload
        storage.delete(key)
    except StorageError as exc:
        print("FAILED:", exc)
        raise SystemExit(1)

    if not matches:
        print("FAILED: the object read back did not match what was written.")
        raise SystemExit(1)
    print("OK: wrote, read back and deleted a test object.")


if __name__ == "__main__":
    main()