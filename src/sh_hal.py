"""
HAL access helpers for SmartHeating.
"""

import time
from typing import Any, Optional

from sh_types import DEFAULT_ROOM_TEMPERATURE


class HalMixin:
    """
    Mixin providing HAL get/set helpers.
    """

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
            self.log_invalid_hal_state(hal_entity, state)
            return self.last_valid_hal_values.get(hal_entity, default_value)

        try:
            value = float(state)
        except (TypeError, ValueError):
            self.log_invalid_hal_state(hal_entity, state)
            return self.last_valid_hal_values.get(hal_entity, default_value)

        if hal_entity in self.invalid_hal_states:
            self.log(
                f"HAL state recovered for '{hal_entity}': {value}", level="INFO"
            )
            self.invalid_hal_states.pop(hal_entity, None)
        self.last_valid_hal_values[hal_entity] = value
        return value

    def sh_get_flag_value(self, flag_entity: str) -> bool:
        """
        Retrieve a boolean flag from the HAL.

        Parameters:
            flag_entity (str): The entity ID for the flag in the HAL.

        Returns:
            bool: True if the flag is 'on', False otherwise.
        """
        if not flag_entity:
            return False
        state = self.get_state(flag_entity)
        if state in (None, "unknown", "unavailable"):
            self.log_invalid_hal_state(flag_entity, state)
            return False
        if flag_entity in self.invalid_hal_states:
            self.log(
                f"HAL state recovered for '{flag_entity}': {state}", level="INFO"
            )
            self.invalid_hal_states.pop(flag_entity, None)
        return state == "on"

    def log_invalid_hal_state(self, hal_entity: str, state: Any) -> None:
        """Rate-limit repeated invalid-state messages per entity and state."""
        now = time.monotonic()
        state_text = str(state)
        previous = self.invalid_hal_states.get(hal_entity)
        interval = max(float(self.invalid_state_log_interval_s), 0.0)
        should_log = (
            previous is None
            or previous[0] != state_text
            or now - previous[1] >= interval
        )
        if should_log:
            fallback = self.last_valid_hal_values.get(hal_entity)
            fallback_text = (
                f"last valid value {fallback}"
                if fallback is not None
                else "configured fallback"
            )
            self.log(
                f"HAL state invalid for '{hal_entity}': {state}; using {fallback_text}",
                level="ERROR",
            )
            self.invalid_hal_states[hal_entity] = (state_text, now)

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
        if domain == "number":
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
        return self.warm_flag_offset if self.sh_get_warm_flag() else 0

    def sh_get_corridor_setpoint(self) -> float:
        """Retrieve the corridor setpoint from the HAL."""
        return self.get_room_setpoint("corridor")

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

    def sh_get_freezing_flag(self) -> bool:
        """Retrieve the state of the freezing flag."""
        return self.sh_get_flag_value(self.HAL_frezzing_flag)

    def sh_get_warm_flag(self) -> bool:
        """Retrieve the state of the warm flag."""
        return self.control_flags.get("warm_flag", False)

    def sh_get_force_flow_flag(self) -> bool:
        """Retrieve the state of the force flow flag."""
        return self.control_flags.get("force_flow_safety_rooms", False)

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

    def sh_get_room_temperature(self, room_name: str) -> float:
        """
        Retrieve a raw room temperature by room key.
        """
        entity = self.room_temperature_entities.get(room_name)
        default = self.get_room_setpoint(room_name) if self.room_setpoints else (
            DEFAULT_ROOM_TEMPERATURE
        )
        if not entity:
            self.log(f"Missing room temperature entity for {room_name}", level="ERROR")
            self.handle_hw_error(f"Missing room temperature entity for {room_name}")
            return default
        return self.sh_get_value(entity, default)

    def sh_get_room_error(self, room_name: str) -> float:
        """
        Calculate target minus current room temperature.
        """
        if self.room_hvac_modes.get(room_name, "heat") == "off":
            return 0.0
        return round(
            self.get_room_setpoint(room_name) - self.sh_get_room_temperature(room_name),
            2,
        )
