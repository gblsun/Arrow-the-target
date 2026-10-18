"""Testes da lógica de gesto com mãos sintéticas (sem câmera). Uso: python src/teste_entrada.py"""
import os
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pygame

import entrada as en
from entrada import Entrada, FiltroKalman1D
from gestos import FiltroOneEuro, Leitura, Mao, mao_sintetica


def mao(cx, cy, s=0.12, fechada=False, lado=""):
    return mao_sintetica(cx, cy, s, fechada=fechada, lado=lado)


def polegar_cima(cx, cy, s=0.12, lado="Right"):
    m = mao(cx, cy, s, fechada=True, lado=lado)
    p = list(m.pontos)
    p[3] = (cx + 0.2 * s, cy - 0.2 * s)
    p[4] = (cx + 0.2 * s, cy - 0.6 * s)
    return Mao(p, lado)


class Camera:
    """Rastreador falso: cada `mostrar` vira uma leitura nova."""
    ativo = True

    def __init__(self):
        self._leitura, self.n = Leitura(), 0

    def mostrar(self, maos):
        self.n += 1
        self._leitura = Leitura(self.n, maos, time.monotonic())

    def leitura(self):
        return self._leitura


def nova_entrada(lateral=True):
    frontal, lat = Camera(), (Camera() if lateral else None)
    return Entrada(frontal, lat, 1280, 720), frontal, lat


def quadro(e, frontal, lateral, x_corda, fechada, dt=1 / 30):
    """Arco (esquerda) fixo; a mão da corda se afasta em x na imagem lateral."""
    frontal.mostrar([mao(0.45, 0.5, 0.15, False, "Left"), mao(0.55, 0.45, 0.12, fechada, "Right")])
    if lateral:
        lateral.mostrar([mao(0.30, 0.5, 0.1), mao(x_corda, 0.5, 0.1, fechada)])
    return e.atualizar(dt)


def teste_kalman():
    f = FiltroKalman1D()
    f.reiniciar(0.0)
    valores = [f.atualizar(1.0) for _ in range(30)]
    assert all(b >= a for a, b in zip(valores, valores[1:])), "deve convergir sem oscilar"
    assert valores[-1] > 0.95
    ruido = np.random.default_rng(1).normal(0.5, 0.1, 200)
    f.reiniciar(0.5)
    saida = [f.atualizar(v) for v in ruido]
    assert np.std(saida[50:]) < np.std(ruido) * 0.6, "deve reduzir o ruído"


def teste_disparo():
    e, fr, la = nova_entrada()
    quadro(e, fr, la, 0.38, False)
    cmd = quadro(e, fr, la, 0.38, True)
    assert cmd.puxando and cmd.confirmar
    for i in range(12):
        cmd = quadro(e, fr, la, 0.38 + 0.03 * i, True)
    assert cmd.forca > 0.6, cmd.forca
    cmd = quadro(e, fr, la, 0.71, False)
    assert cmd.disparou and cmd.forca_disparo > 0.6 and not cmd.puxando


def teste_forca_minima():
    e, fr, la = nova_entrada()
    quadro(e, fr, la, 0.38, False)
    quadro(e, fr, la, 0.38, True)
    quadro(e, fr, la, 0.40, True)
    cmd = quadro(e, fr, la, 0.40, False)
    assert not cmd.disparou, "puxada curta não deve disparar"


def teste_cancela_sem_mao():
    e, fr, la = nova_entrada()
    quadro(e, fr, la, 0.38, False)
    quadro(e, fr, la, 0.38, True)
    for i in range(8):
        quadro(e, fr, la, 0.4 + 0.04 * i, True)
    # Perda curta (< TOLERANCIA_PERDA): a puxada continua.
    fr.mostrar([])
    la.mostrar([])
    cmd = e.atualizar(1 / 30)
    assert cmd.puxando and not cmd.disparou, "perda curta não cancela"
    time.sleep(en.TOLERANCIA_PERDA + 0.05)
    fr.mostrar([])
    la.mostrar([])
    cmd = e.atualizar(1 / 30)
    assert not cmd.puxando and not cmd.disparou, "perder as mãos por mais tempo cancela sem atirar"


def teste_histerese():
    e, fr, _ = nova_entrada(lateral=False)
    mao_meio = mao(0.55, 0.45, 0.12, False, "Right")
    p = list(mao_meio.pontos)
    for i in (8, 12, 16, 20):  # curvatura ~1.3: entre CURVA_FECHA e CURVA_ABRE
        p[i] = (0.55, 0.45 + 0.12 - 1.3 * 0.12)
    p[4] = (p[8][0] + 0.06, p[8][1])  # pinça aberta
    intermediaria = Mao(p, "Right")
    assert en.CURVA_FECHA < intermediaria.curvatura < en.CURVA_ABRE
    arco = mao(0.45, 0.5, 0.15, False, "Left")
    fr.mostrar([arco, intermediaria])
    e.atualizar(1 / 30)
    assert not e.mao_fechada, "aberta continua aberta na zona intermediária"
    fr.mostrar([arco, mao(0.55, 0.45, 0.12, True, "Right")])
    e.atualizar(1 / 30)
    assert e.mao_fechada
    fr.mostrar([arco, intermediaria])
    e.atualizar(1 / 30)
    assert e.mao_fechada, "fechada continua fechada na zona intermediária"


def calibrar(e, fr, la, x_corda, segundos):
    for _ in range(int(segundos * 60)):
        fr.mostrar([mao(0.45, 0.5, 0.15, False, "Left"), mao(0.55, 0.45, 0.12, True, "Right")])
        la.mostrar([mao(0.30, 0.5, 0.1), mao(x_corda, 0.5, 0.1, True)])
        e.calibrar(1 / 60)


def teste_calibracao():
    e, fr, la = nova_entrada()
    e.reiniciar_calibracao()
    calibrar(e, fr, la, 0.38, en.TEMPO_PREPARO + en.TEMPO_ETAPA + 0.3)
    assert e.etapa == 1, e.etapa
    calibrar(e, fr, la, 0.70, en.TEMPO_PREPARO + en.TEMPO_ETAPA + 0.3)
    assert e.etapa == 2 and e.calibrado
    esc = e.escalas["lateral"]
    assert abs(esc.repouso - 0.08) < 1e-6 and abs(esc.cheia - 0.40) < 1e-6, esc
    assert e.indice_corda_lateral == 1
    assert abs(e.centro[0] - 0.45) < 1e-6


def teste_puxada_curta():
    e, fr, la = nova_entrada()
    e.reiniciar_calibracao()
    calibrar(e, fr, la, 0.38, en.TEMPO_PREPARO + en.TEMPO_ETAPA + 0.3)
    calibrar(e, fr, la, 0.40, en.TEMPO_PREPARO + en.TEMPO_ETAPA + 0.3)
    assert e.etapa == 1 and "curta" in e.aviso, (e.etapa, e.aviso)


def teste_continuidade_lateral():
    e, _, la = nova_entrada()
    e.indice_corda_lateral = 1
    arco, corda = mao(0.40, 0.5, 0.1), mao(0.46, 0.5, 0.1)
    e._papeis_lateral([arco, corda])
    # A corda passa um pouco para a esquerda do arco (cruzamento): continua sendo a corda.
    corda2 = mao(0.38, 0.52, 0.1)
    a, c = e._papeis_lateral([arco, corda2])
    assert c is corda2 and a is arco


def teste_polegar():
    assert polegar_cima(0.5, 0.5).polegar == "cima"
    assert mao(0.5, 0.5, fechada=False).polegar is None
    e, fr, _ = nova_entrada(lateral=False)
    resultado = None
    for _ in range(60):
        fr.mostrar([polegar_cima(0.55, 0.45)])
        resultado = e.gesto_polegar(1 / 60) or resultado
    assert resultado == "cima"


def teste_exportar_importar():
    e, fr, la = nova_entrada()
    e.reiniciar_calibracao()
    calibrar(e, fr, la, 0.38, en.TEMPO_PREPARO + en.TEMPO_ETAPA + 0.3)
    calibrar(e, fr, la, 0.70, en.TEMPO_PREPARO + en.TEMPO_ETAPA + 0.3)
    dados = e.exportar_calibracao()
    outra, _, _ = nova_entrada()
    assert outra.importar_calibracao(dados) and outra.calibrado
    assert outra.escalas["lateral"] == e.escalas["lateral"] and outra.centro == e.centro
    assert not outra.importar_calibracao({"centro": [0.5]})


def mao_dedos(cx, cy, s, dedos, lado="Left", inclinacao=0.0):
    return mao_sintetica(cx, cy, s, dedos=dedos, lado=lado, inclinacao=inclinacao)


def teste_contagem_dedos():
    for n in (1, 2, 3):
        assert mao_dedos(0.4, 0.5, 0.12, n).dedos == n
        assert mao_dedos(0.4, 0.5, 0.12, n, inclinacao=0.6).dedos == n, "inclinada"
    assert mao_dedos(0.4, 0.5, 0.12, 4).dedos == 0, "mão aberta não troca de posto"
    assert mao_dedos(0.4, 0.5, 0.12, 0).dedos == 0, "punho não troca de posto"
    # Indicador dobrado com médio estendido: contagem ambígua -> 0.
    m = mao_dedos(0.4, 0.5, 0.12, 2)
    p = list(m.pontos)
    p[8], p[6] = (0.4, 0.5 + 0.06), (0.4, 0.5 + 0.024)
    assert Mao(p, "Left").dedos == 0


def teste_troca_posto():
    e, fr, _ = nova_entrada(lateral=False)
    corda = mao(0.58, 0.42, 0.12, False, "Right")
    inicio = time.monotonic()
    postos = []
    while time.monotonic() - inicio < en.TEMPO_DEDOS + 0.4:
        fr.mostrar([mao_dedos(0.45, 0.5, 0.15, 3), corda])
        cmd = e.atualizar(1 / 60)
        if cmd.posto:
            postos.append(cmd.posto)
        time.sleep(0.01)
    assert postos == [3], f"um único evento depois de {en.TEMPO_DEDOS}s: {postos}"
    # Durante a puxada, mostrar dedos não troca de posto.
    e2, fr2, la2 = nova_entrada()
    quadro(e2, fr2, la2, 0.38, False)
    quadro(e2, fr2, la2, 0.38, True)
    inicio = time.monotonic()
    while time.monotonic() - inicio < en.TEMPO_DEDOS + 0.3:
        fr2.mostrar([mao_dedos(0.45, 0.5, 0.15, 2), mao(0.58, 0.42, 0.12, True, "Right")])
        la2.mostrar([mao(0.30, 0.5, 0.1), mao(0.5, 0.5, 0.1, True)])
        assert not e2.atualizar(1 / 60).posto
        time.sleep(0.01)


def teste_dedos_qualquer_mao():
    """A mão direita (corda) também troca de posto, e mostrar dedos não começa uma puxada."""
    e, fr, _ = nova_entrada(lateral=False)
    arco = mao(0.45, 0.5, 0.15, False, "Left")
    inicio, postos = time.monotonic(), []
    while time.monotonic() - inicio < en.TEMPO_DEDOS + 0.3:
        fr.mostrar([arco, mao_dedos(0.6, 0.45, 0.12, 2, lado="Right")])
        cmd = e.atualizar(1 / 60)
        assert not cmd.puxando, "2 dedos na mão da corda não é corda presa"
        if cmd.posto:
            postos.append(cmd.posto)
        time.sleep(0.01)
    assert postos == [2], postos
    # Contagens diferentes nas duas mãos: nada acontece.
    e2, fr2, _ = nova_entrada(lateral=False)
    inicio = time.monotonic()
    while time.monotonic() - inicio < en.TEMPO_DEDOS + 0.2:
        fr2.mostrar([mao_dedos(0.45, 0.5, 0.15, 1), mao_dedos(0.6, 0.45, 0.12, 3, lado="Right")])
        assert not e2.atualizar(1 / 60).posto
        time.sleep(0.01)


def teste_one_euro():
    rng = np.random.default_rng(2)
    f = FiltroOneEuro()
    t, saida = 0.0, []
    for _ in range(120):  # mão parada com tremor
        t += 1 / 30
        saida.append(f.filtrar(np.array([0.5]) + rng.normal(0, 0.01, 1), t)[0])
    assert np.std(saida[30:]) < 0.004, "parada: deve suavizar bastante"
    for k in range(30):  # movimento rápido: deve acompanhar sem grande atraso
        t += 1 / 30
        alvo = 0.5 + 0.02 * (k + 1)
        valor = f.filtrar(np.array([alvo]), t)[0]
    assert abs(valor - alvo) < 0.05, (valor, alvo)


def teste_angulo_para():
    from flecha import GRAVIDADE, angulo_para
    origem = np.array((0.0, 1.6, 25.0))
    for distancia_alvo in (15, 25, 40):
        alvo = np.array((3.0, 1.45, 25.0 + distancia_alvo))
        yaw, pitch = angulo_para(origem, alvo, 68.0)
        # Simula só a gravidade e confere a altura ao chegar no plano do alvo.
        import mat3d as m3
        pos, vel = origem.copy(), m3.direcao(yaw, pitch) * 68.0
        while pos[2] < alvo[2]:
            vel = vel + np.array((0, -GRAVIDADE, 0)) / 240
            pos = pos + vel / 240
        assert abs(pos[1] - alvo[1]) < 0.05 and abs(pos[0] - alvo[0]) < 0.05, (distancia_alvo, pos)


def teste_sons():
    from sons import gerar
    for nome, onda in gerar().items():
        assert len(onda) > 0 and np.abs(onda).max() <= 1.0 + 1e-6, nome


TESTES = [teste_kalman, teste_disparo, teste_forca_minima, teste_cancela_sem_mao, teste_histerese,
          teste_calibracao, teste_puxada_curta, teste_continuidade_lateral, teste_polegar,
          teste_exportar_importar, teste_contagem_dedos, teste_troca_posto, teste_dedos_qualquer_mao,
          teste_one_euro, teste_angulo_para, teste_sons]


if __name__ == "__main__":
    pygame.init()
    pygame.display.set_mode((10, 10))
    for teste in TESTES:
        teste()
        print(f"ok  {teste.__name__}")
    print(f"entrada: {len(TESTES)} testes passaram")
