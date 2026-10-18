"""Partículas 3D simples (palha, terra, lascas de madeira) projetadas pela câmera do jogo."""
import numpy as np
import pygame

import mat3d as m3

GRAVIDADE = 6.0
NEAR = 0.15


class Particulas:
    def __init__(self, maximo=600):
        self.maximo = maximo
        self.pos = np.zeros((0, 3))
        self.vel = np.zeros((0, 3))
        self.vida = np.zeros(0)
        self.vida_total = np.zeros(0)
        self.cores = np.zeros((0, 3))
        self.tamanho = np.zeros(0)
        self.rng = np.random.default_rng()

    def emitir(self, posicao, cores, quantidade=24, velocidade=3.0, direcao=None, tamanho=0.05, vida=0.9):
        """Explosão de partículas a partir de `posicao`, com viés opcional para `direcao`."""
        n = quantidade
        aleatoria = self.rng.normal(size=(n, 3))
        aleatoria /= np.linalg.norm(aleatoria, axis=1, keepdims=True)
        if direcao is not None:
            aleatoria = aleatoria * 0.7 + np.asarray(direcao) * 0.6
        vel = aleatoria * velocidade * self.rng.uniform(0.4, 1.0, (n, 1)) + np.array((0, 1.2, 0))
        cores = np.array([cores[i % len(cores)] for i in self.rng.integers(0, len(cores), n)], dtype=float)
        vidas = vida * self.rng.uniform(0.6, 1.0, n)
        self.pos = np.vstack((self.pos, np.tile(posicao, (n, 1))))[-self.maximo:]
        self.vel = np.vstack((self.vel, vel))[-self.maximo:]
        self.vida = np.concatenate((self.vida, vidas))[-self.maximo:]
        self.vida_total = np.concatenate((self.vida_total, vidas))[-self.maximo:]
        self.cores = np.vstack((self.cores, cores))[-self.maximo:]
        self.tamanho = np.concatenate((self.tamanho, tamanho * self.rng.uniform(0.6, 1.3, n)))[-self.maximo:]

    def atualizar(self, dt):
        if not len(self.vida):
            return
        self.vel[:, 1] -= GRAVIDADE * dt
        self.vel *= 1 - 1.5 * dt  # arrasto do ar
        self.pos += self.vel * dt
        no_chao = self.pos[:, 1] < 0.02
        self.pos[no_chao, 1] = 0.02
        self.vel[no_chao] *= 0.3
        self.vida -= dt
        vivas = self.vida > 0
        for nome in ("pos", "vel", "vida", "vida_total", "cores", "tamanho"):
            setattr(self, nome, getattr(self, nome)[vivas])

    def desenhar(self, tela, render):
        if not len(self.vida):
            return
        cam = m3.aplicar(render.visao, self.pos)
        visiveis = cam[:, 2] > NEAR
        if not visiveis.any():
            return
        cam = cam[visiveis]
        tela_xy = m3.projetar(cam, render.focal, render.centro)
        raio = np.clip(render.focal * self.tamanho[visiveis] / cam[:, 2], 1, 8)
        frac = (self.vida / self.vida_total)[visiveis]
        cores = self.cores[visiveis]
        for (x, y), r, f, cor in zip(tela_xy.tolist(), raio.tolist(), frac.tolist(), cores.tolist()):
            lado = max(1, int(r * (0.5 + 0.5 * f)))
            pygame.draw.rect(tela, cor, (int(x) - lado // 2, int(y) - lado // 2, lado, lado))
