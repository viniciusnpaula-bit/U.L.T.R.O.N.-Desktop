import json
import secrets
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from desktop_api import create_server


class Runtime:
    def __init__(self):
        self.received = []

    def submit_fluxo(self, flow_id):
        if flow_id != "modo_jogo":
            raise LookupError(flow_id)
        self.received.append(flow_id)
        return "operation-workflow"


class DirectWorkflowApiTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()
        self.token = secrets.token_urlsafe(32)
        self.server, self.url = create_server(self.runtime, self.token)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)

    def call(self, body):
        request = Request(
            self.url + "/api/v1/fluxos/executar",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-ULTRON-Token": self.token},
            method="POST",
        )
        try:
            with urlopen(request, timeout=2) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def test_executes_a_named_workflow_directly_and_returns_operation_id(self):
        status, result = self.call({"id": "modo_jogo"})
        self.assertEqual(status, 202)
        self.assertEqual(result, {"operation_id": "operation-workflow"})
        self.assertEqual(self.runtime.received, ["modo_jogo"])

    def test_rejects_malformed_workflow_payloads_without_queueing(self):
        for body in ({}, {"id": "modo_jogo", "text": "run"}, {"id": "../bad"}, {"id": 4}):
            status, result = self.call(body)
            self.assertEqual(status, 400, body)
            self.assertEqual(result["error"], "invalid_workflow_payload")
        self.assertEqual(self.runtime.received, [])

    def test_returns_not_found_for_unknown_workflow(self):
        status, result = self.call({"id": "nao_existe"})
        self.assertEqual(status, 404)
        self.assertEqual(result["error"], "workflow_not_found")
        self.assertEqual(self.runtime.received, [])



if __name__ == "__main__":
    unittest.main()
