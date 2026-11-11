from sw_api.replay import run_replay
from sw_contracts import JobState
from sw_worker.state import transition
import pytest


def test_replay_records_actual_failures_and_versions(bundle):
    output = run_replay(bundle)
    assert output["passed"]
    assert len(output["checks"]) == 22
    assert output["code"]["source_hashes"]
    assert output["input"] == bundle
    assert not output["edits"]["locked_delete"]["accepted"]
    assert output["edits"]["cycle"]["error_code"] == "INVALID_TIMELINE"
    bundle["expected"]["coverage"]["process"] = "missing"
    wrong = run_replay(bundle)
    assert not wrong["passed"]
    assert wrong["checks"]["coverage/process"] is False


def test_worker_six_states_and_terminal_jobs_do_not_restart():
    assert len(JobState) == 6
    assert transition(JobState.queued, JobState.running) == JobState.running
    assert transition(JobState.running, JobState.waiting_user) == JobState.waiting_user
    for terminal in [JobState.succeeded, JobState.failed, JobState.cancelled]:
        with pytest.raises(ValueError):
            transition(terminal, JobState.running)
