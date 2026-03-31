#!/bin/bash
# =============================================================
#  K4GSR BL10 NanoProbe -- GitHub-based Deployment
#  Pulls latest code from GitHub, updates deps, restarts services.
#
#  Usage:
#    bash deploy/deploy.sh              # Standard deploy
#    bash deploy/deploy.sh --no-restart # Pull only, no service restart
#    bash deploy/deploy.sh --branch dev # Deploy specific branch
# =============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/config.env"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "[ERROR] Config file not found: $CONFIG_FILE"
    exit 1
fi

source "$CONFIG_FILE"

# ---- Parse arguments ----
DO_RESTART="yes"
DEPLOY_BRANCH="$GITHUB_BRANCH"

while [ $# -gt 0 ]; do
    case "$1" in
        --no-restart) DO_RESTART="no"; shift ;;
        --branch)     DEPLOY_BRANCH="$2"; shift 2 ;;
        *)            echo "Unknown option: $1"; exit 1 ;;
    esac
done

# ---- Derived variables ----
VENV_DIR="${INSTALL_DIR}/.venv"
BEAMLINE_CTL="$INSTALL_DIR/deploy/beamline_ctl.sh"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo ""
echo "============================================"
echo "  K4GSR Deploy -- $TIMESTAMP"
echo "  Branch: $DEPLOY_BRANCH"
echo "  Dir:    $INSTALL_DIR"
echo "============================================"
echo ""

cd "$INSTALL_DIR"

# -----------------------------------------------------------
# 1. Pre-deploy checks
# -----------------------------------------------------------
log_info "[1/5] Pre-deploy checks..."

# Check for uncommitted local changes
if ! git diff --quiet 2>/dev/null; then
    log_warn "Uncommitted local changes detected!"
    git status --short
    echo ""
    read -r -p "Continue anyway? Local changes will be stashed. [y/N] " confirm
    if [ "${confirm,,}" != "y" ]; then
        echo "Deploy cancelled."
        exit 0
    fi
    git stash save "auto-stash before deploy $TIMESTAMP"
    log_info "Changes stashed."
fi

PREV_COMMIT=$(git rev-parse --short HEAD)

# -----------------------------------------------------------
# 2. Pull latest code
# -----------------------------------------------------------
log_info "[2/5] Pulling from GitHub ($DEPLOY_BRANCH)..."

git fetch origin
git checkout "$DEPLOY_BRANCH"
git pull origin "$DEPLOY_BRANCH"

NEW_COMMIT=$(git rev-parse --short HEAD)

if [ "$PREV_COMMIT" = "$NEW_COMMIT" ]; then
    log_info "Already up to date ($NEW_COMMIT). No changes."
    if [ "$DO_RESTART" = "no" ]; then
        exit 0
    fi
else
    log_info "Updated: $PREV_COMMIT -> $NEW_COMMIT"
    echo ""
    echo "  Changes:"
    git log --oneline "${PREV_COMMIT}..${NEW_COMMIT}" | head -20
    echo ""
fi

# -----------------------------------------------------------
# 3. Update dependencies (if requirements.txt changed)
# -----------------------------------------------------------
log_info "[3/5] Checking dependencies..."

if git diff "${PREV_COMMIT}..${NEW_COMMIT}" --name-only 2>/dev/null | grep -q "requirements"; then
    log_info "requirements.txt changed. Updating pip packages..."
    "$VENV_DIR/bin/pip" install -r server/requirements.txt -q
    log_info "Dependencies updated."
else
    log_info "No dependency changes."
fi

# -----------------------------------------------------------
# 4. Update config.env on server (merge new keys)
# -----------------------------------------------------------
log_info "[4/5] Checking config..."

# Copy deploy/config.env if not present on server
SERVER_CONFIG="$INSTALL_DIR/deploy/config.env"
if [ ! -f "$SERVER_CONFIG" ]; then
    log_warn "config.env not found. Using defaults from repo."
fi

# -----------------------------------------------------------
# 5. Restart services
# -----------------------------------------------------------
if [ "$DO_RESTART" = "yes" ]; then
    log_info "[5/5] Restarting services..."

    if [ -f "$BEAMLINE_CTL" ]; then
        bash "$BEAMLINE_CTL" restart
    else
        log_warn "beamline_ctl.sh not found. Restart services manually."
    fi
else
    log_info "[5/5] Skipping restart (--no-restart)."
fi

# -----------------------------------------------------------
# Summary
# -----------------------------------------------------------
echo ""
echo "============================================"
echo "  Deploy Complete"
echo "============================================"
echo "  Commit:  $NEW_COMMIT"
echo "  Branch:  $DEPLOY_BRANCH"
echo "  Time:    $(date -Iseconds)"
echo ""
if [ "$DO_RESTART" = "yes" ]; then
    echo "  Service status:"
    bash "$BEAMLINE_CTL" status 2>/dev/null || true
fi
echo "============================================"
