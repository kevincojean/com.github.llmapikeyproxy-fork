# SPDX-License-Identifier: LGPL-3.0-only
# Copyright (c) 2026 Kevin Cojean

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Dict, Optional, Tuple

lib_logger = logging.getLogger("rotator_library")

EXTRA_BODY = "extra_body"
THINKING = "thinking"
REASONING_EFFORT = "reasoning_effort"
TYPE = "type"


class ThinkingControl(StrEnum):
    TOGGLE = "toggle"
    EFFORT = "effort"
    TOGGLE_AND_EFFORT = "both"
    ALWAYS_ON = "always_on"
    UNKNOWN = "unknown"


class ThinkingIntent(StrEnum):
    UNSET = "unset"
    ENABLED = "enabled"
    DISABLED = "disabled"


class ReasoningLevel(StrEnum):
    UNSET = "unset"
    OFF = "off"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    MAX = "max"


LEVEL_ORDER: Tuple[ReasoningLevel, ...] = (
    ReasoningLevel.OFF,
    ReasoningLevel.LOW,
    ReasoningLevel.MEDIUM,
    ReasoningLevel.HIGH,
    ReasoningLevel.MAX,
)

LEVEL_BY_NAME = {
    ReasoningLevel.OFF.value: ReasoningLevel.OFF,
    ReasoningLevel.LOW.value: ReasoningLevel.LOW,
    ReasoningLevel.MEDIUM.value: ReasoningLevel.MEDIUM,
    ReasoningLevel.HIGH.value: ReasoningLevel.HIGH,
    ReasoningLevel.MAX.value: ReasoningLevel.MAX,
}

OFF_ALIASES = frozenset({"none", "disable", "disabled", "off", "no_think"})

NO_THINK = "no_think"
NO_NEED = "none"


@dataclass(frozen=True)
class ThinkingCapability:
    control: ThinkingControl
    levels: Tuple[ReasoningLevel, ...] = ()
    off_value: Optional[str] = None

    def __post_init__(self) -> None:
        for level in self.levels:
            if level not in LEVEL_ORDER:
                raise ValueError(f"invalid thinking level: {level!r}")
        if self.control in (
            ThinkingControl.TOGGLE,
            ThinkingControl.ALWAYS_ON,
            ThinkingControl.UNKNOWN,
        ) and (self.levels or self.off_value is not None):
            raise ValueError(
                f"{self.control.value} control does not take levels or off_value"
            )
        if (
            ReasoningLevel.OFF in self.levels
            and self.off_value is None
            and self.control not in TOGGLE_CONTROLS
        ):
            raise ValueError("OFF level requires an off_value or a toggle control")


UNKNOWN_CAPABILITY = ThinkingCapability(ThinkingControl.UNKNOWN)

TOGGLE_CONTROLS = frozenset({ThinkingControl.TOGGLE, ThinkingControl.TOGGLE_AND_EFFORT})

FAMILIES: Dict[str, ThinkingCapability] = {
    "mimo-": ThinkingCapability(ThinkingControl.TOGGLE),
    "hy3": ThinkingCapability(
        ThinkingControl.EFFORT,
        (ReasoningLevel.OFF, ReasoningLevel.LOW, ReasoningLevel.HIGH),
        NO_THINK,
    ),
    "hy4": ThinkingCapability(
        ThinkingControl.EFFORT,
        (ReasoningLevel.OFF, ReasoningLevel.LOW, ReasoningLevel.HIGH),
        NO_THINK,
    ),
    "deepseek-v4": ThinkingCapability(
        ThinkingControl.TOGGLE_AND_EFFORT,
        (
            ReasoningLevel.OFF,
            ReasoningLevel.LOW,
            ReasoningLevel.HIGH,
            ReasoningLevel.MAX,
        ),
    ),
    "kimi": ThinkingCapability(ThinkingControl.ALWAYS_ON),
    "moonshot": ThinkingCapability(ThinkingControl.ALWAYS_ON),
    "qwen3.7-plus": ThinkingCapability(ThinkingControl.TOGGLE),
    "qwen3.8-flash": ThinkingCapability(ThinkingControl.TOGGLE),
    "qwen3.8-max": ThinkingCapability(ThinkingControl.TOGGLE),
    "glm-5.2": ThinkingCapability(
        ThinkingControl.EFFORT, (ReasoningLevel.HIGH, ReasoningLevel.MAX)
    ),
    "glm-5.3": ThinkingCapability(
        ThinkingControl.EFFORT, (ReasoningLevel.HIGH, ReasoningLevel.MAX)
    ),
    "gpt-6-luna": ThinkingCapability(
        ThinkingControl.EFFORT,
        (
            ReasoningLevel.OFF,
            ReasoningLevel.LOW,
            ReasoningLevel.MEDIUM,
            ReasoningLevel.HIGH,
            ReasoningLevel.MAX,
        ),
        NO_NEED,
    ),
    "gpt-5.6-luna": ThinkingCapability(
        ThinkingControl.EFFORT,
        (
            ReasoningLevel.OFF,
            ReasoningLevel.LOW,
            ReasoningLevel.MEDIUM,
            ReasoningLevel.HIGH,
            ReasoningLevel.MAX,
        ),
        NO_NEED,
    ),
}


def capability_for(model: str) -> ThinkingCapability:
    bare = model.split("/", 1)[1] if "/" in model else model
    bare = bare.lower()
    for prefix, capability in FAMILIES.items():
        if bare.startswith(prefix):
            return capability
    return UNKNOWN_CAPABILITY


def capability_from_plugin(plugin: Any, model: str) -> Optional[ThinkingCapability]:
    hook = getattr(plugin, "get_thinking_capability", None) if plugin else None
    if hook is None:
        return None
    try:
        capability = hook(model)
    except Exception as exc:
        lib_logger.debug(f"thinking capability hook failed for {model}: {exc}")
        return None
    if not isinstance(capability, ThinkingCapability):
        lib_logger.debug(
            f"thinking capability hook for {model} returned {capability!r}; ignoring"
        )
        return None
    return capability


def read_intent(value: Any) -> ThinkingIntent:
    if isinstance(value, dict):
        value = value.get(TYPE)
    if not isinstance(value, str):
        return ThinkingIntent.UNSET
    normalized = value.strip().lower()
    if normalized in OFF_ALIASES:
        return ThinkingIntent.DISABLED
    try:
        return ThinkingIntent(normalized)
    except ValueError:
        lib_logger.debug(f"unknown thinking value {value!r}, ignoring")
        return ThinkingIntent.UNSET


def read_level(value: Any) -> ReasoningLevel:
    if not isinstance(value, str):
        return ReasoningLevel.UNSET
    normalized = value.strip().lower()
    if normalized in OFF_ALIASES:
        return ReasoningLevel.OFF
    return LEVEL_BY_NAME.get(normalized, ReasoningLevel.UNSET)


def clamp_level(level: ReasoningLevel, capability: ThinkingCapability) -> ReasoningLevel:
    if level is ReasoningLevel.UNSET or level in capability.levels:
        return level
    allowed = [LEVEL_ORDER.index(c) for c in capability.levels]
    if not allowed:
        return ReasoningLevel.UNSET
    rank = LEVEL_ORDER.index(level)
    at_or_above = [candidate for candidate in allowed if candidate >= rank]
    target = min(at_or_above) if at_or_above else max(allowed)
    return LEVEL_ORDER[target]


def resolve_intent_and_level(
    kwargs: Dict[str, Any], capability: ThinkingCapability, model: str
) -> Tuple[ThinkingIntent, ReasoningLevel]:
    extra = kwargs.get(EXTRA_BODY)
    extra_in = extra if isinstance(extra, dict) else {}

    intent = read_intent(
        extra_in[THINKING] if THINKING in extra_in else kwargs.get(THINKING)
    )
    level = read_level(
        extra_in[REASONING_EFFORT]
        if REASONING_EFFORT in extra_in
        else kwargs.get(REASONING_EFFORT)
    )

    has_toggle = capability.control in TOGGLE_CONTROLS
    wants_off = intent is ThinkingIntent.DISABLED or level is ReasoningLevel.OFF

    if wants_off:
        if capability.off_value is not None:
            intent = ThinkingIntent.UNSET
            level = ReasoningLevel.OFF
        elif has_toggle:
            intent = ThinkingIntent.DISABLED
            level = ReasoningLevel.UNSET
        else:
            intent = ThinkingIntent.UNSET
            level = ReasoningLevel.UNSET
            lib_logger.debug(f"dropping off request for {model}: no off switch")
    else:
        level = clamp_level(level, capability)
        if capability.control is ThinkingControl.TOGGLE:
            level = ReasoningLevel.UNSET
        elif capability.control is ThinkingControl.EFFORT:
            intent = ThinkingIntent.UNSET
        elif capability.control is ThinkingControl.ALWAYS_ON:
            intent = ThinkingIntent.UNSET
            level = ReasoningLevel.UNSET

    return intent, level


def serialize_level(
    level: ReasoningLevel, capability: ThinkingCapability
) -> Optional[str]:
    if level is ReasoningLevel.UNSET:
        return None
    if level is ReasoningLevel.OFF:
        return capability.off_value
    return level.value


def normalize_thinking(
    kwargs: Dict[str, Any], model: str, capability: ThinkingCapability
) -> Dict[str, Any]:
    if capability.control is ThinkingControl.UNKNOWN:
        result = dict(kwargs)
    else:
        intent, level = resolve_intent_and_level(kwargs, capability, model)
        extra = kwargs.get(EXTRA_BODY)
        extra_out = dict(extra) if isinstance(extra, dict) else {}
        extra_out.pop(THINKING, None)
        extra_out.pop(REASONING_EFFORT, None)

        if intent is not ThinkingIntent.UNSET:
            extra_out[THINKING] = {TYPE: intent.value}
        level_value = serialize_level(level, capability)
        if level_value is not None:
            extra_out[REASONING_EFFORT] = level_value

        result = {**kwargs}
        result.pop(THINKING, None)
        result.pop(REASONING_EFFORT, None)
        if extra_out:
            result[EXTRA_BODY] = extra_out
        else:
            result.pop(EXTRA_BODY, None)

    return result
