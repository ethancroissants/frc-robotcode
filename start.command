#!/usr/bin/env bash
# Cold Fusion Robotics - double-click launcher for macOS / Linux.
# Bootstraps python3 and git via Homebrew (macOS) or the system package
# manager (Linux) when they are missing, then hands off to start.py.
set -e
cd "$(dirname "$0")"

ensure_brew() {
    command -v brew >/dev/null 2>&1 && return 0
    echo "Homebrew is not installed."
    read -r -p "Install Homebrew now? [Y/n] " ans
    case "${ans:-Y}" in
        [Nn]*) return 1 ;;
    esac
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Apple Silicon installs to /opt/homebrew; Intel macs to /usr/local.
    for p in /opt/homebrew/bin /usr/local/bin; do
        [ -x "$p/brew" ] && eval "$("$p/brew" shellenv)" && break
    done
    command -v brew >/dev/null 2>&1
}

linux_install() {
    # $@ is the package list
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update && sudo apt-get install -y "$@"
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y "$@"
    elif command -v yum >/dev/null 2>&1; then
        sudo yum install -y "$@"
    elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -S --noconfirm "$@"
    elif command -v zypper >/dev/null 2>&1; then
        sudo zypper --non-interactive install "$@"
    else
        echo "No supported package manager found. Install manually: $*"
        return 1
    fi
}

ensure_python() {
    command -v python3 >/dev/null 2>&1 && return 0
    command -v python  >/dev/null 2>&1 && return 0
    echo "Python is not installed."
    case "$(uname -s)" in
        Darwin)
            ensure_brew || { echo "Install Python from https://www.python.org/downloads/"; return 1; }
            brew install python ;;
        Linux)
            # Different distros name the tk package differently; try the
            # apt name first, the rpm/arch alternative second.
            if command -v apt-get >/dev/null 2>&1; then
                linux_install python3 python3-pip python3-venv python3-tk
            elif command -v dnf >/dev/null 2>&1 || command -v yum >/dev/null 2>&1; then
                linux_install python3 python3-pip python3-tkinter
            elif command -v pacman >/dev/null 2>&1; then
                linux_install python python-pip tk
            else
                linux_install python3 python3-pip
            fi ;;
        *)
            echo "Unsupported OS. Install Python manually."
            return 1 ;;
    esac
}

ensure_git() {
    command -v git >/dev/null 2>&1 && return 0
    echo "Git is not installed."
    case "$(uname -s)" in
        Darwin)
            ensure_brew || { echo "Install Git from https://git-scm.com/download/mac"; return 1; }
            brew install git ;;
        Linux)
            linux_install git ;;
        *)
            echo "Unsupported OS. Install git manually."
            return 1 ;;
    esac
}

ensure_python || exit 1
ensure_git    || exit 1

if command -v python3 >/dev/null 2>&1; then
    python3 start.py
else
    python start.py
fi
