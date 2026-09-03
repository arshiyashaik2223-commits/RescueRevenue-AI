"""
app/ml/model_infer.py
Recovery-probability inference.

v1 implementation: a hand-tuned logistic-style heuristic over the
feature_engineering.py feature set — NOT a trained sklearn artifact.
This keeps scoring functional and swappable without requiring a
training dataset before the product can be demoed end-to-end. Swap
this out for a joblib-loaded model (see app/ml/model_train.py,
optional/non-MVP) once historical outcome data exists to train on.
"""
import logging
import math

logger = logging.getLogger(__name__)

_MODEL_VERSION = "heuristic_v1.0"

# Weights are hand-tuned, not learned — documented here for transparency
# since this is the piece most likely to be replaced by a trained model.
_REASON_BASE_RATE = {
    "insufficient_funds": 0.35,
    "card_expired": 0.55,
    "bank_declined": 0.30,
    "risk_blocked": 0.10,
    "timeout": 0.60,
    "other": 0.30,
}


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def _logit(p: float) -> float:
    p = min(max(p, 0.001), 0.999)
    return math.log(p / (1 - p))


async def predict(features: dict) -> tuple[float, str]:
    """
    Returns (recovery_score in [0,1], model_version string).
    Declared async so this can be swapped for a remote/async model-
    serving call later without changing every call site.
    """
    base = _REASON_BASE_RATE.get(features.get("failure_reason_category"), 0.3)

    success_ratio = features.get("customer_past_success_ratio", 0.5)
    hours_since_failure = features.get("hours_since_failure", 0)
    prior_retry_count = features.get("prior_retry_count", 0)
    amount_relative = features.get("amount_relative_to_avg", 1.0)

    # Linear combination fed through a sigmoid to keep the result in
    # (0, 1) regardless of how extreme any single feature value is.
    logit = (
        _logit(base)
        + 1.2 * (success_ratio - 0.5)
        - 0.02 * min(hours_since_failure, 72)  # recovery odds decay with time
        - 0.15 * prior_retry_count  # each failed retry lowers odds
        - 0.3 * max(0.0, amount_relative - 1.5)  # unusually large amounts recover less
    )
    score = round(_sigmoid(logit), 4)
    score = min(max(score, 0.01), 0.99)  # never return a hard 0 or 1

    return score, _MODEL_VERSION
