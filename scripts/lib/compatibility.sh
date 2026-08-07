#!/usr/bin/env sh

validate_python_version() {
    if ! printf "%s" "$1" | grep -Eq '^[0-9]+[.][0-9]+([.][0-9]+)?$'; then
        echo "Python version must look like 3.11 or 3.11.9" >&2
        exit 1
    fi
    if [ "$(printf "%s\n" "$1" | awk -F. '{ print $1 }')" != "3" ]; then
        echo "This template currently supports Python 3.x compatibility ranges" >&2
        exit 1
    fi
}

python_major_minor() {
    printf "%s\n" "$1" | awk -F. '{ print $1 "." $2 }'
}

python_version_num() {
    printf "%s\n" "$1" | awk -F. '{ print ($1 * 100) + $2 }'
}

validate_python_range() {
    min_version=$1
    max_version=$2

    validate_python_version "$min_version"
    validate_python_version "$max_version"

    min_num=$(python_version_num "$min_version")
    max_num=$(python_version_num "$max_version")
    if [ "$min_num" -gt "$max_num" ]; then
        echo "Minimum Python version cannot be greater than maximum Python version" >&2
        exit 1
    fi
}

normalize_platform() {
    value=$(printf "%s" "$1" | tr '[:upper:]' '[:lower:]')
    case "$value" in
        ubuntu|linux|gnu-linux|ubuntu-latest)
            printf "ubuntu-latest"
            ;;
        mac|macos|darwin|osx|macos-latest)
            printf "macos-latest"
            ;;
        win|win32|win64|windows|windows-latest)
            printf "windows-latest"
            ;;
        *)
            echo "Unsupported platform: $1" >&2
            exit 1
            ;;
    esac
}

normalize_arch() {
    value=$(printf "%s" "$1" | tr '[:upper:]' '[:lower:]')
    case "$value" in
        x86|x64|amd64|x86_64|x86-64)
            printf "x86_64"
            ;;
        arm64|aarch|aarch64|arm64v8|armv8|armv8-a)
            printf "aarch64"
            ;;
        *)
            echo "Unsupported architecture: $1" >&2
            echo "Supported aliases: x86/x64/amd64/x86_64 and arm64/aarch/aarch64" >&2
            exit 1
            ;;
    esac
}

normalize_platforms() {
    out=""
    for raw in $(printf "%s\n" "$1" | tr ',;' ' '); do
        normalized=$(normalize_platform "$raw")
        if ! printf "%s\n" "$out" | grep -qx "$normalized"; then
            out="${out}${normalized}
"
        fi
    done
    if [ -z "$out" ]; then
        return 1
    fi
    printf "%s" "$out" | sed '/^$/d'
}

normalize_arches() {
    out=""
    for raw in $(printf "%s\n" "$1" | tr ',;' ' '); do
        normalized=$(normalize_arch "$raw")
        if ! printf "%s\n" "$out" | grep -qx "$normalized"; then
            out="${out}${normalized}
"
        fi
    done
    if [ -z "$out" ]; then
        return 1
    fi
    printf "%s" "$out" | sed '/^$/d'
}

default_runner_for_target() {
    platform=$1
    arch=$2

    case "$platform/$arch" in
        ubuntu-latest/x86_64)
            printf "ubuntu-latest"
            ;;
        ubuntu-latest/aarch64)
            printf "linux-arm64"
            ;;
        macos-latest/aarch64)
            printf "macos-arm64"
            ;;
        *)
            echo "No default runner mapping for $platform/$arch" >&2
            echo "Use TARGETS=\"platform/arch=runner-label\" for non-default internal runners." >&2
            exit 1
            ;;
    esac
}

github_runner_for_target() {
    platform=$1
    arch=$2

    case "$platform/$arch" in
        ubuntu-latest/x86_64)
            printf "ubuntu-latest"
            ;;
        ubuntu-latest/aarch64)
            printf "ubuntu-24.04-arm"
            ;;
        macos-latest/x86_64)
            printf "macos-15-intel"
            ;;
        macos-latest/aarch64)
            printf "macos-latest"
            ;;
        windows-latest/x86_64)
            printf "windows-latest"
            ;;
        windows-latest/aarch64)
            printf "windows-11-arm"
            ;;
        *)
            echo "No GitHub mirror runner mapping for $platform/$arch" >&2
            exit 1
            ;;
    esac
}

build_targets() {
    platforms_text=$1
    arches_text=$2

    for platform in $platforms_text; do
        for arch in $arches_text; do
            runner=$(default_runner_for_target "$platform" "$arch")
            printf "%s|%s|%s\n" "$platform" "$arch" "$runner"
        done
    done
}

build_github_targets() {
    platforms_text=$1
    arches_text=$2

    for platform in $platforms_text; do
        for arch in $arches_text; do
            runner=$(github_runner_for_target "$platform" "$arch")
            printf "%s|%s|%s\n" "$platform" "$arch" "$runner"
        done
    done
}

target_pairs() {
    awk -F'|' '$1 != "" { print $1 "/" $2 }'
}

filter_targets_by_pairs() {
    targets_text=$1
    allowed_pairs_text=$2

    printf "%s\n" "$targets_text" | awk -F'|' -v allowed_pairs_text="$allowed_pairs_text" '
        BEGIN {
            split(allowed_pairs_text, allowed_pairs, "\n")
            for (i in allowed_pairs) {
                if (allowed_pairs[i] != "") {
                    allowed[allowed_pairs[i]] = 1
                }
            }
        }
        $1 != "" {
            pair = $1 "/" $2
            if (allowed[pair] == 1) {
                print
            }
        }
    '
}

normalize_targets() {
    out=""
    for raw in $(printf "%s\n" "$1" | tr ',;' ' '); do
        spec=$raw
        runner=""
        case "$spec" in
            *=*)
                runner=${spec#*=}
                spec=${spec%%=*}
                ;;
        esac

        case "$spec" in
            */*)
                platform_raw=${spec%%/*}
                arch_raw=${spec#*/}
                ;;
            *)
                echo "Target must use platform/arch syntax: $raw" >&2
                exit 1
                ;;
        esac

        platform=$(normalize_platform "$platform_raw")
        arch=$(normalize_arch "$arch_raw")
        if [ -z "$runner" ]; then
            runner=$(default_runner_for_target "$platform" "$arch")
        fi

        line="$platform|$arch|$runner"
        if ! printf "%s\n" "$out" | grep -qx "$line"; then
            out="${out}${line}
"
        fi
    done
    if [ -z "$out" ]; then
        return 1
    fi
    printf "%s" "$out" | sed '/^$/d'
}

normalize_target_pairs() {
    out=""
    for raw in $(printf "%s\n" "$1" | tr ',;' ' '); do
        spec=$raw
        case "$spec" in
            *=*)
                spec=${spec%%=*}
                ;;
        esac

        case "$spec" in
            */*)
                platform_raw=${spec%%/*}
                arch_raw=${spec#*/}
                ;;
            *)
                echo "Target removal must use platform/arch syntax: $raw" >&2
                exit 1
                ;;
        esac

        platform=$(normalize_platform "$platform_raw")
        arch=$(normalize_arch "$arch_raw")
        line="$platform/$arch"
        if ! printf "%s\n" "$out" | grep -qx "$line"; then
            out="${out}${line}
"
        fi
    done
    printf "%s" "$out" | sed '/^$/d'
}

unique_target_field() {
    field=$1
    awk -F'|' -v field="$field" '
        {
            value = $field
            if (value != "" && seen[value] == 0) {
                print value
                seen[value] = 1
            }
        }
    '
}

filter_removed_targets() {
    targets_text=$1
    removed_platforms_text=$2
    removed_arches_text=$3
    removed_targets_text=$4

    printf "%s\n" "$targets_text" | awk -F'|' \
        -v removed_platforms_text="$removed_platforms_text" \
        -v removed_arches_text="$removed_arches_text" \
        -v removed_targets_text="$removed_targets_text" '
        BEGIN {
            split(removed_platforms_text, removed_platforms, "\n")
            for (i in removed_platforms) {
                if (removed_platforms[i] != "") {
                    removed_platform_map[removed_platforms[i]] = 1
                }
            }

            split(removed_arches_text, removed_arches, "\n")
            for (i in removed_arches) {
                if (removed_arches[i] != "") {
                    removed_arch_map[removed_arches[i]] = 1
                }
            }

            split(removed_targets_text, removed_targets, "\n")
            for (i in removed_targets) {
                if (removed_targets[i] != "") {
                    removed_target_map[removed_targets[i]] = 1
                }
            }
        }
        {
            pair = $1 "/" $2
            if (removed_platform_map[$1] == 1) {
                next
            }
            if (removed_arch_map[$2] == 1) {
                next
            }
            if (removed_target_map[pair] == 1) {
                next
            }
            print
        }
    '
}
