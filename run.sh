#!/bin/bash

# Set title/banner colors
echo -e "\033[0;34m===================================================\033[0m"
echo -e "\033[0;34m              down2listen Startup\033[0m"
echo -e "\033[0;34m===================================================\033[0m"
echo

# Check if Python is installed
if ! command -v python3 &> /dev/null
then
    echo -e "\033[0;31mERROR: Python 3 is not installed or not in your PATH.\033[0m"
    echo "Please install Python 3 and try again."
    exit 1
fi

# Setup virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    if [ $? -ne 0 ]; then
        echo -e "\033[0;31mERROR: Failed to create virtual environment.\033[0m"
        exit 1
    fi
fi

# Activate virtual environment
echo "Activating virtual environment..."
source .venv/bin/activate
if [ $? -ne 0 ]; then
    echo -e "\033[0;31mERROR: Failed to activate virtual environment.\033[0m"
    exit 1
fi

# Install requirements
echo "Installing dependencies (this may take a moment)..."
python3 -m pip install --upgrade pip
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo -e "\033[0;31mERROR: Failed to install dependencies.\033[0m"
    exit 1
fi

# Start the application and open the browser
echo "Starting server..."
echo
echo "Opening browser at http://127.0.0.1:5000 ..."

# Open browser based on OS/environment
if command -v xdg-open &> /dev/null; then
    xdg-open "http://127.0.0.1:5000"
elif command -v open &> /dev/null; then
    open "http://127.0.0.1:5000"
else
    echo "Please open http://127.0.0.1:5000 in your browser."
fi

echo
echo "Press Ctrl+C in this window to stop the server."
echo -e "\033[0;34m===================================================\033[0m"
python app.py
