"""Repeated attempts of a (task, mode) are selected explicitly and never dropped silently."""

import json

import pytest

from pathmemory.config import settings
from pathmemory.evaluation import report


def _rows(tmp_path, rows):
    p = tmp_path / "eval.jsonl"
    base = {
        "steps": 2,
        "llm_steps": 2,
        "replayed_steps": 0,
        "input_tokens": 100,
        "seconds": 1.0,
        "exp_dir": "/r/results/x",
    }
    p.write_text("".join(json.dumps({**base, **r}) + "\n" for r in rows))
    return p


def test_first_and_latest_differ_and_both_are_visible(tmp_path):
    p = _rows(
        tmp_path,
        [
            {"task": "a", "mode": "graph", "success": True, "task_sha": "a1"},
            {"task": "b", "mode": "graph", "success": False, "task_sha": "b1"},
            {"task": "b", "mode": "graph", "success": True, "task_sha": "b1"},
        ],
    )
    rows = report.load_rows(p)
    assert len(rows) == 3 and [r["_attempt"] for r in rows] == [1, 1, 2]
    first = report.summarize(report.select(rows, "first"))["graph"]
    latest = report.summarize(report.select(rows, "latest"))["graph"]
    assert (first["success"], first["tasks"]) == (1, 2)
    assert (latest["success"], latest["tasks"]) == (2, 2)
    [d] = report.duplicates(rows)
    assert d["task"] == "b" and [a["success"] for a in d["attempts"]] == [False, True]
    assert d["same_definition"] is True


def test_different_definitions_under_one_id_are_never_pooled(tmp_path):
    p = _rows(
        tmp_path,
        [
            {"task": "b", "mode": "none", "success": False, "task_sha": "old"},
            {"task": "b", "mode": "graph", "success": True, "task_sha": "new"},
            {"task": "b", "mode": "none", "success": True, "task_sha": "new"},
        ],
    )
    rows = report.load_rows(p)
    for policy in ("first", "latest"):
        by = report.select(rows, policy)
        assert set(by) == {"b@old", "b@new"}  # two units, whatever the policy
        assert by["b@old"]["none"]["success"] is False and set(by["b@old"]) == {"none"}
        assert by["b@new"]["none"]["success"] is True
    [d] = report.duplicates(rows)
    assert d["same_definition"] is False


def test_selection_must_be_explicit(tmp_path):
    rows = report.load_rows(_rows(tmp_path, [{"task": "a", "mode": "none", "success": True}]))
    with pytest.raises(ValueError):
        report.select(rows, None)
    with pytest.raises(SystemExit):  # the CLI has no default policy
        report.main([str(tmp_path / "eval.jsonl")])


def test_cli_prints_every_repeated_attempt(tmp_path, capsys):
    p = _rows(
        tmp_path,
        [
            {"task": "b", "mode": "none", "success": False, "goal": "count commits"},
            {"task": "b", "mode": "none", "success": True, "goal": "read description"},
        ],
    )
    out = report.main([str(p), "--select", "both"])
    text = capsys.readouterr().out
    for policy in ("first", "latest"):  # different goals = two reporting units, one failure and one success
        assert (out[policy]["none"]["tasks"], out[policy]["none"]["success"]) == (2, 1)
    assert "TASK DEFINITION CHANGED" in text and "count commits" in text and "read description" in text
    assert "2 observations" in text


V1 = settings.root / "docs/evidence/v1/eval.jsonl"


@pytest.mark.skipif(not (settings.root / "results/v1/eval").exists(), reason="v1 run directories not available")
def test_v1_repos5_rerun_was_a_different_task():
    rows = report.load_rows(V1)
    dups = report.duplicates(rows)
    assert len(rows) == 45 and {(d["task"], d["mode"]) for d in dups} == {
        ("repos-5", m) for m in ("none", "flat", "graph")
    }
    by = report.select(rows, "latest")
    assert len(by) == 15 and sum(k.startswith("repos-5@") for k in by) == 2  # never pooled under "repos-5"
    for d in dups:
        assert d["same_definition"] is False
        assert "commits" in d["attempts"][0]["goal"] and "description" in d["attempts"][1]["goal"]
