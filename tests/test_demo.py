"""The demo uses all current trials and can display committed summaries without local traces."""

import json

import pytest
from fastapi.testclient import TestClient

from pathmemory.config import settings
from pathmemory.demo import runs
from pathmemory.demo.app import app
from pathmemory.evaluation.compare import table


def test_published_v2_summary_matches_the_comparison_with_no_local_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(runs, "RESULTS", tmp_path)

    experiments = runs.RunService().experiments()
    [broken] = [e for e in experiments if e["file"] == "docs/evidence/v2/runs/broken.jsonl"]
    rows = [
        json.loads(line) | {"condition": "broken"} for line in (settings.root / broken["file"]).read_text().splitlines()
    ]

    assert broken["selection"] == "all" and broken["observations"] == 20
    assert len(broken["tasks"]) == 5
    assert all(not row["available"] for modes in broken["tasks"].values() for row in modes.values())
    for comparison in table(rows):
        summary = broken["summary"][comparison["mode"]]
        assert summary["tasks"] == comparison["trials"] == 5
        assert summary["success"] == comparison["success"]
        assert summary["model_calls"] == comparison["model_calls"]["mean"]
        assert summary["replay_reached_goal"] == comparison["replay_reached_goal"]
        assert summary["est_cost_usd"] == pytest.approx(comparison["est_cost_usd"]["mean"], abs=0.00005)


def test_repeated_trial_numbers_are_not_dropped_from_local_results(monkeypatch, tmp_path):
    monkeypatch.setattr(runs, "RESULTS", tmp_path)
    monkeypatch.setattr(
        runs,
        "EXPERIMENTS",
        [
            ("batch/eval.jsonl", "unused.jsonl", "local trials", "all"),
        ],
    )
    # Keep the source path under the checkout for the UI's relative provenance field.
    monkeypatch.setattr(runs, "settings", type("Settings", (), {"root": tmp_path})())
    source = settings.root / "docs/evidence/v2/runs/broken.jsonl"
    row = json.loads(source.read_text().splitlines()[0])
    batch = tmp_path / "batch/eval.jsonl"
    batch.parent.mkdir()
    batch.write_text(json.dumps(row) + "\n" + json.dumps(row | {"success": False}) + "\n")

    [experiment] = runs.RunService().experiments()

    summary = experiment["summary"][row["mode"]]
    assert summary["tasks"] == 2 and summary["success"] == 1
    assert len(experiment["tasks"]) == 2


def test_ui_serves_split_assets_and_published_summaries(monkeypatch, tmp_path):
    monkeypatch.setattr(runs, "RESULTS", tmp_path)
    with TestClient(app) as client:
        index = client.get("/")
        assert index.status_code == 200
        assert "/static/styles.css" in index.text and "/static/app.js" in index.text
        for asset in ("styles.css", "app.js"):
            assert client.get(f"/static/{asset}").status_code == 200
        experiments = client.get("/api/experiments")
        assert experiments.status_code == 200
        assert any(e["selection"] == "all" for e in experiments.json())
