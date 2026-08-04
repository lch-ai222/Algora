"""Failure-mode detectors: signals the pass/fail oracle cannot see."""

from codeagent_eval.detectors.context_amnesia import (
    CHECKERS,
    AmnesiaReport,
    UnknownChecker,
    detect_context_amnesia,
    edits_from_trace,
)
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
    "CHECKERS",
    "AmnesiaReport",
    "ConstraintBreach",
    "DriftReport",
    "Evidence",
    "RewardHackReport",
    "Signal",
    "UnknownChecker",
    "detect_context_amnesia",
    "detect_instruction_drift",
    "detect_reward_hacking",
    "edits_from_trace",
    "parse_unified_diff",
]
