#!/usr/bin/env bash

# Script to switch between Python extractor and Rust distiller

set -euo pipefail

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

usage() {
    echo "Usage: $0 {python|rust|status}"
    echo ""
    echo "Commands:"
    echo "  python  - Use the Python-based extractor service"
    echo "  rust    - Use the Rust-based distiller service"
    echo "  status  - Show which extractor is currently active"
    echo ""
    exit 1
}

status() {
    echo -e "${GREEN}Checking extractor status...${NC}"

    if docker compose ps | grep -q "discogsography-python-extractor.*Up"; then
        echo -e "${YELLOW}Python extractor is running${NC}"
    elif docker compose ps | grep -q "discogsography-rust-extractor.*Up"; then
        echo -e "${YELLOW}Rust extractor is running${NC}"
    else
        echo -e "${RED}No extractor service is currently running${NC}"
    fi
}

switch_to_python() {
    echo -e "${GREEN}Switching to Python extractor...${NC}"

    # Stop rust-extractor if running
    docker compose --profile rust-extractor stop rust-extractor 2>/dev/null || true

    # Start Python extractor (default profile, no need to specify)
    docker compose up -d python-extractor

    echo -e "${GREEN}✅ Python extractor is now active${NC}"
}

switch_to_rust() {
    echo -e "${GREEN}Switching to Rust extractor...${NC}"

    # Stop Python extractor if running
    docker compose stop python-extractor 2>/dev/null || true

    # Start Rust extractor
    docker compose --profile rust-extractor up -d rust-extractor

    echo -e "${GREEN}✅ Rust extractor is now active${NC}"
}

# Main logic
if [ $# -eq 0 ]; then
    usage
fi

case "$1" in
    python)
        switch_to_python
        ;;
    rust)
        switch_to_rust
        ;;
    status)
        status
        ;;
    *)
        echo -e "${RED}Invalid option: $1${NC}"
        usage
        ;;
esac
