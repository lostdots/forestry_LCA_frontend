import math

import pandas as pd

DIESEL_LOWER_HEATING_KWH_PER_L = 0.84 * 11.65
DIESEL_DRIVETRAIN_EFFICIENCY = 0.40
ELECTRIC_DRIVETRAIN_EFFICIENCY = 0.90
DIESEL_TO_ELECTRIC_KWH_PER_L = DIESEL_LOWER_HEATING_KWH_PER_L * DIESEL_DRIVETRAIN_EFFICIENCY / ELECTRIC_DRIVETRAIN_EFFICIENCY  # 4.35 kWh/L
CHARGING_LOSS_FACTOR = 1.10
WOOD_DENSITY_T_M3 = 0.960
CABLE_YARDER_DIESEL_REFERENCE_MASS_KG = 31000.0
CABLE_YARDER_RECUP_CARRIAGE_PRODUCTIVITY_FACTOR = 22.5 / 21.4
CABLE_YARDER_RECUP_CARRIAGE_FUEL_FACTOR = 0.88 / 1.27
SUPERCAPACITOR_CELL_CAPACITY_KWH = 5.12 / 1000
AUMEIER_TRUCK_REFERENCE_CYCLE_TIME_H = (27.0 + 15.0 + 54.0 + 19.0 + 38.0 + 19.0) / 60.0
AUMEIER_TRUCK_DIESEL_L_PER_H = 55.0 / AUMEIER_TRUCK_REFERENCE_CYCLE_TIME_H
AUMEIER_TRUCK_BEV_KWH_PER_H = 189.0 / AUMEIER_TRUCK_REFERENCE_CYCLE_TIME_H
AUMEIER_LOADING_UNLOADING_DIESEL_L_PER_H = 11.0
AUMEIER_TRUCK_LOADED_GROSS_MASS_T = 44.0
LECHNER_RECUP_REFERENCE_HEIGHT_M = 550.0

AUTONOMOUS_BASE_CLASS_MACHINE_IDS = {
    "harvester": "harvester_diesel",
    "forwarder": "forwarder_diesel",
    "truck": "truck_diesel",
}


class Machine:
    def __init__(
        self,
        machine_id,
        electric,
        mass_kg,
        lifetime_h,
        lifetime_m3,
        productivity_m3_h,
        diesel_l_h,
        power_consumption_kwh_h,
        battery_capacity_kwh,
        battery_mass_kg,
        number_of_batteries_over_lifetime,
        production_factor_kgco2e_kg,
        maintenance_factor_percentage,
        ttw_zero,
        production_model,
        engine_mass_ICE_kg,
        maintenance_factor_kgco2e_kg=0,
        autonomy_subsystem_mass_kg=0,
        autonomy_subsystem_power_w=0,
        autonomy_subsystem_production_kgco2e=0,
        autonomy_subsystem_eol_kgco2e_kg=0,
        autonomy_productivity_gain_share=0,
        autonomy_energy_saving_share=0,
        autonomy_onboard_electric_efficiency=0.20,
        cab_removed_mass_kg=0,
        relocation_distance=0,
        operating_hours_per_day=0,
    ):

        self.machine_id = machine_id
        self.electric = bool(electric)
        self.mass_kg = _to_float(mass_kg)
        self.lifetime_h = _to_float(lifetime_h)
        self.lifetime_m3 = _to_float(lifetime_m3)
        self.productivity_h = _to_float(productivity_m3_h)
        self.diesel_l_h = _to_float(diesel_l_h)  #
        self.power_consumption_kwh_h = _to_float(power_consumption_kwh_h)  #
        self.battery_capacity = _to_float(battery_capacity_kwh)  #
        self.battery_mass = _to_float(battery_mass_kg)  #
        self.number_of_batteries_over_lifetime = _to_float(number_of_batteries_over_lifetime)
        self.production_factor = _to_float(production_factor_kgco2e_kg)
        self.maintenance_factor = _to_float(maintenance_factor_kgco2e_kg)
        self.maintenance_factor_percentage = _to_float(maintenance_factor_percentage)

        self.ttw_zero = bool(ttw_zero)
        self._recalculate_power_consumption_kwh_m3()

        self.production_emission = 0
        self.maintenance_emission = 0
        self.wtt_emission = 0
        self.ttw_emission = 0
        self.eol_emission = 0
        self.consumption_l_m3 = 0
        self.production_model = production_model
        self.engine_mass_ICE_kg = _to_float(engine_mass_ICE_kg)
        self.autonomy_subsystem_mass_kg = _to_float(autonomy_subsystem_mass_kg)
        self.autonomy_subsystem_power_w = _to_float(autonomy_subsystem_power_w)
        self.autonomy_subsystem_production_kgco2e = _to_float(autonomy_subsystem_production_kgco2e)
        self.autonomy_subsystem_eol_kgco2e_kg = _to_float(autonomy_subsystem_eol_kgco2e_kg)
        self.autonomy_productivity_gain_share = _bounded_share(autonomy_productivity_gain_share)
        self.autonomy_energy_saving_share = _bounded_share(autonomy_energy_saving_share)
        self.autonomy_onboard_electric_efficiency = _to_float(autonomy_onboard_electric_efficiency, default=0.20)
        self.cab_removed_mass_kg = _to_float(cab_removed_mass_kg)
        self.relocation_distance = _to_float(relocation_distance)
        self.operating_hours_per_day = _to_float(operating_hours_per_day)
        self._autonomy_adjustments_applied = False

    def _net_base_mass_kg(self):
        return max(0.0, self.mass_kg - self.cab_removed_mass_kg)

    def _effective_mass_kg(self):
        return self._net_base_mass_kg() + self.autonomy_subsystem_mass_kg

    def _calculate_relocation_emission(self, emission_factors: dict, mode: str):
        """Return machine-relocation emissions in kg CO2e per harvested m3."""
        if (
            self.relocation_distance <= 0
            or self.operating_hours_per_day <= 0
            or self.productivity_h <= 0
        ):
            return 0.0

        factor_ids = {
            "wtt": "heavy_truck_wtt_tkm",
            "ttw": "heavy_truck_ttw_tkm",
        }
        factor_id = factor_ids.get(mode)
        if factor_id is None:
            return 0.0

        # Repository factors are g CO2e/tkm; model results use kg CO2e/m3.
        truck_factor_kgco2e_tkm = _factor(emission_factors, factor_id) / 1000
        machine_mass_t = self._effective_mass_kg() / 1000
        tkm_per_operating_hour = (
            machine_mass_t
            * self.relocation_distance
            / self.operating_hours_per_day
        )
        return (
            tkm_per_operating_hour
            * truck_factor_kgco2e_tkm
            / self.productivity_h
        )

    def _autonomy_production_total(self):
        return self.autonomy_subsystem_production_kgco2e

    def _production_total_with_autonomy(self, base_production_total):
        return base_production_total + self._autonomy_production_total()

    def _apply_autonomy_adjustments(self):
        if self._autonomy_adjustments_applied:
            return

        if self.autonomy_productivity_gain_share > 0 and self.productivity_h > 0:
            self.productivity_h *= 1 + self.autonomy_productivity_gain_share

        if self.autonomy_energy_saving_share > 0:
            self.diesel_l_h *= 1 - self.autonomy_energy_saving_share
            self.consumption_l_m3 *= 1 - self.autonomy_energy_saving_share
            self.power_consumption_kwh_h *= 1 - self.autonomy_energy_saving_share

        autonomy_power_kw = self.autonomy_subsystem_power_w / 1000
        if autonomy_power_kw > 0:
            if self.electric:
                self.power_consumption_kwh_h += autonomy_power_kw * CHARGING_LOSS_FACTOR
            else:
                efficiency = self.autonomy_onboard_electric_efficiency
                if efficiency <= 0:
                    efficiency = 0.20
                self.diesel_l_h += autonomy_power_kw / (DIESEL_LOWER_HEATING_KWH_PER_L * efficiency)

        self._recalculate_power_consumption_kwh_m3()
        self._autonomy_adjustments_applied = True

    def _autonomous_base_class_machine_id(self):
        if "autonomous" not in self.machine_id:
            return None
        for prefix, base_class_id in AUTONOMOUS_BASE_CLASS_MACHINE_IDS.items():
            if self.machine_id.startswith(prefix):
                return base_class_id
        return None

    def _autonomous_base_reference_mass_kg(self):
        base_class_machine_id = self._autonomous_base_class_machine_id()
        if base_class_machine_id == "harvester_diesel":
            return 22000.0
        if base_class_machine_id == "forwarder_diesel":
            return Forwarder.REFERENCE_MASS_KG
        if base_class_machine_id == "truck_diesel":
            return 8000.0
        return self.mass_kg

    def _recalculate_power_consumption_kwh_m3(self):
        if self.power_consumption_kwh_h <= 0 and self.diesel_l_h > 0:
            self.power_consumption_kwh_h = self.diesel_l_h * DIESEL_TO_ELECTRIC_KWH_PER_L * CHARGING_LOSS_FACTOR

        if self.productivity_h > 0 and self.power_consumption_kwh_h > 0:
            self.power_consumption_kwh_m3 = self.power_consumption_kwh_h / self.productivity_h
        elif not hasattr(self, "power_consumption_kwh_m3"):
            self.power_consumption_kwh_m3 = 0

    def calculate_emission(self, consumption_l_h, density, heat_capacity, emission_factor):

        consumption_l_m3 = consumption_l_h / self.productivity_h if self.productivity_h > 0 else self.consumption_l_m3
        coefficient = density * heat_capacity * (emission_factor / 1000)
        fossil_emission = consumption_l_m3 * coefficient

        return fossil_emission

    def calculate_production_emissions(self, materials: list[dict], emission_factors: dict):
        if self.mass_kg <= 0 or self.production_factor <= 0:
            self.production_emission = 0.0
            return

        self.production_emission = self._divide_by_production_output(self._production_total_with_autonomy(self._net_base_mass_kg() * self.production_factor))

    def calculate_maintenance_emissions(self, materials: list[dict], emission_factors: dict):
        if self.mass_kg <= 0 or self.production_factor <= 0:
            self.maintenance_emission = 0.0
            return

        maintenance_total = (
            self._net_base_mass_kg()
            * self.production_factor
            * self.maintenance_factor_percentage
        )
        self.maintenance_emission = self._divide_by_production_output(
            maintenance_total
        )

    def _divide_by_production_output(self, emission_total):
        denominator = self.lifetime_h * self.productivity_h
        if denominator <= 0:
            return 0.0
        return emission_total / denominator

    def calculate_eol_emissions(self, materials: list[dict], emission_factors: dict):
        material_rows = [row for row in materials if row["machine_id"] in self._material_model_ids()]

        eol_total = sum(self._calculate_eol_row(row, emission_factors) for row in material_rows)

        eol_total += self.autonomy_subsystem_mass_kg * self.autonomy_subsystem_eol_kgco2e_kg
        self.eol_emission = eol_total / self._lifetime_output_m3()

    def _calculate_eol_row(self, row: dict, emission_factors: dict):
        factor_id = row.get("eol_factor_id")
        if not factor_id or pd.isna(factor_id):
            return 0.0

        mass_kg = self._eol_material_mass_kg(row)
        if mass_kg <= 0:
            return 0.0

        recycling_rate = _to_float(row.get("recycling_rate"), default=1.0)
        factor = _factor(emission_factors, factor_id)
        return mass_kg * recycling_rate * factor

    def _eol_material_mass_kg(self, row: dict):
        share_percent = row.get("share_percent")
        if share_percent is not None and not pd.isna(share_percent):
            mass_kg = self._eol_share_basis_mass_kg(row) * _to_float(share_percent) / 100
        else:
            mass_kg = _to_float(row.get("mass_kg"))

        if row.get("component") == "battery":
            mass_kg *= self.number_of_batteries_over_lifetime

        return mass_kg

    def _eol_share_basis_mass_kg(self, row: dict):
        return self._net_base_mass_kg()

    def _material_model_ids(self):
        model_ids = [self.machine_id]

        autonomous_base_class_machine_id = self._autonomous_base_class_machine_id()
        if autonomous_base_class_machine_id:
            model_ids.append(autonomous_base_class_machine_id)

        return model_ids

    def _lifetime_output_m3(self):
        if self.lifetime_h > 0 and self.productivity_h > 0:
            return self.lifetime_h * self.productivity_h
        if self.lifetime_m3 > 0:
            return self.lifetime_m3
        return 1.0

    def get_machine(self):
        return self
        # Getter methods

    def get_machine_id(self):
        return self.machine_id

    def get_production_emission(self):
        return self.production_emission

    def get_maintenance_emission(self):
        return self.maintenance_emission

    def get_wtt_emission(self):
        return self.wtt_emission

    def get_ttw_emission(self):
        return self.ttw_emission

    def get_eol_emission(self):
        return self.eol_emission


def _to_float(value, default=0.0):

    if value is None or value == "" or pd.isna(value):
        return default
    return float(value)


def _bounded_share(value):
    return max(0.0, min(_to_float(value), 1.0))


def _factor(emission_factors: dict, factor_name: str, default=0.0):
    """Safely read one prepared emission factor.

    The DataStream returns a flat dictionary, e.g.:
    factors["diesel_wtt"] = 71.0
    factors["diesel_wtt_density"] = 0.84
    factors["diesel_wtt_heating_value"] = 11.65
    """
    if not isinstance(emission_factors, dict):
        return default

    value = emission_factors.get(factor_name, default)

    # Fallback: this also works if an old nested factor dictionary is passed.
    if isinstance(value, dict):
        value = value.get("value", default)

    return _to_float(value, default)


class Forwarder(Machine):
    # Konrad Pully brochure, p. 4: 3950 kg and 140 PS.
    REFERENCE_MASS_KG = 11322.0
    REFERENCE_ENGINE_POWER_KW = 110.0
    PULLY_ENGINE_POWER_KW = 140.0 * 0.73549875
    FUEL_REGRESSION_INTERCEPT_L_H = 4.4539
    FUEL_REGRESSION_SLOPE_L_H_PER_KW = 0.0562
    REFERENCE_DIESEL_L_H = FUEL_REGRESSION_INTERCEPT_L_H + FUEL_REGRESSION_SLOPE_L_H_PER_KW * REFERENCE_ENGINE_POWER_KW
    PULLY_DIESEL_L_H = FUEL_REGRESSION_INTERCEPT_L_H + FUEL_REGRESSION_SLOPE_L_H_PER_KW * PULLY_ENGINE_POWER_KW
    PULLY_EXTERNAL_LOADING_REDUCTION = 0.50
    PULLY_USE_CASE_FUEL_FACTOR = PULLY_DIESEL_L_H / REFERENCE_DIESEL_L_H * (1 - PULLY_EXTERNAL_LOADING_REDUCTION)

    def __init__(
        self,
        *args,
        operating_hours_per_day,
        relocation_distance,
        payload_kg=0,
        load_volume_m3=0,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.type = "forwarder"
        self.operating_hours_per_day = _to_float(operating_hours_per_day)
        self.relocation_distance = _to_float(relocation_distance)
        self.payload_kg = _to_float(payload_kg)
        self.load_volume_m3 = _to_float(load_volume_m3)

    def calculate_eol_emissions(self, materials: list[dict], emission_factors: dict):
        super().calculate_eol_emissions(materials, emission_factors)

    def _eol_share_basis_mass_kg(self, row: dict):
        if self.electric and row.get("machine_id") == self.machine_id:
            return max(0.0, self.mass_kg - self.battery_mass)
        return super()._eol_share_basis_mass_kg(row)

    def _material_model_ids(self):
        model_ids = super()._material_model_ids()
        if self.machine_id == "forwarder_pully":
            model_ids.append("forwarder_diesel")
        return model_ids

    def calculate_production_emissions(self, materials: list[dict], emission_factors: dict):
        if self.electric:
            emission_housing = (self.mass_kg - self.engine_mass_ICE_kg) * self.production_factor
            initial_batteries = min(self.number_of_batteries_over_lifetime, 1.0)
            emission_battery = self.battery_capacity * _factor(emission_factors, "lfp_battery_prod_energy") * initial_batteries
            self.production_emission = self._divide_by_production_output(emission_housing + emission_battery)
            return

        self.production_emission = self._divide_by_production_output(self._production_total_with_autonomy(self._net_base_mass_kg() * self.production_factor))

    def calculate_maintenance_emissions(self, materials: list[dict], emission_factors: dict):
        if self.electric:
            emission_housing = (self.mass_kg - self.engine_mass_ICE_kg) * self.production_factor
            replacement_batteries = max(self.number_of_batteries_over_lifetime - 1.0, 0.0)
            emission_battery = self.battery_capacity * _factor(emission_factors, "lfp_battery_prod_energy") * replacement_batteries
            maintenance_total = emission_housing * self.maintenance_factor_percentage + emission_battery
            self.maintenance_emission = self._divide_by_production_output(maintenance_total)
            return

        maintenance_total = (
            self._net_base_mass_kg()
            * self.production_factor
            * self.maintenance_factor_percentage
        )
        self.maintenance_emission = self._divide_by_production_output(
            maintenance_total
        )

    def apply_use_case_to_machine(self, use_case_row: dict):
        extraction_distance = _to_float(use_case_row["stand_to_logpile_m"])
        self.productivity_h = -0.0042 * extraction_distance + 16.206

        # Meissl (2019), Formula 10: specific forwarder fuel use [l/Efm].
        # The reported reference piece volume is 0.46 Efm.
        piece_volume_m3 = _to_float(use_case_row.get("piece_volume_m3"), default=0.46)
        if piece_volume_m3 <= 0:
            piece_volume_m3 = 0.46

        self.consumption_l_m3 = 0.173 / piece_volume_m3 + 0.00103 * extraction_distance

        if self.machine_id == "forwarder_pully":
            if self.load_volume_m3 <= 0:
                raise ValueError("forwarder_pully requires load_volume_m3 > 0")
            self.consumption_l_m3 *= self.PULLY_USE_CASE_FUEL_FACTOR

        if self.electric:
            self._set_electric_consumption_from_diesel_equivalent()
        else:
            self.diesel_l_h = self.consumption_l_m3 * self.productivity_h

        self._apply_autonomy_adjustments()

    def _set_electric_consumption_from_diesel_equivalent(self):
        self.power_consumption_kwh_m3 = self.consumption_l_m3 * DIESEL_TO_ELECTRIC_KWH_PER_L * CHARGING_LOSS_FACTOR
        self.power_consumption_kwh_h = self.power_consumption_kwh_m3 * self.productivity_h if self.productivity_h > 0 else 0

    def calculate_wtw_emissions(self, emission_factors: dict, mode: str):

        electricity_mix = _factor(emission_factors, "electricity_mix")
        diesel_density = _factor(emission_factors, "diesel_wtt_density")
        diesel_heating_value = _factor(emission_factors, "diesel_wtt_heating_value")
        diesel_wtt = _factor(emission_factors, "diesel_wtt")
        diesel_ttw = _factor(emission_factors, "diesel_ttw")
        emission = 0
        match self.electric:
            case True:
                if mode == "wtt":
                    self._recalculate_power_consumption_kwh_m3()
                    emission = self.power_consumption_kwh_m3 * electricity_mix
                elif mode == "ttw":
                    emission = 0
            case False:
                density = diesel_density
                heat_capacity = diesel_heating_value

                if mode == "wtt":
                    emission_factor = diesel_wtt

                elif mode == "ttw":
                    emission_factor = diesel_ttw

                emission = super().calculate_emission(
                    self.diesel_l_h,
                    density,
                    heat_capacity,
                    emission_factor,
                )

        relocation = self._calculate_relocation_emission(emission_factors, mode)

        if mode == "wtt":
            self.wtt_emission = emission + relocation
        elif mode == "ttw":
            self.ttw_emission = emission + relocation


class Tractor(Machine):
    def __init__(self, *args, load_volume_m3, **kwargs):
        super().__init__(*args, **kwargs)
        self.type = "tractor"
        self.load_volume_m3 = _to_float(load_volume_m3)

    def calculate_eol_emissions(self, materials: list[dict], emission_factors: dict):
        super().calculate_eol_emissions(materials, emission_factors)

    def _calculate_eol_row(self, row: dict, emission_factors: dict):
        if row.get("eol_factor_id") == "tractor_eol_recovery_share":
            mass_kg = self._eol_material_mass_kg(row)
            production_factor = _factor(emission_factors, row.get("production_factor_id"))
            if production_factor <= 0:
                production_factor = self.production_factor
                # recovery share: -23% percent
            recovery_share = _factor(emission_factors, "tractor_eol_recovery_share")
            return mass_kg * production_factor * recovery_share  # from the whole production emission 23 percent will be recovered
        return super()._calculate_eol_row(row, emission_factors)

    def _material_model_ids(self):
        model_ids = super()._material_model_ids()
        if self.electric:
            model_ids.append("tractor_electric")
        else:
            model_ids.append("tractor_diesel")
        return model_ids

    def calculate_production_emissions(self, materials: list[dict], emission_factors: dict):
        if self.electric:
            emission_housing = (self.mass_kg - self.engine_mass_ICE_kg) * self.production_factor
            initial_batteries = min(self.number_of_batteries_over_lifetime, 1.0)
            emission_battery = self.battery_mass * _factor(emission_factors, "li_ion_battery_prod_mass") * initial_batteries
            self.production_emission = self._divide_by_production_output(emission_housing + emission_battery)
            return

        self.production_emission = self._divide_by_production_output(self._production_total_with_autonomy(self._net_base_mass_kg() * self.production_factor))

    def calculate_maintenance_emissions(self, materials: list[dict], emission_factors: dict):
        if self.electric:
            maintenance_housing = (
                (self.mass_kg - self.engine_mass_ICE_kg)
                * self.maintenance_factor
            )
            replacement_batteries = max(self.number_of_batteries_over_lifetime - 1.0, 0.0)
            emission_battery = self.battery_mass * _factor(emission_factors, "li_ion_battery_prod_mass") * replacement_batteries
            maintenance_total = maintenance_housing + emission_battery
            self.maintenance_emission = self._divide_by_production_output(maintenance_total)
            return

        self.maintenance_emission = self._divide_by_production_output(self._net_base_mass_kg() * self.maintenance_factor)

    def _set_electric_consumption_from_diesel_equivalent(self):
        self.power_consumption_kwh_m3 = self.consumption_l_m3 * DIESEL_TO_ELECTRIC_KWH_PER_L * CHARGING_LOSS_FACTOR
        self.power_consumption_kwh_h = self.power_consumption_kwh_m3 * self.productivity_h if self.productivity_h > 0 else 0

    def apply_use_case_to_machine(self, use_case_row: dict):

        match self.machine_id:
            case machine_id if "winch" in machine_id:
                winching_distance = _to_float(use_case_row["winching_distance"])
                extraction_distance = _to_float(use_case_row["extraction_to_log_pile"])
                volume_per_drive = 2.59
                tr = 1879 + 15.81 * (winching_distance - 30) + 2.24 * (extraction_distance - 29)  # das ist die Rueckezeit fuer einen Zyklus in Sekunden
                self.productivity_h = volume_per_drive / (tr / 3600)  # 2.59 m3 pro Zyklus

                bT = 1.30 + 0.017 * (winching_distance - 30) + 0.003 * (extraction_distance - 29)  # Dieselverbrauch pro Rueckezyklus
                # Dieselverbrauch pro Stunde
                self.diesel_l_h = bT / (tr / 3600)
                self.consumption_l_m3 = bT / volume_per_drive  # Dieselverbrauch pro m3, eine durchschnittlicher Rueckezyklus laut Kirnbauer ist 2.59 m3
            case machine_id if "trailer" in machine_id:
                forest_distance = _to_float(use_case_row["forest_distance_km"])
                street_distance = _to_float(use_case_row["street_distance_km"])

                LC = self.load_volume_m3
                if LC <= 0:
                    raise ValueError(f"{self.machine_id} requires load_volume_m3 > 0")

                # Geschwindigkeiten [km/h]
                v_empty_forest_kmh = 15  # fuer Forstwege, nicht Rueckung zwischen Poltern
                v_loaded_forest_kmh = 7  # fuer Forstwege, nicht Rueckung zwischen Poltern
                v_empty_street = 40
                v_loaded_street = 30

                # Zusatzzeiten aus Originalformel
                DP = 0  # Distanz zwischen Holzpoltern [m]
                NM = 1  # Anzahl Bewegungen zwischen Poltern
                NL = 10  # Anzahl Staemme

                tTE = forest_distance * (1 / v_empty_forest_kmh + 1 / v_loaded_forest_kmh) + street_distance * (
                    1 / v_empty_street
                    + 1 / v_loaded_street
                    # Fahrzeit pro Zyklus [h]: Leer- und beladene Fahrt im Wald sowie auf der Strasse, berechnet mit Zeit = Distanz / Geschwindigkeit
                )

                tMV = 0.0011 * (DP**0.764) * NM  # Zeit fuer Bewegung zwischen Holzpoltern [h]
                tPL = 0.007 * NM  # Vorbereitungszeit Laden [h]
                tPU = 0.008  # Vorbereitungszeit Entladen [h]
                tLD = 0.0011 * NL  # Ladezeit abhaengig von der Stammzahl [h]
                tUL = 0.008 * NL  # Entladezeit abhaengig von der Stammzahl [h]

                CT = tTE + tMV + tPL + tPU + tLD + tUL  # Zykluszeit [h/Fuhre]

                self.productivity_h = LC / CT  # m3/h

                # Dieselverbrauch
                HFC_wald = 3.12  # L/h im Wald
                # Goetz et al. (2011): 140 kW tractor with two trailers,
                # measured on-road consumption when empty and fully loaded.
                diesel_empty_street = 47 / 100  # L/km
                diesel_loaded_street = 71 / 100  # L/km

                non_driving_time = tPL + tPU + tLD + tUL

                t_wald = forest_distance * (1 / v_empty_forest_kmh + 1 / v_loaded_forest_kmh)
                diesel_per_drive = HFC_wald * (t_wald + non_driving_time) + diesel_empty_street * street_distance + diesel_loaded_street * street_distance

                self.diesel_l_h = diesel_per_drive / CT

                # optional zur Kontrolle
                self.consumption_l_m3 = diesel_per_drive / LC

        if self.electric:
            self._set_electric_consumption_from_diesel_equivalent()

    def calculate_wtw_emissions(self, emission_factors: dict, mode: str):

        electricity_mix = _factor(emission_factors, "electricity_mix")
        diesel_density = _factor(emission_factors, "diesel_wtt_density")
        diesel_heating_value = _factor(emission_factors, "diesel_wtt_heating_value")
        diesel_wtt = _factor(emission_factors, "diesel_wtt")
        diesel_ttw = _factor(emission_factors, "diesel_ttw")

        emission = 0
        match self.electric:
            case True:
                if mode == "wtt":
                    self._recalculate_power_consumption_kwh_m3()
                    emission = self.power_consumption_kwh_m3 * electricity_mix
                elif mode == "ttw":
                    emission = 0
            case False:
                density = diesel_density
                heat_capacity = diesel_heating_value

                if mode == "wtt":
                    emission_factor = diesel_wtt

                elif mode == "ttw":
                    emission_factor = diesel_ttw

                emission = super().calculate_emission(
                    self.diesel_l_h,
                    density,
                    heat_capacity,
                    emission_factor,
                )

        if mode == "wtt":
            self.wtt_emission = emission
        elif mode == "ttw":
            self.ttw_emission = emission


class Harvester(Machine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.type = "harvester"

    def calculate_eol_emissions(self, materials: list[dict], emission_factors: dict):
        super().calculate_eol_emissions(materials, emission_factors)

    def _machine_body_mass_kg(self):
        if self.electric:
            return max(self.mass_kg - self.battery_mass, 0.0)
        return self.mass_kg

    def calculate_production_emissions(self, materials: list[dict], emission_factors: dict):
        if self.electric:
            emission_housing = self._machine_body_mass_kg() * self.production_factor
            initial_batteries = min(self.number_of_batteries_over_lifetime, 1.0)
            emission_battery = self.battery_capacity * _factor(emission_factors, "lfp_battery_prod_energy") * initial_batteries
            self.production_emission = self._divide_by_production_output(emission_housing + emission_battery)
            return

        self.production_emission = self._divide_by_production_output(self._production_total_with_autonomy(self._net_base_mass_kg() * self.production_factor))

    def calculate_maintenance_emissions(self, materials: list[dict], emission_factors: dict):
        if self.electric:
            emission_housing = self._machine_body_mass_kg() * self.production_factor
            replacement_batteries = max(self.number_of_batteries_over_lifetime - 1.0, 0.0)
            emission_battery = self.battery_capacity * _factor(emission_factors, "lfp_battery_prod_energy") * replacement_batteries
            maintenance_total = emission_housing * self.maintenance_factor_percentage + emission_battery
            self.maintenance_emission = self._divide_by_production_output(maintenance_total)
            return

        maintenance_total = (
            self._net_base_mass_kg()
            * self.production_factor
            * self.maintenance_factor_percentage
        )
        self.maintenance_emission = self._divide_by_production_output(
            maintenance_total
        )

    def apply_use_case_to_machine(self, use_case_row: dict):

        self._apply_autonomy_adjustments()

    def calculate_wtw_emissions(self, emission_factors: dict, mode: str):

        electricity_mix = _factor(emission_factors, "electricity_mix")
        diesel_density = _factor(emission_factors, "diesel_wtt_density")
        diesel_heating_value = _factor(emission_factors, "diesel_wtt_heating_value")
        diesel_wtt = _factor(emission_factors, "diesel_wtt")
        diesel_ttw = _factor(emission_factors, "diesel_ttw")

        emission = 0
        emission_chain_oil_wtt = 0
        match self.electric:
            case True:
                if mode == "wtt":
                    self._recalculate_power_consumption_kwh_m3()
                    emission = self.power_consumption_kwh_m3 * electricity_mix
                elif mode == "ttw":
                    emission = 0
            case False:
                density = diesel_density
                heat_capacity = diesel_heating_value

                if mode == "wtt":
                    emission_factor = diesel_wtt
                    emission_chain_oil_wtt = 0.0818
                elif mode == "ttw":
                    emission_factor = diesel_ttw

                emission = super().calculate_emission(
                    self.diesel_l_h,
                    density,
                    heat_capacity,
                    emission_factor,
                )

        relocation = self._calculate_relocation_emission(emission_factors, mode)

        if mode == "wtt":
            self.wtt_emission = emission + relocation + emission_chain_oil_wtt
        elif mode == "ttw":
            self.ttw_emission = emission + relocation


class Chainsaw(Machine):
    def __init__(self, *args, gasoline_mix_l_h, chain_oil_l_h, power_consumption_kwh_m3, **kwargs):
        super().__init__(*args, **kwargs)
        self.type = "chainsaw"
        self.gasoline_mix_l_h = _to_float(gasoline_mix_l_h)
        self.chain_oil_l_h = _to_float(chain_oil_l_h)
        self.power_consumption_kwh_m3 = _to_float(power_consumption_kwh_m3)

    def calculate_eol_emissions(self, materials: list[dict], emission_factors: dict):
        if not self.electric:
            super().calculate_eol_emissions(materials, emission_factors)
            return

        body_rows = [row for row in materials if row["machine_id"] == self.machine_id and row.get("component") == "saw_body"]
        body_total = sum(self._calculate_eol_row(row, emission_factors) for row in body_rows)
        battery_total = self.battery_capacity * self.number_of_batteries_over_lifetime * _factor(emission_factors, "chainsaw_battery_recycling_credit")
        self.eol_emission = (body_total + battery_total) / self._lifetime_output_m3()

    def calculate_production_emissions(self, materials: list[dict], emission_factors: dict):
        if self.electric:
            mass_housing = self.mass_kg - self.battery_mass
            emission_housing = self.production_factor * mass_housing
            initial_batteries = min(self.number_of_batteries_over_lifetime, 1.0)
            emission_battery = _factor(emission_factors, "li_ion_battery_prod_energy_nick_manganes") * self.battery_capacity * initial_batteries
            self.production_emission = self._divide_by_production_output(emission_housing + emission_battery)
            return

        self.production_emission = self._divide_by_production_output(self._production_total_with_autonomy(self._net_base_mass_kg() * self.production_factor))

    def calculate_maintenance_emissions(self, materials: list[dict], emission_factors: dict):
        chain_oil_emission = (self.chain_oil_l_h / self.productivity_h) * _factor(emission_factors, "chain_oil_wtt") if self.productivity_h > 0 else 0.0

        if self.electric:
            replacement_batteries = max(self.number_of_batteries_over_lifetime - 1.0, 0.0)
            emission_battery = _factor(emission_factors, "li_ion_battery_prod_energy_nick_manganes") * self.battery_capacity * replacement_batteries
            self.maintenance_emission = self._divide_by_production_output(emission_battery) + chain_oil_emission
            return

        maintenance_total = (
            self._net_base_mass_kg()
            * self.production_factor
            * self.maintenance_factor_percentage
        )
        self.maintenance_emission = (
            self._divide_by_production_output(maintenance_total)
            + chain_oil_emission
        )

    def apply_use_case_to_machine(self, use_case_row: dict):

        self._apply_autonomy_adjustments()

    def calculate_wtw_emissions(self, emission_factors: dict, mode: str):

        electricity_mix = _factor(emission_factors, "electricity_mix")
        chainsaw_fuel_mix_wtt = _factor(emission_factors, "chainsaw_fuel_mix_wtt_ecoinvent")
        chainsaw_fuel_mix_ttw = _factor(emission_factors, "chainsaw_fuel_mix_ttw_ecoinvent")

        match self.electric:
            case True:
                if mode == "wtt":
                    self.wtt_emission = self.power_consumption_kwh_m3 * electricity_mix
                elif mode == "ttw":
                    self.ttw_emission = 0
            case False:

                consumption_l_m3 = self.gasoline_mix_l_h / self.productivity_h if self.productivity_h > 0 else 0
                if mode == "wtt":
                    emission_factor = chainsaw_fuel_mix_wtt
                    self.wtt_emission = emission_factor * consumption_l_m3

                elif mode == "ttw":
                    emission_factor = chainsaw_fuel_mix_ttw
                    self.ttw_emission = emission_factor * consumption_l_m3


class ForestTrailer(Machine):
    def __init__(self, *args, payload_kg, load_volume_m3, **kwargs):
        super().__init__(*args, **kwargs)
        self.type = "forest_trailer"
        self.payload_kg = _to_float(payload_kg)
        self.load_volume_m3 = _to_float(load_volume_m3)

    def calculate_eol_emissions(self, materials: list[dict], emission_factors: dict):
        super().calculate_eol_emissions(materials, emission_factors)

    def _material_model_ids(self):
        model_ids = super()._material_model_ids()
        model_ids.append("forest_trailer_loader_crane")
        return model_ids

    def calculate_production_emissions(self, materials: list[dict], emission_factors: dict):
        loader_crane_emissions = 6768.0
        weight_crane = 3000
        production_total = (self.mass_kg - weight_crane) * self.production_factor + loader_crane_emissions
        self.production_emission = self._divide_by_production_output(production_total)

    def calculate_maintenance_emissions(self, materials: list[dict], emission_factors: dict):
        self.maintenance_emission = 0.0

    def apply_use_case_to_machine(self, use_case_row: dict):
        forest_distance = _to_float(use_case_row["forest_distance_km"])
        street_distance = _to_float(use_case_row["street_distance_km"])

        LC = self.load_volume_m3
        if LC <= 0:
            raise ValueError("forest_trailer requires load_volume_m3 > 0")

        # Geschwindigkeiten [km/h]
        v_empty_forest_kmh = 15  # fuer Forstwege, nicht Rueckung zwischen Poltern
        v_loaded_forest_kmh = 7  # fuer Forstwege, nicht Rueckung zwischen Poltern
        v_empty_street = 40
        v_loaded_street = 30

        # Zusatzzeiten aus Originalformel
        DP = 0  # Distanz zwischen Holzpoltern [m]
        NM = 1  # Anzahl Bewegungen zwischen Poltern
        NL = 10  # Anzahl Staemme

        tTE = forest_distance * (1 / v_empty_forest_kmh + 1 / v_loaded_forest_kmh) + street_distance * (
            1 / v_empty_street
            + 1 / v_loaded_street
            # Fahrzeit pro Zyklus [h]: Leer- und beladene Fahrt im Wald sowie auf der Strasse, berechnet mit Zeit = Distanz / Geschwindigkeit
        )

        # Zeit fuer Bewegung zwischen Holzpoltern [h]
        tMV = 0.0011 * (DP**0.764) * NM
        tPL = 0.007 * NM  # Vorbereitungszeit Laden [h]
        tPU = 0.008  # Vorbereitungszeit Entladen [h]
        tLD = 0.0011 * NL  # Ladezeit abhaengig von der Stammzahl [h]
        tUL = 0.008 * NL  # Entladezeit abhaengig von der Stammzahl [h]

        CT = tTE + tMV + tPL + tPU + tLD + tUL  # Zykluszeit [h/Fuhre]

        self.productivity_h = LC / CT  # m3/h

    def calculate_wtw_emissions(self, emission_factors: dict, mode: str):
        self.wtt_emission = 0
        self.ttw_emission = 0


class Truck(Machine):
    def __init__(
        self,
        *args,
        payload_kg,
        load_volume_m3,
        container_weight_kg=0.0,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.type = "truck"
        self.payload_kg = _to_float(payload_kg)
        self.load_volume_m3 = _to_float(load_volume_m3)
        self.container_weight_kg = _to_float(container_weight_kg)

    def calculate_eol_emissions(self, materials: list[dict], emission_factors: dict):
        super().calculate_eol_emissions(materials, emission_factors)

    def calculate_production_emissions(self, materials: list[dict], emission_factors: dict):
        if self.electric:
            production_total = self.mass_kg * self.production_factor
            self.production_emission = self._divide_by_production_output(
                production_total
            )
            return

        self.production_emission = self._divide_by_production_output(self._production_total_with_autonomy(self._net_base_mass_kg() * self.production_factor))

    def calculate_maintenance_emissions(self, materials: list[dict], emission_factors: dict):
        maintenance_factor = (
            self.maintenance_factor
            if self.maintenance_factor > 0
            else self.production_factor * self.maintenance_factor_percentage
        )
        maintenance_total = self._net_base_mass_kg() * maintenance_factor
        self.maintenance_emission = self._divide_by_production_output(maintenance_total)

    @staticmethod
    def _truck_cycle_time_h(
        forest_distance_km,
        street_distance_km,
        unloading_time_reduction_share=0.0,
        empty_return_reduction_share=0.0,
    ):
        loading_time_h = 54.0 / 60.0
        unloading_time_h = (19.0 / 60.0) * (1 - max(0.0, min(_to_float(unloading_time_reduction_share), 1.0)))
        v_empty_forest_kmh = 15
        v_loaded_forest_kmh = 13
        v_empty_street_kmh = 70
        v_loaded_street_kmh = 50

        loaded_return_percentage = max(0.0, min(_to_float(empty_return_reduction_share), 1.0))

        street_return_time_h = street_distance_km * ((1 - loaded_return_percentage) / v_empty_street_kmh + loaded_return_percentage / v_loaded_street_kmh)

        travel_time_h = forest_distance_km / v_empty_forest_kmh + forest_distance_km / v_loaded_forest_kmh + street_distance_km / v_loaded_street_kmh + street_return_time_h
        return travel_time_h + loading_time_h + unloading_time_h

    @staticmethod
    def _truck_forest_fc_l_km(slope_percent, loaded):
        slope = max(0.0, _to_float(slope_percent))
        if loaded:
            return 5.1276 * math.exp(-0.551 * slope)
        return 0.4745 * math.exp(0.1277 * slope)

    @staticmethod
    def _truck_diesel_per_cycle_l(
        forest_distance_km,
        street_distance_km,
        forest_slope_percent,
        unloading_time_reduction_share=0.0,
        empty_return_reduction_share=0.0,
    ):
        fc_empty_forest = Truck._truck_forest_fc_l_km(forest_slope_percent, loaded=False)
        fc_loaded_forest = Truck._truck_forest_fc_l_km(forest_slope_percent, loaded=True)

        # GUIMARÃES et al. [L/km].
        fc_empty_street = 0.53
        fc_loaded_street = 0.78

        loaded_return_percentage = max(0.0, min(_to_float(empty_return_reduction_share), 1.0))

        street_return_l = street_distance_km * ((1 - loaded_return_percentage) * fc_empty_street + loaded_return_percentage * fc_loaded_street)

        loading_time_h = 54.0 / 60.0
        unloading_time_h = (19.0 / 60.0) * (1 - max(0.0, min(_to_float(unloading_time_reduction_share), 1.0)))
        non_driving_l = AUMEIER_LOADING_UNLOADING_DIESEL_L_PER_H * (
            loading_time_h + unloading_time_h
        )

        return forest_distance_km * (fc_empty_forest + fc_loaded_forest) + street_distance_km * fc_loaded_street + street_return_l + non_driving_l

    def recuperation(self, forest_distance_km, forest_slope_percent):
        if not self.electric:
            return 0.0

        elevation_gain_m = max(
            0.0,
            _to_float(forest_distance_km) * 1000 * _to_float(forest_slope_percent) / 100,
        )
        if elevation_gain_m <= 0:
            return 0.0

        reference_recuperation_kwh = max(
            0.0,
            1.3 * AUMEIER_TRUCK_LOADED_GROSS_MASS_T - 0.67,
        )
        return reference_recuperation_kwh * (elevation_gain_m / LECHNER_RECUP_REFERENCE_HEIGHT_M)

    def apply_use_case_to_machine(self, use_case_row: dict):
        forest_distance = _to_float(use_case_row["forest_distance_km"])
        street_distance = _to_float(use_case_row["street_distance_km"])
        forest_slope_percent = _to_float(
            use_case_row.get("forest_road_gradient_percent"),
            default=0.0,
        )
        unloading_time_reduction_share = _to_float(
            use_case_row.get("terminal_handling_time_reduction_share"),
            default=0.0,
        )
        empty_return_reduction_share = max(
            0.0,
            min(
                _to_float(
                    use_case_row.get("empty_return_reduction_share"),
                    default=0.0,
                ),
                1.0,
            ),
        )
        load_volume = self.load_volume_m3
        if load_volume <= 0 and self.payload_kg > 0:
            load_volume = (self.payload_kg / 1000) / WOOD_DENSITY_T_M3
        if load_volume <= 0:
            raise ValueError(f"{self.machine_id} requires load_volume_m3 > 0")

        cycle_time_h = self._truck_cycle_time_h(
            forest_distance,
            street_distance,
            unloading_time_reduction_share,
            empty_return_reduction_share,
        )
        effective_load_volume = load_volume * (1 + empty_return_reduction_share)
        self.productivity_h = effective_load_volume / cycle_time_h

        diesel_equivalent_per_cycle_l = self._truck_diesel_per_cycle_l(
            forest_distance,
            street_distance,
            forest_slope_percent,
            unloading_time_reduction_share,
            empty_return_reduction_share,
        )

        if self.electric:
            # Pandur supplies the gradient-sensitive forest-road consumption,
            # Guimaraes the public-road consumption, and Aumeier the loading
            # consumption. The common drivetrain-efficiency factor converts
            # that diesel-equivalent gross demand to BEV energy. Recuperation
            # on the loaded downhill section is subtracted afterwards. Grid
            # charging losses are applied to the resulting vehicle demand.
            gross_cycle_energy_kwh = (
                diesel_equivalent_per_cycle_l
                * DIESEL_TO_ELECTRIC_KWH_PER_L
            )
            recuperated_kwh = self.recuperation(forest_distance, forest_slope_percent)
            net_cycle_energy_kwh = max(gross_cycle_energy_kwh - recuperated_kwh, 0.0)
            grid_cycle_energy_kwh = net_cycle_energy_kwh * CHARGING_LOSS_FACTOR
            self.power_consumption_kwh_h = grid_cycle_energy_kwh / cycle_time_h if cycle_time_h > 0 else 0
            self.power_consumption_kwh_m3 = grid_cycle_energy_kwh / effective_load_volume
            self.diesel_l_h = 0
            self.consumption_l_m3 = 0
        else:
            self.diesel_l_h = diesel_equivalent_per_cycle_l / cycle_time_h
            self.consumption_l_m3 = diesel_equivalent_per_cycle_l / effective_load_volume

        self._apply_autonomy_adjustments()

    def calculate_wtw_emissions(self, emission_factors: dict, mode: str):
        electricity_mix = _factor(emission_factors, "electricity_mix")
        diesel_density = _factor(emission_factors, "diesel_wtt_density")
        diesel_heating_value = _factor(emission_factors, "diesel_wtt_heating_value")
        diesel_wtt = _factor(emission_factors, "diesel_wtt")
        diesel_ttw = _factor(emission_factors, "diesel_ttw")

        if self.electric:
            if mode == "wtt":
                self.wtt_emission = self.power_consumption_kwh_m3 * electricity_mix
            elif mode == "ttw":
                self.ttw_emission = 0
            return

        if self.machine_id == "truck_efuel":
            if mode == "wtt":
                # Labunski et al. (2024), Table A2, p. 13:
                # mean of all eight German 2030 scenarios = 1.28075 kg CO2e/l.
                efuel_wtt_2030_de = _factor(emission_factors, "efuel_wtt_2030_de")
                self.wtt_emission = self.consumption_l_m3 * efuel_wtt_2030_de
            elif mode == "ttw":
                self.ttw_emission = 0
            return

        if mode == "ttw" and self.ttw_zero:
            self.ttw_emission = 0
            return

        if mode == "wtt":
            emission_factor = diesel_wtt
        elif mode == "ttw":
            emission_factor = diesel_ttw
        else:
            return

        emission = super().calculate_emission(
            self.diesel_l_h,
            diesel_density,
            diesel_heating_value,
            emission_factor,
        )
        if mode == "wtt":
            self.wtt_emission = emission
        elif mode == "ttw":
            self.ttw_emission = emission


class TruckTrailer(Machine):
    def __init__(self, *args, load_volume_m3, **kwargs):
        super().__init__(*args, **kwargs)
        self.type = "truck_trailer"
        self.load_volume_m3 = _to_float(load_volume_m3)

    def _material_model_ids(self):
        model_ids = super()._material_model_ids()
        if self.machine_id == "truck_trailer_intermodal_container":
            model_ids.append("truck_trailer")
        return model_ids

    def calculate_eol_emissions(self, materials: list[dict], emission_factors: dict):
        super().calculate_eol_emissions(materials, emission_factors)

    def calculate_production_emissions(self, materials: list[dict], emission_factors: dict):
        trailer_production_factor = 1.57
        self.production_emission = self._divide_by_production_output(self.mass_kg * trailer_production_factor)

    def calculate_maintenance_emissions(self, materials: list[dict], emission_factors: dict):
        self.maintenance_emission = 0.0

    def apply_use_case_to_machine(self, use_case_row: dict):
        forest_distance = _to_float(use_case_row["forest_distance_km"])
        street_distance = _to_float(use_case_row["street_distance_km"])

        if self.load_volume_m3 <= 0:
            raise ValueError("truck_trailer requires load_volume_m3 > 0")

        cycle_time_h = Truck._truck_cycle_time_h(forest_distance, street_distance)
        self.productivity_h = self.load_volume_m3 / cycle_time_h

    def calculate_wtw_emissions(self, emission_factors: dict, mode: str):
        self.wtt_emission = 0
        self.ttw_emission = 0


class CableYarder(Machine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.type = "cable_yarder"

    def calculate_eol_emissions(self, materials: list[dict], emission_factors: dict):
        super().calculate_eol_emissions(materials, emission_factors)
        if self.machine_id == "cable_yarder_recuperating":
            storage_systems = max(self.number_of_batteries_over_lifetime, 0.0)
            storage_eol_total = (
                self._supercapacitor_cells_per_system()
                * _factor(emission_factors, "supercapacitor_cell_eol_credit_gottardo")
                * storage_systems
            )
            self.eol_emission += storage_eol_total / self._lifetime_output_m3()

    def _supercapacitor_cells_per_system(self):
        if self.machine_id != "cable_yarder_recuperating" or self.battery_capacity <= 0:
            return 0
        # Gottardo et al. assess one 5.12 Wh cell; round up to meet the assumed carriage capacity.
        return math.ceil(self.battery_capacity / SUPERCAPACITOR_CELL_CAPACITY_KWH)

    def _energy_storage_production_total(self, emission_factors: dict, storage_systems):
        if storage_systems <= 0:
            return 0.0
        if self.machine_id == "cable_yarder_recuperating":
            return (
                self._supercapacitor_cells_per_system()
                * _factor(emission_factors, "supercapacitor_cell_prod_gottardo")
                * storage_systems
            )
        if self.electric:
            return self.battery_capacity * _factor(emission_factors, "lfp_battery_prod_energy") * storage_systems
        return 0.0

    def _material_model_ids(self):
        model_ids = super()._material_model_ids()
        if self.machine_id in {"cable_yarder_electric", "cable_yarder_recuperating"}:
            model_ids.append("cable_yarder_diesel")
        return model_ids

    def _machine_body_mass_kg(self):
        if self.machine_id == "cable_yarder_electric":
            # The 31 t total mass includes the initial battery. Model the machine
            # body and battery separately to avoid counting the battery twice.
            return max(self.mass_kg - self.battery_mass, 0.0)
        return self.mass_kg

    def _eol_material_mass_kg(self, row: dict):
        mass_kg = super()._eol_material_mass_kg(row)
        if (
            self.machine_id in {"cable_yarder_electric", "cable_yarder_recuperating"}
            and row.get("machine_id") == "cable_yarder_diesel"
        ):
            mass_kg *= self._machine_body_mass_kg() / CABLE_YARDER_DIESEL_REFERENCE_MASS_KG
        return mass_kg

    def calculate_production_emissions(self, materials: list[dict], emission_factors: dict):
        production_total = self._machine_body_mass_kg() * self.production_factor
        if self.machine_id in {"cable_yarder_electric", "cable_yarder_recuperating"}:
            initial_storage_systems = min(max(self.number_of_batteries_over_lifetime, 0.0), 1.0)
            production_total += self._energy_storage_production_total(
                emission_factors,
                initial_storage_systems,
            )
        self.production_emission = self._divide_by_production_output(production_total)

    def calculate_maintenance_emissions(self, materials: list[dict], emission_factors: dict):
        machine_body_total = (
            self._machine_body_mass_kg()
            * self.production_factor
            * self.maintenance_factor_percentage
        )
        replacement_storage_systems = max(self.number_of_batteries_over_lifetime - 1.0, 0.0)
        maintenance_total = machine_body_total + self._energy_storage_production_total(
            emission_factors,
            replacement_storage_systems,
        )
        self.maintenance_emission = self._divide_by_production_output(maintenance_total)

    def apply_use_case_to_machine(self, use_case_row: dict):
        line_length_m = _to_float(use_case_row["stand_to_logpile_m"])
        if line_length_m <= 0:
            return

        # Werner 2017 Annex A.4 gives 17.6 / 13.2 / 7.2 m3/PMH at
        # 300 / 450 / 600 m line length. The specific time demand
        # (minutes per m3) is interpolated linearly between these points.
        # Extrapolating time demand instead of productivity keeps the
        # resulting productivity positive for line lengths above 600 m.
        support_distances = (300.0, 450.0, 600.0)
        support_time_demands = tuple(60.0 / productivity for productivity in (17.6, 13.2, 7.2))

        if line_length_m <= support_distances[1]:
            lower_index, upper_index = 0, 1
        else:
            lower_index, upper_index = 1, 2

        distance_delta = support_distances[upper_index] - support_distances[lower_index]
        time_demand_slope = (support_time_demands[upper_index] - support_time_demands[lower_index]) / distance_delta
        time_demand_min_m3 = support_time_demands[lower_index] + (line_length_m - support_distances[lower_index]) * time_demand_slope

        self.productivity_h = 60.0 / time_demand_min_m3

        if self.machine_id == "cable_yarder_recuperating":
            self.productivity_h *= CABLE_YARDER_RECUP_CARRIAGE_PRODUCTIVITY_FACTOR
            self.diesel_l_h *= CABLE_YARDER_RECUP_CARRIAGE_FUEL_FACTOR
            self.consumption_l_m3 = self.diesel_l_h / self.productivity_h if self.productivity_h > 0 else 0

    def calculate_wtw_emissions(self, emission_factors: dict, mode: str):

        electricity_mix = _factor(emission_factors, "electricity_mix")
        diesel_density = _factor(emission_factors, "diesel_wtt_density")
        diesel_heating_value = _factor(emission_factors, "diesel_wtt_heating_value")
        diesel_wtt = _factor(emission_factors, "diesel_wtt")
        diesel_ttw = _factor(emission_factors, "diesel_ttw")

        emission = 0
        match self.electric:
            case True:
                if mode == "wtt":
                    self._recalculate_power_consumption_kwh_m3()
                    emission = self.power_consumption_kwh_m3 * electricity_mix
                elif mode == "ttw":
                    emission = 0
            case False:
                density = diesel_density
                heat_capacity = diesel_heating_value

                if mode == "wtt":
                    emission_factor = diesel_wtt
                elif mode == "ttw":
                    emission_factor = diesel_ttw
                emission = super().calculate_emission(
                    self.diesel_l_h,
                    density,
                    heat_capacity,
                    emission_factor,
                )

        if mode == "wtt":
            self.wtt_emission = emission
        elif mode == "ttw":
            self.ttw_emission = emission


class Rail(Machine):
    def __init__(
        self,
        *args,
        wagon_lifetime_years,
        wagon_km_per_year,
        payload_kg,
        load_volume_m3=0.0,
        container_weight_kg=0.0,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.type = "rail"
        self.wagon_lifetime_years = _to_float(wagon_lifetime_years)
        self.wagon_km_per_year = _to_float(wagon_km_per_year)
        self.payload_kg = _to_float(payload_kg)
        self.load_volume_m3 = _to_float(load_volume_m3)
        self.container_weight_kg = _to_float(container_weight_kg)
        self.distance_km = 100
        self.rail_mass_t_per_m3 = WOOD_DENSITY_T_M3

    def calculate_production_emissions(self, materials: list[dict], emission_factors: dict):
        if (
            self.mass_kg <= 0
            or self.payload_kg <= 0
            or self.wagon_lifetime_years <= 0
            or self.wagon_km_per_year <= 0
            or self.rail_mass_t_per_m3 <= 0
        ):
            self.production_emission = 0.0
            return

        # Convert the wagon payload from tonnes to the equivalent transported
        # solid timber volume so the allocation is calculated directly per m3.
        payload_m3 = (self.payload_kg / 1000) / self.rail_mass_t_per_m3
        emission_wagon_m3km = (
            self.mass_kg
            * _factor(emission_factors, "steel_hot_rolled_strip_a1a3")
        ) / (
            self.wagon_lifetime_years
            * self.wagon_km_per_year
            * payload_m3
        )
        emission_locomotive_m3km = (
            _factor(emission_factors, "rail_gv_vehicle_production")
            / 1000
            * self.rail_mass_t_per_m3
        )
        self.production_emission = (
            emission_wagon_m3km + emission_locomotive_m3km
        ) * self.distance_km

    def calculate_maintenance_emissions(self, materials: list[dict], emission_factors: dict):
        self.maintenance_emission = (
            self.production_emission * self.maintenance_factor_percentage
        )

    def apply_use_case_to_machine(self, use_case_row: dict):
        rail_distance = _to_float(use_case_row["rail_km"])
        if rail_distance > 0:
            self.distance_km = rail_distance

        if self.machine_id != "rail_intermodal_container":
            return

        container_load_volume = self.load_volume_m3
        load_factor_improvement = max(
            0.0,
            _to_float(
                use_case_row.get("empty_return_reduction_share"),
                default=0.0,
            ),
        )
        if self.container_weight_kg > 0 and container_load_volume > 0:
            gross_mass_t_per_m3 = WOOD_DENSITY_T_M3 + (self.container_weight_kg / 1000) / container_load_volume
            self.rail_mass_t_per_m3 = gross_mass_t_per_m3 / (1 + load_factor_improvement)

    def calculate_wtw_emissions(self, emission_factors: dict, mode: str):
        rail_ttw = _factor(emission_factors, "rail_gv_ttw")
        total_energy = _factor(emission_factors, "rail_gv_energy_intensity")
        diesel_share = _factor(emission_factors, "rail_diesel_share")
        electric_share = _factor(emission_factors, "rail_electric_share")
        diesel_wtt_factor = _factor(emission_factors, "diesel_wtt")
        electricity_mix = _factor(emission_factors, "electricity_mix")

        electricity_factor = electricity_mix * 1000  # kg -> g
        diesel_energy = total_energy * diesel_share
        electric_energy = total_energy * electric_share

        if mode == "wtt":
            specific_wtt = (
                diesel_energy * diesel_wtt_factor
                + electric_energy * electricity_factor
            )
            self.wtt_emission = (
                specific_wtt
                * self.rail_mass_t_per_m3
                * self.distance_km
                / 1000
            )
        elif mode == "ttw":
            # The published aggregate rail TTW factor is used directly.
            self.ttw_emission = (
                rail_ttw
                * self.rail_mass_t_per_m3
                * self.distance_km
                / 1000
            )

    def calculate_eol_emissions(self, materials: list[dict], emission_factors: dict):
        locomotive_eol_to_production_ratio = _factor(
            emission_factors, "rail_eol_to_production_ratio"
        )
        self.eol_emission = (
            self.production_emission * locomotive_eol_to_production_ratio
        )


class TerminalHandling(Machine):
    def __init__(self, *args, load_volume_m3, **kwargs):
        super().__init__(*args, **kwargs)
        self.type = "terminal_handling"
        self.load_volume_m3 = _to_float(load_volume_m3)
        self.handling_events = 2.0
        self.handling_time_h = (19.0 / 60.0) * self.handling_events

    def calculate_eol_emissions(self, materials: list[dict], emission_factors: dict):
        super().calculate_eol_emissions(materials, emission_factors)

    def apply_use_case_to_machine(self, use_case_row: dict):
        load_volume = self.load_volume_m3
        if load_volume <= 0:
            raise ValueError(f"{self.machine_id} requires load_volume_m3 > 0")
        if self.machine_id == "terminal_handling_intermodal_container":
            reduction_share = max(
                0.0,
                min(
                    _to_float(
                        use_case_row.get("terminal_handling_time_reduction_share"),
                        default=0.0,
                    ),
                    1.0,
                ),
            )
        else:
            reduction_share = 0.0

        self.handling_time_h = (19.0 / 60.0) * self.handling_events * (1 - reduction_share)
        self.productivity_h = load_volume / self.handling_time_h

    def calculate_wtw_emissions(self, emission_factors: dict, mode: str):
        diesel_density = _factor(emission_factors, "diesel_wtt_density")
        diesel_heating_value = _factor(emission_factors, "diesel_wtt_heating_value")
        diesel_wtt = _factor(emission_factors, "diesel_wtt")
        diesel_ttw = _factor(emission_factors, "diesel_ttw")

        if self.productivity_h <= 0:
            return

        if mode == "wtt":
            emission_factor = diesel_wtt
        elif mode == "ttw":
            emission_factor = diesel_ttw
        else:
            return

        emission = super().calculate_emission(
            AUMEIER_LOADING_UNLOADING_DIESEL_L_PER_H,
            diesel_density,
            diesel_heating_value,
            emission_factor,
        )
        if mode == "wtt":
            self.wtt_emission = emission
        elif mode == "ttw":
            self.ttw_emission = emission


class IntermodalContainer(Machine):
    REMOVED_STAKES_MASS_KG = 552.0
    LIFETIME_CYCLES = 2500.0

    @classmethod
    def calculate_timber_load_volume_m3(cls, base_load_volume_m3, container_mass_kg):
        base_load_volume = _to_float(base_load_volume_m3)
        container_mass = _to_float(container_mass_kg)
        net_additional_mass_t = (
            max(container_mass - cls.REMOVED_STAKES_MASS_KG, 0.0) / 1000
        )
        load_volume = base_load_volume - net_additional_mass_t / WOOD_DENSITY_T_M3
        if load_volume <= 0:
            raise ValueError("Intermodal timber load volume must be positive")
        return load_volume

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.type = "intermodal_container"

    def calculate_eol_emissions(self, materials: list[dict], emission_factors: dict):
        super().calculate_eol_emissions(materials, emission_factors)

    def calculate_production_emissions(self, materials: list[dict], emission_factors: dict):
        production_total = self.mass_kg * _factor(emission_factors, "steel_heavy_plate_a1a3")
        self.production_emission = production_total / self.lifetime_m3 if self.lifetime_m3 > 0 else 0.0

    def calculate_maintenance_emissions(self, materials: list[dict], emission_factors: dict):
        self.maintenance_emission = 0

    def apply_use_case_to_machine(self, use_case_row: dict):
        pass

    def calculate_wtw_emissions(self, emission_factors: dict, mode: str):
        self.wtt_emission = 0
        self.ttw_emission = 0


class Winch(Machine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.type = "forest_winch"

    def calculate_eol_emissions(self, materials: list[dict], emission_factors: dict):
        super().calculate_eol_emissions(materials, emission_factors)

    def apply_use_case_to_machine(self, use_case_row: dict):

        self._apply_autonomy_adjustments()

    def calculate_wtw_emissions(self, emission_factors: dict, mode: str):
        self.wtt_emission = 0
        self.ttw_emission = 0


__all__ = [
    "Forwarder",
    "Tractor",
    "Harvester",
    "Chainsaw",
    "ForestTrailer",
    "Truck",
    "TruckTrailer",
    "CableYarder",
    "Rail",
    "TerminalHandling",
    "IntermodalContainer",
    "Winch",
]
