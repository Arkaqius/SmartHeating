"""
Configuration parsing and validation for SmartHeating.
"""

from enum import Enum
from typing import Any, Optional

from sh_types import ROOM_INDEX_FH, ROOM_INDEX_RAD


class ConfigMixin:
    """
    Mixin that provides configuration parsing and validation helpers.
    """

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
