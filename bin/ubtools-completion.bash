# Emits completion definitions without editing shell configuration.
ub_completion() {
    case "${1:-}" in
        bash) cat <<'BASH'
_ub_complete() {
    local current="${COMP_WORDS[COMP_CWORD]}" choices=''
    if (( COMP_CWORD == 1 )); then
        choices='install remove update doctor clean mirror ai setup help completion'
    else
        case "${COMP_WORDS[1]}" in
            ai)
                if (( COMP_CWORD == 2 )); then choices='install update uninstall status doctor';
                else choices='codex claude opencode pi --all --dry-run --yes --latest --offline --timeout --help'; fi;;
            mirror)
                if (( COMP_CWORD == 2 )); then choices='test auto restore';
                else choices='--mirror --timeout --limit --dry-run --yes --json --force --help'; fi;;
            help) choices='install remove update doctor clean mirror ai setup';;
            setup) choices='zh en';;
            completion) choices='bash zsh fish';;
            install) choices='--apt --snap --flatpak --refresh --exact --help';;
            remove) choices='--exact --help';;
            update) choices='--apt --snap --flatpak --list --dry-run --refresh-index --exact --help';;
            doctor) choices='--apt --snap --flatpak --offline --timeout --help';;
            clean) choices='--apt --snap --flatpak --list --dry-run --exact --help';;
        esac
    fi
    mapfile -t COMPREPLY < <(compgen -W "$choices" -- "$current")
}
complete -F _ub_complete ub
BASH
            ;;
        zsh) cat <<'ZSH'
_ub_complete() {
    local -a choices
    if (( CURRENT == 2 )); then
        choices=(install remove update doctor clean mirror ai setup help completion)
    else
        case "$words[2]" in
            ai)
                if (( CURRENT == 3 )); then choices=(install update uninstall status doctor);
                else choices=(codex claude opencode pi --all --dry-run --yes --latest --offline --timeout --help); fi;;
            mirror)
                if (( CURRENT == 3 )); then choices=(test auto restore);
                else choices=(--mirror --timeout --limit --dry-run --yes --json --force --help); fi;;
            completion) choices=(bash zsh fish);;
            setup) choices=(zh en);;
            help) choices=(install remove update doctor clean mirror ai setup);;
            install) choices=(--apt --snap --flatpak --refresh --exact --help);;
            remove) choices=(--exact --help);;
            update) choices=(--apt --snap --flatpak --list --dry-run --refresh-index --exact --help);;
            doctor) choices=(--apt --snap --flatpak --offline --timeout --help);;
            clean) choices=(--apt --snap --flatpak --list --dry-run --exact --help);;
        esac
    fi
    compadd -- $choices
}
compdef _ub_complete ub
ZSH
            ;;
        fish) cat <<'FISH'
complete -c ub -f
complete -c ub -n '__fish_use_subcommand' -a 'install remove update doctor clean mirror ai setup help completion'
complete -c ub -n '__fish_seen_subcommand_from ai' -a 'install update uninstall status doctor codex claude opencode pi'
complete -c ub -n '__fish_seen_subcommand_from mirror' -a 'test auto restore'
complete -c ub -n '__fish_seen_subcommand_from completion' -a 'bash zsh fish'
complete -c ub -n '__fish_seen_subcommand_from setup' -a 'zh en'
complete -c ub -l help -d 'Show help'
complete -c ub -n '__fish_seen_subcommand_from install update doctor clean' -l apt
complete -c ub -n '__fish_seen_subcommand_from install update doctor clean' -l snap
complete -c ub -n '__fish_seen_subcommand_from install update doctor clean' -l flatpak
complete -c ub -n '__fish_seen_subcommand_from update clean ai mirror' -l dry-run
complete -c ub -n '__fish_seen_subcommand_from ai' -l all
FISH
            ;;
        *) echo 'Usage: ub completion bash|zsh|fish' >&2; return 2;;
    esac
}
