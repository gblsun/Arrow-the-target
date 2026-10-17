"""Leitura da webcam com OpenCV + MediaPipe Hands numa thread separada.

A thread só detecta e mede; a interpretação do gesto do arco (calibração, histerese,
disparo) fica em entrada.py, no ritmo do jogo.
"""
import math
import threading
import time
from dataclasses import dataclass, field

LARGURA_PREVIEW, ALTURA_PREVIEW = 256, 192


def distancia(a, b):
    """Distância euclidiana entre dois landmarks normalizados (x, y)."""
    return math.hypot(a[0] - b[0], a[1] - b[1])


@dataclass
class Mao:
    pontos: list  # 21 landmarks (x, y) normalizados, imagem já espelhada

    @property
    def tamanho(self):
        """Pulso (0) até a base do dedo médio (9): referência de escala da mão."""
        return max(distancia(self.pontos[0], self.pontos[9]), 1e-4)

    @property
    def palma(self):
        return self.pontos[9]

    @property
    def pinca(self):
        """Ponto médio entre a ponta do polegar (4) e do indicador (8)."""
        a, b = self.pontos[4], self.pontos[8]
        return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)

    @property
    def abertura_pinca(self):
        return distancia(self.pontos[4], self.pontos[8]) / self.tamanho


@dataclass
class Leitura:
    id_quadro: int = 0
    maos: list = field(default_factory=list)
    instante: float = 0.0


class RastreadorMaos(threading.Thread):
    def __init__(self, indice_camera=0):
        super().__init__(daemon=True)
        self.indice = indice_camera
        self._trava = threading.Lock()
        self._leitura = Leitura()
        self._preview = None
        self.ativo = False
        self.erro = None
        self._parar = threading.Event()

    def run(self):
        try:
            self._executar()
        except Exception as exc:  # a thread não pode derrubar o jogo; cai para mouse/teclado
            self.erro = f"Falha na câmera: {exc}"
            self.ativo = False

    def _executar(self):
        try:
            import cv2
            import mediapipe as mp
        except ImportError as exc:
            self.erro = f"Bibliotecas indisponíveis: {exc.name}"
            return
        camera = cv2.VideoCapture(self.indice, cv2.CAP_DSHOW) if hasattr(cv2, "CAP_DSHOW") else cv2.VideoCapture(self.indice)
        if not camera.isOpened():
            camera = cv2.VideoCapture(self.indice)
        if not camera.isOpened():
            self.erro = "Webcam não encontrada"
            return
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        mp_maos = mp.solutions.hands
        desenho = mp.solutions.drawing_utils
        self.ativo = True
        contador = 0
        with mp_maos.Hands(max_num_hands=2, model_complexity=0,
                           min_detection_confidence=0.6, min_tracking_confidence=0.5) as detector:
            while not self._parar.is_set():
                sucesso, imagem = camera.read()
                if not sucesso:
                    time.sleep(0.01)
                    continue
                imagem = cv2.flip(imagem, 1)  # modo espelho
                rgb = cv2.cvtColor(imagem, cv2.COLOR_BGR2RGB)
                resultado = detector.process(rgb)
                maos = []
                if resultado.multi_hand_landmarks:
                    for hand in resultado.multi_hand_landmarks:
                        maos.append(Mao([(lm.x, lm.y) for lm in hand.landmark]))
                        desenho.draw_landmarks(rgb, hand, mp_maos.HAND_CONNECTIONS)
                preview = cv2.resize(rgb, (LARGURA_PREVIEW, ALTURA_PREVIEW))
                contador += 1
                with self._trava:
                    self._leitura = Leitura(contador, maos, time.monotonic())
                    self._preview = preview
        camera.release()
        self.ativo = False

    def leitura(self):
        with self._trava:
            return self._leitura

    def preview(self):
        with self._trava:
            return self._preview

    def parar(self):
        self._parar.set()
