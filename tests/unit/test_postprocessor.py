import pytest

from backend.app.ai.detector import Detection
from backend.app.ai.postprocessor import EventKind, TemporalValidator, filter_detections, scale_detections
from backend.app.core.enums import HazardType


def det(h=HazardType.FIRE, conf=0.8, bbox=(10, 10, 50, 50)):
    return Detection(h, conf, bbox, h.value.lower())


# ---------------------------------------------------------------- confidence filtering
def test_filter_uses_per_hazard_thresholds():
    dets = [det(HazardType.FIRE, 0.55), det(HazardType.SMOKE, 0.55), det(HazardType.PERSON_FALL, 0.3)]
    kept = filter_detections(dets, {HazardType.SMOKE: 0.7}, default_threshold=0.5)
    assert [d.hazard_type for d in kept] == [HazardType.FIRE]


def test_filter_threshold_is_inclusive():
    assert filter_detections([det(conf=0.5)], {}, 0.5)


def test_filter_drops_unsupported_hazards():
    kept = filter_detections([det(HazardType.FIRE), det(HazardType.SMOKE)], {}, 0.1, supported={HazardType.FIRE})
    assert [d.hazard_type for d in kept] == [HazardType.FIRE]


def test_scale_detections_maps_back_to_original_pixels():
    (d,) = scale_detections([det(bbox=(10, 20, 30, 40))], scale=0.5)
    assert d.bbox == (20, 40, 60, 80)
    assert scale_detections([det()], 1.0)[0].bbox == (10, 10, 50, 50)


# ---------------------------------------------------------------- temporal validation
def run(validator, pattern, hazard=HazardType.FIRE):
    """pattern: string of 1/0 per processed frame."""
    events = []
    for i, ch in enumerate(pattern):
        events += validator.update(i, i * 0.2, [det(hazard)] if ch == "1" else [])
    return events


def kinds(events):
    return [e.kind for e in events]


def test_single_frame_false_positive_is_rejected():
    v = TemporalValidator(window_size=5, min_hits=3, end_after_missed=3)
    assert run(v, "1000000") == []
    assert v.tracks == {}


def test_confirmation_requires_min_hits_in_window():
    v = TemporalValidator(window_size=5, min_hits=3, end_after_missed=3)
    events = run(v, "11")
    assert events == []
    events = run(v, "1")  # third hit -> confirmed
    assert kinds(events) == [EventKind.CONFIRMED]


def test_intermittent_detections_confirm_k_of_n():
    v = TemporalValidator(window_size=5, min_hits=3, end_after_missed=3)
    events = run(v, "10101")
    assert kinds(events) == [EventKind.CONFIRMED]
    assert events[0].total_hits == 3


def test_sparse_hits_never_confirm():
    v = TemporalValidator(window_size=4, min_hits=3, end_after_missed=3)
    assert EventKind.CONFIRMED not in kinds(run(v, "1001001001"))


def test_continuous_event_confirmed_once_then_updated():
    v = TemporalValidator(window_size=5, min_hits=3, end_after_missed=3)
    events = run(v, "1" * 20)
    assert kinds(events).count(EventKind.CONFIRMED) == 1
    assert kinds(events).count(EventKind.UPDATED) == 17
    assert len({e.track_id for e in events}) == 1  # duplicate prevention at track level


def test_short_gap_does_not_split_event():
    v = TemporalValidator(window_size=5, min_hits=3, end_after_missed=4)
    events = run(v, "11111" + "000" + "11111")
    assert kinds(events).count(EventKind.CONFIRMED) == 1
    assert EventKind.ENDED not in kinds(events)


def test_event_ends_after_missed_frames_and_new_event_gets_new_track():
    v = TemporalValidator(window_size=5, min_hits=3, end_after_missed=3)
    events = run(v, "11111" + "000" + "11111")
    assert kinds(events).count(EventKind.CONFIRMED) == 2
    assert kinds(events).count(EventKind.ENDED) == 1
    confirmed = [e for e in events if e.kind == EventKind.CONFIRMED]
    assert confirmed[0].track_id != confirmed[1].track_id


def test_flush_ends_confirmed_tracks_only():
    v = TemporalValidator(window_size=5, min_hits=3, end_after_missed=10)
    run(v, "111", HazardType.FIRE)
    v.update(10, 2.0, [det(HazardType.SMOKE)])  # unconfirmed smoke track
    ended = v.flush()
    assert [(e.kind, e.hazard_type) for e in ended] == [(EventKind.ENDED, HazardType.FIRE)]
    assert v.tracks == {}


def test_hazards_are_tracked_independently():
    v = TemporalValidator(window_size=3, min_hits=2, end_after_missed=2)
    events = []
    for i in range(3):
        events += v.update(i, i, [det(HazardType.FIRE), det(HazardType.SMOKE, 0.6)])
    confirmed = {e.hazard_type for e in events if e.kind == EventKind.CONFIRMED}
    assert confirmed == {HazardType.FIRE, HazardType.SMOKE}


def test_best_detection_and_statistics():
    v = TemporalValidator(window_size=3, min_hits=3, end_after_missed=2, max_samples=2)
    events = []
    for i, conf in enumerate([0.6, 0.9, 0.7]):
        events += v.update(i * 5, i * 0.2, [det(conf=conf), det(conf=conf - 0.1)])
    (ev,) = events
    assert ev.max_confidence == 0.9
    assert ev.mean_confidence == pytest.approx((0.6 + 0.9 + 0.7) / 3, abs=1e-4)
    assert ev.best.frame_index == 5
    assert len(ev.samples) == 2  # capped by max_samples
    assert (ev.first_frame, ev.last_frame) == (0, 10)


@pytest.mark.parametrize("kwargs", [dict(window_size=3, min_hits=4), dict(min_hits=0), dict(end_after_missed=0)])
def test_invalid_validator_parameters(kwargs):
    with pytest.raises(ValueError):
        TemporalValidator(**kwargs)
