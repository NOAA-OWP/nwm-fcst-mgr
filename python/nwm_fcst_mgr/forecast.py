import glob
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
import geopandas as gpd
import pandas as pd
import netCDF4

import matplotlib.pyplot as plt
import yaml
import argparse

from nwm_fcst_mgr.log_level import log_level_set
from nwm_fcst_mgr.git_util import print_git_info_all
from mswm.manager import build_fcst

# setup the logger
logger = logging.getLogger(__name__)


def run_fcst(valid_yaml: str, real_path: str):
    """
    Execute ngen run for forecast period and cold start period (if provided)
    valid_yaml: path to validation yaml file from past calibration run
    real_path: path to realization file for a cold start or forecast period
    """

    # Read validation yaml file
    valid_config = load_yaml(valid_yaml)

    # Retrieve output_dir
    real_file = Path(real_path)
    out_dir = real_file.parent

    # Retrieve hydrofabric gpkg
    gpkg_cats = valid_config['model']['catchments']
    gpkg_nexus = valid_config['model']['nexus']

    # Retrieve ngen executable
    ngen_exe = valid_config['model']['binary']

    # get gage ID and make sure it is not empty
    try:
        gage0 = valid_config['model']['eval_params']['basinID']
    except ValueError as e:
        logger.critical(f'Key model/eval_params/basinID not found in {valid_yaml}\n{e}')
        raise
    if gage0 == "":
        try:
            raise ValueError(f'basinID in {valid_yaml} cannot be empty')
        except ValueError as e:
            logger.critical(e)
            raise

    # Execute ngen run for either cold-start or forecast period
    cmd = f'{ngen_exe} {gpkg_cats} "all" {gpkg_nexus} "all" {real_path}'

    logger.info(f'Initializing NGEN run from:  {real_path}')

    # kick off ngen run and save stdout & stderr to ngen_stdout_stderr.log
    log_file = out_dir / "ngen_stdout_stderr.log"
    try:
        with open(log_file, 'a+') as log:
            subprocess.check_call(cmd, stdout=log, stderr=log, shell=True, cwd=str(out_dir))
    except subprocess.CalledProcessError as e:
        logger.critical(f'Ngen run failed with return code {e.returncode}. Command: {e.cmd}')
        raise
    except Exception as e:
        logger.critical(f'Ngen run failed while running command: {e}')
        raise

    logger.info('NGEN run completed successfully')

    # move output files to output directory
    run_output_dir = out_dir / "output/"
    run_output_dir.mkdir(parents=True, exist_ok=True)
    for pat1 in ['cat*.csv', 'nex*.csv', 'troute*.nc']:
        for f1 in glob.glob(f'{out_dir}/{pat1}'):
            shutil.move(f1, Path(run_output_dir, os.path.basename(f1)))

    logger.info(f'NGEN outputs moved to: {run_output_dir}')

    # read troute output file
    outfile = glob.glob(f'{run_output_dir}/troute*.nc')[0]
    output = read_troute_output(gage0, valid_config['model']['crosswalk'], gpkg_cats, outfile)

    logger.info(f'Reading T-route output file: {outfile}')

    # plot the hydrograph
    plot_path = Path(run_output_dir, gage0 + '_hydrograph.png')
    output.plot(y='sim_flow', kind='line')
    plt.xlabel('Time')
    plt.ylabel('Streamflow (m^3/s)')
    plt.savefig(plot_path, bbox_inches="tight")

    logger.info(f'Hydrograph plot saved to: {plot_path}')

    # save streamflow simulation to csv
    output.to_csv(Path(run_output_dir, gage0 + '_output.csv'))

    logger.info(f'Fcst-mgr NGEN run outputs saved at: {run_output_dir}')


def load_yaml(file_path: str) -> dict:
    """
    Read yaml-based configuration file from previous ngen calibration run
    """
    # Confirm input file exists
    file_path = Path(file_path).absolute()
    if not file_path.exists():
        try:
            raise FileNotFoundError(f'Input file not found: {file_path}')
        except FileNotFoundError as e:
            logger.critical(e)
            raise

    # Read the yaml-based configuration file
    try:
        with open(file_path) as file:
            yaml_dict = yaml.safe_load(file)
    except FileNotFoundError as e:
        logger.critical(f'Config valid yaml file does not exist: {file_path}\n{e}')
        raise
    except yaml.YAMLError as e:
        logger.critical(f"YAML parsing error in valid config yaml file: {file_path}\n{e}")
        raise
    except Exception as e:
        logger.critical(f"Unexpected error loading valid config yaml file at: {file_path}\n{e}")
        raise

    return yaml_dict


def read_troute_output(
        gage0: str,
        cwt_file: Path,
        gpkg_file: Path,
        out_file: Path,
) -> pd.DataFrame:

    """
    Arguments:
    ---------
    gage0: gage ID to retrieve streamflow simulations
    cwt_file: path to crosswalk file mapping gage to catchments
    gpkg_file: path to geopackage file
    out_file: path to t-route output file (in NetCDF format)

    Returns:
    ---------
    dataframe containing time and streamflow simulations

    """
    # Handle crosswalk file (in order to get the correct feature_id when reading t-route data)
    x_walk = pd.Series(dtype=object)
    try:
        with open(cwt_file) as fp:
            data = json.load(fp)
            for id, values in data.items():
                gage = values.get('Gage_no')
                if gage:
                    if not isinstance(gage, str):
                        gage = gage[0]
                    if gage == gage0:
                        x_walk[id] = gage
                        break
    except FileNotFoundError as e:
        logger.critical(f'Crosswalk file not found: {cwt_file}\n{e}')
        raise
    except json.JSONDecodeError as e:
        logger.critical(f'Failed to parse JSON from crosswalk file: {cwt_file}\n{e}')
        raise

    if x_walk.empty:
        try:
            raise Exception(f'{gage0} is not found in crosswalk file {cwt_file}')
        except Exception as e:
            logger.critical(e)
            raise

    # get catchment at basin outlet for reading from t-route output
    catchment_hydro_fabric = gpd.read_file(gpkg_file, layer='divides')
    catchment_hydro_fabric.set_index('id', inplace=True)
    nexus_id = catchment_hydro_fabric.loc[x_walk.index[0].replace('cat', 'wb')]['toid']
    wb_lst = [x.split('-')[1] for x in catchment_hydro_fabric.index[catchment_hydro_fabric['toid'] == nexus_id]]

    # read troute output
    ncvar = netCDF4.Dataset(out_file, "r")
    fid_index = [list(ncvar['feature_id'][0:]).index(int(fid)) for fid in wb_lst]
    output = pd.DataFrame(data={'sim_flow': pd.DataFrame(ncvar['flow'][fid_index], index=fid_index).T.sum(axis=1)})
    t0 = pd.to_datetime(ncvar.file_reference_time, format="%Y-%m-%d_%H:%M:%S")
    output.index = [t0 + pd.Timedelta(seconds=int(t1)) for t1 in ncvar['time']]
    output.index.name = 'Time'

    return output

def fcst_workflow(input_path, valid_yaml, fcst_run_name, use_cold_start=False):
    """
    Run forecast workflow with optional cold start run
    """
    logger.info(f'Initializing forecast run from: {valid_yaml}')

    # Generate msw-mgr inputs for cold start run
    if use_cold_start:
        cold_start_real_path  = build_fcst(input_path=input_path, valid_yaml=valid_yaml,
                                           fcst_run_name=fcst_run_name, use_cold_start=True)
        logger.info(f"Cold start realization file written to: {cold_start_real_path}")

        # Run cold start
        run_fcst(valid_yaml, cold_start_real_path)
        logger.info("Cold start ngen run completed")

    # Generate msw-mgr inputs for forecast run
    fcst_real_path = build_fcst(input_path=input_path, valid_yaml=valid_yaml,
                                fcst_run_name=fcst_run_name)
    logger.info(f"Forecast realization file written to: {fcst_real_path}")

    # Run forecast
    run_fcst(valid_yaml, fcst_real_path)
    logger.info("Forecast ngen run completed")

def hindcast_workflow(input_path, valid_yaml, fcst_run_name, cycle_interval, num_intervals, use_cold_start=False):
    """
    Run hindcast workflow with optional cold start and intermediate ana runs
    Accepts cycle interval and number of intervals for repeated hindcasts
    """
    logger.info(f'Initializing hindcast runs from: {valid_yaml}')

    # Generate msw-mgr inputs for cold start run
    if use_cold_start:

        # Create cold start input files
        cold_start_real_path = build_fcst(input_path=input_path, valid_yaml=valid_yaml,
                                          fcst_run_name=fcst_run_name, use_cold_start=True)
        logger.info(f"Cold start realization file written to: {cold_start_real_path}")
        
        # Run cold start
        run_fcst(valid_yaml, cold_start_real_path)
        logger.info("Cold start ngen run completed")

    # Generate hindcast interval times in hours
    hind_interval = list(range(0, num_intervals, cycle_interval))

    # Loop through hindcast intervals
    for hind_cycle in hind_interval:

        # Format run name for hindcast cycle
        hind_run_name = fcst_run_name + '_' + str(hind_cycle)

        # Create intermediate ana input files
        int_ana_real_path = build_fcst(input_path=input_path, valid_yaml=valid_yaml,
                                       fcst_run_name=hind_run_name, use_int_ana=True, hind_cycle=hind_cycle)
        logger.info(f"Intermediate AnA run {hind_cycle} realization file written to: {int_ana_real_path}")
        
        # Run intermediate ana to generate hindcasting model states
        run_fcst(valid_yaml, int_ana_real_path)
        logger.info(f"Intermediate AnA run {hind_cycle} ngen run completed")

        # Create hindcast input files
        hind_real_path = build_fcst(input_path=input_path, valid_yaml=valid_yaml,
                                    fcst_run_name=hind_run_name, use_hindcast=True, hind_cycle=hind_cycle)
        logger.info(f"Hindcast run {hind_cycle} realization file written to: {hind_real_path}")
        
        # Run hindcasting period
        run_fcst(valid_yaml, hind_real_path)
        logger.info(f"Hindcast run {hind_cycle} ngen run completed")


def parse_args():
    # Create command line parser
    parser = argparse.ArgumentParser(prog="nwm-fcst-mgr",
                                     description="Forecast Manager command-line")
    subparser = parser.add_subparsers(dest="command", required=True, help="Available commands")

    # Define parent parser for shared arguments
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument('input_path', type=str, help='Path to input.config file for forecast')
    parent_parser.add_argument('valid_yaml', type=str, help='Path to validation yaml file from previous run of nwm-cal-mgr')
    parent_parser.add_argument("fcst_run_name", help="Name of the folder to be created for storing inputs/outputs from running ngen")
    parent_parser.add_argument("--use_cold_start", action="store_true", help="Enable cold start flag when passed")

    # subcommand: fcst_workflow
    fcst_workflow_sub = subparser.add_parser("fcst_workflow", parents=[parent_parser], help="Run forecast workflow")

    # Subcommand: hindcast_workflow
    hindcast_workflow_sub = subparser.add_parser("hindcast_workflow", parents=[parent_parser], help="Run forecast workflow")
    hindcast_workflow_sub.add_argument("cycle_interval", type=int, help="Cycle interval (in hours) between hindcast runs")
    hindcast_workflow_sub.add_argument("num_intervals", type=int, help="Number of hindcast cycles to perform")

    return parser.parse_args()


def main():

    # Initialize logging explicitly for CLI entrypoint
    log_level_set()

    # Retrieve CLI args
    args = parse_args()

    # Run fcst/hindcast workflows
    if args.command == "fcst_workflow":
        fcst_workflow(input_path=args.input_path, valid_yaml=args.valid_yaml,
                    fcst_run_name=args.fcst_run_name, use_cold_start=args.use_cold_start)
    if args.command == "hindcast_workflow":
        hindcast_workflow(input_path=args.input_path, valid_yaml=args.valid_yaml,
                          fcst_run_name=args.fcst_run_name, use_cold_start=args.use_cold_start,
                          cycle_interval=args.cycle_interval, num_intervals=args.num_intervals)
    else:
        raise ValueError(f"Unexpected command: {args.command}. Use either 'fcst_workflow' or 'hindcast_workflow'.")


if __name__ == "__main__":
    print_git_info_all()
    main()
