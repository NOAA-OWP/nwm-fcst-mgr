#!/bin/bash

# This shell script lives in the ngen-cal.  It is used by CerfServer when calling ngen-cal

# It is used by CerfServer directly when running in LOCAL mode.
# It is used by the ngen-cal docker container when the server is running in DOCKER or PARALLEL_WORKS mode.

REQUIRED_ARGS=3
SCRIPT_PATH=/ngen-app/ngen-fcst/python/run_ngen_fcst.py

# Set the umask so files and directories are created with 777 permissions
echo Setting umask
umask 000
umask -S

# Function to display help message
show_help() {
  echo "Usage: $(basename "$0") \<forcing_file\> \<config_file\> \<job_name\>"
  echo ""
  echo "forcing_file: Path to the NetCDF forcing file."
  echo "config_file: Path to the config yaml file for a validation run (from ngen-cal)."
  echo "job_name: Path to the folder to be created for storing inputs/outputs from running ngen."
  echo ""
  echo "Example:"
  echo "  $(basename "$0") test_data/forcing.nc test_data/valid_config.yaml fcst_run1"
  echo ""
  exit 1
}

# Show help if the user requests it with --help or -h
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
  show_help
fi

# Check if the correct number of arguments are provided for the selected command
if [ $# -lt $REQUIRED_ARGS ]; then
  echo "Error: Insufficient arguments. Script requires $REQUIRED_ARGS arguments."
  show_help
fi

# Check if the selected script exists
if [ ! -f "$SCRIPT_PATH" ]; then
  echo "Error: Script not found at $SCRIPT_PATH"
  exit 1
fi

FORCING_FILE=$1
CONFIG_FILE=$2
JOB_NAME=$3

echo "DEBUG: FORCING_FILE: ${FORCING_FILE}"
echo "DEBUG: CONFIG_FILE: ${CONFIG_FILE}"
echo "DEBUG: JOB_NAME: ${JOB_NAME}"

# Check if the forcing data exists
if [ ! -f "${FORCING_FILE}" ]; then
  echo "WARN: Forcing data not found at ${FORCING_FILE}"
fi

# Check if the configuration file exists
if [ ! -f "${CONFIG_FILE}" ]; then
  echo "WARN: Configuration file not found at ${CONFIG_FILE}"
fi

# if [ $# -ge 1 ]; then
#   PYTHON_OUTPUT_FILE=$1
#   echo "       Output file: $PYTHON_OUTPUT_FILE"

#   # Create output directory if it doesn't exist
#   OUTPUT_DIR=$(dirname "$PYTHON_OUTPUT_FILE")
#   if [ ! -d "$OUTPUT_DIR" ]; then
#     mkdir -p "$OUTPUT_DIR"
#   fi

#   shift 1
# fi

# if [ $# -ge 1 ]; then
#   VENV_PATH=$1
#   echo "Virtual environment: $VENV_PATH"
#   shift 1
# fi

# Activate the virtual environment if provided
# if [ -n "$VENV_PATH" ]; then
#   if [ -d "$VENV_PATH/bin" ]; then
#     source "$VENV_PATH/bin/activate"
#   else
#     echo "Error: Virtual environment path '$VENV_PATH' is invalid."
#     exit 1
#   fi
# else
#   echo "No virtual environment provided, running with default Python environment."
# fi

# Run the Python script, redirecting its output if an output file is provided
echo "   Running $(basename "$SCRIPT_PATH") with input file: $CONFIG_FILE"
python "${SCRIPT_PATH}" "${FORCING_FILE}" "${CONFIG_FILE}" "${JOB_NAME}"

python_exit_code=$?
if [ $python_exit_code -ne 0 ]; then
  echo "$(basename "$SCRIPT_PATH") exited with code $python_exit_code"
fi

# Display output if redirected to a file
# if [ -n "$PYTHON_OUTPUT_FILE" ]; then
#   echo "Output from running $(basename "$SCRIPT_PATH")"
#   echo "-------------- start of $PYTHON_OUTPUT_FILE -----------------------------"
#   cat "$PYTHON_OUTPUT_FILE"
#   echo "---------------- end of $PYTHON_OUTPUT_FILE -----------------------------"
# fi

echo "Done running $(basename "$SCRIPT_PATH")"

exit $python_exit_code
