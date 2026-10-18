"""Leitura das webcams com OpenCV + MediaPipe Hands, uma thread por câmera.

A thread só detecta e mede; a interpretação do gesto do arco (calibração, histerese,
disparo) fica em entrada.py, no ritmo do jogo.
"""
import math
import threading
import time
from dataclasses import dataclass, field

import numpy as np

LARGURA_PREVIEW, ALTURA_PREVIEW = 320, 240
LARGURA_DETECCAO = 480
BRILHO_MINIMO = 90  # abaixo disso a imagem é realçada (CLAHE) antes da detecção
LIMITE_DETECCAO_MS = 45  # acima disso o modelo mais preciso dá lugar ao mais leve

# Ligações entre os 21 landmarks da mão (mesmo desenho do MediaPipe), para o esqueleto da interface.
CONEXOES = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10), (10, 11),
            (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18), (18, 19), (19, 20), (0, 17)]


def distancia(a, b):
    """Distância euclidiana entre dois landmarks normalizados (x, y)."""
    return math.hypot(a[0] - b[0], a[1] - b[1])


@dataclass
class Mao:
    pontos: list  # 21 landmarks (x, y) normalizados, imagem já espelhada
    lado: str = ""  # "Left"/"Right" do MediaPipe: com a imagem espelhada, é a mão real do usuário
    confianca: float = 1.0  # score da lateralidade

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
    def estendidos(self):
        """Indicador, médio, anelar e mínimo: True se estendido.

        Usa distância ao pulso (ponta mais longe que a articulação PIP), o que funciona
        mesmo com a mão inclinada — ao contrário de comparar só o eixo y.
        """
        p = self.pontos
        return [distancia(p[ponta], p[0]) > 1.15 * distancia(p[pip], p[0])
                for ponta, pip in ((8, 6), (12, 10), (16, 14), (20, 18))]

    @property
    def dedos(self):
        """1, 2 ou 3 quando os dedos estendidos são contíguos a partir do indicador
        (e o mínimo está dobrado); 0 caso contrário (punho, mão aberta ou contagem ambígua)."""
        estendidos = self.estendidos
        n = sum(estendidos)
        if 1 <= n <= 3 and estendidos == [True] * n + [False] * (4 - n):
            return n
        return 0

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


def mao_sintetica(cx, cy, tamanho=0.12, fechada=False, dedos=None, lado="", inclinacao=0.0):
    """Mão vertical gerada por código (tutorial e testes).

    `dedos` = quantos dedos a partir do indicador ficam estendidos (sobrepõe `fechada`).
    `inclinacao` gira a mão em torno do pulso (rad).
    """
    s = tamanho
    p = [(cx, cy)] * 21
    p[0] = (cx, cy + s)
    p[9] = (cx, cy)
    for k, (base, pip, dip, ponta) in enumerate(((5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20))):
        estendido = (k < dedos) if dedos is not None else not fechada
        dx = (k - 1.5) * 0.22 * s
        p[base] = (cx + dx, cy + 0.05 * s)
        if estendido:
            p[pip], p[dip], p[ponta] = (cx + dx * 1.1, cy - 0.3 * s), (cx + dx * 1.15, cy - 0.55 * s), (cx + dx * 1.2, cy - 0.8 * s)
        else:
            p[pip], p[dip], p[ponta] = (cx + dx, cy - 0.15 * s), (cx + dx * 0.9, cy + 0.15 * s), (cx + dx * 0.8, cy + 0.45 * s)
    p[9] = (cx, cy)
    polegar_aberto = dedos is None and not fechada
    p[1] = (cx + 0.3 * s, cy + 0.8 * s)
    p[2] = (cx + 0.45 * s, cy + 0.55 * s)
    p[3] = (cx + (0.6 if polegar_aberto else 0.4) * s, cy + 0.35 * s)
    p[4] = (cx + (0.75 if polegar_aberto else 0.3) * s, cy + (0.15 if polegar_aberto else 0.2) * s)
    if inclinacao:
        c, sn = math.cos(inclinacao), math.sin(inclinacao)
        px, py = p[0]
        p = [(px + c * (x - px) - sn * (y - py), py + sn * (x - px) + c * (y - py)) for x, y in p]
    return Mao(p, lado)


class FiltroOneEuro:
    """Filtro One Euro (Casiez et al., 2012) para arrays: suaviza muito parado e pouco em movimento.

    Coordenadas normalizadas, então `beta` é grande (velocidades típicas ~0,5-2 por segundo).
    """

    def __init__(self, min_cutoff=1.2, beta=8.0, d_cutoff=1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.x = self.dx = None
        self.t = 0.0

    @staticmethod
    def _alfa(cutoff, dt):
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def filtrar(self, x, t):
        x = np.asarray(x, dtype=float)
        if self.x is None:
            self.x, self.dx, self.t = x, np.zeros_like(x), t
            return x
        dt = max(t - self.t, 1e-3)
        self.t = t
        a_d = self._alfa(self.d_cutoff, dt)
        self.dx = a_d * (x - self.x) / dt + (1 - a_d) * self.dx
        cutoff = self.min_cutoff + self.beta * np.abs(self.dx)
        a = 1.0 / (1.0 + (1.0 / (2 * math.pi * cutoff)) / dt)
        self.x = a * x + (1 - a) * self.x
        return self.x


class SuavizadorMaos:
    """Um filtro One Euro por mão, associando as mãos entre quadros pelo pulso mais próximo."""

    def __init__(self, distancia_maxima=0.15, validade=0.5):
        self.distancia_maxima, self.validade = distancia_maxima, validade
        self._slots = []  # [filtro, pulso, instante]

    def suavizar(self, maos, t):
        self._slots = [slot for slot in self._slots if t - slot[2] < self.validade]
        livres = list(self._slots)
        resultado = []
        for mao in maos:
            pulso = mao.pontos[0]
            slot = min(livres, key=lambda sl: distancia(sl[1], pulso), default=None)
            if slot is None or distancia(slot[1], pulso) > self.distancia_maxima:
                slot = [FiltroOneEuro(), pulso, t]
                self._slots.append(slot)
            else:
                livres.remove(slot)
            filtrados = slot[0].filtrar(mao.pontos, t)
            slot[1], slot[2] = pulso, t
            resultado.append(Mao([tuple(p) for p in filtrados.tolist()], mao.lado, mao.confianca))
        return resultado


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
        # Métricas para a interface.
        self.fps = 0.0
        self.brilho = 128.0
        self.realce = False  # CLAHE ligado por pouca luz
        self.complexidade = 1
        self.tempo_deteccao = 0.0  # ms (média móvel)
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

        def criar_detector(complexidade):
            return mp_maos.Hands(max_num_hands=2, model_complexity=complexidade,
                                 min_detection_confidence=0.6, min_tracking_confidence=0.5)

        contador = 0
        camera = None
        falhas = 0
        suavizador = SuavizadorMaos()
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        ultimo_quadro = None
        detector = criar_detector(self.complexidade)
        try:
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
                agora = time.monotonic()
                if ultimo_quadro is not None:
                    self.fps = 0.9 * self.fps + 0.1 / max(agora - ultimo_quadro, 1e-3)
                ultimo_quadro = agora
                if contador % 15 == 0:
                    self.transmitindo = not tela_de_espera(imagem)
                imagem = cv2.flip(imagem, 1)  # modo espelho
                # Detecta numa imagem menor: os landmarks são normalizados, então a escala não muda nada.
                altura, largura = imagem.shape[:2]
                if largura > LARGURA_DETECCAO:
                    imagem = cv2.resize(imagem, (LARGURA_DETECCAO, int(altura * LARGURA_DETECCAO / largura)))
                # Pouca luz: realça o contraste local da luminância (CLAHE) antes de detectar.
                if contador % 10 == 0:
                    self.brilho = float(cv2.cvtColor(cv2.resize(imagem, (64, 48)), cv2.COLOR_BGR2GRAY).mean())
                    self.realce = self.brilho < BRILHO_MINIMO
                if self.realce:
                    lab = cv2.cvtColor(imagem, cv2.COLOR_BGR2LAB)
                    lab[..., 0] = clahe.apply(lab[..., 0])
                    imagem = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
                rgb = cv2.cvtColor(imagem, cv2.COLOR_BGR2RGB)
                inicio = time.perf_counter()
                resultado = detector.process(rgb)
                gasto = (time.perf_counter() - inicio) * 1000
                self.tempo_deteccao = gasto if contador == 0 else 0.9 * self.tempo_deteccao + 0.1 * gasto
                # Modelo adaptativo: se o preciso estiver lento demais nesta máquina, usa o leve.
                if self.complexidade == 1 and contador > 30 and self.tempo_deteccao > LIMITE_DETECCAO_MS:
                    detector.close()
                    self.complexidade = 0
                    detector = criar_detector(0)
                maos = []
                if resultado.multi_hand_landmarks:
                    lados = resultado.multi_handedness or []
                    for i, hand in enumerate(resultado.multi_hand_landmarks):
                        classe = lados[i].classification[0] if i < len(lados) else None
                        maos.append(Mao([(lm.x, lm.y) for lm in hand.landmark],
                                        classe.label if classe else "", classe.score if classe else 1.0))
                maos = suavizador.suavizar(maos, agora)
                preview = cv2.resize(rgb, (LARGURA_PREVIEW, ALTURA_PREVIEW))
                contador += 1
                with self._trava:
                    self._leitura = Leitura(contador, maos, agora)
                    self._preview = preview
        finally:
            detector.close()
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
