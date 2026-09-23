from app.queue_policy import QueuePolicy


def test_auto_uses_large_when_queue_is_below_threshold():
    policy = QueuePolicy(threshold=2)
    assert policy.choose_model("auto", 1) == "large-v3"


def test_auto_uses_medium_when_two_jobs_wait():
    policy = QueuePolicy(threshold=2)
    assert policy.choose_model("auto", 2) == "medium"
    assert policy.choose_model(None, 4) == "medium"


def test_manual_override_wins_over_queue_depth():
    policy = QueuePolicy(threshold=2)
    assert policy.choose_model("large-v3", 20) == "large-v3"
    assert policy.choose_model("medium", 0) == "medium"
