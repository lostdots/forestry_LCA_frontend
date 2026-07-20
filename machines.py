import math

import pandas as pd

DIESEL_TO_ELECTRIC_KWH_PER_L = 4.42
CHARGING_LOSS_FACTOR = 1.10
DIESEL_LOWER_HEATING_KWH_PER_L = 0.84 * 11.65
WOOD_DENSITY_T_M3 = 0.960
INTERMODAL_CONTAINER_DEFAULT_LOAD_VOLUME_M3 = 25.6
CABLE_YARDER_REFERENCE_MASS_KG = 31000.0
CABLE_YARDER_RECUP_CARRIAGE_PRODUCTIVITY_FACTOR = 22.5 / 21.4
CABLE_YARDER_RECUP_CARRIAGE_FUEL_FACTOR = 0.88 / 1.27
AUMEIER_TRUCK_REFERENCE_CYCLE_TIME_H = (27.0 + 15.0 + 54.0 + 19.0 + 38.0 + 19.0) / 60.0
AUMEIER_TRUCK_DIESEL_L_PER_H = 70.0 / AUMEIER_TRUCK_REFERENCE_CYCLE_TIME_H
AUMEIER_TRUCK_BEV_KWH_PER_H = 230 / AUMEIER_TRUCK_REFERENCE_CYCLE_TIME_H
LECHNER_RECUP_REFERENCE_HEIGHT_M = 550.0
# Konrad Pully brochure, p. 4: 3950 kg and 140 PS. Capacity and
# lifetime parameters below are explicit model assumptions.
REFERENCE_FORWARDER_MASS_KG = 11322.0
REFERENCE_FORWARDER_LOAD_VOLUME_M3 = 12.0
PULLY_ENGINE_POWER_KW = 140.0 * 0.73549875
PULLY_DIESEL_L_H = 4.4539 + 0.0562 * PULLY_ENGINE_POWER_KW
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
        repair_factor,
        ttw_zero,
        production_model,
        engine_mass_ICE_kg,
        autonomy_subsystem_mass_kg=0,
        autonomy_subsystem_power_w=0,
        autonomy_subsystem_production_kgco2e=0,
        autonomy_subsystem_eol_kgco2e_kg=0,
        autonomy_productivity_gain_share=0,
        autonomy_energy_saving_share=0,
        autonomy_onboard_electric_efficiency=0.20,
        cab_removed_mass_kg=0,
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
        self.repair_factor = _to_float(repair_factor)

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
        self._autonomy_adjustments_applied = False

    def _net_base_mass_kg(self):
        return max(0.0, self.mass_kg - self.cab_removed_mass_kg)

    def _effective_mass_kg(self):
        return self._net_base_mass_kg() + self.autonomy_subsystem_mass_kg

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
            return REFERENCE_FORWARDER_MASS_KG
        if base_class_machine_id == "truck_diesel":
            return 8000.0
        return self.mass_kg

    def _recalculate_power_consumption_kwh_m3(self):
        if self.power_consumption_kwh_h <= 0 and self.diesel_l_h > 0:
            self.power_consumption_kwh_h = self.diesel_l_h * DIESEL_TO_ELECTRIC_KWH_PER_L * CHARGING_LOSS_FACTOR

        self.power_consumption_kwh_m3 = (
            self.power_consumption_kwh_h / self.productivity_h if self.productivity_h > 0 and self.power_consumption_kwh_h > 0 else 0
        )

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

        self.maintenance_emission = self._divide_by_production_output(self._net_base_mass_kg() * self.production_factor * self.repair_factor)

    def _divide_by_production_output(self, emission_total):
        denominator = self.lifetime_h * self.productivity_h
        if denominator <= 0:
            return 0.0
        return emission_total / denominator

    def calculate_eol_emissions(self, materials: list[dict], emission_factors: dict):
        material_rows = [row for row in materials if row["machine_id"] in self._material_model_ids()]

        eol_total = 0.0
        for row in material_rows:
            factor_id = row.get("eol_factor_id")
            if not factor_id or pd.isna(factor_id):
                continue

            factor = _factor(emission_factors, factor_id)
            mass_kg = _to_float(row.get("mass_kg"))
            if self.machine_id == "forwarder_pully" and row.get("machine_id") == "forwarder_diesel":
                # No Pully-specific material inventory is available. Reuse the
                # diesel-forwarder composition, scaled to the documented 3950 kg.
                mass_kg *= self.mass_kg / REFERENCE_FORWARDER_MASS_KG

            autonomous_base_class_machine_id = self._autonomous_base_class_machine_id()
            if autonomous_base_class_machine_id and row.get("machine_id") == autonomous_base_class_machine_id:
                reference_mass = self._autonomous_base_reference_mass_kg()
                if reference_mass > 0:
                    mass_kg *= self._net_base_mass_kg() / reference_mass
            if factor_id == "tractor_eol_recovery_share":
                production_factor = _factor(emission_factors, row.get("production_factor_id"))
                if production_factor <= 0:
                    production_factor = self.production_factor
                eol_total += mass_kg * production_factor * factor
                continue

            recycling_rate = _to_float(row.get("recycling_rate"), default=1.0)
            if mass_kg <= 0:
                continue

            if row.get("component") == "battery":
                mass_kg *= self.number_of_batteries_over_lifetime

            eol_total += mass_kg * recycling_rate * factor

        eol_total += self.autonomy_subsystem_mass_kg * self.autonomy_subsystem_eol_kgco2e_kg
        self.eol_emission = eol_total / self._lifetime_output_m3()

    def _material_model_ids(self):
        model_ids = [self.machine_id]

        if self.machine_id in {"rail", "rail_intermodal_container"}:
            model_ids.append("rail_rnoos_wagon")
        elif self.machine_id == "forest_trailer":
            model_ids.append("forest_trailer_loader_crane")
        elif self.machine_id.startswith("tractor_electric"):
            model_ids.append("tractor_electric")
        elif self.machine_id.startswith("tractor_diesel"):
            model_ids.append("tractor_diesel")
        elif self.machine_id == "truck_trailer":
            model_ids.append("truck_trailer")
        elif self.machine_id == "forwarder_pully":
            model_ids.append("forwarder_diesel")
        elif self.machine_id in {"cable_yarder_electric", "cable_yarder_recuperating"}:
            model_ids.append("cable_yarder_diesel")

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

    def calculate_production_emissions(self, materials: list[dict], emission_factors: dict):
        if self.electric:
            emission_housing = (self.mass_kg - self.engine_mass_ICE_kg) * self.production_factor
            emission_battery = self.battery_capacity * _factor(emission_factors, "lfp_battery_prod_energy") * self.number_of_batteries_over_lifetime
            self.production_emission = self._divide_by_production_output(emission_housing + emission_battery)
            return

        self.production_emission = self._divide_by_production_output(self._production_total_with_autonomy(self._net_base_mass_kg() * self.production_factor))

    def calculate_maintenance_emissions(self, materials: list[dict], emission_factors: dict):
        if self.electric:
            emission_housing = (self.mass_kg - self.engine_mass_ICE_kg) * self.production_factor
            self.maintenance_emission = self._divide_by_production_output(emission_housing * self.repair_factor)
            return

        self.maintenance_emission = self._divide_by_production_output(self._net_base_mass_kg() * self.production_factor * self.repair_factor)

    def apply_use_case_to_machine(self, use_case_row: dict):
        extraction_distance = _to_float(use_case_row["stand_to_logpile_m"])
        self.productivity_h = -0.0042 * extraction_distance + 16.206

        if self.machine_id == "forwarder_pully":
            if self.load_volume_m3 <= 0:
                raise ValueError("forwarder_pully requires load_volume_m3 > 0")

            # The brochure does not state capacity. A 4 m3 geometric estimate
            # is scaled against a 12 m3 medium-forwarder reference.
            self.productivity_h *= self.load_volume_m3 / REFERENCE_FORWARDER_LOAD_VOLUME_M3
            self.diesel_l_h = PULLY_DIESEL_L_H
            self.consumption_l_m3 = self.diesel_l_h / self.productivity_h
            self._apply_autonomy_adjustments()
            return

        # Meissl (2019), Formula 10: specific forwarder fuel use [l/Efm].
        # The reported reference piece volume is 0.46 Efm.
        piece_volume_m3 = _to_float(use_case_row.get("piece_volume_m3"), default=0.46)
        if piece_volume_m3 <= 0:
            piece_volume_m3 = 0.46

        self.consumption_l_m3 = 0.173 / piece_volume_m3 + 0.00103 * extraction_distance

        if self.electric:
            self._set_electric_consumption_from_diesel_equivalent()
        else:
            self.diesel_l_h = self.consumption_l_m3 * self.productivity_h

        self._apply_autonomy_adjustments()

    def _set_electric_consumption_from_diesel_equivalent(self):
        self.power_consumption_kwh_m3 = self.consumption_l_m3 * DIESEL_TO_ELECTRIC_KWH_PER_L * CHARGING_LOSS_FACTOR
        self.power_consumption_kwh_h = self.power_consumption_kwh_m3 * self.productivity_h if self.productivity_h > 0 else 0

    def calculate_emission(self, emission_factors: dict, mode: str):

        electricity_mix = _factor(emission_factors, "electricity_mix")
        diesel_density = _factor(emission_factors, "diesel_wtt_density")
        diesel_heating_value = _factor(emission_factors, "diesel_wtt_heating_value")
        diesel_wtt = _factor(emission_factors, "diesel_wtt")
        diesel_ttw = _factor(emission_factors, "diesel_ttw")
        heavy_truck_wtt = _factor(emission_factors, "heavy_truck_wtt_tkm") / 1000
        heavy_truck_ttw = _factor(emission_factors, "heavy_truck_ttw_tkm") / 1000

        emission = 0
        truck_factor = 0
        match self.electric:
            case True:
                if mode == "wtt":
                    self._recalculate_power_consumption_kwh_m3()
                    emission = self.power_consumption_kwh_m3 * electricity_mix
                    truck_factor = heavy_truck_wtt  # kg CO2e / tkm
                elif mode == "ttw":
                    emission = 0
                    truck_factor = heavy_truck_ttw  # kg CO2e / tkm
            case False:
                density = diesel_density
                heat_capacity = diesel_heating_value

                if mode == "wtt":
                    emission_factor = diesel_wtt
                    truck_factor = heavy_truck_wtt  # kg CO2e / tkm

                elif mode == "ttw":
                    emission_factor = diesel_ttw
                    truck_factor = heavy_truck_ttw  # kg CO2e / tkm

                emission = super().calculate_emission(
                    self.diesel_l_h,
                    density,
                    heat_capacity,
                    emission_factor,
                )

        # Ueberstellung
        machine_mass_t = self._effective_mass_kg() / 1000

        tkm_per_operating_hour = (machine_mass_t * self.relocation_distance) / self.operating_hours_per_day

        relocation = (tkm_per_operating_hour * truck_factor) / self.productivity_h

        if mode == "wtt":
            self.wtt_emission = emission + relocation
        elif mode == "ttw":
            self.ttw_emission = emission + relocation


class Tractor(Machine):
    def __init__(self, *args, load_volume_m3, **kwargs):
        super().__init__(*args, **kwargs)
        self.type = "tractor"
        self.load_volume_m3 = _to_float(load_volume_m3)

    def calculate_production_emissions(self, materials: list[dict], emission_factors: dict):
        if self.electric:
            emission_housing = (self.mass_kg - self.engine_mass_ICE_kg) * self.production_factor
            emission_battery = self.battery_mass * _factor(emission_factors, "li_ion_battery_prod_mass") * self.number_of_batteries_over_lifetime
            self.production_emission = self._divide_by_production_output(emission_housing + emission_battery)
            return

        self.production_emission = self._divide_by_production_output(self._production_total_with_autonomy(self._net_base_mass_kg() * self.production_factor))

    def calculate_maintenance_emissions(self, materials: list[dict], emission_factors: dict):
        if self.electric:
            emission_housing = (self.mass_kg - self.engine_mass_ICE_kg) * self.production_factor
            self.maintenance_emission = self._divide_by_production_output(emission_housing * self.repair_factor)
            return

        self.maintenance_emission = self._divide_by_production_output(self._net_base_mass_kg() * self.production_factor * self.repair_factor)

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
                diesel_empty_street = 48 / 100  # L/km
                diesel_loaded_street = 71 / 100  # L/km

                non_driving_time = tPL + tPU + tLD + tUL

                t_wald = forest_distance * (1 / v_empty_forest_kmh + 1 / v_loaded_forest_kmh)
                diesel_per_drive = HFC_wald * (t_wald + non_driving_time) + diesel_empty_street * street_distance + diesel_loaded_street * street_distance

                self.diesel_l_h = diesel_per_drive / CT

                # optional zur Kontrolle
                self.consumption_l_m3 = diesel_per_drive / LC

        if self.electric:
            self._set_electric_consumption_from_diesel_equivalent()

    def calculate_emission(self, emission_factors: dict, mode: str):

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

    def calculate_production_emissions(self, materials: list[dict], emission_factors: dict):
        if self.electric:
            emission_housing = (self.mass_kg - self.engine_mass_ICE_kg) * self.production_factor
            emission_battery = self.battery_capacity * _factor(emission_factors, "lfp_battery_prod_energy") * self.number_of_batteries_over_lifetime
            self.production_emission = self._divide_by_production_output(emission_housing + emission_battery)
            return

        self.production_emission = self._divide_by_production_output(self._production_total_with_autonomy(self._net_base_mass_kg() * self.production_factor))

    def calculate_maintenance_emissions(self, materials: list[dict], emission_factors: dict):
        if self.electric:
            emission_housing = (self.mass_kg - self.engine_mass_ICE_kg) * self.production_factor
            self.maintenance_emission = self._divide_by_production_output(emission_housing * self.repair_factor)
            return

        self.maintenance_emission = self._divide_by_production_output(self._net_base_mass_kg() * self.production_factor * self.repair_factor)

    def apply_use_case_to_machine(self, use_case_row: dict):

        self._apply_autonomy_adjustments()

    def calculate_emission(self, emission_factors: dict, mode: str):

        electricity_mix = _factor(emission_factors, "electricity_mix")
        diesel_density = _factor(emission_factors, "diesel_wtt_density")
        diesel_heating_value = _factor(emission_factors, "diesel_wtt_heating_value")
        diesel_wtt = _factor(emission_factors, "diesel_wtt")
        diesel_ttw = _factor(emission_factors, "diesel_ttw")

        emission = 0
        emission_machine_transport_wtt = 0
        emission_chain_oil_wtt = 0
        emission_machine_transport_ttw = 0
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
                    emission_machine_transport_wtt = 0.095
                    emission_chain_oil_wtt = 0.0818
                elif mode == "ttw":
                    emission_factor = diesel_ttw
                    emission_machine_transport_ttw = 0.245

                emission = super().calculate_emission(
                    self.diesel_l_h,
                    density,
                    heat_capacity,
                    emission_factor,
                )

        if mode == "wtt":
            self.wtt_emission = emission + emission_machine_transport_wtt + emission_chain_oil_wtt
        elif mode == "ttw":
            self.ttw_emission = emission + emission_machine_transport_ttw


class Chainsaw(Machine):
    def __init__(self, *args, gasoline_mix_l_h, chain_oil_l_h, power_consumption_kwh_m3, **kwargs):
        super().__init__(*args, **kwargs)
        self.type = "chainsaw"
        self.gasoline_mix_l_h = _to_float(gasoline_mix_l_h)
        self.chain_oil_l_h = _to_float(chain_oil_l_h)
        self.power_consumption_kwh_m3 = _to_float(power_consumption_kwh_m3)

    def calculate_production_emissions(self, materials: list[dict], emission_factors: dict):
        if self.electric:
            mass_housing = self.mass_kg - self.battery_mass
            emission_housing = self.production_factor * mass_housing
            emission_battery = (
                _factor(emission_factors, "li_ion_battery_prod_energy_nick_manganes") * self.battery_mass * self.number_of_batteries_over_lifetime
            )
            self.production_emission = self._divide_by_production_output(emission_housing + emission_battery)
            return

        self.production_emission = self._divide_by_production_output(self._production_total_with_autonomy(self._net_base_mass_kg() * self.production_factor))

    def calculate_maintenance_emissions(self, materials: list[dict], emission_factors: dict):
        if self.electric:
            self.maintenance_emission = 0.0
            return

        self.maintenance_emission = self._divide_by_production_output(self._net_base_mass_kg() * self.production_factor * self.repair_factor)

    def apply_use_case_to_machine(self, use_case_row: dict):

        self._apply_autonomy_adjustments()

    def calculate_emission(self, emission_factors: dict, mode: str):

        electricity_mix = _factor(emission_factors, "electricity_mix")
        chain_oil_wtt = _factor(emission_factors, "chain_oil_wtt")
        chainsaw_fuel_mix_wtt = _factor(emission_factors, "chainsaw_fuel_mix_wtt_ecoinvent")
        chainsaw_fuel_mix_ttw = _factor(emission_factors, "chainsaw_fuel_mix_ttw_ecoinvent")

        chain_oil_wtt_emission = (self.chain_oil_l_h / self.productivity_h) * chain_oil_wtt

        match self.electric:
            case True:
                if mode == "wtt":
                    self.wtt_emission = (self.power_consumption_kwh_m3 * electricity_mix) + chain_oil_wtt_emission
                elif mode == "ttw":
                    self.ttw_emission = 0
            case False:

                consumption_l_m3 = self.gasoline_mix_l_h / self.productivity_h if self.productivity_h > 0 else 0
                if mode == "wtt":
                    emission_factor = chainsaw_fuel_mix_wtt
                    self.wtt_emission = (emission_factor * consumption_l_m3) + chain_oil_wtt_emission

                elif mode == "ttw":
                    emission_factor = chainsaw_fuel_mix_ttw
                    self.ttw_emission = emission_factor * consumption_l_m3


class ForestTrailer(Machine):
    def __init__(self, *args, payload_kg, load_volume_m3, **kwargs):
        super().__init__(*args, **kwargs)
        self.type = "forest_trailer"
        self.payload_kg = _to_float(payload_kg)
        self.load_volume_m3 = _to_float(load_volume_m3)

    def calculate_production_emissions(self, materials: list[dict], emission_factors: dict):
        trailer_production_factor = 1.57
        loader_crane_emissions = 6768.0
        weight_crane = 3000
        production_total = (self.mass_kg - weight_crane) * trailer_production_factor + loader_crane_emissions
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
        v_empty_forest_kmh = 20  # fuer Forstwege, nicht Rueckung zwischen Poltern
        v_loaded_forest_kmh = 12.5  # fuer Forstwege, nicht Rueckung zwischen Poltern
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

    def calculate_emission(self, emission_factors: dict, mode: str):
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

    def calculate_production_emissions(self, materials: list[dict], emission_factors: dict):
        if self.electric:
            emission_housing = self.mass_kg * self.production_factor
            emission_battery = self.battery_capacity * _factor(emission_factors, "lfp_battery_prod_energy") * self.number_of_batteries_over_lifetime
            self.production_emission = self._divide_by_production_output(emission_housing + emission_battery)
            return

        self.production_emission = self._divide_by_production_output(self._production_total_with_autonomy(self._net_base_mass_kg() * self.production_factor))

    def calculate_maintenance_emissions(self, materials: list[dict], emission_factors: dict):
        self.maintenance_emission = self._divide_by_production_output(self._net_base_mass_kg() * self.production_factor * self.repair_factor)

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

        travel_time_h = forest_distance_km / v_loaded_forest_kmh + street_distance_km / v_loaded_street_kmh + street_return_time_h
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

        # Anttila et al. based starting values for paved/public roads [L/km].
        fc_empty_street = 0.53
        fc_loaded_street = 0.78

        loaded_return_percentage = max(0.0, min(_to_float(empty_return_reduction_share), 1.0))

        street_return_l = street_distance_km * ((1 - loaded_return_percentage) * fc_empty_street + loaded_return_percentage * fc_loaded_street)

        loading_time_h = 54.0 / 60.0
        unloading_time_h = (19.0 / 60.0) * (1 - max(0.0, min(_to_float(unloading_time_reduction_share), 1.0)))
        non_driving_l = AUMEIER_TRUCK_DIESEL_L_PER_H * (loading_time_h + unloading_time_h)

        return forest_distance_km * fc_loaded_forest + street_distance_km * fc_loaded_street + street_return_l + non_driving_l

    def recuperation(self, forest_distance_km, forest_slope_percent):
        if self.machine_id != "truck_bev":
            return 0.0

        forest_height_m = max(0.0, _to_float(forest_distance_km) * 1000 * _to_float(forest_slope_percent) / 100)
        if forest_height_m <= 0:
            return 0.0

        loaded_mass_t = (self.mass_kg + self.payload_kg) / 1000
        reference_recuperation_kwh = max(0.0, 1.3 * loaded_mass_t - 0.67)
        return reference_recuperation_kwh * (forest_height_m / LECHNER_RECUP_REFERENCE_HEIGHT_M)

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
        if self.container_weight_kg > 0:
            load_volume -= (self.container_weight_kg / 1000) / WOOD_DENSITY_T_M3
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

        # Aumeier: the average cycle energy is reduced by recuperation on the
        # loaded downhill forest-road section, scaled to Lechner's 550 m case.
        # The hourly rate is kept constant while use-case distances change
        # productivity through cycle time.
        if self.electric:
            cycle_energy_kwh = AUMEIER_TRUCK_BEV_KWH_PER_H * cycle_time_h
            recuperated_kwh = self.recuperation(forest_distance, forest_slope_percent)
            net_cycle_energy_kwh = max(cycle_energy_kwh - recuperated_kwh, 0.0)
            self.power_consumption_kwh_h = net_cycle_energy_kwh / cycle_time_h if cycle_time_h > 0 else 0
            self.power_consumption_kwh_m3 = net_cycle_energy_kwh / effective_load_volume
            self.diesel_l_h = 0
            self.consumption_l_m3 = 0
        else:
            diesel_per_cycle_l = self._truck_diesel_per_cycle_l(
                forest_distance,
                street_distance,
                forest_slope_percent,
                unloading_time_reduction_share,
                empty_return_reduction_share,
            )
            self.diesel_l_h = diesel_per_cycle_l / cycle_time_h
            self.consumption_l_m3 = diesel_per_cycle_l / effective_load_volume

        self._apply_autonomy_adjustments()

    def calculate_emission(self, emission_factors: dict, mode: str):
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

    def calculate_emission(self, emission_factors: dict, mode: str):
        self.wtt_emission = 0
        self.ttw_emission = 0


class CableYarder(Machine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.type = "cable_yarder"

    def calculate_production_emissions(self, materials: list[dict], emission_factors: dict):
        cable_yarder_materials = [
            ("aluminium_alloy", 578, 8.5),
            ("cast_iron", 6680, 2.0),
            ("chromium_steel", 1700, 6.2),
            ("copper", 51, 4.0),
            ("electronics", 115, 20.0),
            ("flat_glass", 233, 1.4),
            ("low_alloy_steel_1", 18300, 2.43),
            ("low_alloy_steel_2", 16100, 2.43),
            ("synthetic_rubber", 2200, 3.0),
            ("polypropylene", 1020, 2.0),
            ("lead", 295, 2.0),
            ("wire_drawing_steel", 4010, 0.5),
            ("wire_drawing_copper", 51, 0.5),
        ]
        production_total = sum(mass_kg * emission_factor for _, mass_kg, emission_factor in cable_yarder_materials)
        if self.machine_id == "cable_yarder_recuperating":
            production_total *= self.mass_kg / CABLE_YARDER_REFERENCE_MASS_KG
        if self.machine_id in {"cable_yarder_electric", "cable_yarder_recuperating"}:
            production_total += self.battery_capacity * _factor(emission_factors, "lfp_battery_prod_energy") * self.number_of_batteries_over_lifetime
        self.production_emission = self._divide_by_production_output(production_total)

    def calculate_maintenance_emissions(self, materials: list[dict], emission_factors: dict):
        self.maintenance_emission = 0.0

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

    def calculate_emission(self, emission_factors: dict, mode: str):

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
        if self.mass_kg <= 0 or self.payload_kg <= 0 or self.wagon_lifetime_years <= 0 or self.wagon_km_per_year <= 0:
            self.production_emission = 0.0
            return

        emission_wagon = (self.mass_kg * _factor(emission_factors, "steel_heavy_plate_a1a3")) / (
            self.wagon_lifetime_years * self.wagon_km_per_year * (self.payload_kg / 1000)
        )
        emission_lokomotive = 0.000052
        self.production_emission = (emission_wagon + emission_lokomotive) * self.rail_mass_t_per_m3 * self.distance_km

    def calculate_maintenance_emissions(self, materials: list[dict], emission_factors: dict):
        self.maintenance_emission = 0.0
        # rail_infrastructure = _factor(emission_factors, "rail_infrastructure") / 1000
        # self.maintenance_emission = rail_infrastructure * self.rail_mass_t_per_m3 * self.distance_km

    def apply_use_case_to_machine(self, use_case_row: dict):
        rail_distance = _to_float(use_case_row["rail_km"])
        if rail_distance > 0:
            self.distance_km = rail_distance

        if self.machine_id != "rail_intermodal_container":
            return

        container_load_volume = self.load_volume_m3
        if container_load_volume <= 0 and self.container_weight_kg > 0:
            container_load_volume = INTERMODAL_CONTAINER_DEFAULT_LOAD_VOLUME_M3 - (self.container_weight_kg / 1000) / WOOD_DENSITY_T_M3
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

    def calculate_emission(self, emission_factors: dict, mode: str):

        rail_ttw = _factor(emission_factors, "rail_gv_ttw")
        total_energy = _factor(emission_factors, "rail_gv_energy_intensity")
        diesel_ttw_factor = _factor(emission_factors, "diesel_ttw")
        diesel_wtt_factor = _factor(emission_factors, "diesel_wtt")
        electricity_mix = _factor(emission_factors, "electricity_mix")

        distance = self.distance_km
        electricity_factor = electricity_mix * 1000  # kg -> g

        diesel_energy = rail_ttw / diesel_ttw_factor
        electric_energy = total_energy - diesel_energy

        if mode == "wtt":
            self.wtt_emission = ((diesel_energy * diesel_wtt_factor + electric_energy * electricity_factor) * self.rail_mass_t_per_m3 / 1000) * distance
        elif mode == "ttw":
            self.ttw_emission = (diesel_energy * diesel_ttw_factor * distance * self.rail_mass_t_per_m3) / 1000

    def calculate_eol_emissions(self, materials: list[dict], emission_factors: dict):
        rail_eol_gco2e_tkm = 0.015
        self.eol_emission = (rail_eol_gco2e_tkm * self.rail_mass_t_per_m3 * self.distance_km) / 1000


class TerminalHandling(Machine):
    def __init__(self, *args, load_volume_m3, **kwargs):
        super().__init__(*args, **kwargs)
        self.type = "terminal_handling"
        self.load_volume_m3 = _to_float(load_volume_m3)
        self.handling_events = 2.0
        self.handling_time_h = (19.0 / 60.0) * self.handling_events

    def apply_use_case_to_machine(self, use_case_row: dict):
        load_volume = self.load_volume_m3
        if load_volume <= 0:
            load_volume = INTERMODAL_CONTAINER_DEFAULT_LOAD_VOLUME_M3
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

    def calculate_emission(self, emission_factors: dict, mode: str):
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
            AUMEIER_TRUCK_DIESEL_L_PER_H,
            diesel_density,
            diesel_heating_value,
            emission_factor,
        )
        if mode == "wtt":
            self.wtt_emission = emission
        elif mode == "ttw":
            self.ttw_emission = emission


class IntermodalContainer(Machine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.type = "intermodal_container"

    def calculate_production_emissions(self, materials: list[dict], emission_factors: dict):
        production_total = self.mass_kg * _factor(emission_factors, "steel_heavy_plate_a1a3")
        self.production_emission = production_total / self.lifetime_m3 if self.lifetime_m3 > 0 else 0.0

    def calculate_maintenance_emissions(self, materials: list[dict], emission_factors: dict):
        self.maintenance_emission = 0

    def apply_use_case_to_machine(self, use_case_row: dict):
        pass

    def calculate_emission(self, emission_factors: dict, mode: str):
        self.wtt_emission = 0
        self.ttw_emission = 0


class Winch(Machine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.type = "forest_winch"

    def apply_use_case_to_machine(self, use_case_row: dict):

        self._apply_autonomy_adjustments()

    def calculate_emission(self, emission_factors: dict, mode: str):
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


