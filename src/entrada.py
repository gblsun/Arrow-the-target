"""Unifica gesto (arco com as duas mãos, até duas câmeras), mouse e teclado num comando por quadro.

Papéis das mãos (destro; a tecla L inverte):
- mão esquerda, à frente: segura o arco e define a mira (câmera frontal);
- mão direita, atrás: fechada segura a corda; a distância até a mão do arco é a força
  (medida de preferência pela câmera lateral); abrir a mão solta a flecha.
"""
import math
import time
from collections import Counter, deque
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
TEMPO_DEDOS = 0.8  # tempo segurando 1, 2 ou 3 dedos (qualquer mão) para trocar de posto
TOLERANCIA_PERDA = 0.25  # mão da corda pode sumir por esse tempo sem cancelar a puxada (s)
TAMANHO_RASTRO = 15
TEMPO_PUXADA_MOUSE = 1.1

ETAPAS_CALIBRACAO = [
    ("Mão esquerda", [
        "Levante só a mão esquerda, aberta, à frente do corpo (onde fica o arco).",
        "Deixe a mão direita abaixada, fora das duas câmeras.",
    ]),
    ("Mão direita", [
        "Abaixe a esquerda e levante só a mão direita, aberta, perto do rosto.",
        "As duas câmeras devem ver apenas essa mão.",
    ]),
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
ETAPA_ESQUERDA, ETAPA_DIREITA, ETAPA_REPOUSO, ETAPA_PUXADA, ETAPA_TESTE = range(5)
ROTULOS_PADRAO = {"esquerda": "Left", "direita": "Right"}


@dataclass
class Comando:
    mira: tuple = (0.0, 0.0)  # [-1, 1] em x (direita) e y (baixo)
    puxando: bool = False
    forca: float = 0.0
    disparou: bool = False
    forca_disparo: float = 0.0
    confirmar: bool = False
    fonte: str = "mouse"
    posto: int = 0  # 1-3 quando a mão esquerda mostrou os dedos por TEMPO_DEDOS


class FiltroKalman1D:
    """Kalman de estado único (valor constante + ruído): suaviza a força sem atraso excessivo.

    q = quanto o valor real pode variar por passo; r = ruído da medida.
    """

    def __init__(self, q=0.02, r=0.04):
        self.q, self.r = q, r
        self.reiniciar()

    def reiniciar(self, valor=0.0):
        self.x, self.p = valor, 1.0

    def atualizar(self, medida):
        self.p += self.q
        ganho = self.p / (self.p + self.r)
        self.x += ganho * (medida - self.x)
        self.p *= 1 - ganho
        return self.x


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
        self.rotulos = dict(ROTULOS_PADRAO)  # lateralidade que o MediaPipe dá a cada mão real (frontal)
        self.reiniciar_calibracao()

        self._mira_gesto = (0.0, 0.0)
        self.inclinacao = 0.0  # rotação da mão do arco (rad), usada para inclinar o arco
        self._filtro_forca = FiltroKalman1D()
        self._corda_lateral_anterior = None
        # Troca de posto pelos dedos da mão do arco.
        self.dedos_atual = 0
        self._maos_frontais = []
        self._ultima_corda = 0.0
        self.progresso_dedos = 0.0
        self._dedos_desde = 0.0
        self._dedos_usado = False
        # Últimas mãos identificadas e rastro da mão da corda, por câmera (para as prévias).
        self.pares = {"frontal": (None, None), "lateral": (None, None)}
        self.maos_camera = {"frontal": [], "lateral": []}
        self.rastros = {"frontal": deque(maxlen=TAMANHO_RASTRO), "lateral": deque(maxlen=TAMANHO_RASTRO)}
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
        return self.rotulos["direita" if self.canhoto else "esquerda"]

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
        """De perfil a lateralidade é pouco confiável: usa a posição calibrada em x e,
        quadro a quadro, a continuidade (a mão da corda é a mais próxima de onde ela estava)."""
        if len(maos) < 2:
            self._corda_lateral_anterior = None
            return None, None
        a, b = maos[:2]
        anterior = self._corda_lateral_anterior  # (palma do arco, palma da corda) no quadro anterior
        arco = corda = None
        if anterior is not None:
            # Escolhe a atribuição com menor deslocamento total das duas mãos.
            direto = distancia(a.palma, anterior[0]) + distancia(b.palma, anterior[1])
            trocado = distancia(b.palma, anterior[0]) + distancia(a.palma, anterior[1])
            if min(direto, trocado) < 0.3:  # salto grande: volta para a ordem em x
                arco, corda = (a, b) if direto <= trocado else (b, a)
        if corda is None:
            ordenadas = sorted((a, b), key=lambda m: m.palma[0])
            corda, arco = ordenadas[self.indice_corda_lateral], ordenadas[1 - self.indice_corda_lateral]
        self._corda_lateral_anterior = (arco.palma, corda.palma)
        return arco, corda

    def _medir(self):
        """Mão do arco (frontal), mão da corda, distância entre palmas e a câmera que a mediu."""
        mf, ml = self._maos(self.frontal), self._maos(self.lateral)
        self.maos_frontal, self.maos_lateral = len(mf), len(ml)
        self._maos_frontais = mf
        self.maos_camera = {"frontal": mf, "lateral": ml}  # mesma leitura dos pares (para desenhar)
        arco_f, corda_f = self._papeis_frontal(mf)
        arco_l, corda_l = self._papeis_lateral(ml)
        self.pares = {"frontal": (arco_f, corda_f), "lateral": (arco_l, corda_l)}
        for nome, corda in (("frontal", corda_f), ("lateral", corda_l)):
            rastro = self.rastros[nome]
            if corda is None:
                rastro.clear()
            elif not rastro or rastro[-1] != corda.palma:
                rastro.append(corda.palma)
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
            # Inclinação: ângulo do vetor pulso -> base do dedo médio em relação à vertical.
            px, py = arco.pontos[0]
            qx, qy = arco.palma
            angulo = m3.limitar(math.atan2(qx - px, py - qy), -0.7, 0.7)
            self.inclinacao = m3.lerp(self.inclinacao, angulo, 0.25)
        self._atualizar_dedos(agora)

        if corda is None:
            # Perda curta (oclusão, borrão) durante a puxada: mantém o estado e a força.
            if self._puxando_gesto and agora - self._ultima_corda < TOLERANCIA_PERDA:
                return
            self._puxando_gesto = self._fechada = False  # mão da corda sumiu: cancela sem atirar
            return
        self._ultima_corda = agora

        estava = self._fechada
        self._fechada = self._esta_fechada(corda, estava)
        if self._fechada and not estava and corda.dedos:
            self._fechada = False  # mostrando 1-3 dedos para trocar de posto: não é a corda presa
        forca = self.escalas[fonte].forca(dist) if dist is not None else None

        if self._fechada and not estava:
            self._eventos.append("confirmar")
            self._puxando_gesto = forca is not None
            self._forca_gesto = 0.0
            self._filtro_forca.reiniciar(forca or 0.0)
            self._historico.clear()
        if self._fechada and self._puxando_gesto and forca is not None:
            self._forca_gesto = m3.limitar(self._filtro_forca.atualizar(forca))
            self._historico.append((agora, self._forca_gesto))
        if not self._fechada and estava and self._puxando_gesto:
            self._puxando_gesto = False
            recentes = [f for t, f in self._historico if agora - t <= JANELA_DISPARO]
            forca_disparo = max(recentes, default=self._forca_gesto)
            if forca_disparo >= FORCA_MINIMA:
                self._eventos.append(("disparo", forca_disparo))

    def _atualizar_dedos(self, agora):
        """Qualquer mão (câmera frontal) com 1, 2 ou 3 dedos por TEMPO_DEDOS -> troca de posto.

        Se as duas mãos mostrarem contagens diferentes, nada acontece. Nunca durante uma
        puxada; depois de disparar, só aceita de novo quando a contagem mudar.
        """
        contagens = {m.dedos for m in self._maos_frontais if m.dedos}
        n = contagens.pop() if len(contagens) == 1 and not self._puxando_gesto else 0
        if n != self.dedos_atual:
            self.dedos_atual, self._dedos_desde, self._dedos_usado = n, agora, False
        if n == 0 or self._dedos_usado:
            self.progresso_dedos = 0.0
            return
        self.progresso_dedos = m3.limitar((agora - self._dedos_desde) / TEMPO_DEDOS)
        if self.progresso_dedos >= 1:
            self._dedos_usado = True
            self.progresso_dedos = 0.0
            self._eventos.append(("posto", n))

    # ---------------------------------------------------------------- calibração guiada

    def reiniciar_calibracao(self):
        self.calibrado = False
        self.etapa = ETAPA_ESQUERDA
        self._amostras = [[] for _ in ETAPAS_CALIBRACAO]
        self.rotulos = dict(ROTULOS_PADRAO)
        self._lateral_identificada = False  # ordem em x das mãos na lateral já veio das etapas 1 e 2
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

    @property
    def _usa_lateral(self):
        return self.lateral is not None and self.lateral.ativo

    def calibrar(self, dt):
        """Avança a calibração guiada: preparo (contagem) -> coleta parada -> validação."""
        self._medir()  # mantém os pares e rastros das prévias atualizados
        mf, ml = self._maos(self.frontal), self._maos(self.lateral)
        self.maos_frontal, self.maos_lateral = len(mf), len(ml)
        if self.etapa in (ETAPA_ESQUERDA, ETAPA_DIREITA):
            pose, amostra, aviso = self._pose_uma_mao(mf, ml)
        else:
            pose, amostra, aviso = self._pose_arco(mf, ml)
        if self.etapa == ETAPA_TESTE:
            return
        self._coletar(dt, pose, amostra, aviso)

    def _pose_uma_mao(self, mf, ml):
        """Etapas 1 e 2: só a mão da vez aparece, e cada câmera aprende qual mão é ela."""
        lado = "esquerda" if self.etapa == ETAPA_ESQUERDA else "direita"
        so_uma_f, so_uma_l = len(mf) == 1, len(ml) == 1
        self.checklist = [(f"Câmera frontal vê só a mão {lado}", so_uma_f)]
        if self._usa_lateral:
            self.checklist.append((f"Câmera lateral vê só a mão {lado}", so_uma_l))
        aviso = "Mostre só a mão " + lado + ", com a outra abaixada"
        if lado == "direita" and self._amostras[ETAPA_ESQUERDA]:
            diferente = so_uma_f and mf[0].lado != self.rotulos["esquerda"]
            self.checklist.append(("Reconhecida como outra mão (não a esquerda)", diferente))
            if so_uma_f and not diferente:
                aviso = "A câmera frontal confundiu com a esquerda: mostre a palma de frente"
        if not all(ok for _, ok in self.checklist):
            return None, None, aviso
        lateral = ml[0].palma if self._usa_lateral else None
        pose = [mf[0].palma] + ([lateral] if lateral else [])
        return pose, {"rotulo": mf[0].lado, "lateral": lateral}, ""

    def _pose_arco(self, mf, ml):
        """Etapas 3 a 5: as duas mãos na pose do arco."""
        arco_f, corda_f = self._papeis_frontal(mf)
        lateral = sorted(ml[:2], key=lambda m: m.palma[0]) if len(ml) >= 2 else None
        corda = corda_f or (min(ml, key=lambda m: m.curvatura) if ml else None)
        fechada = corda is not None and self._esta_fechada(corda, False)
        self.checklist = [
            ("Mão esquerda vista pela câmera frontal", arco_f is not None),
            ("Mão direita fechada, segurando a corda", fechada),
        ]
        if self._usa_lateral:
            self.checklist.append(("Câmera lateral vê as duas mãos", lateral is not None))
        if not all(ok for _, ok in self.checklist):
            return None, None, "Ajuste a pose até todos os itens ficarem verdes"
        pose = [arco_f.palma, corda.palma] + ([m.palma for m in lateral] if lateral else [])
        amostra = {
            "palma": arco_f.palma,
            "frontal": distancia(arco_f.palma, corda_f.palma) if corda_f else None,
            "lateral": [m.palma for m in lateral] if lateral else None,
        }
        return pose, amostra, ""

    def _coletar(self, dt, pose, amostra, aviso):
        """Conta o tempo parado na pose e guarda as amostras da etapa atual."""
        if self.fase == "preparar":
            self.contagem -= dt
            if self.contagem <= 0:
                self.fase = "coletar"
            return

        if pose is None:
            self._tempo_etapa = max(0.0, self._tempo_etapa - dt * 0.5)
            self.aviso = aviso
            return
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
        self._amostras[self.etapa].append(amostra)
        if self._tempo_etapa >= TEMPO_ETAPA:
            self.avancar_etapa()

    def avancar_etapa(self):
        """Conclui a etapa atual (também usado pelo Enter para pular)."""
        if self.etapa == ETAPA_ESQUERDA:
            self._identificar_esquerda()
            self.etapa = ETAPA_DIREITA
            self._preparar("")
        elif self.etapa == ETAPA_DIREITA:
            self._identificar_direita()
            self.etapa = ETAPA_REPOUSO
            self._preparar("")
        elif self.etapa == ETAPA_REPOUSO:
            self.etapa = ETAPA_PUXADA
            self._preparar("")
        elif self.etapa == ETAPA_PUXADA:
            ok = self._concluir()
            if not ok and self._amostras[ETAPA_PUXADA]:
                self._amostras[ETAPA_PUXADA] = []
                self._preparar("A puxada foi curta: leve a mão direita até o rosto")
                return
            self.etapa = ETAPA_TESTE
            self.calibrado = True
            self.teste_forca = None

    def _identificar_esquerda(self):
        """Rótulo do MediaPipe mais frequente para a mão esquerda real na câmera frontal."""
        amostras = [a["rotulo"] for a in self._amostras[ETAPA_ESQUERDA] if a["rotulo"]]
        if amostras:
            self.rotulos["esquerda"] = Counter(amostras).most_common(1)[0][0]
            self.rotulos["direita"] = "Right" if self.rotulos["esquerda"] == "Left" else "Left"

    def _identificar_direita(self):
        """Rótulo da mão direita na frontal e, na lateral, de que lado (em x) fica cada mão."""
        esquerda, direita = self._amostras[ETAPA_ESQUERDA], self._amostras[ETAPA_DIREITA]
        rotulos = [a["rotulo"] for a in direita if a["rotulo"]]
        if rotulos:
            self.rotulos["direita"] = Counter(rotulos).most_common(1)[0][0]
            if not esquerda:  # esquerda pulada: fica com o outro rótulo
                self.rotulos["esquerda"] = "Right" if self.rotulos["direita"] == "Left" else "Left"
        xe = [a["lateral"][0] for a in esquerda if a["lateral"]]
        xd = [a["lateral"][0] for a in direita if a["lateral"]]
        if xe and xd and abs(median(xd) - median(xe)) > AMPLITUDE_MINIMA:
            indice_direita = 1 if median(xd) > median(xe) else 0
            self.indice_corda_lateral = 1 - indice_direita if self.canhoto else indice_direita
            self._lateral_identificada = True

    def _concluir(self):
        """Calcula mira e escalas de força pela mediana das amostras. False se a puxada foi curta."""
        repouso, cheia = self._amostras[ETAPA_REPOUSO], self._amostras[ETAPA_PUXADA]
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
            if not self._lateral_identificada:
                # Sem as etapas 1 e 2: a mão da corda é a que mais se deslocou entre o repouso e a puxada.
                mediana = lambda pts, i: (median(p[i][0] for p in pts), median(p[i][1] for p in pts))
                desloc = [distancia(mediana(l0, i), mediana(l1, i)) for i in (0, 1)]
                self.indice_corda_lateral = 0 if desloc[0] > desloc[1] else 1
            r0 = median(distancia(p[0], p[1]) for p in l0)
            r1 = median(distancia(p[0], p[1]) for p in l1)
            if r1 - r0 > AMPLITUDE_MINIMA:
                self.escalas["lateral"] = Escala(r0, r1)
                medida = True
        return medida

    def exportar_calibracao(self):
        """Dados da calibração para salvar por pessoa (config.json)."""
        return {
            "centro": list(self.centro),
            "escalas": {k: [e.repouso, e.cheia] for k, e in self.escalas.items()},
            "indice_corda_lateral": self.indice_corda_lateral,
            "canhoto": self.canhoto,
            "rotulos": dict(self.rotulos),
        }

    def importar_calibracao(self, dados):
        try:
            centro = tuple(dados["centro"])
            escalas = {k: Escala(*v) for k, v in dados["escalas"].items()}
            indice = int(dados["indice_corda_lateral"])
            rotulos = dict(dados.get("rotulos", ROTULOS_PADRAO))  # calibrações antigas não têm
            if len(centro) != 2 or set(rotulos) != set(ROTULOS_PADRAO):
                return False
        except (KeyError, TypeError, ValueError):
            return False
        self.centro, self.escalas, self.indice_corda_lateral, self.rotulos = centro, escalas, indice, rotulos
        self.canhoto = bool(dados.get("canhoto", False))
        self.calibrado = True
        self.etapa = ETAPA_TESTE
        return True

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
            elif evento[0] == "posto":
                cmd.posto = evento[1]
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
