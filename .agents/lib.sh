# shellcheck shell=bash
## Shared helpers for the orb lifecycle scripts. Sourced, bash, no side effects.

LOG_BASE="$(basename "$0" .sh)"
LOG_SCOPE="$LOG_BASE"

step() { LOG_SCOPE="$LOG_BASE/$1"; }
info() { printf 'INFO %s: %s\n' "$LOG_SCOPE" "$*"; }
warn() { printf 'WARN %s: %s\n' "$LOG_SCOPE" "$*" >&2; }

NIX_PROFILE="$HOME/.nix-profile/bin/nix"
# shellcheck disable=SC2034 # used by the sourcing script
AGENT_ENV="$HOME/.amp-completions-env.sh"

tool_env() {
  cat <<'EOF'
export DO_NOT_TRACK=1
EOF
}

normalize_proxy_env() {
  local http_proxy_value https_proxy_value
  http_proxy_value="${HTTP_PROXY:-${http_proxy:-${npm_config_http_proxy:-}}}"
  https_proxy_value="${HTTPS_PROXY:-${https_proxy:-${npm_config_https_proxy:-}}}"
  [ -n "$http_proxy_value" ] || http_proxy_value="$https_proxy_value"
  [ -n "$https_proxy_value" ] || https_proxy_value="$http_proxy_value"
  [ -n "$http_proxy_value" ] || return 0
  export HTTP_PROXY="$http_proxy_value" http_proxy="$http_proxy_value"
  export HTTPS_PROXY="$https_proxy_value" https_proxy="$https_proxy_value"
  info "egress proxy in use"
}

install_nix() {
  if [ "$(id -u)" = "0" ]; then
    if [ -n "${NIX_CONFIG:-}" ]; then
      NIX_CONFIG+=$'\n'
    fi
    NIX_CONFIG+="build-users-group ="
    export NIX_CONFIG
  fi

  if [ ! -x "$NIX_PROFILE" ]; then
    curl -fsSL https://nixos.org/nix/install -o /tmp/nix-installer.sh
    sh /tmp/nix-installer.sh --no-daemon --yes --no-channel-add
    # shellcheck disable=SC1091 # created by the installer above
    . "$HOME/.nix-profile/etc/profile.d/nix.sh"
  fi

  mkdir -p "$HOME/.config/nix"
  touch "$HOME/.config/nix/nix.conf"
  grep -Fqx 'sandbox = false' "$HOME/.config/nix/nix.conf" ||
    printf '%s\n' 'sandbox = false' >>"$HOME/.config/nix/nix.conf"
  grep -Eq '^experimental-features = .*nix-command.*flakes' "$HOME/.config/nix/nix.conf" ||
    printf '%s\n' 'experimental-features = nix-command flakes' >>"$HOME/.config/nix/nix.conf"
}

devshell_activate() {
  [ -x "$NIX_PROFILE" ] || return 1
  PATH="$(dirname "$NIX_PROFILE"):$HOME/.nix-profile/bin:$PATH"
  export PATH
  command -v direnv >/dev/null 2>&1 ||
    nix profile install --inputs-from . nixpkgs#direnv || return 1
  direnv allow . || return 1
  devshell_reload
}

devshell_reload() {
  local dump
  dump="$(direnv export bash)" || return 1
  eval "$dump"
}
