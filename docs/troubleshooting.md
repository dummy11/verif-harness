# Troubleshooting

## Verilator is missing

Run `./scripts/setup.sh` for the diagnostic and install Verilator 5.x using the
method appropriate for the host. CI installs the Ubuntu package explicitly.

## A type is unknown during compilation

Check the canonical compile order. Packages and interfaces must precede their
consumers; assertion modules must precede bind files.

## The generator refuses to run

The generator is additive. Move to a clean output directory or review and
remove the exact generated targets yourself. It will not overwrite Human work.

## Public-release audit fails

Review the reported file and line. Replace private values with neutral data or
remove the artifact. Do not add exclusions merely to suppress a real finding.
When history contains sensitive data, create a new clean export or use an
organization-approved history-rewrite process before publication.

## Public CI passes but UVM fails locally

Public CI validates only the non-UVM example and structural checks. Compare the
commercial simulator version, UVM library, compile order, macros, and filelist.
