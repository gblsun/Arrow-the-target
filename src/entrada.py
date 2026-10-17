"""Unifica gesto (duas mãos como arco), mouse e teclado num único comando por quadro."""
import time
from dataclasses import dataclass

import pygame

import mat3d as m3
from gestos import distancia

# Pinça com histerese, em unidades de "tamanho da mão" (pulso -> base do dedo médio).
PINCA_FECHA, PINCA_ABRE = 0.35, 0.55
ALCANCE_PUXADA = 1.6  # quanto a mão da corda precisa se afastar para força 1
FORCA_MINIMA = 0.2
SUAVIZACAO = 0.35  # média móvel exponencial da mira
TEMPO_CALIBRACAO = 2.0
TEMPO_PUXADA_MOUSE = 1.1


@dataclass
class Comando:
    mira: tuple = (0.0, 0.0)  # [-1, 1] em x (direita) e y (baixo)
    puxando: bool = False
    forca: float = 0.0
    disparou: bool = False
    forca_disparo: float = 0.0
    confirmar: bool = False
    fonte: str = "mouse"


class Entrada:
    def __init__(self, rastreador, largura, altura):
        self.rastreador = rastreador
        self.largura, self.altura = largura, altura
        self.canhoto = False
        self.centro = (0.5, 0.5)
        self.repouso = 0.6
        self.calibrado = False
        self._amostras = []
        self._tempo_calibrado = 0.0

        self._id_quadro = -1
        self._mira_gesto = (0.0, 0.0)
        self._pinca = False
        self._puxando_gesto = False
        self._forca_gesto = 0.0
        self._ultimo_gesto = 0.0
        self._maos = []
        self._eventos_gesto = []  # disparos/confirmações detectados no último quadro de câmera

        self._mouse_puxando = False
        self._forca_mouse = 0.0
        self._soltou_mouse = False
        self._confirmar = False

    # ---------------------------------------------------------------- eventos do pygame

    def processar_evento(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            self._mouse_puxando = True
            self._confirmar = True
        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1 and self._mouse_puxando:
            self._mouse_puxando = False
            self._soltou_mouse = True
        elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_SPACE:
            self._mouse_puxando = True
        elif ev.type == pygame.KEYUP and ev.key == pygame.K_SPACE and self._mouse_puxando:
            self._mouse_puxando = False
            self._soltou_mouse = True
        elif ev.type == pygame.KEYDOWN and ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._confirmar = True

    # ---------------------------------------------------------------- gesto

    @property
    def maos_visiveis(self):
        return len(self._maos)

    @property
    def gesto_ativo(self):
        return self.rastreador is not None and time.monotonic() - self._ultimo_gesto < 0.4

    @property
    def pinca(self):
        return self._pinca

    def _papeis(self, maos):
        """Mão da corda = a que fica do lado de fora (direita na imagem espelhada para destros)."""
        ordenadas = sorted(maos, key=lambda m: m.palma[0])
        if self.canhoto:
            return ordenadas[-1], ordenadas[0]
        return ordenadas[0], ordenadas[-1]

    def _ler_gesto(self):
        self._eventos_gesto = []
        if self.rastreador is None:
            return
        leitura = self.rastreador.leitura()
        if leitura.id_quadro == self._id_quadro:
            return
        self._id_quadro = leitura.id_quadro
        self._maos = leitura.maos
        if not self._maos:
            if self._puxando_gesto:
                self._puxando_gesto = False  # mãos perdidas: cancela sem disparar
            self._pinca = False
            return
        self._ultimo_gesto = time.monotonic()

        if len(self._maos) >= 2:
            arco, corda = self._papeis(self._maos[:2])
        else:
            arco = corda = self._maos[0]

        # Mira: posição da palma da mão do arco em relação ao centro calibrado.
        alvo_x = m3.limitar((arco.palma[0] - self.centro[0]) / 0.22, -1, 1)
        alvo_y = m3.limitar((arco.palma[1] - self.centro[1]) / 0.2, -1, 1)
        mx, my = self._mira_gesto
        self._mira_gesto = (m3.lerp(mx, alvo_x, SUAVIZACAO), m3.lerp(my, alvo_y, SUAVIZACAO))

        abertura = corda.abertura_pinca
        estava = self._pinca
        if estava and abertura > PINCA_ABRE:
            self._pinca = False
        elif not estava and abertura < PINCA_FECHA:
            self._pinca = True

        if len(self._maos) >= 2:
            afastamento = distancia(corda.pinca, arco.palma) / arco.tamanho
            forca = m3.limitar((afastamento - self.repouso) / ALCANCE_PUXADA)
        else:
            forca = 0.0

        if self._pinca and not estava:
            self._eventos_gesto.append("confirmar")
            self._puxando_gesto = len(self._maos) >= 2
            self._forca_gesto = 0.0
        if self._pinca and self._puxando_gesto:
            if len(self._maos) < 2:
                self._puxando_gesto = False  # perdeu a mão do arco no meio da puxada
            else:
                self._forca_gesto = m3.lerp(self._forca_gesto, forca, 0.5)
        if not self._pinca and estava and self._puxando_gesto:
            self._puxando_gesto = False
            if self._forca_gesto >= FORCA_MINIMA:
                self._eventos_gesto.append(("disparo", self._forca_gesto))

    # ---------------------------------------------------------------- calibração

    def calibrar(self, dt):
        """Acumula amostras com as duas mãos visíveis. Devolve o progresso em [0, 1]."""
        self._ler_gesto()
        if len(self._maos) >= 2:
            arco, corda = self._papeis(self._maos[:2])
            self._amostras.append((arco.palma, distancia(corda.pinca, arco.palma) / arco.tamanho))
            self._tempo_calibrado += dt
        progresso = m3.limitar(self._tempo_calibrado / TEMPO_CALIBRACAO)
        if progresso >= 1 and self._amostras:
            n = len(self._amostras)
            self.centro = (sum(a[0][0] for a in self._amostras) / n, sum(a[0][1] for a in self._amostras) / n)
            self.repouso = min(1.2, sum(a[1] for a in self._amostras) / n)
            self.calibrado = True
        return progresso

    def soltar_tudo(self):
        """Descarta puxadas em andamento (usado ao trocar de tela)."""
        self._mouse_puxando = self._soltou_mouse = False
        self._forca_mouse = 0.0
        self._puxando_gesto = False

    def reiniciar_calibracao(self):
        self._amostras, self._tempo_calibrado, self.calibrado = [], 0.0, False

    # ---------------------------------------------------------------- comando do quadro

    def atualizar(self, dt):
        self._ler_gesto()
        cmd = Comando()

        if self._mouse_puxando:
            self._forca_mouse = min(1.0, self._forca_mouse + dt / TEMPO_PUXADA_MOUSE)

        usar_gesto = self.gesto_ativo and len(self._maos) >= 2 and not self._mouse_puxando
        if usar_gesto:
            cmd.fonte = "gesto"
            cmd.mira = self._mira_gesto
            cmd.puxando = self._puxando_gesto
            cmd.forca = self._forca_gesto if self._puxando_gesto else 0.0
        else:
            mx, my = pygame.mouse.get_pos()
            cmd.mira = (m3.limitar((mx - self.largura / 2) / (self.largura / 2), -1, 1),
                        m3.limitar((my - self.altura / 2) / (self.altura / 2), -1, 1))
            cmd.puxando = self._mouse_puxando
            cmd.forca = self._forca_mouse if self._mouse_puxando else 0.0

        for evento in self._eventos_gesto:
            if evento == "confirmar":
                cmd.confirmar = True
            elif evento[0] == "disparo":
                cmd.disparou, cmd.forca_disparo = True, evento[1]
        self._eventos_gesto = []

        if self._soltou_mouse:
            if self._forca_mouse >= FORCA_MINIMA:
                cmd.disparou, cmd.forca_disparo = True, self._forca_mouse
            self._forca_mouse = 0.0
            self._soltou_mouse = False
        if self._confirmar:
            cmd.confirmar = True
            self._confirmar = False
        return cmd
