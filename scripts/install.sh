#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY="https://github.com/liyw0205/nonebot_plugin_spirit_pet"
RELEASE_ASSET="$REPOSITORY/releases/latest/download/project.tar.gz"
RELEASE_PROXIES=("https://gh-proxy.com/")
DEFAULT_DIRECTORY="$HOME/spirit-pet"
SOURCE_MARKER=.xiupet-source
ACTION=install
if (($#)) && [[ $1 == install || $1 == update || $1 == uninstall ]]; then
    ACTION=$1
    shift
fi
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
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$SCRIPT_PATH")" && pwd -P)
SOURCE_ROOT=
if [[ -f $SCRIPT_DIR/../pyproject.toml && -f $SCRIPT_DIR/../requirements.txt && -f $SCRIPT_DIR/../.env.example ]]; then
    SOURCE_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)
fi

DIRECTORY=
SOURCE_MODE=release
YES=0
NO_START=0
SKIP_SYSTEM=0
[[ ${SPIRIT_PET_SKIP_SYSTEM:-0} == 1 ]] && SKIP_SYSTEM=1
while (($#)); do
    case "$1" in
        --directory)
            (($# >= 2)) || { printf 'Missing value for --directory\n' >&2; exit 2; }
            DIRECTORY=$2
            shift 2
            ;;
        --source)
            (($# >= 2)) || { printf 'Missing value for --source\n' >&2; exit 2; }
            SOURCE_MODE=$2
            shift 2
            ;;
        --yes)
            YES=1
            shift
            ;;
        --no-start)
            NO_START=1
            shift
            ;;
        --skip-system)
            SKIP_SYSTEM=1
            shift
            ;;
        --help|-h)
            printf 'Usage: %s [install|update|uninstall] [--source release|checkout] [--directory PATH] [--yes] [--no-start] [--skip-system]\n' "$0"
            printf 'Install and update default to the latest GitHub Release; --source checkout is for new development installs. Existing project files are preserved.\n'
            exit 0
            ;;
        *)
            printf 'Unknown option: %s\n' "$1" >&2
            exit 2
            ;;
    esac
done

case "$ACTION" in
    install|update|uninstall) ;;
    *) printf 'Usage: %s [install|update|uninstall] [--source release|checkout] [--directory PATH] [--yes] [--no-start] [--skip-system]\n' "$0" >&2; exit 2 ;;
esac
case "$SOURCE_MODE" in
    release|checkout) ;;
    *) printf 'Invalid source mode: %s (expected release or checkout)\n' "$SOURCE_MODE" >&2; exit 2 ;;
esac
if [[ $ACTION == update && $SOURCE_MODE != release ]]; then
    printf 'spirit-pet: update only accepts Release sources; checkout installs are never overwritten\n' >&2
    exit 2
fi

if [[ -z $DIRECTORY ]]; then
    if [[ $SOURCE_MODE == checkout ]]; then
        [[ -n $SOURCE_ROOT ]] || { printf 'spirit-pet: --source checkout requires a project checkout\n' >&2; exit 1; }
        DIRECTORY=$SOURCE_ROOT
    else
        DIRECTORY=$DEFAULT_DIRECTORY
    fi
fi
[[ $DIRECTORY == /* ]] || DIRECTORY=$PWD/$DIRECTORY

fail() { printf 'spirit-pet: %s\n' "$*" >&2; exit 1; }

as_root() {
    if ((EUID == 0)); then "$@"
    elif command -v sudo >/dev/null 2>&1; then sudo "$@"
    else fail '系统依赖缺失；请安装 sudo，或手动安装 Python 3.10+、venv、curl 和 tar' ; fi
}

install_system_dependencies() {
    if command -v pkg >/dev/null 2>&1; then
        pkg install -y python curl tar
    elif command -v apt-get >/dev/null 2>&1; then
        as_root apt-get update
        as_root apt-get install -y python3 python3-venv python3-pip curl tar ca-certificates
    elif command -v dnf >/dev/null 2>&1; then
        as_root dnf install -y python3 python3-pip curl tar ca-certificates
    elif command -v yum >/dev/null 2>&1; then
        as_root yum install -y python3 python3-pip curl tar ca-certificates
    elif command -v apk >/dev/null 2>&1; then
        as_root apk add python3 py3-pip py3-virtualenv curl tar ca-certificates
    elif command -v pacman >/dev/null 2>&1; then
        as_root pacman -Sy --needed --noconfirm python python-pip curl tar
    elif command -v zypper >/dev/null 2>&1; then
        as_root zypper --non-interactive install python3 python3-pip curl tar ca-certificates
    elif command -v brew >/dev/null 2>&1; then
        brew install python curl
    else
        fail '无法识别系统包管理器；请手动安装 Python 3.10+、venv、curl 和 tar'
    fi
}

find_python() {
    local candidate version major minor
    if [[ -n ${SPIRIT_PET_PYTHON:-} ]]; then
        candidate=$SPIRIT_PET_PYTHON
        version=$("$candidate" --version 2>&1) || return 1
        [[ $version =~ ^Python[[:space:]]+([0-9]+)\.([0-9]+) ]] || return 1
        major=${BASH_REMATCH[1]}
        minor=${BASH_REMATCH[2]}
        if ((major > 3 || (major == 3 && minor >= 10))); then
            printf '%s\n' "$candidate"
            return 0
        fi
        return 1
    fi
    for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
        command -v "$candidate" >/dev/null 2>&1 || continue
        version=$("$candidate" --version 2>&1) || continue
        [[ $version =~ ^Python[[:space:]]+([0-9]+)\.([0-9]+) ]] || continue
        major=${BASH_REMATCH[1]}
        minor=${BASH_REMATCH[2]}
        if ((major > 3 || (major == 3 && minor >= 10))); then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

ensure_python() {
    if ! PYTHON=$(find_python); then
        ((SKIP_SYSTEM == 0)) || fail '未找到 Python 3.10+；移除 --skip-system 后可尝试使用系统包管理器安装'
        install_system_dependencies
        PYTHON=$(find_python) || fail '系统安装后仍未找到可用的 Python 3.10+'
    fi
}

TMP_DIR=
UPDATE_DIR=
UPDATE_ACTIVE=0
UPDATE_COMMITTED=0
UPDATE_PATHS=(src scripts pyproject.toml requirements.txt)
UPDATE_INSTALLED=()
UPDATE_BACKED_UP=()

rollback_update() {
    local index path parent
    for ((index=${#UPDATE_INSTALLED[@]}-1; index>=0; index--)); do
        path=${UPDATE_INSTALLED[index]}
        rm -rf -- "$DIRECTORY/$path" || return 1
    done
    for ((index=${#UPDATE_BACKED_UP[@]}-1; index>=0; index--)); do
        path=${UPDATE_BACKED_UP[index]}
        parent=$(dirname -- "$DIRECTORY/$path")
        mkdir -p -- "$parent" || return 1
        mv -- "$UPDATE_DIR/backup/$path" "$DIRECTORY/$path" || return 1
    done
}

cleanup() {
    local exit_code=$? rollback_ok=1
    if ((UPDATE_ACTIVE && !UPDATE_COMMITTED)); then
        rollback_update || rollback_ok=0
        if ((rollback_ok == 0)); then
            printf 'spirit-pet: source rollback incomplete; preserve backup at %s\n' "$UPDATE_DIR/backup" >&2
        fi
    fi
    [[ -z $TMP_DIR ]] || rm -rf -- "$TMP_DIR"
    if [[ -n $UPDATE_DIR ]] && ((UPDATE_COMMITTED || rollback_ok)); then
        rm -rf -- "$UPDATE_DIR"
    fi
    return "$exit_code"
}
trap cleanup EXIT

canonical_directory() {
    [[ ! -L $DIRECTORY ]] || fail "拒绝使用符号链接作为安装目录：$DIRECTORY"
    if [[ -d $DIRECTORY ]]; then
        DIRECTORY=$(CDPATH= cd -- "$DIRECTORY" && pwd -P)
    elif [[ $ACTION == install ]]; then
        mkdir -p -- "$DIRECTORY"
        DIRECTORY=$(CDPATH= cd -- "$DIRECTORY" && pwd -P)
    fi
}

download_release_candidate() {
    local url=$1 archive="$TMP_DIR/source.tar.gz" extract_dir="$TMP_DIR/extracted" pyproject
    rm -f -- "$archive"
    rm -rf -- "$extract_dir"
    mkdir -p -- "$extract_dir" || return 1
    curl --fail --location --retry 3 --proto '=https' --proto-redir '=https' \
        "$url" -o "$archive" || return 1
    tar -tzf "$archive" >/dev/null 2>&1 || return 1
    tar -xzf "$archive" -C "$extract_dir" || return 1
    pyproject=$(find "$extract_dir" -mindepth 1 -maxdepth 5 -name pyproject.toml -print -quit)
    [[ -n $pyproject && -f ${pyproject%/pyproject.toml}/requirements.txt && -f ${pyproject%/pyproject.toml}/.env.example ]] || return 1
    SOURCE_ROOT=${pyproject%/pyproject.toml}
}

download_source() {
    command -v curl >/dev/null 2>&1 || {
        ((SKIP_SYSTEM == 0)) || fail '未找到 curl；移除 --skip-system 后可尝试安装系统依赖'
        install_system_dependencies
    }
    command -v tar >/dev/null 2>&1 || {
        ((SKIP_SYSTEM == 0)) || fail '未找到 tar；移除 --skip-system 后可尝试安装系统依赖'
        install_system_dependencies
    }
    TMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/spirit-pet.XXXXXX")
    local proxy
    for proxy in "${RELEASE_PROXIES[@]}"; do
        if download_release_candidate "$proxy$RELEASE_ASSET"; then return; fi
        printf '发布资产代理不可用或归档无效，尝试回退。\n' >&2
    done
    download_release_candidate "$RELEASE_ASSET" || fail 'GitHub Release 发布资产下载失败或归档无效；请检查 latest Release 是否包含 project.tar.gz'
}

prepare_project() {
    canonical_directory
    if [[ -f $DIRECTORY/pyproject.toml && -f $DIRECTORY/requirements.txt ]]; then
        printf '保留已有项目源码：%s\n' "$DIRECTORY"
        return
    fi
    if [[ ! -f $DIRECTORY/.xiupet-managed ]]; then
        local first_entry
        first_entry=$(find "$DIRECTORY" -mindepth 1 -maxdepth 1 -print -quit)
        [[ -z $first_entry ]] || fail "拒绝覆盖非空目录：$DIRECTORY"
    fi
    if [[ $SOURCE_MODE == checkout ]]; then
        [[ -n $SOURCE_ROOT ]] || fail '--source checkout requires a project checkout'
    else
        download_source
    fi
    local entry name
    for entry in "$SOURCE_ROOT"/* "$SOURCE_ROOT"/.[!.]* "$SOURCE_ROOT"/..?*; do
        [[ -e $entry || -L $entry ]] || continue
        name=${entry##*/}
        case "$name" in
            .git|.venv|.xiupet|.xiupet-managed|.xiupet-source|.pytest_cache|.ruff_cache|__pycache__|.env|data) continue ;;
        esac
        cp -R -n "$entry" "$DIRECTORY/"
    done
    [[ -f $DIRECTORY/pyproject.toml && -f $DIRECTORY/requirements.txt ]] || fail "项目文件复制失败：$DIRECTORY"
    touch "$DIRECTORY/.xiupet-managed"
    printf '%s\n' "$SOURCE_MODE" > "$DIRECTORY/$SOURCE_MARKER"
}

require_release_install() {
    local source_mode=
    [[ -d $DIRECTORY ]] || fail "安装目录不存在：$DIRECTORY"
    [[ -f $DIRECTORY/.xiupet-managed ]] || fail '拒绝更新非托管目录'
    [[ ! -e $DIRECTORY/.git ]] || fail '拒绝更新 Git checkout；开发源码不会被 Release 覆盖'
    [[ -f $DIRECTORY/$SOURCE_MARKER ]] || fail '安装来源未知；仅可更新由 Release 管理的安装目录'
    source_mode=$(<"$DIRECTORY/$SOURCE_MARKER")
    [[ $source_mode == release ]] || fail "安装来源为 '$source_mode'；xiupet update 只更新 Release 安装，不覆盖 checkout 源码"
    [[ -f $DIRECTORY/pyproject.toml && -f $DIRECTORY/requirements.txt ]] || fail '安装目录缺少项目或依赖定义'
}

replace_release_sources() {
    local path destination parent
    UPDATE_DIR="$DIRECTORY/.xiupet-update.$$"
    [[ ! -e $UPDATE_DIR && ! -L $UPDATE_DIR ]] || fail "更新临时目录已存在：$UPDATE_DIR"
    mkdir -p -- "$UPDATE_DIR/stage" "$UPDATE_DIR/backup" || fail '无法创建更新暂存目录'
    for path in "${UPDATE_PATHS[@]}"; do
        [[ -e $SOURCE_ROOT/$path ]] || fail "Release 归档缺少更新内容：$path"
        cp -a -- "$SOURCE_ROOT/$path" "$UPDATE_DIR/stage/$path" || fail "暂存更新内容失败：$path"
    done
    UPDATE_ACTIVE=1
    for path in "${UPDATE_PATHS[@]}"; do
        destination="$DIRECTORY/$path"
        parent=$(dirname -- "$destination")
        mkdir -p -- "$parent" || return 1
        if [[ -e $destination || -L $destination ]]; then
            mv -- "$destination" "$UPDATE_DIR/backup/$path" || return 1
            UPDATE_BACKED_UP+=("$path")
        fi
        mv -- "$UPDATE_DIR/stage/$path" "$destination" || return 1
        UPDATE_INSTALLED+=("$path")
    done
}

prepare_update() {
    canonical_directory
    require_release_install
    download_source
    [[ -d $SOURCE_ROOT/src && -d $SOURCE_ROOT/scripts ]] || fail 'Release 归档缺少 src/ 或 scripts/'
    replace_release_sources || fail 'Release 源码替换失败；已尝试恢复原源码'
}

ensure_env() {
    if [[ ! -f $DIRECTORY/.env ]]; then
        cp "$DIRECTORY/.env.example" "$DIRECTORY/.env"
        local token
        token=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')
        printf '\nONEBOT_V11_ACCESS_TOKEN=%s\n' "$token" >> "$DIRECTORY/.env"
        chmod 600 "$DIRECTORY/.env"
    fi
}

register_xiupet() {
    local bin_dir=${SPIRIT_PET_BIN_DIR:-$HOME/.local/bin} link target="$DIRECTORY/scripts/xiupet.sh"
    [[ -f $target ]] || fail "未找到 xiupet 脚本：$target"
    mkdir -p -- "$bin_dir"
    bin_dir=$(CDPATH= cd -- "$bin_dir" && pwd -P)
    link="$bin_dir/xiupet"
    if [[ -L $link ]]; then
        local existing
        existing=$(readlink "$link")
        [[ $existing == "$target" ]] || fail "$link 已指向其他安装：$existing"
    elif [[ -e $link ]]; then
        fail "$link 已存在且不是符号链接，请先自行检查"
    fi
    [[ -L $link ]] || ln -s -- "$target" "$link"
    printf '%s\n' "$link" > "$DIRECTORY/.xiupet-command"
    case ":${PATH}:" in
        *":$bin_dir:"*) ;;
        *) printf '将 %s 加入 PATH 后即可使用 xiupet。\n' "$bin_dir" ;;
    esac
}

remove_xiupet() {
    local bin_dir=${SPIRIT_PET_BIN_DIR:-$HOME/.local/bin} link target="$DIRECTORY/scripts/xiupet.sh"
    if [[ -f $DIRECTORY/.xiupet-command ]]; then
        link=$(<"$DIRECTORY/.xiupet-command")
    else
        link="$bin_dir/xiupet"
    fi
    if [[ -L $link && $(readlink "$link") == "$target" ]]; then rm -- "$link"; fi
    rm -f -- "$DIRECTORY/.xiupet-command"
}

install_project() {
    if [[ $ACTION == update ]]; then prepare_update; else prepare_project; fi
    ensure_python
    local venv="$DIRECTORY/.venv"
    local -a venv_args=()
    case ${PREFIX:-} in
        */com.termux/files/usr) venv_args+=(--system-site-packages) ;;
    esac
    if [[ ! -x $venv/bin/python ]]; then
        if ! "$PYTHON" -m venv "${venv_args[@]}" "$venv"; then
            ((SKIP_SYSTEM == 0)) || fail '创建虚拟环境失败；请安装系统 venv 支持后重试'
            install_system_dependencies
            "$PYTHON" -m venv "${venv_args[@]}" "$venv" || fail '创建虚拟环境失败，请检查系统 Python 的 venv 支持'
        fi
    fi
    "$venv/bin/python" -m pip install --upgrade pip
    "$venv/bin/python" -m pip install 'nb-cli==1.5.0' -r "$DIRECTORY/requirements.txt"
    if [[ $ACTION == update ]]; then
        UPDATE_COMMITTED=1
        rm -rf -- "$UPDATE_DIR"
        UPDATE_DIR=
        UPDATE_ACTIVE=0
        printf 'Release 更新完成：%s\n' "$DIRECTORY"
        printf '机器人未启动；使用 xiupet start 手动启动。\n'
        return
    fi
    ensure_env
    register_xiupet
    printf '安装完成：%s\n' "$DIRECTORY"
    if ((NO_START)); then
        printf '启动命令：xiupet start\n'
    else
        cd -- "$DIRECTORY"
        "$venv/bin/nb" run
    fi
}

confirm_uninstall() {
    if ((YES)); then return; fi
    [[ -t 0 ]] || fail '非交互卸载需要显式传入 --yes'
    printf '确认卸载 %s？[y/N] ' "$DIRECTORY" >&2
    local answer
    read -r answer
    [[ $answer == y || $answer == Y || $answer == yes || $answer == YES ]] || fail '已取消卸载'
}

uninstall_project() {
    if [[ ! -d $DIRECTORY ]]; then
        printf '安装目录不存在：%s\n' "$DIRECTORY"
        remove_xiupet
        return
    fi
    canonical_directory
    confirm_uninstall
    if [[ -x $DIRECTORY/scripts/xiupet.sh ]]; then
        bash "$DIRECTORY/scripts/xiupet.sh" stop || true
    fi
    remove_xiupet
    if [[ -f $DIRECTORY/.xiupet-managed ]]; then
        rm -rf -- "$DIRECTORY"
        printf '已卸载并删除安装目录。\n'
    else
        rm -rf -- "$DIRECTORY/.venv" "$DIRECTORY/.xiupet"
        printf '已移除运行环境；源码、.env 和存档已保留。\n'
    fi
}

if [[ $ACTION == install || $ACTION == update ]]; then
    install_project
else
    uninstall_project
fi
