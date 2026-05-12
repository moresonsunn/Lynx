# Security Policy

## Reporting Vulnerabilities

If you discover a security vulnerability in Lynx, please report it responsibly.

**Email:** Open a private issue or contact the maintainers directly through GitHub.

Do **not** open a public issue for security vulnerabilities.

## What to Include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if you have one)

We'll acknowledge reports within 48 hours and aim to release a fix promptly.

## Scope

This policy covers the Lynx application itself:

- FastAPI backend
- React frontend
- Docker image and entrypoint scripts
- Authentication and authorization logic

It does **not** cover:

- Vulnerabilities in upstream game servers (Minecraft, Steam games)
- Issues in third-party Docker images used by game servers
- Misconfiguration of the host environment

## Best Practices for Deployment

- **Change the default admin password** immediately after install
- **Set a unique `SECRET_KEY`** in production — don't use the default
- **Restrict CORS origins** — avoid `ALLOWED_ORIGIN_REGEX=.*` in production
- **Use HTTPS** — put Lynx behind a reverse proxy (Nginx, Caddy, Traefik) with TLS
- **Keep Docker updated** — Lynx relies on the Docker socket, so host security matters
- **Enable 2FA** for admin accounts
- **Review audit logs** periodically
