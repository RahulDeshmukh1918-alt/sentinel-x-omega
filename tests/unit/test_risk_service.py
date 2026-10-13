import pytest

from backend.app.core.enums import HazardType, Severity
from backend.app.services.risk_service import RiskAssessmentAgent, RiskConfig

FACTORS = {HazardType.FIRE: 0.9, HazardType.SMOKE: 0.6, HazardType.ROAD_ACCIDENT: 0.85,
           HazardType.ELECTRICAL_SPARK: 0.7, HazardType.PERSON_FALL: 0.75}


@pytest.fixture
def agent():
    return RiskAssessmentAgent(RiskConfig(0.4, 0.3, 0.3, 15, FACTORS))


def test_score_matches_documented_formula(agent):
    # 100 * (0.4*0.8 + 0.3*(15/15) + 0.3*0.9) = 89.0
    r = agent.assess(HazardType.FIRE, confidence=0.8, persistence_frames=15)
    assert r.score == pytest.approx(89.0)
    assert r.severity == Severity.CRITICAL
    assert (r.confidence_component, r.persistence_component, r.severity_component) == (0.8, 1.0, 0.9)


def test_partial_persistence(agent):
    # 100 * (0.4*0.6 + 0.3*(5/15) + 0.3*0.6) = 52.0 -> MEDIUM
    r = agent.assess(HazardType.SMOKE, confidence=0.6, persistence_frames=5)
    assert r.score == pytest.approx(52.0)
    assert r.severity == Severity.MEDIUM


@pytest.mark.parametrize("conf,frames,mult", [(-1, -10, -5), (5, 10_000, 50), (0, 0, 0), (1, 15, 1)])
def test_score_always_within_0_and_100(agent, conf, frames, mult):
    r = agent.assess(HazardType.FIRE, conf, frames, context_multiplier=mult)
    assert 0.0 <= r.score <= 100.0


def test_weights_are_normalised():
    a = RiskAssessmentAgent(RiskConfig(4, 3, 3, 15, FACTORS))  # same ratios, different scale
    b = RiskAssessmentAgent(RiskConfig(0.4, 0.3, 0.3, 15, FACTORS))
    assert a.assess(HazardType.FIRE, 0.7, 9).score == b.assess(HazardType.FIRE, 0.7, 9).score
    assert sum(a.config.normalised_weights) == pytest.approx(1.0)


@pytest.mark.parametrize("score,expected", [
    (0, Severity.LOW), (30, Severity.LOW), (30.1, Severity.MEDIUM), (55, Severity.MEDIUM),
    (55.1, Severity.HIGH), (75, Severity.HIGH), (75.1, Severity.CRITICAL), (100, Severity.CRITICAL),
])
def test_severity_band_boundaries(agent, score, expected):
    assert agent.severity_for_score(score) == expected


def test_custom_bands():
    agent = RiskAssessmentAgent(RiskConfig(1, 1, 1, 10, FACTORS, band_low_max=10, band_medium_max=20, band_high_max=30))
    assert agent.severity_for_score(25) == Severity.HIGH
    assert agent.severity_for_score(31) == Severity.CRITICAL


def test_context_multiplier_raises_severity_component(agent):
    base = agent.assess(HazardType.SMOKE, 0.6, 5)
    boosted = agent.assess(HazardType.SMOKE, 0.6, 5, context_multiplier=1.5)
    assert boosted.score > base.score
    assert boosted.severity_component == pytest.approx(0.9)


def test_unknown_factor_falls_back_to_default():
    agent = RiskAssessmentAgent(RiskConfig(0, 0, 1, 10, {}))
    assert agent.assess(HazardType.FIRE, 1, 10).score == pytest.approx(100 * RiskAssessmentAgent.DEFAULT_FACTOR)


@pytest.mark.parametrize("kwargs", [
    dict(weight_confidence=0, weight_persistence=0, weight_severity=0),
    dict(weight_confidence=-1),
    dict(band_low_max=60, band_medium_max=50),
    dict(persistence_saturation_frames=0),
    dict(severity_factors={HazardType.FIRE: 1.5}),
])
def test_invalid_config_rejected(kwargs):
    with pytest.raises(ValueError):
        RiskConfig(**kwargs)


def test_from_settings(settings):
    cfg = RiskConfig.from_settings(settings)
    assert cfg.severity_factors[HazardType.FIRE] == settings.hazard_severity_factors["FIRE"]
    assert cfg.band_high_max == settings.severity_band_high_max


def test_explain_mentions_components(agent):
    text = agent.assess(HazardType.FIRE, 0.8, 15).explain()
    assert "risk=89.0" in text and "CRITICAL" in text
