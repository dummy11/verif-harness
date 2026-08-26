# oss-readiness — public-release audit

Run a read-only audit before copying code into a public repository and again
after every release candidate commit.

## Procedure

1. Confirm with a Human that the project has publication rights. Sanitization
   cannot establish ownership or permission.
2. Create a clean export; do not reuse a confidential repository's Git history.
3. Maintain `.github/public-release-denylist.txt` with one project-specific
   forbidden identifier per line.
4. Run:

   ```bash
   python3 <skill-dir>/oss-readiness/scripts/audit_oss_readiness.py \
     --require-community --history
   ```

5. Review every finding manually. Run secret-scanning tools approved by the
   publishing organization in addition to this structural audit.
6. Verify a fresh clone can execute the documented example without private
   dependencies.

## Boundary

A zero-finding result does not prove that content is non-confidential, grant
publication rights, select a license on behalf of an owner, or publish data.
