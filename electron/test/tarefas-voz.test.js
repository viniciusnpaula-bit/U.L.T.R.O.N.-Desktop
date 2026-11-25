const test = require("node:test");
const assert = require("node:assert/strict");
const { createApiClient } = require("../api");

const BASE_URL = "http://127.0.0.1:3900";
const TOKEN = "a".repeat(40);

test("rotas de tarefas (subagentes) usam GET/POST locais esperados e validam o ID", async () => {
  const calls = [];
  const client = createApiClient({
    baseUrl: BASE_URL,
    token: TOKEN,
    fetchImpl: async (url, init) => {
      calls.push({ url, method: init.method, body: init.body });
      return {
        ok: true,
        status: 200,
        text: async () => JSON.stringify({ tarefas: [], ativas: 0 }),
      };
    },
  });

  await client.tarefasListar();
  await client.tarefaCancelar("abcdef123456");

  assert.equal(calls.length, 2);
  assert.equal(calls[0].url, `${BASE_URL}/api/v1/tarefas`);
  assert.equal(calls[0].method, "GET");
  assert.equal(calls[1].url, `${BASE_URL}/api/v1/tarefas/cancelar`);
  assert.equal(calls[1].method, "POST");
  assert.deepEqual(JSON.parse(calls[1].body), { id: "abcdef123456" });

  assert.throws(() => client.tarefaCancelar("invalido!"), /Identificador de tarefa inválido/);
  assert.throws(() => client.tarefaCancelar("../123456789012"), /Identificador de tarefa inválido/);
  assert.equal(calls.length, 2);
});
