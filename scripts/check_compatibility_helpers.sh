#!/usr/bin/env sh
if [ -n "${ZSH_VERSION:-}" ] && command -v emulate >/dev/null 2>&1; then
    emulate -L sh
fi
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
cd "$root_dir"

# shellcheck disable=SC1091
. scripts/lib/compatibility.sh

assert_eq() {
    expected=$1
    actual=$2
    label=$3

    if [ "$expected" != "$actual" ]; then
        echo "❌ $label" >&2
        echo "expected: $expected" >&2
        echo "actual:   $actual" >&2
        exit 1
    fi
}

assert_eq "ubuntu-latest" "$(normalize_platform linux)" "linux platform alias"
assert_eq "macos-latest" "$(normalize_platform darwin)" "darwin platform alias"
assert_eq "windows-latest" "$(normalize_platform win)" "windows platform alias"
assert_eq "x86_64" "$(normalize_arch amd64)" "amd64 arch alias"
assert_eq "aarch64" "$(normalize_arch arm64)" "arm64 arch alias"

targets=$(normalize_targets "linux/amd64=runner-x,macos/aarch64=runner-m")
expected_targets="ubuntu-latest|x86_64|runner-x
macos-latest|aarch64|runner-m"
assert_eq "$expected_targets" "$targets" "target normalization"

github_targets=$(build_github_targets "ubuntu-latest windows-latest" "x86_64 aarch64")
filtered=$(filter_removed_targets "$github_targets" "windows-latest" "" "")
expected_filtered="ubuntu-latest|x86_64|ubuntu-latest
ubuntu-latest|aarch64|ubuntu-24.04-arm"
assert_eq "$expected_filtered" "$filtered" "platform removal filtering"

validate_python_range 3.11 3.13

echo "✅ Compatibility helper checks passed."
