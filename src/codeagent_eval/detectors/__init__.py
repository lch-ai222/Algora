"""Failure-mode detectors: signals the pass/fail oracle cannot see."""

from codeagent_eval.detectors.reward_hacking import (
    Evidence,
    RewardHackReport,
    Signal,
    detect_reward_hacking,
    parse_unified_diff,
)

__all__ = [
    "Evidence",
    "RewardHackReport",
    "Signal",
    "detect_reward_hacking",
    "parse_unified_diff",
]
