import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

from machines import (
    Forwarder,
    Tractor,
    Harvester,
    Chainsaw,
    ForestTrailer,
    Truck,
    TruckTrailer,
    CableYarder,
    Rail,
    TerminalHandling,
    IntermodalContainer,
    Winch,
    Machine,
)
from pathways import PATHWAY_STEPS, TRANSPORT_PATHWAY_GROUPS


def plot_use_case_diagrams(
    results_df,
    machine_results_df,
    output_dir="use_cases_results",
    use_case_col="use_case",
    pathway_col="pathway_id",
):
    """
    Create and display pathway and machine-level use-case diagrams.

    Each transport pathway group is stored in its own subdirectory.
    """
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    use_case_order = ["short_distance", "average_distance", "long_distance"]
    use_case_labels = {
        "short_distance": "Short Case",
        "average_distance": "Average Case",
        "long_distance": "Long Case",
    }
    emission_columns = ["production", "maintenance", "wtt", "ttw", "eol"]
    colors = ["steelblue", "lightgray", "orange", "seagreen", "firebrick"]

    for group_name, group_config in TRANSPORT_PATHWAY_GROUPS.items():
        pathway_order = group_config["pathways"]
        group_results = results_df[results_df[pathway_col].isin(pathway_order)].copy()
        group_machine_results = machine_results_df[
            machine_results_df[pathway_col].isin(pathway_order)
        ].copy()

        if group_results.empty:
            print(f"No results found for {group_name}.")
            continue

        group_output_path = output_root / group_config["directory"]
        group_output_path.mkdir(parents=True, exist_ok=True)

        available_pathways = [
            pathway_id
            for pathway_id in pathway_order
            if pathway_id in group_results[pathway_col].values
        ]
        pathway_labels = (
            group_results[[pathway_col, "variant"]]
            .drop_duplicates(pathway_col)
            .set_index(pathway_col)["variant"]
            .to_dict()
        )

        group_results.to_csv(
            group_output_path / "pathway_results.csv",
            sep=";",
            decimal=",",
            index=False,
        )
        group_machine_results.to_csv(
            group_output_path / "machine_results.csv",
            sep=";",
            decimal=",",
            index=False,
        )

        for use_case_key in use_case_order:
            subset = group_results[group_results[use_case_col] == use_case_key].copy()

            if subset.empty:
                print(
                    f"No data found for {group_name}, "
                    f"{use_case_labels[use_case_key]}."
                )
                continue

            subset = subset.groupby(pathway_col, as_index=False)[emission_columns].sum()
            subset = (
                subset.set_index(pathway_col).reindex(available_pathways).reset_index()
            )

            fig, ax = plt.subplots(figsize=(11, 6))
            _plot_stacked_emissions(
                ax,
                subset,
                [
                    pathway_labels.get(pathway_id, pathway_id)
                    for pathway_id in subset[pathway_col]
                ],
                emission_columns,
                colors,
            )
            ax.set_ylabel("Emissions [kg CO2e/m3]")
            ax.set_title(f"{group_name} - {use_case_labels[use_case_key]}")
            fig.tight_layout()
            fig.savefig(
                group_output_path / f"pathways_{use_case_key}.png",
                dpi=200,
                bbox_inches="tight",
            )
            plt.close(fig)

        for step_index, role_name in group_config["machine_roles"].items():
            subset = group_machine_results[
                group_machine_results["step_index"] == step_index
            ].copy()
            if subset.empty:
                continue

            subset[pathway_col] = pd.Categorical(
                subset[pathway_col],
                categories=available_pathways,
                ordered=True,
            )
            subset[use_case_col] = pd.Categorical(
                subset[use_case_col],
                categories=use_case_order,
                ordered=True,
            )
            subset = subset.sort_values([pathway_col, use_case_col])

            x_labels = [
                f"{role_name} {pathway_labels.get(pathway_id, pathway_id)}\n"
                f"({use_case_labels[use_case]})"
                for pathway_id, use_case in zip(
                    subset[pathway_col].astype(str),
                    subset[use_case_col].astype(str),
                )
            ]

            fig_width = max(14, len(subset) * 1.8)
            fig, ax = plt.subplots(figsize=(fig_width, 7))
            _plot_stacked_emissions(
                ax,
                subset,
                x_labels,
                emission_columns,
                colors,
            )
            ax.set_ylabel("Emissions [kg CO2e/m3]")
            ax.set_title(f"{role_name} emissions across {group_name} use cases")
            ax.tick_params(axis="x", rotation=25)
            fig.tight_layout()

            file_name = (
                role_name.lower()
                .replace(" / ", "_")
                .replace("/", "_")
                .replace(" ", "_")
            )
            fig.savefig(
                group_output_path / f"machine_{step_index + 1}_{file_name}.png",
                dpi=200,
                bbox_inches="tight",
            )
            plt.close(fig)


def _plot_stacked_emissions(
    ax,
    data,
    x_labels,
    emission_columns,
    colors,
):
    positive_bottom = pd.Series(0.0, index=data.index)
    negative_bottom = pd.Series(0.0, index=data.index)

    for column, color in zip(emission_columns, colors):
        values = data[column].astype(float)
        positive_values = values.clip(lower=0)
        negative_values = values.clip(upper=0)

        ax.bar(
            x_labels,
            positive_values,
            bottom=positive_bottom,
            label=column.upper(),
            color=color,
        )
        ax.bar(
            x_labels,
            negative_values,
            bottom=negative_bottom,
            color=color,
        )
        positive_bottom = positive_bottom + positive_values
        negative_bottom = negative_bottom + negative_values

    net_totals = data[emission_columns].astype(float).sum(axis=1)
    for index, total_value in enumerate(net_totals):
        ax.text(
            index,
            positive_bottom.iloc[index],
            f"{total_value:.2f}",
            ha="center",
            va="bottom",
        )

    ax.axhline(0, color="black", linewidth=0.8)
    ax.legend()


def run_pathway(
    use_case_row,
    stream,
    materials,
    emission_factors,
    machine_results=None,
):

    pathway_id = use_case_row["pathway_id"]
    machine_ids = PATHWAY_STEPS.get(pathway_id)

    if machine_ids is None:
        raise ValueError(f"No pathway defined for: {pathway_id}")

    pathway_result = {
        "pathway_id": pathway_id,
        "use_case": use_case_row["use_case"],
        "group": use_case_row["group"],
        "variant": use_case_row["variant"],
        "production": 0,
        "maintenance": 0,
        "wtt": 0,
        "ttw": 0,
        "eol": 0,
        "total": 0,
    }

    intermodal_container_row = (
        stream.get_machine("intermodal_container")
        if "intermodal_container" in machine_ids
        else None
    )

    for step_index, machine_id in enumerate(machine_ids):
        machine_row = stream.get_machine(machine_id)
        if machine_row is None:
            print(
                f"Skipping missing machine '{machine_id}' "
                f"in pathway '{pathway_id}'."
            )
            continue

        machine = _create_machine_from_row(machine_row, intermodal_container_row)

        machine.apply_use_case_to_machine(use_case_row)

        machine.calculate_production_emissions(materials, emission_factors)
        machine.calculate_maintenance_emissions(materials, emission_factors)
        machine.calculate_eol_emissions(materials, emission_factors)
        machine.calculate_emission(emission_factors, "wtt")
        machine.calculate_emission(emission_factors, "ttw")

        production = machine.get_production_emission()
        maintenance = machine.get_maintenance_emission()
        wtt = machine.get_wtt_emission()
        ttw = machine.get_ttw_emission()
        eol = machine.get_eol_emission()

        if machine_results is not None:
            machine_results.append(
                {
                    "pathway_id": pathway_id,
                    "use_case": use_case_row["use_case"],
                    "group": use_case_row["group"],
                    "variant": use_case_row["variant"],
                    "step_index": step_index,
                    "machine_id": machine_id,
                    "production": production,
                    "maintenance": maintenance,
                    "wtt": wtt,
                    "ttw": ttw,
                    "eol": eol,
                    "total": production + maintenance + wtt + ttw + eol,
                }
            )

        pathway_result["production"] += production
        pathway_result["maintenance"] += maintenance
        pathway_result["wtt"] += wtt
        pathway_result["ttw"] += ttw
        pathway_result["eol"] += eol

    pathway_result["total"] = (
        pathway_result["production"]
        + pathway_result["maintenance"]
        + pathway_result["wtt"]
        + pathway_result["ttw"]
        + pathway_result["eol"]
    )

    return pathway_result


def _create_machine_from_row(machine_object, intermodal_container_object=None):
    mid = machine_object["machine_id"]

    if mid.startswith("forwarder"):
        cls = Forwarder
    elif mid.startswith("tractor"):
        cls = Tractor
    elif mid.startswith("harvester"):
        cls = Harvester
    elif mid.startswith("chainsaw"):
        cls = Chainsaw
    elif mid == "forest_trailer":
        cls = ForestTrailer
    elif mid.startswith("truck_") and mid != "truck_trailer":
        cls = Truck
    elif mid == "truck_trailer":
        cls = TruckTrailer
    elif mid.startswith("cable_yarder"):
        cls = CableYarder
    elif mid in {"rail", "rail_intermodal_container"}:
        cls = Rail
    elif mid in {"terminal_handling_logs", "terminal_handling_intermodal_container"}:
        cls = TerminalHandling
    elif mid == "intermodal_container":
        cls = IntermodalContainer
    elif mid == "forest_winch":
        cls = Winch
    else:
        cls = Machine

    machine_args = {
        "machine_id": machine_object["machine_id"],
        "electric": machine_object["electric"],
        "mass_kg": machine_object["mass_kg"],
        "lifetime_h": machine_object["lifetime_h"],
        "lifetime_m3": machine_object["lifetime_m3"],
        "productivity_m3_h": machine_object["productivity_m3_h"],
        "diesel_l_h": machine_object["diesel_l_h"],
        "power_consumption_kwh_h": machine_object["power_consumption_kwh_h"],
        "battery_capacity_kwh": machine_object["battery_capacity_kwh"],
        "battery_mass_kg": machine_object["battery_mass_kg"],
        "number_of_batteries_over_lifetime": machine_object[
            "number_of_batteries_over_lifetime"
        ],
        "production_factor_kgco2e_kg": machine_object["production_factor_kgco2e_kg"],
        "repair_factor": machine_object["repair_factor"],
        "ttw_zero": machine_object["ttw_zero"],
        "production_model": machine_object["production_model"],
        "engine_mass_ICE_kg": machine_object["engine_mass_ICE_kg"],
        "autonomy_subsystem_mass_kg": machine_object.get("autonomy_subsystem_mass_kg", 0),
        "autonomy_subsystem_power_w": machine_object.get("autonomy_subsystem_power_w", 0),
        "autonomy_subsystem_production_kgco2e": machine_object.get("autonomy_subsystem_production_kgco2e", 0),
        "autonomy_subsystem_eol_kgco2e_kg": machine_object.get("autonomy_subsystem_eol_kgco2e_kg", 0),
        "autonomy_productivity_gain_share": machine_object.get("autonomy_productivity_gain_share", 0),
        "autonomy_energy_saving_share": machine_object.get("autonomy_energy_saving_share", 0),
        "autonomy_onboard_electric_efficiency": machine_object.get("autonomy_onboard_electric_efficiency", 0.20),
        "cab_removed_mass_kg": machine_object.get("cab_removed_mass_kg", 0),
    }

    if cls == ForestTrailer:
        machine_args["payload_kg"] = machine_object["payload_kg"]
        machine_args["load_volume_m3"] = machine_object["load_volume_m3"]

    if cls == Truck:
        machine_args["payload_kg"] = machine_object["payload_kg"]
        machine_args["load_volume_m3"] = machine_object["load_volume_m3"]
        machine_args["container_weight_kg"] = 0
        if machine_object["machine_id"].endswith("intermodal_container"):
            machine_args["container_weight_kg"] = intermodal_container_object.get(
                "mass_kg", 0
            )
            machine_args["load_volume_m3"] = intermodal_container_object.get(
                "load_volume_m3", 0
            )

    if cls == TruckTrailer:
        machine_args["load_volume_m3"] = machine_object["load_volume_m3"]

    if cls == TerminalHandling:
        machine_args["load_volume_m3"] = machine_object["load_volume_m3"]
        if machine_object["machine_id"].endswith("intermodal_container"):
            machine_args["load_volume_m3"] = intermodal_container_object.get(
                "load_volume_m3", 0
            )

    if cls == Tractor:
        machine_args["load_volume_m3"] = machine_object["load_volume_m3"]

    if cls == Chainsaw:
        machine_args["gasoline_mix_l_h"] = machine_object["gasoline_mix_l_h"]
        machine_args["chain_oil_l_h"] = machine_object["chain_oil_l_h"]
        machine_args["power_consumption_kwh_m3"] = machine_object[
            "power_consumption_kwh_m3"
        ]

    if cls == Rail:
        machine_args["wagon_lifetime_years"] = machine_object["wagon_lifetime_years"]
        machine_args["wagon_km_per_year"] = machine_object["wagon_km_per_year"]
        machine_args["payload_kg"] = machine_object["payload_kg"]
        machine_args["load_volume_m3"] = machine_object.get("load_volume_m3", 0)
        machine_args["container_weight_kg"] = 0
        if machine_object["machine_id"].endswith("intermodal_container"):
            machine_args["container_weight_kg"] = intermodal_container_object.get(
                "mass_kg", 0
            )
            machine_args["load_volume_m3"] = intermodal_container_object.get(
                "load_volume_m3", 0
            )

    if cls == Forwarder:
        machine_args["relocation_distance"] = machine_object["relocation_distance"]
        machine_args["operating_hours_per_day"] = machine_object[
            "operating_hours_per_day"
        ]
        machine_args["payload_kg"] = machine_object["payload_kg"]
        machine_args["load_volume_m3"] = machine_object["load_volume_m3"]

    return cls(**machine_args)


class DataStream:
    def __init__(
        self,
        use_cases_path: str,
        machines_path: str,
        materials_path: str,
        emission_repository_path: str,
    ):
        self.use_cases = self._read_csv(use_cases_path)
        self.machines = self._read_csv(machines_path)
        self.materials = self._read_csv(materials_path)
        emission_repository = self._read_csv(emission_repository_path)

        # Rohdaten bleiben bei Bedarf noch verfuegbar.
        self.emission_repository = self._create_lookup_dictionary(
            emission_repository, key_column="factor_id"
        )

        # Flaches Dictionary fuer die Berechnungen:
        # Beispiel: factors["diesel_wtt"], factors["diesel_wtt_density"],
        # factors["diesel_wtt_heating_value"]
        self.emission_factors = self._create_emission_factor_dictionary(
            emission_repository
        )

    def _read_csv(self, csv_path: str):
        dataframe = pd.read_csv(csv_path, sep=";", decimal=",")
        return dataframe.to_dict(orient="records")

    def _create_lookup_dictionary(self, data: list[dict], key_column: str):
        lookup = {}

        for row in data:
            key = row[key_column]
            lookup[key] = row

        return lookup

    def _create_emission_factor_dictionary(self, data: list[dict]):
        factors = {}

        for row in data:
            factor_id = row["factor_id"]

            factors[factor_id] = self._to_float(row.get("value", 0))
            factors[f"{factor_id}_density"] = self._to_float(row.get("density_kg_l", 0))
            factors[f"{factor_id}_heating_value"] = self._to_float(
                row.get("heating_value_kwh_kg", 0)
            )
            factors[f"{factor_id}_derived"] = self._to_float(
                row.get("derived_kgco2e_l", 0)
            )

        return factors

    def _to_float(self, value, default=0.0):
        if value is None or value == "" or pd.isna(value):
            return default
        return float(value)

    def get_all_use_cases(self):
        return self.use_cases

    def get_all_machines(self):
        return self.machines

    def get_all_materials(self):
        return self.materials

    def get_all_emission_factors(self):
        return self.emission_factors

    def get_use_case(self, pathway_id: str, use_case: str):
        for row in self.use_cases:
            if row["pathway_id"] == pathway_id and row["use_case"] == use_case:
                return row
        return None

    def get_machine(self, machine_id: str):
        for row in self.machines:
            if row["machine_id"] == machine_id:
                return row
        return None

    def get_materials_for_machine(self, machine_id: str):
        materials = []

        for row in self.materials:
            if row["machine_id"] == machine_id:
                materials.append(row)

        return materials

    def get_emission_factor(self, factor_id: str):
        return self.emission_factors.get(factor_id, 0)
