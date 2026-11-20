const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "..");

test("preview-mock acompanha a versão e métodos públicos de preload.js", async () => {
  const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8"));
  const mockSrc = fs.readFileSync(path.join(ROOT, "site", "preview-mock.js"), "utf8");

  const context = {
    window: {},
    location: { search: "" },
    URLSearchParams,
    Date,
    Math,
    setTimeout: () => 0,
    document: { getElementById: () => null, querySelector: () => null },
    Event: class {},
  };
  vm.runInNewContext(mockSrc, context);

  const api = context.window.ultron;
  assert.equal(api.version, pkg.version);
  assert.equal(typeof api.clearConversation, "function");
  assert.equal(typeof api.executarFluxo, "function");

  const info = await api.updateInfo();
  assert.equal(info.current_version, pkg.version);
  const flow = await api.executarFluxo("modo_jogo");
  assert.match(flow.operation_id, /modo_jogo/);
});

test("carregarPersonalidade em personalidade-painel.js não sobrescreve tratamentos já salvos", () => {
  const painelSrc = fs.readFileSync(path.join(ROOT, "site", "src", "personalidade-painel.js"), "utf8");
  assert.match(
    painelSrc,
    /if \(typeof p\.tratamento === 'string' && !tratamentosPorPerfil\[p\.id\]\)/,
    "carregarPersonalidade deve preencher apenas perfis sem tratamento salvo"
  );
});
