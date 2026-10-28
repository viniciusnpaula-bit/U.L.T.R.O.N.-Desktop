import test from 'node:test';
import assert from 'node:assert/strict';
import { estadoDoOrbe, geometriaDoCristal, normalizarModo, projetar } from '../src/orb.js';

test('modo do núcleo é 3d por padrão e só aceita 2d quando pedido', () => {
  assert.equal(normalizarModo('3d'), '3d');
  assert.equal(normalizarModo('2d'), '2d');
  assert.equal(normalizarModo('2D'), '3d');
  assert.equal(normalizarModo('webgl'), '3d');
  assert.equal(normalizarModo(''), '3d');
  assert.equal(normalizarModo(undefined), '3d');
});

test('projeção devolve números finitos e cresce com a profundidade', () => {
  const camera = { z: 7.4, foco: Math.PI / 4 };
  const longe = projetar({ x: 0, y: 0, z: 0 }, camera);
  const perto = projetar({ x: 0, y: 0, z: 2 }, camera);
  for (const valor of [longe.x, longe.y, longe.escala, perto.escala]) {
    assert.ok(Number.isFinite(valor), String(valor));
  }
  assert.ok(perto.escala > longe.escala);
  const invalido = projetar({}, { z: 0, foco: Number.NaN });
  assert.ok(Number.isFinite(invalido.escala) && invalido.escala > 0);
});

test('cristal: as arestas são medidas na malha regular, antes da escala', () => {
  const malha = geometriaDoCristal();
  assert.equal(malha.vertices.length, 12);
  assert.equal(malha.arestas.length, 30);
});

test('estadoDoOrbe continua traduzindo só o status real', () => {
  const agora = 1000;
  assert.equal(estadoDoOrbe(null, {}, agora).rotulo, 'SEM NÚCLEO');
  assert.equal(estadoDoOrbe({ core_running: true }, {}, agora).rotulo, 'À ESCUTA');
  assert.equal(estadoDoOrbe({ core_running: true, speaking: true }, {}, agora).rotulo, 'RESPONDENDO');
  assert.equal(estadoDoOrbe({ core_running: true, microphone_paused: true }, {}, agora).rotulo,
    'EM SILÊNCIO');
});
