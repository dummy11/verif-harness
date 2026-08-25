#!/bin/csh -f
# csh/tcsh entry point. The setup implementation uses Bash arrays, [[ ]], and
# strict-mode semantics, so csh dispatches it explicitly instead of parsing it.
set script_dir = "$0:h"
set python_path = ""
if ( $?VERIF_HARNESS_PYTHON ) then
    set python_path = "$VERIF_HARNESS_PYTHON"
    if ( ! -x "$python_path" ) then
        set python_matches = (`where -p "$python_path"`)
        if ( $#python_matches > 0 ) set python_path = "$python_matches[1]"
    endif
endif
if ( "$python_path" == "" || ! -x "$python_path" ) then
    foreach python_candidate (python3 python3.13 python3.12 python3.11)
        set python_matches = (`where -p "$python_candidate"`)
        if ( $#python_matches > 0 ) then
            if ( -x "$python_matches[1]" ) then
                set python_path = "$python_matches[1]"
                break
            endif
        endif
    end
endif
if ( "$python_path" == "" || ! -x "$python_path" ) then
    /bin/sh -c 'printf "%s\n" "$1" >&2' sh \
        "ERROR: csh cannot resolve Python 3; set VERIF_HARNESS_PYTHON to an executable path."
    exit 2
endif
if ( ! -x "$script_dir/setup.sh" ) then
    /bin/sh -c 'printf "%s\n" "$1" >&2' sh \
        "ERROR: Bash setup implementation is missing: $script_dir/setup.sh"
    exit 2
endif
set bash_matches = (`where -p bash`)
set bash_path = ""
if ( $#bash_matches > 0 ) set bash_path = "$bash_matches[1]"
if ( "$bash_path" == "" ) then
    /bin/sh -c 'printf "%s\n" "$1" >&2' sh \
        "ERROR: verif-harness setup requires bash; it is not on PATH."
    exit 2
endif
setenv VERIF_HARNESS_PYTHON "$python_path"
exec "$bash_path" "$script_dir/setup.sh" $argv:q
