const test = require("node:test");
const assert = require("node:assert/strict");
const { createApiClient } = require("../api");

const TOKEN = "t".repeat(48);
const OPERATION_ID = "a".repeat(32);

test("execução direta envia o ID ao endpoint local validado", async () => {
  const calls = [];
  const api = createApiClient({
    baseUrl: "http://127.0.0.1:43873", token: TOKEN,
    fetchImpl: async (url, init) => {
      calls.push({ url, init });
      return Response.json({ operation_id: OPERATION_ID }, { status: 202 });
    },
  });

  assert.deepEqual(await api.executarFluxo("modo_jogo"), { operation_id: OPERATION_ID });
  assert.equal(calls[0].url, "http://127.0.0.1:43873/api/v1/fluxos/executar");
  assert.equal(calls[0].init.method, "POST");
  assert.equal(calls[0].init.body, '{"id":"modo_jogo"}');
  assert.equal(calls[0].init.headers["X-ULTRON-Token"], TOKEN);
});

test("execução direta rejeita IDs inválidos e respostas sem operação", async () => {
  let calls = 0;
  const api = createApiClient({
    baseUrl: "http://127.0.0.1:43873", token: TOKEN,
    fetchImpl: async () => { calls += 1; return Response.json({ operation_id: "curto" }); },
  });

  for (const id of ["", "../bad", "A", "x".repeat(41), null, 4]) {
    await assert.rejects(api.executarFluxo(id), /Identificador de fluxo inválido/);
  }
  assert.equal(calls, 0);
  await assert.rejects(api.executarFluxo("modo_jogo"), /Resposta inválida da API local/);
  assert.equal(calls, 1);
});
