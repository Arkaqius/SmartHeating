"""Compatible active entry point; deploy only during the controlled takeover."""

from smartheating.appdaemon_app import SmartHeating as _SmartHeating


class SmartHeating(_SmartHeating):
    """AppDaemon discovers classes declared in the configured entry module."""
