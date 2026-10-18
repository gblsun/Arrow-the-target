"""Efeitos sonoros sintetizados com numpy (sem arquivos de áudio).

Se não houver dispositivo de som, todos os métodos viram operações vazias.
"""
import numpy as np

TAXA = 22050


def _t(duracao):
    return np.arange(int(TAXA * duracao)) / TAXA


def _envelope(n, ataque, decaimento):
    """Ataque linear seguido de decaimento exponencial (em segundos)."""
    t = np.arange(n) / TAXA
    env = np.exp(-np.maximum(t - ataque, 0) / decaimento)
    if ataque > 0:
        env *= np.minimum(t / ataque, 1.0)
    return env


def _passa_baixa(sinal, janela):
    janela = max(1, int(janela))
    return np.convolve(sinal, np.ones(janela) / janela, mode="same")


def _ruido(n, rng):
    return rng.uniform(-1, 1, n)


def gerar(semente=3):
    """Devolve {nome: array float em [-1, 1]} com todos os efeitos."""
    rng = np.random.default_rng(semente)
    sons = {}

    # Corda sendo puxada: rangido grave de madeira.
    t = _t(0.45)
    rangido = _passa_baixa(_ruido(len(t), rng), 40) * (0.6 + 0.4 * np.sin(2 * np.pi * 23 * t))
    sons["puxar"] = 0.5 * rangido * _envelope(len(t), 0.15, 0.25)

    # Disparo: "twang" da corda (fundamental com queda de altura) + estalo.
    t = _t(0.5)
    freq = 140 * np.exp(-t * 3) + 70
    fase = 2 * np.pi * np.cumsum(freq) / TAXA
    corda = (np.sin(fase) + 0.5 * np.sin(2 * fase) + 0.25 * np.sin(3 * fase)) * _envelope(len(t), 0.002, 0.12)
    estalo = _ruido(len(t), rng) * _envelope(len(t), 0.0, 0.01)
    sons["disparo"] = 0.6 * corda + 0.3 * estalo

    # Voo: ruído filtrado com envelope em sino (assobio do ar).
    t = _t(0.6)
    sopro = _ruido(len(t), rng) - _passa_baixa(_ruido(len(t), rng), 12)
    sons["voo"] = 0.35 * _passa_baixa(sopro, 3) * np.sin(np.pi * t / t[-1]) ** 2

    # Impacto na palha: baque grave e abafado.
    t = _t(0.3)
    baque = np.sin(2 * np.pi * 85 * t) * _envelope(len(t), 0.001, 0.06)
    palha = _passa_baixa(_ruido(len(t), rng), 6) * _envelope(len(t), 0.0, 0.04)
    sons["alvo"] = 0.8 * baque + 0.6 * palha

    # Na mosca: baque + sino brilhante.
    t = _t(1.0)
    sino = (np.sin(2 * np.pi * 880 * t) + 0.6 * np.sin(2 * np.pi * 1320 * t) + 0.3 * np.sin(2 * np.pi * 1760 * t))
    sino *= _envelope(len(t), 0.005, 0.35)
    base = np.zeros(len(t))
    base[:len(sons["alvo"])] = sons["alvo"]
    sons["mosca"] = 0.6 * base + 0.35 * sino

    # Madeira (árvore): batida seca.
    t = _t(0.2)
    sons["madeira"] = 0.7 * np.sin(2 * np.pi * 320 * t) * _envelope(len(t), 0.0, 0.03) + \
        0.3 * _ruido(len(t), rng) * _envelope(len(t), 0.0, 0.008)

    # Chão: terra abafada.
    t = _t(0.25)
    sons["chao"] = 0.6 * _passa_baixa(_ruido(len(t), rng), 25) * _envelope(len(t), 0.0, 0.05)

    # Bônus: arpejo ascendente.
    notas = [523, 659, 784, 1047]
    partes = []
    for f in notas:
        t = _t(0.09)
        partes.append(np.sin(2 * np.pi * f * t) * _envelope(len(t), 0.003, 0.05))
    t = _t(0.5)
    partes.append(np.sin(2 * np.pi * 1047 * t) * _envelope(len(t), 0.003, 0.18))
    sons["bonus"] = 0.45 * np.concatenate(partes)

    # Clique da interface.
    t = _t(0.06)
    sons["clique"] = 0.4 * np.sin(2 * np.pi * 1200 * t) * _envelope(len(t), 0.0, 0.012)

    # Fanfarra de fim de torneio (trompa suave: quadrada filtrada).
    partes = []
    for f, d in ((392, 0.18), (523, 0.18), (659, 0.18), (784, 0.6)):
        t = _t(d)
        onda = np.sign(np.sin(2 * np.pi * f * t))
        partes.append(_passa_baixa(onda, 8) * _envelope(len(t), 0.01, d * 0.8))
    sons["fanfarra"] = 0.3 * np.concatenate(partes)

    # Ambiente em laço: vento suave + pios de pássaros.
    duracao = 8.0
    t = _t(duracao)
    vento = _passa_baixa(_ruido(len(t), rng), 120)
    vento *= 0.6 + 0.4 * np.sin(2 * np.pi * t / duracao)  # período = duração: laço sem emenda
    vento /= np.abs(vento).max() + 1e-9
    ambiente = 0.25 * vento
    for _ in range(7):
        inicio = rng.uniform(0.2, duracao - 0.6)
        tt = _t(rng.uniform(0.08, 0.16))
        f0 = rng.uniform(2200, 3400)
        pio = np.sin(2 * np.pi * np.cumsum(f0 + 900 * np.sin(np.pi * tt / tt[-1])) / TAXA)
        pio *= np.sin(np.pi * tt / tt[-1]) * 0.12
        i = int(inicio * TAXA)
        ambiente[i:i + len(pio)] += pio
    sons["ambiente"] = ambiente
    # Rangido contínuo da corda/madeira esticando: laço de 1 s sem emenda.
    # Ruído grave filtrado + "grãos" de atrito em ritmo irregular (stick-slip da corda).
    t = _t(1.0)
    base = _passa_baixa(_ruido(len(t), rng), 30)
    base *= 0.5 + 0.5 * np.sin(2 * np.pi * 3 * t) ** 2  # período divide 1 s: laço sem emenda
    graos = np.zeros(len(t))
    for inicio in np.sort(rng.uniform(0, 0.95, 14)):
        n = int(TAXA * rng.uniform(0.012, 0.03))
        i = int(inicio * TAXA)
        tt = np.arange(n) / TAXA
        f = rng.uniform(180, 420)
        grao = np.sin(2 * np.pi * f * tt) * np.exp(-tt / 0.008)
        graos[i:i + n] += grao[:len(graos) - i]
    sons["rangido"] = 0.5 * base / (np.abs(base).max() + 1e-9) + 0.45 * graos

    # Estalos de tensão: rangidos curtos, cada vez mais agudos (25%, 50%, 75%, 95% de força).
    for k, f0 in enumerate((160, 230, 320, 450), start=1):
        t = _t(0.22)
        freq = f0 * (1 + 0.25 * t / t[-1])
        fase = 2 * np.pi * np.cumsum(freq) / TAXA
        atrito = np.sign(np.sin(fase)) * _passa_baixa(_ruido(len(t), rng) * 0.5 + 1, 5)
        sons[f"tensao{k}"] = 0.35 * _passa_baixa(atrito, 4) * _envelope(len(t), 0.01, 0.06)

    # Normaliza picos acima de 0.9 (evita distorção ao converter para 16 bits).
    for nome, onda in sons.items():
        pico = np.abs(onda).max()
        if pico > 0.9:
            sons[nome] = onda * (0.9 / pico)
    return sons


class Sons:
    def __init__(self, ligado=True):
        self.ok = False
        self._sons = {}
        self._canal_rangido = None
        self._limiar = 0
        if not ligado:
            return
        try:
            import pygame
            if not pygame.mixer.get_init():
                pygame.mixer.init(TAXA, -16, 2, 512)
            frequencia, _, canais = pygame.mixer.get_init()
            for nome, onda in gerar().items():
                if frequencia != TAXA:
                    novo = np.interp(np.linspace(0, len(onda) - 1, int(len(onda) * frequencia / TAXA)),
                                     np.arange(len(onda)), onda)
                    onda = novo
                amostras = (np.clip(onda, -1, 1) * 32000).astype(np.int16)
                if canais == 2:
                    amostras = np.column_stack((amostras, amostras))
                self._sons[nome] = pygame.sndarray.make_sound(np.ascontiguousarray(amostras))
            self.ok = True
        except Exception:
            self._sons = {}

    def tocar(self, nome, volume=1.0, pan=0.0):
        """pan em [-1, 1]: -1 = só esquerda, 1 = só direita (potência constante)."""
        som = self._sons.get(nome)
        if som is None:
            return
        canal = som.play()
        if canal is not None:
            angulo = (max(-1.0, min(1.0, pan)) + 1) * np.pi / 4
            canal.set_volume(volume * np.cos(angulo) * 1.41, volume * np.sin(angulo) * 1.41)

    # ---------------------------------------------------------------- rangido contínuo da puxada

    def iniciar_rangido(self):
        som = self._sons.get("rangido")
        if som is None or self._canal_rangido is not None:
            return
        self._canal_rangido = som.play(loops=-1)
        self._limiar = 0
        if self._canal_rangido is not None:
            self._canal_rangido.set_volume(0.1)

    def ajustar_rangido(self, forca, velocidade):
        """Volume acompanha a força e cresce enquanto ela sobe; estalos ao cruzar os limiares."""
        if self._canal_rangido is not None:
            volume = 0.12 + 0.55 * forca + min(0.35, max(0.0, velocidade) * 0.25)
            self._canal_rangido.set_volume(min(1.0, volume))
        for k, limiar in enumerate((0.25, 0.5, 0.75, 0.95), start=1):
            if forca >= limiar and self._limiar < k:
                self._limiar = k
                self.tocar(f"tensao{k}", 0.8)

    def parar_rangido(self):
        if self._canal_rangido is not None:
            self._canal_rangido.fadeout(80)
            self._canal_rangido = None
        self._limiar = 0

    def ambiente(self, volume=0.35):
        som = self._sons.get("ambiente")
        if som is not None:
            som.set_volume(volume)
            som.play(loops=-1)
