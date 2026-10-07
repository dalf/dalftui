# Oh My Posh prompt for interactive zsh, sourced from ~/.zshrc by ./install.
[[ -o interactive ]] && (( $+commands[oh-my-posh] )) || return 0

# ${(%):-%x} is this file, even when FUNCTION_ARGZERO is off.
eval "$(oh-my-posh init zsh --config "${${(%):-%x}:A:h}/oh-my-posh.omp.json")"

# Export job counts for the theme (Oh My Posh calls this before each prompt).
# Define it after the init, which replaces it with an empty function.
# zsh runs $(jobs) in a subshell without jobs, so count $jobstates instead.
zmodload zsh/parameter
set_poshcontext() {
    export OMP_JOBS_RUNNING=${#${(M)${(v)jobstates}:#running:*}} OMP_JOBS_STOPPED=${#${(M)${(v)jobstates}:#suspended:*}}
}
