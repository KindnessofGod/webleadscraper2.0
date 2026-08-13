import pytest

from src import db
from src.cost_tracker import CostCeilingExceeded, CostTracker


@pytest.fixture
def conn(tmp_path):
    return db.connect(str(tmp_path / "test.db"))


def test_records_cost_and_accumulates(conn):
    tracker = CostTracker(conn, run_id="r1", price_usd_per_gb=1.0, ceiling_usd=10.0)
    one_gb = 1024 ** 3
    tracker.record(one_gb // 2, batch_id="b1")
    assert tracker.cumulative_cost_usd == pytest.approx(0.5, abs=1e-6)
    tracker.record(one_gb // 2, batch_id="b2")
    assert tracker.cumulative_cost_usd == pytest.approx(1.0, abs=1e-6)


def test_raises_when_ceiling_exceeded(conn):
    tracker = CostTracker(conn, run_id="r1", price_usd_per_gb=1.0, ceiling_usd=1.0)
    one_gb = 1024 ** 3
    with pytest.raises(CostCeilingExceeded):
        tracker.record(int(one_gb * 1.5), batch_id="b1")


def test_ledger_persists_across_tracker_instances(conn):
    one_gb = 1024 ** 3
    CostTracker(conn, run_id="r1", price_usd_per_gb=1.0, ceiling_usd=10.0).record(one_gb, batch_id="b1")
    tracker2 = CostTracker(conn, run_id="r2", price_usd_per_gb=1.0, ceiling_usd=10.0)
    assert tracker2.cumulative_cost_usd == pytest.approx(1.0, abs=1e-6)


def test_new_run_starts_above_ceiling_if_prior_runs_spent_it(conn):
    one_gb = 1024 ** 3
    tracker1 = CostTracker(conn, run_id="r1", price_usd_per_gb=1.0, ceiling_usd=100.0)
    tracker1.record(int(one_gb * 5), batch_id="b1")

    tracker2 = CostTracker(conn, run_id="r2", price_usd_per_gb=1.0, ceiling_usd=5.0)
    with pytest.raises(CostCeilingExceeded):
        tracker2.check_ceiling()
