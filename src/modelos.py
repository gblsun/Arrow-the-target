"""Malhas poliédricas low-poly do cenário, geradas proceduralmente.

Cada primitiva sai com as faces orientadas para fora (normal apontando para longe do
centróide da primitiva), o que permite descartar faces de costas no renderizador.
"""
import math

import numpy as np

import mat3d as m3

# Paleta: floresta no fim de tarde, madeira e tecidos de feira medieval.
MADEIRA = (122, 84, 50)
MADEIRA_ESCURA = (86, 58, 36)
MADEIRA_CLARA = (160, 118, 72)
PALHA = (214, 182, 104)
TRONCO = (92, 66, 46)
PINHEIRO = [(46, 92, 58), (40, 84, 52), (54, 104, 64)]
FOLHAGEM = [(78, 122, 54), (92, 134, 60), (66, 110, 50)]
PEDRA = (128, 126, 118)
CORDA = (190, 168, 120)
FERRO = (150, 150, 158)
PENA = (200, 52, 44)
TECIDOS = [(150, 36, 40), (40, 70, 130), (196, 150, 40)]
ANEIS = [(236, 232, 220), (40, 40, 44), (52, 108, 196), (206, 48, 44), (238, 196, 52)]
RAIOS_ANEIS = [1.0, 0.8, 0.6, 0.4, 0.2]
PONTOS_ANEIS = [2, 4, 6, 8, 10]


class Malha:
    def __init__(self, vertices, faces, cores, vies=None):
        self.vertices = np.asarray(vertices, dtype=float).reshape(-1, 3)
        self.faces = [tuple(f) for f in faces]
        self.cores = [tuple(c) for c in cores]
        self.vies = list(vies) if vies is not None else [0.0] * len(self.faces)

    def transformada(self, m):
        return Malha(m3.aplicar(m, self.vertices), self.faces, self.cores, self.vies)

    def colorida(self, cor):
        return Malha(self.vertices, self.faces, [cor] * len(self.faces), self.vies)


def juntar(*malhas):
    vertices, faces, cores, vies = [], [], [], []
    base = 0
    for malha in malhas:
        vertices.append(malha.vertices)
        faces += [tuple(i + base for i in f) for f in malha.faces]
        cores += malha.cores
        vies += malha.vies
        base += len(malha.vertices)
    return Malha(np.vstack(vertices), faces, cores, vies)


def _orientada(vertices, faces, cor):
    """Cria uma primitiva convexa invertendo as faces cuja normal aponta para dentro."""
    v = np.asarray(vertices, dtype=float)
    centro = v.mean(axis=0)
    ajustadas = []
    for f in faces:
        a, b, c = v[f[0]], v[f[1]], v[f[2]]
        normal = np.cross(b - a, c - a)
        if np.dot(normal, v[list(f)].mean(axis=0) - centro) < 0:
            f = tuple(reversed(f))
        ajustadas.append(f)
    cores = cor if isinstance(cor, list) else [cor] * len(ajustadas)
    return Malha(v, ajustadas, cores)


# ---------------------------------------------------------------- primitivas

def caixa(sx, sy, sz, cor, centro=(0, 0, 0)):
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    cx, cy, cz = centro
    v = [(cx + x, cy + y, cz + z) for x in (-hx, hx) for y in (-hy, hy) for z in (-hz, hz)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    return _orientada(v, faces, cor)


def prisma(n, raio, altura, cor, y0=0.0, raio_topo=None, tampas=True):
    """Prisma (ou tronco de cone) vertical com base em y0."""
    raio_topo = raio if raio_topo is None else raio_topo
    v = []
    for i in range(n):
        a = 2 * math.pi * i / n
        v.append((raio * math.cos(a), y0, raio * math.sin(a)))
    for i in range(n):
        a = 2 * math.pi * i / n
        v.append((raio_topo * math.cos(a), y0 + altura, raio_topo * math.sin(a)))
    faces = [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
    if tampas:
        faces += [tuple(range(n)), tuple(range(n, 2 * n))]
    return _orientada(v, faces, cor)


def cone(n, raio, altura, cor, y0=0.0):
    v = [(raio * math.cos(2 * math.pi * i / n), y0, raio * math.sin(2 * math.pi * i / n)) for i in range(n)]
    v.append((0, y0 + altura, 0))
    faces = [(i, (i + 1) % n, n) for i in range(n)] + [tuple(range(n))]
    return _orientada(v, faces, cor)


def esfera(n_lon, n_lat, raio, cores):
    """Esfera facetada (latitude/longitude). `cores` é sorteada por face em ciclo."""
    v = [(0, raio, 0)]
    for j in range(1, n_lat):
        phi = math.pi * j / n_lat
        for i in range(n_lon):
            th = 2 * math.pi * i / n_lon
            v.append((raio * math.sin(phi) * math.cos(th), raio * math.cos(phi), raio * math.sin(phi) * math.sin(th)))
    v.append((0, -raio, 0))
    sul = len(v) - 1
    faces = [(0, 1 + i, 1 + (i + 1) % n_lon) for i in range(n_lon)]
    for j in range(n_lat - 2):
        a, b = 1 + j * n_lon, 1 + (j + 1) * n_lon
        faces += [(a + i, b + i, b + (i + 1) % n_lon, a + (i + 1) % n_lon) for i in range(n_lon)]
    ultimo = 1 + (n_lat - 2) * n_lon
    faces += [(ultimo + i, sul, ultimo + (i + 1) % n_lon) for i in range(n_lon)]
    lista = [cores[k % len(cores)] for k in range(len(faces))]
    return _orientada(v, faces, lista)


def disco_frontal(n, raio, z, cor, vies):
    """Polígono plano no plano z, com a frente voltada para -z (para o jogador)."""
    v = [(raio * math.cos(2 * math.pi * i / n), raio * math.sin(2 * math.pi * i / n), z) for i in range(n)]
    # Ordem horária vista de -z => normal (b-a)x(c-a) aponta para -z.
    face = tuple(reversed(range(n)))
    return Malha(v, [face], [cor], [vies])


def poligono_chao(pontos_xz, cor, altura=0.01):
    """Decalque plano no chão, voltado para cima."""
    v = [(x, altura, z) for x, z in pontos_xz]
    # Garante normal +y (ordem anti-horária vista de cima, com z para a frente).
    a, b, c = np.array(v[0]), np.array(v[1]), np.array(v[2])
    face = tuple(range(len(v)))
    if np.cross(b - a, c - a)[1] < 0:
        face = tuple(reversed(face))
    return Malha(v, [face], [cor])


def elipse_chao(cx, cz, rx, rz, cor, n=10):
    return poligono_chao(
        [(cx + rx * math.cos(2 * math.pi * i / n), cz + rz * math.sin(2 * math.pi * i / n)) for i in range(n)], cor
    )


def tabua(p0, p1, largura, espessura, cor):
    """Caixa alongada ligando dois pontos (pernas, cordas, vigas)."""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    eixo = p1 - p0
    comprimento = float(np.linalg.norm(eixo))
    yaw, pitch = m3.angulos_de(eixo)
    m = m3.compor(m3.translacao(*((p0 + p1) / 2)), m3.orientacao(yaw, pitch))
    return caixa(largura, espessura, comprimento, cor).transformada(m)


# ---------------------------------------------------------------- objetos do cenário

def pinheiro(rng):
    altura = rng.uniform(5.5, 9.0)
    cor = PINHEIRO[rng.integers(len(PINHEIRO))]
    partes = [prisma(5, 0.22, altura * 0.35, TRONCO, tampas=False)]
    niveis = 3
    for k in range(niveis):
        base = altura * (0.25 + 0.22 * k)
        raio = altura * (0.32 - 0.07 * k)
        tom = tuple(min(255, int(c * (0.9 + 0.1 * k))) for c in cor)
        partes.append(cone(6, raio, altura * 0.4, tom, y0=base))
    return juntar(*partes), altura


def arvore_copa(rng):
    altura = rng.uniform(4.0, 6.5)
    raio = rng.uniform(1.6, 2.4)
    tons = [FOLHAGEM[(i + rng.integers(3)) % 3] for i in range(3)]
    copa = esfera(6, 4, raio, tons).transformada(
        m3.compor(m3.translacao(0, altura - raio * 0.6, 0), m3.escala(1.0, 0.85, 1.0))
    )
    tronco = prisma(5, 0.25, altura - raio * 0.8, TRONCO, raio_topo=0.18, tampas=False)
    return juntar(tronco, copa), altura


def pedra(rng):
    s = rng.uniform(0.4, 1.1)
    return esfera(5, 3, 1.0, [PEDRA, (116, 114, 106)]).transformada(
        m3.compor(m3.translacao(0, s * 0.25, 0), m3.rot_y(rng.uniform(0, 6.28)), m3.escala(s * 1.3, s * 0.6, s))
    )


def cerca(comprimento, n_postes=None):
    """Cerca ao longo do eixo x, começando na origem."""
    n_postes = n_postes or max(2, int(comprimento / 2.5) + 1)
    partes = []
    for i in range(n_postes):
        x = comprimento * i / (n_postes - 1)
        partes.append(caixa(0.16, 1.1, 0.16, MADEIRA_ESCURA, centro=(x, 0.55, 0)))
    for y in (0.45, 0.85):
        partes.append(caixa(comprimento, 0.1, 0.06, MADEIRA, centro=(comprimento / 2, y, 0)))
    return juntar(*partes)


def plataforma():
    """Piso de madeira do posto de tiro, com fardo de palha e suporte de flechas."""
    tabuas = [caixa(0.55, 0.12, 2.4, MADEIRA_CLARA if i % 2 else MADEIRA, centro=(-2.2 + i * 0.55, 0.06, 0))
              for i in range(9)]
    fardo = caixa(1.1, 0.6, 0.7, PALHA, centro=(3.2, 0.3, 0.2))
    aljava = juntar(
        caixa(0.08, 1.0, 0.08, MADEIRA_ESCURA, centro=(-3.0, 0.5, 0.3)),
        caixa(0.08, 1.0, 0.08, MADEIRA_ESCURA, centro=(-3.0, 0.5, -0.3)),
        caixa(0.08, 0.08, 0.7, MADEIRA, centro=(-3.0, 0.95, 0)),
    )
    return juntar(*tabuas, fardo, aljava)


def poste_estandarte(altura=4.5):
    return juntar(
        prisma(6, 0.08, altura, MADEIRA_ESCURA),
        cone(6, 0.12, 0.25, FERRO, y0=altura),
    )


def estandarte(cor, altura=4.5):
    """Flâmula presa ao poste (origem no eixo do poste); gira em torno de y com o vento."""
    pano = caixa(1.2, 1.5, 0.04, cor, centro=(0.65, altura - 0.95, 0))
    faixa = caixa(1.2, 0.18, 0.05, ANEIS[4], centro=(0.65, altura - 1.55, 0))
    return juntar(pano, faixa)


def alvo(raio=1.0, com_cavalete=True):
    """Alvo de palha com anéis coloridos. Origem no centro dos anéis; frente voltada para -z."""
    k = raio
    partes = [prisma(14, 1.08 * k, 0.32 * k, PALHA).transformada(m3.compor(m3.translacao(0, 0, 0.0), m3.rot_x(math.pi / 2)))]
    # Anéis como discos planos à frente da palha: o menor fica mais à frente (vies maior).
    for i, (r, cor) in enumerate(zip(RAIOS_ANEIS, ANEIS)):
        partes.append(disco_frontal(16, r * k, -0.005 - 0.004 * i, cor, vies=0.01 * (i + 1)))
    if com_cavalete:
        partes += [
            tabua((-0.7 * k, 0.2 * k, -0.05), (-0.9 * k, -1.4, -0.35), 0.1, 0.1, MADEIRA),
            tabua((0.7 * k, 0.2 * k, -0.05), (0.9 * k, -1.4, -0.35), 0.1, 0.1, MADEIRA),
            tabua((0, 0.6 * k, 0.33), (0, -1.4, 1.1), 0.1, 0.1, MADEIRA_ESCURA),
        ]
    return juntar(*partes)


def alvo_pendurado(raio, comprimento_corda):
    """Alvo pendurado: origem no pivô (viga), centro do alvo em (0, -comprimento_corda, 0)."""
    corpo = alvo(raio, com_cavalete=False).transformada(m3.translacao(0, -comprimento_corda, 0))
    cordas = juntar(
        tabua((-0.35, 0, 0.05), (-0.35 * raio, -comprimento_corda + 0.8 * raio, 0.05), 0.04, 0.04, CORDA),
        tabua((0.35, 0, 0.05), (0.35 * raio, -comprimento_corda + 0.8 * raio, 0.05), 0.04, 0.04, CORDA),
    )
    return juntar(corpo, cordas)


def forca_de_madeira(vao, altura):
    """Pórtico de madeira (dois postes e uma viga) centrado na origem, ao longo de x."""
    return juntar(
        caixa(0.22, altura, 0.22, MADEIRA_ESCURA, centro=(-vao / 2, altura / 2, 0)),
        caixa(0.22, altura, 0.22, MADEIRA_ESCURA, centro=(vao / 2, altura / 2, 0)),
        caixa(vao + 0.6, 0.22, 0.26, MADEIRA, centro=(0, altura, 0)),
        tabua((-vao / 2, altura - 0.9, 0), (-vao / 2 + 0.8, altura, 0), 0.12, 0.12, MADEIRA),
        tabua((vao / 2, altura - 0.9, 0), (vao / 2 - 0.8, altura, 0), 0.12, 0.12, MADEIRA),
    )


def trilho(comprimento):
    """Trilho baixo por onde corre o alvo móvel, ao longo de x e centrado na origem."""
    return juntar(
        caixa(comprimento, 0.12, 0.2, MADEIRA_ESCURA, centro=(0, 0.1, -0.4)),
        caixa(comprimento, 0.12, 0.2, MADEIRA_ESCURA, centro=(0, 0.1, 0.4)),
        *[caixa(0.3, 0.06, 1.2, MADEIRA, centro=(x, 0.03, 0))
          for x in np.linspace(-comprimento / 2, comprimento / 2, int(comprimento / 1.5) + 1)],
    )


def flecha():
    """Flecha ao longo de +z, com a ponta em z = +0.45."""
    return juntar(
        caixa(0.025, 0.025, 0.8, MADEIRA_CLARA, centro=(0, 0, 0)),
        cone(4, 0.04, 0.1, FERRO).transformada(m3.compor(m3.translacao(0, 0, 0.35), m3.rot_x(math.pi / 2))),
        caixa(0.005, 0.07, 0.16, PENA, centro=(0, 0, -0.32)),
        caixa(0.07, 0.005, 0.16, (236, 230, 214), centro=(0, 0, -0.32)),
    )


def morro(rng, raio, altura, cor):
    return cone(7, raio, altura, cor).transformada(m3.rot_y(rng.uniform(0, 6.28)))


def carregar_obj(nome, cor=(150, 150, 150)):
    """Leitor OBJ simplificado (apenas `v` e `f`), adaptado de ref/exercicios/pygame_aulas_1_a_9."""
    vertices, faces = [], []
    with open(nome, encoding="utf-8") as arquivo:
        for linha in arquivo:
            partes = linha.split()
            if not partes or partes[0].startswith("#"):
                continue
            if partes[0] == "v":
                vertices.append(tuple(float(valor) for valor in partes[1:4]))
            elif partes[0] == "f":
                faces.append(tuple(int(item.split("/")[0]) - 1 for item in partes[1:]))
    return Malha(vertices, faces, [cor] * len(faces))
