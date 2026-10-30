import json
from datetime import datetime, timedelta, timezone
from core.history_identity import history_owner


def test_retention_and_user_scope(store):
    token = history_owner.set("one")
    try:
        old = store.save_artifact("run", "old", "txt", b"old")
        recent = store.save_artifact("run", "recent", "txt", b"new")
        old["created_at"] = (datetime.now(timezone.utc) - timedelta(days=16)).isoformat()
        with store.connect() as db:
            db.execute("UPDATE artifacts SET payload = ? WHERE id = ?", (json.dumps(old), old["id"]))
        assert [item["id"] for item in store.list_artifacts()] == [recent["id"]]
        assert store.get_artifact(old["id"]) is None
        store.purge_expired_artifacts()
        assert not (store.artifacts_dir / old["filename"]).exists()
        assert (store.artifacts_dir / recent["filename"]).read_bytes() == b"new"
    finally:
        history_owner.reset(token)
    token = history_owner.set("other")
    try:
        assert store.list_artifacts() == []
    finally:
        history_owner.reset(token)
