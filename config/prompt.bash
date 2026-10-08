# mise and the Oh My Posh prompt for interactive bash, sourced from ~/.bashrc by ./install.
# Debian and Ubuntu's ~/.profile adds ~/.local/bin, where ./bootstrap installs it, only after sourcing ~/.bashrc.
[[ $- == *i* ]] || return 0

# Let Oh My Posh display environments, before mise can activate one.
if PATH=$PATH:$HOME/.local/bin command -v oh-my-posh >/dev/null; then
    export VIRTUAL_ENV_DISABLE_PROMPT=1 CONDA_CHANGEPS1=false
fi

# Activate mise unless ~/.bashrc already did; child shells do not inherit its hook function.
if ! declare -F _mise_hook >/dev/null && dalftui_mise=$(PATH=$PATH:$HOME/.local/bin command -v mise); then
    eval "$("$dalftui_mise" activate bash)"
fi
unset dalftui_mise

PATH=$PATH:$HOME/.local/bin command -v oh-my-posh >/dev/null || return 0

eval "$(PATH=$PATH:$HOME/.local/bin oh-my-posh init bash --config "$(dirname "${BASH_SOURCE[0]}")/oh-my-posh.omp.json")"

# Export job counts for the theme (Oh My Posh calls this before each prompt).
# Define it after the init, which replaces it with an empty function.
set_poshcontext() {
    local running=($(jobs -rp)) stopped=($(jobs -sp))
    export OMP_JOBS_RUNNING=${#running[@]} OMP_JOBS_STOPPED=${#stopped[@]}
}
