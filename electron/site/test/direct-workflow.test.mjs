import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { RealTransport } from "../src/real.js";

const here = dirname(fileURLToPath(import.meta.url));

test("transporte envia o ID pelo método seguro do bridge", async () => {
  const calls = [];
  const bridge = {
    health: async () => ({ ok: true }),
    executarFluxo: async id => (calls.push(id), { operation_id: "a".repeat(32) }),
  };
  const transport = new RealTransport({ bridge, onEvent: () => {} });
  await transport.connect({ poll: false });

  assert.deepEqual(await transport.executarFluxo("modo_jogo"), { operation_id: "a".repeat(32) });
  assert.deepEqual(calls, ["modo_jogo"]);
  transport.disconnect();
});

test("botão executa por ID sem enviar uma frase ao LLM", async () => {
  const app = await readFile(join(here, "..", "app.js"), "utf8");
  const main = await readFile(join(here, "..", "..", "main.js"), "utf8");
  const preload = await readFile(join(here, "..", "..", "preload.js"), "utf8");
  const inicio = app.indexOf("async function rodarFluxo(");
  const fim = app.indexOf("\n}", inicio);
  const handler = app.slice(inicio, fim);

  assert.ok(inicio >= 0 && fim > inicio);
  assert.ok(handler.includes("transport.executarFluxo(id)"));
  assert.equal(handler.includes("send("), false);
  assert.ok(preload.includes("ipcRenderer.invoke('fluxos:executar', id)"));
  assert.ok(main.includes("ipcMain.handle('fluxos:executar'"));
  assert.ok(main.includes("isSender(event, mainWindow)"));
  assert.ok(main.includes("api.executarFluxo(id)"));
});
