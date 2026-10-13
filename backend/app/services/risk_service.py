"""Risk Assessment Agent.

Conceptual model (prototype design, not an experimentally validated predictor)::

    Risk = 100 × (w_c·C + w_p·P + w_s·S)

    C = mean detection confidence of the event          (0..1)
    P = min(1, persistence_frames / saturation_frames)  (0..1)
    S = hazard severity factor × context multiplier     (0..1, clamped)
    w_* = configured weights, normalised to sum to 1

The score is therefore always in 0..100. Severity bands (default 30/55/75)
map the score to LOW/MEDIUM/HIGH/CRITICAL:

    score <= low_max      -> LOW
    score <= medium_max   -> MEDIUM
    score <= high_max     -> HIGH
    otherwise             -> CRITICAL
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from backend.app.core.enums import HazardType, Severity


def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else float(x)


@dataclass(frozen=True)
class RiskConfig:
    weight_confidence: float = 0.4
    weight_persistence: float = 0.3
    weight_severity: float = 0.3
    persistence_saturation_frames: int = 15
    severity_factors: Mapping[HazardType, float] = field(default_factory=dict)
    band_low_max: float = 30
    band_medium_max: float = 55
    band_high_max: float = 75

    def __post_init__(self) -> None:
        weights = (self.weight_confidence, self.weight_persistence, self.weight_severity)
        if any(w < 0 for w in weights) or sum(weights) <= 0:
            raise ValueError("risk weights must be non-negative and not all zero")
        if self.persistence_saturation_frames < 1:
            raise ValueError("persistence_saturation_frames must be >= 1")
        if not (0 <= self.band_low_max < self.band_medium_max < self.band_high_max <= 100):
            raise ValueError("bands must satisfy 0 <= low < medium < high <= 100")
        for hazard, f in self.severity_factors.items():
            if not 0 <= f <= 1:
                raise ValueError(f"severity factor for {hazard} must be within 0..1")

    @property
    def normalised_weights(self) -> tuple[float, float, float]:
        total = self.weight_confidence + self.weight_persistence + self.weight_severity
        return (self.weight_confidence / total, self.weight_persistence / total, self.weight_severity / total)

    @classmethod
    def from_settings(cls, settings) -> "RiskConfig":
        return cls(
            weight_confidence=settings.risk_weight_confidence,
            weight_persistence=settings.risk_weight_persistence,
            weight_severity=settings.risk_weight_severity,
            persistence_saturation_frames=settings.persistence_saturation_frames,
            severity_factors={HazardType(k): float(v) for k, v in settings.hazard_severity_factors.items()},
            band_low_max=settings.severity_band_low_max,
            band_medium_max=settings.severity_band_medium_max,
            band_high_max=settings.severity_band_high_max,
        )


@dataclass(frozen=True)
class RiskAssessment:
    score: float
    severity: Severity
    confidence_component: float
    persistence_component: float
    severity_component: float
    weights: tuple[float, float, float]

    def explain(self) -> str:
        wc, wp, ws = self.weights
        return (
            f"risk={self.score:.1f} ({self.severity.value}) = 100 x ({wc:.2f}x{self.confidence_component:.2f} conf"
            f" + {wp:.2f}x{self.persistence_component:.2f} persistence"
            f" + {ws:.2f}x{self.severity_component:.2f} hazard factor)"
        )


class RiskAssessmentAgent:
    DEFAULT_FACTOR = 0.5

    def __init__(self, config: RiskConfig):
        self.config = config

    def severity_for_score(self, score: float) -> Severity:
        c = self.config
        if score <= c.band_low_max:
            return Severity.LOW
        if score <= c.band_medium_max:
            return Severity.MEDIUM
        if score <= c.band_high_max:
            return Severity.HIGH
        return Severity.CRITICAL

    def assess(self, hazard_type: HazardType, confidence: float, persistence_frames: int,
               context_multiplier: float = 1.0) -> RiskAssessment:
        """``context_multiplier`` lets a deployment weight e.g. a fuel depot above a car park."""
        c = _clamp01(confidence)
        p = _clamp01(persistence_frames / self.config.persistence_saturation_frames)
        factor = self.config.severity_factors.get(HazardType(hazard_type), self.DEFAULT_FACTOR)
        s = _clamp01(factor * max(0.0, context_multiplier))
        wc, wp, ws = self.config.normalised_weights
        score = round(max(0.0, min(100.0, 100.0 * (wc * c + wp * p + ws * s))), 1)
        return RiskAssessment(score, self.severity_for_score(score), round(c, 4), round(p, 4), round(s, 4), (wc, wp, ws))
