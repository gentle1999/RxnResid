#!/usr/bin/env sh
if [ -n "${ZSH_VERSION:-}" ] && command -v emulate >/dev/null 2>&1; then
    emulate -L sh
fi
set -eu

DEFAULT_PACKAGE="myrepositorytemplate"
DEFAULT_DISPLAY="MyRepositoryTemplate"
DEFAULT_DESCRIPTION="Internal Python project."
DEFAULT_AUTHOR_NAME="Project Maintainers"
DEFAULT_GITEA_HOST="http://nas.asymcatml.net:13000"
INTERNAL_CONFIG_FILE=".templates/config/internal.env"
INTERNAL_CONFIG_LIB="scripts/lib/internal_config.sh"
PROJECT_TEMPLATE_DIR=".templates/project"
SKIP_PACKAGE=0
SKIP_OWNER=0
PACKAGE_NAME=""
GITEA_USER_VALUE=""
PROJECT_TITLE=""
PROJECT_DESCRIPTION=""
AUTHOR_NAME=""
AUTHOR_EMAIL=""
GITEA_HOST_VALUE=""

usage() {
    cat <<'EOF'
Usage: scripts/configure_project.sh [options]

Configure a repository created from this template.

Options:
  --package-name NAME     Python package/import name, for example my_tool
  --project-title TITLE   Human-readable project title for README and MkDocs
  --description TEXT      Project description for README, pyproject, and MkDocs
  --author-name NAME      Project author or maintainer name for pyproject
  --author-email EMAIL    Optional project author email for pyproject
  --gitea-host URL        Internal Gitea host URL
  --gitea-user USER       Gitea user or organization
  --skip-package          Do not configure package name
  --skip-owner            Do not configure Gitea owner
  -h, --help              Show this help
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --package-name)
            PACKAGE_NAME="${2:-}"
            shift 2
            ;;
        --project-title)
            PROJECT_TITLE="${2:-}"
            shift 2
            ;;
        --description)
            PROJECT_DESCRIPTION="${2:-}"
            shift 2
            ;;
        --author-name)
            AUTHOR_NAME="${2:-}"
            shift 2
            ;;
        --author-email)
            AUTHOR_EMAIL="${2:-}"
            shift 2
            ;;
        --gitea-host)
            GITEA_HOST_VALUE="${2:-}"
            shift 2
            ;;
        --gitea-user)
            GITEA_USER_VALUE="${2:-}"
            shift 2
            ;;
        --skip-package)
            SKIP_PACKAGE=1
            shift
            ;;
        --skip-owner)
            SKIP_OWNER=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
cd "$root_dir"

# shellcheck disable=SC1091
. "$INTERNAL_CONFIG_LIB"
load_internal_config
DEFAULT_GITEA_HOST=${INTERNAL_GITEA_HOST:-$DEFAULT_GITEA_HOST}

ensure_project_config() {
    for file in README.md pyproject.toml mkdocs.yml; do
        if [ -f "$file" ]; then
            continue
        fi
        if [ ! -f "$PROJECT_TEMPLATE_DIR/$file" ]; then
            echo "Missing project config template: $PROJECT_TEMPLATE_DIR/$file" >&2
            exit 1
        fi
        cp "$PROJECT_TEMPLATE_DIR/$file" "$file"
        echo "  generated $file from $PROJECT_TEMPLATE_DIR/$file"
    done
}

validate_package_name() {
    case "$1" in
        ""|[!a-z]*|*[!a-z0-9_]*)
            echo "Package name must be a valid Python import name: lowercase letters, numbers, and underscores only" >&2
            exit 1
            ;;
    esac
}

validate_owner() {
    case "$1" in
        ""|*[!A-Za-z0-9_.-]*)
            echo "Gitea user/org may only contain letters, numbers, underscore, dot, and hyphen" >&2
            exit 1
            ;;
    esac
}

validate_author_email() {
    if [ -z "$1" ]; then
        return 0
    fi
    case "$1" in
        *[[:space:]]*|*@|@*|*@*@*|*..*)
            echo "Author email must look like name@example.com, or be omitted" >&2
            exit 1
            ;;
        *@*.*)
            ;;
        *)
            echo "Author email must look like name@example.com, or be omitted" >&2
            exit 1
            ;;
    esac
}

display_name() {
    awk -F_ '{
        out = ""
        for (i = 1; i <= NF; i++) {
            if ($i != "") {
                out = out toupper(substr($i, 1, 1)) substr($i, 2)
            }
        }
        print out
    }'
}

project_title_for_package() {
    if [ "$1" = "$DEFAULT_PACKAGE" ]; then
        printf "%s" "$DEFAULT_DISPLAY"
    else
        printf "%s\n" "$1" | display_name
    fi
}

normalize_host() {
    value=$1
    if [ -z "$value" ]; then
        value=$DEFAULT_GITEA_HOST
    fi
    printf "%s" "$value" | sed 's#/*$##'
}

toml_escape() {
    printf "%s" "$1" | sed 's#\\#\\\\#g; s#"#\\"#g'
}

yaml_escape() {
    printf "%s" "$1" | sed 's#\\#\\\\#g; s#"#\\"#g'
}

current_package_name() {
    if [ -n "$PACKAGE_NAME" ]; then
        printf "%s" "$PACKAGE_NAME"
        return
    fi

    if [ -f pyproject.toml ]; then
        value=$(awk -F'"' '/^name =/ && $2 !~ /[{][{]/ { print $2; exit }' pyproject.toml)
        if [ -n "$value" ]; then
            printf "%s" "$value"
            return
        fi
    fi

    if [ -f Makefile ]; then
        value=$(awk -F':=' '/^PACKAGE_NAME[[:space:]]*:=/ { gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2); print $2; exit }' Makefile)
        if [ -n "$value" ]; then
            printf "%s" "$value"
            return
        fi
    fi

    for package_dir in src/*; do
        if [ -d "$package_dir" ] && [ -f "$package_dir/__init__.py" ]; then
            basename "$package_dir"
            return
        fi
    done

    printf "%s" "$DEFAULT_PACKAGE"
}

current_gitea_user() {
    if [ -n "$GITEA_USER_VALUE" ]; then
        printf "%s" "$GITEA_USER_VALUE"
        return
    fi

    if [ -f Makefile ]; then
        value=$(awk -F':=' '/^GITEA_USER[[:space:]]*:=/ { gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2); print $2; exit }' Makefile)
        if [ -n "$value" ]; then
            printf "%s" "$value"
            return
        fi
    fi

    printf "YOUR_USER"
}

current_gitea_host() {
    if [ -n "$GITEA_HOST_VALUE" ]; then
        normalize_host "$GITEA_HOST_VALUE"
        return
    fi

    if [ -f Makefile ]; then
        value=$(awk -F':=' '/^GITEA_HOST[[:space:]]*:=/ { gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2); print $2; exit }' Makefile)
        if [ -n "$value" ]; then
            case "$value" in
                *'$('*|*'${'*)
                    ;;
                *)
                    normalize_host "$value"
                    return
                    ;;
            esac
        fi
    fi

    normalize_host "$DEFAULT_GITEA_HOST"
}

current_project_title() {
    if [ -f README.md ]; then
        awk '
            NR == 1 && /^# / {
                sub(/^# /, "")
                if ($0 !~ /[{][{]/) {
                    print
                }
                exit
            }
        ' README.md
    fi
}

current_project_description() {
    if [ -f pyproject.toml ]; then
        value=$(awk -F'"' '/^description =/ && $2 !~ /[{][{]/ { print $2; exit }' pyproject.toml)
        if [ -n "$value" ]; then
            printf "%s" "$value"
            return
        fi
    fi

    if [ -f README.md ]; then
        awk '
            NR == 3 {
                if ($0 !~ /[{][{]/) {
                    print
                }
                exit
            }
        ' README.md
    fi
}

current_author_name() {
    if [ -f pyproject.toml ]; then
        awk -F'name = "' '
            /^authors = \[/ {
                in_authors = 1
                next
            }
            in_authors == 1 && /^\]/ {
                exit
            }
            in_authors == 1 && /name = "/ {
                split($2, parts, "\"")
                if (parts[1] !~ /[{][{]/) {
                    print parts[1]
                }
                exit
            }
        ' pyproject.toml
    fi
}

current_author_email() {
    if [ -f pyproject.toml ]; then
        awk -F'email = "' '
            /^authors = \[/ {
                in_authors = 1
                next
            }
            in_authors == 1 && /^\]/ {
                exit
            }
            in_authors == 1 && /email = "/ {
                split($2, parts, "\"")
                if (parts[1] !~ /[{][{]/) {
                    print parts[1]
                }
                exit
            }
        ' pyproject.toml
    fi
}

replace_in_text_files() {
    old_value=$1
    new_value=$2

    find . -type f \
        -not -path "./.git/*" \
        -not -path "./.venv/*" \
        -not -path "./.mypy_cache/*" \
        -not -path "./.ruff_cache/*" \
        -not -path "./.pytest_cache/*" \
        -not -path "./__pycache__/*" \
        -not -path "*/__pycache__/*" \
        -not -path "./dist/*" \
        -not -path "./build/*" \
        -not -path "./htmlcov/*" \
        -not -path "./scripts/*" \
        -not -path "./uv.lock" \
        -exec sh -c '
            old_value=$1
            new_value=$2
            shift 2
            for file do
                if grep -Iq "$old_value" "$file"; then
                    sed -i.bak "s#${old_value}#${new_value}#g" "$file"
                fi
            done
        ' sh "$old_value" "$new_value" {} +
}

cleanup_backups() {
    find . -name "*.bak" -type f -delete
}

set_makefile_variable() {
    name=$1
    value=$2

    [ -f Makefile ] || return 0
    tmp="Makefile.tmp"
    awk -v name="$name" -v value="$value" '
        index($0, name " :=") == 1 {
            print name " := " value
            updated = 1
            next
        }
        { print }
        END {
            if (updated == 0) {
                print name " := " value
            }
        }
    ' Makefile > "$tmp"
    mv "$tmp" Makefile
}

set_license_owner() {
    owner=$1

    [ -f LICENSE ] || return 0
    tmp="LICENSE.tmp"
    awk -v owner="$owner" '
        /^Copyright \(c\) / {
            sub(/ [^ ]+$/, " " owner)
            print
            next
        }
        { print }
    ' LICENSE > "$tmp"
    mv "$tmp" LICENSE
}

package_already_configured() {
    [ ! -d "src/$DEFAULT_PACKAGE" ]
}

owner_already_configured() {
    ensure_project_config
    if grep -Eq "YOUR_USER|[{][{]GITEA_USER[}][}]" README.md pyproject.toml LICENSE mkdocs.yml 2>/dev/null; then
        return 1
    fi
    if grep -Eq '^GITEA_USER[[:space:]]*:=[[:space:]]*YOUR_USER[[:space:]]*$' Makefile 2>/dev/null; then
        return 1
    fi
    return 0
}

prompt_required() {
    prompt=$1
    value=""
    while [ -z "$value" ]; do
        printf "%s: " "$prompt" >&2
        IFS= read -r value
        if [ -z "$value" ]; then
            echo "Value cannot be empty" >&2
        fi
    done
    printf "%s" "$value"
}

prompt_default() {
    prompt=$1
    default=$2
    printf "%s (default: %s): " "$prompt" "$default" >&2
    IFS= read -r value
    if [ -z "$value" ]; then
        value=$default
    fi
    printf "%s" "$value"
}

prompt_optional() {
    prompt=$1
    printf "%s: " "$prompt" >&2
    IFS= read -r value
    printf "%s" "$value"
}

is_interactive() {
    [ -t 0 ]
}

project_metadata_pending() {
    grep -Eq '[{][{](PACKAGE_NAME|PROJECT_TITLE|PROJECT_DESCRIPTION|PROJECT_DESCRIPTION_TOML|PROJECT_TITLE_YAML|PROJECT_DESCRIPTION_YAML|AUTHOR_ENTRY|GITEA_HOST|GITEA_USER)[}][}]' README.md pyproject.toml mkdocs.yml 2>/dev/null
}

metadata_args_supplied() {
    [ -n "$PACKAGE_NAME" ] || \
        [ -n "$PROJECT_TITLE" ] || \
        [ -n "$PROJECT_DESCRIPTION" ] || \
        [ -n "$AUTHOR_NAME" ] || \
        [ -n "$AUTHOR_EMAIL" ] || \
        [ -n "$GITEA_HOST_VALUE" ] || \
        [ -n "$GITEA_USER_VALUE" ]
}

configure_package() {
    if package_already_configured; then
        if [ -z "$PACKAGE_NAME" ]; then
            PACKAGE_NAME=$(current_package_name)
        fi
        echo "✅ Package name already configured."
        return
    fi

    if [ -z "$PACKAGE_NAME" ]; then
        if ! is_interactive; then
            echo "Package name is required in non-interactive mode. Pass PACKAGE_NAME=your_package." >&2
            exit 1
        fi
        PACKAGE_NAME=$(prompt_required "👉 Enter new package name, use underscores instead of hyphens")
    fi
    validate_package_name "$PACKAGE_NAME"

    if [ "$PACKAGE_NAME" = "$DEFAULT_PACKAGE" ]; then
        echo "✅ Keeping default package name."
        return
    fi

    if [ -d "src/$PACKAGE_NAME" ]; then
        echo "Directory already exists: src/$PACKAGE_NAME" >&2
        exit 1
    fi

    mv "src/$DEFAULT_PACKAGE" "src/$PACKAGE_NAME"
    echo "  renamed src/$DEFAULT_PACKAGE -> src/$PACKAGE_NAME"

    new_display=$(project_title_for_package "$PACKAGE_NAME")
    replace_in_text_files "$DEFAULT_PACKAGE" "$PACKAGE_NAME"
    replace_in_text_files "$DEFAULT_DISPLAY" "$new_display"
    cleanup_backups
    echo "✅ Package name configured."
}

configure_owner() {
    if owner_already_configured; then
        if [ -n "$GITEA_USER_VALUE" ] && [ "$GITEA_USER_VALUE" != "YOUR_USER" ]; then
            validate_owner "$GITEA_USER_VALUE"
            set_makefile_variable "GITEA_USER" "$GITEA_USER_VALUE"
            set_license_owner "$GITEA_USER_VALUE"
            echo "✅ Gitea owner configured."
            return
        fi
        echo "✅ Gitea owner already configured."
        return
    fi

    if [ -z "$GITEA_USER_VALUE" ]; then
        if is_interactive; then
            GITEA_USER_VALUE=$(prompt_default "👉 Enter Gitea user or organization" "YOUR_USER")
        else
            GITEA_USER_VALUE="YOUR_USER"
        fi
    fi

    if [ "$GITEA_USER_VALUE" = "YOUR_USER" ]; then
        echo "ℹ️ Keeping YOUR_USER placeholders."
        return
    fi

    validate_owner "$GITEA_USER_VALUE"
    for file in README.md pyproject.toml LICENSE mkdocs.yml; do
        if [ -f "$file" ]; then
            sed -i.bak "s#YOUR_USER#${GITEA_USER_VALUE}#g" "$file"
        fi
    done
    set_makefile_variable "GITEA_USER" "$GITEA_USER_VALUE"
    set_license_owner "$GITEA_USER_VALUE"
    rm -f README.md.bak pyproject.toml.bak LICENSE.bak Makefile.bak mkdocs.yml.bak
    echo "✅ Gitea owner configured."
}

render_project_file() {
    file=$1
    package_name=$2
    project_title=$3
    project_description=$4
    project_description_toml=$5
    project_title_yaml=$6
    project_description_yaml=$7
    author_entry=$8
    gitea_host=$9
    gitea_user=${10}
    internal_pypi_index=${11}

    [ -f "$file" ] || return 0
    tmp="${file}.tmp"
    awk \
        -v package_name="$package_name" \
        -v project_title="$project_title" \
        -v project_description="$project_description" \
        -v project_description_toml="$project_description_toml" \
        -v project_title_yaml="$project_title_yaml" \
        -v project_description_yaml="$project_description_yaml" \
        -v author_entry="$author_entry" \
        -v gitea_host="$gitea_host" \
        -v gitea_user="$gitea_user" \
        -v internal_pypi_index="$internal_pypi_index" '
        function replace_all(text, key, value,    pos) {
            while ((pos = index(text, key)) > 0) {
                text = substr(text, 1, pos - 1) value substr(text, pos + length(key))
            }
            return text
        }
        {
            line = $0
            line = replace_all(line, "{{PACKAGE_NAME}}", package_name)
            line = replace_all(line, "{{PROJECT_TITLE}}", project_title)
            line = replace_all(line, "{{PROJECT_DESCRIPTION}}", project_description)
            line = replace_all(line, "{{PROJECT_DESCRIPTION_TOML}}", project_description_toml)
            line = replace_all(line, "{{PROJECT_TITLE_YAML}}", project_title_yaml)
            line = replace_all(line, "{{PROJECT_DESCRIPTION_YAML}}", project_description_yaml)
            line = replace_all(line, "{{AUTHOR_ENTRY}}", author_entry)
            line = replace_all(line, "{{GITEA_HOST}}", gitea_host)
            line = replace_all(line, "{{GITEA_USER}}", gitea_user)
            line = replace_all(line, "{{INTERNAL_PYPI_INDEX}}", internal_pypi_index)
            print line
        }
    ' "$file" > "$tmp"
    mv "$tmp" "$file"
}

refresh_readme_metadata() {
    file=$1
    project_title=$2
    project_description=$3

    [ -f "$file" ] || return 0
    tmp="${file}.tmp"
    awk -v project_title="$project_title" -v project_description="$project_description" '
        NR == 1 && /^# / {
            print "# " project_title
            next
        }
        NR == 3 {
            print project_description
            next
        }
        { print }
    ' "$file" > "$tmp"
    mv "$tmp" "$file"
}

refresh_pyproject_metadata() {
    file=$1
    package_name=$2
    project_description_toml=$3
    author_entry=$4
    gitea_host=$5
    gitea_user=$6
    internal_pypi_index=$7

    [ -f "$file" ] || return 0
    tmp="${file}.tmp"
    awk \
        -v package_name="$package_name" \
        -v project_description_toml="$project_description_toml" \
        -v author_entry="$author_entry" \
        -v gitea_host="$gitea_host" \
        -v gitea_user="$gitea_user" \
        -v internal_pypi_index="$internal_pypi_index" '
        /^\[.*\]$/ {
            if (in_scripts == 1 && script_printed == 0) {
                print package_name " = \"" package_name ".main:main\""
            }
            section = $0
            in_scripts = 0
            in_hong = 0
            in_pypi = 0
            print
            next
        }
        section == "[project]" && /^name = / {
            print "name = \"" package_name "\""
            next
        }
        section == "[project]" && /^description = / {
            print "description = \"" project_description_toml "\""
            next
        }
        section == "[project]" && /^authors = \[/ {
            print
            print "    " author_entry ","
            in_authors = 1
            next
        }
        in_authors == 1 {
            if ($0 ~ /^\]/) {
                print
                in_authors = 0
            }
            next
        }
        section == "[project.urls]" && /^Homepage = / {
            print "Homepage = \"" gitea_host "/" gitea_user "/" package_name "\""
            next
        }
        section == "[project.urls]" && /^Repository = / {
            print "Repository = \"" gitea_host "/" gitea_user "/" package_name "\""
            next
        }
        section == "[project.urls]" && /^Issues = / {
            print "Issues = \"" gitea_host "/" gitea_user "/" package_name "/issues\""
            next
        }
        section == "[project.scripts]" && in_scripts == 0 {
            in_scripts = 1
            script_printed = 0
        }
        in_scripts == 1 && /^[A-Za-z0-9_-]+[[:space:]]*=/ {
            if (script_printed == 0) {
                print package_name " = \"" package_name ".main:main\""
                script_printed = 1
            }
            next
        }
        /^url = / && section == "[[tool.uv.index]]" && in_pypi == 1 {
            print "url = \"" internal_pypi_index "\""
            next
        }
        /^url = / && section == "[[tool.uv.index]]" && in_hong == 1 {
            print "url = \"" gitea_host "/api/packages/" gitea_user "/pypi/simple/\""
            next
        }
        /^publish-url = / && section == "[[tool.uv.index]]" && in_hong == 1 {
            print "publish-url = \"" gitea_host "/api/packages/" gitea_user "/pypi/\""
            next
        }
        section == "[[tool.uv.index]]" && /^name = "hong"/ {
            in_hong = 1
            print
            next
        }
        section == "[[tool.uv.index]]" && /^name = "pypi"/ {
            in_pypi = 1
            print
            next
        }
        { print }
        END {
            if (in_scripts == 1 && script_printed == 0) {
                print package_name " = \"" package_name ".main:main\""
            }
        }
    ' "$file" > "$tmp"
    mv "$tmp" "$file"
}

refresh_mkdocs_metadata() {
    file=$1
    project_title_yaml=$2
    project_description_yaml=$3
    package_name=$4
    gitea_host=$5
    gitea_user=$6

    [ -f "$file" ] || return 0
    tmp="${file}.tmp"
    awk \
        -v project_title_yaml="$project_title_yaml" \
        -v project_description_yaml="$project_description_yaml" \
        -v package_name="$package_name" \
        -v gitea_host="$gitea_host" \
        -v gitea_user="$gitea_user" '
        /^site_name:/ {
            print "site_name: \"" project_title_yaml "\""
            next
        }
        /^site_description:/ {
            print "site_description: \"" project_description_yaml "\""
            next
        }
        /^site_url:/ {
            print "site_url: \"" gitea_host "/" gitea_user "/" package_name "\""
            next
        }
        /^repo_url:/ {
            print "repo_url: \"" gitea_host "/" gitea_user "/" package_name "\""
            next
        }
        /^repo_name:/ {
            print "repo_name: \"" gitea_user "/" package_name "\""
            next
        }
        { print }
    ' "$file" > "$tmp"
    mv "$tmp" "$file"
}

render_project_metadata() {
    package_name=$(current_package_name)
    gitea_user=$(current_gitea_user)
    gitea_host=$(current_gitea_host)
    metadata_pending=0
    if project_metadata_pending; then
        metadata_pending=1
    fi

    if [ "$metadata_pending" -eq 0 ] && ! metadata_args_supplied; then
        echo "✅ Project metadata already rendered."
        return
    fi

    validate_package_name "$package_name"
    if [ "$gitea_user" != "YOUR_USER" ]; then
        validate_owner "$gitea_user"
    fi
    validate_author_email "$AUTHOR_EMAIL"

    default_title=$(project_title_for_package "$package_name")
    if [ "$gitea_user" = "YOUR_USER" ]; then
        default_author="$DEFAULT_AUTHOR_NAME"
    else
        default_author="$gitea_user"
    fi
    existing_title=$(current_project_title)
    existing_description=$(current_project_description)
    existing_author_name=$(current_author_name)
    existing_author_email=$(current_author_email)

    if [ "$SKIP_PACKAGE" -eq 0 ] && [ "$SKIP_OWNER" -eq 0 ] && is_interactive && [ "$metadata_pending" -eq 1 ]; then
        if [ -z "$PROJECT_TITLE" ]; then
            PROJECT_TITLE=$(prompt_default "👉 Enter project title" "$default_title")
        fi
        if [ -z "$PROJECT_DESCRIPTION" ]; then
            PROJECT_DESCRIPTION=$(prompt_default "👉 Enter project description" "$DEFAULT_DESCRIPTION")
        fi
        if [ -z "$AUTHOR_NAME" ]; then
            AUTHOR_NAME=$(prompt_default "👉 Enter project author/maintainer name" "$default_author")
        fi
        if [ -z "$AUTHOR_EMAIL" ]; then
            AUTHOR_EMAIL=$(prompt_optional "👉 Enter project author email, or press Enter to omit")
        fi
    fi

    if [ -z "$PROJECT_TITLE" ]; then
        if [ -n "$existing_title" ]; then
            PROJECT_TITLE=$existing_title
        else
            PROJECT_TITLE=$default_title
        fi
    fi
    if [ -z "$PROJECT_DESCRIPTION" ]; then
        if [ -n "$existing_description" ]; then
            PROJECT_DESCRIPTION=$existing_description
        else
            PROJECT_DESCRIPTION="$DEFAULT_DESCRIPTION"
        fi
    fi
    if [ -z "$AUTHOR_NAME" ]; then
        if [ -n "$existing_author_name" ]; then
            AUTHOR_NAME=$existing_author_name
        else
            AUTHOR_NAME=$default_author
        fi
    fi
    if [ -z "$AUTHOR_EMAIL" ] && [ -n "$existing_author_email" ]; then
        AUTHOR_EMAIL=$existing_author_email
    fi

    validate_author_email "$AUTHOR_EMAIL"

    if [ -n "$GITEA_HOST_VALUE" ]; then
        set_makefile_variable "GITEA_HOST" "$gitea_host"
    fi

    escaped_description=$(toml_escape "$PROJECT_DESCRIPTION")
    escaped_title_yaml=$(yaml_escape "$PROJECT_TITLE")
    escaped_description_yaml=$(yaml_escape "$PROJECT_DESCRIPTION")
    escaped_author_name=$(toml_escape "$AUTHOR_NAME")
    if [ -n "$AUTHOR_EMAIL" ]; then
        escaped_author_email=$(toml_escape "$AUTHOR_EMAIL")
        author_entry="{ name = \"$escaped_author_name\", email = \"$escaped_author_email\" }"
    else
        author_entry="{ name = \"$escaped_author_name\" }"
    fi
    internal_pypi_index=${INTERNAL_PYPI_INDEX:-https://mirrors.zju.edu.cn/pypi/web/simple}

    for file in README.md pyproject.toml mkdocs.yml; do
        render_project_file \
            "$file" \
            "$package_name" \
            "$PROJECT_TITLE" \
            "$PROJECT_DESCRIPTION" \
            "$escaped_description" \
            "$escaped_title_yaml" \
            "$escaped_description_yaml" \
            "$author_entry" \
            "$gitea_host" \
            "$gitea_user" \
            "$internal_pypi_index"
    done
    refresh_readme_metadata README.md "$PROJECT_TITLE" "$PROJECT_DESCRIPTION"
    refresh_pyproject_metadata pyproject.toml "$package_name" "$escaped_description" "$author_entry" "$gitea_host" "$gitea_user" "$internal_pypi_index"
    refresh_mkdocs_metadata mkdocs.yml "$escaped_title_yaml" "$escaped_description_yaml" "$package_name" "$gitea_host" "$gitea_user"
    echo "✅ Project metadata rendered."
}

ensure_project_config

if [ "$SKIP_PACKAGE" -eq 0 ]; then
    configure_package
fi

if [ "$SKIP_OWNER" -eq 0 ]; then
    configure_owner
fi

render_project_metadata
