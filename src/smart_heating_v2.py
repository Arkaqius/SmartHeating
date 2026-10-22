"""Separate module name lets v2 shadow coexist with the deployed legacy module."""

from smartheating.appdaemon_app import SmartHeating as _SmartHeating


class SmartHeating(_SmartHeating):
    """Observation entry class declared locally for the AppDaemon loader."""
