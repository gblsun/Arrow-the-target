"""Leitura das webcams com OpenCV + MediaPipe Hands, uma thread por câmera.

A thread só detecta e mede; a interpretação do gesto do arco (calibração, histerese,
disparo) fica em entrada.py, no ritmo do jogo.
"""
import math
import threading
import time
from dataclasses import dataclass, field

LARGURA_PREVIEW, ALTURA_PREVIEW = 320, 240


def distancia(a, b):
    """Distância euclidiana entre dois landmarks normalizados (x, y)."""
    return math.hypot(a[0] - b[0], a[1] - b[1])


@dataclass
class Mao:
    pontos: list  # 21 landmarks (x, y) normalizados, imagem já espelhada
    lado: str = ""  # "Left"/"Right" do MediaPipe: com a imagem espelhada, é a mão real do usuário

    @property
    def tamanho(self):
        """Pulso (0) até a base do dedo médio (9): referência de escala da mão."""
        return max(distancia(self.pontos[0], self.pontos[9]), 1e-4)

    @property
    def palma(self):
        return self.pontos[9]

    @property
    def curvatura(self):
        """Distância média das pontas dos dedos ao pulso, em tamanhos de mão.

        Mão aberta fica perto de 1.7; punho fechado, perto de 0.9.
        """
        return sum(distancia(self.pontos[i], self.pontos[0]) for i in (8, 12, 16, 20)) / 4 / self.tamanho

    @property
    def abertura_pinca(self):
        return distancia(self.pontos[4], self.pontos[8]) / self.tamanho

    @property
    def polegar(self):
        """'cima', 'baixo' ou None — regra de ref/mediapipe/exercicios_mediapipe.pdf, normalizada pelo tamanho."""
        lm = self.pontos
        estendidos = sum(lm[p][1] < lm[a][1] for p, a in ((8, 6), (12, 10), (16, 14), (20, 18)))
        if estendidos > 1 or self.curvatura > 1.35:
            return None
        diferenca = (lm[4][1] - lm[3][1]) / self.tamanho
        if diferenca < -0.25 and lm[4][1] < lm[5][1] - 0.3 * self.tamanho:
            return "cima"
        if diferenca > 0.25 and lm[4][1] > lm[17][1] + 0.3 * self.tamanho:
            return "baixo"
        return None


@dataclass
class Leitura:
    id_quadro: int = 0
    maos: list = field(default_factory=list)
    instante: float = 0.0


@dataclass(frozen=True)
class Fonte:
    """Uma câmera: índice + backend do OpenCV, nome do dispositivo e resolução que abriu."""
    indice: int
    backend: str = "DSHOW"  # DSHOW (nomes conhecidos) ou MSMF
    nome: str = ""
    largura: int = 0  # 0 = resolução padrão do dispositivo
    altura: int = 0

    @property
    def rotulo(self):
        return self.nome or f"Câmera {self.indice} ({self.backend})"


def _api(cv2, backend):
    return cv2.CAP_DSHOW if backend == "DSHOW" else cv2.CAP_MSMF


def abrir_captura(cv2, indice, backend, largura=0, altura=0):
    """Abre a câmera já pedindo a resolução: algumas (ex.: DroidCam) só abrem assim."""
    camera = cv2.VideoCapture()
    try:
        if largura:
            camera.open(indice, _api(cv2, backend), [cv2.CAP_PROP_FRAME_WIDTH, largura, cv2.CAP_PROP_FRAME_HEIGHT, altura])
        else:
            camera.open(indice, _api(cv2, backend))
    except Exception:
        pass
    return camera


def tela_de_espera(quadro):
    """Imagem de "sem transmissão" de câmera virtual: cor sólida (tela azul da DroidCam)
    ou quase toda preta com um texto ("Start DroidCam")."""
    import cv2
    cinza = cv2.cvtColor(cv2.resize(quadro, (64, 48)), cv2.COLOR_BGR2GRAY)
    return cinza.std() < 8 or (cinza < 20).mean() > 0.9


def nomes_dispositivos():
    """Nomes dos dispositivos de vídeo na ordem dos índices do DirectShow (Windows)."""
    try:
        from pygrabber.dshow_graph import FilterGraph
        return FilterGraph().get_input_devices()
    except Exception:
        return []


RESOLUCOES = ((640, 480), (1280, 720), (0, 0))


def _testar(cv2, indice, backend):
    """Tenta abrir em cada resolução. Devolve (largura, altura, quadro) ou None."""
    for largura, altura in RESOLUCOES:
        camera = abrir_captura(cv2, indice, backend, largura, altura)
        quadro = None
        if camera.isOpened():
            for _ in range(8):  # câmeras virtuais às vezes demoram alguns quadros
                ok, img = camera.read()
                if ok and img is not None:
                    quadro = img
                    break
                time.sleep(0.03)
        camera.release()
        if quadro is not None:
            return largura, altura, quadro
    return None


def _parecidos(a, b):
    import cv2
    pa = cv2.resize(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), (32, 24)).astype(float)
    pb = cv2.resize(cv2.cvtColor(b, cv2.COLOR_BGR2GRAY), (32, 24)).astype(float)
    return abs(pa - pb).mean() < 10


def listar_fontes(maximo=8):
    """Todas as câmeras do sistema e o estado de cada uma.

    Devolve [(Fonte, estado)], estado em "ok" (transmitindo), "espera" (abre, mas mostra
    a tela de espera da câmera virtual) ou "sem_sinal" (não abre).
    Procura pelo DirectShow (com nomes) e completa com o Media Foundation, que enxerga
    câmeras virtuais que o DirectShow não abre (ex.: "DroidCam Video").
    """
    try:
        import cv2
    except ImportError:
        return []
    nomes = nomes_dispositivos()
    resultado, quadros, falhas = [], [], []
    for i in range(len(nomes) if nomes else maximo):
        nome = nomes[i] if nomes else ""
        teste = _testar(cv2, i, "DSHOW")
        if teste is None:
            if nome:
                falhas.append((i, nome))
            continue
        largura, altura, quadro = teste
        quadros.append(quadro)
        estado = "espera" if tela_de_espera(quadro) else "ok"
        resultado.append((Fonte(i, "DSHOW", nome, largura, altura), estado))

    for i in range(maximo):
        teste = _testar(cv2, i, "MSMF")
        if teste is None:
            continue
        largura, altura, quadro = teste
        if any(_parecidos(quadro, q) for q in quadros) and not tela_de_espera(quadro):
            continue  # mesma câmera já encontrada pelo DirectShow
        # Câmera que só abre pelo Media Foundation: herda o nome de uma que falhou no DirectShow.
        nome = falhas.pop(0)[1] if falhas else ""
        quadros.append(quadro)
        estado = "espera" if tela_de_espera(quadro) else "ok"
        resultado.append((Fonte(i, "MSMF", nome, largura, altura), estado))

    for i, nome in falhas:
        resultado.append((Fonte(i, "DSHOW", nome), "sem_sinal"))
    ordem = {"ok": 0, "espera": 1, "sem_sinal": 2}
    resultado.sort(key=lambda par: ordem[par[1]])
    return resultado


class RastreadorMaos(threading.Thread):
    def __init__(self, fonte):
        super().__init__(daemon=True)
        self.fonte = fonte
        self._trava = threading.Lock()
        self._leitura = Leitura()
        self._preview = None
        self.ativo = False
        self.erro = None
        self.transmitindo = False  # False enquanto a câmera virtual mostra a tela de espera
        self._parar = threading.Event()

    @property
    def nome(self):
        return self.fonte.rotulo

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

        def abrir():
            f = self.fonte
            cam = abrir_captura(cv2, f.indice, f.backend, f.largura, f.altura)
            if not cam.isOpened():
                for largura, altura in RESOLUCOES:
                    cam = abrir_captura(cv2, f.indice, f.backend, largura, altura)
                    if cam.isOpened():
                        break
            return cam

        mp_maos = mp.solutions.hands
        desenho = mp.solutions.drawing_utils
        contador = 0
        camera = None
        falhas = 0
        with mp_maos.Hands(max_num_hands=2, model_complexity=0,
                           min_detection_confidence=0.6, min_tracking_confidence=0.5) as detector:
            while not self._parar.is_set():
                # (Re)conexão: a webcam pode não existir ainda, ser desconectada ou tomada por outro app.
                if camera is None or not camera.isOpened():
                    camera = abrir()
                    if not camera.isOpened():
                        self.ativo = False
                        self.erro = "Sem sinal"
                        self._parar.wait(2.0)
                        continue
                    self.ativo, self.erro, falhas = True, None, 0
                sucesso, imagem = camera.read()
                if not sucesso:
                    falhas += 1
                    if falhas > 15:
                        camera.release()
                        camera = None
                        self.ativo = False
                        self.erro = "Desconectada, reconectando..."
                        with self._trava:
                            self._preview = None
                        self._parar.wait(1.0)
                    else:
                        time.sleep(0.02)
                    continue
                falhas = 0
                if contador % 15 == 0:
                    self.transmitindo = not tela_de_espera(imagem)
                imagem = cv2.flip(imagem, 1)  # modo espelho
                rgb = cv2.cvtColor(imagem, cv2.COLOR_BGR2RGB)
                resultado = detector.process(rgb)
                maos = []
                if resultado.multi_hand_landmarks:
                    lados = resultado.multi_handedness or []
                    for i, hand in enumerate(resultado.multi_hand_landmarks):
                        lado = lados[i].classification[0].label if i < len(lados) else ""
                        maos.append(Mao([(lm.x, lm.y) for lm in hand.landmark], lado))
                        desenho.draw_landmarks(rgb, hand, mp_maos.HAND_CONNECTIONS)
                preview = cv2.resize(rgb, (LARGURA_PREVIEW, ALTURA_PREVIEW))
                contador += 1
                with self._trava:
                    self._leitura = Leitura(contador, maos, time.monotonic())
                    self._preview = preview
        if camera is not None:
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
