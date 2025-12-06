#!/bin/bash

# ============================================================================
# Inventory Update - Installation Script
# For Ubuntu 24 LTS Server (LAN deployment without SSL)
# ============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
APP_NAME="inventory-update"
INSTALL_DIR="/opt/${APP_NAME}"
REPO_URL="https://github.com/ruolez/inventory-update.git"
COMPOSE_PROJECT="inventory-update"
DATA_VOLUME="${COMPOSE_PROJECT}_postgres_data"

# Print colored message
print_msg() {
    echo -e "${2:-$BLUE}${1}${NC}"
}

print_success() {
    echo -e "${GREEN}✓ ${1}${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ ${1}${NC}"
}

print_error() {
    echo -e "${RED}✗ ${1}${NC}"
}

# Check if running as root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        print_error "This script must be run as root (use sudo)"
        exit 1
    fi
}

# Check Ubuntu version
check_ubuntu() {
    if [[ ! -f /etc/os-release ]]; then
        print_error "Cannot determine OS version"
        exit 1
    fi
    source /etc/os-release
    if [[ "$ID" != "ubuntu" ]]; then
        print_warning "This script is designed for Ubuntu. Proceeding anyway..."
    fi
}

# Install Docker if not present
install_docker() {
    if command -v docker &> /dev/null; then
        print_success "Docker is already installed"
        return
    fi

    print_msg "Installing Docker..."

    # Remove old versions
    apt-get remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

    # Install prerequisites
    apt-get update
    apt-get install -y ca-certificates curl gnupg lsb-release

    # Add Docker's official GPG key
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    # Set up repository
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null

    # Install Docker
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    # Start and enable Docker
    systemctl start docker
    systemctl enable docker

    print_success "Docker installed successfully"
}

# Get server IP address
get_ip_address() {
    # Try to get the primary IP address
    IP=$(hostname -I | awk '{print $1}')
    if [[ -z "$IP" ]]; then
        IP="localhost"
    fi
    echo "$IP"
}

# Prompt for IP address
prompt_ip_address() {
    local default_ip=$(get_ip_address)
    echo ""
    print_msg "Enter the server IP address for LAN access"
    read -p "IP Address [$default_ip]: " input_ip
    SERVER_IP="${input_ip:-$default_ip}"

    # Validate IP format
    if [[ ! "$SERVER_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] && [[ "$SERVER_IP" != "localhost" ]]; then
        print_error "Invalid IP address format"
        exit 1
    fi
}

# Create production docker-compose file
create_production_compose() {
    cat > "${INSTALL_DIR}/docker-compose.prod.yml" << 'COMPOSE_EOF'
version: '3.8'

services:
  db:
    image: postgres:15-alpine
    container_name: inventory_db
    restart: unless-stopped
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: inventory
      TZ: America/Chicago
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init-scripts:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - inventory_network

  app:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: inventory_app
    restart: unless-stopped
    ports:
      - "80:5557"
    environment:
      FLASK_APP: app.main:app
      FLASK_ENV: production
      DATABASE_URL: postgresql://postgres:postgres@db:5432/inventory
      TZ: America/Chicago
    extra_hosts:
      - "host.docker.internal:host-gateway"
    depends_on:
      db:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5557/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    networks:
      - inventory_network

volumes:
  postgres_data:
    name: inventory-update_postgres_data

networks:
  inventory_network:
    driver: bridge
COMPOSE_EOF

    print_success "Production docker-compose file created"
}

# Clean install
clean_install() {
    print_msg "Starting clean installation..." "$YELLOW"
    echo ""

    # Check for existing installation
    if [[ -d "$INSTALL_DIR" ]]; then
        print_warning "Existing installation found at $INSTALL_DIR"
        read -p "Remove existing installation and data? (y/N): " confirm
        if [[ "$confirm" =~ ^[Yy]$ ]]; then
            remove_installation
        else
            print_msg "Installation cancelled"
            exit 0
        fi
    fi

    # Install Docker
    install_docker

    # Prompt for IP
    prompt_ip_address

    # Clone repository
    print_msg "Cloning repository..."
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"

    # Create production compose file
    create_production_compose

    # Build and start containers
    print_msg "Building and starting containers..."
    docker compose -f docker-compose.prod.yml -p "$COMPOSE_PROJECT" up -d --build

    # Wait for services to be ready
    print_msg "Waiting for services to start..."
    sleep 10

    # Check health
    if curl -s "http://localhost/health" > /dev/null 2>&1; then
        print_success "Installation completed successfully!"
    else
        print_warning "Services are starting up. Please wait a moment..."
    fi

    echo ""
    print_msg "============================================" "$GREEN"
    print_msg "  Inventory Update is now running!" "$GREEN"
    print_msg "============================================" "$GREEN"
    echo ""
    print_msg "  Access the application at:"
    print_msg "  http://${SERVER_IP}" "$YELLOW"
    echo ""
    print_msg "  Installation directory: $INSTALL_DIR"
    print_msg "  Data volume: $DATA_VOLUME"
    echo ""
}

# Update from GitHub
update_installation() {
    print_msg "Starting update..." "$YELLOW"
    echo ""

    if [[ ! -d "$INSTALL_DIR" ]]; then
        print_error "No installation found at $INSTALL_DIR"
        print_msg "Please run a clean install first."
        exit 1
    fi

    cd "$INSTALL_DIR"

    # Check for data volume
    if docker volume inspect "$DATA_VOLUME" > /dev/null 2>&1; then
        print_success "Data volume found - settings will be preserved"
    else
        print_warning "Data volume not found - this appears to be a fresh install"
    fi

    # Stop containers (but don't remove volumes)
    print_msg "Stopping containers..."
    docker compose -f docker-compose.prod.yml -p "$COMPOSE_PROJECT" down 2>/dev/null || \
    docker compose -p "$COMPOSE_PROJECT" down 2>/dev/null || true

    # Save current image IDs for cleanup
    OLD_IMAGES=$(docker images -q "${COMPOSE_PROJECT}*" 2>/dev/null || true)

    # Pull latest code
    print_msg "Pulling latest code from GitHub..."
    git fetch origin
    git reset --hard origin/main

    # Recreate production compose file (in case of updates)
    create_production_compose

    # Rebuild and start containers
    print_msg "Rebuilding containers..."
    docker compose -f docker-compose.prod.yml -p "$COMPOSE_PROJECT" build --no-cache

    print_msg "Starting containers..."
    docker compose -f docker-compose.prod.yml -p "$COMPOSE_PROJECT" up -d

    # Clean up old images
    print_msg "Cleaning up old images..."
    docker image prune -f > /dev/null 2>&1

    # Remove dangling images
    docker images -q --filter "dangling=true" | xargs -r docker rmi 2>/dev/null || true

    # Wait for services
    print_msg "Waiting for services to start..."
    sleep 10

    # Check health
    if curl -s "http://localhost/health" > /dev/null 2>&1; then
        print_success "Update completed successfully!"
    else
        print_warning "Services are starting up. Please wait a moment..."
    fi

    # Get IP for display
    SERVER_IP=$(get_ip_address)

    echo ""
    print_msg "============================================" "$GREEN"
    print_msg "  Update completed!" "$GREEN"
    print_msg "============================================" "$GREEN"
    echo ""
    print_msg "  Application: http://${SERVER_IP}" "$YELLOW"
    print_msg "  Data volume preserved: $DATA_VOLUME"
    echo ""
}

# Remove installation completely
remove_installation() {
    print_msg "Removing installation..." "$RED"
    echo ""

    if [[ ! -d "$INSTALL_DIR" ]]; then
        print_warning "No installation found at $INSTALL_DIR"
    fi

    # Stop and remove containers
    if [[ -d "$INSTALL_DIR" ]]; then
        cd "$INSTALL_DIR"
        print_msg "Stopping and removing containers..."
        docker compose -f docker-compose.prod.yml -p "$COMPOSE_PROJECT" down -v 2>/dev/null || \
        docker compose -p "$COMPOSE_PROJECT" down -v 2>/dev/null || true
    fi

    # Remove any remaining containers with our names
    docker rm -f inventory_app inventory_db 2>/dev/null || true

    # Remove the data volume
    print_msg "Removing data volume..."
    docker volume rm "$DATA_VOLUME" 2>/dev/null || true
    docker volume rm "${COMPOSE_PROJECT}_postgres_data" 2>/dev/null || true

    # Remove images
    print_msg "Removing Docker images..."
    docker rmi $(docker images -q "${COMPOSE_PROJECT}*" 2>/dev/null) 2>/dev/null || true
    docker rmi $(docker images -q "*inventory*" 2>/dev/null) 2>/dev/null || true

    # Clean up dangling images
    docker image prune -f > /dev/null 2>&1

    # Remove installation directory
    if [[ -d "$INSTALL_DIR" ]]; then
        print_msg "Removing installation directory..."
        rm -rf "$INSTALL_DIR"
    fi

    print_success "Installation removed completely"
    echo ""
}

# Show status
show_status() {
    echo ""
    print_msg "============================================"
    print_msg "  Inventory Update - Status"
    print_msg "============================================"
    echo ""

    if [[ ! -d "$INSTALL_DIR" ]]; then
        print_warning "Not installed"
        return
    fi

    cd "$INSTALL_DIR"

    # Container status
    print_msg "Containers:"
    docker compose -f docker-compose.prod.yml -p "$COMPOSE_PROJECT" ps 2>/dev/null || \
    docker ps --filter "name=inventory" --format "  {{.Names}}: {{.Status}}" 2>/dev/null || \
    print_warning "  No containers found"

    echo ""

    # Volume status
    print_msg "Data Volume:"
    if docker volume inspect "$DATA_VOLUME" > /dev/null 2>&1; then
        print_success "  $DATA_VOLUME exists"
    else
        print_warning "  $DATA_VOLUME not found"
    fi

    echo ""

    # Health check
    print_msg "Health Check:"
    if curl -s "http://localhost/health" > /dev/null 2>&1; then
        print_success "  Application is running"
        SERVER_IP=$(get_ip_address)
        print_msg "  URL: http://${SERVER_IP}" "$YELLOW"
    else
        print_error "  Application is not responding"
    fi

    echo ""
}

# Show menu
show_menu() {
    clear
    echo ""
    print_msg "============================================" "$BLUE"
    print_msg "  Inventory Update - Installation Script" "$BLUE"
    print_msg "============================================" "$BLUE"
    echo ""
    print_msg "  1) Clean Install"
    print_msg "  2) Update from GitHub"
    print_msg "  3) Remove Installation"
    print_msg "  4) Show Status"
    print_msg "  5) Exit"
    echo ""
}

# Main
main() {
    check_root
    check_ubuntu

    # If argument provided, run that action
    case "${1:-}" in
        install)
            clean_install
            exit 0
            ;;
        update)
            update_installation
            exit 0
            ;;
        remove)
            read -p "Are you sure you want to remove the installation? (y/N): " confirm
            if [[ "$confirm" =~ ^[Yy]$ ]]; then
                remove_installation
            fi
            exit 0
            ;;
        status)
            show_status
            exit 0
            ;;
    esac

    # Interactive menu
    while true; do
        show_menu
        read -p "Select an option [1-5]: " choice
        echo ""

        case $choice in
            1)
                clean_install
                read -p "Press Enter to continue..."
                ;;
            2)
                update_installation
                read -p "Press Enter to continue..."
                ;;
            3)
                read -p "Are you sure you want to remove the installation? (y/N): " confirm
                if [[ "$confirm" =~ ^[Yy]$ ]]; then
                    remove_installation
                fi
                read -p "Press Enter to continue..."
                ;;
            4)
                show_status
                read -p "Press Enter to continue..."
                ;;
            5)
                print_msg "Goodbye!"
                exit 0
                ;;
            *)
                print_error "Invalid option"
                sleep 1
                ;;
        esac
    done
}

main "$@"
