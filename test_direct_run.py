#!/usr/bin/env python3
"""Self-checks for direct_run.py. Run: python3 test_direct_run.py"""

import direct_run as dr

# Keep the checks fast and quiet, including when collected by pytest.
dr.log = lambda *args, **kwargs: None
dr.time.sleep = lambda seconds: None


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {}
        self.text = str(self._body)

    def json(self):
        return self._body


class FakeAPI:
    """Returns queued responses; the last one repeats."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, path, payload=None):
        self.calls.append((path, payload))
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]


def make_quest(task_type="WATCH_VIDEO", target=30, done=0):
    return {
        "id": "q1",
        "config": {"taskConfig": {"tasks": {task_type: {"target": target}}}},
        "userStatus": {
            "enrolledAt": "2020-01-01T00:00:00+00:00",
            "progress": {task_type: {"value": done}},
        },
    }


def make_completer(api):
    c = dr.QuestCompleter("x" * 60, poll_interval=10, run_once=True)
    c._api = api
    c.username = "tester"
    return c


def test_parse_timestamp():
    assert dr.parse_timestamp("2026-01-01T00:00:00Z") is not None
    assert dr.parse_timestamp(None) is None
    assert dr.parse_timestamp("not-a-date") is None


def test_null_progress():
    quest = make_quest()
    quest["userStatus"]["progress"] = None
    assert dr.get_seconds_done(quest) == 0
    quest["userStatus"]["progress"] = {"WATCH_VIDEO": None}
    assert dr.get_seconds_done(quest) == 0


def test_expired_quest_not_completable():
    quest = make_quest()
    quest["config"]["expiresAt"] = "2020-01-01T00:00:00Z"
    assert dr.is_completable(quest) is False


def test_video_success_marks_completed():
    api = FakeAPI(
        FakeResponse(200, {"progress": {"WATCH_VIDEO": {"value": 0}}}),
        FakeResponse(200),
        FakeResponse(200),
        FakeResponse(200),
        FakeResponse(200),
        FakeResponse(200, {"completed_at": "2026-01-01T00:01:00Z"}),
    )
    c = make_completer(api)
    c._process_quest(make_quest())
    assert c.stats["quests_completed"] == 1
    assert "q1" in c._completed_ids
    assert api.calls[-1][1] == {"timestamp": 30}


def test_video_failure_not_counted():
    api = FakeAPI(FakeResponse(500))
    c = make_completer(api)
    c._process_quest(make_quest())
    assert c.stats["quests_completed"] == 0
    assert "q1" not in c._completed_ids
    assert len(api.calls) == dr.MAX_FAILURES


def test_stop_skips_final_request():
    api = FakeAPI(FakeResponse(200, {"completed_at": "2026-01-01T00:01:00Z"}))
    c = make_completer(api)
    c._should_stop = True
    assert c._complete_video(make_quest()) is False
    assert api.calls == []


def test_heartbeat_stall_stops():
    api = FakeAPI(FakeResponse(200, {"progress": {"PLAY_ON_DESKTOP": {"value": 0}}}))
    c = make_completer(api)
    c._process_quest(make_quest("PLAY_ON_DESKTOP", target=60))
    assert c.stats["quests_completed"] == 0
    assert "q1" not in c._completed_ids
    assert len(api.calls) == dr.MAX_STALLS


def test_heartbeat_success():
    api = FakeAPI(FakeResponse(200, {"completed_at": "2026-01-01T00:01:00Z"}))
    c = make_completer(api)
    c._process_quest(make_quest("PLAY_ACTIVITY", target=60))
    assert c.stats["quests_completed"] == 1
    assert "q1" in c._completed_ids


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"ok  {test.__name__}")
    print(f"\n{len(tests)} checks passed")


if __name__ == "__main__":
    main()
