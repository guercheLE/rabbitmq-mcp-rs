# RabbitMQ management API sources

This reference lists the official RabbitMQ management API index used to generate each OpenAPI document.
The source URL is suitable for automated downloads; the rendered URL opens the original HTML documentation in a browser.

| Version | Source HTML | Rendered index | OpenAPI |
| --- | --- | --- | --- |
| 4.3.2 | [source](https://raw.githubusercontent.com/rabbitmq/rabbitmq-server/v4.3.2/deps/rabbitmq_management/priv/www/api/index.html) | [view](https://rawcdn.githack.com/rabbitmq/rabbitmq-server/v4.3.2/deps/rabbitmq_management/priv/www/api/index.html) | [`rabbitmq-management-v4.3.2.openapi.yaml`](../openapi/rabbitmq-management-v4.3.2.openapi.yaml) |
| 4.2.8 | [source](https://raw.githubusercontent.com/rabbitmq/rabbitmq-server/v4.2.8/deps/rabbitmq_management/priv/www/api/index.html) | [view](https://rawcdn.githack.com/rabbitmq/rabbitmq-server/v4.2.8/deps/rabbitmq_management/priv/www/api/index.html) | [`rabbitmq-management-v4.2.8.openapi.yaml`](../openapi/rabbitmq-management-v4.2.8.openapi.yaml) |
| 4.1.8 | [source](https://raw.githubusercontent.com/rabbitmq/rabbitmq-server/v4.1.8/deps/rabbitmq_management/priv/www/api/index.html) | [view](https://rawcdn.githack.com/rabbitmq/rabbitmq-server/v4.1.8/deps/rabbitmq_management/priv/www/api/index.html) | [`rabbitmq-management-v4.1.8.openapi.yaml`](../openapi/rabbitmq-management-v4.1.8.openapi.yaml) |
| 4.0.9 | [source](https://raw.githubusercontent.com/rabbitmq/rabbitmq-server/v4.0.9/deps/rabbitmq_management/priv/www/api/index.html) | [view](https://rawcdn.githack.com/rabbitmq/rabbitmq-server/v4.0.9/deps/rabbitmq_management/priv/www/api/index.html) | [`rabbitmq-management-v4.0.9.openapi.yaml`](../openapi/rabbitmq-management-v4.0.9.openapi.yaml) |
| 3.13.7 | [source](https://raw.githubusercontent.com/rabbitmq/rabbitmq-server/v3.13.7/deps/rabbitmq_management/priv/www/api/index.html) | [view](https://rawcdn.githack.com/rabbitmq/rabbitmq-server/v3.13.7/deps/rabbitmq_management/priv/www/api/index.html) | [`rabbitmq-management-v3.13.7.openapi.yaml`](../openapi/rabbitmq-management-v3.13.7.openapi.yaml) |

## Regeneration

Run the generator from the repository root:

```bash
python3 scripts/generate_openapi.py
```

The base generator uses only the Python standard library. It downloads each supported source index, overwrites the matching file in `openapi/`, and removes stale files that match the generator's filename pattern.

## Runtime enrichment

When the Docker daemon is running, the generator starts each RabbitMQ version with `docker run --rm` and the disposable credentials `openapi_admin` / `openapi_admin_password`. It creates probe resources, exercises GET/PUT/POST/DELETE endpoints, opens the Management UI in headless Chrome, logs in, navigates management screens, and captures request URLs, non-sensitive headers, bodies, status codes, and JSON responses. The Management UI is the required source for the publish and get-message POST signatures. Direct API calls provide complementary observations and cleanup.

RabbitMQ 3.13.7 uses the pinned image `rabbitmq@sha256:9f65f155849158d312201e4ca0eee99724036ae3ec4c7ef30063967cf11735c8` from Docker Hub. Because that base image does not enable the web UI, the container startup enables `rabbitmq_management` offline before launching `rabbitmq-server` through the official entrypoint.

Observed schemas carry `x-rabbitmq-observed: true`; operations list observed statuses and sources. Runtime values and credentials are not persisted. Chrome or Chromium and Node.js are required when Docker is available. Use `--skip-runtime-enrichment` for an explicitly HTML-only generation.

## Conversion boundary

The source HTML does not provide formal JSON request or response schemas. The generator infers a schema only when a description contains a valid JSON example inside a `pre` block. A field is marked as required only when the surrounding prose explicitly calls it mandatory; inferred schemas carry `x-rabbitmq-inferred: true` and retain their source examples. Explicitly identified response examples are handled separately from request examples. Ambiguous, invalid, and undocumented payloads keep the generic `{}` schema. Validate application-specific payloads against the documentation and a RabbitMQ node running the same version.
