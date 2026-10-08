#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY="https://github.com/liyw0205/nonebot_plugin_spirit_pet"
DEFAULT_DIRECTORY="$HOME/spirit-pet"
ACTION=${1:-install}
if (($#)); then shift; fi
if [[ $ACTION == --help || $ACTION == -h ]]; then
    printf 'Usage: %s [install|uninstall] [--directory PATH] [--yes] [--no-start] [--skip-system]\n' "$0"
    exit 0
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
            printf 'Usage: %s [install|uninstall] [--directory PATH] [--yes] [--no-start] [--skip-system]\n' "$0"
            exit 0
            ;;
        *)
            printf 'Unknown option: %s\n' "$1" >&2
            exit 2
            ;;
    esac
done

case "$ACTION" in
    install|uninstall) ;;
    *) printf 'Usage: %s [install|uninstall] [--directory PATH] [--yes] [--no-start] [--skip-system]\n' "$0" >&2; exit 2 ;;
esac

if [[ -z $DIRECTORY ]]; then
    if [[ -n $SOURCE_ROOT ]]; then DIRECTORY=$SOURCE_ROOT; else DIRECTORY=$DEFAULT_DIRECTORY; fi
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
cleanup() { [[ -z $TMP_DIR ]] || rm -rf -- "$TMP_DIR"; }
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
    curl --fail --location --retry 3 --proto '=https' --proto-redir '=https' \
        "$REPOSITORY/archive/refs/heads/main.tar.gz" -o "$TMP_DIR/source.tar.gz"
    tar -xzf "$TMP_DIR/source.tar.gz" -C "$TMP_DIR"
    local pyproject
    pyproject=$(find "$TMP_DIR" -mindepth 2 -maxdepth 3 -name pyproject.toml -print -quit)
    [[ -n $pyproject ]] || fail '源码归档无效，未找到 pyproject.toml'
    SOURCE_ROOT=${pyproject%/pyproject.toml}
}

prepare_project() {
    canonical_directory
    if [[ -f $DIRECTORY/pyproject.toml && -f $DIRECTORY/requirements.txt ]]; then
        return
    fi
    if [[ ! -f $DIRECTORY/.xiupet-managed ]]; then
        local first_entry
        first_entry=$(find "$DIRECTORY" -mindepth 1 -maxdepth 1 -print -quit)
        [[ -z $first_entry ]] || fail "拒绝覆盖非空目录：$DIRECTORY"
    fi
    if [[ -z $SOURCE_ROOT ]]; then download_source; fi
    local entry name
    for entry in "$SOURCE_ROOT"/* "$SOURCE_ROOT"/.[!.]* "$SOURCE_ROOT"/..?*; do
        [[ -e $entry || -L $entry ]] || continue
        name=${entry##*/}
        case "$name" in
            .git|.venv|.xiupet|.xiupet-managed|.pytest_cache|.ruff_cache|__pycache__|.env|data) continue ;;
        esac
        cp -R -n "$entry" "$DIRECTORY/"
    done
    [[ -f $DIRECTORY/pyproject.toml && -f $DIRECTORY/requirements.txt ]] || fail "项目文件复制失败：$DIRECTORY"
    touch "$DIRECTORY/.xiupet-managed"
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
    prepare_project
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

if [[ $ACTION == install ]]; then
    install_project
else
    uninstall_project
fi
