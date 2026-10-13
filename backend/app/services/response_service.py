"""Response Recommendation Agent.

A rule-based playbook mapping (hazard type, severity) to recommended
departments and actions. Output is **advisory only**: nothing in this
prototype contacts any emergency service.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.app.core.enums import HazardType, Priority, Severity

PRIORITY_FOR_SEVERITY = {
    Severity.CRITICAL: Priority.P1,
    Severity.HIGH: Priority.P2,
    Severity.MEDIUM: Priority.P3,
    Severity.LOW: Priority.P4,
}


@dataclass(frozen=True)
class ResponseRecommendation:
    department: str
    action: str
    priority: Priority


def _fire(sev: Severity) -> list[tuple[str, str]]:
    if sev in (Severity.HIGH, Severity.CRITICAL):
        return [("Fire Brigade", "Recommend immediate fire brigade response; begin evacuation of the affected area.")]
    return [("Fire Brigade", "Verify footage, then request fire brigade response if fire is confirmed.")]


def _smoke(sev: Severity) -> list[tuple[str, str]]:
    if sev in (Severity.HIGH, Severity.CRITICAL):
        return [("Fire Safety", "Investigate smoke source on site; place fire brigade on standby.")]
    return [("Fire Safety", "Investigate possible smoke source and verify on camera.")]


def _accident(sev: Severity) -> list[tuple[str, str]]:
    recs = [("Ambulance / EMS", "Recommend ambulance dispatch to the accident location.")]
    if sev in (Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL):
        recs.append(("Traffic Police", "Recommend police assistance for traffic control and scene safety."))
    return recs


def _spark(sev: Severity) -> list[tuple[str, str]]:
    recs = [("Electrical Maintenance", "Isolate power to the affected circuit and inspect the equipment.")]
    if sev in (Severity.HIGH, Severity.CRITICAL):
        recs.append(("Fire Safety", "Keep fire safety personnel on standby due to ignition risk."))
    return recs


def _fall(sev: Severity) -> list[tuple[str, str]]:
    if sev in (Severity.HIGH, Severity.CRITICAL):
        return [("Ambulance / EMS", "Recommend medical emergency assistance for the fallen person.")]
    return [("On-site Medical / Security", "Send on-site staff to check on the person and assess injuries.")]


_PLAYBOOK = {
    HazardType.FIRE: _fire,
    HazardType.SMOKE: _smoke,
    HazardType.ROAD_ACCIDENT: _accident,
    HazardType.ELECTRICAL_SPARK: _spark,
    HazardType.PERSON_FALL: _fall,
}


class ResponseRecommendationAgent:
    def recommend(self, hazard_type: HazardType, severity: Severity) -> list[ResponseRecommendation]:
        hazard_type, severity = HazardType(hazard_type), Severity(severity)
        priority = PRIORITY_FOR_SEVERITY[severity]
        return [ResponseRecommendation(dept, action, priority) for dept, action in _PLAYBOOK[hazard_type](severity)]
