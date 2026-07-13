# rabbitmq-mcp-rs

Rust MCP server for the RabbitMQ management HTTP API.

## API specifications

This repository includes OpenAPI 3.1 documents for RabbitMQ 4.3.2, 4.2.8, 4.1.8, 4.0.9, and 3.13.7, generated from the official management API indexes. The generator conservatively infers input and output schemas from explicit JSON examples and marks them with `x-rabbitmq-inferred: true`; undocumented schemas remain generic.

- [Source index URLs and generation notes](docs/api-sources.md)
- [Generated OpenAPI specifications](openapi)

Regenerate every supported specification with:

```bash
python3 scripts/generate_openapi.py
```

If Docker is running, generation automatically starts disposable RabbitMQ containers, logs into each Management UI in headless Chrome, captures the app's API traffic, exercises controlled read/write calls, and enriches the OpenAPI schemas with runtime observations. Use `--skip-runtime-enrichment` for HTML-only generation.

RabbitMQ 3.13.7 is pinned to the Docker Hub digest `rabbitmq@sha256:9f65f155849158d312201e4ca0eee99724036ae3ec4c7ef30063967cf11735c8`. The base image is runnable with `docker run --rm`, but it does not enable the Management web UI by default, so the generator enables `rabbitmq_management` offline during container startup.
