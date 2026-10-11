#!/usr/bin/env bash
set -Eeuo pipefail

resolve_script() {
    local source=${BASH_SOURCE[0]} directory
    while [[ -L $source ]]; do
        directory=$(CDPATH= cd -- "$(dirname -- "$source")" && pwd -P)
        source=$(readlink "$source")
        [[ $source == /* ]] || source=$directory/$source
    done
    printf '%s\n' "$source"
}

SCRIPT_PATH=$(resolve_script)
PROJECT=${XIUPET_PROJECT:-$(dirname -- "$(dirname -- "$SCRIPT_PATH")")}
PROJECT=$(CDPATH= cd -- "$PROJECT" && pwd -P)
VENV="$PROJECT/.venv"
BIN="$VENV/bin"
NB="$BIN/nb"
RUNTIME="$PROJECT/.xiupet"
PID_FILE="$RUNTIME/pid"
LOG_FILE="$RUNTIME/run.log"

fail() { printf 'xiupet: %s\n' "$*" >&2; exit 1; }

read_pid() {
    [[ -f $PID_FILE ]] || return 1
    local value
    value=$(<"$PID_FILE")
    [[ $value =~ ^[1-9][0-9]*$ ]] || return 1
    printf '%s\n' "$value"
}

is_running() {
    local pid=${1:-}
    [[ $pid =~ ^[1-9][0-9]*$ ]] && kill -0 "$pid" 2>/dev/null
}

process_group() {
    local pid=$1 value
    value=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ' || true)
    [[ $value =~ ^[1-9][0-9]*$ ]] && printf '%s\n' "$value"
}

status() {
    local pid
    pid=$(read_pid) || { printf 'xiupet is stopped\n'; return 1; }
    if is_running "$pid"; then
        printf 'xiupet is running (pid %s)\nlog: %s\n' "$pid" "$LOG_FILE"
        return 0
    fi
    rm -f -- "$PID_FILE"
    printf 'xiupet is stopped\n'
    return 1
}

start() {
    local pid
    pid=$(read_pid) || pid=
    if is_running "$pid"; then
        printf 'xiupet is already running (pid %s)\n' "$pid"
        return 0
    fi
    rm -f -- "$PID_FILE"
    [[ -x $NB ]] || fail "NoneBot CLI not found: $NB. Run scripts/install.sh install first."
    mkdir -p -- "$RUNTIME"
    # The child changes to the project before running the equivalent of "$NB" run.
    if command -v setsid >/dev/null 2>&1; then
        nohup setsid bash -c 'cd -- "$1" && exec "$2" run' xiupet "$PROJECT" "$NB" \
            >>"$LOG_FILE" 2>&1 </dev/null &
    else
        nohup bash -c 'cd -- "$1" && exec "$2" run' xiupet "$PROJECT" "$NB" \
            >>"$LOG_FILE" 2>&1 </dev/null &
    fi
    pid=$!
    printf '%s\n' "$pid" > "$PID_FILE.tmp"
    mv -- "$PID_FILE.tmp" "$PID_FILE"
    sleep 0.2
    if ! is_running "$pid"; then
        rm -f -- "$PID_FILE"
        printf 'xiupet failed to start; inspect %s\n' "$LOG_FILE" >&2
        return 1
    fi
    printf 'xiupet started (pid %s)\nlog: %s\n' "$pid" "$LOG_FILE"
}

stop() {
    local pid group attempt
    pid=$(read_pid) || pid=
    if ! is_running "$pid"; then
        rm -f -- "$PID_FILE"
        printf 'xiupet is already stopped\n'
        return 0
    fi
    group=$(process_group "$pid") || group=
    if [[ $group == "$pid" ]]; then
        kill -TERM -- "-$group" 2>/dev/null || true
    else
        kill -TERM "$pid" 2>/dev/null || true
    fi
    for ((attempt=0; attempt<80; attempt++)); do
        is_running "$pid" || break
        sleep 0.1
    done
    if is_running "$pid"; then
        if [[ $group == "$pid" ]]; then
            kill -KILL -- "-$group" 2>/dev/null || true
        else
            kill -KILL "$pid" 2>/dev/null || true
        fi
    fi
    rm -f -- "$PID_FILE"
    printf 'xiupet stopped (pid %s)\n' "$pid"
}

run_installer() {
    local action=$1
    local installer="$PROJECT/scripts/install.sh"
    [[ -f $installer ]] || fail "Installer not found: $installer"
    "$installer" "$action" --directory "$PROJECT" --no-start "${@:2}"
}

require_release_install() {
    local source_mode=
    [[ -f $PROJECT/.xiupet-managed ]] || fail 'This is not a managed installation.'
    [[ ! -e $PROJECT/.git ]] || fail 'This is a Git checkout; xiupet update will not overwrite development source.'
    [[ -f $PROJECT/.xiupet-source ]] || fail 'Install source is unknown; update requires a Release-managed installation.'
    source_mode=$(<"$PROJECT/.xiupet-source")
    [[ $source_mode == release ]] || fail "Install source is '$source_mode'; development source will not be overwritten by xiupet update."
    [[ -f $PROJECT/pyproject.toml && -f $PROJECT/requirements.txt ]] || fail 'Project or dependency files are missing.'
}

ACTION=${1:-status}
shift || true
case "$ACTION" in
    start) start ;;
    stop) stop ;;
    restart) stop; start ;;
    status) status ;;
    install) stop; run_installer install ;;
    update)
        [[ $# == 0 ]] || fail 'update does not accept arguments; checkout installs are not overwritten.'
        require_release_install
        stop
        run_installer update
        ;;
    logs)
        lines=80
        if [[ ${1:-} == --lines ]]; then
            [[ ${2:-} =~ ^[1-9][0-9]*$ ]] || fail '--lines must be a positive integer'
            lines=$2
        fi
        if [[ -f $LOG_FILE ]]; then tail -n "$lines" "$LOG_FILE"; else printf 'No log file yet: %s\n' "$LOG_FILE"; fi
        ;;
    uninstall)
        stop
        run_installer uninstall --yes
        ;;
    --help|-h)
        printf 'Usage: xiupet [start|stop|restart|status|logs [--lines N]|install|update|uninstall]\n'
        printf 'install reinstalls dependencies from local files; update fetches the latest Release source and dependencies without starting the bot.\n'
        printf 'update only accepts Release-managed installs and preserves .env, data, .xiupet, .venv, logs, and command links.\n'
        ;;
    *) fail "Unknown action: $ACTION" ;;
esac
