# add-ci-hook — generate a reviewable CI verification job

Generate a GitLab CI or Jenkins fragment from an explicit JSON contract. This
mode writes a fragment only; it does not modify a live CI file, trigger a
pipeline, configure a runner, or handle credentials.

## Procedure

1. Read the regression Makefile help, workflow, roadmap CI criterion, and
   existing CI configuration.
2. Copy `ci-spec.example.json`. Set provider, commands, runner tags/agent,
   timeout, variables, and artifacts. Commands must use the pipeline checkout;
   do not add an internal `git pull`.
3. Generate:

   ```bash
   python3 <skill-dir>/add-ci-hook/scripts/generate_ci.py \
     --spec <ci-spec.json> --out <ci-fragment>
   ```

4. Review site-specific EDA licensing, scheduler behavior, secret handling,
   timeout, artifact size, and cleanup.
5. Merge the fragment manually into `.gitlab-ci.yml` or `Jenkinsfile`.
6. Validate syntax and run the job on a real compiled runner before recording
   CI PASS.

Never place tokens, license strings, passwords, or private keys in the JSON
contract or generated fragment.
