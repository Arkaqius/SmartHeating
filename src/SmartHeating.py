"""
Smart heating AppDeamon application.
"""

import datetime
import traceback
from typing import Any, Optional

import appdaemon.plugins.hass.hassapi as hass

from sh_config import ConfigMixin
from sh_hal import HalMixin
from sh_logic import LogicMixin
from sh_logging import LoggingMixin
from sh_ww import TemporaryWarmWater


__author__ = "Arkaqius"
"""
Offset smaller than 0 -> smaller flow
Offset bigger than 0 -> bigger flow
"""


class SmartHeating(hass.Hass, ConfigMixin, HalMixin, LogicMixin, LoggingMixin):
    """
    SmartHeating - An AppDaemon app for intelligent heating control.

    The SmartHeating class is designed to optimize and control heating elements
    across various zones/rooms in a home automation setup using Home Assistant.
    This app utilizes the AppDaemon framework to interact with Home Assistant,
    enabling the orchestration of various entities and automations for a
    smart heating solution.

    Note: Ensure that the relevant Home Assistant entities (sensors,
          climate entities, etc.) are configured and working properly for
          effective use of this app.
    """

    # region AppDeamon functions
    def initialize(self) -> None:
        """
        Initialize the app, set up the main loop, and define state callbacks.

        - Loads config.
        - Starts the main loop.
        - Initializes state listeners and internal fields.
        """
        try:
            # Load config
            self.init_config()

            # Initialize internal fields
            self.initialize_internal_fields()

            # Initialize the app main loop
            self.start_main_loop()

            # Initialize heartbeat logging
            self.start_heartbeat()

            # Initialize state listeners
            self.setup_state_listeners()

            # Initialize TemporaryWarmWater
            self.temporary_ww = TemporaryWarmWater(self)
            self.temporary_ww.initialize()

            # Log initialization completion
            self.log_debug("Initialization finished")
            self.log_config()

        except Exception as e:
            self.handle_sw_error(
                "Error during initialization", e
            )  # SW error, stop the app

    def start_main_loop(self) -> None:
        """Starts the main loop for the app based on cycle time."""
        start_time = self.datetime() + datetime.timedelta(seconds=self.cycle_time)
        self.handle = self.run_every(self.sh_main_loop, start_time, self.cycle_time)

    def start_heartbeat(self) -> None:
        """Starts a periodic heartbeat log to confirm the app is healthy."""
        interval = 30 * 60
        start_time = self.datetime() + datetime.timedelta(seconds=interval)
        self.heartbeat_handle = self.run_every(self.log_heartbeat, start_time, interval)

    def setup_state_listeners(self) -> None:
        """Set up state listeners for all setpoints."""
        setpoint_mappings = [
            (self.HAL_garage_setpoint_in, [self.HAL_garage_setpoint_out]),
            (
                self.HAL_bedroom_setpoint_in,
                [
                    self.HAL_bedroom_left_setpoint_out,
                    self.HAL_bedroom_right_setpoint_out,
                ],
            ),
            (self.HAL_kidsroom_setpoint_in, [self.HAL_kidsroom_setpoint_out]),
            (self.HAL_office_setpoint_in, [self.HAL_office_setpoint_out]),
        ]

        for input_setpoint, output_setpoints in setpoint_mappings:
            self.listen_state(
                self.setpoint_update, input_setpoint, devices=output_setpoints
            )

        flag_entities = [
            self.HAL_makeWarm_flag,
            self.HAL_frezzing_flag,
            self.HAL_forceFlow_flag,
        ]
        for flag_entity in flag_entities:
            self.listen_state(self.flag_update, flag_entity)

    def initialize_internal_fields(self) -> None:
        """Initialize the internal state variables for the app."""
        self.thermostat_error = None
        self.wam_errors = None
        self.rads_error = None
        self.warm_flag = None
        self.freezing_flag = None
        self.force_flow_flag = None
        self.radiator_positions = None
        self.previous_offset: Optional[float] = None
        self.previous_thermostat_setpoint: Optional[float] = None
        self.last_output_offset: Optional[float] = None
        self.last_output_setpoint: Optional[float] = None
        self.last_output_reasons: list[str] = []
        self.last_wam: Optional[float] = None
        self.last_loop_end: Optional[datetime.datetime] = None
        self.last_loop_duration: Optional[float] = None
        self.heartbeat_handle = None

    def setpoint_update(
        self,
        entity: Any,
        attribute: Any,
        old: Any,
        new: Any,
        kwargs: dict[str, Any],
    ) -> None:
        """
        Update setpoint values upon state change.

        Parameters:
        - entity (Any): Entity id that triggered the callback.
        - attribute (Any): Attribute name (unused).
        - old (Any): Previous state value.
        - new (Any): The new state of the entity.
        - kwargs (dict[str, Any]): Additional arguments, expects 'devices'.

        Returns:
        None
        """
        self.log_debug(
            f"Setpoint update entity:{entity} attr:{attribute} old:{old} new:{new} kvargs:{kwargs}"
        )
        if new in (None, "unknown", "unavailable"):
            self.log(
                f"Setpoint update ignored due to invalid state for {entity}: {new}",
                level="ERROR",
            )
            return

        try:
            new_value = float(new)
        except (TypeError, ValueError) as e:
            self.log(
                f"Setpoint update ignored due to non-numeric state for {entity} '{new}': {e}",
                level="ERROR",
            )
            return

        devices = kwargs.get("devices", [])
        if not devices:
            self.log("Setpoint update missing target devices.", level="ERROR")
            return
        # Check if the device is a TRV and update the temperature
        for device in devices:
            self.call_service(
                "climate/set_temperature", entity_id=device, temperature=new_value
            )

    def sh_main_loop(self, _: Any) -> None:
        """
        Main smart heating event loop which orchestrates the logic for managing the heating system.

        This function manages various system flags, calculates offsets using system parameters,
        and ensures optimal performance and safety of the heating system.

        Args:
            _ (Any): Scheduler callback argument (unused).

        Returns:
            None
        """
        start_time = self.datetime()
        try:
            off_final = 0

            # Collect current system values
            self.collect_system_values()
            self.log_input_variables()

            # Apply various adjustments to the offset
            off_final, reasons = self.calculate_final_offset(off_final)
            off_final_rounded = round(off_final, 1)

            # Update TRVs and thermostat offset
            self.sh_update_TRVs()
            new_setpoint, setpoint_updated = self.sh_update_thermostat(
                off_final_rounded
            )
            self.last_output_offset = off_final_rounded
            self.last_output_setpoint = new_setpoint
            self.log_main_output(
                off_final_rounded, new_setpoint, setpoint_updated, reasons
            )
        except Exception as e:
            self.handle_hw_error(
                f"Error in main loop: {str(e)}"
            )  # HW error, safe state
        finally:
            end_time = self.datetime()
            try:
                self.last_loop_end = end_time
                self.last_loop_duration = (end_time - start_time).total_seconds()
            except Exception as e:
                self.log(f"Failed to record loop timing: {e}", level="ERROR")

    def collect_system_values(self) -> None:
        """Collect necessary current values of the system parameters."""
        self.thermostat_setpoint = self.sh_get_thermostat_setpoint()
        self.corridor_setpoint: float = self.sh_get_corridor_setpoint()
        self.wam_errors: list[float] = self.sh_get_wam_errors()
        self.rads_error: list[float] = self.sh_get_rad_errors()
        self.warm_flag: bool = self.sh_get_warm_flag()
        self.freezing_flag: bool = self.sh_get_freezing_flag()
        self.force_flow_flag: bool = self.sh_get_force_flow_flag()
        self.radiator_positions: list[float] = self.sh_get_radiator_postions()

    # endregion

    # region ErrorHandling
    def handle_sw_error(self, message: str, exception: Exception) -> None:
        """
        Handle software errors by logging the exception and stopping the app.

        Parameters:
            message (str): Custom error message to be logged.
            exception (Exception): The raised exception object.

        Raises:
            Exception: Re-raises the exception to fault hard.
        """
        self.log(
            f"SW ERROR: {message}: {str(exception)}\n{traceback.format_exc()}",
            level="ERROR",
        )
        raise exception

    def handle_hw_error(self, message: str) -> None:
        """
        Handle system/hardware errors by logging the error and entering a safe state.

        Parameters:
            message (str): Custom error message to be logged.
        """
        self.log(f"HW ERROR: {message}", level="ERROR")
        self.enter_safe_state()

    def enter_safe_state(self) -> None:
        """
        Placeholder method to enter a safe state.
        Add logic here to stop critical processes and prevent damage.
        """
        # Stop the main loop to prevent repeated faulty actions.
        try:
            if hasattr(self, "handle") and self.handle:
                self.cancel_timer(self.handle)
                self.handle = None
                self.log("Safe state: main loop timer cancelled.", level="ERROR")
            if hasattr(self, "heartbeat_handle") and self.heartbeat_handle:
                self.cancel_timer(self.heartbeat_handle)
                self.heartbeat_handle = None
                self.log("Safe state: heartbeat timer cancelled.", level="ERROR")
        except Exception as e:
            self.log(f"Safe state: failed to cancel timer: {e}", level="ERROR")

    # endregion
