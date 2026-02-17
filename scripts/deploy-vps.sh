#!/bin/bash
# VPS Deployment Script for nanobot
# Usage: ./deploy-vps.sh

set -e

echo "🚀 Nanobot VPS Deployment Script"
echo "================================"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root or with sudo${NC}"
    exit 1
fi

echo -e "${GREEN}Step 1: Updating system...${NC}"
apt update && apt upgrade -y

echo -e "${GREEN}Step 2: Installing dependencies...${NC}"
apt install -y python3.11 python3.11-venv python3-pip git curl

# Optional: Install Node.js for WhatsApp support
read -p "Install Node.js for WhatsApp support? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${GREEN}Installing Node.js 20...${NC}"
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt install -y nodejs
fi

echo -e "${GREEN}Step 3: Installing nanobot...${NC}"
if [ -d "/opt/nanobot" ]; then
    echo -e "${YELLOW}nanobot directory exists, pulling latest changes...${NC}"
    cd /opt/nanobot
    git pull
else
    git clone https://github.com/HKUDS/nanobot.git /opt/nanobot
    cd /opt/nanobot
fi

pip install -e .

echo -e "${GREEN}Step 4: Initializing nanobot...${NC}"
nanobot onboard

echo -e "${YELLOW}Please edit your config file: ~/.nanobot/config.json${NC}"
echo -e "${YELLOW}Add your API keys and channel configurations${NC}"
read -p "Press enter to open config file in nano..."
nano ~/.nanobot/config.json

echo -e "${GREEN}Step 5: Creating systemd service...${NC}"
cat > /etc/systemd/system/nanobot.service << 'EOF'
[Unit]
Description=Nanobot Gateway
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/nanobot
ExecStart=/usr/local/bin/nanobot gateway
Restart=always
RestartSec=10
Environment="PATH=/usr/local/bin:/usr/bin:/bin"

[Install]
WantedBy=multi-user.target
EOF

echo -e "${GREEN}Step 6: Enabling and starting service...${NC}"
systemctl daemon-reload
systemctl enable nanobot
systemctl start nanobot

echo -e "${GREEN}Step 7: Checking status...${NC}"
sleep 2
systemctl status nanobot --no-pager

echo ""
echo -e "${GREEN}✅ Deployment complete!${NC}"
echo ""
echo "Useful commands:"
echo "  - View logs: journalctl -u nanobot -f"
echo "  - Restart: systemctl restart nanobot"
echo "  - Stop: systemctl stop nanobot"
echo "  - Edit config: nano ~/.nanobot/config.json"
echo "  - Update: cd /opt/nanobot && git pull && pip install -e . && systemctl restart nanobot"
echo ""
