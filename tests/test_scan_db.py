"""Unit tests for ScanDB — SQLite scan history database."""
import json
import pytest


class TestScanDBInit:
    """Database creation and schema."""

    def test_db_file_created(self, scan_db, tmp_path):
        """Database file exists after init."""
        db_path = tmp_path / "test_scan_history.db"
        assert db_path.exists()

    def test_empty_initially(self, scan_db):
        """No scans in fresh database."""
        assert scan_db.count() == 0
        assert scan_db.list_scans() == []


class TestScanDBRecordScan:
    """CRUD: Create (record_scan)."""

    def test_record_basic(self, scan_db, sample_scan_metadata):
        """Record a scan and verify row ID."""
        row_id = scan_db.record_scan(**sample_scan_metadata)
        assert row_id > 0

    def test_record_increments_count(self, scan_db, sample_scan_metadata):
        """Each record_scan increases count."""
        scan_db.record_scan(**sample_scan_metadata)
        assert scan_db.count() == 1

        meta2 = sample_scan_metadata.copy()
        meta2["uid"] = "00000000-0000-0000-0000-000000000001"
        scan_db.record_scan(**meta2)
        assert scan_db.count() == 2

    def test_record_with_none_optionals(self, scan_db):
        """Record with minimal required fields."""
        row_id = scan_db.record_scan(
            uid="test-uid-minimal",
            plan_name="count",
            status="success",
            start_time="2026-02-15T12:00:00"
        )
        assert row_id > 0

    def test_record_duplicate_uid_replaces(self, scan_db, sample_scan_metadata):
        """INSERT OR REPLACE: same UID overwrites."""
        scan_db.record_scan(**sample_scan_metadata)
        sample_scan_metadata["status"] = "failed"
        scan_db.record_scan(**sample_scan_metadata)
        assert scan_db.count() == 1
        row = scan_db.get_scan(sample_scan_metadata["uid"])
        assert row["status"] == "failed"

    def test_record_with_params_json(self, scan_db):
        """params dict is stored as JSON and retrieved as dict."""
        params = {"e_start": 9.0, "e_stop": 11.0, "elements": ["Fe", "Cu"]}
        scan_db.record_scan(
            uid="test-json-params",
            plan_name="energy_scan",
            status="success",
            start_time="2026-02-15T12:00:00",
            params=params
        )
        row = scan_db.get_scan("test-json-params")
        assert row["params"] == params
        assert isinstance(row["params"]["elements"], list)


class TestScanDBListScans:
    """CRUD: Read (list_scans, get_scan)."""

    def _insert_n(self, scan_db, n):
        for i in range(n):
            scan_db.record_scan(
                uid=f"uid-{i:04d}",
                plan_name="energy_scan" if i % 2 == 0 else "raster_scan",
                status="success",
                start_time=f"2026-02-15T{10 + i // 60:02d}:{i % 60:02d}:00",
                num_points=i * 10
            )

    def test_list_default(self, scan_db):
        """list_scans returns scans in reverse chronological order."""
        self._insert_n(scan_db, 5)
        rows = scan_db.list_scans()
        assert len(rows) == 5
        # Most recent first
        assert rows[0]["uid"] == "uid-0004"

    def test_list_limit(self, scan_db):
        """limit parameter caps result count."""
        self._insert_n(scan_db, 20)
        rows = scan_db.list_scans(limit=5)
        assert len(rows) == 5

    def test_list_offset(self, scan_db):
        """offset skips first N results (pagination)."""
        self._insert_n(scan_db, 10)
        page1 = scan_db.list_scans(limit=3, offset=0)
        page2 = scan_db.list_scans(limit=3, offset=3)
        assert page1[0]["uid"] != page2[0]["uid"]
        # No overlap
        uids1 = {r["uid"] for r in page1}
        uids2 = {r["uid"] for r in page2}
        assert uids1.isdisjoint(uids2)

    def test_list_plan_filter(self, scan_db):
        """plan_filter returns only matching plan type."""
        self._insert_n(scan_db, 10)
        raster = scan_db.list_scans(plan_filter="raster_scan")
        assert all(r["plan_name"] == "raster_scan" for r in raster)
        assert len(raster) == 5  # odd indices

    def test_get_scan_found(self, scan_db, sample_scan_metadata):
        """get_scan returns dict for existing UID."""
        scan_db.record_scan(**sample_scan_metadata)
        row = scan_db.get_scan(sample_scan_metadata["uid"])
        assert row is not None
        assert row["plan_name"] == "energy_scan"
        assert row["num_points"] == 50

    def test_get_scan_not_found(self, scan_db):
        """get_scan returns None for missing UID."""
        assert scan_db.get_scan("nonexistent-uid") is None


class TestScanDBDelete:
    """CRUD: Delete."""

    def test_delete_existing(self, scan_db, sample_scan_metadata):
        """delete_scan removes record and returns True."""
        scan_db.record_scan(**sample_scan_metadata)
        assert scan_db.delete_scan(sample_scan_metadata["uid"]) is True
        assert scan_db.count() == 0

    def test_delete_nonexistent(self, scan_db):
        """delete_scan returns False for missing UID."""
        assert scan_db.delete_scan("no-such-uid") is False


class TestScanDBCount:
    """Count queries."""

    def test_count_all(self, scan_db):
        """count() returns total scans."""
        for i in range(7):
            scan_db.record_scan(
                uid=f"c-{i}", plan_name="count",
                status="success", start_time=f"2026-02-15T10:{i:02d}:00"
            )
        assert scan_db.count() == 7

    def test_count_with_filter(self, scan_db):
        """count(plan_filter) returns filtered count."""
        scan_db.record_scan(uid="a1", plan_name="energy_scan",
                            status="success", start_time="2026-02-15T10:00:00")
        scan_db.record_scan(uid="a2", plan_name="raster_scan",
                            status="success", start_time="2026-02-15T10:01:00")
        assert scan_db.count(plan_filter="energy_scan") == 1
        assert scan_db.count(plan_filter="raster_scan") == 1
        assert scan_db.count(plan_filter="xafs_scan") == 0
