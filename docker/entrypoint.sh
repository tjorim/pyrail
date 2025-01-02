#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Ensure the fixed virtual environment is activated
if [ ! -d "/venv" ]; then
  echo "Virtual environment not found. Installing dependencies..."
  poetry install --with dev
fi

exec "$@"
