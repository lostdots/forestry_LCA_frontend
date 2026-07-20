from helper_functions import (
    DataStream,
    run_pathway,
    plot_use_case_diagrams,
)

import pandas as pd


def main():
    stream = DataStream(
        use_cases_path="csv_use_cases.csv",
        machines_path="csv_machines.csv",
        materials_path="csv_materials.csv",
        emission_repository_path="csv_emission_repository.csv",
    )
    materials = stream.get_all_materials()
    emission_factors = stream.get_all_emission_factors()
    results = []
    machine_results = []

    for use_case_row in stream.get_all_use_cases():
        result = run_pathway(
            use_case_row,
            stream,
            materials,
            emission_factors,
            machine_results=machine_results,
        )
        results.append(result)

    results_df = pd.DataFrame(results)
    machine_results_df = pd.DataFrame(machine_results)
    print(results_df)

    results_df.to_csv("results_pathways.csv", sep=";", decimal=",", index=False)
    plot_use_case_diagrams(
        results_df,
        machine_results_df,
        output_dir="use_cases_results",
    )


if __name__ == "__main__":
    main()
