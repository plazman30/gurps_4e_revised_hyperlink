#!/bin/bash
# Double-click setup for the GURPS PDF Hyperlinker (macOS).
#
# Installs Homebrew if needed, installs Python via Homebrew if needed,
# then installs the one required Python package. Safe to run more than
# once -- each step just says "already installed" and moves on.

set -e

# Always work relative to wherever this script actually lives, no matter
# where it was double-clicked from.
cd "$(dirname "$0")"

echo "=================================================="
echo " GURPS PDF Hyperlinker - Setup"
echo "=================================================="
echo

if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew not found. Installing it now..."
    echo "(This may ask for your Mac password, and print a lot of text -- that's normal.)"
    echo
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

    # Make brew available in this session (Apple Silicon vs Intel paths differ).
    if [ -x /opt/homebrew/bin/brew ]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [ -x /usr/local/bin/brew ]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
else
    echo "Homebrew already installed."
fi
echo

echo "Installing Python (skips automatically if already installed)..."
brew install python3
echo

echo "Installing the required Python package (PyMuPDF)..."
python3 -m pip install -r requirements.txt --break-system-packages
echo

echo "=================================================="
echo " Setup complete!"
echo
echo " Example of running the tool on a book:"
echo "   python3 hyperlink_pdf.py YourBook.pdf YourBook_linked.pdf"
echo "=================================================="
echo
read -p "Press Enter to close this window..."
