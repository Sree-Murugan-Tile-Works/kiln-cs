#!/usr/bin/env bash
# setup.bash — one-time bootstrap for kiln-cs
#
# Run from the project root after cloning:
#   bash setup.bash
#
# What it does:
#   1. Verifies Python ≥ 3.10
#   2. Creates data/ directory
#   3. Creates a shared .venv at the project root
#   4. Installs all packages from requirements.txt
#   5. Initialises config.db  (fan-ctrl/config.py)
#   6. Initialises data.db    (kiln_data + error_log tables)
#   7. Prints a pass/fail report

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Colour helpers ─────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info() { echo -e "  ${CYAN}→${NC}  $*"; }
ok()   { echo -e "  ${GREEN}✓${NC}  $*"; }
warn() { echo -e "  ${YELLOW}!${NC}  $*"; }
err()  { echo -e "  ${RED}✗${NC}  $*"; }

# ── Step tracking ──────────────────────────────────────────────────────────────
STEP_NAMES=()
STEP_PASS=()

record_pass() { ok  "$1";    STEP_NAMES+=("$1"); STEP_PASS+=(1); }
record_fail() { err "$1: $2"; STEP_NAMES+=("$1"); STEP_PASS+=(0); }

# ── Banner ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}  ╔══════════════════════════════════════╗${NC}"
echo -e "${CYAN}  ║          kiln-cs  setup              ║${NC}"
echo -e "${CYAN}  ╚══════════════════════════════════════╝${NC}"
echo ""

# ── 1. Python version ──────────────────────────────────────────────────────────
info "Checking Python version..."
if ! command -v python3 &>/dev/null; then
    record_fail "Python 3" "python3 not found in PATH"
    echo ""
    err "Cannot continue. Install Python 3.10+ first:"
    echo "      sudo apt install python3 python3-venv python3-pip"
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)

if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ]; then
    record_pass "Python $PY_VER  (>= 3.10 required)"
else
    record_fail "Python version" "found $PY_VER — need 3.10 or newer"
    echo ""
    err "Cannot continue. Install Python 3.10+, then re-run setup.bash"
    exit 1
fi

# ── 2. data/ directory ─────────────────────────────────────────────────────────
info "Creating data/ directory..."
if mkdir -p data; then
    record_pass "data/ directory"
else
    record_fail "data/ directory" "mkdir -p data failed"
fi

# ── 3. Virtual environment ─────────────────────────────────────────────────────
info "Creating virtual environment at .venv/ ..."
if [ -d ".venv" ]; then
    warn ".venv/ already exists — reusing it"
fi
if python3 -m venv .venv; then
    record_pass "Virtual environment (.venv/)"
else
    record_fail "Virtual environment (.venv/)" "python3 -m venv failed"
    echo ""
    err "Cannot continue. Try:"
    echo "      sudo apt install python3-venv"
    exit 1
fi

# ── 4. Upgrade pip ─────────────────────────────────────────────────────────────
info "Upgrading pip..."
if .venv/bin/pip install --quiet --upgrade pip 2>&1; then
    record_pass "pip upgrade"
else
    warn "pip upgrade failed — pip may be slightly outdated but install will likely still work"
fi

# ── 5. Install packages ────────────────────────────────────────────────────────
info "Installing packages from requirements.txt (may take a minute on Pi)..."
if .venv/bin/pip install --quiet -r requirements.txt; then
    record_pass "Install requirements.txt"
else
    record_fail "Install requirements.txt" "pip install failed — see output above"
fi

# ── 6. Initialise config.db ────────────────────────────────────────────────────
info "Initialising config.db via fan-ctrl/config.py..."
if ( cd fan-ctrl && "$SCRIPT_DIR/.venv/bin/python" config.py > /dev/null ); then
    record_pass "config.db created with default parameters"
else
    record_fail "config.db" "fan-ctrl/config.py returned an error"
fi

# ── 7. Initialise data.db ──────────────────────────────────────────────────────
info "Initialising data.db (kiln_data + error_log tables)..."
if ( cd fan-ctrl && "$SCRIPT_DIR/.venv/bin/python" - <<'PYEOF'
from dbwriter import create_data_tables
create_data_tables('../data/data.db')
PYEOF
); then
    record_pass "data.db created (kiln_data + error_log tables)"
else
    record_fail "data.db" "dbwriter.create_data_tables returned an error"
fi

# ── Final report ───────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}  ╔══════════════════════════════════════╗${NC}"
echo -e "${CYAN}  ║           Setup Report               ║${NC}"
echo -e "${CYAN}  ╚══════════════════════════════════════╝${NC}"
echo ""

TOTAL_PASS=0
TOTAL_FAIL=0
for i in "${!STEP_NAMES[@]}"; do
    if [ "${STEP_PASS[$i]}" -eq 1 ]; then
        echo -e "  ${GREEN}✓${NC}  ${STEP_NAMES[$i]}"
        TOTAL_PASS=$((TOTAL_PASS + 1))
    else
        echo -e "  ${RED}✗${NC}  ${STEP_NAMES[$i]}"
        TOTAL_FAIL=$((TOTAL_FAIL + 1))
    fi
done

echo ""
if [ "$TOTAL_FAIL" -eq 0 ]; then
    echo -e "  ${GREEN}All $TOTAL_PASS steps passed — kiln-cs is ready to run.${NC}"
    echo ""
    echo "  ── How to run ──────────────────────────────────────────────────"
    echo ""
    echo "  Activate the shared venv (do this once per shell session):"
    echo "    source .venv/bin/activate"
    echo ""
    echo "  Control daemon  (runs continuously — wire to systemd on Pi):"
    echo "    cd fan-ctrl && python main.py"
    echo ""
    echo "  Dashboard  (start when you need to view or configure):"
    echo "    cd dashboard && flask --app web run -h 0.0.0.0 -p 5001"
    echo ""
    echo "  ────────────────────────────────────────────────────────────────"
else
    echo -e "  ${RED}$TOTAL_FAIL step(s) failed — $TOTAL_PASS passed.${NC}"
    echo ""
    echo "  Fix the issues listed above, then re-run:  bash setup.bash"
fi
echo ""
