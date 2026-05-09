"""
Smart heating AppDeamon application.
"""

import datetime
from typing import Any, Optional

from appdaemon_common import HealthAppBase, init_step

from sh_config import ConfigMixin
from sh_hal import HalMixin
from sh_logic import LogicMixin
from sh_logging import LoggingMixin
from sh_mqtt import MqttClimateMixin


__author__ = "Arkaqius"
"""
Offset smaller than 0 -> smaller flow
Offset bigger than 0 -> bigger flow
"""


class SmartHeating(
    HealthAppBase, ConfigMixin, HalMixin, LogicMixin, LoggingMixin, MqttClimateMixin
):
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
    @init_step("config", order=10)
    def init_config_step(self) -> None:
        """Load config and publish its hash to the health entity."""
        self.init_config()
        self.update_health_attrs(config_hash=self.compute_config_hash(self.args))

    @init_step("runtime_state", order=20)
    def init_runtime_state_step(self) -> None:
        """Initialize internal runtime fields."""
        self.initialize_internal_fields()

    @init_step("mqtt_entities", order=30)
    def init_mqtt_entities_step(self) -> None:
        """Initialize app-owned MQTT entities."""
        self.init_mqtt_climates()

    @init_step("main_loop", order=40)
    def init_main_loop_step(self) -> None:
        """Start the main SmartHeating loop."""
        self.start_main_loop()

    @init_step("listeners", order=50)
    def init_listeners_step(self) -> None:
        """Register Home Assistant and MQTT listeners."""
        self.setup_state_listeners()

    @init_step("heartbeat", order=60)
    def init_heartbeat_step(self) -> None:
        """Start standardized AppDaemon common heartbeat."""
        self.start_heartbeat(self.heartbeat_s)

    @init_step("logging", order=70)
    def init_logging_step(self) -> None:
        """Log startup details after all init steps have completed."""
        self.log_debug("Initialization finished")
        self.log_config()

    def start_main_loop(self) -> None:
        """Starts the main loop for the app based on cycle time."""
        start_time = self.datetime() + datetime.timedelta(seconds=self.cycle_time)
        self.schedule_every("main_loop", start_time, self.cycle_time, self.sh_main_loop)

    def setup_state_listeners(self) -> None:
        """Set up state listeners for all setpoints."""
        self.setup_mqtt_climate_listeners()

        flag_entities = [
            self.HAL_frezzing_flag,
        ]
        for flag_entity in flag_entities:
            if flag_entity:
                self.listen_state_named(
                    f"flag_{flag_entity}", self.flag_update, flag_entity
                )

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
        self.last_forced_burn_offset: Optional[float] = None
        self.last_forced_burn_active = False
        self.last_force_flow_safety_active = False
        self.last_safety_room_error: Optional[float] = None
        self.last_loop_end: Optional[datetime.datetime] = None
        self.last_loop_duration: Optional[float] = None
        self.room_setpoints: dict[str, float] = {}
        self.room_hvac_modes: dict[str, str] = {}
        self.control_flags: dict[str, bool] = {}
        self.mqtt_plugin_api = None
        self.mqtt_command_topics: dict[str, tuple[str, str]] = {}
        self.mqtt_control_command_topics: dict[str, str] = {}
        self.mqtt_climate_rooms = {}

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
            self.publish_all_mqtt_climate_states()
        except Exception as e:
            self.handle_hw_error(
                f"Error in main loop: {str(e)}"
            )  # HW error, safe state
        finally:
            end_time = self.datetime()
            try:
                self.last_loop_end = end_time
                self.last_loop_duration = (end_time - start_time).total_seconds()
                self.publish_mqtt_diagnostic_states()
                self.update_health_attrs(
                    last_loop_end=end_time.isoformat(),
                    last_loop_duration_s=round(self.last_loop_duration, 3),
                    last_output_offset=self.last_output_offset,
                    last_output_setpoint=self.last_output_setpoint,
                    last_output_reasons=(
                        ",".join(self.last_output_reasons)
                        if self.last_output_reasons
                        else "none"
                    ),
                )
            except Exception as e:
                self.log(
                    f"Failed to record or publish loop diagnostics: {e}",
                    level="ERROR",
                )

    def collect_system_values(self) -> None:
        """Collect necessary current values of the system parameters."""
        self.thermostat_setpoint = self.sh_get_thermostat_setpoint()
        self.corridor_setpoint: float = self.sh_get_corridor_setpoint()
        self.corridor_temperature: float = self.sh_get_room_temperature("corridor")
        self.wam_errors: list[float] = self.sh_get_wam_errors()
        self.rads_error: list[float] = self.sh_get_rad_errors()
        self.warm_flag: bool = self.sh_get_warm_flag()
        self.freezing_flag: bool = self.sh_get_freezing_flag()
        self.force_flow_flag: bool = self.sh_get_force_flow_flag()
        self.radiator_positions: list[float] = self.sh_get_radiator_postions()

    # endregion

    # region ErrorHandling
    def handle_hw_error(self, message: str) -> None:
        """
        Handle system/hardware errors by logging the error and entering a safe state.

        Parameters:
            message (str): Custom error message to be logged.
        """
        self.log(f"HW ERROR: {message}", level="ERROR")
        self.enter_safe_state(message, stop_timers=True, stop_listeners=True)

    def on_enter_safe_state(self) -> None:
        """Publish the latest diagnostics when the app enters safe state."""
        self.publish_mqtt_diagnostic_states()

    def heartbeat_message(self) -> Optional[str]:
        """Return SmartHeating-specific heartbeat details for appdaemon_common."""
        if self.last_loop_end is None:
            return "last_loop=none"
        duration = (
            round(self.last_loop_duration, 3)
            if self.last_loop_duration is not None
            else "n/a"
        )
        reasons = (
            ",".join(self.last_output_reasons) if self.last_output_reasons else "none"
        )
        return (
            f"last_offset={self.last_output_offset}, "
            f"last_setpoint={self.last_output_setpoint}, "
            f"last_reasons={reasons}, "
            f"loop_duration_s={duration}"
        )

    # endregion
