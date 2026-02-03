"""
Temporary warm water helper.
"""

from typing import Any, Optional

import appdaemon.plugins.hass.hassapi as hass


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
            # Will be done by UX autoamtion in HA

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
