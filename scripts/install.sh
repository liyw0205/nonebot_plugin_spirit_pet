#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    printf 'Usage: bash install.sh [--directory PATH] [--venv PATH] [--branch main|develop] [--host IP] [--port PORT] [--yes] [--no-start]\n'
    printf 'Python/curl: auto-install where supported. SPIRIT_PET_SKIP_SYSTEM=1 disables system package installation.\n'
    exit 0
fi
BRANCH=${SPIRIT_PET_BRANCH:-main}
ARGS=("$@")
for ((ARG=0; ARG<${#ARGS[@]}; ARG++)); do
    case "${ARGS[$ARG]}" in
        --branch) BRANCH=${ARGS[$((ARG+1))]:-} ;;
        --branch=*) BRANCH=${ARGS[$ARG]#--branch=} ;;
    esac
done
case "$BRANCH" in main|develop) ;; *) printf 'Branch must be main or develop\n' >&2; exit 1 ;; esac
export SPIRIT_PET_BRANCH="$BRANCH"

find_python() {
    if [[ -n ${SPIRIT_PET_PYTHON:-} ]]; then
        if command -v "$SPIRIT_PET_PYTHON" >/dev/null && "$SPIRIT_PET_PYTHON" -c 'import sys, venv, ensurepip; assert (3,10)<=sys.version_info[:2]<(4,0)' 2>/dev/null; then
            printf '%s\n' "$SPIRIT_PET_PYTHON"
            return 0
        fi
        return 1
    fi
    for CANDIDATE in python3 python3.13 python3.12 python3.11 python3.10; do
        if command -v "$CANDIDATE" >/dev/null && "$CANDIDATE" -c 'import sys, venv, ensurepip; assert (3,10)<=sys.version_info[:2]<(4,0)' 2>/dev/null; then
            printf '%s\n' "$CANDIDATE"
            return 0
        fi
    done
    return 1
}

PYTHON=$(find_python || true)
NEEDS_REMOTE_BOOTSTRAP=1
[[ -f "$SCRIPT_DIR/install_bootstrap.py" ]] && NEEDS_REMOTE_BOOTSTRAP=0
if [[ ${SPIRIT_PET_SKIP_SYSTEM:-0} != 1 ]]; then
    if [[ ${SPIRIT_PET_PLATFORM:-} == termux || ${PREFIX:-} == /data/data/com.termux/files/usr ]]; then
        command -v pkg >/dev/null || { printf 'Termux pkg is required.\n' >&2; exit 1; }
        pkg install -y python clang rust make pkg-config openssl libffi curl
    elif [[ -z $PYTHON ]] || { [[ $NEEDS_REMOTE_BOOTSTRAP == 1 ]] && ! command -v curl >/dev/null; }; then
        if command -v brew >/dev/null; then
            brew install python@3.12 curl ca-certificates
            if [[ -z ${SPIRIT_PET_PYTHON:-} ]]; then
                SPIRIT_PET_PYTHON="$(brew --prefix python@3.12)/bin/python3.12"
                export SPIRIT_PET_PYTHON
            fi
        else
            SUDO=()
            if [[ $(id -u) != 0 ]]; then
                command -v sudo >/dev/null || { printf 'System packages are missing. Rerun as root or install sudo, Python >=3.10 with venv/pip, and curl.\n' >&2; exit 1; }
                SUDO=(sudo)
            fi
            if command -v apt-get >/dev/null; then
                "${SUDO[@]}" apt-get update
                "${SUDO[@]}" apt-get install -y python3 python3-venv python3-pip curl ca-certificates
            elif command -v dnf >/dev/null; then
                "${SUDO[@]}" dnf install -y python3 python3-pip curl ca-certificates
            elif command -v yum >/dev/null; then
                "${SUDO[@]}" yum install -y python3 python3-pip python3-virtualenv curl ca-certificates
            elif command -v apk >/dev/null; then
                "${SUDO[@]}" apk add python3 py3-pip py3-virtualenv curl ca-certificates
            elif command -v zypper >/dev/null; then
                "${SUDO[@]}" zypper --non-interactive refresh
                "${SUDO[@]}" zypper --non-interactive install python3 python3-pip python3-virtualenv curl ca-certificates
            elif command -v pacman >/dev/null; then
                "${SUDO[@]}" pacman -S --needed --noconfirm python python-pip curl ca-certificates
            else
                printf 'No supported package manager found. Install Python >=3.10 with venv/pip and curl, then rerun.\n' >&2
                exit 1
            fi
        fi
    fi
fi
PYTHON=$(find_python) || { printf 'No usable Python >=3.10 with venv/pip was found. Install it and rerun.\n' >&2; exit 1; }
if [[ -f "$SCRIPT_DIR/install_bootstrap.py" ]]; then
    "$PYTHON" "$SCRIPT_DIR/install_bootstrap.py" "$@"
    exit $?
fi

command -v curl >/dev/null || { printf 'Install curl before using the downloaded bootstrap.\n' >&2; exit 1; }
TEMPORARY=$(mktemp -d)
trap 'rm -rf -- "$TEMPORARY"' EXIT
SOURCES=("" "https://gh-proxy.com/" "https://gh.jasonzeng.dev/" "https://git.yylx.win/" "https://wget.la/")
URL="https://raw.githubusercontent.com/liyw0205/nonebot_plugin_spirit_pet/$BRANCH/scripts/install_bootstrap.py"
BEST_FILE=''
BEST_TIME=999999
for INDEX in "${!SOURCES[@]}"; do
    SOURCE=${SOURCES[$INDEX]}
    FILE="$TEMPORARY/bootstrap-$INDEX.py"
    printf '[%s/5] %s: ' "$((INDEX+1))" "${SOURCE:-GitHub}"
    if COST=$(curl -fLsS --proto '=https' --proto-redir '=https' --connect-timeout 5 --max-time 15 \
        --max-filesize 131072 -o "$FILE" -w '%{time_total}' "$SOURCE$URL" 2>"$TEMPORARY/error") \
        && "$PYTHON" -c 'import ast,pathlib,sys; s=pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"); assert s.startswith("# spirit-pet-installer-bootstrap-v1\n"); ast.parse(s)' "$FILE" 2>>"$TEMPORARY/error"; then
        printf 'OK %s s, Python content validated\n' "$COST"
        if awk -v current="$COST" -v best="$BEST_TIME" 'BEGIN {exit !(current < best)}'; then
            BEST_TIME=$COST
            BEST_FILE=$FILE
        fi
    else
        printf 'FAILED (download error or invalid/HTML response)\n'
        sed -n '1,3p' "$TEMPORARY/error" >&2
    fi
done
[[ -n "$BEST_FILE" ]] || { printf 'All five sources failed. Use a complete local checkout or repair DNS/TLS/network.\n' >&2; exit 1; }
printf 'Selected validated bootstrap: %s s\n' "$BEST_TIME"
"$PYTHON" "$BEST_FILE" "$@"
