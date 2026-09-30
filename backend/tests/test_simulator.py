import pandas as pd

from app.data.loader import validate_frames
from app.data.schemas import TABLES
from app.data.simulator import SimConfig, simulate


def test_simulator_is_deterministic_and_valid():
    a = simulate(SimConfig(devices=150, weeks=10, seed=3))
    b = simulate(SimConfig(devices=150, weeks=10, seed=3))
    for name in TABLES:
        pd.testing.assert_frame_equal(a[name], b[name])
    assert len(a["devices"]) == 150
    assert len(a["telemetry"]) == 150 * 10
    assert set(a["telemetry"]["week"]) == set(range(1, 11))
    assert len(a["tickets"]) > 0 and len(a["remediations"]) > 0
    frames, _ = validate_frames({k: v.copy() for k, v in a.items()})  # raises if the schema drifts
    assert len(frames["tickets"]) == len(a["tickets"])


def test_simulator_seed_changes_output():
    a = simulate(SimConfig(devices=80, weeks=8, seed=1))["telemetry"]
    b = simulate(SimConfig(devices=80, weeks=8, seed=2))["telemetry"]
    assert not a["boot_duration_sec"].equals(b["boot_duration_sec"])
