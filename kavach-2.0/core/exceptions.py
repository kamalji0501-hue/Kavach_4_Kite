"""
Batman v3 — Exception hierarchy.

Every exception inherits from BatmanError so callers can catch broadly
or narrowly as needed.
"""


class BatmanError(Exception):
    """Base exception for all Batman system errors."""


# ── Broker ───────────────────────────────────────────────────


class BrokerAuthError(BatmanError):
    """Authentication / token failure."""


class BrokerConnectionError(BatmanError):
    """Broker unreachable or disconnected."""


class OrderPlacementError(BatmanError):
    """Order could not be placed."""


class OrderCancelError(BatmanError):
    """Order could not be cancelled."""


class PositionError(BatmanError):
    """Position query or close failed."""


# ── Config & State ───────────────────────────────────────────


class ConfigError(BatmanError):
    """Invalid or missing configuration."""


class StateError(BatmanError):
    """State load / save failure."""


# ── Module ───────────────────────────────────────────────────


class ModuleError(BatmanError):
    """A module failed to start or execute."""


class ModuleDisabledError(ModuleError):
    """Attempted operation on a disabled module."""
