import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const here = dirname(fileURLToPath(import.meta.url));
const appPath = join(here, '..', 'app.js');

test('todo handler ligado a um controle existe no módulo', async () => {
  const source = await readFile(appPath, 'utf8');

  // `elemento.onclick = algumNome;` só funciona se `algumNome` existir.
  // Um nome errado lança ReferenceError no topo do módulo e derruba a
  // inicialização inteira — inclusive a conexão com o núcleo.
  const usados = new Set();
  for (const m of source.matchAll(/\.(?:onclick|onsubmit|onchange|oninput)\s*=\s*([A-Za-z_$][\w$]*)\s*;/g)) {
    usados.add(m[1]);
  }

  const declarados = new Set();
  for (const m of source.matchAll(/(?:function|const|let|var)\s+([A-Za-z_$][\w$]*)/g)) {
    declarados.add(m[1]);
  }
  for (const m of source.matchAll(/import\s*\{([^}]+)\}\s*from/g)) {
    for (const parte of m[1].split(',')) {
      const nome = parte.trim().split(/\s+as\s+/).pop();
      if (nome) declarados.add(nome);
    }
  }

  assert.ok(usados.size > 0, 'nenhum handler encontrado — o padrão do teste ficou obsoleto');
  const faltando = [...usados].filter(nome => !declarados.has(nome)).sort();
  assert.deepEqual(faltando, [], `handlers sem definição: ${faltando.join(', ')}`);
});

test('o módulo não repete a mesma ligação de controle', async () => {
  const source = await readFile(appPath, 'utf8');
  const vistas = new Map();
  const duplicadas = [];
  for (const m of source.matchAll(/\$\((['"])([^'"]+)\1\)\.onclick\s*=/g)) {
    const id = m[2];
    vistas.set(id, (vistas.get(id) || 0) + 1);
    if (vistas.get(id) === 2) duplicadas.push(id);
  }
  assert.deepEqual(duplicadas, [], `controles ligados mais de uma vez: ${duplicadas.join(', ')}`);
});

test('o elemento de reserva aceita todo método chamado com ?.', async () => {
  const source = await readFile(appPath, 'utf8');

  // `$(id)` devolve VAZIO quando o elemento não existe. Um `?.remove()` nesse
  // objeto não protege nada: `?.` só para em null/undefined, e o VAZIO é um
  // objeto real sem `remove`. O segundo comando digitado caía numa rejeição
  // silenciosa por causa disso. Este teste impede que um método novo usado com
  // `?.` falte no reservatório.
  const inicio = source.indexOf('const VAZIO = {');
  assert.ok(inicio >= 0, 'objeto VAZIO não encontrado em app.js');
  const abre = source.indexOf('{', inicio);
  let profundidade = 0;
  let fecha = -1;
  for (let i = abre; i < source.length; i += 1) {
    if (source[i] === '{') profundidade += 1;
    else if (source[i] === '}') {
      profundidade -= 1;
      if (profundidade === 0) { fecha = i; break; }
    }
  }
  assert.ok(fecha > abre, 'não consegui delimitar o objeto VAZIO');
  const vazio = vm.runInNewContext(`(${source.slice(abre, fecha + 1)})`);

  const metodos = new Set();
  for (const m of source.matchAll(/\$\([^)]*\)\?\.([A-Za-z_$][\w$]*)\s*\(/g)) metodos.add(m[1]);
  assert.ok(metodos.size > 0, 'nenhuma chamada opcional encontrada — o padrão do teste ficou obsoleto');

  const faltando = [...metodos].filter(nome => typeof vazio[nome] !== 'function').sort();
  assert.deepEqual(faltando, [], `métodos ausentes no reservatório VAZIO: ${faltando.join(', ')}`);
});

test('atalhos globais nao duplicam listener entre window e document', async () => {
  const source = await readFile(appPath, 'utf8');
  const ocorrencias = source.match(/addEventListener\(\s*['"]keydown['"]\s*,\s*atalhos\b/g) || [];
  assert.equal(ocorrencias.length, 1);
});

test('acompanharAtualizacao limpa updateUi.timer ao encerrar polling', async () => {
  const source = await readFile(appPath, 'utf8');
  const bloco = source.slice(
    source.indexOf('async function acompanharAtualizacao()'),
    source.indexOf('function pedirReinicio('),
  );
  assert.match(bloco, /clearInterval\(updateUi\.timer\);\s*\r?\n\s*updateUi\.timer\s*=\s*null;/);
  const clearsDentroLoop = (bloco.slice(bloco.indexOf('setInterval')).match(/clearInterval\(updateUi\.timer\);/g) || []).length;
  const resetsDentroLoop = (bloco.slice(bloco.indexOf('setInterval')).match(/updateUi\.timer\s*=\s*null;/g) || []).length;
  assert.equal(clearsDentroLoop, 3);
  assert.equal(resetsDentroLoop, 3);
});

test('update:launch aceita objeto { launched: true } retornado pela API', async () => {
  const mainSource = await readFile(join(here, '..', '..', 'main.js'), 'utf8');
  const trecho = mainSource.slice(
    mainSource.indexOf("ipcMain.handle('update:launch'"),
    mainSource.indexOf("ipcMain.handle('update:rollback'"),
  );
  assert.match(trecho, /launched\.launched\s*===\s*true/);
  assert.doesNotMatch(trecho, /return launched === true;/);
});
