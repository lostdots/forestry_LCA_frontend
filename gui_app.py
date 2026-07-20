"""Streamlit interface for the forestry LCA model.

Each browser session works on temporary CSV copies and feeds those files into
the existing calculation code. The editors can also overwrite the repository
CSV files when the user explicitly chooses that action.
"""

from pathlib import Path
import base64
import html
import importlib
import shutil
import tempfile

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import helper_functions
import machines
import pathways

importlib.reload(machines)
importlib.reload(helper_functions)
importlib.reload(pathways)

from helper_functions import DataStream, run_pathway
from pathways import TRANSPORT_PATHWAY_GROUPS

ROOT = Path(__file__).parent
IMAGE_ROOT = ROOT
CREATOR_IMAGES = {
    "felling": IMAGE_ROOT / "Bild_Axt_am_Stock.png",
    "extraction": IMAGE_ROOT / "Bild_Forwarding.png",
    "transport": IMAGE_ROOT / "Bild_LKW.png",
}
CSV_FILES = (
    "csv_use_cases.csv",
    "csv_machines.csv",
    "csv_materials.csv",
    "csv_emission_repository.csv",
)
PHASES = ["production", "maintenance", "wtt", "ttw", "eol"]
PHASE_LABELS = {
    "production": "Produktion",
    "wtt": "WTT",
    "ttw": "TTW",
    "maintenance": "Maintenance",
    "eol": "EOL",
}
PHASE_HELP = {
    "production": "Emissionen aus Herstellung und Bereitstellung der Maschine.",
    "maintenance": "Emissionen von Wartung- und Reparatur.",
    "wtt": "Well-to-Tank: Emissionen von der Energiegewinnung bis zum Tank oder Akku.",
    "ttw": "Tank-to-Wheel: direkte Emissionen während des Maschinenbetriebs.",
    "eol": "End-of-Life: Emissionen und Gutschriften am Ende der Lebensdauer.",
}
PHASE_SUBTITLES = {
    "production": "Herstellung",
    "maintenance": "Wartung · ",
    "wtt": "Well-to-Tank",
    "ttw": "Tank-to-Wheel",
    "eol": "End-of-Life",
}
COLORS = {
    "production": "#294f78",
    "wtt": "#d09a52",
    "ttw": "#33785f",
    "maintenance": "#cbd5d1",
    "eol": "#53636a",
}
USE_CASE_LABELS = {
    "short_distance": "Kurze Distanz",
    "average_distance": "Mittlere Distanz",
    "long_distance": "Lange Distanz",
}
GROUP_LABELS = {
    "Motor-manual harvesting": "Motor-Manual Harvesting",
    "Partially automated harvesting": "Partly Automated Harvesting",
    "Harvesting in steep terrain": "Harvesting in Steep Terrain",
    "Autonomous pathway": "Autonomous Harvesting",
}
DIRECT_ROUTE_GROUPS = {
    "Motor-manual harvesting",
    "Partially automated harvesting",
    "Autonomous pathway",
}
CUSTOM_PATHWAY_GROUP = "Custom pathways"
SAVED_PATHWAY_START = "# --- Custom pathways saved from GUI: start ---"
SAVED_PATHWAY_END = "# --- Custom pathways saved from GUI: end ---"
CUSTOM_USE_CASE = "custom_scenario"
CUSTOM_FIELDS = [
    "winching_distance",
    "extraction_to_log_pile",
    "forest_distance_km",
    "street_distance_km",
    "forest_road_gradient_percent",
    "stand_to_logpile_m",
    "road_to_logpile_m",
    "direct_road_logpile_to_plant_km",
    "logpile_to_rail_terminal_km",
    "rail_km",
    "rail_terminal_to_plant_km",
    "terminal_handling_time_reduction_share",
    "empty_return_reduction_share",
]
ELECTRICITY_MIX_FACTOR_ID = "electricity_mix"
FELLING_OPTIONS = {
    "Harvester": {
        "Diesel": ["harvester_diesel"],
        "Electric": ["harvester_electric"],
    },
    "Chainsaw": {
        "Petrol": ["chainsaw_petrol"],
        "Electric": ["chainsaw_electric"],
    },
}
EXTRACTION_OPTIONS = {
    "Forwarder": {
        "Diesel": ["forwarder_diesel"],
        "Electric": ["forwarder_electric"],
        "Pully": ["forwarder_pully"],
    },
    "Tractor with winch": {
        "Diesel": ["tractor_diesel_winch", "forest_winch"],
        "Electric": ["tractor_electric_winch", "forest_winch"],
    },
    "Cable yarder": {
        "Diesel": ["cable_yarder_diesel"],
        "Electric": ["cable_yarder_electric"],
        "Recuperating": ["cable_yarder_recuperating"],
    },
}
TRANSPORT_OPTIONS = {
    "Truck": {
        "Diesel": ["truck_diesel", "truck_trailer"],
        "BEV": ["truck_bev", "truck_trailer"],
        "e-fuel": ["truck_efuel", "truck_trailer"],
        "Intermodal": [
            "truck_diesel_intermodal_container",
            "truck_trailer",
            "intermodal_container",
        ],
    },
    "Tractor with trailer": {
        "Diesel": ["tractor_diesel_trailer", "forest_trailer"],
        "Electric": ["tractor_electric_trailer", "forest_trailer"],
    },
    "Rail": {
        "Logs": ["rail", "terminal_handling_logs"],
        "Intermodal": [
            "rail_intermodal_container",
            "terminal_handling_intermodal_container",
        ],
    },
}
MACHINE_CATEGORIES = {
    "Truck": {
        "Diesel": "truck_diesel",
        "BEV": "truck_bev",
        "e-fuel": "truck_efuel",
        "Intermodal": "truck_diesel_intermodal_container",
    },
    "Tractor": {
        "Diesel winch": "tractor_diesel_winch",
        "Electric winch": "tractor_electric_winch",
        "Diesel trailer": "tractor_diesel_trailer",
        "Electric trailer": "tractor_electric_trailer",
    },
    "Harvester": {"Diesel": "harvester_diesel", "Electric": "harvester_electric"},
    "Forwarder": {
        "Diesel": "forwarder_diesel",
        "Electric": "forwarder_electric",
        "Pully": "forwarder_pully",
    },
    "Chainsaw": {"Petrol": "chainsaw_petrol", "Electric": "chainsaw_electric"},
    "Cable yarder": {
        "Diesel": "cable_yarder_diesel",
        "Electric": "cable_yarder_electric",
        "Recuperating": "cable_yarder_recuperating",
    },
    "Rail": {"Logs": "rail", "Intermodal": "rail_intermodal_container"},
    "Trailer / attachment": {
        "Truck trailer": "truck_trailer",
        "Forest trailer": "forest_trailer",
        "Forest winch": "forest_winch",
        "Intermodal container": "intermodal_container",
    },
}
FIELD_LABELS = {
    "machine_id": "Maschinen-ID",
    "pathway_id": "Pfad-ID",
    "use_case": "Use Case",
    "group": "Pfadgruppe",
    "variant": "Variante",
    "electric": "Elektrisch",
    "mass_kg": "Masse [kg]",
    "payload_kg": "Nutzlast [kg]",
    "lifetime_h": "Lebensdauer [h]",
    "lifetime_m3": "Lebensdauer [m³]",
    "productivity_m3_h": "Produktivität [m³/h]",
    "diesel_l_h": "Dieselverbrauch [l/h]",
    "gasoline_mix_l_h": "Benzingemisch [l/h]",
    "chain_oil_l_h": "Kettenöl [l/h]",
    "power_consumption_kwh_h": "Stromverbrauch [kWh/h]",
    "power_consumption_kwh_m3": "Stromverbrauch [kWh/m³]",
    "battery_capacity_kwh": "Batteriekapazität [kWh]",
    "engine_mass_ICE_kg": "Masse Verbrennungsmotor [kg]",
    "battery_mass_kg": "Batteriemasse [kg]",
    "number_of_batteries_over_lifetime": "Batterien über Lebensdauer",
    "production_factor_kgco2e_kg": "Produktionsfaktor [kg CO₂e/kg]",
    "repair_factor": "Reparaturfaktor",
    "wagon_lifetime_years": "Waggon-Lebensdauer [Jahre]",
    "wagon_km_per_year": "Waggon-Fahrleistung [km/Jahr]",
    "relocation_distance": "Umsetzdistanz [km]",
    "operating_hours_per_day": "Betriebsstunden pro Tag",
    "ttw_zero": "Keine direkten Emissionen",
    "production_model": "Produktionsmodell",
    "load_volume_m3": "Ladevolumen [m³]",
    "winching_distance": "Seilwindendistanz [m]",
    "extraction_to_log_pile": "Rückedistanz zum Polter [m]",
    "forest_distance_km": "Forststraßendistanz [km]",
    "street_distance_km": "Straßendistanz [km]",
    "forest_road_gradient_percent": "Forststraßenneigung [%]",
    "stand_to_logpile_m": "Bestand zum Polter [m]",
    "road_to_logpile_m": "Straße zum Polter [m]",
    "direct_road_logpile_to_plant_km": "Polter zum Werk [km]",
    "logpile_to_rail_terminal_km": "Polter zum Bahnterminal [km]",
    "rail_km": "Bahndistanz [km]",
    "rail_terminal_to_plant_km": "Bahnterminal zum Werk [km]",
    ELECTRICITY_MIX_FACTOR_ID: "Electricity Mix [g CO2e/kWh]",
    "factor_id": "Faktor-ID",
    "category": "Kategorie",
    "module": "Modul",
    "value": "Wert",
    "unit": "Einheit",
    "density_kg_l": "Dichte [kg/l]",
    "heating_value_kwh_kg": "Heizwert [kWh/kg]",
    "derived_kgco2e_l": "Abgeleitet [kg CO2e/l]",
    "Quelle:": "Quelle",
}


st.set_page_config(
    page_title="Forestry LCA",
    page_icon="🌲",
    layout="wide",
    initial_sidebar_state="expanded",
)


def add_styles():
    st.markdown(
        """
        <style>
        :root { --forest: #245c47; --ink: #18312a; --mist: #f4f7f5; }
        .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
            background: #fbfcfb !important; color: var(--ink) !important;
        }
        [data-testid="stSidebar"] { background: #183d31; }
        [data-testid="stSidebar"] * { color: #f5faf7 !important; }
        [data-testid="stSidebar"] [role="radiogroup"] {
            gap: .45rem;
            width: 100%;
        }
        [data-testid="stSidebar"] [data-baseweb="radio"] {
            width: 100%;
            min-height: 3.35rem;
            padding: .85rem 1rem;
            border: 1px solid transparent;
            border-radius: .7rem;
            cursor: pointer;
            transition: background .16s ease, border-color .16s ease, transform .16s ease;
        }
        [data-testid="stSidebar"] [data-baseweb="radio"] > div:first-child {
            display: none !important;
        }
        [data-testid="stSidebar"] [data-baseweb="radio"] p {
            font-size: 1.08rem !important;
            font-weight: 600 !important;
            line-height: 1.25 !important;
        }
        [data-testid="stSidebar"] [data-baseweb="radio"]:hover {
            background: rgba(255,255,255,.09);
            transform: translateX(2px);
        }
        [data-testid="stSidebar"] [data-baseweb="radio"]:has(input:checked) {
            background: rgba(255,255,255,.15);
            border-color: rgba(255,255,255,.12);
            box-shadow: inset 4px 0 0 #d09a52;
        }
        [data-testid="stSidebar"] [data-testid="stButton"] button {
            background: #f5faf7 !important;
            border-color: #91a69c !important;
        }
        [data-testid="stSidebar"] [data-testid="stButton"] button,
        [data-testid="stSidebar"] [data-testid="stButton"] button * {
            color: #18312a !important;
            -webkit-text-fill-color: #18312a !important;
        }
        [data-testid="stSidebar"] [data-testid="stButton"] button:hover {
            background: #e3ece8 !important;
            border-color: #6f8b7e !important;
        }
        [data-testid="stMain"] h1,
        [data-testid="stMain"] h2,
        [data-testid="stMain"] h3,
        [data-testid="stMain"] p,
        [data-testid="stMain"] label,
        [data-testid="stMain"] [data-testid="stWidgetLabel"] p {
            color: var(--ink) !important;
        }
        h1, h2, h3 { letter-spacing: -.02em; }

        /* All editable fields are deliberately light, independent of the
           browser or operating-system theme. */
        [data-testid="stMain"] div[data-baseweb="input"],
        [data-testid="stMain"] div[data-baseweb="select"] > div,
        [data-testid="stMain"] [data-testid="stNumberInput"] > div {
            background: #ffffff !important;
            color: var(--ink) !important;
            border-color: #91a69c !important;
        }
        [data-testid="stMain"] input,
        [data-testid="stMain"] div[data-baseweb="select"] span,
        [data-testid="stMain"] div[data-baseweb="select"] svg {
            color: var(--ink) !important;
            -webkit-text-fill-color: var(--ink) !important;
            fill: var(--ink) !important;
        }
        [data-testid="stMain"] [data-testid="stNumberInput"] button {
            background: #f1f5f3 !important;
            color: var(--ink) !important;
            border-left-color: #d4dfda !important;
        }
        [data-testid="stMain"] [data-testid="stNumberInput"] button:hover {
            background: #e3ece8 !important;
        }
        [data-testid="stMain"] [data-testid="stNumberInput"] button svg {
            fill: var(--ink) !important;
        }
        [data-testid="stMain"] [data-testid="stFormSubmitButton"] button {
            background: #2f674f !important;
            border-color: #2f674f !important;
            min-height: 2.8rem;
        }
        [data-testid="stMain"] [data-testid="stFormSubmitButton"] button,
        [data-testid="stMain"] [data-testid="stFormSubmitButton"] button * {
            color: #ffffff !important;
            -webkit-text-fill-color: #ffffff !important;
            font-weight: 650 !important;
        }
        [data-testid="stMain"] [data-testid="stFormSubmitButton"] button:hover {
            background: #24523f !important;
            border-color: #24523f !important;
        }
        [data-testid="stMain"] [data-testid="stFormSubmitButton"] button:focus-visible {
            box-shadow: 0 0 0 .2rem rgba(47,103,79,.24) !important;
        }
        .lca-metric-card {
            background: #ffffff;
            border: 1px solid #cbd9d2;
            border-radius: .7rem;
            padding: .8rem 1rem;
            min-width: 0;
            min-height: 6.7rem;
            display: flex;
            flex-direction: column;
            justify-content: center;
            box-shadow: 0 2px 12px rgba(20,55,42,.04);
        }
        .lca-metric-title {
            color: var(--ink);
            font-size: clamp(.9rem, 1vw, 1.05rem);
            font-weight: 650;
            line-height: 1.2;
        }
        .lca-metric-subtitle {
            color: #6b7d75;
            font-size: clamp(.7rem, .78vw, .82rem);
            line-height: 1.2;
            margin-top: .15rem;
        }
        .lca-metric-result {
            display: flex;
            align-items: baseline;
            flex-wrap: wrap;
            column-gap: .3rem;
            row-gap: 0;
            margin-top: .55rem;
            color: var(--ink);
        }
        .lca-metric-number {
            font-size: clamp(1.15rem, 1.45vw, 1.5rem);
            font-weight: 600;
            line-height: 1.1;
            white-space: nowrap;
        }
        .lca-metric-unit {
            color: #52635c;
            font-size: clamp(.72rem, .82vw, .88rem);
            line-height: 1.2;
            white-space: nowrap;
        }
        [data-testid="stSegmentedControl"] {
            width: fit-content;
            max-width: 100%;
            margin: .15rem 0 1.25rem 0;
        }
        [data-testid="stSegmentedControl"] [role="radiogroup"] {
            display: inline-flex;
            gap: 0;
            padding: .18rem;
            background: #ffffff;
            border: 1px solid #d4dfda;
            border-radius: .78rem;
            box-shadow: 0 2px 12px rgba(20,55,42,.04);
            overflow: hidden;
        }
        [data-testid="stSegmentedControl"] label {
            min-width: 8.2rem;
            min-height: 2.45rem;
            margin: 0 !important;
            border-radius: .62rem !important;
            border: 0 !important;
            color: #263c35 !important;
            background: transparent !important;
            transition: background .16s ease, color .16s ease, box-shadow .16s ease;
        }
        [data-testid="stSegmentedControl"] label:hover {
            background: #f1f5f3 !important;
        }
        [data-testid="stSegmentedControl"] label:has(input:checked) {
            background: #e5eee9 !important;
            color: #12382c !important;
            box-shadow: 0 1px 8px rgba(36,92,71,.10);
        }
        [data-testid="stSegmentedControl"] label p {
            font-weight: 650 !important;
            line-height: 1.1 !important;
            text-align: center !important;
            color: inherit !important;
        }
        [data-testid="stMain"] [data-testid="stButton"] button {
            background: #2f674f !important;
            border-color: #2f674f !important;
            min-height: 2.7rem;
        }
        [data-testid="stMain"] [data-testid="stButton"] button,
        [data-testid="stMain"] [data-testid="stButton"] button * {
            color: #ffffff !important;
            -webkit-text-fill-color: #ffffff !important;
            font-weight: 650 !important;
        }
        [data-testid="stMain"] [data-testid="stButton"] button:hover {
            background: #24523f !important;
            border-color: #24523f !important;
        }
        .creator-row {
            display: grid;
            grid-template-columns: minmax(120px, 190px) minmax(260px, 1fr);
            gap: 1rem;
            align-items: center;
            padding: 1rem;
            border: 1px solid #d4dfda;
            border-radius: .72rem;
            background: #ffffff;
            box-shadow: 0 2px 12px rgba(20,55,42,.04);
            margin-bottom: .8rem;
        }
        .creator-image {
            min-height: 9rem;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: .8rem 0 0 .8rem;
        }
        .creator-image img {
            width: 100%;
            max-width: 10rem;
            max-height: 8rem;
            object-fit: contain;
            opacity: .78;
        }
        .creator-kicker {
            color: #60766d;
            font-size: .78rem;
            font-weight: 700;
            letter-spacing: .04em;
            text-transform: uppercase;
            margin-bottom: .35rem;
        }
        .creator-preview {
            display: flex;
            align-items: center;
            gap: .45rem;
            flex-wrap: wrap;
            padding: 1rem;
            border: 1px solid #d4dfda;
            border-radius: .72rem;
            background: #ffffff;
            box-shadow: 0 2px 12px rgba(20,55,42,.04);
        }
        .creator-node {
            min-width: 7.8rem;
            padding: .75rem .9rem;
            border-radius: 999px;
            background: #e5eee9;
            color: #12382c;
            text-align: center;
            font-weight: 700;
            border: 1px solid #c6d8d0;
        }
        .creator-node.start, .creator-node.end {
            background: #2f674f;
            color: #ffffff;
            border-color: #2f674f;
        }
        .creator-arrow {
            color: #6f8b7e;
            font-weight: 800;
        }
        div[data-baseweb="select"], div[data-testid="stNumberInput"] { max-width: 100%; }
        [data-testid="stPlotlyChart"] { background: #ffffff !important; }
        [data-testid="stPlotlyChart"] .modebar-btn path {
            fill: #52635c !important;
        }
        .hint { color: #60766d; font-size: .92rem; }
        .placeholder {
            padding: 2.4rem; border: 1px dashed #9eb4aa; border-radius: .8rem;
            background: var(--mist); text-align: center;
        }
        .creator-credit {
            margin: -.15rem 0 1.1rem 0;
            color: rgba(245,250,247,.62);
            font-size: .76rem;
            font-style: italic;
            font-weight: 400;
            line-height: 1.25;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def session_dir() -> Path:
    if "session_dir" not in st.session_state:
        folder = Path(tempfile.mkdtemp(prefix="forestry_lca_gui_"))
        for name in CSV_FILES:
            shutil.copy2(ROOT / name, folder / name)
        st.session_state.session_dir = str(folder)
    return Path(st.session_state.session_dir)


def read_csv(name: str) -> pd.DataFrame:
    return pd.read_csv(session_dir() / name, sep=";", decimal=",")


def write_csv(data: pd.DataFrame, name: str):
    data.to_csv(session_dir() / name, sep=";", decimal=",", index=False)


def overwrite_original_csv(name: str):
    """Copy the current session CSV back to the repository CSV file."""
    shutil.copy2(session_dir() / name, ROOT / name)


def reset_session_files():
    for name in CSV_FILES:
        shutil.copy2(ROOT / name, session_dir() / name)
    for key in list(st.session_state):
        if key == "custom_pathways" or key.startswith(
            (
                "machine_",
                "case_",
                "live_",
                "metric_variant_",
                "machine_role_",
                "_machine_role_",
                "selected_machine_role_",
                "creator_",
                "custom_pathway_name",
                "standard_electricity_mix_gco2e",
                "machine_editor_",
                "machine_result_",
                "_machine_result_",
                "case_group",
                "case_variant",
                "case_use_case",
                "_case_",
                "emission_",
                "_emission_",
            )
        ):
            del st.session_state[key]


def sync_widget_value(widget_key: str, state_key: str):
    st.session_state[state_key] = st.session_state[widget_key]


def prepare_widget_value(widget_key: str, state_key: str, options: list, default=None):
    if not options:
        return None
    fallback = default if default in options else options[0]
    if st.session_state.get(state_key) not in options:
        st.session_state[state_key] = fallback
    st.session_state[widget_key] = st.session_state[state_key]
    return st.session_state[state_key]


def variant_button_label(variant: str) -> str:
    return variant


def variant_buttons(
    label: str, variants: list[str], key: str, preferred: str | None = None
) -> str:
    index = variants.index(preferred) if preferred in variants else 0
    return st.segmented_control(
        label,
        variants,
        default=variants[index],
        key=key,
        required=True,
        format_func=variant_button_label,
        label_visibility="collapsed",
        width="content",
    )


def row_for_variant(data: pd.DataFrame, variant: str) -> pd.Series | None:
    rows = data[data["variant"] == variant]
    return None if rows.empty else rows.iloc[0]


def slugify_pathway_id(label: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "_" for char in label).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return f"CUSTOM_{slug or 'pathway'}".upper()


def custom_pathways() -> dict:
    return st.session_state.setdefault("custom_pathways", {})


def display_steps_from_sequence(machine_ids: list[str]) -> list[dict]:
    steps = []
    index = 0
    while index < len(machine_ids):
        machine_id = machine_ids[index]
        next_id = machine_ids[index + 1] if index + 1 < len(machine_ids) else None
        third_id = machine_ids[index + 2] if index + 2 < len(machine_ids) else None
        if (
            machine_id.startswith("tractor_")
            and machine_id.endswith("_winch")
            and next_id == "forest_winch"
        ):
            steps.append({"label": "Tractor with winch", "indices": [index, index + 1]})
            index += 2
        elif (
            machine_id.startswith("tractor_")
            and machine_id.endswith("_trailer")
            and next_id == "forest_trailer"
        ):
            steps.append(
                {"label": "Tractor with trailer", "indices": [index, index + 1]}
            )
            index += 2
        elif (
            machine_id.startswith("truck_")
            and next_id == "truck_trailer"
            and third_id == "intermodal_container"
        ):
            steps.append(
                {"label": "Truck intermodal", "indices": [index, index + 1, index + 2]}
            )
            index += 3
        elif machine_id.startswith("truck_") and next_id == "truck_trailer":
            steps.append({"label": "Truck", "indices": [index, index + 1]})
            index += 2
        elif (
            machine_id.startswith("rail")
            and next_id
            and next_id.startswith("terminal_handling")
        ):
            steps.append({"label": "Rail", "indices": [index, index + 1]})
            index += 2
        else:
            steps.append(
                {"label": machine_id.replace("_", " ").title(), "indices": [index]}
            )
            index += 1
    return steps


def custom_group_name(pathway_id: str, config: dict | None = None) -> str:
    if config and config.get("label"):
        return config["label"]
    data = read_csv("csv_use_cases.csv")
    rows = data[data["pathway_id"] == pathway_id]
    if not rows.empty:
        return str(
            rows.iloc[0].get("group") or rows.iloc[0].get("variant") or pathway_id
        )
    return pathway_id


def custom_roles_from_sequence(machine_ids: list[str]) -> dict:
    return {
        index: step["label"]
        for index, step in enumerate(display_steps_from_sequence(machine_ids))
    }


def active_pathway_groups() -> dict:
    groups = {
        name: {**config, "pathways": list(config["pathways"])}
        for name, config in TRANSPORT_PATHWAY_GROUPS.items()
    }
    for pathway_id, machine_ids in pathways.PATHWAY_STEPS.items():
        if not pathway_id.startswith("CUSTOM_"):
            continue
        group_name = custom_group_name(pathway_id)
        groups[group_name] = {
            "directory": "custom_pathways",
            "pathways": [pathway_id],
            "machine_roles": custom_roles_from_sequence(machine_ids),
        }
    for pathway_id, config in custom_pathways().items():
        groups[custom_group_name(pathway_id, config)] = {
            "directory": "custom_pathways",
            "pathways": [pathway_id],
            "machine_roles": {
                index: step["label"]
                for index, step in enumerate(config["display_steps"])
            },
        }
    return groups


def apply_custom_pathways():
    for pathway_id, config in custom_pathways().items():
        pathways.PATHWAY_STEPS[pathway_id] = list(config["machines"])
        helper_functions.PATHWAY_STEPS[pathway_id] = list(config["machines"])
        TRANSPORT_PATHWAY_GROUPS[custom_group_name(pathway_id, config)] = {
            "directory": "custom_pathways",
            "pathways": [pathway_id],
            "machine_roles": {
                index: step["label"]
                for index, step in enumerate(config["display_steps"])
            },
        }


def add_custom_use_case_row(pathway_id: str, label: str, values: dict):
    data = read_csv("csv_use_cases.csv")
    row = {column: "" for column in data.columns}
    row.update(
        {
            "group": label,
            "variant": label,
            "pathway_id": pathway_id,
            "use_case": CUSTOM_USE_CASE,
        }
    )
    for field in CUSTOM_FIELDS:
        if field in row:
            row[field] = values.get(field, "")
    data = data[data["pathway_id"] != pathway_id]
    data = pd.concat([data, pd.DataFrame([row])], ignore_index=True)
    write_csv(data, "csv_use_cases.csv")


def remove_custom_pathway(pathway_id: str):
    config = custom_pathways().pop(pathway_id, None)
    group_name = custom_group_name(pathway_id, config)
    pathways.PATHWAY_STEPS.pop(pathway_id, None)
    helper_functions.PATHWAY_STEPS.pop(pathway_id, None)
    TRANSPORT_PATHWAY_GROUPS.pop(group_name, None)
    data = read_csv("csv_use_cases.csv")
    data = data[data["pathway_id"] != pathway_id]
    write_csv(data, "csv_use_cases.csv")


def write_saved_pathways_block():
    saved_pathways = {}
    saved_groups = {}
    for pathway_id, machine_ids in pathways.PATHWAY_STEPS.items():
        if pathway_id.startswith("CUSTOM_"):
            saved_pathways[pathway_id] = list(machine_ids)
            group_name = custom_group_name(
                pathway_id, custom_pathways().get(pathway_id)
            )
            saved_groups[group_name] = {
                "directory": "custom_pathways",
                "pathways": [pathway_id],
                "machine_roles": custom_roles_from_sequence(list(machine_ids)),
            }
    block_lines = [SAVED_PATHWAY_START, f"PATHWAY_STEPS.update({saved_pathways!r})"]
    for group_name, config in saved_groups.items():
        block_lines.append(f"TRANSPORT_PATHWAY_GROUPS[{group_name!r}] = {config!r}")
    block_lines.extend([SAVED_PATHWAY_END, ""])
    block = "\n".join(block_lines)
    path = ROOT / "pathways.py"
    source = path.read_text(encoding="utf-8")
    if SAVED_PATHWAY_START in source and SAVED_PATHWAY_END in source:
        before, rest = source.split(SAVED_PATHWAY_START, 1)
        _, after = rest.split(SAVED_PATHWAY_END, 1)
        source = before.rstrip() + "\n\n" + block + after.lstrip("\n")
    else:
        source = source.rstrip() + "\n\n" + block
    path.write_text(source, encoding="utf-8")


def save_custom_pathway_to_original(pathway_id: str):
    write_saved_pathways_block()
    session_data = read_csv("csv_use_cases.csv")
    original = pd.read_csv(ROOT / "csv_use_cases.csv", sep=";", decimal=",")
    original = original[original["pathway_id"] != pathway_id]
    rows = session_data[session_data["pathway_id"] == pathway_id]
    original = pd.concat([original, rows], ignore_index=True)
    original.to_csv(ROOT / "csv_use_cases.csv", sep=";", decimal=",", index=False)


def calculate() -> tuple[pd.DataFrame, pd.DataFrame]:
    apply_custom_pathways()
    folder = session_dir()
    stream = DataStream(
        use_cases_path=folder / "csv_use_cases.csv",
        machines_path=folder / "csv_machines.csv",
        materials_path=folder / "csv_materials.csv",
        emission_repository_path=folder / "csv_emission_repository.csv",
    )
    results, machines = [], []
    materials = stream.get_all_materials()
    factors = stream.get_all_emission_factors()
    for row in stream.get_all_use_cases():
        results.append(
            run_pathway(row, stream, materials, factors, machine_results=machines)
        )
    pathway_df = pd.DataFrame(results)
    machine_df = pd.DataFrame(machines)
    return pathway_df, machine_df


def phase_metrics(row: pd.Series | None):
    columns = st.columns(5)
    for column, phase in zip(columns, PHASES):
        value = 0.0 if row is None else float(row.get(phase, 0.0))
        formatted_value = f"{value:.3f}".replace(".", ",")
        column.markdown(
            f"""
            <div class="lca-metric-card" title="{PHASE_HELP[phase]}">
                <div class="lca-metric-title">{PHASE_LABELS[phase]}</div>
                <div class="lca-metric-subtitle">{PHASE_SUBTITLES[phase]}</div>
                <div class="lca-metric-result">
                    <span class="lca-metric-number">{formatted_value}</span>
                    <span class="lca-metric-unit">kg CO₂e/m³</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def stacked_chart(
    data: pd.DataFrame,
    x: str,
    title: str,
    show_totals: bool = True,
):
    plot = data.copy()
    categories = plot[x].astype(str).tolist()
    figure = go.Figure()
    for phase in PHASES:
        figure.add_bar(
            x=categories,
            y=plot[phase].astype(float),
            name=PHASE_LABELS[phase],
            marker_color=COLORS[phase],
            offsetgroup="lca-stack",
            alignmentgroup="lca-stack",
            hovertemplate=f"{PHASE_LABELS[phase]}: %{{y:.3f}} kg CO₂e/m³<extra></extra>",
        )

    if show_totals:
        positive_tops = plot[PHASES].clip(lower=0).sum(axis=1)
        net_totals = plot[PHASES].sum(axis=1)
        for category, top, total in zip(categories, positive_tops, net_totals):
            figure.add_annotation(
                x=category,
                y=float(top),
                text=f"{total:.2f}",
                showarrow=False,
                yshift=12,
                font=dict(color="#18312a", size=13),
            )

    figure.update_layout(
        title=title,
        barmode="relative",
        bargap=0.42,
        height=440,
        margin=dict(l=20, r=20, t=65, b=20),
        legend_title_text="Lebenszyklusphase",
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(color="#18312a", size=14),
        title_font=dict(color="#18312a", size=20),
        legend=dict(font=dict(color="#18312a"), title_font=dict(color="#18312a")),
        hovermode="x unified",
    )
    figure.update_xaxes(
        showgrid=False,
        color="#18312a",
        tickfont=dict(color="#18312a"),
        title_font=dict(color="#18312a"),
        linecolor="#52635c",
        tickmode="array",
        tickvals=categories,
        ticktext=[f"<b>{label}</b>" for label in categories],
    )
    figure.update_yaxes(
        color="#18312a",
        tickfont=dict(color="#18312a"),
        title_font=dict(color="#18312a"),
        gridcolor="#dfe8e3",
        zerolinecolor="#52635c",
    )
    st.plotly_chart(figure, width="stretch")


def editable_fields(row: pd.Series, prefix: str, locked: set[str]) -> dict:
    values = {}
    fields = [
        field for field in row.index if field not in locked and not pd.isna(row[field])
    ]
    columns = st.columns(3)
    for index, field in enumerate(fields):
        current = row[field]
        label = FIELD_LABELS.get(field, field.replace("_", " ").title())
        key = f"{prefix}_{field}"
        with columns[index % 3]:
            if isinstance(current, (bool, pd.BooleanDtype)) or field in {
                "electric",
                "ttw_zero",
            }:
                values[field] = st.selectbox(
                    label, [True, False], index=0 if bool(current) else 1, key=key
                )
            elif isinstance(current, str):
                values[field] = st.text_input(label, value=current, key=key)
            else:
                number = float(current)
                step = (
                    1.0
                    if number == 0 or number.is_integer()
                    else max(abs(number) / 100, 0.01)
                )
                values[field] = st.number_input(
                    label, value=number, step=float(step), format="%.6g", key=key
                )
    return values


def current_electricity_mix_gco2e() -> float:
    data = read_csv("csv_emission_repository.csv")
    rows = data[data["factor_id"] == ELECTRICITY_MIX_FACTOR_ID]
    if rows.empty:
        return 310.0
    value = rows.iloc[0].get("value", 0.31)
    return round((0.31 if pd.isna(value) else float(value)) * 1000, 3)


def update_electricity_mix(widget_key: str):
    data = read_csv("csv_emission_repository.csv")
    rows = data["factor_id"] == ELECTRICITY_MIX_FACTOR_ID
    if not rows.any():
        return
    data.loc[rows, "value"] = float(st.session_state[widget_key]) / 1000
    write_csv(data, "csv_emission_repository.csv")


def update_live_use_case(group: str, use_case: str, field: str, widget_key: str):
    """Persist a live input and keep direct-road distance fields consistent."""
    data = read_csv("csv_use_cases.csv")
    rows = (data["group"] == group) & (data["use_case"] == use_case)
    data.loc[rows, field] = float(st.session_state[widget_key])

    if group in DIRECT_ROUTE_GROUPS:
        first = data.loc[rows].iloc[0]
        forest = (
            0.0
            if pd.isna(first["forest_distance_km"])
            else float(first["forest_distance_km"])
        )
        street = (
            0.0
            if pd.isna(first["street_distance_km"])
            else float(first["street_distance_km"])
        )

        if field == "direct_road_logpile_to_plant_km":
            street = max(float(st.session_state[widget_key]) - forest, 0.0)
            data.loc[rows, "street_distance_km"] = street
            related_key = f"live_{group}_{use_case}_street_distance_km"
            if related_key in st.session_state:
                st.session_state[related_key] = street
        elif field in {"forest_distance_km", "street_distance_km"}:
            total = forest + street
            data.loc[rows, "direct_road_logpile_to_plant_km"] = total
            related_key = f"live_{group}_{use_case}_direct_road_logpile_to_plant_km"
            if related_key in st.session_state:
                st.session_state[related_key] = total

    write_csv(data, "csv_use_cases.csv")


def standard_scenario():
    use_cases = read_csv("csv_use_cases.csv")

    left, right = st.columns([1.05, 2.2], gap="large")
    with left:
        st.title("Szenario Auswahl")
        st.caption("Auswertung mit bestehender LCA-Rechenlogik")
        pathway_groups = active_pathway_groups()
        group_options = list(pathway_groups)
        group = prepare_widget_value("_standard_group", "standard_group", group_options)
        group = st.selectbox(
            "Harvesting-Pfad",
            group_options,
            key="_standard_group",
            on_change=sync_widget_value,
            args=("_standard_group", "standard_group"),
            format_func=lambda value: GROUP_LABELS.get(value, value),
        )
        options = (
            use_cases.loc[use_cases["group"] == group, "use_case"]
            .drop_duplicates()
            .tolist()
        )
        use_case = prepare_widget_value(
            "_standard_use_case", "standard_use_case", options
        )
        use_case = st.selectbox(
            "Distanz-Szenario",
            options,
            key="_standard_use_case",
            on_change=sync_widget_value,
            args=("_standard_use_case", "standard_use_case"),
            format_func=lambda item: USE_CASE_LABELS.get(item, item),
        )

    selected = use_cases[
        (use_cases["group"] == group) & (use_cases["use_case"] == use_case)
    ]
    variants = selected["variant"].tolist()

    with right:
        st.title("Szenarioparameter")
        st.caption(
            "Jede Änderung wird sofort in die temporäre CSV geschrieben und neu berechnet."
        )
        electricity_mix_key = "standard_electricity_mix_gco2e"
        st.slider(
            FIELD_LABELS[ELECTRICITY_MIX_FACTOR_ID],
            min_value=0,
            max_value=800,
            value=int(round(current_electricity_mix_gco2e())),
            step=1,
            key=electricity_mix_key,
            on_change=update_electricity_mix,
            args=(electricity_mix_key,),
        )
        update_electricity_mix(electricity_mix_key)

        live_fields = [
            field for field in use_cases.columns[4:] if not selected[field].isna().all()
        ]
        inputs = st.columns(3)
        for index, field in enumerate(live_fields):
            current = selected.iloc[0][field]
            value = 0.0 if pd.isna(current) else float(current)
            widget_key = f"live_{group}_{use_case}_{field}"
            input_options = {
                "label": FIELD_LABELS.get(field, field),
                "step": 1.0 if value == 0 or value.is_integer() else 0.1,
                "key": widget_key,
                "on_change": update_live_use_case,
                "args": (group, use_case, field, widget_key),
            }
            if widget_key not in st.session_state:
                input_options["value"] = value
            inputs[index % 3].number_input(**input_options)

    pathway_df, machine_df = calculate()
    pathway_groups = active_pathway_groups()
    pathways = pathway_groups[group]["pathways"]
    overview = pathway_df[
        (pathway_df["pathway_id"].isin(pathways)) & (pathway_df["use_case"] == use_case)
    ].copy()

    st.divider()
    st.subheader("Emissionspfade im Vergleich")
    overview_variant = variant_buttons(
        "Kennzahlen anzeigen für",
        variants,
        f"metric_variant_overview_{group}_{use_case}",
    )
    overview_detail = row_for_variant(overview, overview_variant)
    phase_metrics(overview_detail)
    stacked_chart(
        overview, "variant", f"{group} · {USE_CASE_LABELS.get(use_case, use_case)}"
    )

    st.subheader("Maschinenemissionen")
    machine_variant = variant_buttons(
        "Kennzahlen und Maschinen anzeigen für",
        variants,
        f"metric_variant_machines_{group}_{use_case}",
        preferred=overview_variant,
    )
    machine_detail = row_for_variant(overview, machine_variant)
    selected_pathway = None if machine_detail is None else machine_detail["pathway_id"]
    all_machines = machine_df[
        (machine_df["pathway_id"] == selected_pathway)
        & (machine_df["use_case"] == use_case)
    ].copy()
    all_machines["Maschine"] = (
        all_machines["machine_id"].str.replace("_", " ").str.title()
    )
    phase_metrics(machine_detail)
    stacked_chart(
        all_machines,
        "Maschine",
        f"Alle Maschinen · {machine_variant}",
    )

    st.subheader("Maschinenemissionen für jeden Pfad")
    roles = TRANSPORT_PATHWAY_GROUPS[group]["machine_roles"]
    role_options = []
    for step, role in roles.items():
        role_data = machine_df[
            (machine_df["pathway_id"].isin(pathways))
            & (machine_df["use_case"] == use_case)
            & (machine_df["step_index"] == step)
        ]
        if not role_data.empty:
            role_options.append((step, role))

    selected_step, selected_role = st.selectbox(
        "Maschine auswählen",
        role_options,
        key=f"machine_role_{group}_{use_case}",
        format_func=lambda item: item[1],
    )
    role_data = machine_df[
        (machine_df["pathway_id"].isin(pathways))
        & (machine_df["use_case"] == use_case)
        & (machine_df["step_index"] == selected_step)
    ].copy()
    role_variants = role_data["variant"].tolist()
    role_variant = variant_buttons(
        "Kennzahlen anzeigen für",
        role_variants,
        f"metric_variant_role_{group}_{use_case}_{selected_step}",
        preferred=machine_variant,
    )
    role_detail = row_for_variant(role_data, role_variant)
    st.markdown(f"### {selected_role}")
    phase_metrics(role_detail)
    stacked_chart(role_data, "variant", selected_role)


def machines_editor():
    st.title("Anpassung Machines")
    st.caption(
        "Maschine, Untertyp und Szenario auswählen; Änderungen bleiben zunächst in der temporären CSV."
    )
    data = read_csv("csv_machines.csv")

    category = st.selectbox(
        "Maschine", list(MACHINE_CATEGORIES), key="machine_editor_category"
    )
    variants = MACHINE_CATEGORIES[category]
    if st.session_state.get("machine_editor_variant") not in variants:
        st.session_state["machine_editor_variant"] = next(iter(variants))
    subtype = st.selectbox(
        "Unterkategorie", list(variants), key="machine_editor_variant"
    )
    machine_id = variants[subtype]

    index = data.index[data["machine_id"] == machine_id][0]
    row = data.loc[index]
    st.subheader(machine_id.replace("_", " ").title())
    with st.form("machine_form"):
        updates = editable_fields(row, f"machine_{machine_id}", {"machine_id"})
        submit_col, overwrite_col, _ = st.columns([0.20, 0.24, 0.56], gap="small")
        submitted = submit_col.form_submit_button(
            "Änderungen übernehmen", type="primary"
        )
        overwrite_submitted = overwrite_col.form_submit_button(
            "Original-CSV überschreiben"
        )
    if submitted or overwrite_submitted:
        for field, value in updates.items():
            data.at[index, field] = value
        write_csv(data, "csv_machines.csv")
        if overwrite_submitted:
            overwrite_original_csv("csv_machines.csv")
            st.success(
                "Maschine wurde in der temporären CSV und in der Original-CSV aktualisiert."
            )
        else:
            st.success("Maschine wurde in der temporären CSV aktualisiert.")

    st.markdown("### Auswirkung im Szenario")
    use_cases = read_csv("csv_use_cases.csv")
    groups = use_cases["group"].drop_duplicates().tolist()
    scenario_group = prepare_widget_value(
        "_machine_result_group", "machine_result_group", groups
    )
    scenario_group = st.selectbox(
        "Harvesting-Pfad",
        groups,
        key="_machine_result_group",
        on_change=sync_widget_value,
        args=("_machine_result_group", "machine_result_group"),
        format_func=lambda value: GROUP_LABELS.get(value, value),
    )
    group_data = use_cases[use_cases["group"] == scenario_group]
    scenarios = group_data["use_case"].drop_duplicates().tolist()
    scenario = prepare_widget_value(
        "_machine_result_use_case", "machine_result_use_case", scenarios
    )
    scenario = st.selectbox(
        "Distanz-Szenario",
        scenarios,
        key="_machine_result_use_case",
        on_change=sync_widget_value,
        args=("_machine_result_use_case", "machine_result_use_case"),
        format_func=lambda value: USE_CASE_LABELS.get(value, value),
    )
    _pathway_df, machine_df = calculate()
    chart_data = machine_df[
        (machine_df["machine_id"] == machine_id)
        & (machine_df["group"] == scenario_group)
        & (machine_df["use_case"] == scenario)
    ].copy()
    if chart_data.empty:
        st.info("Diese Maschine kommt im gewählten Szenario nicht vor.")
    else:
        result_variants = chart_data["variant"].tolist()
        selected_result_variant = variant_buttons(
            "Kennzahlen anzeigen für",
            result_variants,
            f"machine_editor_metric_variant_{machine_id}_{scenario_group}_{scenario}",
        )
        phase_metrics(row_for_variant(chart_data, selected_result_variant))
        stacked_chart(
            chart_data,
            "variant",
            f"{machine_id.replace('_', ' ').title()} · {GROUP_LABELS.get(scenario_group, scenario_group)}",
        )

    st.download_button(
        "Aktuelle Machines-CSV herunterladen",
        data=read_csv("csv_machines.csv").to_csv(sep=";", decimal=",", index=False),
        file_name="csv_machines.csv",
        mime="text/csv",
    )


def use_cases_editor():
    st.title("Anpassung Use Cases")
    st.caption(
        "Hier können die verschiedenen Use Cases ausgewählt und deren Werte abgeändert werden."
    )
    data = read_csv("csv_use_cases.csv")
    groups = data["group"].drop_duplicates().tolist()
    group = prepare_widget_value("_case_group", "case_group", groups)
    group = st.selectbox(
        "Harvesting-Pfad",
        groups,
        key="_case_group",
        on_change=sync_widget_value,
        args=("_case_group", "case_group"),
        format_func=lambda value: GROUP_LABELS.get(value, value),
    )
    group_data = data[data["group"] == group]
    variants = group_data["variant"].drop_duplicates().tolist()
    variant = prepare_widget_value("_case_variant", "case_variant", variants)
    variant = st.selectbox(
        "Variante",
        variants,
        key="_case_variant",
        on_change=sync_widget_value,
        args=("_case_variant", "case_variant"),
    )
    variant_data = group_data[group_data["variant"] == variant]
    scenarios = variant_data["use_case"].drop_duplicates().tolist()
    use_case = prepare_widget_value("_case_use_case", "case_use_case", scenarios)
    use_case = st.selectbox(
        "Distanz-Szenario",
        scenarios,
        key="_case_use_case",
        on_change=sync_widget_value,
        args=("_case_use_case", "case_use_case"),
        format_func=lambda value: USE_CASE_LABELS.get(value, value),
    )
    index = variant_data.index[variant_data["use_case"] == use_case][0]
    row = data.loc[index]
    with st.form("use_case_form"):
        updates = editable_fields(
            row,
            f"case_{row['pathway_id']}_{use_case}",
            {"group", "variant", "pathway_id", "use_case"},
        )
        submit_col, overwrite_col, _ = st.columns([0.20, 0.24, 0.56], gap="small")
        submitted = submit_col.form_submit_button(
            "Änderungen übernehmen", type="primary"
        )
        overwrite_submitted = overwrite_col.form_submit_button(
            "Original-CSV überschreiben"
        )
    if submitted or overwrite_submitted:
        for field, value in updates.items():
            data.at[index, field] = value
        write_csv(data, "csv_use_cases.csv")
        if overwrite_submitted:
            overwrite_original_csv("csv_use_cases.csv")
            st.success(
                "Use Case wurde in der temporären CSV und in der Original-CSV aktualisiert."
            )
        else:
            st.success("Use Case wurde in der temporären CSV aktualisiert.")
    st.download_button(
        "Aktuelle Use-Cases-CSV herunterladen",
        data=read_csv("csv_use_cases.csv").to_csv(sep=";", decimal=",", index=False),
        file_name="csv_use_cases.csv",
        mime="text/csv",
    )


def format_emission_value(value) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).replace(".", ",")


def parse_emission_value(raw: str):
    text = str(raw).strip()
    if text == "":
        return ""
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return text


def emission_factor_fields(row: pd.Series, prefix: str) -> dict:
    updates = {}
    columns = st.columns(3)
    for index, field in enumerate(row.index):
        if field == "factor_id":
            continue
        label = FIELD_LABELS.get(field, field.replace("_", " ").title())
        key = f"{prefix}_{field}"
        with columns[index % 3]:
            raw = st.text_input(label, value=format_emission_value(row[field]), key=key)
        updates[field] = parse_emission_value(raw)
    return updates


def emission_factors_editor():
    st.title("Anpassung Emissionsfaktoren")
    st.caption(
        "Emissionsfaktor auswählen, Werte ändern und zunächst in der temporären CSV speichern."
    )
    data = read_csv("csv_emission_repository.csv")
    categories = data["category"].fillna("Sonstige").drop_duplicates().tolist()
    category = prepare_widget_value(
        "_emission_category", "emission_category", categories
    )
    category = st.selectbox(
        "Kategorie",
        categories,
        key="_emission_category",
        on_change=sync_widget_value,
        args=("_emission_category", "emission_category"),
    )
    category_data = data[data["category"].fillna("Sonstige") == category]
    factors = category_data["factor_id"].astype(str).tolist()
    factor_id = prepare_widget_value("_emission_factor", "emission_factor", factors)
    factor_id = st.selectbox(
        "Faktor",
        factors,
        key="_emission_factor",
        on_change=sync_widget_value,
        args=("_emission_factor", "emission_factor"),
        format_func=lambda value: value.replace("_", " "),
    )

    index = data.index[data["factor_id"].astype(str) == factor_id][0]
    row = data.loc[index]
    st.subheader(factor_id.replace("_", " ").title())
    with st.form("emission_factor_form"):
        updates = emission_factor_fields(row, f"emission_{factor_id}")
        submit_col, overwrite_col, _ = st.columns([0.20, 0.24, 0.56], gap="small")
        submitted = submit_col.form_submit_button(
            "Änderungen übernehmen", type="primary"
        )
        overwrite_submitted = overwrite_col.form_submit_button(
            "Original-CSV überschreiben"
        )
    if submitted or overwrite_submitted:
        for field, value in updates.items():
            data.at[index, field] = value
        write_csv(data, "csv_emission_repository.csv")
        if overwrite_submitted:
            overwrite_original_csv("csv_emission_repository.csv")
            st.success(
                "Emissionsfaktor wurde in der temporären CSV und in der Original-CSV aktualisiert."
            )
        else:
            st.success("Emissionsfaktor wurde in der temporären CSV aktualisiert.")

    st.download_button(
        "Aktuelle Emissionsfaktoren-CSV herunterladen",
        data=read_csv("csv_emission_repository.csv").to_csv(
            sep=";", decimal=",", index=False
        ),
        file_name="csv_emission_repository.csv",
        mime="text/csv",
    )


def option_label(machine: str, variant: str) -> str:
    return f"{machine} - {variant}"


def match_option(machine_ids: list[str], start: int, options: dict):
    for machine, variants in options.items():
        for variant, sequence in variants.items():
            end = start + len(sequence)
            if machine_ids[start:end] == sequence:
                return machine, variant, end
    first_machine = next(iter(options))
    first_variant = next(iter(options[first_machine]))
    return first_machine, first_variant, start


def load_creator_from_sequence(
    label: str, machine_ids: list[str], values: dict | None = None
):
    st.session_state["custom_pathway_name"] = label
    for field in CUSTOM_FIELDS:
        value = "" if values is None else values.get(field, "")
        if pd.isna(value):
            value = ""
        st.session_state[f"creator_{field}"] = str(value)
    index = 0
    felling_machine, felling_variant, index = match_option(
        machine_ids, index, FELLING_OPTIONS
    )
    extraction_machine, extraction_variant, index = match_option(
        machine_ids, index, EXTRACTION_OPTIONS
    )
    st.session_state["creator_felling_machine"] = felling_machine
    st.session_state["creator_felling_variant"] = felling_variant
    st.session_state["creator_extraction_machine"] = extraction_machine
    st.session_state["creator_extraction_variant"] = extraction_variant
    segments = []
    while index < len(machine_ids):
        transport_machine, transport_variant, next_index = match_option(
            machine_ids, index, TRANSPORT_OPTIONS
        )
        if next_index == index:
            break
        segments.append((transport_machine, transport_variant))
        index = next_index
    st.session_state["creator_segment_count"] = max(1, len(segments))
    for segment_index, (transport_machine, transport_variant) in enumerate(segments):
        st.session_state[f"creator_transport_machine_{segment_index}"] = (
            transport_machine
        )
        st.session_state[f"creator_transport_variant_{segment_index}"] = (
            transport_variant
        )


def custom_values_from_row(row: pd.Series) -> dict:
    values = {}
    for field in CUSTOM_FIELDS:
        value = row.get(field, "")
        values[field] = "" if pd.isna(value) else value
    return values


def custom_values_from_use_cases(pathway_id: str) -> dict:
    data = read_csv("csv_use_cases.csv")
    rows = data[data["pathway_id"] == pathway_id]
    if rows.empty:
        return {}
    return custom_values_from_row(rows.iloc[0])


def saved_creator_options() -> dict:
    options = {}
    for pathway_id, config in custom_pathways().items():
        options[config.get("label", pathway_id)] = (
            pathway_id,
            list(config["machines"]),
            dict(config.get("values") or custom_values_from_use_cases(pathway_id)),
        )
    data = read_csv("csv_use_cases.csv")
    custom_rows = data[data["pathway_id"].astype(str).str.startswith("CUSTOM_")]
    for _, row in custom_rows.iterrows():
        pathway_id = str(row["pathway_id"])
        if pathway_id in helper_functions.PATHWAY_STEPS:
            label = str(row.get("group") or row.get("variant") or pathway_id)
            options[label] = (
                pathway_id,
                list(helper_functions.PATHWAY_STEPS[pathway_id]),
                custom_values_from_row(row),
            )
    for pathway_id, machine_ids in pathways.PATHWAY_STEPS.items():
        if pathway_id.startswith("CUSTOM_"):
            options[custom_group_name(pathway_id)] = (
                pathway_id,
                list(machine_ids),
                custom_values_from_use_cases(pathway_id),
            )
    return options


def render_creator_preview(display_steps: list[dict]):
    labels = ["Bestand"] + [step["label"] for step in display_steps] + ["Werk"]
    parts = []
    for index, label in enumerate(labels):
        node_class = (
            "creator-node start"
            if index == 0
            else "creator-node end" if index == len(labels) - 1 else "creator-node"
        )
        parts.append(f'<div class="{node_class}">{html.escape(label)}</div>')
        if index < len(labels) - 1:
            parts.append('<div class="creator-arrow">&rarr;</div>')
    st.markdown(
        f'<div class="creator-preview">{"".join(parts)}</div>', unsafe_allow_html=True
    )


def creator_image_column(column, image_key: str):
    image_path = CREATOR_IMAGES[image_key]
    if image_path.exists():
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        column.markdown(
            f'<div class="creator-image"><img src="data:image/png;base64,{encoded}" alt=""></div>',
            unsafe_allow_html=True,
        )


def parse_creator_values() -> tuple[dict, list[str]]:
    values = {}
    errors = []
    inputs = st.columns(4)
    for index, field in enumerate(CUSTOM_FIELDS):
        raw = inputs[index % 4].text_input(
            FIELD_LABELS.get(field, field),
            value=st.session_state.get(f"creator_{field}", "0"),
            key=f"creator_{field}",
        )
        try:
            values[field] = float(str(raw).replace(",", "."))
        except ValueError:
            errors.append(FIELD_LABELS.get(field, field))
            values[field] = raw
    return values, errors


def select_variant(prefix: str, options: dict):
    machines = list(options)
    machine = st.selectbox("Maschine", machines, key=f"{prefix}_machine")
    variants = list(options[machine])
    if st.session_state.get(f"{prefix}_variant") not in variants:
        st.session_state[f"{prefix}_variant"] = variants[0]
    variant = st.selectbox("Variante", variants, key=f"{prefix}_variant")
    return machine, variant, options[machine][variant]


def pathway_creator():
    st.title("Pathway Creator")
    st.caption(
        "Maschinen auswählen, Transportsegmente kombinieren und als temporären oder festen Pfad übernehmen."
    )

    saved_options = saved_creator_options()
    load_choices = ["Neuer Pfad"] + list(saved_options)
    load_label = st.selectbox(
        "Bestehenden Custom-Pfad laden", load_choices, key="creator_load_pathway"
    )
    if load_label != "Neuer Pfad" and st.button("Auswahl laden"):
        _pathway_id, machine_ids, values = saved_options[load_label]
        load_creator_from_sequence(load_label, machine_ids, values)
        st.rerun()

    name = st.text_input(
        "Pfadname",
        value=st.session_state.get("custom_pathway_name", "Custom pathway"),
        key="custom_pathway_name",
    )
    pathway_id = slugify_pathway_id(name)

    st.markdown("### Pfad zusammenstellen")
    with st.container(border=True):
        img_col, input_col = st.columns([0.18, 0.82], gap="large")
        creator_image_column(img_col, "felling")
        with input_col:
            st.markdown(
                '<div class="creator-kicker">1 Fällen</div>', unsafe_allow_html=True
            )
            felling_machine, felling_variant, felling_sequence = select_variant(
                "creator_felling", FELLING_OPTIONS
            )

    with st.container(border=True):
        img_col, input_col = st.columns([0.18, 0.82], gap="large")
        creator_image_column(img_col, "extraction")
        with input_col:
            st.markdown(
                '<div class="creator-kicker">2 Rücken</div>', unsafe_allow_html=True
            )
            extraction_machine, extraction_variant, extraction_sequence = (
                select_variant("creator_extraction", EXTRACTION_OPTIONS)
            )

    transport_segments = []
    with st.container(border=True):
        img_col, input_col = st.columns([0.18, 0.82], gap="large")
        creator_image_column(img_col, "transport")
        with input_col:
            st.markdown(
                '<div class="creator-kicker">3 Transportkette</div>',
                unsafe_allow_html=True,
            )
            segment_count = st.number_input(
                "Anzahl Transportsegmente",
                min_value=1,
                max_value=4,
                value=st.session_state.get("creator_segment_count", 1),
                step=1,
                key="creator_segment_count",
            )
            for index in range(int(segment_count)):
                cols = st.columns(2, gap="small")
                with cols[0]:
                    transport_machine = st.selectbox(
                        f"Segment {index + 1}",
                        list(TRANSPORT_OPTIONS),
                        key=f"creator_transport_machine_{index}",
                    )
                with cols[1]:
                    variants = list(TRANSPORT_OPTIONS[transport_machine])
                    if (
                        st.session_state.get(f"creator_transport_variant_{index}")
                        not in variants
                    ):
                        st.session_state[f"creator_transport_variant_{index}"] = (
                            variants[0]
                        )
                    transport_variant = st.selectbox(
                        "Variante", variants, key=f"creator_transport_variant_{index}"
                    )
                transport_segments.append(
                    (
                        transport_machine,
                        transport_variant,
                        TRANSPORT_OPTIONS[transport_machine][transport_variant],
                    )
                )

    machine_ids = []
    display_steps = []
    for label, sequence in [
        (option_label(felling_machine, felling_variant), felling_sequence),
        (option_label(extraction_machine, extraction_variant), extraction_sequence),
    ]:
        start_index = len(machine_ids)
        machine_ids.extend(sequence)
        display_steps.append(
            {"label": label, "indices": list(range(start_index, len(machine_ids)))}
        )
    for transport_machine, transport_variant, sequence in transport_segments:
        start_index = len(machine_ids)
        machine_ids.extend(sequence)
        display_steps.append(
            {
                "label": option_label(transport_machine, transport_variant),
                "indices": list(range(start_index, len(machine_ids))),
            }
        )

    st.markdown("### Live-Vorschau")
    render_creator_preview(display_steps)

    st.markdown("### Szenariowerte")
    values, value_errors = parse_creator_values()
    if value_errors:
        st.warning("Bitte numerische Werte prüfen: " + ", ".join(value_errors))

    action_cols = st.columns([0.25, 0.25, 0.25, 0.25], gap="small")
    can_submit = not value_errors
    if action_cols[0].button(
        "Temporären Pfad erstellen", type="primary", disabled=not can_submit
    ):
        custom_pathways()[pathway_id] = {
            "label": name,
            "machines": machine_ids,
            "display_steps": display_steps,
            "values": values,
        }
        apply_custom_pathways()
        add_custom_use_case_row(pathway_id, name, values)
        st.session_state["standard_group"] = name
        st.session_state["_standard_group"] = name
        st.session_state["standard_use_case"] = CUSTOM_USE_CASE
        st.session_state["_standard_use_case"] = CUSTOM_USE_CASE
        st.success(
            "Pfad wurde temporär hinzugefügt und ist jetzt in Standard-Szenarien sowie Anpassung Use Cases verfügbar."
        )
    if action_cols[1].button("Ins Original übernehmen", disabled=not can_submit):
        custom_pathways()[pathway_id] = {
            "label": name,
            "machines": machine_ids,
            "display_steps": display_steps,
            "values": values,
        }
        apply_custom_pathways()
        add_custom_use_case_row(pathway_id, name, values)
        save_custom_pathway_to_original(pathway_id)
        st.success(
            "Pfad wurde dauerhaft in pathways.py und csv_use_cases.csv übernommen."
        )
    if action_cols[2].button("Temporären Pfad löschen"):
        remove_custom_pathway(pathway_id)
        st.success("Temporärer Pfad wurde entfernt.")


def main():
    add_styles()
    session_dir()
    with st.sidebar:
        st.title("🌲 Forestry LCA")
        st.caption("Life Cycle Assessment")
        st.markdown(
            '<div class="creator-credit">© 2026 Designed &amp; developed by Alexander Krenbucher</div>',
            unsafe_allow_html=True,
        )
        page = st.radio(
            "Navigation",
            [
                "Pathway Creator",
                "Standard-Szenarien",
                "Anpassung Use Cases",
                "Anpassung Machines",
                "Anpassung Emissionsfaktoren",
            ],
            index=1,
            key="main_page",
            label_visibility="collapsed",
        )
        st.divider()
        if st.button("Standardwerte wiederherstellen", width="stretch"):
            reset_session_files()
            st.rerun()
        st.caption("      Original csv Dateien laden")

    pages = {
        "Standard-Szenarien": standard_scenario,
        "Pathway Creator": pathway_creator,
        "Anpassung Use Cases": use_cases_editor,
        "Anpassung Machines": machines_editor,
        "Anpassung Emissionsfaktoren": emission_factors_editor,
    }
    pages[page]()


if __name__ == "__main__":
    main()
