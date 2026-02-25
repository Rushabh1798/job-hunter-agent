# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| `main`  | Yes       |

This project is pre-1.0. Only the latest commit on `main` receives security fixes.

## Reporting a Vulnerability

**Do not open a public issue for security vulnerabilities.**

Report vulnerabilities via [GitHub Security Advisories](https://github.com/rushabhthakkar/job-hunter-agent/security/advisories/new).

You will receive an acknowledgment within 48 hours. We will work with you to understand the issue and coordinate a fix before any public disclosure.

## In Scope

- Credential exposure (API keys, tokens leaking to logs or output files)
- SQL injection via user-supplied preferences text or resume content
- Arbitrary code execution through malicious PDF files or scraped HTML
- Path traversal via resume paths or output directory configuration
- Cross-site scripting via scraped content rendered in output files

## Out of Scope

- Denial of service via resource exhaustion (CPU, memory, disk from large resumes or many companies)
- Vulnerabilities in upstream dependencies (report these to the respective projects)
