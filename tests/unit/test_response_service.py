import pytest

from backend.app.core.enums import HazardType, Priority, Severity
from backend.app.services.response_service import ResponseRecommendationAgent

agent = ResponseRecommendationAgent()


def departments(h, s):
    return [r.department for r in agent.recommend(h, s)]


@pytest.mark.parametrize("hazard", list(HazardType))
@pytest.mark.parametrize("severity", list(Severity))
def test_every_combination_has_a_recommendation(hazard, severity):
    recs = agent.recommend(hazard, severity)
    assert recs and all(r.department and r.action for r in recs)


def test_fire_recommends_fire_brigade():
    assert departments(HazardType.FIRE, Severity.CRITICAL) == ["Fire Brigade"]
    assert "immediate" in agent.recommend(HazardType.FIRE, Severity.CRITICAL)[0].action


def test_accident_recommends_ambulance_and_police_when_serious():
    assert departments(HazardType.ROAD_ACCIDENT, Severity.LOW) == ["Ambulance / EMS"]
    assert departments(HazardType.ROAD_ACCIDENT, Severity.HIGH) == ["Ambulance / EMS", "Traffic Police"]


def test_spark_recommends_electrical_maintenance():
    assert departments(HazardType.ELECTRICAL_SPARK, Severity.MEDIUM)[0] == "Electrical Maintenance"


def test_fall_recommends_medical_help():
    assert departments(HazardType.PERSON_FALL, Severity.CRITICAL) == ["Ambulance / EMS"]


def test_smoke_recommends_investigation():
    assert "Investigate" in agent.recommend(HazardType.SMOKE, Severity.LOW)[0].action


@pytest.mark.parametrize("sev,prio", [(Severity.CRITICAL, Priority.P1), (Severity.HIGH, Priority.P2),
                                      (Severity.MEDIUM, Priority.P3), (Severity.LOW, Priority.P4)])
def test_priority_follows_severity(sev, prio):
    assert {r.priority for r in agent.recommend(HazardType.FIRE, sev)} == {prio}


def test_accepts_string_values():
    assert agent.recommend("FIRE", "HIGH")[0].priority == Priority.P2
