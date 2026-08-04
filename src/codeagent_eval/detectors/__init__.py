"""Failure-mode detectors: signals the pass/fail oracle cannot see."""

from codeagent_eval.detectors.instruction_drift import (
    ConstraintBreach,
    DriftReport,
    detect_instruction_drift,
)
from codeagent_eval.detectors.reward_hacking import (
    Evidence,
    RewardHackReport,
    Signal,
    detect_reward_hacking,
    parse_unified_diff,
)

__all__ = [
    "ConstraintBreach",
    "DriftReport",
    "Evidence",
    "RewardHackReport",
    "Signal",
    "detect_instruction_drift",
    "detect_reward_hacking",
    "parse_unified_diff",
]
