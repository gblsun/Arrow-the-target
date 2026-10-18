"""Unifica gesto (arco com as duas mãos, até duas câmeras), mouse e teclado num comando por quadro.

Papéis das mãos (destro; a tecla L inverte):
- mão esquerda, à frente: segura o arco e define a mira (câmera frontal);
- mão direita, atrás: fechada segura a corda; a distância até a mão do arco é a força
  (medida de preferência pela câmera lateral); abrir a mão solta a flecha.
"""
import time
from collections import deque
from statistics import median
from dataclasses import dataclass

import pygame

import mat3d as m3
from gestos import distancia

# Mão da corda: fechada se fizer pinça OU punho; aberta só com pinça aberta E dedos estendidos.
PINCA_FECHA, PINCA_ABRE = 0.35, 0.55
CURVA_FECHA, CURVA_ABRE = 1.2, 1.45
FORCA_MINIMA = 0.2
SUAVIZACAO = 0.35  # média móvel exponencial da mira
VALIDADE = 0.4  # leituras de câmera mais antigas que isso são ignoradas (s)
JANELA_DISPARO = 0.25  # força do disparo = máxima dos últimos instantes antes de abrir a mão
TEMPO_PREPARO = 3.0  # contagem regressiva antes de cada etapa
TEMPO_ETAPA = 2.0  # tempo parado na pose para concluir a etapa
ESTABILIDADE = 0.03  # deslocamento máximo das palmas entre quadros para contar como "parado"
AMPLITUDE_MINIMA = 0.05  # diferença mínima entre repouso e puxada (fração da imagem)
TEMPO_POLEGAR = 0.7
TEMPO_PUXADA_MOUSE = 1.1

ETAPAS_CALIBRACAO = [
    ("Arco em repouso", [
        "Braço esquerdo esticado à frente, mão na altura do peito.",
        "Mão direita fechada, encostada na esquerda, segurando a corda.",
    ]),
    ("Puxada completa", [
        "Sem mexer a mão esquerda, puxe a direita para trás.",
        "Leve a mão direita fechada até o rosto (ponto de âncora).",
    ]),
    ("Tiro de teste", [
        "Puxe e abra a mão direita para soltar uma flecha de teste.",
        "Polegar para cima (ou Enter) começa; polegar para baixo refaz.",
    ]),
]


@dataclass
class Comando:
    mira: tuple = (0.0, 0.0)  # [-1, 1] em x (direita) e y (baixo)
    puxando: bool = False
    forca: float = 0.0
    disparou: bool = False
    forca_disparo: float = 0.0
    confirmar: bool = False
    fonte: str = "mouse"


@dataclass
class Escala:
    """Converte a distância entre as palmas (fração da imagem) em força [0, 1]."""
    repouso: float
    cheia: float

    def forca(self, d):
        return m3.limitar((d - self.repouso) / (self.cheia - self.repouso))


class Entrada:
    def __init__(self, frontal, lateral, largura, altura):
        self.frontal, self.lateral = frontal, lateral
        self.largura, self.altura = largura, altura
        self.canhoto = False
        self.centro = (0.5, 0.5)
        self.escalas = {"frontal": Escala(0.08, 0.32), "lateral": Escala(0.08, 0.40)}
        self.indice_corda_lateral = 1  # posição (ordem em x) da mão da corda na imagem lateral
        self.reiniciar_calibracao()

        self._mira_gesto = (0.0, 0.0)
        self._fechada = False
        self._puxando_gesto = False
        self._forca_gesto = 0.0
        self._historico = deque(maxlen=30)
        self._ultimo_gesto = 0.0
        self._eventos = []
        self.fonte_forca = ""
        self.maos_frontal = self.maos_lateral = 0

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

    # ---------------------------------------------------------------- leitura das câmeras

    @property
    def gesto_ativo(self):
        return time.monotonic() - self._ultimo_gesto < VALIDADE

    @property
    def mao_fechada(self):
        return self._fechada

    @property
    def lado_arco(self):
        return "Right" if self.canhoto else "Left"

    def definir_cameras(self, frontal, lateral):
        self.frontal, self.lateral = frontal, lateral
        self.reiniciar_calibracao()

    def trocar_cameras(self):
        self.frontal, self.lateral = self.lateral, self.frontal
        self.reiniciar_calibracao()

    def _maos(self, rastreador):
        if rastreador is None or not rastreador.ativo:
            return []
        leitura = rastreador.leitura()
        if time.monotonic() - leitura.instante > VALIDADE:
            return []
        return leitura.maos

    def _papeis_frontal(self, maos):
        """(arco, corda) pela lateralidade do MediaPipe; se ambígua, a mão do arco é a maior (mais perto)."""
        arco = [m for m in maos if m.lado == self.lado_arco]
        corda = [m for m in maos if m.lado and m.lado != self.lado_arco]
        if len(maos) >= 2 and (len(arco) != 1 or len(corda) != 1):
            a, b = sorted(maos[:2], key=lambda m: -m.tamanho)
            return a, b
        return (arco[0] if arco else None), (corda[0] if corda else None)

    def _papeis_lateral(self, maos):
        """De perfil a lateralidade é pouco confiável: usa a posição calibrada em x."""
        if len(maos) < 2:
            return None, None
        ordenadas = sorted(maos[:2], key=lambda m: m.palma[0])
        return ordenadas[1 - self.indice_corda_lateral], ordenadas[self.indice_corda_lateral]

    def _medir(self):
        """Mão do arco (frontal), mão da corda, distância entre palmas e a câmera que a mediu."""
        mf, ml = self._maos(self.frontal), self._maos(self.lateral)
        self.maos_frontal, self.maos_lateral = len(mf), len(ml)
        arco_f, corda_f = self._papeis_frontal(mf)
        arco_l, corda_l = self._papeis_lateral(ml)
        if arco_l and corda_l:
            return arco_f, corda_l, distancia(arco_l.palma, corda_l.palma), "lateral"
        if arco_f and corda_f:
            return arco_f, corda_f, distancia(arco_f.palma, corda_f.palma), "frontal"
        return arco_f, corda_f or corda_l, None, ""

    def _esta_fechada(self, mao, estava):
        pinca, curva = mao.abertura_pinca, mao.curvatura
        if estava:
            return not (pinca > PINCA_ABRE and curva > CURVA_ABRE)
        return pinca < PINCA_FECHA or curva < CURVA_FECHA

    def _ler_gesto(self):
        self._eventos = []
        arco, corda, dist, fonte = self._medir()
        self.fonte_forca = fonte
        agora = time.monotonic()

        if arco is not None:
            self._ultimo_gesto = agora
            alvo_x = m3.limitar((arco.palma[0] - self.centro[0]) / 0.22, -1, 1)
            alvo_y = m3.limitar((arco.palma[1] - self.centro[1]) / 0.2, -1, 1)
            mx, my = self._mira_gesto
            self._mira_gesto = (m3.lerp(mx, alvo_x, SUAVIZACAO), m3.lerp(my, alvo_y, SUAVIZACAO))

        if corda is None:
            self._puxando_gesto = self._fechada = False  # mão da corda sumiu: cancela sem atirar
            return

        estava = self._fechada
        self._fechada = self._esta_fechada(corda, estava)
        forca = self.escalas[fonte].forca(dist) if dist is not None else None

        if self._fechada and not estava:
            self._eventos.append("confirmar")
            self._puxando_gesto = forca is not None
            self._forca_gesto = 0.0
            self._historico.clear()
        if self._fechada and self._puxando_gesto and forca is not None:
            self._forca_gesto = m3.lerp(self._forca_gesto, forca, 0.5)
            self._historico.append((agora, self._forca_gesto))
        if not self._fechada and estava and self._puxando_gesto:
            self._puxando_gesto = False
            recentes = [f for t, f in self._historico if agora - t <= JANELA_DISPARO]
            forca_disparo = max(recentes, default=self._forca_gesto)
            if forca_disparo >= FORCA_MINIMA:
                self._eventos.append(("disparo", forca_disparo))

    # ---------------------------------------------------------------- calibração guiada

    def reiniciar_calibracao(self):
        self.calibrado = False
        self.etapa = 0
        self._amostras = [[], []]
        self.checklist = []
        self.teste_forca = None
        self._polegar, self._tempo_polegar = None, 0.0
        self._preparar("")

    def _preparar(self, aviso):
        self.fase = "preparar"
        self.contagem = TEMPO_PREPARO
        self._tempo_etapa = 0.0
        self._ultima_pose = None
        self.aviso = aviso

    @property
    def progresso_etapa(self):
        return m3.limitar(self._tempo_etapa / TEMPO_ETAPA)

    def calibrar(self, dt):
        """Avança a calibração guiada: preparo (contagem) -> coleta parada -> validação."""
        mf, ml = self._maos(self.frontal), self._maos(self.lateral)
        self.maos_frontal, self.maos_lateral = len(mf), len(ml)
        arco_f, corda_f = self._papeis_frontal(mf)
        lateral = sorted(ml[:2], key=lambda m: m.palma[0]) if len(ml) >= 2 else None
        corda = corda_f or (min(ml, key=lambda m: m.curvatura) if ml else None)
        fechada = corda is not None and self._esta_fechada(corda, False)
        self.checklist = [
            ("Mão esquerda vista pela câmera frontal", arco_f is not None),
            ("Mão direita fechada, segurando a corda", fechada),
        ]
        if self.lateral is not None and self.lateral.ativo:
            self.checklist.append(("Câmera lateral vê as duas mãos", lateral is not None))
        if self.etapa == 2:
            return

        if self.fase == "preparar":
            self.contagem -= dt
            if self.contagem <= 0:
                self.fase = "coletar"
            return

        if not all(ok for _, ok in self.checklist):
            self._tempo_etapa = max(0.0, self._tempo_etapa - dt * 0.5)
            self.aviso = "Ajuste a pose até todos os itens ficarem verdes"
            return
        pose = [arco_f.palma, corda.palma] + ([m.palma for m in lateral] if lateral else [])
        if self._ultima_pose is not None and len(pose) == len(self._ultima_pose):
            movimento = max(distancia(a, b) for a, b in zip(pose, self._ultima_pose))
        else:
            movimento = 0.0
        self._ultima_pose = pose
        if movimento > ESTABILIDADE:
            self._tempo_etapa = max(0.0, self._tempo_etapa - dt * 0.5)
            self.aviso = "Segure firme, sem mexer as mãos"
            return

        self.aviso = ""
        self._tempo_etapa += dt
        self._amostras[self.etapa].append({
            "palma": arco_f.palma,
            "frontal": distancia(arco_f.palma, corda_f.palma) if corda_f else None,
            "lateral": [m.palma for m in lateral] if lateral else None,
        })
        if self._tempo_etapa >= TEMPO_ETAPA:
            self.avancar_etapa()

    def avancar_etapa(self):
        """Conclui a etapa atual (também usado pelo Enter para pular)."""
        if self.etapa == 0:
            self.etapa = 1
            self._preparar("")
        elif self.etapa == 1:
            ok = self._concluir()
            if not ok and self._amostras[1]:
                self._amostras[1] = []
                self._preparar("A puxada foi curta: leve a mão direita até o rosto")
                return
            self.etapa = 2
            self.calibrado = True
            self.teste_forca = None

    def _concluir(self):
        """Calcula mira e escalas de força pela mediana das amostras. False se a puxada foi curta."""
        repouso, cheia = self._amostras
        if repouso:
            self.centro = (median(a["palma"][0] for a in repouso), median(a["palma"][1] for a in repouso))
        medida = False
        d0 = [a["frontal"] for a in repouso if a["frontal"] is not None]
        d1 = [a["frontal"] for a in cheia if a["frontal"] is not None]
        if d0 and d1 and median(d1) - median(d0) > AMPLITUDE_MINIMA:
            self.escalas["frontal"] = Escala(median(d0), median(d1))
            medida = True
        l0 = [a["lateral"] for a in repouso if a["lateral"]]
        l1 = [a["lateral"] for a in cheia if a["lateral"]]
        if l0 and l1:
            # A mão da corda é a que mais se deslocou entre o repouso e a puxada.
            mediana = lambda pts, i: (median(p[i][0] for p in pts), median(p[i][1] for p in pts))
            desloc = [distancia(mediana(l0, i), mediana(l1, i)) for i in (0, 1)]
            self.indice_corda_lateral = 0 if desloc[0] > desloc[1] else 1
            r0 = median(distancia(p[0], p[1]) for p in l0)
            r1 = median(distancia(p[0], p[1]) for p in l1)
            if r1 - r0 > AMPLITUDE_MINIMA:
                self.escalas["lateral"] = Escala(r0, r1)
                medida = True
        return medida

    def gesto_polegar(self, dt):
        """'cima'/'baixo' quando o polegar fica nessa posição por TEMPO_POLEGAR segundos."""
        atual = None
        for mao in self._maos(self.frontal):
            atual = atual or mao.polegar
        if atual != self._polegar:
            self._polegar, self._tempo_polegar = atual, 0.0
            return None
        if atual is None:
            return None
        self._tempo_polegar += dt
        if self._tempo_polegar >= TEMPO_POLEGAR:
            self._tempo_polegar = -10.0  # evita repetir até mudar de gesto
            return atual
        return None

    @property
    def progresso_polegar(self):
        return m3.limitar(self._tempo_polegar / TEMPO_POLEGAR) if self._polegar else 0.0

    # ---------------------------------------------------------------- comando do quadro

    def soltar_tudo(self):
        """Descarta puxadas em andamento (usado ao trocar de tela)."""
        self._mouse_puxando = self._soltou_mouse = False
        self._forca_mouse = 0.0
        self._puxando_gesto = False

    def atualizar(self, dt):
        self._ler_gesto()
        cmd = Comando()

        if self._mouse_puxando:
            self._forca_mouse = min(1.0, self._forca_mouse + dt / TEMPO_PUXADA_MOUSE)

        if self.gesto_ativo and not self._mouse_puxando:
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

        for evento in self._eventos:
            if evento == "confirmar":
                cmd.confirmar = True
            elif evento[0] == "disparo":
                cmd.disparou, cmd.forca_disparo = True, evento[1]
        self._eventos = []

        if self._soltou_mouse:
            if self._forca_mouse >= FORCA_MINIMA:
                cmd.disparou, cmd.forca_disparo = True, self._forca_mouse
            self._forca_mouse = 0.0
            self._soltou_mouse = False
        if self._confirmar:
            cmd.confirmar = True
            self._confirmar = False
        return cmd
