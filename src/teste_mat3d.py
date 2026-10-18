"""Verificações rápidas das transformações e da projeção. Uso: python src/teste_mat3d.py"""
import math

import numpy as np

import mat3d as m3


def perto(a, b, tol=1e-9):
    return np.allclose(a, b, atol=tol)


def testar():
    p = (1.0, 0.0, 0.0)
    # Ordem importa: T·R gira e depois translada; R·T translada e depois gira.
    tr = m3.compor(m3.translacao(0, 0, 5), m3.rot_y(math.pi / 2))
    rt = m3.compor(m3.rot_y(math.pi / 2), m3.translacao(0, 0, 5))
    assert perto(m3.aplicar_ponto(tr, p), (0, 0, 4))
    assert perto(m3.aplicar_ponto(rt, p), (5, 0, -1))

    # Escala é aplicada antes da rotação em T·R·S.
    trs = m3.compor(m3.translacao(1, 2, 3), m3.rot_z(math.pi / 2), m3.escala(2))
    assert perto(m3.aplicar_ponto(trs, p), (1, 4, 3))

    # direcao() e orientacao() concordam, e angulos_de() é o inverso.
    yaw, pitch = 0.4, -0.2
    assert perto(m3.aplicar_ponto(m3.orientacao(yaw, pitch), (0, 0, 1)), m3.direcao(yaw, pitch))
    assert perto(m3.angulos_de(m3.direcao(yaw, pitch)), (yaw, pitch))

    # A câmera leva um ponto à sua frente para o eixo +z e ele projeta no centro da tela.
    pos = np.array((2.0, 1.5, -3.0))
    v = m3.matriz_visao(pos, yaw, pitch)
    alvo = pos + 10 * m3.direcao(yaw, pitch)
    assert perto(m3.aplicar_ponto(v, alvo), (0, 0, 10))
    assert perto(m3.projetar(m3.aplicar_ponto(v, alvo), 500, (640, 360)), (640, 360))

    # Um ponto acima do eixo óptico aparece acima do centro (y de tela menor).
    acima = m3.projetar(np.array((0.0, 1.0, 10.0)), 500, (640, 360))
    assert acima[1] < 360

    # Recorte no plano near mantém só a parte da frente.
    tri = [np.array(q, float) for q in ((0, 0, -1), (1, 0, 2), (-1, 0, 2))]
    recortado = m3.recortar_near(tri, 0.5)
    assert len(recortado) == 4 and all(q[2] >= 0.5 - 1e-9 for q in recortado)

    # Sombra planar: o ponto cai no plano do chão, deslizando ao longo da direção da luz.
    luz = np.array((-0.45, 0.8, -0.35))
    luz /= np.linalg.norm(luz)
    ponto = np.array((2.0, 3.0, 5.0))
    sombra = m3.aplicar_ponto(m3.sombra_planar(luz, 0.02), ponto)
    assert perto(sombra[1], 0.02)
    assert perto(np.cross(ponto - sombra, luz), 0, tol=0.03)

    # Interpolação e easing preservam os extremos.
    for f in (m3.ease_in, m3.ease_out, m3.ease_in_out):
        assert perto(f(0.0), 0) and perto(f(1.0), 1)
    assert perto(m3.vai_e_volta(1.5, 1.0), 0.5) and perto(m3.vai_e_volta(0.5, 1.0), 0.5)
    print("mat3d: todos os testes passaram")


if __name__ == "__main__":
    testar()
