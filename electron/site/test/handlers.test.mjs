import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

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
