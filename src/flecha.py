"""Voo balístico das flechas e colisão com alvos, árvores e chão."""
import math

import numpy as np

import mat3d as m3
import modelos as mod

GRAVIDADE = 9.8
VELOCIDADE_MIN, VELOCIDADE_MAX = 22.0, 68.0
PONTA = 0.45  # distância do centro da flecha até a ponta
PENETRACAO = 0.12
SUBPASSOS = 4

MALHA = mod.flecha()


class Flecha:
    def __init__(self, posicao, direcao, forca, vento, multiplicador):
        velocidade = m3.lerp(VELOCIDADE_MIN, VELOCIDADE_MAX, forca)
        self.pos = np.array(posicao, dtype=float)
        self.vel = np.array(direcao, dtype=float) * velocidade
        self.vento = vento
        self.multiplicador = multiplicador
        self.estado = "voando"  # voando | cravada | chao | arvore | perdida
        self.alvo = None
        self.local = None
        self.m_fixa = None
        self.tempo = 0.0
        self.pontos = 0
        self.rastro = [self.pos.copy()]

    def matriz(self):
        if self.estado == "cravada":
            return self.alvo.matriz @ self.local  # segue o alvo (hierarquia)
        if self.m_fixa is not None:
            return self.m_fixa
        yaw, pitch = m3.angulos_de(self.vel)
        return m3.compor(m3.translacao(*self.pos), m3.orientacao(yaw, pitch))

    def ponta_mundo(self):
        return m3.aplicar_ponto(self.matriz(), (0, 0, PONTA))

    def atualizar(self, dt, cena):
        """Integra o voo. Devolve um evento (tipo, alvo, pontos) quando a flecha para."""
        if self.estado != "voando":
            return None
        self.tempo += dt
        h = dt / SUBPASSOS
        for _ in range(SUBPASSOS):
            ponta_antes = self.pos + self.vel / np.linalg.norm(self.vel) * PONTA
            self.vel += np.array((self.vento, -GRAVIDADE, 0.0)) * h
            self.pos += self.vel * h
            direcao = self.vel / np.linalg.norm(self.vel)
            ponta = self.pos + direcao * PONTA

            colisao = None
            for alvo in cena.alvos:
                hit = alvo.intersecao(ponta_antes, ponta)
                if hit and (colisao is None or hit[0] < colisao[0]):
                    colisao = (hit[0], alvo, hit[1], hit[2])
            if colisao:
                _, alvo, p_local, r = colisao
                d_local = alvo.inversa[:3, :3] @ direcao
                yaw, pitch = m3.angulos_de(d_local)
                centro = p_local - d_local * (PONTA - PENETRACAO)
                self.local = m3.compor(m3.translacao(*centro), m3.orientacao(yaw, pitch))
                self.estado, self.alvo = "cravada", alvo
                self.pontos = alvo.pontos(r)
                return ("alvo", alvo, self.pontos)

            if ponta[1] <= 0.0:
                self._fixar(direcao, altura_ponta=-PENETRACAO)
                self.estado = "chao"
                return ("chao", None, 0)

            for x, z, raio, altura in cena.troncos:
                if math.hypot(ponta[0] - x, ponta[2] - z) < raio + 0.05 and ponta[1] < altura * 0.6:
                    self._fixar(direcao)
                    self.estado = "arvore"
                    return ("arvore", None, 0)
            self.rastro.append(self.pos.copy())
            if len(self.rastro) > 24:
                self.rastro.pop(0)

        if self.tempo > 6 or self.pos[2] > 160 or abs(self.pos[0]) > 90:
            self.estado = "perdida"
            return ("perdida", None, 0)
        return None

    def _fixar(self, direcao, altura_ponta=None):
        if altura_ponta is not None:
            # Recua a flecha ao longo da direção até a ponta ficar logo abaixo do chão.
            ponta = self.pos + direcao * PONTA
            if direcao[1] < -1e-3:
                k = (ponta[1] - altura_ponta) / -direcao[1]
                self.pos = self.pos - direcao * (-k)
        else:
            self.pos = self.pos + direcao * PENETRACAO
        yaw, pitch = m3.angulos_de(direcao)
        self.m_fixa = m3.compor(m3.translacao(*self.pos), m3.orientacao(yaw, pitch))


def angulo_para(origem, alvo, velocidade, iteracoes=30):
    """(yaw, pitch) para acertar `alvo` saindo de `origem` com `velocidade`, sem vento.

    Yaw pela direção horizontal; pitch por bisseção, simulando só a gravidade até o plano do alvo.
    """
    origem, alvo = np.asarray(origem, float), np.asarray(alvo, float)
    delta = alvo - origem
    yaw = math.atan2(delta[0], delta[2])
    horizontal = math.hypot(delta[0], delta[2])

    def altura_ao_chegar(pitch):
        vh, vy = velocidade * math.cos(pitch), velocidade * math.sin(pitch)
        t = horizontal / vh
        return origem[1] + vy * t - 0.5 * GRAVIDADE * t * t

    baixo, alto = -0.5, 0.7
    for _ in range(iteracoes):
        meio = (baixo + alto) / 2
        if altura_ao_chegar(meio) < alvo[1]:
            baixo = meio
        else:
            alto = meio
    return yaw, (baixo + alto) / 2
