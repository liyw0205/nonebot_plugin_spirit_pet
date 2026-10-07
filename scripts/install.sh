#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY=liyw0205/nonebot_plugin_spirit_pet
ACTION=install
ACTION_SET=0
DIRECTORY=
VENV=
BRANCH=${SPIRIT_PET_BRANCH:-main}
HOST=127.0.0.1
PORT=8080
YES=0
NO_START=0
SKIP_SYSTEM=${SPIRIT_PET_SKIP_SYSTEM:-0}
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
LOCAL_PROJECT=$(dirname -- "$SCRIPT_DIR")

usage() {
    printf 'Usage: bash install.sh [install|uninstall|reinstall|update|update-deps] [options]\n'
    printf 'Options: --directory PATH --venv PATH --branch main|develop --host IP --port PORT --yes --no-start --skip-system\n'
}

fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }

while (($#)); do
    case "$1" in
        install|uninstall|reinstall|update|update-deps)
            ((ACTION_SET == 0)) || fail 'Specify only one action.'
            ACTION=$1
            ACTION_SET=1
            ;;
        --directory) (($# >= 2)) || fail '--directory requires a path'; DIRECTORY=$2; shift ;;
        --directory=*) DIRECTORY=${1#*=} ;;
        --venv) (($# >= 2)) || fail '--venv requires a path'; VENV=$2; shift ;;
        --venv=*) VENV=${1#*=} ;;
        --branch) (($# >= 2)) || fail '--branch requires main or develop'; BRANCH=$2; shift ;;
        --branch=*) BRANCH=${1#*=} ;;
        --host) (($# >= 2)) || fail '--host requires an address'; HOST=$2; shift ;;
        --host=*) HOST=${1#*=} ;;
        --port) (($# >= 2)) || fail '--port requires a number'; PORT=$2; shift ;;
        --port=*) PORT=${1#*=} ;;
        --yes) YES=1 ;;
        --no-start) NO_START=1 ;;
        --skip-system) SKIP_SYSTEM=1 ;;
        --help|-h) usage; exit 0 ;;
        *) fail "Unknown argument: $1" ;;
    esac
    shift
done

[[ $BRANCH == main || $BRANCH == develop ]] || fail 'Branch must be main or develop.'
[[ $PORT =~ ^[0-9]+$ ]] && ((PORT >= 1 && PORT <= 65535)) || fail 'Port must be between 1 and 65535.'
[[ -n $HOST && $HOST != *$'\n'* ]] || fail 'Host is invalid.'

is_project() {
    local path=$1
    [[ -f $path/pyproject.toml && -f $path/requirements.txt \
        && -f $path/src/plugins/nonebot_plugin_spirit_pet/__init__.py \
        && -f $path/scripts/install.sh && -f $path/scripts/xiupet.sh ]]
}

absolute_directory() {
    local path=$1 parent name
    [[ $path != *$'\n'* && $path != *$'\r'* ]] || fail 'Installation paths cannot contain line breaks.'
    [[ ! -L $path ]] || fail "Refusing a symlinked installation path: $path"
    if [[ -d $path ]]; then (CDPATH= cd -- "$path" && pwd -P); return; fi
    parent=$(dirname -- "$path")
    name=$(basename -- "$path")
    mkdir -p -- "$parent"
    printf '%s/%s\n' "$(CDPATH= cd -- "$parent" && pwd -P)" "$name"
}

if [[ -n $DIRECTORY ]]; then
    TARGET=$(absolute_directory "$DIRECTORY")
elif is_project "$LOCAL_PROJECT"; then
    TARGET=$(CDPATH= cd -- "$LOCAL_PROJECT" && pwd -P)
else
    TARGET="$HOME/spirit-pet"
fi

find_python() {
    local candidate version major minor
    if [[ -n ${SPIRIT_PET_PYTHON:-} ]]; then
        candidate=$SPIRIT_PET_PYTHON
        version=$("$candidate" --version 2>&1) || return 1
        [[ $version =~ ^Python[[:space:]]+([0-9]+)\.([0-9]+)(\.[0-9]+)?$ ]] || return 1
        major=${BASH_REMATCH[1]}
        minor=${BASH_REMATCH[2]}
        ((major == 3 && minor >= 10)) || return 1
        printf '%s\n' "$candidate"
        return 0
    fi
    for candidate in python3 python3.13 python3.12 python3.11 python3.10; do
        command -v "$candidate" >/dev/null 2>&1 || continue
        version=$("$candidate" --version 2>&1) || continue
        [[ $version =~ ^Python[[:space:]]+([0-9]+)\.([0-9]+)(\.[0-9]+)?$ ]] || continue
        major=${BASH_REMATCH[1]}
        minor=${BASH_REMATCH[2]}
        if ((major == 3 && minor >= 10)); then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

install_system_tools() {
    [[ $SKIP_SYSTEM != 1 ]] || fail 'Required system tools are missing and --skip-system was specified.'
    if [[ ${PREFIX:-} == /data/data/com.termux/files/usr ]]; then
        command -v pkg >/dev/null || fail 'Termux pkg is required to install Python and build tools.'
        pkg install -y python clang rust make pkg-config openssl libffi curl tar gzip coreutils
    elif command -v brew >/dev/null 2>&1; then
        brew install python@3.12 curl
        if [[ -z ${SPIRIT_PET_PYTHON:-} ]]; then
            SPIRIT_PET_PYTHON="$(brew --prefix python@3.12)/bin/python3.12"
            export SPIRIT_PET_PYTHON
        fi
    else
        local -a sudo=()
        if [[ $(id -u) != 0 ]]; then
            command -v sudo >/dev/null || fail 'Install Python 3.10+, curl, tar and gzip, or rerun as root/sudo.'
            sudo=(sudo)
        fi
        if command -v apt-get >/dev/null 2>&1; then
            "${sudo[@]}" apt-get update
            "${sudo[@]}" apt-get install -y python3 python3-venv python3-pip curl ca-certificates tar gzip
        elif command -v dnf >/dev/null 2>&1; then
            "${sudo[@]}" dnf install -y python3 python3-pip curl ca-certificates tar gzip
        elif command -v yum >/dev/null 2>&1; then
            "${sudo[@]}" yum install -y python3 python3-pip python3-virtualenv curl ca-certificates tar gzip
        elif command -v apk >/dev/null 2>&1; then
            "${sudo[@]}" apk add python3 py3-pip py3-virtualenv curl ca-certificates tar gzip
        elif command -v zypper >/dev/null 2>&1; then
            "${sudo[@]}" zypper --non-interactive refresh
            "${sudo[@]}" zypper --non-interactive install python3 python3-pip python3-virtualenv curl ca-certificates tar gzip
        elif command -v pacman >/dev/null 2>&1; then
            "${sudo[@]}" pacman -S --needed --noconfirm python python-pip curl ca-certificates tar gzip
        else
            fail 'No supported package manager found. Install Python 3.10+, curl, tar and gzip, then retry.'
        fi
    fi
}

stop_if_running() {
    if [[ -x $TARGET/scripts/xiupet.sh ]]; then
        XIUPET_PROJECT=$TARGET "$TARGET/scripts/xiupet.sh" stop || true
    fi
}

remove_installation() {
    is_project "$TARGET" || fail "Not a Spirit Pet project: $TARGET"
    if [[ -e $TARGET/.git && $YES != 1 ]]; then
        fail 'Refusing to remove a Git checkout without --yes and --directory.'
    fi
    if [[ ! -f $TARGET/.xiupet-install && $YES != 1 ]]; then
        fail 'Refusing to remove an unmarked source checkout without --yes.'
    fi
    if [[ $YES != 1 ]]; then
        [[ -r /dev/tty ]] || fail 'Uninstall is destructive; pass --yes in a non-interactive shell.'
        printf 'Remove %s and its project environment/data? [y/N] ' "$TARGET" >/dev/tty
        local answer
        IFS= read -r answer </dev/tty || answer=
        [[ $answer == y || $answer == Y || $answer == yes || $answer == YES ]] || {
            printf 'Uninstall cancelled.\n'
            return 0
        }
    fi
    stop_if_running
    local shortcut
    shortcut=
    if [[ -f $TARGET/.xiupet-command ]]; then
        IFS= read -r shortcut < "$TARGET/.xiupet-command" || true
    fi
    if [[ -n $shortcut && $(basename -- "$shortcut") == xiupet && -f $shortcut ]] \
        && grep -Fqx -- "# spirit-pet-command: $TARGET" "$shortcut"; then
        rm -f -- "$shortcut"
    fi
    cd -- "$HOME"
    rm -rf -- "$TARGET"
    printf 'Uninstalled Spirit Pet from %s\n' "$TARGET"
}

if [[ $ACTION == uninstall ]]; then
    remove_installation
    exit 0
fi

needs_download=0
if [[ $ACTION == update && -e $TARGET/.git ]]; then
    :
elif [[ $ACTION == update-deps ]]; then
    is_project "$TARGET" || fail "Not a Spirit Pet project: $TARGET"
elif [[ $ACTION == update ]] && is_project "$TARGET"; then
    needs_download=1
elif is_project "$TARGET"; then
    :
elif is_project "$LOCAL_PROJECT"; then
    :
else
    needs_download=1
fi

if ! find_python >/dev/null 2>&1 || { ((needs_download)) && ! command -v curl >/dev/null 2>&1; }; then
    install_system_tools
fi
PYTHON=$(find_python) || fail 'No usable Python 3.10+ with venv and ensurepip was found.'
if ((needs_download)) && ! command -v curl >/dev/null 2>&1; then
    fail 'curl is required to download the source archive.'
fi
if ((needs_download)) && ! command -v tar >/dev/null 2>&1; then
    fail 'tar is required to extract the source archive.'
fi

validate_archive() {
    local archive=$1 listing verbose
    gzip -t -- "$archive" || return 1
    listing=$(tar -tzf "$archive") || return 1
    [[ -n $listing ]] || return 1
    printf '%s\n' "$listing" | awk '
        BEGIN { count=0; root="" }
        {
            path=$0; sub(/\/$/, "", path)
            if (path == "" || path ~ /^\// || path ~ /\\/ || path ~ /^[A-Za-z]:/ || path ~ /(^|\/)\.\.?($|\/)/) exit 1
            split(path, part, "/")
            if (root == "") root=part[1]
            if (part[1] != root || tolower(path) in seen) exit 1
            seen[tolower(path)]=1; count++
        }
        END { if (count == 0) exit 1 }
    ' || return 1
    verbose=$(tar -tvzf "$archive") || return 1
    printf '%s\n' "$verbose" | awk '
        BEGIN { total=0; count=0 }
        {
            kind=substr($0,1,1)
            if (kind != "-" && kind != "d") exit 1
            size=$3+0
            if (size < 0 || size > 104857600 || total+size > 104857600) exit 1
            total+=size; count++
        }
        END { if (count == 0) exit 1 }
    '
}

download_project() {
    local destination=$1 source url file elapsed best_time=999999 best_file= best_source= name index=0
    local -a sources=("" "https://gh-proxy.com/" "https://gh.jasonzeng.dev/" "https://git.yylx.win/" "https://wget.la/")
    url="https://github.com/$REPOSITORY/archive/refs/heads/$BRANCH.tar.gz"
    mkdir -p -- "$destination"
    for source in "${sources[@]}"; do
        index=$((index + 1))
        name=${source:-GitHub}
        file="$destination/archive-$index.tar.gz"
        printf '[%s/5] %s: ' "$index" "$name" >&2
        if elapsed=$(curl -fLsS --proto '=https' --proto-redir '=https' --connect-timeout 8 --max-time 60 \
            --max-filesize 20971520 -o "$file" -w '%{time_total}' "$source$url" 2>/dev/null) \
            && validate_archive "$file"; then
            printf 'OK %.2f s, archive validated\n' "$elapsed" >&2
            if awk -v current="$elapsed" -v best="$best_time" 'BEGIN {exit !(current < best)}'; then
                best_time=$elapsed
                best_file=$file
                best_source=$name
            fi
        else
            rm -f -- "$file"
            printf 'FAILED (download or archive validation)\n' >&2
        fi
    done
    [[ -n $best_file ]] || fail 'All source downloads failed. Check network/TLS or run from a complete checkout.'
    printf 'Selected source: %s (%.2f s)\n' "$best_source" "$best_time" >&2
    local listing root extracted
    listing=$(tar -tzf "$best_file")
    root=${listing%%$'\n'*}
    root=${root%%/*}
    extracted="$destination/extracted"
    mkdir -p -- "$extracted"
    tar --no-same-owner --no-same-permissions --no-overwrite-dir -xzf "$best_file" -C "$extracted" --strip-components=1 "$root"
    is_project "$extracted" || fail 'Downloaded archive is missing required project files.'
    printf '%s\n' "$extracted"
}

copy_project() {
    local source=$1 destination=$2 entry
    mkdir -p -- "$destination"
    for entry in pyproject.toml requirements.txt .env.example README.md LICENSE src scripts docs; do
        if [[ -d $source/$entry ]]; then
            cp -a -- "$source/$entry" "$destination/"
        elif [[ -f $source/$entry ]]; then
            cp -a -- "$source/$entry" "$destination/"
        fi
    done
}

if [[ $ACTION == update && -e $TARGET/.git ]]; then
    [[ -z $(git -C "$TARGET" status --porcelain) ]] || fail 'Git checkout has local changes; save them before update.'
    [[ -n $(git -C "$TARGET" branch --show-current) ]] || fail 'Cannot update a detached Git checkout.'
    stop_if_running
    git -C "$TARGET" pull --ff-only
elif [[ $ACTION != update-deps ]] && ! is_project "$TARGET"; then
    TEMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/spirit-pet-install.XXXXXX")
    trap 'rm -rf -- "$TEMP_DIR"' EXIT
    if [[ -e $TARGET ]] && find "$TARGET" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
        fail "Refusing to overwrite a non-project directory: $TARGET"
    fi
    if is_project "$LOCAL_PROJECT" && [[ $LOCAL_PROJECT != "$TARGET" ]]; then
        SOURCE=$LOCAL_PROJECT
    elif is_project "$TARGET" && [[ $ACTION != update ]]; then
        SOURCE=$TARGET
    else
        SOURCE=$(download_project "$TEMP_DIR")
    fi
    if is_project "$TARGET" && [[ $ACTION != update ]]; then
        printf 'Keeping existing project source unchanged: %s\n' "$TARGET"
    else
        copy_project "$SOURCE" "$TARGET"
    fi
fi

is_project "$TARGET" || fail "Incomplete project directory: $TARGET"
if [[ $ACTION == update || $ACTION == reinstall ]]; then stop_if_running; fi

if [[ -n $VENV ]]; then
    VENV=$(absolute_directory "$VENV")
elif [[ -f $TARGET/.xiupet-venv ]]; then
    VENV=$(<"$TARGET/.xiupet-venv")
else
    VENV="$TARGET/.venv"
fi
PYTHON_IN_VENV="$VENV/bin/python"
PIP_IN_VENV="$VENV/bin/pip"
if [[ $ACTION == reinstall && -e $VENV ]]; then
    [[ -f $VENV/pyvenv.cfg && -x $PYTHON_IN_VENV ]] || fail "Refusing to replace an invalid environment: $VENV"
    rm -rf -- "$VENV"
fi
if [[ -e $VENV ]]; then
    [[ -f $VENV/pyvenv.cfg && -x $PYTHON_IN_VENV ]] || fail "Not a usable virtual environment: $VENV"
else
    mkdir -p -- "$(dirname -- "$VENV")"
    if [[ ${PREFIX:-} == /data/data/com.termux/files/usr ]]; then
        "$PYTHON" -m venv --system-site-packages "$VENV" || fail 'Could not create the virtual environment; install Python venv support and retry.'
    else
        "$PYTHON" -m venv "$VENV" || fail 'Could not create the virtual environment; install Python venv support and retry.'
    fi
fi

[[ -x $PIP_IN_VENV ]] || fail "pip is missing from the virtual environment: $VENV"
"$PIP_IN_VENV" install --disable-pip-version-check --no-input 'nb-cli==1.5.0'
"$PIP_IN_VENV" install --disable-pip-version-check --no-input -r "$TARGET/requirements.txt"
"$PIP_IN_VENV" check
"$VENV/bin/nb" --help >/dev/null

if [[ ! -e $TARGET/.env ]]; then
    cp -- "$TARGET/.env.example" "$TARGET/.env"
    token=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')
    [[ ${#token} -eq 64 ]] || fail 'Could not generate a OneBot access token.'
    printf '\nONEBOT_V11_ACCESS_TOKEN=%s\n' "$token" >> "$TARGET/.env"
    awk -v host="$HOST" -v port="$PORT" '
        /^HOST=/ { print "HOST=" host; host=""; next }
        /^PORT=/ { print "PORT=" port; port=""; next }
        { print }
        END { if (host != "") print "HOST=" host; if (port != "") print "PORT=" port }
    ' "$TARGET/.env" > "$TARGET/.env.tmp"
    mv -- "$TARGET/.env.tmp" "$TARGET/.env"
    chmod 600 "$TARGET/.env"
    printf 'Created private configuration: %s/.env\n' "$TARGET"
else
    printf 'Keeping existing configuration unchanged: %s/.env\n' "$TARGET"
fi

write_xiupet_command() {
    local bin_dir=${SPIRIT_PET_BIN_DIR:-$HOME/.local/bin} command_file content
    command_file="$bin_dir/xiupet"
    mkdir -p -- "$bin_dir"
    printf -v quoted_project '%q' "$TARGET"
    printf -v quoted_manager '%q' "$TARGET/scripts/xiupet.sh"
    content="#!/usr/bin/env bash\n# spirit-pet-command: $TARGET\nexport XIUPET_PROJECT=$quoted_project\nexec $quoted_manager \"\$@\"\n"
    if [[ -e $command_file ]]; then
        grep -Fq "XIUPET_PROJECT=$quoted_project" "$command_file" \
            || fail "Refusing to overwrite an existing command: $command_file"
    fi
    printf '%b' "$content" > "$command_file"
    chmod 755 "$command_file"
    printf '%s\n' "$command_file" > "$TARGET/.xiupet-command"
    printf '%s\n' "$VENV" > "$TARGET/.xiupet-venv"
    printf 'source-install\n' > "$TARGET/.xiupet-install"
    printf 'Generated management command: %s\n' "$command_file"
    case :$PATH: in *:"$bin_dir":*) ;; *) printf 'Add %s to PATH to run xiupet directly.\n' "$bin_dir" ;; esac
}

write_xiupet_command
printf 'Project: %s\n' "$TARGET"
printf 'Run in foreground: cd %q && %q run\n' "$TARGET" "$VENV/bin/nb"
printf 'Manage in background: xiupet start|stop|restart|status|logs|update|update-deps|uninstall\n'

if [[ $NO_START != 1 && $ACTION != update-deps && $ACTION != update && $ACTION != reinstall ]]; then
    printf 'Starting in the foreground with nb run. Ctrl+C stops the bot.\n'
    cd -- "$TARGET"
    exec "$VENV/bin/nb" run
fi
