import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "generate_openapi.py"
SPEC = importlib.util.spec_from_file_location("generate_openapi", MODULE_PATH)
assert SPEC and SPEC.loader
generate_openapi = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generate_openapi)


def source_for(methods: tuple[str, ...], description: str, path: str = "/api/widgets/<i>name</i>") -> str:
    flags = {method: ("X" if method in methods else "") for method in ("get", "put", "delete", "post")}
    return f"""
    <html><body><table>
      <tr><th>GET</th><th>PUT</th><th>DELETE</th><th>POST</th><th>Path</th><th>Description</th></tr>
      <tr>
        <td>{flags['get']}</td><td>{flags['put']}</td><td>{flags['delete']}</td><td>{flags['post']}</td>
        <td class="path">{path}</td><td>{description}</td>
      </tr>
    </table></body></html>
    """


class SafeSchemaInferenceTests(unittest.TestCase):
    def build(self, source: str):
        return generate_openapi.build_openapi(source, "1.2.3", "https://example.test/index.html")

    def test_infers_request_schema_and_only_explicitly_mandatory_fields(self):
        document = self.build(
            source_for(
                ("put",),
                """To PUT a widget, use a body like:
                <pre>{"type":"direct","durable":true,"arguments":{}}</pre>
                The <code>type</code> key is mandatory; other keys are optional.""",
            )
        )

        media = document["paths"]["/api/widgets/{name}"]["put"]["requestBody"]["content"]["application/json"]
        self.assertEqual(
            media["schema"],
            {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "durable": {"type": "boolean"},
                    "arguments": {"type": "object", "additionalProperties": True},
                },
                "required": ["type"],
                "x-rabbitmq-inferred": True,
            },
        )
        self.assertEqual(media["example"], {"type": "direct", "durable": True, "arguments": {}})

    def test_separates_explicit_request_and_response_examples(self):
        document = self.build(
            source_for(
                ("post",),
                """You will need a body looking something like:
                <pre>{"payload":"hello","payload_encoding":"string"}</pre>
                All keys are mandatory. If the message is published successfully,
                the response will look like: <pre>{"routed":true}</pre>""",
                "/api/exchanges/<i>vhost</i>/<i>name</i>/publish",
            )
        )

        operation = document["paths"]["/api/exchanges/{vhost}/{name}/publish"]["post"]
        request_media = operation["requestBody"]["content"]["application/json"]
        response_media = operation["responses"]["2XX"]["content"]["application/json"]
        self.assertEqual(request_media["schema"]["required"], ["payload", "payload_encoding"])
        self.assertEqual(response_media["schema"]["properties"], {"routed": {"type": "boolean"}})
        self.assertEqual(response_media["example"], {"routed": True})

    def test_all_other_keys_mandatory_excludes_explicit_optional_key(self):
        document = self.build(
            source_for(
                ("post",),
                """Post a body looking like:
                <pre>{"count":5,"ackmode":"ack_requeue_true","encoding":"auto","truncate":50000}</pre>
                <code>truncate</code> is optional; all other keys are mandatory.""",
            )
        )

        schema = document["paths"]["/api/widgets/{name}"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        self.assertEqual(schema["required"], ["count", "ackmode", "encoding"])

    def test_does_not_treat_put_example_as_get_response(self):
        document = self.build(
            source_for(
                ("get", "put"),
                """To PUT a widget, use a body like: <pre>{"enabled":true}</pre>
                All keys are optional.""",
            )
        )

        path_item = document["paths"]["/api/widgets/{name}"]
        self.assertNotIn("content", path_item["get"]["responses"]["2XX"])
        request_media = path_item["put"]["requestBody"]["content"]["application/json"]
        self.assertEqual(request_media["example"], {"enabled": True})
        self.assertNotIn("required", request_media["schema"])

    def test_keeps_generic_schema_when_pre_block_is_not_json(self):
        document = self.build(
            source_for(("post",), "Request example: <pre>curl -X POST http://localhost/api/widgets</pre>")
        )

        media = document["paths"]["/api/widgets/{name}"]["post"]["requestBody"]["content"]["application/json"]
        self.assertEqual(media, {"schema": {}})


class SupportedVersionTests(unittest.TestCase):
    def test_only_requested_release_snapshots_are_supported(self):
        self.assertEqual(generate_openapi.VERSIONS, ("4.3.2", "4.2.8", "4.1.8", "4.0.9", "3.13.7"))

    def test_prunes_only_stale_generated_openapi_files(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            kept = output_dir / "rabbitmq-management-v4.3.2.openapi.yaml"
            stale = output_dir / "rabbitmq-management-v4.3.1.openapi.yaml"
            unrelated = output_dir / "custom.openapi.yaml"
            for path in (kept, stale, unrelated):
                path.write_text("test", encoding="utf-8")

            removed = generate_openapi.prune_generated_files(output_dir, ("4.3.2",))

            self.assertEqual(removed, [stale])
            self.assertTrue(kept.exists())
            self.assertFalse(stale.exists())
            self.assertTrue(unrelated.exists())

    def test_sources_document_explains_3_13_7_digest_startup(self):
        document = generate_openapi.sources_markdown(generate_openapi.VERSIONS)

        self.assertIn(generate_openapi.RABBITMQ_3_13_7_IMAGE, document)
        self.assertIn("enables `rabbitmq_management` offline", document)


if __name__ == "__main__":
    unittest.main()
