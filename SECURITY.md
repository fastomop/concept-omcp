# Security policy

## Reporting a vulnerability

Please report security issues **privately**, not as public GitHub issues. Use GitHub's
[private vulnerability reporting](https://github.com/fastomop/concept-omcp/security/advisories/new)
("Report a vulnerability" under the repository's *Security* tab). Include a description,
affected version(s), reproduction steps, and impact.

## Supported versions

concept-omcp is pre-1.0 (`0.x`). Security fixes target the **latest released minor
version** only. Pin to a minor version and upgrade promptly when an advisory is published.

## Response targets

These are good-faith targets for a volunteer-maintained project, not contractual SLAs:

| Stage | Target |
| --- | --- |
| Acknowledge report | within 5 business days |
| Initial assessment | within 10 business days |
| Fix or mitigation for confirmed high-severity issues | as soon as practicable |

## Scope

In scope: the concept-omcp code — the MCP server and its tools, the `ConceptStore`
runtime, the build pipeline, the CLI, and the published container image.

Out of scope:

- **Vocabulary data and its licensing.** concept-omcp ships no vocabulary content; the
  OMOP vocabularies a user loads are governed by their own licences (see [NOTICE](NOTICE)).
  Licensing-compliance questions are not security vulnerabilities.
- **The MCP transport's authorization model.** Streamable HTTP / SSE transports are
  unauthenticated at the application layer (authorization is OPTIONAL in MCP). When
  exposing concept-omcp over a network, gate it at your reverse proxy. The default stdio
  transport runs as a local subprocess with no network surface.
- Vulnerabilities in third-party dependencies (report those upstream), though we will
  bump affected pins.

## Disclosure

We follow coordinated disclosure: we will work with you on a fix and a disclosure
timeline, and credit you in the advisory unless you prefer to remain anonymous.

## Thanks

We appreciate responsible disclosure and the time researchers spend improving the
safety of the OHDSI tooling ecosystem.
