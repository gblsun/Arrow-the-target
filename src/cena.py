"""Montagem da clareira na floresta: cenário estático, alvos animados e estandartes."""
import math

import numpy as np

import mat3d as m3
import modelos as mod
from render import Lote

# Postos de tiro: (z do posto, distância nominal até a linha de alvos, multiplicador de pontos)
LINHA_ALVOS = 40.0
POSTOS = [(LINHA_ALVOS - 15, 15, 1.0), (LINHA_ALVOS - 25, 25, 1.5), (LINHA_ALVOS - 40, 40, 2.0)]
ALTURA_OLHOS = 1.65
LIMITE_LATERAL = 5.0
CLAREIRA = (-15.0, 15.0, -8.0, 62.0)  # x_min, x_max, z_min, z_max


class Alvo:
    """Alvo com matriz de modelo dependente do tempo. O centro dos anéis fica em `centro_local`."""

    def __init__(self, nome, malha, raio, centro_local=(0, 0, 0)):
        self.nome = nome
        self.malha = malha
        self.raio = raio
        self.centro_local = np.array(centro_local, dtype=float)
        self.matriz = np.eye(4)
        self.inversa = np.eye(4)

    def movimento(self, t):
        raise NotImplementedError

    def atualizar(self, t):
        self.matriz = self.movimento(t)
        self.inversa = np.linalg.inv(self.matriz)

    def centro_mundo(self):
        return m3.aplicar_ponto(self.matriz, self.centro_local)

    def intersecao(self, a, b):
        """Segmento a->b (mundo) contra o plano frontal dos anéis.

        Devolve (u, ponto_local, distancia_ao_centro) ou None. u ∈ [0, 1] ao longo do segmento.
        """
        la, lb = m3.aplicar_ponto(self.inversa, a), m3.aplicar_ponto(self.inversa, b)
        zf = self.centro_local[2] - 0.02
        if not (la[2] < zf <= lb[2]):
            return None
        u = (zf - la[2]) / (lb[2] - la[2])
        p = la + (lb - la) * u
        r = math.hypot(p[0] - self.centro_local[0], p[1] - self.centro_local[1])
        if r > self.raio * 1.08:
            return None
        return u, p, r

    def pontos(self, r):
        for raio_anel, pontos in zip(reversed(mod.RAIOS_ANEIS), reversed(mod.PONTOS_ANEIS)):
            if r <= raio_anel * self.raio:
                return pontos
        return 0  # acertou só a palha da borda


class AlvoFixo(Alvo):
    def __init__(self, nome, posicao, yaw=0.0):
        super().__init__(nome, mod.alvo(1.0), 1.0)
        self.m = m3.compor(m3.translacao(*posicao), m3.rot_y(yaw))

    def movimento(self, t):
        return self.m


class AlvoDeslizante(Alvo):
    """Corre sobre um trilho entre dois pontos com ease-in-out (aula 10)."""

    def __init__(self, nome, a, b, periodo):
        super().__init__(nome, mod.alvo(0.8), 0.8)
        self.a, self.b, self.periodo = np.array(a, float), np.array(b, float), periodo

    def movimento(self, t):
        u = m3.ease_in_out(m3.vai_e_volta(t, self.periodo))
        return m3.translacao(*m3.lerp(self.a, self.b, u))


class AlvoPendulo(Alvo):
    """Pendurado numa viga: rotação em torno do pivô (composição hierárquica T(pivô)·R(θ))."""

    def __init__(self, nome, pivo, corda, amplitude, periodo):
        raio = 0.6
        super().__init__(nome, mod.alvo_pendurado(raio, corda), raio, centro_local=(0, -corda, 0))
        self.pivo, self.amplitude, self.periodo = pivo, amplitude, periodo

    def movimento(self, t):
        theta = self.amplitude * math.sin(2 * math.pi * t / self.periodo)
        giro = 0.25 * math.sin(2 * math.pi * t / (self.periodo * 1.7))
        return m3.compor(m3.translacao(*self.pivo), m3.rot_z(theta), m3.rot_y(giro))


class Estandarte:
    def __init__(self, posicao, cor):
        self.posicao = posicao
        self.malha = mod.estandarte(cor)
        self.fase = posicao[0] * 0.7 + posicao[2] * 0.3

    def matriz(self, t, vento, agitado=False):
        # O eixo +x local da flâmula aponta para (vento, 0, 1.6): rot_y(a) leva +x a (cos a, 0, -sin a).
        base = math.atan2(-1.6, vento)
        amplitude = 0.35 if agitado else 0.12 + 0.03 * abs(vento)
        tremor = amplitude * math.sin(t * (6 if agitado else 2.5) + self.fase)
        return m3.compor(m3.translacao(*self.posicao), m3.rot_y(base + tremor))


class Cena:
    def __init__(self, semente=7):
        rng = np.random.default_rng(semente)
        self.troncos = []  # (x, z, raio, altura) para colisão das flechas
        estaticos, chao = [], []

        self._floresta(rng, estaticos, chao)

        for i, (z, _, _) in enumerate(POSTOS):
            estaticos.append((mod.plataforma(), m3.translacao(0, 0, z), False))
            chao.append((mod.poligono_chao([(-4.5, z - 1.8), (4.5, z - 1.8), (4.5, z + 1.8), (-4.5, z + 1.8)], (124, 104, 70)), np.eye(4), False))
        # Trilha de terra ligando os postos à linha de alvos.
        chao.append((mod.poligono_chao([(-1.6, -6), (1.6, -6), (2.2, 58), (-2.2, 58)], (138, 116, 78), altura=0.005), np.eye(4), False))

        # Cercas laterais delimitando a raia.
        for lado in (-1, 1):
            estaticos.append((mod.cerca(50), m3.compor(m3.translacao(lado * 13.5, 0, 6), m3.rot_y(-math.pi / 2)), False))

        self.alvos = [
            AlvoFixo("Alvo da esquerda", (-4.0, 1.45, LINHA_ALVOS)),
            AlvoFixo("Alvo da direita", (4.5, 1.45, LINHA_ALVOS + 2.5)),
            AlvoDeslizante("Alvo do trilho", (-7.5, 1.0, LINHA_ALVOS + 10), (7.5, 1.0, LINHA_ALVOS + 10), periodo=3.2),
            AlvoPendulo("Alvo pendurado", (-9.5, 4.6, LINHA_ALVOS + 4), corda=2.2, amplitude=0.35, periodo=2.6),
        ]
        estaticos.append((mod.trilho(17), m3.translacao(0, 0, LINHA_ALVOS + 10.4), False))
        estaticos.append((mod.forca_de_madeira(2.4, 4.6), m3.translacao(-9.5, 0, LINHA_ALVOS + 4), False))
        for x, z in ((-4.0, LINHA_ALVOS), (4.5, LINHA_ALVOS + 2.5)):
            chao.append((mod.elipse_chao(x, z + 0.4, 1.3, 0.9, (66, 90, 44)), np.eye(4), False))
        chao.append((mod.elipse_chao(0, LINHA_ALVOS + 10.4, 9.5, 1.2, (70, 92, 46)), np.eye(4), False))

        # Estandartes junto aos postos e à linha de alvos.
        self.estandartes = []
        for i, (x, z) in enumerate([(-6.0, POSTOS[0][0] + 1), (6.0, POSTOS[0][0] + 1), (-6.0, POSTOS[2][0] + 1),
                                    (6.0, POSTOS[2][0] + 1), (-12, LINHA_ALVOS + 6), (12, LINHA_ALVOS + 6)]):
            estaticos.append((mod.poste_estandarte(), m3.translacao(x, 0, z), False))
            self.estandartes.append(Estandarte((x, 0, z), mod.TECIDOS[i % 3]))

        self.lote_estatico = Lote(estaticos)
        self.lote_chao = Lote(chao)
        self.direcao_sol = m3.direcao(math.radians(-38), math.radians(9))

    def _floresta(self, rng, estaticos, chao):
        x0, x1, z0, z1 = CLAREIRA
        plantadas = 0
        tentativas = 0
        while plantadas < 120 and tentativas < 5000:
            tentativas += 1
            x, z = rng.uniform(-70, 70), rng.uniform(-25, 140)
            margem = rng.uniform(0, 3)
            if x0 - margem < x < x1 + margem and z0 - margem < z < z1 + margem:
                continue
            if rng.random() < 0.55:
                malha, altura = mod.pinheiro(rng)
                raio = 0.25
            else:
                malha, altura = mod.arvore_copa(rng)
                raio = 0.3
            escala = rng.uniform(0.85, 1.25)
            m = m3.compor(m3.translacao(x, 0, z), m3.rot_y(rng.uniform(0, 2 * math.pi)), m3.escala(escala))
            estaticos.append((malha, m, False))
            chao.append((mod.elipse_chao(x + 0.8, z + 0.6, 1.8 * escala, 1.3 * escala, (58, 84, 38), n=8), np.eye(4), False))
            self.troncos.append((x, z, raio * escala, altura * escala))
            plantadas += 1
        # Pedras espalhadas nas bordas da clareira.
        for _ in range(26):
            x = rng.choice([-1, 1]) * rng.uniform(9, 20)
            z = rng.uniform(-6, 70)
            estaticos.append((mod.pedra(rng), m3.translacao(x, 0, z), False))
        # Morros ao fundo, cobertos de neblina.
        for i in range(9):
            ang = math.radians(-80 + i * 20)
            dist = rng.uniform(170, 210)
            m = m3.translacao(math.sin(ang) * dist, -2, math.cos(ang) * dist + 30)
            estaticos.append((mod.morro(rng, rng.uniform(45, 70), rng.uniform(22, 40), (84, 112, 78)), m, False))

    def atualizar(self, t):
        for alvo in self.alvos:
            alvo.atualizar(t)

    def lote_dinamico(self, t, vento, foco, extras):
        itens = [(a.malha, a.matriz, a is foco) for a in self.alvos]
        for e in self.estandartes:
            perto_foco = foco is not None and abs(e.posicao[2] - LINHA_ALVOS) < 10
            itens.append((e.malha, e.matriz(t, vento, agitado=perto_foco), False))
        return Lote(itens + extras)

    def alvo_na_mira(self, origem, direcao, alcance=120.0):
        """Seleção por raio: o alvo mais próximo cruzado pela linha de visada."""
        fim = origem + direcao * alcance
        melhor = None
        for alvo in self.alvos:
            hit = alvo.intersecao(origem, fim)
            if hit and hit[2] <= alvo.raio and (melhor is None or hit[0] < melhor[0]):
                melhor = (hit[0], alvo)
        return melhor[1] if melhor else None
