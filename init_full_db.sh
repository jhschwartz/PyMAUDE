#!/bin/bash
#
# MAUDE Database Initialization Script
#
# This script sets up the Python environment and runs the database initializer.
# It can be used by researchers to download MAUDE data and create a SQLite database
# for use in external SQLite tools.
#
# Usage:
#   ./init_full_db.sh                    # Interactive mode
#   ./init_full_db.sh --years 2015-2024 --tables device,text --output maude.db
#
# Copyright (C) 2024 Jacob Schwartz, University of Michigan Medical School
# Licensed under GPL v3

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "============================================================"
echo "          MAUDE Database Initialization Script"
echo "============================================================"
echo ""

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is not installed.${NC}"
    echo "Please install Python 3.7 or later and try again."
    echo "Visit: https://www.python.org/downloads/"
    exit 1
fi

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 7 ]); then
    echo -e "${RED}Error: Python 3.7 or later is required.${NC}"
    echo "You have Python $PYTHON_VERSION"
    echo "Please upgrade Python and try again."
    exit 1
fi

echo -e "${GREEN}✓${NC} Python $PYTHON_VERSION found"

# Check if we're in a virtual environment
if [ -z "$VIRTUAL_ENV" ]; then
    # Not in a venv, check if one exists
    if [ ! -d "venv" ]; then
        echo ""
        echo "Creating virtual environment..."
        python3 -m venv venv
        echo -e "${GREEN}✓${NC} Virtual environment created"
    fi

    # Activate the virtual environment
    echo "Activating virtual environment..."
    source venv/bin/activate
    echo -e "${GREEN}✓${NC} Virtual environment activated"
else
    echo -e "${GREEN}✓${NC} Already in virtual environment"
fi

# Check if dependencies are installed
echo ""
echo "Checking dependencies..."

if ! python3 -c "import pandas" 2>/dev/null; then
    echo "Installing dependencies..."
    pip install -q -e .
    echo -e "${GREEN}✓${NC} Dependencies installed"
else
    echo -e "${GREEN}✓${NC} Dependencies already installed"
fi

# Check for internet connection
echo ""
echo "Checking internet connection..."
if ping -c 1 -W 2 www.google.com &> /dev/null || ping -c 1 -W 2 8.8.8.8 &> /dev/null; then
    echo -e "${GREEN}✓${NC} Internet connection available"
else
    echo -e "${YELLOW}Warning: Could not verify internet connection.${NC}"
    echo "You'll need internet access to download MAUDE data from FDA servers."
    echo ""
    read -p "Continue anyway? [y/N]: " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Cancelled."
        exit 1
    fi
fi

# Run the Python initialization script
echo ""
echo "============================================================"
echo ""

# Pass all command-line arguments to the Python script
python3 init_database.py "$@"

EXIT_CODE=$?

# Deactivate virtual environment if we activated it
if [ -n "$VIRTUAL_ENV" ]; then
    deactivate 2>/dev/null || true
fi

exit $EXIT_CODE
