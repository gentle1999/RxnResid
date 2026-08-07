#!/usr/bin/env sh

render_action_template() {
    input_file=$1
    output_file=$2

    awk \
        -v gitea_checkout_action="$GITEA_CHECKOUT_ACTION" \
        -v github_checkout_action="$GITHUB_CHECKOUT_ACTION" '
        function replace_all(text, key, value,    pos) {
            while ((pos = index(text, key)) > 0) {
                text = substr(text, 1, pos - 1) value substr(text, pos + length(key))
            }
            return text
        }
        {
            line = replace_all($0, "{{GITEA_CHECKOUT_ACTION}}", gitea_checkout_action)
            line = replace_all(line, "{{GITHUB_CHECKOUT_ACTION}}", github_checkout_action)
            print line
        }
    ' "$input_file" > "$output_file"
}
