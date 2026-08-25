"""Simple One-at-a-Time sensitivity analysis for the forestry LCA model.

Every calculation copies the input data, changes exactly one value and then
uses the existing use-case and emission calculations.
"""

from copy import deepcopy
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from helper_functions import DataStream, _create_machine_from_row
from pathways import PATHWAY_STEPS

# ============================================================
# CONFIGURATION
# ============================================================

DEFAULT_LOW_CHANGE_PERCENT = -25.0
DEFAULT_HIGH_CHANGE_PERCENT = 25.0
TOP_MACHINE_DRIVERS = 10

MACHINE_DISPLAY_NAMES = {
    "chainsaw_electric": "Chainsaw",
    "chainsaw_petrol": "Chainsaw",
    "tractor_electric_winch": "Tractor Winch",
    "tractor_diesel_winch": "Tractor Winch",
    "tractor_electric_trailer": "Tractor Trailer",
    "tractor_diesel_trailer": "Tractor Trailer",
    "truck_diesel": "Truck (Diesel)",
    "truck_bev": "Truck (BEV)",
    "truck_efuel": "Truck (e-fuel)",
    "harvester_diesel": "Harvester (Diesel)",
    "harvester_electric": "Harvester (Electric)",
    "forwarder_diesel": "Forwarder (Diesel)",
    "forwarder_electric": "Forwarder (Electric)",
    "forwarder_pully": "Forwarder (Pully)",
    "cable_yarder_diesel": "Cable Yarder (Diesel)",
    "cable_yarder_electric": "Cable Yarder (Electric)",
    "cable_yarder_recuperating": "Cable Yarder (Recuperating)",
    "rail": "Rail",
    "rail_intermodal_container": "Rail (Intermodal)",
    "terminal_handling_logs": "Terminal Handling",
    "terminal_handling_intermodal_container": "Terminal Handling",
    "harvester_autonomous_low_diesel": "Harvester (Diesel)",
    "harvester_autonomous_high_diesel": "Harvester (Diesel)",
    "harvester_autonomous_partly_diesel": "Harvester (Diesel)",
    "forwarder_autonomous_low_diesel": "Forwarder (Diesel)",
    "forwarder_autonomous_high_diesel": "Forwarder (Diesel)",
    "forwarder_autonomous_partly_diesel": "Forwarder (Diesel)",
    "truck_autonomous_low_diesel": "Truck (Diesel)",
    "truck_autonomous_high_diesel": "Truck (Diesel)",
    "truck_autonomous_partly_diesel": "Truck (Diesel)",
}

PARAMETER_DISPLAY_NAMES = {
    "Diesel WTT emission factor": "Diesel WTT factor",
    "E-fuel WTT emission factor": "E-fuel WTT factor",
    "Fuel consumption": "Gasoline-mix consumption",
    "Lithium-ion battery production factor": ("Li-ion battery production factor"),
    "Autonomous energy saving": "Fuel savings due to autonomy",
}

MACHINE_PARAMETER_DISPLAY_NAMES = {
    ("tractor_diesel_trailer", "Diesel consumption"): "Fuel consumption",
    ("truck_diesel", "Productivity"): "productivity",
    ("truck_diesel", "Load volume"): "load volume",
    ("truck_diesel", "Diesel consumption"): "fuel consumption",
    ("harvester_diesel", "Productivity"): "productivity",
    ("harvester_diesel", "Diesel consumption"): "fuel consumption",
    ("harvester_diesel", "Machine production factor"): "machine production factor",
    ("forwarder_diesel", "Productivity"): "productivity",
    ("forwarder_diesel", "Diesel consumption"): "fuel consumption",
    ("forwarder_diesel", "Machine production factor"): "machine production factor",
    ("tractor_diesel_trailer", "Diesel consumption"): "fuel consumption",
}

# Positive values define a symmetric variation: 10.0 means -10% / +10%.
# Parameters that do not occur in a pathway are ignored automatically.
PARAMETER_CHANGE_PERCENT = {
    "Productivity": 25.0,
    "Diesel consumption": 25.0,
    "Load volume": 25.0,
    "E-fuel WTT emission factor": 25.0,
    "Electricity mix": 50.0,
    "Electricity consumption": 25.0,
    "Diesel WTT emission factor": 25.0,
    "Autonomous energy saving": 25.0,
    "Machine lifetime": 25.0,
    "Lithium-ion battery production factor": 25.0,
    "Machine production factor": 25.0,
    "Batteries over machine lifetime": 100,
    "LFP battery production factor": 25.0,
    "Autonomous productivity gain": 25.0,
    "Fuel consumption": 25.0,
    "Chainsaw fuel WTT emission factor": 25.0,
    "Supercapacitor production factor": 25.0,
    "Nickel-manganese battery production factor": 25.0,
}

# Enter absolute scenarios here when percentages are not suitable.
# A machine-specific key is also possible:
# "harvester_diesel.productivity_h"
ABSOLUTE_PARAMETER_VALUES = {
    # "electricity_mix": {"low_value": 0.200, "high_value": 0.800},
}

# change_time:
# "after_use_case"  = the use case calculates or overwrites this value
# "before_use_case" = the use-case calculation uses this input value
MACHINE_PARAMETER_SETTINGS = [
    ("productivity_h", "Productivity", "m³/h", "after_use_case"),
    ("diesel_l_h", "Diesel consumption", "l/h", "after_use_case"),
    ("gasoline_mix_l_h", "Fuel consumption", "l/h", "after_use_case"),
    (
        "power_consumption_kwh_h",
        "Electricity consumption",
        "kWh/h",
        "after_use_case",
    ),
    (
        "power_consumption_kwh_m3",
        "Electricity consumption",
        "kWh/m³",
        "after_use_case",
    ),
    ("lifetime_h", "Machine lifetime", "h", "after_use_case"),
    ("lifetime_m3", "Machine lifetime", "m³", "after_use_case"),
    (
        "production_factor",
        "Machine production factor",
        "kg CO₂e/kg",
        "after_use_case",
    ),
    (
        "number_of_batteries_over_lifetime",
        "Batteries over machine lifetime",
        "number",
        "after_use_case",
    ),
    ("load_volume_m3", "Load volume", "m³", "before_use_case"),
    (
        "autonomy_productivity_gain_share",
        "Autonomous productivity gain",
        "share",
        "before_use_case",
    ),
    (
        "autonomy_energy_saving_share",
        "Autonomous energy saving",
        "share",
        "before_use_case",
    ),
]

EMISSION_FACTOR_SETTINGS = [
    ("diesel_wtt", "Diesel WTT emission factor", "g CO₂e/kWh"),
    ("electricity_mix", "Electricity mix", "kg CO₂e/kWh"),
    ("efuel_wtt_2030_de", "E-fuel WTT emission factor", "kg CO₂e/l"),
    (
        "chainsaw_fuel_mix_wtt_ecoinvent",
        "Chainsaw fuel WTT emission factor",
        "kg CO₂e/l",
    ),
    (
        "lfp_battery_prod_energy",
        "LFP battery production factor",
        "kg CO₂e/kWh",
    ),
    (
        "li_ion_battery_prod_mass",
        "Lithium-ion battery production factor",
        "kg CO₂e/kg battery",
    ),
    (
        "li_ion_battery_prod_energy_nick_manganes",
        "Nickel-manganese battery production factor",
        "kg CO₂e/kWh",
    ),
    (
        "supercapacitor_cell_prod_gottardo",
        "Supercapacitor production factor",
        "kg CO₂e/cell",
    ),
]


# ============================================================
# COPY DATA, CHANGE ONE VALUE AND RUN THE MODEL
# ============================================================


def calculate_pathway_total(use_case_row, stream, changes=None):
    """Calculate a pathway after changing zero, one or several input values."""
    use_case_row = deepcopy(use_case_row)
    machine_rows = deepcopy(stream.get_all_machines())
    materials = deepcopy(stream.get_all_materials())
    emission_factors = deepcopy(stream.get_all_emission_factors())

    if changes is None:
        changes = []
    elif isinstance(changes, dict):
        changes = [changes]

    for change in changes:
        if change["data_source"] == "emission_factors":
            emission_factors[change["parameter_name"]] = change["new_value"]

    totals = dict.fromkeys(
        ["production", "maintenance", "wtt", "ttw", "eol"],
        0.0,
    )

    for machine_id in PATHWAY_STEPS[use_case_row["pathway_id"]]:
        machine_row = next(
            (row for row in machine_rows if row["machine_id"] == machine_id),
            None,
        )
        if machine_row is None:
            continue

        machine_changes = [change for change in changes if change["data_source"] == "machine" and change["machine_id"] == machine_id]
        for change in machine_changes:
            if change["change_time"] == "before_use_case":
                machine_row[change["parameter_name"]] = change["new_value"]

        machine = _create_machine_from_row(machine_row)
        machine.apply_use_case_to_machine(use_case_row)

        for change in machine_changes:
            if change["change_time"] != "after_use_case":
                continue

            parameter_name = change["parameter_name"]
            setattr(machine, parameter_name, change["new_value"])

            if parameter_name in {"productivity_h", "diesel_l_h"}:
                if machine.productivity_h > 0:
                    machine.consumption_l_m3 = machine.diesel_l_h / machine.productivity_h

            if parameter_name in {
                "productivity_h",
                "power_consumption_kwh_h",
            }:
                if machine.electric and machine.power_consumption_kwh_h > 0:
                    machine._recalculate_power_consumption_kwh_m3()

        machine.calculate_production_emissions(materials, emission_factors)
        machine.calculate_maintenance_emissions(materials, emission_factors)
        machine.calculate_eol_emissions(materials, emission_factors)
        machine.calculate_wtw_emissions(emission_factors, "wtt")
        machine.calculate_wtw_emissions(emission_factors, "ttw")

        totals["production"] += machine.get_production_emission()
        totals["maintenance"] += machine.get_maintenance_emission()
        totals["wtt"] += machine.get_wtt_emission()
        totals["ttw"] += machine.get_ttw_emission()
        totals["eol"] += machine.get_eol_emission()

    totals["total"] = sum(totals.values())
    return totals


# ============================================================
# FIND PARAMETERS AND RUN LOW/HIGH CALCULATIONS
# ============================================================


def get_sensitivity_parameters(use_case_row, stream):
    """Collect positive machine inputs and available emission factors."""
    parameters = []

    for machine_id in PATHWAY_STEPS[use_case_row["pathway_id"]]:
        machine_row = stream.get_machine(machine_id)
        if machine_row is None:
            continue

        machine = _create_machine_from_row(deepcopy(machine_row))
        machine.apply_use_case_to_machine(deepcopy(use_case_row))
        added_names = set()

        for name, label, unit, change_time in MACHINE_PARAMETER_SETTINGS:
            if name.startswith("power_consumption") and not machine.electric:
                continue
            if name == "diesel_l_h" and machine.electric:
                continue
            if name == "gasoline_mix_l_h" and machine.electric:
                continue
            if name == "number_of_batteries_over_lifetime" and not machine.electric and machine.machine_id != "cable_yarder_recuperating":
                continue
            if not hasattr(machine, name):
                continue

            baseline = float(getattr(machine, name))
            if baseline <= 0:
                continue
            if name == "lifetime_m3" and "lifetime_h" in added_names:
                continue
            if name == "power_consumption_kwh_m3" and "power_consumption_kwh_h" in added_names:
                continue

            added_names.add(name)
            parameters.append(
                {
                    "parameter_id": f"{machine_id}.{name}",
                    "parameter_name": name,
                    "parameter_label": label,
                    "unit": unit,
                    "data_source": "machine",
                    "machine_id": machine_id,
                    "change_time": change_time,
                    "baseline_value": baseline,
                }
            )

    factors = stream.get_all_emission_factors()
    for name, label, unit in EMISSION_FACTOR_SETTINGS:
        baseline = float(factors.get(name, 0.0))
        if baseline > 0:
            parameters.append(
                {
                    "parameter_id": name,
                    "parameter_name": name,
                    "parameter_label": label,
                    "unit": unit,
                    "data_source": "emission_factors",
                    "machine_id": "All machines",
                    "change_time": "before_use_case",
                    "baseline_value": baseline,
                }
            )

    return parameters


def get_low_and_high_values(parameter, low_percent, high_percent):
    """Use configured absolute values or percentage changes."""
    absolute = ABSOLUTE_PARAMETER_VALUES.get(parameter["parameter_id"]) or ABSOLUTE_PARAMETER_VALUES.get(parameter["parameter_name"])
    if absolute:
        return float(absolute["low_value"]), float(absolute["high_value"])

    configured_percent = PARAMETER_CHANGE_PERCENT.get(parameter["parameter_label"])
    if configured_percent is not None:
        change_percent = abs(float(configured_percent))
        low_percent = -change_percent
        high_percent = change_percent

    baseline = parameter["baseline_value"]
    low_value = baseline * (1 + low_percent / 100)
    high_value = baseline * (1 + high_percent / 100)
    if parameter["unit"] == "share":
        return (
            min(max(low_value, 0.0), 1.0),
            min(max(high_value, 0.0), 1.0),
        )
    return max(low_value, 0.0), max(high_value, 0.0)


def run_sensitivity_analysis(use_case_row, stream, low_percent, high_percent):
    """Calculate Baseline, Low and High for every available parameter."""
    baseline = calculate_pathway_total(use_case_row, stream)
    if baseline != calculate_pathway_total(use_case_row, stream):
        raise RuntimeError("Baseline data changed between sensitivity runs.")

    results = []
    for parameter in get_sensitivity_parameters(use_case_row, stream):
        low_value, high_value = get_low_and_high_values(
            parameter,
            low_percent,
            high_percent,
        )
        low = calculate_pathway_total(
            use_case_row,
            stream,
            {**parameter, "new_value": low_value},
        )
        high = calculate_pathway_total(
            use_case_row,
            stream,
            {**parameter, "new_value": high_value},
        )
        baseline_total = baseline["total"]
        low_percent_result = (low["total"] - baseline_total) / baseline_total * 100 if baseline_total != 0 else 0.0
        high_percent_result = (high["total"] - baseline_total) / baseline_total * 100 if baseline_total != 0 else 0.0

        results.append(
            {
                "pathway": use_case_row["pathway_id"],
                "variant": use_case_row["variant"],
                "use_case": use_case_row["use_case"],
                "machine_id": parameter["machine_id"],
                "parameter_id": parameter["parameter_id"],
                "parameter_label": parameter["parameter_label"],
                "unit": parameter["unit"],
                "baseline_parameter_value": parameter["baseline_value"],
                "low_parameter_value": low_value,
                "high_parameter_value": high_value,
                "baseline_total_kgco2e_m3": baseline_total,
                "low_total_kgco2e_m3": low["total"],
                "high_total_kgco2e_m3": high["total"],
                "low_change_percent": low_percent_result,
                "high_change_percent": high_percent_result,
                "range_absolute": abs(high["total"] - low["total"]),
            }
        )

    table = pd.DataFrame(results)
    if low_percent != 0 or high_percent != 0:
        table = table[table["range_absolute"] > 1e-12]
    return table.sort_values("range_absolute", ascending=False)


def run_grouped_sensitivity_analysis(
    use_case_row,
    stream,
    low_percent,
    high_percent,
):
    """Change all inputs with the same label together."""
    baseline_total = calculate_pathway_total(use_case_row, stream)["total"]
    parameter_groups = {}

    for parameter in get_sensitivity_parameters(use_case_row, stream):
        parameter_groups.setdefault(
            parameter["parameter_label"],
            [],
        ).append(parameter)

    results = []
    for label, parameters in parameter_groups.items():
        low_changes = []
        high_changes = []

        for parameter in parameters:
            low_value, high_value = get_low_and_high_values(
                parameter,
                low_percent,
                high_percent,
            )
            low_changes.append({**parameter, "new_value": low_value})
            high_changes.append({**parameter, "new_value": high_value})

        low_total = calculate_pathway_total(
            use_case_row,
            stream,
            low_changes,
        )["total"]
        high_total = calculate_pathway_total(
            use_case_row,
            stream,
            high_changes,
        )["total"]
        result_range = abs(high_total - low_total)

        if result_range <= 1e-12 and (low_percent != 0 or high_percent != 0):
            continue

        only_parameter = parameters[0] if len(parameters) == 1 else None
        results.append(
            {
                "pathway": use_case_row["pathway_id"],
                "variant": use_case_row["variant"],
                "use_case": use_case_row["use_case"],
                "machine_id": "All applicable machines",
                "parameter_id": f"grouped.{label.lower().replace(' ', '_')}",
                "parameter_label": label,
                "unit": only_parameter["unit"] if only_parameter else "various",
                "baseline_parameter_value": (only_parameter["baseline_value"] if only_parameter else None),
                "low_parameter_value": (low_changes[0]["new_value"] if only_parameter else None),
                "high_parameter_value": (high_changes[0]["new_value"] if only_parameter else None),
                "changed_parameter_count": len(parameters),
                "baseline_total_kgco2e_m3": baseline_total,
                "low_total_kgco2e_m3": low_total,
                "high_total_kgco2e_m3": high_total,
                "low_change_percent": ((low_total - baseline_total) / baseline_total * 100 if baseline_total != 0 else 0.0),
                "high_change_percent": ((high_total - baseline_total) / baseline_total * 100 if baseline_total != 0 else 0.0),
                "range_absolute": result_range,
            }
        )

    return pd.DataFrame(results).sort_values(
        "range_absolute",
        ascending=False,
    )


# ============================================================
# TORNADO CHART AND STREAMLIT PAGE
# ============================================================


def get_parameter_display_name(machine_id, parameter_label):
    """Return a presentation-only parameter name."""
    return MACHINE_PARAMETER_DISPLAY_NAMES.get(
        (machine_id, parameter_label),
        PARAMETER_DISPLAY_NAMES.get(parameter_label, parameter_label),
    )


def get_machine_display_name(machine_id):
    """Return a presentation-only machine name."""
    return MACHINE_DISPLAY_NAMES.get(
        machine_id,
        machine_id.replace("_", " ").title(),
    )


def get_chart_label(machine_id, parameter_label, separator="  "):
    """Build a chart label without changing calculation identifiers."""
    parameter_name = get_parameter_display_name(machine_id, parameter_label)
    if str(machine_id).startswith("All"):
        return parameter_name
    return f"{get_machine_display_name(machine_id)}" f"{separator}{parameter_name}"


def create_tornado_chart(results, x_axis_range):
    """Create one horizontal Low-to-High tornado chart."""
    plot = results.sort_values("range_absolute", ascending=True).copy()
    plot["chart_label"] = plot.apply(
        lambda row: get_chart_label(row["machine_id"], row["parameter_label"]),
        axis=1,
    )
    plot["start"] = plot[["low_total_kgco2e_m3", "high_total_kgco2e_m3"]].min(axis=1)
    plot["width"] = (plot["high_total_kgco2e_m3"] - plot["low_total_kgco2e_m3"]).abs()

    figure = go.Figure(
        go.Bar(
            y=plot["chart_label"],
            x=plot["width"],
            base=plot["start"],
            orientation="h",
            marker_color="#4f8a70",
            customdata=plot[
                [
                    "low_total_kgco2e_m3",
                    "high_total_kgco2e_m3",
                    "low_change_percent",
                    "high_change_percent",
                ]
            ],
            hovertemplate=("Low: %{customdata[0]:.3f} (%{customdata[2]:+.2f}%)<br>" "High: %{customdata[1]:.3f} (%{customdata[3]:+.2f}%)" "<extra></extra>"),
        )
    )
    figure.add_scatter(
        y=plot["chart_label"],
        x=plot["low_total_kgco2e_m3"],
        mode="markers+text",
        marker=dict(color="#294f78", size=7),
        text=plot["low_change_percent"].map(lambda value: f"{value:+.1f}%"),
        textposition=[
            "middle left" if low <= high else "middle right"
            for low, high in zip(
                plot["low_total_kgco2e_m3"],
                plot["high_total_kgco2e_m3"],
            )
        ],
        textfont=dict(color=["#294f78" if value >= 0 else "#b23a3a" for value in plot["low_change_percent"]]),
        hoverinfo="skip",
        showlegend=False,
    )
    figure.add_scatter(
        y=plot["chart_label"],
        x=plot["high_total_kgco2e_m3"],
        mode="markers+text",
        marker=dict(color="#d09a52", size=7),
        text=plot["high_change_percent"].map(lambda value: f"{value:+.1f}%"),
        textposition=[
            "middle right" if high >= low else "middle left"
            for low, high in zip(
                plot["low_total_kgco2e_m3"],
                plot["high_total_kgco2e_m3"],
            )
        ],
        textfont=dict(color=["#294f78" if value >= 0 else "#b23a3a" for value in plot["high_change_percent"]]),
        hoverinfo="skip",
        showlegend=False,
    )

    baseline = float(plot.iloc[0]["baseline_total_kgco2e_m3"])
    figure.add_vline(x=baseline, line_color="#18312a", line_width=2)
    figure.update_layout(
        title=(f"{plot.iloc[0]['variant']}<br>" f"<sup>Baseline: {baseline:.3f} kg CO₂e/m³</sup>"),
        height=max(450, 27 * len(plot) + 150),
        margin=dict(l=20, r=20, t=75, b=45),
        plot_bgcolor="white",
        paper_bgcolor="white",
        xaxis_title="GHG Emissions [kg CO₂ eq m⁻³]",
        showlegend=False,
    )
    figure.update_xaxes(range=x_axis_range, gridcolor="#dfe8e3")
    figure.update_yaxes(showgrid=False)
    return figure


def show_sensitivity_analysis_page(
    data_folder: Path,
    pathway_groups,
    group_labels,
    use_case_labels,
):
    """Display settings, tornado charts, result table and CSV download."""
    stream = DataStream(
        data_folder / "csv_use_cases.csv",
        data_folder / "csv_machines.csv",
        data_folder / "csv_materials.csv",
        data_folder / "csv_emission_repository.csv",
    )
    use_cases = pd.DataFrame(stream.get_all_use_cases())

    st.title("Sensitivity Analysis")
    st.caption("Only parameters that change total GWP are shown.")
    controls = st.columns(4)
    group = controls[0].selectbox(
        "Pathway",
        list(pathway_groups),
        format_func=lambda value: group_labels.get(value, value),
    )
    use_case_options = use_cases.loc[use_cases["group"] == group, "use_case"].drop_duplicates().tolist()
    selected_use_case = controls[1].selectbox(
        "Use Case",
        use_case_options,
        format_func=lambda value: use_case_labels.get(value, value),
    )
    low_percent = controls[2].number_input(
        "Low change [%]",
        value=DEFAULT_LOW_CHANGE_PERCENT,
        max_value=0.0,
        step=5.0,
    )
    high_percent = controls[3].number_input(
        "High change [%]",
        value=DEFAULT_HIGH_CHANGE_PERCENT,
        min_value=0.0,
        step=5.0,
    )

    if not st.button("Run Sensitivity Analysis", type="primary"):
        return

    rows = use_cases[(use_cases["group"] == group) & (use_cases["use_case"] == selected_use_case) & (use_cases["pathway_id"].isin(pathway_groups[group]["pathways"]))]
    with st.spinner("Calculating Baseline, Low and High..."):
        results = [run_sensitivity_analysis(row, stream, low_percent, high_percent) for row in rows.to_dict(orient="records")]

    st.subheader("Tornado diagrams")
    for column, result in zip(st.columns(len(results)), results):
        with column:
            st.plotly_chart(
                create_tornado_chart(result, get_centered_x_axis(result)),
                width="stretch",
            )

    st.subheader("Results")
    st.dataframe(combined, width="stretch", hide_index=True)
    st.download_button(
        "Download results as CSV",
        data=combined.to_csv(
            index=False,
            sep=";",
            decimal=",",
        ).encode("utf-8-sig"),
        file_name=f"sensitivity_{selected_use_case}.csv",
        mime="text/csv",
    )


# ============================================================
# SAVE CSV FILES AND PNG IMAGES IN USE-CASE RESULT FOLDERS
# ============================================================


def save_tornado_png(results, output_path, x_axis_range):
    """Save a readable, non-interactive tornado diagram as PNG."""
    import matplotlib.pyplot as plt

    plot = results.sort_values("range_absolute", ascending=True).copy()
    labels = [get_chart_label(row.machine_id, row.parameter_label) for row in plot.itertuples()]
    starts = plot[["low_total_kgco2e_m3", "high_total_kgco2e_m3"]].min(axis=1)
    widths = (plot["high_total_kgco2e_m3"] - plot["low_total_kgco2e_m3"]).abs()

    figure_height = max(6, len(plot) * 0.38 + 2)
    figure, axis = plt.subplots(figsize=(13, figure_height))
    axis.barh(labels, widths, left=starts, color="#4f8a70")
    baseline = float(plot.iloc[0]["baseline_total_kgco2e_m3"])
    axis.axvline(baseline, color="#18312a", linewidth=1.8)

    for index, row in enumerate(plot.itertuples()):
        endpoints = (
            (
                row.low_total_kgco2e_m3,
                row.high_total_kgco2e_m3,
                row.low_change_percent,
            ),
            (
                row.high_total_kgco2e_m3,
                row.low_total_kgco2e_m3,
                row.high_change_percent,
            ),
        )
        for value, other_value, change_percent in endpoints:
            is_left_endpoint = value <= other_value
            axis.annotate(
                f"{change_percent:+.1f}%",
                xy=(value, index),
                xytext=(-6 if is_left_endpoint else 6, 0),
                textcoords="offset points",
                va="center",
                ha="right" if is_left_endpoint else "left",
                fontsize=8,
                color="#294f78" if change_percent >= 0 else "#b23a3a",
            )

    axis.set_xlim(x_axis_range)
    axis.set_xlabel(r"GHG Emissions [kg CO$_2$ eq m$^{-3}$]")
    axis.set_title(f"Sensitivity Analysis – {plot.iloc[0]['variant']}\n" f"Baseline: {baseline:.3f} kg CO2 eq m-3")
    axis.grid(axis="x", color="#dfe8e3", linewidth=0.8)
    axis.set_axisbelow(True)
    figure.tight_layout()
    figure.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(figure)


def get_shared_percent_x_axis(result_tables, top_n=10):
    """Return one symmetric percentage axis for comparable pathway plots."""
    maximum_percent = max(
        max(
            results.head(top_n)["low_change_percent"].abs().max(),
            results.head(top_n)["high_change_percent"].abs().max(),
        )
        for results in result_tables
    )
    half_width = max(float(maximum_percent) * 1.25, 1.0)
    return [-half_width, half_width]


def save_compact_tornado_png(
    results,
    output_path,
    x_axis_range,
    top_n=10,
):
    """Save one compact, frameless percentage-based sensitivity plot."""
    import matplotlib.pyplot as plt

    plot = results.head(top_n).sort_values("range_absolute", ascending=True).copy()
    labels = [
        get_chart_label(
            row.machine_id,
            row.parameter_label,
            separator="\n",
        )
        for row in plot.itertuples()
    ]
    starts = plot[["low_change_percent", "high_change_percent"]].min(axis=1)
    widths = (plot["high_change_percent"] - plot["low_change_percent"]).abs()
    figure_height = max(4.4, len(plot) * 0.48 + 0.8)
    figure, axis = plt.subplots(figsize=(8.2, figure_height))
    axis.barh(labels, widths, left=starts, color="#4f8a70")
    axis.axvline(0, color="#18312a", linewidth=1.2)

    for index, row in enumerate(plot.itertuples()):
        for value, other_value in (
            (row.low_change_percent, row.high_change_percent),
            (row.high_change_percent, row.low_change_percent),
        ):
            is_left_endpoint = value <= other_value
            axis.annotate(
                f"{value:+.1f}%",
                xy=(value, index),
                xytext=(-5 if is_left_endpoint else 5, 0),
                textcoords="offset points",
                va="center",
                ha="right" if is_left_endpoint else "left",
                fontsize=9,
                color="#294f78" if value >= 0 else "#b23a3a",
            )

    axis.set_xlim(x_axis_range)
    axis.set_xticks([])
    axis.tick_params(axis="y", length=0, pad=-12)
    for label in axis.get_yticklabels():
        label.set_fontsize(10.5)
        label.set_fontweight("semibold")
    axis.set_title(
        str(plot.iloc[0]["variant"]),
        fontsize=12,
        fontweight="semibold",
        pad=7,
    )
    axis.grid(False)
    for spine in axis.spines.values():
        spine.set_visible(False)

    figure.tight_layout(pad=0.35)
    figure.savefig(output_path, dpi=250, bbox_inches="tight")
    plt.close(figure)


def get_centered_x_axis(results):
    """Return an x-axis centered on the pathway baseline."""
    values = results[
        [
            "baseline_total_kgco2e_m3",
            "low_total_kgco2e_m3",
            "high_total_kgco2e_m3",
        ]
    ]
    baseline = float(results.iloc[0]["baseline_total_kgco2e_m3"])
    maximum_deviation = max(
        abs(float(values.min().min()) - baseline),
        abs(float(values.max().max()) - baseline),
    )
    half_width = max(maximum_deviation * 1.30, 0.01)
    return [baseline - half_width, baseline + half_width]


def save_sensitivity_analysis(
    stream,
    output_dir="use_cases_results",
    low_percent=DEFAULT_LOW_CHANGE_PERCENT,
    high_percent=DEFAULT_HIGH_CHANGE_PERCENT,
):
    """Save detailed and grouped sensitivity results for every pathway."""
    from pathways import TRANSPORT_PATHWAY_GROUPS

    output_root = Path(output_dir)
    all_use_cases = pd.DataFrame(stream.get_all_use_cases())

    for group_name, group_config in TRANSPORT_PATHWAY_GROUPS.items():
        group_rows = all_use_cases[all_use_cases["pathway_id"].isin(group_config["pathways"])]
        if group_rows.empty:
            continue
        diagram_top_n = 6 if group_name == "Harvesting in steep terrain" else TOP_MACHINE_DRIVERS

        sensitivity_folder = output_root / group_config["directory"] / "sensitivity_analysis"
        sensitivity_folder.mkdir(parents=True, exist_ok=True)
        machines_folder = sensitivity_folder / "Machines"
        grouped_folder = sensitivity_folder / "Grouped"
        machines_2x2_folder = machines_folder / "2x2"
        grouped_2x2_folder = grouped_folder / "2x2"
        machines_folder.mkdir(parents=True, exist_ok=True)
        grouped_folder.mkdir(parents=True, exist_ok=True)
        machines_2x2_folder.mkdir(parents=True, exist_ok=True)
        grouped_2x2_folder.mkdir(parents=True, exist_ok=True)
        detailed_exports = []
        grouped_exports = []

        for use_case_name in group_rows["use_case"].drop_duplicates():
            rows = group_rows[group_rows["use_case"] == use_case_name]
            detailed_tables = [
                run_sensitivity_analysis(
                    row,
                    stream,
                    low_percent,
                    high_percent,
                )
                for row in rows.to_dict(orient="records")
            ]
            grouped_tables = [
                run_grouped_sensitivity_analysis(
                    row,
                    stream,
                    low_percent,
                    high_percent,
                )
                for row in rows.to_dict(orient="records")
            ]
            detailed_percent_axis = get_shared_percent_x_axis(detailed_tables, diagram_top_n)
            grouped_percent_axis = get_shared_percent_x_axis(grouped_tables, diagram_top_n)

            for row, detailed, grouped in zip(
                rows.to_dict(orient="records"),
                detailed_tables,
                grouped_tables,
            ):
                pathway_id = row["pathway_id"]
                detailed_plot = detailed.head(diagram_top_n)
                grouped_plot = grouped.head(diagram_top_n)
                save_tornado_png(
                    detailed_plot,
                    machines_folder / f"tornado_{use_case_name}_{pathway_id}_machines.png",
                    get_centered_x_axis(detailed_plot),
                )
                save_tornado_png(
                    grouped_plot,
                    grouped_folder / f"tornado_{use_case_name}_{pathway_id}_grouped.png",
                    get_centered_x_axis(grouped_plot),
                )
                save_compact_tornado_png(
                    detailed,
                    machines_2x2_folder / f"tornado_{use_case_name}_{pathway_id}_machines_compact.png",
                    detailed_percent_axis,
                    top_n=diagram_top_n,
                )
                save_compact_tornado_png(
                    grouped,
                    grouped_2x2_folder / f"tornado_{use_case_name}_{pathway_id}_grouped_compact.png",
                    grouped_percent_axis,
                    top_n=diagram_top_n,
                )
                detailed_exports.append(detailed)
                grouped_exports.append(grouped)

        pd.concat(detailed_exports, ignore_index=True).to_csv(
            machines_folder / "sensitivity_machine_parameters.csv",
            sep=";",
            decimal=",",
            index=False,
        )
        pd.concat(grouped_exports, ignore_index=True).to_csv(
            grouped_folder / "sensitivity_grouped_parameters.csv",
            sep=";",
            decimal=",",
            index=False,
        )
        legacy_outputs = list(sensitivity_folder.glob("tornado_*.png"))
        legacy_outputs.extend(
            sensitivity_folder / file_name
            for file_name in (
                "sensitivity_machine_parameters.csv",
                "sensitivity_grouped_parameters.csv",
            )
        )
        for legacy_output in legacy_outputs:
            legacy_output.unlink(missing_ok=True)
        combined_outputs = list(machines_2x2_folder.glob("*_2x2.png"))
        combined_outputs.extend(grouped_2x2_folder.glob("*_2x2.png"))
        for combined_output in combined_outputs:
            combined_output.unlink(missing_ok=True)
        print(f"Saved sensitivity analysis for {group_name}.")
