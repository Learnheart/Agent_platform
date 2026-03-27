"""Injection Detector — prompt injection detection (Soft Guardrail).

Phase 1: Heuristic-only detection using pattern matching.
Phase 2: Will add classifier model.

See docs/architecture/07-guardrails.md Section Inbound.
"""

from __future__ import annotations

import re
import time

from src.guardrails.models import DetectionResult

# Heuristic patterns that indicate prompt injection attempts
_INJECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("role_override", re.compile(
        r"(?i)(ignore|disregard|forget)\s+(all\s+)?(previous|above|prior|earlier)\s+(instructions?|prompts?|rules?|constraints?)",
    )),
    ("system_impersonation", re.compile(
        r"(?i)(you\s+are\s+now|act\s+as|pretend\s+(to\s+be|you\s+are)|new\s+instructions?:)",
    )),
    ("delimiter_escape", re.compile(
        r"(?i)(```\s*system|<\|im_start\|>|<\|system\|>|\[INST\]|\[\/INST\]|<<SYS>>)",
    )),
    ("instruction_injection", re.compile(
        r"(?i)(ignore\s+the\s+above|override\s+(the\s+)?system|do\s+not\s+follow\s+(any|the)\s+rules)",
    )),
    ("jailbreak", re.compile(
        r"(?i)(DAN\s+mode|developer\s+mode|jailbreak|bypass\s+filter|ignore\s+safety)",
    )),
    ("output_manipulation", re.compile(
        r"(?i)(print\s+the\s+(system\s+)?prompt|reveal\s+your\s+instructions|show\s+me\s+your\s+(system\s+)?prompt)",
    )),
]


class InjectionDetector:
    """Detects prompt injection using heuristic pattern matching.

    Phase 1: Pattern-based detection. Fail-open (soft guardrail)
    with best-effort detection.
    """

    def detect(self, user_input: str, system_prompt: str = "") -> DetectionResult:
        """Check user input for injection patterns.

        Returns:
            DetectionResult with is_injection=True if patterns are found.
        """
        start = time.monotonic()

        for strategy_name, pattern in _INJECTION_PATTERNS:
            match = pattern.search(user_input)
            if match:
                latency = (time.monotonic() - start) * 1000
                return DetectionResult(
                    is_injection=True,
                    confidence=0.8,
                    strategy_triggered=strategy_name,
                    details=f"Matched pattern: {match.group()[:100]}",
                    latency_ms=latency,
                )

        # Check for structural delimiter manipulation
        delimiter_result = self._check_delimiters(user_input, system_prompt)
        if delimiter_result:
            delimiter_result.latency_ms = (time.monotonic() - start) * 1000
            return delimiter_result

        latency = (time.monotonic() - start) * 1000
        return DetectionResult(
            is_injection=False,
            confidence=0.0,
            latency_ms=latency,
        )

    def _check_delimiters(self, user_input: str, system_prompt: str) -> DetectionResult | None:
        """Detect structural manipulation via delimiters."""
        # Check if user input contains common system prompt markers
        suspicious_markers = [
            "###SYSTEM###",
            "---SYSTEM---",
            "[SYSTEM]:",
            "SYSTEM_PROMPT:",
        ]
        input_upper = user_input.upper()
        for marker in suspicious_markers:
            if marker in input_upper:
                return DetectionResult(
                    is_injection=True,
                    confidence=0.7,
                    strategy_triggered="delimiter_analysis",
                    details=f"Suspicious delimiter found: {marker}",
                )
        return None
