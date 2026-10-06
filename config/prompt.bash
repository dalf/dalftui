# Oh My Posh prompt for interactive bash, sourced from ~/.bashrc by ./install.
[[ $- == *i* ]] && command -v oh-my-posh >/dev/null || return 0

eval "$(oh-my-posh init bash --config "$(dirname "${BASH_SOURCE[0]}")/oh-my-posh.omp.json")"

# Export job counts for the theme (Oh My Posh calls this before each prompt).
# Define it after the init, which replaces it with an empty function.
set_poshcontext() {
    local running=($(jobs -rp)) stopped=($(jobs -sp))
    export OMP_JOBS_RUNNING=${#running[@]} OMP_JOBS_STOPPED=${#stopped[@]}
}
