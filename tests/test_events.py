from src import store
from src.events import list_events, publish_event


def test_publish_and_list_events_in_order():
    run = store.create_run(platform="web", bdd_script="...")
    publish_event(run.id, "run_provisioning", {"scenarios_total": 2})
    publish_event(run.id, "run_running")

    events = list_events(run.id)
    assert [e.type for e in events] == ["run_provisioning", "run_running"]
    assert events[0].payload == {"scenarios_total": 2}


def test_list_events_after_seq_replays_only_new_events():
    run = store.create_run(platform="web", bdd_script="...")
    publish_event(run.id, "a")
    publish_event(run.id, "b")
    first_seq = list_events(run.id)[0].id

    replayed = list_events(run.id, after_seq=first_seq)
    assert [e.type for e in replayed] == ["b"]


def test_list_events_scoped_to_run():
    run1 = store.create_run(platform="web", bdd_script="...")
    run2 = store.create_run(platform="web", bdd_script="...")
    publish_event(run1.id, "a")
    publish_event(run2.id, "b")

    assert [e.type for e in list_events(run1.id)] == ["a"]
