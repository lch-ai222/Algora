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
from codeagent_eval.detectors.repro_bundle import (
    BUNDLE_SCHEMA,
    ReplayResult,
    ReproBundleError,
    build_repro_bundle,
    grade_signature,
    replay_repro_bundle,
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
    "ReplayResult",
    "ReproBundleError",
    "Signal",
    "UnknownChecker",
    "detect_context_amnesia",
    "detect_instruction_drift",
    "detect_reward_hacking",
    "edits_from_trace",
    "BUNDLE_SCHEMA",
    "build_repro_bundle",
    "grade_signature",
    "parse_unified_diff",
    "replay_repro_bundle",
]
