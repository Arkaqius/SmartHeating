"""
Configuration parsing and validation for SmartHeating.
"""

from enum import Enum
from typing import Any, Optional

from sh_types import DEFAULT_ROOM_SETPOINT, ROOM_INDEX_FH, ROOM_INDEX_RAD


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
        self.heartbeat_s = int(
            self.get_config_value("heartbeat_s", section="config", default=1800)
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

        # Load mandatory room inputs and generated MQTT climate configuration.
        self.init_room_config()
        self.init_mqtt_climate_config()
        self.init_trv_climate_config()

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
            "HAL_inputs",
            [
                ("frezzing_flag", "HAL_frezzing_flag"),
            ],
            required=False,
        )

        self.load_hal_mappings(
            "HAL_output",
            [
                ("thermostat_setpoint", "HAL_thermostat_setpoint"),
            ],
        )

    def init_room_config(self) -> None:
        """
        Load mandatory raw room temperature inputs for managed climates.
        """
        self.floor_room_names = [room.name.lower() for room in ROOM_INDEX_FH]
        self.radiator_room_names = [room.name.lower() for room in ROOM_INDEX_RAD]
        self.room_names = self.floor_room_names + self.radiator_room_names
        self.room_temperature_entities: dict[str, str] = {}
        self.room_friendly_names: dict[str, str] = {}
        self.room_default_setpoints: dict[str, float] = {}

        temperature_data = self.args.get("HAL_room_temperatures")
        if not isinstance(temperature_data, dict) or not temperature_data:
            self.handle_config_error(KeyError("HAL_room_temperatures"))

        missing: list[str] = []
        for room in self.room_names:
            value = self.get_room_mapping_value(
                temperature_data, room, ("temperature", "temp")
            )
            if value in (None, ""):
                missing.append(room)
            else:
                self.room_temperature_entities[room] = value
        if missing:
            self.handle_config_error(
                KeyError(
                    "Missing HAL_room_temperatures for: " + ", ".join(missing)
                )
            )

        names_data = self.args.get("room_names", {})
        if isinstance(names_data, dict):
            for room in self.room_names:
                name = self.get_room_mapping_value(names_data, room, ("name",))
                if name:
                    self.room_friendly_names[room] = str(name)

        setpoint_data = self.args.get("default_setpoints", {})
        if isinstance(setpoint_data, dict):
            for room in self.room_names:
                value = self.get_room_mapping_value(
                    setpoint_data, room, ("setpoint",)
                )
                if value not in (None, ""):
                    try:
                        self.room_default_setpoints[room] = float(value)
                    except (TypeError, ValueError) as e:
                        self.handle_config_error(
                            ValueError(f"Invalid default setpoint for {room}: {e}")
                        )

    def init_mqtt_climate_config(self) -> None:
        """
        Load MQTT discovery settings for managed climates.
        """
        mqtt_data = self.args.get("mqtt_climates", {})
        if not isinstance(mqtt_data, dict):
            mqtt_data = {}

        self.mqtt_discovery_prefix = str(
            mqtt_data.get("discovery_prefix", "homeassistant")
        ).strip("/")
        self.mqtt_base_topic = str(
            mqtt_data.get("base_topic", "smart_heating")
        ).strip("/")
        self.mqtt_entity_prefix = str(mqtt_data.get("entity_prefix", "sh")).strip("_")
        if not self.mqtt_entity_prefix:
            self.mqtt_entity_prefix = "sh"
        self.mqtt_event_name = str(mqtt_data.get("event_name", "MQTT_MESSAGE"))
        self.mqtt_min_temp = float(mqtt_data.get("min_temp", 5.0))
        self.mqtt_max_temp = float(mqtt_data.get("max_temp", 30.0))
        self.mqtt_temp_step = float(mqtt_data.get("temp_step", 0.5))
        self.mqtt_precision = float(mqtt_data.get("precision", 0.1))
        self.mqtt_temperature_unit = str(mqtt_data.get("temperature_unit", "C"))
        self.default_room_setpoint = float(
            mqtt_data.get("default_setpoint", DEFAULT_ROOM_SETPOINT)
        )
        self.heat_action_threshold = float(
            mqtt_data.get("heat_action_threshold", 0.2)
        )

    def init_trv_climate_config(self) -> None:
        """
        Load physical TRV climate mappings and build room-level lookup tables.
        """
        trv_data = self.args.get("HAL_climate_TRVs")
        if not isinstance(trv_data, dict):
            trv_data = self.args.get("HAL_setpoint_mapping_out", {})
        if not isinstance(trv_data, dict):
            trv_data = {}

        mappings = {
            "office": ("office", "office_setpoint"),
            "kidsroom": ("kidsroom", "kidsroom_setpoint"),
            "bedroom_left": ("bedroom_left", "bedroom_left_setpoint"),
            "bedroom_right": ("bedroom_right", "bedroom_right_setpoint"),
            "garage": ("garage", "garage_setpoint"),
        }
        missing: list[str] = []
        for attribute_key, keys in mappings.items():
            value = None
            for key in keys:
                if key in trv_data:
                    value = trv_data[key]
                    break
            if value in (None, ""):
                missing.append(keys[0])
            setattr(self, f"HAL_{attribute_key}_setpoint_out", value)

        if missing:
            section = (
                "HAL_climate_TRVs"
                if "HAL_climate_TRVs" in self.args
                else "HAL_setpoint_mapping_out"
            )
            self.handle_config_error(
                KeyError(f"Missing {section} entries: {', '.join(missing)}")
            )

        self.trv_climate_entities_by_trv: dict[str, str] = {
            "office": self.HAL_office_setpoint_out,
            "kidsroom": self.HAL_kidsroom_setpoint_out,
            "bedroom_left": self.HAL_bedroom_left_setpoint_out,
            "bedroom_right": self.HAL_bedroom_right_setpoint_out,
            "garage": self.HAL_garage_setpoint_out,
        }
        self.room_trv_climate_entities: dict[str, tuple[str, ...]] = {
            "office": (self.HAL_office_setpoint_out,),
            "kidsroom": (self.HAL_kidsroom_setpoint_out,),
            "bedroom": (
                self.HAL_bedroom_left_setpoint_out,
                self.HAL_bedroom_right_setpoint_out,
            ),
            "garage": (self.HAL_garage_setpoint_out,),
        }

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

    def get_room_mapping_value(
        self, section_data: dict[str, Any], room: str, suffixes: tuple[str, ...]
    ) -> Any:
        """
        Read a room keyed value while accepting both underscored and compact keys.
        """
        compact_room = room.replace("_", "")
        candidates = [room, compact_room]
        for suffix in suffixes:
            candidates.extend(
                [
                    f"{room}_{suffix}",
                    f"{compact_room}_{suffix}",
                ]
            )

        for key in candidates:
            if key in section_data:
                return section_data[key]
        return None

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
            "heartbeat_s",
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
