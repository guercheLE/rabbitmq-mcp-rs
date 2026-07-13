import importlib.util
import json
import shutil
import subprocess
import unittest
from collections import OrderedDict
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "generate_openapi.py"
SPEC = importlib.util.spec_from_file_location("generate_openapi_runtime", MODULE_PATH)
assert SPEC and SPEC.loader
generate_openapi = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generate_openapi)


class RuntimeEnrichmentTests(unittest.TestCase):
    def test_3_13_7_uses_linked_digest_and_enables_management_ui(self):
        configuration = generate_openapi.runtime_container_configuration("3.13.7")

        self.assertEqual(
            configuration["image"],
            "rabbitmq@sha256:9f65f155849158d312201e4ca0eee99724036ae3ec4c7ef30063967cf11735c8",
        )
        self.assertEqual(configuration["docker_options"], ["--entrypoint", "bash"])
        command = " ".join(configuration["command"])
        self.assertIn("rabbitmq-plugins enable --offline rabbitmq_management", command)
        self.assertIn("docker-entrypoint.sh rabbitmq-server", command)

    def test_docker_check_uses_daemon_exit_status(self):
        calls = []

        def running(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0)

        def stopped(command, **kwargs):
            return subprocess.CompletedProcess(command, 1)

        self.assertTrue(generate_openapi.docker_is_running(runner=running))
        self.assertFalse(generate_openapi.docker_is_running(runner=stopped))
        self.assertEqual(calls[0][0], ["docker", "info"])

    def test_matches_observed_url_to_most_specific_openapi_path(self):
        paths = OrderedDict(
            (
                ("/api/queues/{vhost}", {}),
                ("/api/queues/{vhost}/{name}", {}),
            )
        )

        matched = generate_openapi.match_openapi_path(
            paths,
            "/api/queues/openapi-probe/openapi-queue?columns=name",
        )

        self.assertEqual(matched, "/api/queues/{vhost}/{name}")

    def test_enriches_requests_and_responses_without_persisting_runtime_values(self):
        document = OrderedDict(
            (
                ("openapi", "3.1.0"),
                (
                    "paths",
                    OrderedDict(
                        (
                            (
                                "/api/vhosts/{name}",
                                OrderedDict(
                                    (
                                        (
                                            "get",
                                            OrderedDict(
                                                (
                                                    ("operationId", "getApiVhostsName"),
                                                    ("responses", OrderedDict((("2XX", {"description": "Success"}),))),
                                                )
                                            ),
                                        ),
                                        (
                                            "put",
                                            OrderedDict(
                                                (
                                                    ("operationId", "putApiVhostsName"),
                                                    (
                                                        "requestBody",
                                                        OrderedDict(
                                                            (
                                                                (
                                                                    "content",
                                                                    OrderedDict(
                                                                        (("application/json", OrderedDict((("schema", OrderedDict()),))),)
                                                                    ),
                                                                ),
                                                            )
                                                        ),
                                                    ),
                                                    ("responses", OrderedDict((("2XX", {"description": "Success"}),))),
                                                )
                                            ),
                                        ),
                                        (
                                            "post",
                                            OrderedDict(
                                                (
                                                    ("operationId", "postApiVhostsName"),
                                                    (
                                                        "requestBody",
                                                        OrderedDict(
                                                            (
                                                                (
                                                                    "content",
                                                                    OrderedDict(
                                                                        (("application/json", OrderedDict((("schema", OrderedDict()),))),)
                                                                    ),
                                                                ),
                                                            )
                                                        ),
                                                    ),
                                                    ("responses", OrderedDict((("2XX", {"description": "Success"}),))),
                                                )
                                            ),
                                        ),
                                    )
                                ),
                            ),
                        )
                    ),
                ),
            )
        )
        observations = [
            {
                "source": "direct",
                "method": "PUT",
                "path": "/api/vhosts/openapi-probe",
                "status": 201,
                "request": {"description": "runtime-only", "tags": "openapi"},
                "response": None,
            },
            {
                "source": "browser",
                "method": "GET",
                "path": "/api/vhosts/openapi-probe",
                "status": 200,
                "request": None,
                "response": {"name": "openapi-probe", "tracing": False},
            },
            {
                "source": "browser",
                "method": "POST",
                "path": "/api/vhosts/openapi-probe?mode=safe",
                "request": {"action": "probe"},
                "requestHeaders": {"Content-Type": "application/json", "X-Reason": "ui-action"},
                "status": 204,
                "response": None,
            },
        ]

        generate_openapi.enrich_with_observations(document, observations, "4.3.2")

        put = document["paths"]["/api/vhosts/{name}"]["put"]
        request_schema = put["requestBody"]["content"]["application/json"]["schema"]
        self.assertEqual(request_schema["properties"]["description"], {"type": "string"})
        self.assertTrue(request_schema["x-rabbitmq-observed"])
        self.assertNotIn("example", put["requestBody"]["content"]["application/json"])
        self.assertEqual(put["x-rabbitmq-observed-statuses"], [201])

        get = document["paths"]["/api/vhosts/{name}"]["get"]
        response_schema = get["responses"]["200"]["content"]["application/json"]["schema"]
        self.assertEqual(response_schema["properties"]["tracing"], {"type": "boolean"})
        self.assertTrue(response_schema["x-rabbitmq-observed"])
        self.assertNotIn("example", get["responses"]["200"]["content"]["application/json"])
        self.assertEqual(get["x-rabbitmq-observed-sources"], ["browser"])
        post = document["paths"]["/api/vhosts/{name}"]["post"]
        parameters = {(parameter["in"], parameter["name"]): parameter for parameter in post["parameters"]}
        self.assertTrue(parameters[("query", "mode")]["x-rabbitmq-observed"])
        self.assertTrue(parameters[("header", "X-Reason")]["x-rabbitmq-observed"])
        self.assertEqual(post["requestBody"]["content"]["application/json"]["schema"]["properties"]["action"], {"type": "string"})
        self.assertEqual(document["x-rabbitmq-runtime-enrichment"]["observedOperations"], 3)

    def test_probe_plan_includes_read_and_write_methods(self):
        steps = generate_openapi.probe_seed_steps()
        methods = {step[0] for step in steps}

        self.assertTrue({"GET", "PUT", "POST", "DELETE"}.issubset(methods))

    def test_parses_docker_assigned_management_port(self):
        self.assertEqual(generate_openapi.parse_docker_port("127.0.0.1:49153\n"), 49153)
        self.assertEqual(generate_openapi.parse_docker_port("[::]:49154\n"), 49154)

    def test_direct_api_call_captures_authenticated_request_and_response(self):
        received = {}

        class Response:
            status = 201
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self):
                return json.dumps({"accepted": True}).encode()

        def opener(request, timeout):
            received["authorization"] = request.get_header("Authorization")
            received["body"] = json.loads(request.data)
            received["timeout"] = timeout
            return Response()

        observation = generate_openapi.call_management_api(
            "http://127.0.0.1:15672",
            "PUT",
            "/api/widgets/example",
            {"enabled": True},
            username="probe",
            password="secret",
            opener=opener,
        )

        self.assertTrue(received["authorization"].startswith("Basic "))
        self.assertEqual(received["body"], {"enabled": True})
        self.assertEqual(observation["status"], 201)
        self.assertEqual(observation["request"], {"enabled": True})
        self.assertEqual(observation["response"], {"accepted": True})
        self.assertEqual(observation["source"], "direct")

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for browser capture")
    def test_browser_capture_helper_is_valid_and_does_not_embed_credentials(self):
        helper = Path(__file__).parents[1] / "scripts" / "capture_management_api.mjs"

        result = subprocess.run(["node", "--check", helper], capture_output=True, text=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(generate_openapi.RUNTIME_PASSWORD, helper.read_text(encoding="utf-8"))

    def test_requires_post_signatures_from_browser_capture(self):
        valid = [
            {"method": "POST", "path": "/api/exchanges/openapi-probe/openapi-probe-exchange/publish"},
            {"method": "POST", "path": "/api/queues/openapi-probe/openapi-probe-queue/get"},
        ]

        generate_openapi.validate_browser_post_observations(valid)
        with self.assertRaisesRegex(RuntimeError, "POST signatures"):
            generate_openapi.validate_browser_post_observations(valid[:1])


if __name__ == "__main__":
    unittest.main()
