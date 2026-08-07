#!/usr/bin/env sh

job_id_for_target() {
    platform=$1
    arch=$2
    python_version=$3

    arch_id=$(printf "%s" "$arch" | tr '_' '-')
    python_id=$(printf "%s" "$python_version" | tr -d '.')
    printf "test-%s-%s-py%s" "$platform" "$arch_id" "$python_id"
}

current_package_name() {
    if [ -f pyproject.toml ]; then
        awk -F'"' '/^name =/ { print $2; exit }' pyproject.toml
    fi
}

require_template() {
    template=$1
    if [ ! -f "$template" ]; then
        echo "Missing CI template: $template" >&2
        exit 1
    fi
}

render_target_template() {
    rtt_template=$1
    rtt_job_id=$2
    rtt_platform=$3
    rtt_arch=$4
    rtt_runner=$5
    rtt_python_version=$6

    require_template "$rtt_template"
    awk \
        -v job_id="$rtt_job_id" \
        -v platform="$rtt_platform" \
        -v arch="$rtt_arch" \
        -v runner="$rtt_runner" \
        -v python_version="$rtt_python_version" \
        -v gitea_checkout_action="$GITEA_CHECKOUT_ACTION" '
        function replace_all(text, key, value,    pos) {
            while ((pos = index(text, key)) > 0) {
                text = substr(text, 1, pos - 1) value substr(text, pos + length(key))
            }
            return text
        }
        {
            line = $0
            line = replace_all(line, "{{JOB_ID}}", job_id)
            line = replace_all(line, "{{PLATFORM}}", platform)
            line = replace_all(line, "{{ARCH}}", arch)
            line = replace_all(line, "{{RUNNER}}", runner)
            line = replace_all(line, "{{PYTHON_VERSION}}", python_version)
            line = replace_all(line, "{{GITEA_CHECKOUT_ACTION}}", gitea_checkout_action)
            print line
        }
    ' "$rtt_template"
}

render_workflow_template() {
    rwt_template=$1
    rwt_output=$2
    rwt_matrix_block=$3
    rwt_gitea_jobs_block=$4
    rwt_gitea_needs_block=$5
    rwt_docker_job_block=$6
    rwt_package_name=$7

    require_template "$rwt_template"
    awk \
        -v matrix_block="$rwt_matrix_block" \
        -v gitea_jobs_block="$rwt_gitea_jobs_block" \
        -v gitea_needs_block="$rwt_gitea_needs_block" \
        -v docker_job_block="$rwt_docker_job_block" \
        -v package_name="$rwt_package_name" \
        -v internal_gitea_host="$INTERNAL_GITEA_HOST" \
        -v internal_pypi_index="$INTERNAL_PYPI_INDEX" \
        -v public_pypi_index="$PUBLIC_PYPI_INDEX" \
        -v act_pypi_index="$ACT_PYPI_INDEX" \
        -v python_install_mirror="$PYTHON_INSTALL_MIRROR" \
        -v gitea_checkout_action="$GITEA_CHECKOUT_ACTION" \
        -v github_checkout_action="$GITHUB_CHECKOUT_ACTION" \
        -v github_setup_uv_action="$GITHUB_SETUP_UV_ACTION" \
        -v github_release_action="$GITHUB_RELEASE_ACTION" '
        function print_file(file,    line) {
            if (file == "") {
                return
            }
            while ((getline line < file) > 0) {
                print line
            }
            close(file)
        }
        function replace_all(text, key, value,    pos) {
            while ((pos = index(text, key)) > 0) {
                text = substr(text, 1, pos - 1) value substr(text, pos + length(key))
            }
            return text
        }
        index($0, "{{COMPATIBILITY_MATRIX}}") > 0 {
            print_file(matrix_block)
            next
        }
        index($0, "{{COMPATIBILITY_JOBS}}") > 0 {
            print_file(gitea_jobs_block)
            next
        }
        index($0, "{{COMPATIBILITY_NEEDS}}") > 0 {
            print_file(gitea_needs_block)
            next
        }
        index($0, "{{DOCKER_CHECK_JOB}}") > 0 {
            print_file(docker_job_block)
            next
        }
        {
            line = replace_all($0, "{{PACKAGE_NAME}}", package_name)
            line = replace_all(line, "{{INTERNAL_GITEA_HOST}}", internal_gitea_host)
            line = replace_all(line, "{{INTERNAL_PYPI_INDEX}}", internal_pypi_index)
            line = replace_all(line, "{{PUBLIC_PYPI_INDEX}}", public_pypi_index)
            line = replace_all(line, "{{ACT_PYPI_INDEX}}", act_pypi_index)
            line = replace_all(line, "{{PYTHON_INSTALL_MIRROR}}", python_install_mirror)
            line = replace_all(line, "{{GITEA_CHECKOUT_ACTION}}", gitea_checkout_action)
            line = replace_all(line, "{{GITHUB_CHECKOUT_ACTION}}", github_checkout_action)
            line = replace_all(line, "{{GITHUB_SETUP_UV_ACTION}}", github_setup_uv_action)
            line = replace_all(line, "{{GITHUB_RELEASE_ACTION}}", github_release_action)
            print line
        }
    ' "$rwt_template" > "$rwt_output"
}

write_ci_matrix_block() {
    block_file=$1
    targets_text=$2
    python_versions_text=$3

    {
        echo "        include:"
        printf "%s\n" "$targets_text" | while IFS='|' read -r platform arch runner; do
            [ -n "$platform" ] || continue
            for python_version in $python_versions_text; do
                render_target_template "$CI_TEMPLATE_DIR/github-matrix-entry.yaml.tpl" "" "$platform" "$arch" "$runner" "$python_version"
            done
        done
    } > "$block_file"
}

write_gitea_jobs_block() {
    block_file=$1
    targets_text=$2
    python_versions_text=$3

    {
        printf "%s\n" "$targets_text" | while IFS='|' read -r platform arch runner; do
            [ -n "$platform" ] || continue
            for python_version in $python_versions_text; do
                job_id=$(job_id_for_target "$platform" "$arch" "$python_version")
                render_target_template "$CI_TEMPLATE_DIR/gitea-test-job.yaml.tpl" "$job_id" "$platform" "$arch" "$runner" "$python_version"
                echo
            done
        done
    } > "$block_file"
}

write_gitea_needs_block() {
    block_file=$1
    targets_text=$2
    python_versions_text=$3

    {
        printf "%s\n" "$targets_text" | while IFS='|' read -r platform arch runner; do
            [ -n "$platform" ] || continue
            for python_version in $python_versions_text; do
                job_id=$(job_id_for_target "$platform" "$arch" "$python_version")
                render_target_template "$CI_TEMPLATE_DIR/gitea-need-entry.yaml.tpl" "$job_id" "$platform" "$arch" "$runner" "$python_version"
            done
        done
    } > "$block_file"
}

write_docker_job_block() {
    block_file=$1
    workflow_type=$2

    : > "$block_file"
    [ -f Dockerfile ] || return 0

    case "$workflow_type" in
        gitea)
            snippet="$CI_TEMPLATE_DIR/docker-check.gitea.yaml"
            ;;
        github)
            snippet="$CI_TEMPLATE_DIR/docker-check.github.yaml"
            ;;
        *)
            echo "Unknown workflow type: $workflow_type" >&2
            exit 1
            ;;
    esac

    require_template "$snippet"
    render_action_template "$snippet" "$block_file"
}

write_ci_workflows() {
    matrix_block=$1
    gitea_jobs_block=$2
    gitea_needs_block=$3

    package_name=$(current_package_name)
    if [ -z "$package_name" ]; then
        echo "Cannot determine package name from pyproject.toml" >&2
        exit 1
    fi

    github_docker_block=$(mktemp)
    gitea_docker_block=$(mktemp)
    write_docker_job_block "$github_docker_block" github
    write_docker_job_block "$gitea_docker_block" gitea
    mkdir -p .github/workflows .gitea/workflows

    render_workflow_template \
        "$CI_TEMPLATE_DIR/github-ci.yaml.tpl" \
        ".github/workflows/ci.yaml" \
        "$matrix_block" \
        "" \
        "" \
        "$github_docker_block" \
        "$package_name"

    render_workflow_template \
        "$CI_TEMPLATE_DIR/gitea-ci.yaml.tpl" \
        ".gitea/workflows/ci.yaml" \
        "" \
        "$gitea_jobs_block" \
        "$gitea_needs_block" \
        "$gitea_docker_block" \
        "$package_name"

    rm -f "$github_docker_block" "$gitea_docker_block"
}
