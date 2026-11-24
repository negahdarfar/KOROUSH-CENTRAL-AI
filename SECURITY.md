# Security Policy

## Reporting a vulnerability

Do not open a public issue containing credentials, exploit details, or personal data.
Report suspected vulnerabilities privately to the repository owner through GitHub's
private vulnerability reporting feature when it is enabled.

## Operational security

- Keep provider keys, GitHub tokens, and admin credentials in Railway variables.
- Never commit secrets or paste them into issues, logs, or chat.
- Keep production deployments separate from draft pull requests.
- Require review and successful CI before merging changes to the production branch.
- Treat repository contents and model output as untrusted input.
- Rotate any credential suspected of exposure.
