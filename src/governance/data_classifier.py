"""Data Classifier — rule-based PII and credential detection.

Phase 1: Pattern matching for common PII types.
Phase 2: Integration with Presidio or similar.

See docs/architecture/09-governance.md.
"""

from __future__ import annotations

import re
from typing import Any

from src.core.enums import DataSensitivity

# Patterns for common PII/credential types
_PATTERNS: list[tuple[str, re.Pattern, DataSensitivity]] = [
    ("email", re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"), DataSensitivity.CONFIDENTIAL),
    ("api_key", re.compile(r"(?:sk|pk|api)[-_][a-zA-Z0-9]{20,}"), DataSensitivity.RESTRICTED),
    ("bearer_token", re.compile(r"Bearer\s+[a-zA-Z0-9\-._~+/]+=*"), DataSensitivity.RESTRICTED),
    ("credit_card", re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"), DataSensitivity.RESTRICTED),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), DataSensitivity.RESTRICTED),
    ("phone", re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"), DataSensitivity.CONFIDENTIAL),
    ("aws_key", re.compile(r"AKIA[0-9A-Z]{16}"), DataSensitivity.RESTRICTED),
    ("password_field", re.compile(r"(?i)(?:password|passwd|secret)\s*[:=]\s*\S+"), DataSensitivity.RESTRICTED),
]


class ClassificationResult:
    """Result of data classification."""

    def __init__(
        self,
        sensitivity: DataSensitivity = DataSensitivity.PUBLIC,
        tags: list[str] | None = None,
        matches: list[dict[str, Any]] | None = None,
    ):
        self.sensitivity = sensitivity
        self.tags = tags or []
        self.matches = matches or []

    @property
    def has_sensitive_data(self) -> bool:
        return self.sensitivity in (DataSensitivity.CONFIDENTIAL, DataSensitivity.RESTRICTED)


class DataClassifier:
    """Rule-based data classification for PII/credential detection."""

    def classify(self, text: str) -> ClassificationResult:
        """Classify text for sensitive data."""
        if not text:
            return ClassificationResult()

        tags: list[str] = []
        matches: list[dict[str, Any]] = []
        max_sensitivity = DataSensitivity.PUBLIC

        sensitivity_order = {
            DataSensitivity.PUBLIC: 0,
            DataSensitivity.INTERNAL: 1,
            DataSensitivity.CONFIDENTIAL: 2,
            DataSensitivity.RESTRICTED: 3,
        }

        for name, pattern, sensitivity in _PATTERNS:
            found = pattern.findall(text)
            if found:
                tags.append(name)
                matches.append({"type": name, "count": len(found)})
                if sensitivity_order.get(sensitivity, 0) > sensitivity_order.get(max_sensitivity, 0):
                    max_sensitivity = sensitivity

        return ClassificationResult(
            sensitivity=max_sensitivity,
            tags=tags,
            matches=matches,
        )
