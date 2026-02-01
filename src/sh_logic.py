"""
Core heating logic for SmartHeating.
"""

from math import nan

from sh_types import (
    DEFAULT_RAD_POS,
    DEFAULT_WAM_ERROR,
    DEAFULT_RAD_ERR,
    ROOM_INDEX_FH,
    ROOM_INDEX_RAD,
    TRV_INDEX,
)


class LogicMixin:
    """
    Mixin providing the main heating logic operations.
    """

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
