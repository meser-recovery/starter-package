# S12 public dummy CI — isolated branch only

Local draft starts with collector/workflow gates false. Only the exact reviewed CI-only
enabling patch may open those two gates after a future publication/run grant; no production
S12 gate is opened. Actual gate values are visible in the reviewed source.
Only existing workflow347881817/path safety-baseline.yml, on an isolated non-main branch.
Main/default workflow and Pages main/root unchanged. No PR/merge, no main fallback.
Branch suffix is the exact reviewed Git tree SHA; context+checkout commit/tree/one-parent
checks bind the branch version, not arbitrary workflow inputs. No workflow inputs.
Public archive/inspector are fixed SHA and bytes. Only six runtime files are staged.
No production inputs, credentials, private paths, installs, Docker, sudo, services,
mounts, cache, OIDC, deployment environment or production network probes.
Do not execute locally; independent review and an exact future grant are required.
No application SIGKILL or retry. Managed runner timeout/cancel may forcibly stop processes;
unknown ownership, cancellation, missing artifacts/cleanup cannot establish live PASS.
Only report.json + SHA256SUMS may be uploaded; all data is public dummy evidence.
