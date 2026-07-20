PATHWAY_STEPS = {
    # motor manual harvesting
    "MMH-E": [
        "chainsaw_electric",
        "tractor_electric_winch",
        "forest_winch",
        "tractor_electric_trailer",
        "forest_trailer",
    ],
    "MMH-MC": [
        "chainsaw_petrol",
        "tractor_diesel_winch",
        "forest_winch",
        "tractor_diesel_trailer",
        "forest_trailer",
    ],
    # partially automated harvesting
    "PAH-E": [
        "harvester_electric",
        "forwarder_electric",
        "truck_bev",
        "truck_trailer",
    ],
    "PAH-C": [
        "harvester_diesel",
        "forwarder_diesel",
        "truck_diesel",
        "truck_trailer",
    ],
    "PAH-I": [
        "harvester_diesel",
        "forwarder_pully",
        "truck_efuel",
        "truck_trailer",
    ],
    # harvesting in steep terrain
    "HST-E": [
        "chainsaw_electric",
        "cable_yarder_electric",
        "truck_bev",
        "truck_trailer",
        "rail",
        "terminal_handling_logs",
    ],
    "HST-C": [
        "chainsaw_petrol",
        "cable_yarder_diesel",
        "truck_diesel",
        "truck_trailer",
        "rail",
        "terminal_handling_logs",
    ],
    "HST-I": [
        "chainsaw_electric",
        "cable_yarder_recuperating",
        "truck_diesel_intermodal_container",
        "truck_trailer",
        "rail_intermodal_container",
        "terminal_handling_intermodal_container",
        "intermodal_container",
    ],
    # autonomous pathway
    "AP-L": [
        "harvester_autonomous_low_diesel",
        "forwarder_autonomous_low_diesel",
        "truck_autonomous_low_diesel",
        "truck_trailer",
    ],
    "AP-P": [
        "harvester_autonomous_partly_diesel",
        "forwarder_autonomous_partly_diesel",
        "truck_autonomous_partly_diesel",
        "truck_trailer",
    ],
    "AP-H": [
        "harvester_autonomous_high_diesel",
        "forwarder_autonomous_high_diesel",
        "truck_autonomous_high_diesel",
        "truck_trailer",
    ],
}


TRANSPORT_PATHWAY_GROUPS = {
    "Motor-manual harvesting": {
        "directory": "motor_manual_harvesting",
        "pathways": ["MMH-E", "MMH-MC"],
        "machine_roles": {
            0: "Chainsaw",
            1: "Tractor with winch",
            2: "Forest winch",
            3: "Tractor with trailer",
            4: "Forest trailer",
        },
    },
    "Partially automated harvesting": {
        "directory": "partially_automated_harvesting",
        "pathways": ["PAH-E", "PAH-C", "PAH-I"],
        "machine_roles": {
            0: "Harvester",
            1: "Forwarder",
            2: "Truck",
            3: "Truck trailer",
        },
    },
    "Harvesting in steep terrain": {
        "directory": "harvesting_in_steep_terrain",
        "pathways": ["HST-E", "HST-C", "HST-I"],
        "machine_roles": {
            0: "Chainsaw",
            1: "Cable yarder",
            2: "Truck",
            3: "Truck trailer",
            4: "Rail transport",
            5: "Rail unloading / terminal handling",
            6: "Intermodal container",
        },
    },
    "Autonomous pathway": {
        "directory": "autonomous_pathway",
        "pathways": ["AP-L", "AP-P", "AP-H"],
        "machine_roles": {
            0: "Harvester",
            1: "Forwarder",
            2: "Truck",
            3: "Truck trailer",
        },
    },
}

