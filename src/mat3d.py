"""Transformações geométricas 3D em coordenadas homogêneas (matrizes 4x4) e interpolação.

Convenção do mundo: x para a direita, y para cima, z para a frente (para longe do jogador).
"""
import math
from functools import reduce

import numpy as np


# ---------------------------------------------------------------- matrizes básicas

def translacao(tx, ty, tz):
    m = np.eye(4)
    m[:3, 3] = (tx, ty, tz)
    return m


def escala(sx, sy=None, sz=None):
    sy = sx if sy is None else sy
    sz = sx if sz is None else sz
    return np.diag((sx, sy, sz, 1.0))


def rot_x(angulo):
    c, s = math.cos(angulo), math.sin(angulo)
    return np.array([[1, 0, 0, 0], [0, c, -s, 0], [0, s, c, 0], [0, 0, 0, 1]], dtype=float)


def rot_y(angulo):
    c, s = math.cos(angulo), math.sin(angulo)
    return np.array([[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1]], dtype=float)


def rot_z(angulo):
    c, s = math.cos(angulo), math.sin(angulo)
    return np.array([[c, -s, 0, 0], [s, c, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=float)


def compor(*matrizes):
    """Compõe da esquerda para a direita: compor(T, R, S) = T·R·S (S é aplicada primeiro)."""
    return reduce(np.matmul, matrizes, np.eye(4))


def aplicar(m, pontos):
    """Aplica a matriz 4x4 a um array (N, 3) de pontos."""
    pontos = np.asarray(pontos, dtype=float)
    return pontos @ m[:3, :3].T + m[:3, 3]


def aplicar_ponto(m, ponto):
    return aplicar(m, np.asarray(ponto, dtype=float)[None, :])[0]


def orientacao(yaw, pitch):
    """Rotação que leva o eixo +z local para a direção (yaw, pitch). Pitch positivo olha para cima."""
    return rot_y(yaw) @ rot_x(-pitch)


def direcao(yaw, pitch):
    cp = math.cos(pitch)
    return np.array((math.sin(yaw) * cp, math.sin(pitch), math.cos(yaw) * cp))


def angulos_de(vetor):
    """Inverso de direcao(): devolve (yaw, pitch) de um vetor."""
    x, y, z = vetor
    return math.atan2(x, z), math.atan2(y, math.hypot(x, z))


# ---------------------------------------------------------------- câmera

def matriz_visao(posicao, yaw, pitch):
    """Mundo -> câmera: inversa de T(posicao)·orientacao(yaw, pitch)."""
    return rot_x(pitch) @ rot_y(-yaw) @ translacao(*(-np.asarray(posicao, dtype=float)))


def distancia_focal(largura, fov_graus):
    return (largura / 2) / math.tan(math.radians(fov_graus) / 2)


def projetar(pontos_camera, focal, centro):
    """Projeção perspectiva de pontos já em coordenadas de câmera (z > 0 à frente)."""
    z = pontos_camera[..., 2]
    sx = centro[0] + focal * pontos_camera[..., 0] / z
    sy = centro[1] - focal * pontos_camera[..., 1] / z
    return np.stack((sx, sy), axis=-1)


def recortar_near(poligono, near):
    """Sutherland-Hodgman contra o plano z = near (coordenadas de câmera)."""
    saida = []
    n = len(poligono)
    for i in range(n):
        a, b = poligono[i], poligono[(i + 1) % n]
        dentro_a, dentro_b = a[2] >= near, b[2] >= near
        if dentro_a:
            saida.append(a)
        if dentro_a != dentro_b:
            t = (near - a[2]) / (b[2] - a[2])
            saida.append(a + (b - a) * t)
    return saida


def sombra_planar(luz, altura=0.02):
    """Projeta pontos no plano y = altura ao longo da direção da luz (sombra projetada).

    P' = P - L * (P.y / L.y): cada ponto desliza pelo raio de luz até tocar o chão.
    """
    lx, ly, lz = luz
    m = np.array([[1, -lx / ly, 0, 0],
                  [0, 0, 0, altura],
                  [0, -lz / ly, 1, 0],
                  [0, 0, 0, 1]], dtype=float)
    return m


# ---------------------------------------------------------------- interpolação (aula 10)

def lerp(a, b, u):
    return a + (b - a) * u


def limitar(valor, minimo=0.0, maximo=1.0):
    return max(minimo, min(maximo, valor))


def ease_in(u):
    return u * u


def ease_out(u):
    return 1 - (1 - u) ** 2


def ease_in_out(u):
    return 2 * u * u if u < 0.5 else 1 - (-2 * u + 2) ** 2 / 2


def vai_e_volta(t, periodo):
    """Parâmetro u em [0, 1] que vai e volta com o tempo (ida em `periodo` segundos)."""
    fase = (t % (2 * periodo)) / periodo
    return fase if fase <= 1 else 2 - fase
