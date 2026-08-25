#!/bin/csh
# csh/tcsh entry point. The setup implementation uses Bash arrays, [[ ]], and
# strict-mode semantics, so csh dispatches it explicitly instead of parsing it.
set script_dir = "$0:h"
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
exec "$bash_path" "$script_dir/setup.sh" $argv:q
