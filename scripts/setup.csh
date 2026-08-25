#!/bin/csh -f
# csh/tcsh entry point. The setup implementation uses Bash arrays, [[ ]], and
# strict-mode semantics, so csh dispatches it explicitly instead of parsing it.
set script_dir = "$0:h"
if ( ! -x "$script_dir/setup.sh" ) then
    echo "ERROR: Bash setup implementation is missing: $script_dir/setup.sh" >&2
    exit 2
endif
set bash_path = `which bash`
if ( "$bash_path" == "" ) then
    echo "ERROR: verif-harness setup requires bash; it is not on PATH." >&2
    exit 2
endif
exec "$bash_path" "$script_dir/setup.sh" $argv:q
