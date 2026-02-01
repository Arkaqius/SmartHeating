"""
Logging helpers for SmartHeating.
"""

from typing import Any


class LoggingMixin:
    """
    Mixin providing logging helpers and summary output.
    """

    def log_debug(self, message: str) -> None:
        """
        Log debug messages using AppDaemon's logging API.

        Args:
            message (str): Message to log.
        """
        self.log(message, level="DEBUG")

    def log_input_variables(self) -> None:
        """
        Log important variables for debugging purposes. Handle errors in logging (HW Error).
        """
        variables = [
            "thermostat_setpoint",
            "corridor_setpoint",
            "wam_errors",
            "rads_error",
            "warm_flag",
            "freezing_flag",
            "force_flow_flag",
            "radiator_positions",
        ]

        for var in variables:
            try:
                self.log_debug(f"Variable: {var}: {getattr(self, var)}")
            except AttributeError:
                self.log(f"Variable {var} not found!", level="ERROR")
            except Exception as e:
                self.log(
                    f"An error occurred while logging {var}: {str(e)}", level="ERROR"
                )

    def log_main_output(
        self,
        offset: float,
        new_setpoint: float,
        setpoint_updated: bool,
        reasons: list[str],
    ) -> None:
        """
        Log a single INFO summary when outputs change to reduce log noise.
        """
        offset_changed = self.previous_offset is None or offset != self.previous_offset
        setpoint_changed = setpoint_updated and (
            self.previous_thermostat_setpoint is None
            or new_setpoint != self.previous_thermostat_setpoint
        )
        if offset_changed or setpoint_changed:
            max_rads_error = (
                max(self.rads_error) if isinstance(self.rads_error, list) else None
            )
            reason_text = ",".join(reasons) if reasons else "none"
            self.log(
                "Loop output updated: "
                f"offset={offset}, thermostat_setpoint={new_setpoint}, "
                f"reason={reason_text}, corridor_setpoint={self.corridor_setpoint}, "
                f"wam={self.last_wam}, max_rads_error={max_rads_error}, "
                f"force_flow_flag={self.force_flow_flag}",
                level="INFO",
            )
            self.previous_offset = offset
            if setpoint_updated:
                self.previous_thermostat_setpoint = new_setpoint

    def log_heartbeat(self, kwargs: dict[str, Any]) -> None:
        """
        Periodic health log to confirm the app is alive.
        """
        if self.last_loop_end is None:
            age_text = "n/a"
        else:
            age_text = round(
                (self.datetime() - self.last_loop_end).total_seconds(), 1
            )
        duration_text = (
            round(self.last_loop_duration, 3)
            if self.last_loop_duration is not None
            else "n/a"
        )
        self.log(
            "Heartbeat: "
            f"last_offset={self.last_output_offset}, "
            f"last_setpoint={self.last_output_setpoint}, "
            f"last_reasons={','.join(self.last_output_reasons) if self.last_output_reasons else 'none'}, "
            f"loop_age_s={age_text}, loop_duration_s={duration_text}",
            level="INFO",
        )

    def flag_update(
        self, entity: str, attribute: str, old: str, new: str, kwargs: dict[str, Any]
    ) -> None:
        """
        Log transitions for key control flags.
        """
        if old in (None, "unknown", "unavailable") and new in (
            None,
            "unknown",
            "unavailable",
        ):
            return
        if old != new:
            self.log(f"Flag changed: {entity} {old} -> {new}", level="INFO")
