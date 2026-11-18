from datetime import UTC, datetime

from kubeevents.watcher import safe_count, to_record

from .conftest import make_event


def test_safe_count_prefers_count_then_series() -> None:
    assert safe_count(make_event(count=3)) == 3
    assert safe_count(make_event(count=4, legacy_fields=False)) == 4
    assert safe_count(make_event(count=None)) == 1


def test_to_record_legacy_fields() -> None:
    record = to_record(make_event())

    assert record.uid == "uid-1"
    assert record.namespace == "test"
    assert record.involved_kind == "Pod"
    assert record.component == "kubelet"
    assert record.host == "node-1"
    assert record.first_timestamp == datetime(2026, 11, 18, 10, 0, tzinfo=UTC)
    assert record.count == 1


def test_to_record_new_fields_fill_gaps() -> None:
    record = to_record(make_event(count=5, legacy_fields=False))

    assert record.component == "kubelet"
    assert record.host == "node-2"
    assert record.first_timestamp == datetime(2026, 11, 18, 10, 0, tzinfo=UTC)
    assert record.last_timestamp == datetime(2026, 11, 18, 11, 0, tzinfo=UTC)
    assert record.count == 5
