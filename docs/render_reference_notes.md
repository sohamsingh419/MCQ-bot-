# Render deployment reference notes

The official Render Blueprint specification confirms that a Docker-based background worker is declared with `type: worker`, `runtime: docker`, and may use `dockerfilePath`; when omitted, Render uses the repository-root Dockerfile and its CMD. Environment variables may use `sync: false` for secrets or `fromDatabase` with `property: connectionString` for a managed Postgres database. A Blueprint file is normally named `render.yaml` at the repository root.

Sources:

- https://render.com/docs/blueprint-spec — Render Blueprint YAML Reference; Docker background workers, Dockerfile fields, `sync: false`, and `fromDatabase` syntax.
- https://render.com/docs/infrastructure-as-code — Render Blueprints setup, repository-root `render.yaml`, managed Postgres wiring, and deployment workflow.

These references were accessed on 2026-08-21 and should be rechecked if Render changes its Blueprint schema before deployment.
