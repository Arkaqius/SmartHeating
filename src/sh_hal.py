"""
HAL access helpers for SmartHeating.
"""

from typing import Any, Optional


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
