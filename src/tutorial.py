"""Tutorial demonstrativo (não jogável): o jogo se joga sozinho enquanto mãos sintéticas
mostram, em duas "câmeras de demonstração", exatamente o gesto a fazer.

Cada cena tem duração, legenda e uma função que, dado o progresso u ∈ [0, 1], define as mãos
sintéticas, a mira, a força e ações pontuais (disparar, trocar de posto, mostrar o bônus).
"""
import math
from collections import deque

import numpy as np
import pygame

import mat3d as m3
from entrada import Comando, TEMPO_DEDOS
from flecha import VELOCIDADE_MAX, angulo_para
from gestos import mao_sintetica
from hud import OURO, PERGAMINHO, desenhar_maos, desenhar_puxada

# Cenas: (título, legenda, duração em s, nome do método que anima)
CENAS = [
    ("Bem-vindo, arqueiro", "Assista: o jogo mostra como se joga. Depois você calibra as suas mãos.", 4.0, "_boas_vindas"),
    ("Mirar", "A mão ESQUERDA, esticada à frente, segura o arco: movê-la move a mira. Ela fica dourada sobre um alvo.", 5.0, "_mirar"),
    ("Puxar a corda", "FECHE a mão direita e puxe-a para trás, até o rosto. A câmera lateral mede quanto você puxou.", 4.5, "_puxar"),
    ("Soltar", "ABRA a mão direita para soltar a flecha. Tiros bons ganham a câmera da flecha.", 5.0, "_soltar"),
    ("Trocar de posto", "Mostre 1, 2 ou 3 dedos com QUALQUER mão por um instante: o arqueiro vai para aquele posto.", 4.5, "_trocar_posto"),
    ("Mais longe, mais pontos", "No posto 2 cada ponto vale o dobro; no posto 3, o triplo. O vento também pesa mais.", 6.5, "_tiro_longe"),
    ("Alvo bônus", "De vez em quando um alvo dourado cruza a clareira: acerte-o para ganhar 25 pontos.", 6.5, "_bonus"),
    ("Sua vez!", "Agora vamos calibrar as suas mãos. Fique de frente para a câmera.", 3.5, "_fim"),
]


def _suave(u, a, b):
    """0 antes de a, 1 depois de b, ease-in-out entre os dois."""
    return m3.ease_in_out(m3.limitar((u - a) / max(b - a, 1e-6)))


class Tutorial:
    def __init__(self, jogo):
        self.jogo = jogo
        self.indice = 0
        self.tempo = 0.0
        self.acabou = False
        self._feito = set()
        self.forca = 0.0
        self.puxando = False
        self.fechada = False
        self.mira = (0.0, 0.03)  # yaw, pitch desejados
        self.dedos_mostrados = 0
        self.progresso_dedos = 0.0
        # Mãos sintéticas em cada "câmera de demonstração" e o rastro da mão da corda.
        self.maos = {"frontal": [], "lateral": []}
        self.pares = {"frontal": (None, None), "lateral": (None, None)}
        self.rastros = {"frontal": deque(maxlen=15), "lateral": deque(maxlen=15)}
        self._forca_disparo = None
        self._posto_pedido = 0

    # ---------------------------------------------------------------- execução

    @property
    def cena(self):
        return CENAS[self.indice]

    def pular(self):
        self.acabou = True

    def atualizar(self, dt):
        """Avança o roteiro e devolve um Comando, como se viesse das mãos do jogador."""
        if self.acabou:
            return Comando(fonte="gesto")
        self.tempo += dt
        _, _, duracao, metodo = self.cena
        u = m3.limitar(self.tempo / duracao)
        self._forca_disparo, self._posto_pedido = None, 0
        getattr(self, metodo)(u)
        self._registrar_rastros()
        cmd = Comando(mira=(0.0, 0.0), puxando=self.puxando, forca=self.forca, fonte="gesto")
        if self._forca_disparo is not None:
            cmd.disparou, cmd.forca_disparo = True, self._forca_disparo
        cmd.posto = self._posto_pedido
        if u >= 1:
            self.indice += 1
            self.tempo = 0.0
            if self.indice >= len(CENAS):
                self.acabou = True
        return cmd

    def _uma_vez(self, chave):
        if (self.indice, chave) in self._feito:
            return False
        self._feito.add((self.indice, chave))
        return True

    def _mirar_em(self, alvo):
        """Ângulos que acertam o centro do alvo com força máxima e sem vento."""
        origem = self.jogo.pos_camera + np.array((0, -0.08, 0))
        return angulo_para(origem, alvo.centro_mundo(), VELOCIDADE_MAX)

    # ---------------------------------------------------------------- mãos sintéticas

    def _maos(self, desvio_mira=(0.0, 0.0), puxada=0.0, fechada=False, dedos=None, mao_dedos="Right"):
        """Monta as duas vistas: frontal (de frente) e lateral (de perfil)."""
        dx, dy = desvio_mira
        arco_f = mao_sintetica(0.3 + dx, 0.6 + dy, 0.2, fechada=False, lado="Left",
                               dedos=dedos if mao_dedos == "Left" else None)
        # De frente, a mão direita recua para o rosto: sobe e se aproxima do centro.
        cx = m3.lerp(0.64, 0.6, puxada)
        cy = m3.lerp(0.58, 0.36, puxada)
        corda_f = mao_sintetica(cx, cy, m3.lerp(0.19, 0.16, puxada), fechada=fechada, lado="Right",
                                dedos=dedos if mao_dedos == "Right" else None)
        # De perfil, a distância entre as mãos é a puxada.
        arco_l = mao_sintetica(0.18, 0.58, 0.15, fechada=False)
        corda_l = mao_sintetica(m3.lerp(0.36, 0.76, puxada), m3.lerp(0.58, 0.46, puxada), 0.15, fechada=fechada)
        self.maos = {"frontal": [arco_f, corda_f], "lateral": [arco_l, corda_l]}
        self.pares = {"frontal": (arco_f, corda_f), "lateral": (arco_l, corda_l)}
        self.fechada = fechada

    def _registrar_rastros(self):
        for chave, (_, corda) in self.pares.items():
            rastro = self.rastros[chave]
            if corda is None or not self.puxando:
                rastro.clear()
            elif not rastro or rastro[-1] != corda.palma:
                rastro.append(corda.palma)

    # ---------------------------------------------------------------- cenas

    def _boas_vindas(self, u):
        self.puxando, self.forca = False, 0.0
        varredura = math.sin(u * math.pi * 2) * 0.12
        self.mira = (varredura, 0.04)
        self._maos(desvio_mira=(varredura * 0.25, 0.0))

    def _mirar(self, u):
        self.puxando, self.forca = False, 0.0
        yaw, pitch = self._mirar_em(self.jogo.cena.alvos[0])
        k = _suave(u, 0.1, 0.7)
        self.mira = (m3.lerp(0.0, yaw, k), m3.lerp(0.04, pitch, k))
        self._maos(desvio_mira=(m3.lerp(0.0, -0.07, k), m3.lerp(0.0, -0.02, k)))

    def _puxar(self, u):
        yaw, pitch = self._mirar_em(self.jogo.cena.alvos[0])
        self.mira = (yaw, pitch)
        fechada = u > 0.15
        self.forca = _suave(u, 0.25, 0.9) if fechada else 0.0
        self.puxando = fechada
        self._maos(desvio_mira=(-0.07, -0.02), puxada=self.forca, fechada=fechada)

    def _soltar(self, u):
        yaw, pitch = self._mirar_em(self.jogo.cena.alvos[0])
        self.mira = (yaw, pitch)
        if u < 0.08:
            self.puxando, self.forca = True, 1.0
            self._maos(desvio_mira=(-0.07, -0.02), puxada=1.0, fechada=True)
            return
        if self._uma_vez("disparo"):
            self._forca_disparo = 1.0
        self.puxando, self.forca = False, 0.0
        self._maos(desvio_mira=(-0.07, -0.02), puxada=0.9, fechada=False)

    def _trocar_posto(self, u):
        self.puxando, self.forca = False, 0.0
        self.mira = (0.0, 0.04)
        mostrando = 0.1 < u < 0.8  # segura os dedos tempo suficiente para ver o anel encher
        self.dedos_mostrados = 2 if mostrando else 0
        self.progresso_dedos = m3.limitar((u - 0.1) * self.cena[2] / TEMPO_DEDOS) if mostrando else 0.0
        if mostrando and self.progresso_dedos >= 1 and self._uma_vez("posto"):
            self._posto_pedido = 2
        self._maos(dedos=2 if mostrando else None, mao_dedos="Right")

    def _tiro_longe(self, u):
        alvo = self.jogo.cena.alvos[1]
        yaw, pitch = self._mirar_em(alvo)
        k = _suave(u, 0.0, 0.25)
        self.mira = (m3.lerp(0.0, yaw, k), m3.lerp(0.04, pitch, k))
        self._sequencia_tiro(u, inicio=0.3, fim=0.62, desvio=(0.06, -0.02))

    def _bonus(self, u):
        bonus = self.jogo.cena.alvos[-1]
        if self._uma_vez("fixar"):
            bonus.fixar((1.5, 3.2, 47.0))
        yaw, pitch = self._mirar_em(bonus)
        k = _suave(u, 0.1, 0.35)
        self.mira = (m3.lerp(self.mira[0], yaw, k), m3.lerp(self.mira[1], pitch, k))
        self._sequencia_tiro(u, inicio=0.4, fim=0.7, desvio=(0.02, -0.08))

    def _sequencia_tiro(self, u, inicio, fim, desvio):
        """Fecha a mão, puxa até o máximo e solta em `fim`."""
        if u < inicio:
            self.puxando, self.forca = False, 0.0
            self._maos(desvio_mira=desvio)
        elif u < fim:
            self.puxando = True
            self.forca = _suave(u, inicio + 0.03, fim - 0.05)
            self._maos(desvio_mira=desvio, puxada=self.forca, fechada=True)
        else:
            if self._uma_vez("disparo"):
                self._forca_disparo = 1.0
            self.puxando, self.forca = False, 0.0
            self._maos(desvio_mira=desvio, puxada=0.9, fechada=False)

    def _fim(self, u):
        self.puxando, self.forca = False, 0.0
        self.mira = (0.0, 0.04)
        self._maos()
        if self._uma_vez("liberar"):
            self.jogo.cena.alvos[-1].fixar(None)

    # ---------------------------------------------------------------- desenho

    def desenhar(self, tela, hud, t):
        titulo, legenda, _, _ = self.cena if not self.acabou else CENAS[-1]
        hud.painel_tutorial(tela, min(self.indice, len(CENAS) - 1), len(CENAS), titulo, legenda, t)
        # Duas câmeras de demonstração com as mãos sintéticas fazendo o gesto.
        largura, altura = 300, 225
        y = hud.altura - altura - 60
        for i, (chave, nome) in enumerate((("frontal", "Câmera frontal"), ("lateral", "Câmera lateral"))):
            rect = pygame.Rect(16 + i * (largura + 16), y, largura, altura)
            hud.painel(tela, rect.inflate(10, 40).move(0, 15), 210)
            self._fundo_camera(tela, rect, chave)
            desenhar_puxada(tela, rect, self.pares[chave], self.rastros[chave], self.forca, self.puxando,
                            self.fechada, hud.f_pequena)
            desenhar_maos(tela, rect, self.maos[chave], self.pares[chave], self.forca, self.puxando, hud.f_pequena)
            hud.texto(tela, f"{nome} (demonstração)", hud.f_pequena, OURO, (rect.x + 4, rect.bottom + 6))
        if self.dedos_mostrados:
            hud.indicador_posto(tela, self.dedos_mostrados, self.progresso_dedos, self.jogo.posto + 1)
        hud.texto(tela, "Enter: pular o tutorial", hud.f_pequena, PERGAMINHO, (hud.largura - 16, hud.altura - 16), "bottomright")

    @staticmethod
    def _fundo_camera(tela, rect, chave):
        """Fundo que lembra uma câmera: parede, e a silhueta do arqueiro (de frente ou de perfil)."""
        pygame.draw.rect(tela, (54, 58, 66), rect)
        pygame.draw.rect(tela, (64, 68, 78), (rect.x, rect.y, rect.w, rect.h // 2))
        cor = (36, 38, 44)
        if chave == "frontal":
            cabeca = (rect.x + int(rect.w * 0.5), rect.y + int(rect.h * 0.28))
            pygame.draw.circle(tela, cor, cabeca, int(rect.h * 0.13))
            pygame.draw.ellipse(tela, cor, (rect.x + rect.w * 0.22, rect.y + rect.h * 0.45, rect.w * 0.56, rect.h * 0.7))
        else:
            cabeca = (rect.x + int(rect.w * 0.8), rect.y + int(rect.h * 0.3))
            pygame.draw.circle(tela, cor, cabeca, int(rect.h * 0.12))
            pygame.draw.ellipse(tela, cor, (rect.x + rect.w * 0.68, rect.y + rect.h * 0.46, rect.w * 0.24, rect.h * 0.7))
        pygame.draw.rect(tela, (20, 14, 8), rect, 2)


