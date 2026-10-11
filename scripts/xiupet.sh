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
SOURCE_ROOT=${XIUPET_SOURCE:-$PROJECT}
SOURCE_MODE=${XIUPET_SOURCE_MODE:-auto}
MIRROR=${XIUPET_MIRROR:-accelerated}
MIRROR_URL=${XIUPET_MIRROR_URL:-}
VENV_PATH=${XIUPET_VENV:-}
LOG_LINES=80
YES=0
LOGIN_ARGS=()
VENV_EXPLICIT=0
[[ -n ${XIUPET_VENV:-} ]] && VENV_EXPLICIT=1

fail() { printf 'xiupet: %s\n' "$*" >&2; exit 1; }

refresh_paths() {
    if ((VENV_EXPLICIT == 0)); then
        if [[ -f $PROJECT/.xiupet-venv ]]; then VENV_PATH=$(<"$PROJECT/.xiupet-venv"); else VENV_PATH=.venv; fi
    fi
    [[ $VENV_PATH == /* ]] || VENV_PATH=$PROJECT/$VENV_PATH
    VENV=${VENV_PATH%/}
    BIN="$VENV/bin"
    NB="$BIN/nb"
    PYTHON="$BIN/python"
    RUNTIME="$PROJECT/.xiupet"
    PID_FILE="$RUNTIME/pid"
    LOG_FILE="$RUNTIME/run.log"
}

usage() {
    printf '用法：xiupet <install|update|uninstall|start|stop|restart|status|logs|login> [选项]\n'
    printf '选项：--source-mode auto|release|source --source PATH --mirror direct|accelerated|custom --target PATH --venv PATH --lines N\n'
    printf 'QQ 官方机器人授权：xiupet login [--timeout SEC] [--interval SEC]\n'
}

ACTION=status
if (($#)) && [[ $1 =~ ^(install|update|uninstall|start|stop|restart|status|logs|login)$ ]]; then ACTION=$1; shift; fi
while (($#)); do
    case "$1" in
        --target)
            (($# >= 2)) || fail '--target 需要一个路径'
            PROJECT=$2; PROJECT=$(CDPATH= cd -- "$PROJECT" && pwd -P)
            shift 2 ;;
        --source) (($# >= 2)) || fail '--source 需要一个路径'; SOURCE_ROOT=$2; shift 2 ;;
        --source-mode) (($# >= 2)) || fail '--source-mode 需要一个值'; SOURCE_MODE=$2; shift 2 ;;
        --mirror) (($# >= 2)) || fail '--mirror 需要一个值'; MIRROR=$2; shift 2 ;;
        --mirror-url) (($# >= 2)) || fail '--mirror-url 需要一个 URL'; MIRROR_URL=$2; shift 2 ;;
        --venv)
            (($# >= 2)) || fail '--venv 需要一个路径'
            VENV_EXPLICIT=1; VENV_PATH=$2; shift 2 ;;
        --lines) (($# >= 2)) || fail '--lines 需要一个值'; LOG_LINES=$2; shift 2 ;;
        --timeout|--interval) (($# >= 2)) || fail "$1 需要一个值"; LOGIN_ARGS+=("$1" "$2"); shift 2 ;;
        --yes) YES=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) fail "未知参数：$1" ;;
    esac
done
refresh_paths
case "$ACTION" in install|update|uninstall|start|stop|restart|status|logs|login) ;; *) fail "未知动作：$ACTION" ;; esac
case "$SOURCE_MODE" in auto|release|source) ;; *) fail "不支持的源码模式：$SOURCE_MODE" ;; esac
case "$MIRROR" in direct|accelerated|custom) ;; *) fail "不支持的镜像模式：$MIRROR" ;; esac
[[ $LOG_LINES =~ ^[1-9][0-9]*$ ]] || fail '--lines 必须是正整数'

read_pid() { [[ -f $PID_FILE ]] || return 1; local value; value=$(<"$PID_FILE"); [[ $value =~ ^[1-9][0-9]*$ ]] || return 1; printf '%s\n' "$value"; }
is_running() { local pid=${1:-}; [[ $pid =~ ^[1-9][0-9]*$ ]] && kill -0 "$pid" 2>/dev/null; }
process_group() { local pid=$1 value; value=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ' || true); [[ $value =~ ^[1-9][0-9]*$ ]] && printf '%s\n' "$value"; }

status() {
    local pid; pid=$(read_pid) || { printf 'xiupet is stopped\n'; return 1; }
    if is_running "$pid"; then printf 'xiupet is running (pid %s)\nlog: %s\n' "$pid" "$LOG_FILE"; return 0; fi
    rm -f -- "$PID_FILE"; printf 'xiupet is stopped\n'; return 1
}

start() {
    local pid; pid=$(read_pid) || pid=
    if is_running "$pid"; then printf 'xiupet is already running (pid %s)\n' "$pid"; return 0; fi
    rm -f -- "$PID_FILE"; [[ -x $NB ]] || fail "NoneBot CLI not found: $NB. Run xiupet install first."
    mkdir -p -- "$RUNTIME"
    if command -v setsid >/dev/null 2>&1; then
        nohup setsid bash -c 'cd -- "$1" && exec "$2" run' xiupet "$PROJECT" "$NB" >>"$LOG_FILE" 2>&1 </dev/null &
    else
        nohup bash -c 'cd -- "$1" && exec "$2" run' xiupet "$PROJECT" "$NB" >>"$LOG_FILE" 2>&1 </dev/null &
    fi
    pid=$!; printf '%s\n' "$pid" > "$PID_FILE.tmp"; mv -- "$PID_FILE.tmp" "$PID_FILE"; sleep 0.2
    is_running "$pid" || { rm -f -- "$PID_FILE"; printf 'xiupet failed to start; inspect %s\n' "$LOG_FILE" >&2; return 1; }
    printf 'xiupet started (pid %s)\nlog: %s\n' "$pid" "$LOG_FILE"
}

stop() {
    local pid group attempt; pid=$(read_pid) || pid=
    if ! is_running "$pid"; then rm -f -- "$PID_FILE"; printf 'xiupet is already stopped\n'; return 0; fi
    group=$(process_group "$pid") || group=
    if [[ $group == "$pid" ]]; then kill -TERM -- "-$group" 2>/dev/null || true; else kill -TERM "$pid" 2>/dev/null || true; fi
    for ((attempt=0; attempt<80; attempt++)); do is_running "$pid" || break; sleep 0.1; done
    if is_running "$pid"; then if [[ $group == "$pid" ]]; then kill -KILL -- "-$group" 2>/dev/null || true; else kill -KILL "$pid" 2>/dev/null || true; fi; fi
    rm -f -- "$PID_FILE"; printf 'xiupet stopped (pid %s)\n' "$pid"
}

run_installer() {
    local action=$1 installer="$PROJECT/scripts/install.sh" effective_mode=$SOURCE_MODE
    [[ -f $installer ]] || fail "Installer not found: $installer"
    [[ $action == update ]] && effective_mode=release
    local -a args=("$action" --target "$PROJECT" --source "$SOURCE_ROOT" --source-mode "$effective_mode" --mirror "$MIRROR" --venv "$VENV" --no-start)
    [[ -n $MIRROR_URL ]] && args+=(--mirror-url "$MIRROR_URL")
    ((YES)) && args+=(--yes)
    bash "$installer" "${args[@]}"
}

require_release_install() {
    [[ -f $PROJECT/.xiupet-managed ]] || fail 'This is not a managed installation.'
    [[ ! -e $PROJECT/.git ]] || fail 'This is a Git checkout; xiupet update will not overwrite development source.'
    [[ -f $PROJECT/.xiupet-source ]] || fail 'Install source is unknown; update requires a Release-managed installation.'
    [[ $(<"$PROJECT/.xiupet-source") == release ]] || fail 'Install source is not a Release; development source will not be overwritten by xiupet update.'
}

login() {
    [[ -x $PYTHON ]] || fail "Python not found: $PYTHON. Run xiupet install first."
    local helper="$PROJECT/.xiupet/qq_login.py"; [[ -f $helper ]] || helper="$PROJECT/scripts/qq_login.py"
    [[ -f $helper ]] || fail "QQ login helper not found: $PROJECT/.xiupet/qq_login.py"
    local was_running=0 pid; pid=$(read_pid) || pid=; is_running "$pid" && was_running=1 || true
    if "$PYTHON" "$helper" --env "$PROJECT/.env" "${LOGIN_ARGS[@]}"; then
        if ((was_running)); then printf 'QQ configuration updated; restarting xiupet.\n'; stop; start; else printf 'QQ configuration updated; it will take effect on the next start.\n'; fi
    else return $?; fi
}

case "$ACTION" in
    start) start ;; stop) stop ;; restart) stop; start ;; status) status ;;
    logs) if [[ -f $LOG_FILE ]]; then tail -n "$LOG_LINES" "$LOG_FILE"; else printf 'No log file yet: %s\n' "$LOG_FILE"; fi ;;
    install) stop; run_installer install ;;
    update) require_release_install; stop; run_installer update ;;
    uninstall) stop; YES=1; run_installer uninstall ;;
    login) login ;;
esac
