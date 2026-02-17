#!/bin/bash
# Docker Deployment Script for nanobot
# Usage: ./deploy-docker.sh

set -e

echo "🐳 Nanobot Docker Deployment Script"
echo "===================================="

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}Docker not found. Installing Docker...${NC}"
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    rm get-docker.sh

    # Install Docker Compose plugin
    apt install -y docker-compose-plugin

    echo -e "${GREEN}Docker installed successfully${NC}"
else
    echo -e "${GREEN}Docker already installed${NC}"
fi

# Check if Docker Compose is available
if ! docker compose version &> /dev/null; then
    echo -e "${RED}Docker Compose plugin not found${NC}"
    exit 1
fi

echo -e "${GREEN}Step 1: Creating config directory...${NC}"
mkdir -p ~/.nanobot

# Initialize config if it doesn't exist
if [ ! -f ~/.nanobot/config.json ]; then
    echo -e "${GREEN}Step 2: Initializing config...${NC}"
    docker run --rm -v ~/.nanobot:/root/.nanobot ghcr.io/hkuds/nanobot:latest onboard

    echo -e "${YELLOW}Please edit your config file: ~/.nanobot/config.json${NC}"
    echo -e "${YELLOW}Add your API keys and channel configurations${NC}"
    read -p "Press enter to open config file in nano..."
    nano ~/.nanobot/config.json
else
    echo -e "${GREEN}Config already exists${NC}"
fi

echo -e "${GREEN}Step 3: Starting nanobot with Docker Compose...${NC}"
docker compose up -d

echo -e "${GREEN}Step 4: Checking status...${NC}"
sleep 2
docker compose ps
docker compose logs --tail=20

echo ""
echo -e "${GREEN}✅ Deployment complete!${NC}"
echo ""
echo "Useful commands:"
echo "  - View logs: docker compose logs -f"
echo "  - Restart: docker compose restart"
echo "  - Stop: docker compose down"
echo "  - Edit config: nano ~/.nanobot/config.json (then restart)"
echo "  - Update: docker compose pull && docker compose up -d"
echo ""
