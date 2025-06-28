#!/bin/bash

# Define the source directories relative to this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PROJECT_ROOT=$(dirname "$SCRIPT_DIR")
WEECHAT_SOURCE_DIR="$PROJECT_ROOT/weechat"

# Determine WeeChat's Python script directory (adjust if yours is different)
WEECHAT_PYTHON_DIR="$HOME/.local/share/weechat/python"
if [ ! -d "$WEECHAT_PYTHON_DIR" ]; then
    WEECHAT_PYTHON_DIR="$HOME/.weechat/python" # Fallback
fi

if [ ! -d "$WEECHAT_PYTHON_DIR" ]; then
    echo "Error: WeeChat Python script directory not found at $WEECHAT_PYTHON_DIR."
    echo "Please ensure WeeChat is installed and you've run a Python script at least once."
    exit 1
fi

echo "Deploying AutoXDCC modular WeeChat scripts to: $WEECHAT_PYTHON_DIR"

# Remove existing deployments to prevent conflicts
echo "Cleaning up old symlinks/files..."
rm -f "$WEECHAT_PYTHON_DIR/autoxdcc.py"          # Remove previous autoxdcc.py symlink
rm -rf "$WEECHAT_PYTHON_DIR/libautoxdcc"         # Remove previous libautoxdcc symlink/directory

# Create new symlinks for the modular structure
echo "Creating symlink for autoxdcc.py (main entry point)..."
ln -s "$WEECHAT_SOURCE_DIR/autoxdcc.py" "$WEECHAT_PYTHON_DIR/autoxdcc.py"

echo "Creating symlink for libautoxdcc/ (library package)..."
ln -s "$WEECHAT_SOURCE_DIR/libautoxdcc" "$WEECHAT_PYTHON_DIR/libautoxdcc"

echo "Deployment complete."
echo "------------------------------------------------------------------"
echo "NEXT STEPS:"
echo "1. Go to your WeeChat instance."
echo "2. Run: /python reload autoxdcc"
echo "   (Note: The script name is now 'autoxdcc', not 'autoxdcc_modular')."
echo "3. You should see '[autoxdcc] AutoXDCC WeeChat backend (v0.4.0) loaded and ready.'"
echo "------------------------------------------------------------------"
