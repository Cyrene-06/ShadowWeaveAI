from sw_contracts import JobState

TRANSITIONS = {
    JobState.queued: {JobState.running, JobState.cancelled},
    JobState.running: {JobState.waiting_user, JobState.succeeded, JobState.failed, JobState.cancelled},
    JobState.waiting_user: {JobState.running, JobState.cancelled, JobState.failed},
    JobState.succeeded: set(),
    JobState.failed: set(),
    JobState.cancelled: set(),
}


def transition(current: JobState, next_state: JobState) -> JobState:
    if next_state not in TRANSITIONS[current]:
        raise ValueError(f"illegal job transition {current} -> {next_state}")
    return next_state
