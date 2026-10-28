import test from 'node:test';
import assert from 'node:assert/strict';
import { estadoDoOrbe, geometriaDoCristal, normalizarHumor, normalizarModo, projetar } from '../src/orb.js';

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

test('cada estado real escolhe um dos quatro humores de animação', () => {
  const agora = 1000;
  assert.equal(estadoDoOrbe(null, {}, agora).humor, 'ocioso');
  assert.equal(estadoDoOrbe({ core_running: true }, {}, agora).humor, 'ocioso');
  assert.equal(estadoDoOrbe({ core_running: true, microphone_paused: true }, {}, agora).humor, 'ocioso');
  assert.equal(estadoDoOrbe({ core_running: true, speaking: true }, {}, agora).humor, 'respondendo');
  assert.equal(estadoDoOrbe({ core_running: true, microphone_state: 'processando' }, {}, agora).humor,
    'trabalhando');
  assert.equal(estadoDoOrbe({ core_running: true, microphone_state: 'processando' }, {}, agora).rotulo,
    'TRABALHANDO');
  assert.equal(estadoDoOrbe({ core_running: true, microphone_state: 'calibrando' }, {}, agora).humor,
    'trabalhando');
  assert.equal(estadoDoOrbe({
    core_running: true, microphone_capturing: true, microphone_threshold: 100, microphone_level: 320,
  }, {}, agora).humor, 'escutando');
});

test('humor só aceita os quatro nomes; qualquer outra coisa volta ao ocioso', () => {
  for (const nome of ['ocioso', 'escutando', 'respondendo', 'trabalhando']) {
    assert.equal(normalizarHumor(nome), nome);
  }
  assert.equal(normalizarHumor('2d'), 'ocioso');
  assert.equal(normalizarHumor(''), 'ocioso');
  assert.equal(normalizarHumor(undefined), 'ocioso');
});

test('nível usa o volume real normalizado pelo limiar e nunca sai de 0..1', () => {
  const agora = 1000;
  const escutando = { core_running: true, microphone_capturing: true, microphone_threshold: 100 };
  assert.equal(estadoDoOrbe({ ...escutando, microphone_level: 80 }, {}, agora).nivel, 0.5);
  assert.equal(estadoDoOrbe({ ...escutando, microphone_level: 100000 }, {}, agora).nivel, 1);
  assert.equal(estadoDoOrbe({ ...escutando, microphone_level: -50 }, {}, agora).nivel, 0);
  assert.equal(estadoDoOrbe({ ...escutando, microphone_level: Number.NaN }, {}, agora).nivel, 0);
  assert.equal(estadoDoOrbe({ ...escutando, microphone_threshold: 0, microphone_level: 50 }, {}, agora).nivel, 0);
  const semCaptura = { core_running: true, microphone_capturing: false, microphone_threshold: 100, microphone_level: 90 };
  assert.equal(estadoDoOrbe(semCaptura, {}, agora).nivel, 0);
});
