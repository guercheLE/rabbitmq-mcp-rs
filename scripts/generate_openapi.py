#!/usr/bin/env python3
"""Generate OpenAPI 3.1 documents from RabbitMQ's management API index."""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable


VERSIONS = (
    "4.3.2",
    "4.2.8",
    "4.1.8",
    "4.0.9",
    "3.13.7",
)

SOURCE_URL = (
    "https://raw.githubusercontent.com/rabbitmq/rabbitmq-server/"
    "v{version}/deps/rabbitmq_management/priv/www/api/index.html"
)
RENDERED_URL = (
    "https://rawcdn.githack.com/rabbitmq/rabbitmq-server/"
    "v{version}/deps/rabbitmq_management/priv/www/api/index.html"
)
METHODS = ("get", "put", "delete", "post")
RUNTIME_USER = "openapi_admin"
RUNTIME_PASSWORD = "openapi_admin_password"
RABBITMQ_3_13_7_IMAGE = (
    "rabbitmq@sha256:9f65f155849158d312201e4ca0eee99724036ae3ec4c7ef30063967cf11735c8"
)
PROBE_VHOST = "openapi-probe"
PROBE_USER = "openapi-probe-user"
PROBE_EXCHANGE = "openapi-probe-exchange"
PROBE_QUEUE = "openapi-probe-queue"
PROBE_POLICY = "openapi-probe-policy"
PROBE_GLOBAL_PARAMETER = "openapi-probe-parameter"


class ReferenceTableParser(HTMLParser):
    """Extract table cells while retaining path parameters and line breaks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._cell_index = -1
        self._table_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag == "table":
            self._table_depth += 1
            if self._table_depth == 1:
                self._table = []
        elif tag == "tr" and self._table_depth == 1:
            self._row = []
            self._cell_index = -1
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []
            self._cell_index += 1
        elif tag == "br" and self._cell is not None:
            self._cell.append("\n")
        elif tag == "i" and self._cell is not None and self._cell_index == 4:
            self._cell.append("{")
        elif tag == "pre" and self._cell is not None:
            self._cell.append("\n[[PRE]]")
        elif tag == "code" and self._cell is not None:
            self._cell.append("[[CODE]]")
        elif tag in {"p", "li"} and self._cell is not None:
            self._cell.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "i" and self._cell is not None and self._cell_index == 4:
            self._cell.append("}")
        elif tag == "pre" and self._cell is not None:
            self._cell.append("[[/PRE]]\n")
        elif tag == "code" and self._cell is not None:
            self._cell.append("[[/CODE]]")
        elif tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            self._table.append(self._row)
            self._row = None
        elif tag == "table":
            if self._table_depth == 1 and self._table is not None:
                self.tables.append(self._table)
                self._table = None
            self._table_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def normalize_text(value: str) -> str:
    without_markers = re.sub(r"\[\[/?(?:PRE|CODE)\]\]", "", value)
    return re.sub(r"\s+", " ", html.unescape(without_markers)).strip()


def reference_rows(source: str) -> list[list[str]]:
    parser = ReferenceTableParser()
    parser.feed(source)
    for table in parser.tables:
        if not table:
            continue
        header = [normalize_text(cell).upper() for cell in table[0]]
        if header[:6] == ["GET", "PUT", "DELETE", "POST", "PATH", "DESCRIPTION"]:
            return table[1:]
    raise ValueError("RabbitMQ API reference table was not found")


def row_paths(path_cell: str) -> list[tuple[str, bool]]:
    paths: list[tuple[str, bool]] = []
    for line in path_cell.splitlines():
        deprecated = "deprecated" in line.lower()
        for match in re.finditer(r"/api/[A-Za-z0-9_./:{}-]*", line):
            path = match.group(0).rstrip(".,;:")
            if path:
                paths.append((path, deprecated))
    return paths


def operation_id(method: str, path: str) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", path)
    return method + "".join(part[:1].upper() + part[1:] for part in parts)


def summary(description: str) -> str:
    first = re.split(r"(?<=[.!?])\s+|\n", description, maxsplit=1)[0].strip()
    if len(first) <= 140:
        return first
    return first[:137].rstrip() + "..."


def tag_for(path: str) -> str:
    segments = [segment for segment in path.split("/") if segment and segment != "api"]
    if not segments:
        return "management"
    return re.sub(r"[{}]", "", segments[0]) or "management"


def json_examples(raw_description: str) -> list[tuple[str, Any]]:
    """Return explicitly classifiable JSON examples from description pre blocks."""

    examples: list[tuple[str, Any]] = []
    previous_end = 0
    previous_kind: str | None = None
    for match in re.finditer(r"\[\[PRE\]\](.*?)\[\[/PRE\]\]", raw_description, re.DOTALL):
        try:
            value = json.loads(match.group(1).strip())
        except (json.JSONDecodeError, TypeError):
            previous_end = match.end()
            continue

        context = normalize_text(raw_description[previous_end : match.start()])
        context_lower = context.lower()
        if re.search(
            r"\bresponse\b.{0,100}\b(?:look|looks|contain|contains|example|body)\b|\bresponds?\s+with\b",
            context_lower,
        ):
            kind = "response"
        elif re.search(
            r"\brequest body\b|\b(?:need|provide|post|put|upload)\b.{0,80}\bbody\b|"
            r"\bbody\b.{0,50}\b(?:look|looking|like|required|must|should)\b|\bpayload\b",
            context_lower,
        ):
            kind = "request"
        elif previous_kind and re.fullmatch(r"(?:or\s*:?)?", context_lower):
            kind = previous_kind
        else:
            kind = "unknown"

        examples.append((kind, value))
        previous_kind = kind
        previous_end = match.end()
    return examples


def explicit_key_rules(raw_description: str, properties: Iterable[str]) -> list[str]:
    """Infer required keys only from explicit mandatory/optional statements."""

    property_order = list(properties)
    marked = re.sub(r"\s+", " ", raw_description)
    mandatory: set[str] = set()
    optional: set[str] = set()
    rule_pattern = re.compile(r"\b(mandatory|optional)\b", re.IGNORECASE)
    for rule in rule_pattern.finditer(marked):
        boundary = max(
            marked.rfind(".", 0, rule.start()),
            marked.rfind(";", 0, rule.start()),
            marked.rfind(",", 0, rule.start()),
        )
        clause = marked[boundary + 1 : rule.start()]
        names = re.findall(r"\[\[CODE\]\](.*?)\[\[/CODE\]\]", clause)
        target = mandatory if rule.group(1).lower() == "mandatory" else optional
        target.update(normalize_text(name) for name in names)

    prose = normalize_text(raw_description).lower()
    if re.search(r"\ball (?:the )?other keys are mandatory\b", prose):
        required = [name for name in property_order if name not in optional]
    elif re.search(r"\ball keys are mandatory\b", prose):
        required = property_order
    elif re.search(r"\ball keys are optional\b", prose):
        required = []
    else:
        required = [name for name in property_order if name in mandatory]
    return required


def inferred_schema(value: Any, required: Iterable[str] = (), *, mark_inferred: bool = True) -> OrderedDict[str, Any]:
    schema: OrderedDict[str, Any] = OrderedDict()
    if isinstance(value, dict):
        schema["type"] = "object"
        if value:
            schema["properties"] = OrderedDict(
                (name, inferred_schema(item, mark_inferred=False)) for name, item in value.items()
            )
            required_set = set(required)
            required_in_order = [name for name in value if name in required_set]
            if required_in_order:
                schema["required"] = required_in_order
        else:
            schema["additionalProperties"] = True
    elif isinstance(value, list):
        schema["type"] = "array"
        if value:
            item_schemas = [inferred_schema(item, mark_inferred=False) for item in value]
            schema["items"] = item_schemas[0] if all(item == item_schemas[0] for item in item_schemas) else OrderedDict(
                (("oneOf", item_schemas),)
            )
        else:
            schema["items"] = OrderedDict()
    elif isinstance(value, bool):
        schema["type"] = "boolean"
    elif isinstance(value, int):
        schema["type"] = "integer"
    elif isinstance(value, float):
        schema["type"] = "number"
    elif isinstance(value, str):
        schema["type"] = "string"
    elif value is None:
        schema["type"] = ["null"]
    else:
        raise TypeError(f"unsupported JSON example type: {type(value).__name__}")

    if mark_inferred:
        schema["x-rabbitmq-inferred"] = True
    return schema


def _schema_without_evidence_markers(value: Any) -> OrderedDict[str, Any]:
    schema = inferred_schema(value, mark_inferred=False)
    schema.pop("required", None)
    return schema


def _merge_schema(left: dict[str, Any], right: dict[str, Any]) -> OrderedDict[str, Any]:
    if not left:
        return OrderedDict(right)
    if not right:
        return OrderedDict(left)
    if left.get("type") == right.get("type") == "object":
        merged = OrderedDict(left)
        properties = OrderedDict(left.get("properties", {}))
        for name, schema in right.get("properties", {}).items():
            properties[name] = _merge_schema(properties[name], schema) if name in properties else OrderedDict(schema)
        if properties:
            merged["properties"] = properties
        if left.get("additionalProperties") or right.get("additionalProperties"):
            merged["additionalProperties"] = True
        return merged
    if left.get("type") == right.get("type") == "array":
        merged = OrderedDict(left)
        merged["items"] = _merge_schema(left.get("items", {}), right.get("items", {}))
        return merged
    if left == right:
        return OrderedDict(left)

    variants = []
    for candidate in (left, right):
        candidate_variants = candidate.get("oneOf") if set(candidate) == {"oneOf"} else [candidate]
        for variant in candidate_variants:
            if variant not in variants:
                variants.append(OrderedDict(variant))
    return OrderedDict((("oneOf", variants),))


def match_openapi_path(paths: dict[str, Any], observed_path: str) -> str | None:
    path = urllib.parse.urlsplit(observed_path).path.rstrip("/") or "/"
    candidates = []
    for template in paths:
        normalized = template.rstrip("/") or "/"
        pattern = re.sub(r"\{[^{}]+\}", r"[^/]+", re.escape(normalized).replace(r"\{", "{").replace(r"\}", "}"))
        if re.fullmatch(pattern, path):
            static_length = len(re.sub(r"\{[^{}]+\}", "", normalized))
            candidates.append((static_length, template))
    return max(candidates, default=(0, None))[1]


def enrich_with_observations(
    document: dict[str, Any],
    observations: Iterable[dict[str, Any]],
    version: str,
) -> None:
    observed_operations: set[tuple[str, str]] = set()
    used_observations = 0
    for observation in observations:
        template = match_openapi_path(document.get("paths", {}), observation.get("path", ""))
        method = str(observation.get("method", "")).lower()
        if not template or method not in document["paths"][template]:
            continue
        operation = document["paths"][template][method]
        status = int(observation["status"])
        source = str(observation.get("source", "direct"))
        observed_operations.add((method, template))
        used_observations += 1

        statuses = set(operation.get("x-rabbitmq-observed-statuses", []))
        statuses.add(status)
        operation["x-rabbitmq-observed-statuses"] = sorted(statuses)
        sources = set(operation.get("x-rabbitmq-observed-sources", []))
        sources.add(source)
        operation["x-rabbitmq-observed-sources"] = sorted(sources)

        parameters = operation.setdefault("parameters", [])
        existing_parameters = {
            (parameter.get("in"), str(parameter.get("name", "")).lower())
            for parameter in parameters
        }
        query = urllib.parse.parse_qs(
            urllib.parse.urlsplit(str(observation.get("path", ""))).query,
            keep_blank_values=True,
        )
        for name in query:
            key = ("query", name.lower())
            if key not in existing_parameters:
                parameters.append(
                    OrderedDict(
                        (
                            ("name", name),
                            ("in", "query"),
                            ("required", False),
                            ("schema", OrderedDict((("type", "string"),))),
                            ("x-rabbitmq-observed", True),
                        )
                    )
                )
                existing_parameters.add(key)

        ignored_headers = {
            "accept",
            "accept-encoding",
            "authorization",
            "connection",
            "content-length",
            "content-type",
            "cookie",
            "host",
            "origin",
            "referer",
            "user-agent",
        }
        for name in observation.get("requestHeaders", {}):
            lower_name = name.lower()
            key = ("header", lower_name)
            if lower_name in ignored_headers or lower_name.startswith("sec-") or key in existing_parameters:
                continue
            parameters.append(
                OrderedDict(
                    (
                        ("name", name),
                        ("in", "header"),
                        ("required", False),
                        ("schema", OrderedDict((("type", "string"),))),
                        ("x-rabbitmq-observed", True),
                    )
                )
            )
            existing_parameters.add(key)
        if not parameters:
            operation.pop("parameters", None)

        request_value = observation.get("request")
        if request_value is not None and method in {"put", "post"}:
            request_body = operation.setdefault("requestBody", OrderedDict())
            content = request_body.setdefault("content", OrderedDict())
            media = content.setdefault("application/json", OrderedDict((("schema", OrderedDict()),)))
            observed_schema = _schema_without_evidence_markers(request_value)
            media["schema"] = _merge_schema(media.get("schema", {}), observed_schema)
            media["schema"]["x-rabbitmq-observed"] = True

        response = operation.setdefault("responses", OrderedDict()).setdefault(
            str(status),
            OrderedDict((("description", "Response observed from a disposable RabbitMQ container."),)),
        )
        response_value = observation.get("response")
        if response_value is not None:
            content = response.setdefault("content", OrderedDict())
            media = content.setdefault("application/json", OrderedDict((("schema", OrderedDict()),)))
            observed_schema = _schema_without_evidence_markers(response_value)
            media["schema"] = _merge_schema(media.get("schema", {}), observed_schema)
            media["schema"]["x-rabbitmq-observed"] = True

    document["x-rabbitmq-runtime-enrichment"] = OrderedDict(
        (
            ("rabbitmqVersion", version),
            ("sources", ["browser", "direct"]),
            ("observedOperations", len(observed_operations)),
            ("observationsUsed", used_observations),
        )
    )


def media_type_from_examples(
    values: list[Any],
    raw_description: str,
    *,
    infer_required: bool,
) -> OrderedDict[str, Any]:
    schemas = []
    for value in values:
        required = explicit_key_rules(raw_description, value.keys()) if infer_required and isinstance(value, dict) else []
        schemas.append(inferred_schema(value, required))

    if len(schemas) == 1:
        schema = schemas[0]
    else:
        for candidate in schemas:
            candidate.pop("x-rabbitmq-inferred", None)
        schema = OrderedDict((("oneOf", schemas), ("x-rabbitmq-inferred", True)))

    media: OrderedDict[str, Any] = OrderedDict((("schema", schema),))
    if len(values) == 1:
        media["example"] = values[0]
    else:
        media["examples"] = OrderedDict(
            (f"example{index}", OrderedDict((("value", value),)))
            for index, value in enumerate(values, start=1)
        )
    return media


def make_operation(
    method: str,
    path: str,
    description: str,
    raw_description: str,
    deprecated: bool,
) -> OrderedDict[str, Any]:
    operation: OrderedDict[str, Any] = OrderedDict()
    operation["tags"] = [tag_for(path)]
    operation["summary"] = summary(description) or f"{method.upper()} {path}"
    operation["description"] = description or "No description is present in the source index."
    operation["operationId"] = operation_id(method, path)
    if deprecated:
        operation["deprecated"] = True

    parameters = []
    for name in dict.fromkeys(re.findall(r"{([^{}]+)}", path)):
        parameters.append(
            OrderedDict(
                (
                    ("name", name),
                    ("in", "path"),
                    ("required", True),
                    ("schema", OrderedDict((("type", "string"),))),
                )
            )
        )
    if parameters:
        operation["parameters"] = parameters

    examples = json_examples(raw_description)
    request_examples = [value for kind, value in examples if kind == "request"]
    response_examples = [value for kind, value in examples if kind == "response"]

    if method in {"put", "post"}:
        content: OrderedDict[str, Any] = OrderedDict(
            (("application/json", OrderedDict((("schema", OrderedDict()),))),)
        )
        if request_examples:
            content["application/json"] = media_type_from_examples(
                request_examples,
                raw_description,
                infer_required=True,
            )
        if "multipart/form-data" in description:
            content["multipart/form-data"] = OrderedDict((("schema", OrderedDict()),))
        operation["requestBody"] = OrderedDict(
            (
                (
                    "description",
                    "Request payload. Consult the operation description and RabbitMQ version-specific documentation for required fields.",
                ),
                ("required", False),
                ("content", content),
            )
        )

    operation["responses"] = OrderedDict(
        (
            ("2XX", OrderedDict((("description", "Successful response."),))),
            ("4XX", OrderedDict((("description", "Client error."),))),
            ("5XX", OrderedDict((("description", "RabbitMQ server error."),))),
        )
    )
    if response_examples:
        operation["responses"]["2XX"]["content"] = OrderedDict(
            (
                (
                    "application/json",
                    media_type_from_examples(response_examples, raw_description, infer_required=False),
                ),
            )
        )
    return operation


def build_openapi(source: str, version: str, source_url: str) -> OrderedDict[str, Any]:
    paths: OrderedDict[str, Any] = OrderedDict()
    for row in reference_rows(source):
        if len(row) < 6:
            continue
        raw_description = row[5]
        description = normalize_text(raw_description)
        for path, deprecated in row_paths(row[4]):
            path_item = paths.setdefault(path, OrderedDict())
            for index, method in enumerate(METHODS):
                if normalize_text(row[index]).upper() != "X":
                    continue
                if method in path_item:
                    raise ValueError(f"duplicate operation: {method.upper()} {path}")
                path_item[method] = make_operation(method, path, description, raw_description, deprecated)

    if not paths:
        raise ValueError("no API paths were extracted")

    document: OrderedDict[str, Any] = OrderedDict()
    document["openapi"] = "3.1.0"
    document["info"] = OrderedDict(
        (
            ("title", "RabbitMQ Management HTTP API"),
            ("version", version),
            (
                "description",
                "Generated from the RabbitMQ management plugin API index. "
                "Schemas are inferred conservatively from valid JSON examples and explicit field requirement prose. "
                "Schemas without sufficient source evidence remain intentionally generic.",
            ),
        )
    )
    document["externalDocs"] = OrderedDict(
        (("description", "RabbitMQ management API index used to generate this document."), ("url", source_url))
    )
    document["servers"] = [
        OrderedDict(
            (
                ("url", "http://localhost:15672"),
                ("description", "Default local RabbitMQ management endpoint."),
            )
        )
    ]
    document["security"] = [OrderedDict((("basicAuth", []),))]
    document["paths"] = paths
    document["components"] = OrderedDict(
        (
            (
                "securitySchemes",
                OrderedDict(
                    (
                        (
                            "basicAuth",
                            OrderedDict((("type", "http"), ("scheme", "basic"))),
                        ),
                    )
                ),
            ),
        )
    )
    document["x-rabbitmq-version"] = version
    document["x-generated-from"] = source_url
    return document


def validate_document(document: dict[str, Any]) -> None:
    if document.get("openapi") != "3.1.0":
        raise ValueError("the generated document is not OpenAPI 3.1.0")

    operation_ids: set[str] = set()
    for path, path_item in document.get("paths", {}).items():
        if not path.startswith("/api/"):
            raise ValueError(f"unexpected management API path: {path}")
        expected_parameters = set(re.findall(r"{([^{}]+)}", path))
        for method, operation in path_item.items():
            if method not in METHODS:
                raise ValueError(f"unexpected HTTP method: {method} {path}")
            operation_id_value = operation.get("operationId")
            if not operation_id_value or operation_id_value in operation_ids:
                raise ValueError(f"missing or duplicate operationId: {operation_id_value}")
            operation_ids.add(operation_id_value)
            actual_parameters = {
                parameter["name"]
                for parameter in operation.get("parameters", [])
                if parameter.get("in") == "path" and parameter.get("required") is True
            }
            if actual_parameters != expected_parameters:
                raise ValueError(
                    f"path parameter mismatch for {method.upper()} {path}: "
                    f"expected {sorted(expected_parameters)}, got {sorted(actual_parameters)}"
                )
            if "responses" not in operation:
                raise ValueError(f"responses are missing for {method.upper()} {path}")


def scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def yaml_lines(value: Any, indent: int = 0) -> Iterable[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        if not value:
            yield prefix + "{}"
            return
        for key, item in value.items():
            quoted_key = json.dumps(str(key), ensure_ascii=False)
            if isinstance(item, (dict, list)) and item:
                yield f"{prefix}{quoted_key}:"
                yield from yaml_lines(item, indent + 2)
            elif isinstance(item, (dict, list)):
                yield f"{prefix}{quoted_key}: {'{}' if isinstance(item, dict) else '[]'}"
            else:
                yield f"{prefix}{quoted_key}: {scalar(item)}"
    elif isinstance(value, list):
        if not value:
            yield prefix + "[]"
            return
        for item in value:
            if isinstance(item, (dict, list)) and item:
                yield prefix + "-"
                yield from yaml_lines(item, indent + 2)
            elif isinstance(item, (dict, list)):
                yield prefix + ("- {}" if isinstance(item, dict) else "- []")
            else:
                yield prefix + "- " + scalar(item)
    else:
        yield prefix + scalar(value)


def dump_yaml(document: dict[str, Any]) -> str:
    return "\n".join(yaml_lines(document)) + "\n"


def download(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "rabbitmq-mcp-rs-openapi-generator"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8")
    except urllib.error.URLError as error:
        raise RuntimeError(f"could not download {url}: {error}") from error


def docker_is_running(*, runner: Any = subprocess.run) -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = runner(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def parse_docker_port(output: str) -> int:
    match = re.search(r":(\d+)\s*$", output.strip())
    if not match:
        raise ValueError(f"could not parse Docker port mapping: {output!r}")
    return int(match.group(1))


def call_management_api(
    base_url: str,
    method: str,
    path: str,
    body: Any | None,
    *,
    username: str = RUNTIME_USER,
    password: str = RUNTIME_PASSWORD,
    opener: Any = urllib.request.urlopen,
    timeout: float = 15,
) -> dict[str, Any]:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    credentials = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    headers = {"Accept": "application/json", "Authorization": f"Basic {credentials}"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/")),
        data=payload,
        headers=headers,
        method=method,
    )

    try:
        response_context = opener(request, timeout=timeout)
        with response_context as response:
            status = response.status
            response_headers = dict(response.headers.items()) if hasattr(response.headers, "items") else dict(response.headers)
            raw = response.read()
    except urllib.error.HTTPError as error:
        status = error.code
        response_headers = dict(error.headers.items()) if error.headers else {}
        raw = error.read()

    response_value: Any | None = None
    if raw:
        text = raw.decode("utf-8", errors="replace")
        content_type = response_headers.get("Content-Type", response_headers.get("content-type", ""))
        if "json" in content_type.lower() or text.lstrip().startswith(("{", "[")):
            try:
                response_value = json.loads(text)
            except json.JSONDecodeError:
                response_value = None

    return {
        "source": "direct",
        "method": method.upper(),
        "path": path,
        "status": status,
        "request": body,
        "response": response_value,
        "headers": response_headers,
    }


def probe_seed_steps() -> list[tuple[str, str, Any | None]]:
    vhost = urllib.parse.quote(PROBE_VHOST, safe="")
    user = urllib.parse.quote(PROBE_USER, safe="")
    exchange = urllib.parse.quote(PROBE_EXCHANGE, safe="")
    queue = urllib.parse.quote(PROBE_QUEUE, safe="")
    policy = urllib.parse.quote(PROBE_POLICY, safe="")
    parameter = urllib.parse.quote(PROBE_GLOBAL_PARAMETER, safe="")
    return [
        ("GET", "/api/overview", None),
        ("GET", "/api/nodes", None),
        ("GET", "/api/feature-flags", None),
        ("PUT", "/api/cluster-name", {"name": "rabbitmq-openapi-probe"}),
        ("PUT", f"/api/vhosts/{vhost}", {"description": "OpenAPI runtime probe", "tags": "openapi"}),
        (
            "PUT",
            f"/api/users/{user}",
            {"password": "runtime-probe-password", "tags": "management"},
        ),
        (
            "PUT",
            f"/api/permissions/{vhost}/{user}",
            {"configure": ".*", "write": ".*", "read": ".*"},
        ),
        (
            "PUT",
            f"/api/exchanges/{vhost}/{exchange}",
            {"type": "direct", "auto_delete": False, "durable": False, "internal": False, "arguments": {}},
        ),
        (
            "PUT",
            f"/api/queues/{vhost}/{queue}",
            {"auto_delete": False, "durable": True, "arguments": {}},
        ),
        (
            "POST",
            f"/api/bindings/{vhost}/e/{exchange}/q/{queue}",
            {"routing_key": "openapi", "arguments": {}},
        ),
        (
            "PUT",
            f"/api/policies/{vhost}/{policy}",
            {"pattern": f"^{re.escape(PROBE_QUEUE)}$", "definition": {"max-length": 100}, "priority": 0, "apply-to": "queues"},
        ),
        (
            "PUT",
            f"/api/global-parameters/{parameter}",
            {"name": PROBE_GLOBAL_PARAMETER, "value": {"source": "openapi-probe"}},
        ),
        (
            "POST",
            f"/api/exchanges/{vhost}/{exchange}/publish",
            {"properties": {}, "routing_key": "openapi", "payload": "runtime probe", "payload_encoding": "string"},
        ),
        (
            "POST",
            f"/api/queues/{vhost}/{queue}/get",
            {"count": 1, "ackmode": "ack_requeue_false", "encoding": "auto", "truncate": 50000},
        ),
        ("GET", "/api/cluster-name", None),
        ("GET", "/api/extensions", None),
        ("GET", "/api/definitions", None),
        ("GET", "/api/connections", None),
        ("GET", "/api/channels", None),
        ("GET", "/api/consumers", None),
        ("GET", "/api/exchanges", None),
        ("GET", f"/api/exchanges/{vhost}/{exchange}", None),
        ("GET", "/api/queues", None),
        ("GET", f"/api/queues/{vhost}/{queue}", None),
        ("GET", f"/api/queues/{vhost}/{queue}/bindings", None),
        ("GET", "/api/bindings", None),
        ("GET", f"/api/bindings/{vhost}/e/{exchange}/q/{queue}", None),
        ("GET", "/api/vhosts", None),
        ("GET", f"/api/vhosts/{vhost}", None),
        ("GET", "/api/users", None),
        ("GET", f"/api/users/{user}", None),
        ("GET", "/api/permissions", None),
        ("GET", f"/api/permissions/{vhost}/{user}", None),
        ("GET", "/api/global-parameters", None),
        ("GET", f"/api/global-parameters/{parameter}", None),
        ("GET", "/api/policies", None),
        ("GET", f"/api/policies/{vhost}/{policy}", None),
        ("GET", "/api/operator-policies", None),
        ("GET", "/api/health/checks/alarms", None),
        ("GET", "/api/whoami", None),
        ("GET", "/api/auth", None),
        ("GET", "/api/deprecated-features", None),
        ("DELETE", f"/api/queues/{vhost}/{queue}/contents", None),
        ("DELETE", f"/api/policies/{vhost}/{policy}", None),
        ("DELETE", f"/api/queues/{vhost}/{queue}", None),
        ("DELETE", f"/api/exchanges/{vhost}/{exchange}", None),
        ("DELETE", f"/api/permissions/{vhost}/{user}", None),
        ("DELETE", f"/api/users/{user}", None),
        ("DELETE", f"/api/vhosts/{vhost}", None),
        ("DELETE", f"/api/global-parameters/{parameter}", None),
    ]


def _run_probe_steps(
    base_url: str,
    steps: Iterable[tuple[str, str, Any | None]],
) -> list[dict[str, Any]]:
    observations = []
    for method, path, body in steps:
        try:
            observation = call_management_api(base_url, method, path, body)
        except (OSError, urllib.error.URLError) as error:
            print(f"warning: {method} {path} failed: {error}", file=sys.stderr)
            continue
        observations.append(observation)
        if observation["status"] >= 400:
            print(
                f"warning: {method} {path} returned HTTP {observation['status']}",
                file=sys.stderr,
            )
    return observations


def _find_chrome() -> str:
    candidates = (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    )
    for candidate in candidates:
        resolved = shutil.which(candidate) if "/" not in candidate else candidate
        if resolved and Path(resolved).exists():
            return str(resolved)
    raise RuntimeError("Chrome or Chromium is required for RabbitMQ Management UI capture")


def capture_browser_observations(base_url: str) -> list[dict[str, Any]]:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required for Chrome DevTools Protocol capture")
    chrome = _find_chrome()
    helper = Path(__file__).with_name("capture_management_api.mjs")
    if not helper.exists():
        raise RuntimeError(f"browser capture helper is missing: {helper}")

    with tempfile.TemporaryDirectory(prefix="rabbitmq-openapi-chrome-") as profile:
        process = subprocess.Popen(
            [
                chrome,
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-sandbox",
                "--remote-allow-origins=*",
                "--remote-debugging-port=0",
                f"--user-data-dir={profile}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            active_port = Path(profile) / "DevToolsActivePort"
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and not active_port.exists():
                if process.poll() is not None:
                    raise RuntimeError("Chrome exited before exposing its DevTools endpoint")
                time.sleep(0.1)
            if not active_port.exists():
                raise RuntimeError("Chrome DevTools endpoint did not become ready")
            port = int(active_port.read_text(encoding="utf-8").splitlines()[0])
            environment = os.environ.copy()
            environment.update(
                {
                    "RABBITMQ_CDP_URL": f"http://127.0.0.1:{port}",
                    "RABBITMQ_BASE_URL": base_url,
                    "RABBITMQ_RUNTIME_USER": RUNTIME_USER,
                    "RABBITMQ_RUNTIME_PASSWORD": RUNTIME_PASSWORD,
                }
            )
            result = subprocess.run(
                [node, helper],
                capture_output=True,
                text=True,
                env=environment,
                timeout=120,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(f"browser capture failed: {result.stderr.strip()}")
            observations = json.loads(result.stdout)
            if not isinstance(observations, list):
                raise RuntimeError("browser capture did not return an observation list")
            return observations
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def validate_browser_post_observations(observations: Iterable[dict[str, Any]]) -> None:
    required = {
        f"/api/exchanges/{PROBE_VHOST}/{PROBE_EXCHANGE}/publish",
        f"/api/queues/{PROBE_VHOST}/{PROBE_QUEUE}/get",
    }
    captured = {
        urllib.parse.urlsplit(str(observation.get("path", ""))).path
        for observation in observations
        if str(observation.get("method", "")).upper() == "POST"
    }
    missing = required - captured
    if missing:
        diagnostics = [
            observation.get("diagnostics")
            for observation in observations
            if observation.get("source") == "browser-diagnostic"
        ]
        raise RuntimeError(
            "Management UI did not expose the required POST signatures: "
            + ", ".join(sorted(missing))
            + f"; browser diagnostics: {json.dumps(diagnostics, ensure_ascii=False)}"
        )


def _wait_for_management_api(base_url: str) -> None:
    deadline = time.monotonic() + 90
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            observation = call_management_api(base_url, "GET", "/api/overview", None, timeout=3)
            if 200 <= observation["status"] < 300:
                return
        except (OSError, urllib.error.URLError) as error:
            last_error = error
        time.sleep(1)
    raise RuntimeError(f"RabbitMQ management API did not become ready: {last_error}")


def runtime_container_configuration(version: str) -> dict[str, Any]:
    if version == "3.13.7":
        return {
            "image": RABBITMQ_3_13_7_IMAGE,
            "docker_options": ["--entrypoint", "bash"],
            "command": [
                "-lc",
                "rabbitmq-plugins enable --offline rabbitmq_management "
                "&& exec docker-entrypoint.sh rabbitmq-server",
            ],
        }
    return {
        "image": f"rabbitmq:{version}-management",
        "docker_options": [],
        "command": [],
    }


def collect_runtime_observations(version: str) -> list[dict[str, Any]]:
    container_name = f"rabbitmq-openapi-{version.replace('.', '-')}-{os.getpid()}"
    configuration = runtime_container_configuration(version)
    image = configuration["image"]
    run = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-d",
            "--name",
            container_name,
            "-p",
            "127.0.0.1::15672",
            "-e",
            f"RABBITMQ_DEFAULT_USER={RUNTIME_USER}",
            "-e",
            f"RABBITMQ_DEFAULT_PASS={RUNTIME_PASSWORD}",
            *configuration["docker_options"],
            image,
            *configuration["command"],
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if run.returncode != 0:
        raise RuntimeError(f"docker run failed for {image}: {run.stderr.strip()}")

    observations: list[dict[str, Any]] = []
    steps = probe_seed_steps()
    first_delete = next(index for index, step in enumerate(steps) if step[0] == "DELETE")
    active_steps = steps[:first_delete]
    cleanup_steps = steps[first_delete:]
    try:
        port_result = subprocess.run(
            ["docker", "port", container_name, "15672/tcp"],
            capture_output=True,
            text=True,
            check=True,
        )
        port = parse_docker_port(port_result.stdout)
        base_url = f"http://127.0.0.1:{port}"
        _wait_for_management_api(base_url)
        observations.extend(_run_probe_steps(base_url, active_steps))
        browser_observations = capture_browser_observations(base_url)
        validate_browser_post_observations(browser_observations)
        observations.extend(browser_observations)

        binding_path = (
            f"/api/bindings/{urllib.parse.quote(PROBE_VHOST, safe='')}/e/"
            f"{urllib.parse.quote(PROBE_EXCHANGE, safe='')}/q/{urllib.parse.quote(PROBE_QUEUE, safe='')}"
        )
        binding_lists = [
            observation["response"]
            for observation in observations
            if observation.get("method") == "GET" and observation.get("path") == binding_path
        ]
        for bindings in binding_lists:
            if isinstance(bindings, list) and bindings:
                properties_key = bindings[0].get("properties_key")
                if properties_key is not None:
                    encoded = urllib.parse.quote(str(properties_key), safe="")
                    observations.extend(_run_probe_steps(base_url, [("DELETE", f"{binding_path}/{encoded}", None)]))
                    break
        observations.extend(_run_probe_steps(base_url, cleanup_steps))
        return observations
    finally:
        subprocess.run(
            ["docker", "stop", "--timeout", "10", container_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


def prune_generated_files(output_dir: Path, versions: Iterable[str]) -> list[Path]:
    expected_names = {
        f"rabbitmq-management-v{version}.openapi.yaml"
        for version in versions
    }
    removed = []
    for path in sorted(output_dir.glob("rabbitmq-management-v*.openapi.yaml")):
        if path.name not in expected_names:
            path.unlink()
            removed.append(path)
    return removed


def sources_markdown(versions: Iterable[str]) -> str:
    lines = [
        "# RabbitMQ management API sources",
        "",
        "This reference lists the official RabbitMQ management API index used to generate each OpenAPI document.",
        "The source URL is suitable for automated downloads; the rendered URL opens the original HTML documentation in a browser.",
        "",
        "| Version | Source HTML | Rendered index | OpenAPI |",
        "| --- | --- | --- | --- |",
    ]
    for version in versions:
        source = SOURCE_URL.format(version=version)
        rendered = RENDERED_URL.format(version=version)
        lines.append(
            f"| {version} | [source]({source}) | [view]({rendered}) | "
            f"[`rabbitmq-management-v{version}.openapi.yaml`](../openapi/rabbitmq-management-v{version}.openapi.yaml) |"
        )
    lines.extend(
        (
            "",
            "## Regeneration",
            "",
            "Run the generator from the repository root:",
            "",
            "```bash",
            "python3 scripts/generate_openapi.py",
            "```",
            "",
            "The base generator uses only the Python standard library. It downloads each supported source index, overwrites the matching file in `openapi/`, "
            "and removes stale files that match the generator's filename pattern.",
            "",
            "## Runtime enrichment",
            "",
            "When the Docker daemon is running, the generator starts each RabbitMQ version with `docker run --rm` and the disposable credentials "
            f"`{RUNTIME_USER}` / `{RUNTIME_PASSWORD}`. It creates probe resources, exercises GET/PUT/POST/DELETE endpoints, opens the Management UI "
            "in headless Chrome, logs in, navigates management screens, and captures request URLs, non-sensitive headers, bodies, status codes, and JSON responses. "
            "The Management UI is the required source for the publish and get-message POST signatures. Direct API calls provide complementary observations and cleanup.",
            "",
            f"RabbitMQ 3.13.7 uses the pinned image `{RABBITMQ_3_13_7_IMAGE}` from Docker Hub. Because that base image does not enable the web UI, "
            "the container startup enables `rabbitmq_management` offline before launching `rabbitmq-server` through the official entrypoint.",
            "",
            "Observed schemas carry `x-rabbitmq-observed: true`; operations list observed statuses and sources. Runtime values and credentials are not persisted. "
            "Chrome or Chromium and Node.js are required when Docker is available. Use `--skip-runtime-enrichment` for an explicitly HTML-only generation.",
            "",
            "## Conversion boundary",
            "",
            "The source HTML does not provide formal JSON request or response schemas. The generator infers a schema only when a description "
            "contains a valid JSON example inside a `pre` block. A field is marked as required only when the surrounding prose explicitly calls "
            "it mandatory; inferred schemas carry `x-rabbitmq-inferred: true` and retain their source examples. Explicitly identified response examples "
            "are handled separately from request examples. Ambiguous, invalid, and undocumented payloads keep the generic `{}` schema. "
            "Validate application-specific payloads against the documentation and a RabbitMQ node running the same version.",
            "",
        )
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="append", choices=VERSIONS, dest="versions")
    parser.add_argument("--source-dir", type=Path, help="Read v<version>.html files instead of downloading them.")
    parser.add_argument("--output-dir", type=Path, default=Path("openapi"))
    parser.add_argument("--sources-doc", type=Path, default=Path("docs/api-sources.md"))
    parser.add_argument(
        "--skip-runtime-enrichment",
        action="store_true",
        help="Do not start disposable RabbitMQ containers even when Docker is running.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    versions = tuple(args.versions or VERSIONS)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.sources_doc.parent.mkdir(parents=True, exist_ok=True)

    runtime_enrichment = False
    if args.skip_runtime_enrichment:
        print("runtime enrichment explicitly skipped")
    elif docker_is_running():
        runtime_enrichment = True
        print("Docker daemon detected; runtime enrichment enabled")
    else:
        print("Docker daemon is not running; generating from HTML sources only")

    for version in versions:
        source_url = SOURCE_URL.format(version=version)
        if args.source_dir:
            source = (args.source_dir / f"v{version}.html").read_text(encoding="utf-8")
        else:
            source = download(source_url)
        document = build_openapi(source, version, source_url)
        if runtime_enrichment:
            observations = collect_runtime_observations(version)
            enrich_with_observations(document, observations, version)
            print(f"captured {len(observations)} runtime observations for RabbitMQ {version}")
        validate_document(document)
        destination = args.output_dir / f"rabbitmq-management-v{version}.openapi.yaml"
        destination.write_text(dump_yaml(document), encoding="utf-8")
        print(f"generated {destination} ({len(document['paths'])} paths)")

    if not args.versions:
        for removed in prune_generated_files(args.output_dir, versions):
            print(f"removed {removed}")
        args.sources_doc.write_text(sources_markdown(versions), encoding="utf-8")
        print(f"generated {args.sources_doc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
