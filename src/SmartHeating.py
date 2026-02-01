"""
Smart heating AppDeamon application.
"""

import datetime
import traceback
from typing import Any, Optional
from math import nan
from enum import Enum
import appdaemon.plugins.hass.hassapi as hass


__author__ = "Arkaqius"
"""
Offset smaller than 0 -> smaller flow
Offset bigger than 0 -> bigger flow
"""

# DEFAULT VALUES FOR FLOAT()
DEFAULT_COR_TERROR = 0.0
DEFAULT_RAD_POS = 50.0
DEFAULT_WAM_ERROR = 0.0
DEAFULT_RAD_ERR = 0.0


# region Enumerations
class ROOM_INDEX_FH(Enum):
    """
    Floor heating room index enumeration.
    """

    LIVINGROOM = 0
    CORRIDOR = 1
    BATHROOM = 2
    ENTRANCE = 3
    UPPER_CORRIDOR = 4
    WARDROBE = 5
    UPPER_BATHROOM = 6


class ROOM_INDEX_RAD(Enum):
    """
    Radaitor heating room index enumeration.
    """

    OFFICE = 0
    KIDSROOM = 1
    BEDROOM = 2
    GARAGE = 3


class TRV_INDEX(Enum):
    """
    TRV valves index enumeration.
    """

    OFFICE = 0
    KIDSROOM = 1
    BEDROOM_LEFT = 2
    BEDROOM_RIGHT = 3
    GARAGE = 4


# endregion


class SmartHeating(hass.Hass):
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

    # region Cfg init functions
    def init_config(self) -> None:
        """
        Load and set up configuration from provided args.
        Extracts parameters and HALs from `args` for application use.
        """
        # Load config values using helper method
        self.cycle_time = self.get_config_value(
            "cycle_time", section="config", default=60
        )
        self.warm_flag_offset = self.get_config_value(
            "warm_flag_offset", section="config", default=0
        )
        self.frezzying_flag_offset = self.get_config_value(
            "frezzing_flag_offset",
            section="config",
            default=0,
            aliases=["freezing_flag_offset"],
        )
        self.error_offset_update_threshold = self.get_config_value(
            "error_offset_update_threshold", section="config", default=0.5
        )
        self.force_flow_offset = self.get_config_value(
            "force_flow_off",
            section="config",
            default=0,
            aliases=["force_flow_offset"],
        )
        self.radiator_boost_threshold = self.get_config_value(
            "radiator_boost_threshold", section="config", default=0
        )
        self.rads_error_factor = self.get_config_value(
            "rads_error_factor", section="config", default=1
        )
        self.force_burn_thres = self.get_config_value(
            "force_burn_thres", section="config", default=0
        )

        # Load factor parameters
        self.wam_params: list[float] = self.init_wam_params()
        self.rads_params: list[float] = self.init_rads_params()

        # Load HAL mappings using helper methods
        self.load_hal_mappings(
            "HAL_setpoint_mapping_in",
            [
                ("office_setpoint", "HAL_office_setpoint_in"),
                ("kidsroom_setpoint", "HAL_kidsroom_setpoint_in"),
                ("bedroom_setpoint", "HAL_bedroom_setpoint_in"),
                ("garage_setpoint", "HAL_garage_setpoint_in"),
            ],
        )

        self.load_hal_mappings(
            "HAL_setpoint_mapping_out",
            [
                ("office_setpoint", "HAL_office_setpoint_out"),
                ("kidsroom_setpoint", "HAL_kidsroom_setpoint_out"),
                ("bedroom_left_setpoint", "HAL_bedroom_left_setpoint_out"),
                ("bedroom_right_setpoint", "HAL_bedroom_right_setpoint_out"),
                ("garage_setpoint", "HAL_garage_setpoint_out"),
            ],
        )

        self.load_hal_mappings(
            "HAL_TRV_pos",
            [
                ("garage_pos", "HAL_TRV_garage_pos"),
                ("bedroomLeft_pos", "HAL_TRV_bedroom_left_pos"),
                ("bedroomRight_pos", "HAL_TRV_bedroom_right_pos"),
                ("office_pos", "HAL_TRV_office_pos"),
                ("kidsRoom_pos", "HAL_TRV_kidsroom_pos"),
            ],
        )

        self.load_hal_mappings(
            "HAL_errors",
            [
                ("livingRoom_error", "HAL_livingroom_tError"),
                ("corridor_error", "HAL_corridor_tError"),
                ("bathroom_error", "HAL_bathroom_tError"),
                ("entrance_error", "HAL_entrance_tError"),
                ("uppercorridor_error", "HAL_upper_corridor_tError"),
                ("wardrobe_error", "HAL_wardrobe_tError"),
                ("upperbathroom_error", "HAL_upper_bathroom_tError"),
                ("office_error", "HAL_office_tError"),
                ("kidsroom_error", "HAL_kidsroom_tError"),
                ("garage_error", "HAL_garage_tError"),
                ("bedroom_error", "HAL_bedroom_tError"),
            ],
        )

        self.load_hal_mappings(
            "HAL_inputs",
            [
                ("makeWarm_flag", "HAL_makeWarm_flag"),
                ("frezzing_flag", "HAL_frezzing_flag"),
                ("forceFlow_flag", "HAL_forceFlow_flag"),
                ("corridor_setpoint", "HAL_corridor_setpoint"),
            ],
        )

        self.load_hal_mappings(
            "HAL_output",
            [
                ("wam_value", "HAL_wam_value"),
                ("setpoint_offset", "HAL_setpoint_offset"),
                ("thermostat_setpoint", "HAL_thermostat_setpoint"),
            ],
        )

    def get_config_value(
        self,
        key: str,
        section: str,
        default: Any = None,
        aliases: Optional[list[str]] = None,
    ) -> Any:
        """
        Helper to fetch config values with a default fallback.

        Args:
            key (str): Config key to read from args.
            section (str): Config section within args.
            default (Any): Fallback value when the key is missing.

        Returns:
            Any: The resolved config value or the default.
        """
        section_data = self.args.get(section, {})
        if key in section_data:
            return section_data[key]

        if aliases:
            for alias in aliases:
                if alias in section_data:
                    self.log(
                        f"Config key '{section}.{alias}' is deprecated or misspelled; use '{section}.{key}'.",
                        level="ERROR",
                    )
                    return section_data[alias]

        if default is not None:
            self.log(
                f"Config missing: '{section}.{key}'. Using default {default}.",
                level="ERROR",
            )
            return default

        raise KeyError(f"Missing config key '{section}.{key}'")

    def handle_config_error(self, error: Exception) -> None:
        """
        Handle configuration error by logging and stopping the app.

        Args:
            error (Exception): Exception raised while reading config.
        """
        self.log(f"Configuration Error: {str(error)}", level="ERROR")
        self.stop_app("HeaterController")
        raise error

    def load_hal_mappings(
        self, section: str, mappings: list[tuple[str, str]], required: bool = True
    ) -> None:
        """
        Helper to load HAL mappings from args into class attributes.

        Args:
            section (str): Args section containing the mappings.
            mappings (list[tuple[str, str]]): (key, attribute_name) pairs to load.
        """
        missing: list[str] = []
        section_data = self.args.get(section, {})
        for key, attribute in mappings:
            value = section_data.get(key)
            if required and value in (None, ""):
                missing.append(f"{section}.{key}")
            setattr(self, attribute, value)

        if missing:
            self.handle_config_error(KeyError(", ".join(missing)))

    def log_config(self) -> None:
        """
        Log the active configuration values for debugging.
        """
        config_items: list[str] = [
            "cycle_time",
            "warm_flag_offset",
            "frezzying_flag_offset",
            "error_offset_update_threshold",
            "force_flow_offset",
            "radiator_boost_threshold",
            "rads_error_factor",
            "force_burn_thres",
        ]

        for item in config_items:
            self.log_debug(f"Config: {item}: {getattr(self, item)}")

    def init_wam_params(self) -> list[float]:
        """
        Initialize Weighted Average Method (WAM) parameters by normalizing the WAM factors.

        Returns:
        List[float]: Normalized WAM factors for the floor heating rooms.
        """
        wam_params: list[float] = self.init_params_from_args(
            "wam_factors", ROOM_INDEX_FH
        )
        return wam_params

    def init_rads_params(self) -> list[float]:
        """
        Initialize radiator factors by normalizing the radiator factors.

        Returns:
        List[float]: Normalized radiator factors.
        """
        rads_params: list[float] = self.init_params_from_args(
            "rads_factors", ROOM_INDEX_RAD
        )
        return rads_params

    def init_params_from_args(
        self, factor_key: str, room_index_enum: type[Enum]
    ) -> list[float]:
        """
        Generic method to initialize normalized factors from the args.

        Parameters:
        - factor_key (str): The key in the args dictionary to retrieve factors.
        - room_index_enum (type[Enum]): Enum class defining room indices.

        Returns:
        List[float]: A list of normalized factors.
        """
        factor_data = self.args.get(factor_key)
        if not isinstance(factor_data, dict) or not factor_data:
            self.handle_config_error(KeyError(factor_key))

        # Calculate the sum of all factor values
        try:
            factors_sum: float = sum(float(v) for v in factor_data.values())
        except (TypeError, ValueError) as e:
            self.handle_config_error(ValueError(f"Invalid factor in '{factor_key}': {e}"))

        if factors_sum <= 0:
            self.handle_config_error(
                ValueError(f"Sum of factors in '{factor_key}' must be > 0")
            )

        # Get the total number of rooms based on the size of the enum
        num_rooms = len(list(room_index_enum))

        # Initialize list with zeroes based on the number of rooms
        params = [0] * num_rooms

        # Loop over the enum values to populate the params list with normalized values
        for room in room_index_enum:
            key = room.name.lower()
            if key not in factor_data:
                self.handle_config_error(
                    KeyError(f"Missing factor '{factor_key}.{key}'")
                )
            try:
                params[room.value] = float(factor_data[key]) / factors_sum
            except (TypeError, ValueError) as e:
                self.handle_config_error(
                    ValueError(f"Invalid factor '{factor_key}.{key}': {e}")
                )

        return params

    # endregion

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

    def calculate_final_offset(self, off_final: float) -> tuple[float, list[str]]:
        """
        Calculate the final offset using different system parameters. Handle HW errors.

        Args:
            off_final (float): Current offset value before adjustments.

        Returns:
            tuple[float, list[str]]: Updated offset and list of reasons applied.
        """
        reasons: list[str] = []
        # Apply WAM errors
        before = off_final
        off_final = self.sh_apply_wam_voting(off_final)
        if off_final != before:
            reasons.append("wam")
        self.log_debug(f"Offset after WAM: {off_final}")

        # Apply warm flag
        before = off_final
        off_final = self.sh_apply_warm_flag(off_final)
        if off_final != before:
            reasons.append("warm_flag")
        self.log_debug(f"Offset after warm flag: {off_final}")

        # Apply weather forecast
        before = off_final
        off_final = self.sh_apply_weather_forecast(off_final)
        if off_final != before:
            reasons.append("freezing_flag")
        self.log_debug(f"Offset after weather forecast: {off_final}")

        # Check forced burn
        before = off_final
        off_final = self.sh_check_forced_burn(off_final)
        if off_final != before:
            reasons.append("forced_burn")
        self.log_debug(f"Offset after forced burn check: {off_final}")

        # Check force flow for safety priority
        before = off_final
        off_final = self.sh_force_flow_for_safety_prio(off_final)
        if off_final != before:
            reasons.append("force_flow")
        self.log_debug(
            f"Offset after force flow for safety priority: {off_final}"
        )
        self.last_output_reasons = reasons
        return off_final, reasons

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

    # endregion

    # region SmartHeating logic functions
    def sh_force_flow_for_safety_prio(self, off_final: float) -> float:
        """
        Ensure safety priority by enforcing flow if necessary, based on radiator errors and flag state.

        Parameters:
            off_final (float): Current offset value before safety adjustments.

        Returns:
            float: Returns the force_flow_offset if conditions are met, otherwise off_final.
        """
        self.log_debug(
            f"self.rads_error[ROOM_INDEX_RAD.BEDROOM.value]:{self.rads_error[ROOM_INDEX_RAD.BEDROOM.value]}"
        )
        if self.rads_error[ROOM_INDEX_RAD.BEDROOM.value] > 0:
            self.log_debug(f"self.force_flow_flag:{self.force_flow_flag}")
            if self.force_flow_flag:
                return self.force_flow_offset
        return off_final

    def sh_check_forced_burn(self, off_final: float) -> float:
        """
        Check and apply forced burn based on corridor error, final offset and radiator errors.

        Parameters:
            off_final (float): Offset final value.

        Returns:
            float: Calculated forced burn value or 0 if conditions are not met.
        """
        # Check if any radiator error exceeds the threshold
        if (self.wam_errors[ROOM_INDEX_FH.CORRIDOR.value] + off_final) < 0 and any(
            a > self.force_burn_thres for a in self.rads_error
        ):
            # Multiply each radiator error by its corresponding factor from self.rads_factors
            modified_rads_error: list[float] = [
                r_error * self.rads_params[i]
                for i, r_error in enumerate(self.rads_error)
            ]

            # Calculate the addition to the final offset based on the modified radiator errors
            forced_burn = (
                sum(max(a, 0) for a in modified_rads_error) * self.rads_error_factor
            )
            self.log_debug(f"Forced_burn {forced_burn} ")
            return off_final + forced_burn  # Add the forced burn to the final offset
        else:
            return off_final  # Conditions not met, return the original offset

    def sh_apply_warm_flag(self, off_final: float) -> float:
        """
        Apply warm flag and retrieve updated offset.

        Parameters:
            off_final (float): Initial offset.

        Returns:
            float: Updated offset after applying warm flag.
        """
        # Check warm in flag and get offset
        ret_offset: float = off_final + self.sh_get_offset_warm_flag()
        return ret_offset

    def sh_apply_weather_forecast(self, off_final: float) -> float:
        """
        Apply weather forecast data (freezing flag) and get updated offset.

        Parameters:
            off_final (float): Initial offset.

        Returns:
            float: Updated offset after considering freezing flag.
        """
        # Check freezing forecast
        ret_offset: float = off_final + self.sh_get_offset_frezzing_flag()
        return ret_offset

    def sh_apply_wam_voting(self, off_final: float) -> float:
        """
        Apply Weighted Arithmetic Mean (WAM) voting and get updated offset.

        Parameters:
            off_final (float): Initial offset.

        Returns:
            float: Updated offset after applying WAM voting.
        """
        # Calculate WAM
        wam: float = round(self.sh_wam(self.wam_errors, self.wam_params), 2)
        if wam != wam:
            self.log(
                "WAM calculation returned NaN. Check factor configuration and inputs.",
                level="ERROR",
            )
            self.handle_hw_error("WAM calculation returned NaN.")
            return off_final
        self.last_wam = wam
        self.sh_set_internal_wam_value(wam)
        return off_final + wam

    def sh_update_TRVs(self) -> None:
        """Update TRVs based on errors and radiator positions."""
        trv_mappings = {
            ROOM_INDEX_RAD.OFFICE: TRV_INDEX.OFFICE,
            ROOM_INDEX_RAD.KIDSROOM: TRV_INDEX.KIDSROOM,
            ROOM_INDEX_RAD.BEDROOM: (TRV_INDEX.BEDROOM_LEFT, TRV_INDEX.BEDROOM_RIGHT),
            ROOM_INDEX_RAD.GARAGE: TRV_INDEX.GARAGE,
        }

        for room, trv in trv_mappings.items():
            if isinstance(trv, tuple):  # For multiple TRVs like bedroom
                self.update_multiple_trvs(room, trv)
            else:
                self.update_trv(room, trv)

    def update_trv(self, room: ROOM_INDEX_RAD, trv: TRV_INDEX) -> None:
        """
        Update a single TRV based on room error and position.

        Args:
            room (ROOM_INDEX_RAD): Room identifier for the radiator error lookup.
            trv (TRV_INDEX): TRV valve identifier to update.
        """
        if (
            self.rads_error[room.value] > 0.5
            and self.radiator_positions[trv.value] < self.radiator_boost_threshold
        ):
            self.call_service(
                "climate/set_preset_mode",
                entity_id=f"climate.{trv.name.lower()}_TRV",
                preset_mode="boost",
            )
            self.log_debug(f"Forcing boost for {trv.name.lower()}")

    def update_multiple_trvs(
        self, room: ROOM_INDEX_RAD, trvs: tuple[TRV_INDEX, TRV_INDEX]
    ) -> None:
        """
        Update multiple TRVs (like bedroom with left and right TRVs).

        Args:
            room (ROOM_INDEX_RAD): Room identifier for the radiator error lookup.
            trvs (tuple[TRV_INDEX, TRV_INDEX]): TRV valves to update.
        """
        for trv in trvs:
            self.update_trv(room, trv)

    def sh_update_thermostat(self, off_final: float) -> tuple[float, bool]:
        """
        Update the thermostat setpoint based on the corridor setpoint and a provided offset,
        if the difference between the current thermostat setpoint and the new one is greater than
        the predefined update threshold.

        Parameters:
            off_final (float): The offset to be added to the corridor setpoint to calculate the new thermostat setpoint.

        Returns:
            tuple[float, bool]: The calculated thermostat setpoint and whether it was updated.
        """
        self.sh_set_internal_setpoint_offset(off_final)
        new_thermostat_setpoint: float = (
            self.corridor_setpoint - self.wam_errors[ROOM_INDEX_FH.CORRIDOR.value]
        ) + off_final
        self.log_debug(
            f"Updating thermostat,\n\tcorridor_t {(self.corridor_setpoint - self.wam_errors[ROOM_INDEX_FH.CORRIDOR.value])}\n\tcorridor_setpoint {self.corridor_setpoint}\n\toff_final: {off_final}\n\tthermostat_setpoint: {self.thermostat_setpoint}\n\tnew_thermostat_setpoint: {new_thermostat_setpoint}"
        )
        # Check if error is higher that update threshold
        if (
            abs(self.thermostat_setpoint - new_thermostat_setpoint)
            >= self.error_offset_update_threshold
        ):
            self.sh_set_thermostat_setpoint(new_thermostat_setpoint)
            return new_thermostat_setpoint, True
        return new_thermostat_setpoint, False

    def sh_get_radiator_postions(self) -> list[float]:
        """Retrieve the position values of different radiators from the HAL."""
        return [
            self.sh_get_value(
                getattr(self, f"HAL_TRV_{trv.name.lower()}_pos"), DEFAULT_RAD_POS
            )
            for trv in TRV_INDEX
        ]

    def sh_wam(self, temperatures: list[float], weights: list[float]) -> float:
        """
        Calculate the weighted arithmetic mean of temperatures.

        Parameters:
            temperatures (List[float]): A list of temperature values.
            weights (List[float]): A list of weights corresponding to the temperature values.

        Returns:
            float: The calculated weighted arithmetic mean of temperatures.
                    Returns NaN if the lengths of temperatures and weights do not match.
        """
        if len(temperatures) != len(weights):
            return nan

        total_weighted_temp: float = sum(
            temp * weight for temp, weight in zip(temperatures, weights)
        )
        return total_weighted_temp / sum(weights)

    def sh_get_wam_errors(self) -> list[float]:
        """
        Retrieve thermostat errors for different rooms from the HAL and return them as a list.

        Returns:
            List[float]: A list of thermostat errors corresponding to different rooms.
        """
        return [
            self.sh_get_value(
                getattr(self, f"HAL_{room.name.lower()}_tError"), DEFAULT_WAM_ERROR
            )
            for room in ROOM_INDEX_FH
        ]

    def sh_get_rad_errors(self) -> list[float]:
        """
        Retrieve radiator errors for different rooms from the HAL and return them as a list.

        Returns:
            List[float]: A list of radiator errors corresponding to different rooms.
        """
        return [
            self.sh_get_value(
                getattr(self, f"HAL_{room.name.lower()}_tError"), DEAFULT_RAD_ERR
            )
            for room in ROOM_INDEX_RAD
        ]

    # endregion

    # region HAL opaque functions

    def sh_get_value(self, hal_entity: str, default_value: float = 0.0) -> float:
        """
        Generic method to retrieve a state value from the HAL and safely convert it to float.

        Parameters:
            hal_entity (str): The entity ID for the state in the HAL.
            default_value (float): The default value to return if the state is None or conversion fails.

        Returns:
            float: The state value as a float or the default value if conversion fails.
        """
        if not hal_entity:
            self.log("HAL entity is missing for value lookup.", level="ERROR")
            self.handle_hw_error("HAL entity missing for value lookup.")
            return default_value
        state = self.get_state(hal_entity)
        if state in (None, "unknown", "unavailable"):
            self.log(
                f"HAL state invalid for '{hal_entity}': {state}",
                level="ERROR",
            )
            return default_value
        return self.safe_float_convert(state, default_value)

    def sh_get_flag_value(self, flag_entity: str) -> bool:
        """
        Retrieve a boolean flag from the HAL.

        Parameters:
            flag_entity (str): The entity ID for the flag in the HAL.

        Returns:
            bool: True if the flag is 'on', False otherwise.
        """
        if not flag_entity:
            self.log("HAL entity is missing for flag lookup.", level="ERROR")
            self.handle_hw_error("HAL entity missing for flag lookup.")
            return False
        state = self.get_state(flag_entity)
        if state in (None, "unknown", "unavailable"):
            self.log(
                f"HAL state invalid for '{flag_entity}': {state}",
                level="ERROR",
            )
            return False
        return state == "on"

    def sh_get_offset_flag(self, flag_entity: str, offset_value: int) -> int:
        """
        Retrieve the offset for a flag.

        Parameters:
            flag_entity (str): The entity ID for the flag in the HAL.
            offset_value (int): The offset value to return if the flag is 'on'.

        Returns:
            int: The offset if the flag is 'on', otherwise 0.
        """
        return offset_value if self.sh_get_flag_value(flag_entity) else 0

    def sh_set_value(
        self, entity: str, value: float, min_value: Optional[float] = None
    ) -> None:
        """
        Generic method to set a value in the HAL.

        Parameters:
            entity (str): The entity ID in the HAL.
            value (float): The value to set.
            min_value (float, optional): If provided, ensures the value is at least this value.
        """
        if not entity:
            self.log("HAL entity is missing for set operation.", level="ERROR")
            self.handle_hw_error("HAL entity missing for set operation.")
            return

        if min_value is not None:
            value = max(min_value, value)

        domain = entity.split(".")[0] if "." in entity else ""
        if domain == "input_number":
            self.call_service("input_number/set_value", entity_id=entity, value=value)
        elif domain == "number":
            self.call_service("number/set_value", entity_id=entity, value=value)
        else:
            self.log(
                f"Unsupported entity domain for set_value: '{entity}'",
                level="ERROR",
            )
            self.handle_hw_error(f"Unsupported entity domain for set_value: '{entity}'")

    def sh_get_offset_frezzing_flag(self) -> int:
        """Get the offset for the freezing flag."""
        return self.sh_get_offset_flag(
            self.HAL_frezzing_flag, self.frezzying_flag_offset
        )

    def sh_get_offset_warm_flag(self) -> int:
        """Get the offset for the warm flag."""
        return self.sh_get_offset_flag(self.HAL_makeWarm_flag, self.warm_flag_offset)

    def sh_get_corridor_setpoint(self) -> float:
        """Retrieve the corridor setpoint from the HAL."""
        return self.sh_get_value(self.HAL_corridor_setpoint)

    def sh_get_thermostat_setpoint(self) -> float:
        """Retrieve the corridor setpoint from the HAL."""
        return self.sh_get_value(self.HAL_thermostat_setpoint)

    def sh_set_thermostat_setpoint(self, value: float) -> None:
        """
        Set a new thermostat setpoint in the HAL, ensuring it is at least 15.0.

        Args:
            value (float): Desired thermostat setpoint value.
        """
        self.sh_set_value(self.HAL_thermostat_setpoint, value, min_value=15.0)

    def sh_set_internal_wam_value(self, value: float) -> None:
        """
        Set the internal WAM value in the HAL.

        Args:
            value (float): WAM value to persist.
        """
        self.sh_set_value(self.HAL_wam_value, value)

    def sh_set_internal_setpoint_offset(self, value: float) -> None:
        """
        Set the internal setpoint offset in the HAL.

        Args:
            value (float): Setpoint offset to persist.
        """
        self.sh_set_value(self.HAL_setpoint_offset, value)

    def sh_get_freezing_flag(self) -> bool:
        """Retrieve the state of the freezing flag."""
        return self.sh_get_flag_value(self.HAL_frezzing_flag)

    def sh_get_warm_flag(self) -> bool:
        """Retrieve the state of the warm flag."""
        return self.sh_get_flag_value(self.HAL_makeWarm_flag)

    def sh_get_force_flow_flag(self) -> bool:
        """Retrieve the state of the force flow flag."""
        return self.sh_get_flag_value(self.HAL_forceFlow_flag)

    # endregion

    # region utilites
    def log_debug(self, message: str) -> None:
        """
        Log debug messages using AppDaemon's logging API.

        Args:
            message (str): Message to log.
        """
        self.log(message, level="DEBUG")

    def safe_float_convert(self, value: Any, default: Optional[float] = None) -> float:
        """
        Attempts to convert a string to a float. If the conversion fails,
        logs a warning and returns a default value, or raises a hardware error if no valid default is provided.

        Args:
            value (Any): The value to be converted to float.
            default (float, optional): The default value to return in case of conversion failure. If None is passed,
                hardware error is raised.

        Returns:
            float: The converted float value or the default value if conversion fails.
        """
        try:
            return float(value)
        except (TypeError, ValueError) as e:
            if default is not None:
                self.log(
                    f"Conversion warning: Could not convert '{value}' to float. Returning default value {default}: {str(e)}",
                    level="WARNING",
                )
                return default
            else:
                self.log(
                    f"Conversion error: Could not convert '{value}' to float: {str(e)}",
                    level="ERROR",
                )
                self.handle_hw_error(
                    f"Failed to convert value '{value}' to float, no valid default provided. Raising hardware fault."
                )
                raise ValueError(
                    f"Failed to convert '{value}' to float, no valid default provided."
                )

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


class TemporaryWarmWater:
    """
    TemporaryWarmWater - Handles warm water activation using an input_boolean.
    """

    def __init__(self, hass_instance: hass.Hass) -> None:
        """
        Initialize the class with the AppDaemon hass instance.

        Args:
            hass_instance (hass.Hass): Main AppDaemon instance to call services.
        """
        self.hass = hass_instance
        self.timer_handle: Optional[Any] = None  # Handle for managing the timer

    def initialize(self) -> None:
        """
        Setup the input_boolean entity and add state listeners.
        """
        # Initialize input_boolean with attributes
        self.hass.set_state(
            "input_boolean.temporary_ww",
            state="off",
            attributes={
                "friendly_name": "Temporary Warm Water",
                "icon": "mdi:water-boiler",
                "description": "Enables warm water for 15 minutes.",
            },
        )

        # Listen for state changes
        self.hass.listen_state(
            self.handle_input_boolean_change, "input_boolean.temporary_ww"
        )
        self.hass.log(
            "TemporaryWarmWater initialized with input_boolean.", level="INFO"
        )

    def handle_input_boolean_change(
        self,
        entity: str,
        attribute: str,
        old: str,
        new: str,
        kwargs: dict[str, Any],
    ) -> None:
        """
        Handle state changes of input_boolean.temporary_ww:
        - Turn ON warm water for 15 minutes if set to 'on'.
        - Turn OFF warm water immediately if set to 'off'.

        Args:
            entity (str): Entity id that triggered the callback.
            attribute (str): Attribute that changed.
            old (str): Previous state value.
            new (str): New state value.
            kwargs (dict[str, Any]): Callback keyword arguments.
        """
        if old == "off" and new == "on":
            self.hass.log(
                "Input_boolean ON: Enabling warm water for 15 minutes.", level="INFO"
            )

            # Turn on warm water
            self.hass.call_service(
                "input_boolean/turn_on", entity_id="input_boolean.ww_state"
            )

            # Start a 15-minute timer
            if self.timer_handle:
                self.hass.cancel_timer(self.timer_handle)  # Cancel existing timer
            self.timer_handle = self.hass.run_in(self.turn_off_warm_water, 15 * 60)

        elif old == "on" and new == "off":
            self.hass.log(
                "Input_boolean OFF: Turning off warm water immediately.", level="INFO"
            )

            # Cancel timer if running
            if self.timer_handle:
                self.hass.cancel_timer(self.timer_handle)
                self.timer_handle = None

            # Turn off warm water
            self.turn_off_warm_water({})

    def turn_off_warm_water(self, kwargs: dict[str, Any]) -> None:
        """
        Turn off the warm water state.

        Args:
            kwargs (dict[str, Any]): Callback keyword arguments (unused).
        """
        self.hass.call_service(
            "input_boolean/turn_off", entity_id="input_boolean.ww_state"
        )
        self.hass.log("Warm water turned off.", level="INFO")
