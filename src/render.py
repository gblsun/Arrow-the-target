"""Pipeline de renderização em software: modelo -> mundo -> câmera -> projeção -> pintor.

Os cálculos por face (iluminação, descarte e profundidade) são vetorizados com numpy;
apenas o desenho final dos polígonos visíveis é feito em laço Python.
"""
import math

import numpy as np
import pygame

import mat3d as m3

DIFUSA = 0.68
NEBLINA_INICIO, NEBLINA_FIM, NEBLINA_MAX = 30.0, 170.0, 0.88
NEAR = 0.15
DISTANCIA_MAX = 230.0


# Paletas do ciclo de luz: o torneio começa à tarde e termina no pôr do sol.
TARDE = dict(sol=(-38, 9), luz=(-0.45, 0.8, -0.35), ambiente=0.42, tom=(1.0, 0.93, 0.80), ceu_topo=(104, 152, 200),
             ceu_horizonte=(238, 212, 170), grama_perto=(82, 118, 52), grama_longe=(128, 150, 96),
             cor_sol=(255, 244, 214))
POR_DO_SOL = dict(sol=(-50, 1.5), luz=(-0.75, 0.38, -0.3), ambiente=0.34, tom=(1.0, 0.70, 0.48), ceu_topo=(58, 66, 120),
                  ceu_horizonte=(250, 150, 92), grama_perto=(62, 84, 40), grama_longe=(150, 120, 80),
                  cor_sol=(255, 190, 120))


class Iluminacao:
    """Estado global da luz. `versao` muda a cada ajuste para os lotes se reiluminarem."""

    def __init__(self):
        self.versao = 0
        self.hora = -1.0
        self.definir_hora(0.0)

    def definir_hora(self, hora):
        """hora em [0, 1]: 0 = tarde, 1 = pôr do sol."""
        hora = m3.limitar(hora)
        if abs(hora - self.hora) < 0.02:
            return False
        self.hora = hora
        mistura = lambda a, b: tuple(m3.lerp(x, y, hora) for x, y in zip(a, b))
        yaw, elev = mistura(TARDE["sol"], POR_DO_SOL["sol"])
        self.direcao_sol = m3.direcao(math.radians(yaw), math.radians(elev))
        # A luz do sombreamento vem de trás do jogador (ilumina a frente dos alvos) e desce ao entardecer.
        luz = np.array(mistura(TARDE["luz"], POR_DO_SOL["luz"]))
        self.luz = luz / np.linalg.norm(luz)
        self.ambiente = m3.lerp(TARDE["ambiente"], POR_DO_SOL["ambiente"], hora)
        self.tom = np.array(mistura(TARDE["tom"], POR_DO_SOL["tom"]))
        for chave in ("ceu_topo", "ceu_horizonte", "grama_perto", "grama_longe", "cor_sol"):
            setattr(self, chave, tuple(int(c) for c in mistura(TARDE[chave], POR_DO_SOL[chave])))
        self.neblina = np.array(self.ceu_horizonte, dtype=float) * 0.92
        self.versao += 1
        return True

    def iluminar(self, cores_base, normais, destaque):
        lambert = np.clip(normais @ self.luz, 0, 1)
        intensidade = self.ambiente + DIFUSA * lambert
        cores = np.clip(cores_base * intensidade[:, None] * self.tom, 0, 255)
        cores[destaque] = np.clip(cores[destaque] * 1.15 + 25, 0, 255)
        return cores


ILUMINACAO = Iluminacao()


class Lote:
    """Conjunto de faces já em coordenadas de mundo, pronto para desenho vetorizado."""

    def __init__(self, itens):
        """`itens`: lista de (malha, matriz_modelo, destaque)."""
        vertices, faces, cores, vies, destaque = [], [], [], [], []
        base = 0
        for malha, m, realce in itens:
            vertices.append(m3.aplicar(m, malha.vertices))
            faces += [tuple(i + base for i in f) for f in malha.faces]
            cores += malha.cores
            vies += malha.vies
            destaque += [realce] * len(malha.faces)
            base += len(malha.vertices)
        self.vazio = not faces
        if self.vazio:
            return
        self.vertices = np.vstack(vertices)
        largura = max(len(f) for f in faces)
        self.contagem = np.array([len(f) for f in faces])
        self.indices = np.array([f + (f[-1],) * (largura - len(f)) for f in faces])
        self.vies = np.array(vies, dtype=float)
        self.destaque = np.array(destaque, dtype=bool)

        v = self.vertices
        a, b, c = v[self.indices[:, 0]], v[self.indices[:, 1]], v[self.indices[:, 2]]
        normal = np.cross(b - a, c - a)
        normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-9)
        self.normais = normal
        # Centro da face sem contar os índices repetidos do preenchimento.
        self.mascara = np.arange(largura)[None, :] < self.contagem[:, None]
        self.centros = (v[self.indices] * self.mascara[..., None]).sum(axis=1) / self.contagem[:, None]

        self.cores_base = np.array(cores, dtype=float)
        self._versao_luz = -1
        self._cores = None

    @property
    def cores(self):
        """Cores iluminadas, recalculadas só quando a luz muda (ciclo do dia)."""
        if self._versao_luz != ILUMINACAO.versao:
            self._cores = ILUMINACAO.iluminar(self.cores_base, self.normais, self.destaque)
            self._versao_luz = ILUMINACAO.versao
        return self._cores


class Renderizador:
    def __init__(self, largura, altura):
        self.largura, self.altura = largura, altura
        self.centro = (largura / 2, altura / 2)
        self._versao_fundo = -1
        self.focal = m3.distancia_focal(largura, 70)
        self.visao = np.eye(4)
        self.posicao = np.zeros(3)
        self.yaw = self.pitch = 0.0

    def _atualizar_fundo(self):
        """Céu, chão e sol seguem a hora do dia; só são refeitos quando a luz muda."""
        if self._versao_fundo == ILUMINACAO.versao:
            return
        il = ILUMINACAO
        self.fundo = self._gradiente(self.altura * 3, [(0.0, il.ceu_topo), (0.5, il.ceu_horizonte)])
        medio = tuple(int(m3.lerp(a, b, 0.5)) for a, b in zip(il.grama_longe, il.grama_perto))
        escuro = tuple(int(c * 0.72) for c in il.grama_perto)
        self.chao = self._gradiente(self.altura * 2, [(0.0, il.grama_longe), (0.04, medio), (0.4, il.grama_perto), (1.0, escuro)])
        self.sol = pygame.Surface((140, 140), pygame.SRCALPHA)
        for raio, alfa in ((70, 30), (45, 60), (26, 255)):
            pygame.draw.circle(self.sol, (*il.cor_sol, alfa), (70, 70), raio)
        self._versao_fundo = il.versao

    def _gradiente(self, altura, paradas):
        sup = pygame.Surface((1, altura))
        for y in range(altura):
            u = y / (altura - 1)
            for (u0, c0), (u1, c1) in zip(paradas, paradas[1:]):
                if u0 <= u <= u1:
                    k = (u - u0) / (u1 - u0)
                    break
            else:
                c0 = c1 = paradas[-1][1]
                k = 0
            sup.set_at((0, y), [int(m3.lerp(a, b, k)) for a, b in zip(c0, c1)])
        return pygame.transform.scale(sup, (self.largura, altura))

    def definir_camera(self, posicao, yaw, pitch, fov):
        self.posicao = np.asarray(posicao, dtype=float)
        self.yaw, self.pitch = yaw, pitch
        self.visao = m3.matriz_visao(self.posicao, yaw, pitch)
        self.focal = m3.distancia_focal(self.largura, fov)

    # ---------------------------------------------------------------- projeção de pontos soltos

    def projetar_ponto(self, ponto):
        """Ponto de mundo -> (x, y) de tela, ou None se estiver atrás da câmera."""
        p = m3.aplicar_ponto(self.visao, ponto)
        if p[2] < NEAR:
            return None
        s = m3.projetar(p, self.focal, self.centro)
        return float(s[0]), float(s[1])

    # ---------------------------------------------------------------- fundo

    def desenhar_fundo(self, tela, direcao_sol=None):
        self._atualizar_fundo()
        direcao_sol = ILUMINACAO.direcao_sol if direcao_sol is None else direcao_sol
        horizonte = self.centro[1] + self.focal * math.tan(self.pitch)
        tela.blit(self.fundo, (0, int(horizonte - self.fundo.get_height() / 2)))
        sol = self.projetar_ponto(self.posicao + direcao_sol * 500)
        if sol:
            tela.blit(self.sol, (sol[0] - 70, sol[1] - 70))
        y = int(horizonte)
        if y < self.altura:
            tela.blit(self.chao, (0, y), area=pygame.Rect(0, 0, self.largura, self.altura - max(y, 0) + 2))

    # ---------------------------------------------------------------- lotes

    def _preparar(self, lote):
        """Descarte, recorte e cor final das faces visíveis de um lote. Devolve lista (prof, cor, pontos, contorno)."""
        if lote.vazio:
            return []
        v_cam = m3.aplicar(self.visao, lote.vertices)
        para_cam = self.posicao - lote.centros
        frente = np.einsum("ij,ij->i", lote.normais, para_cam) > 0
        z = v_cam[lote.indices, 2]
        z_max = z.max(axis=1)
        prof = (z * lote.mascara).sum(axis=1) / lote.contagem
        visivel = frente & (z_max > NEAR) & (prof < DISTANCIA_MAX)

        # Descarte lateral: todos os vértices fora do mesmo lado do tronco de visão.
        zc = np.maximum(v_cam[..., 2], NEAR)
        sx = self.centro[0] + self.focal * v_cam[..., 0] / zc
        sy = self.centro[1] - self.focal * v_cam[..., 1] / zc
        fx, fy = sx[lote.indices], sy[lote.indices]
        atras = z < NEAR
        fora = ((fx < 0) & ~atras).all(1) | ((fx > self.largura) & ~atras).all(1) | ((fy > self.altura) & ~atras).all(1) | ((fy < 0) & ~atras).all(1)
        visivel &= ~fora

        neblina = np.clip((prof - NEBLINA_INICIO) / (NEBLINA_FIM - NEBLINA_INICIO), 0, NEBLINA_MAX)
        cores = lote.cores * (1 - neblina[:, None]) + ILUMINACAO.neblina * neblina[:, None]

        # Faces que cruzam o plano near são recortadas em 3D; as demais só precisam de
        # recorte 2D quando ultrapassam a janela. Faces menores que um pixel são ignoradas.
        cruza_near = atras.any(axis=1)
        fx_min, fx_max = fx.min(axis=1), fx.max(axis=1)
        fy_min, fy_max = fy.min(axis=1), fy.max(axis=1)
        minuscula = ~cruza_near & (fx_max - fx_min < 1.0) & (fy_max - fy_min < 1.0)
        visivel &= ~minuscula
        excede = cruza_near | (fx_min < -4) | (fx_max > self.largura + 4) | (fy_min < -4) | (fy_max > self.altura + 4)

        sel = np.nonzero(visivel)[0]
        chaves = (prof - lote.vies)[sel].tolist()
        cores_sel = cores[sel].tolist()
        pontos_sel = np.stack((fx[sel], fy[sel]), axis=2).tolist()
        contagens = lote.contagem[sel].tolist()
        destaques = lote.destaque[sel].tolist()
        excede_sel = excede[sel].tolist()
        near_sel = cruza_near[sel].tolist()

        saida = []
        for k, i in enumerate(sel.tolist()):
            n = contagens[k]
            if near_sel[k]:
                recortado = m3.recortar_near(list(v_cam[lote.indices[i, :n]]), NEAR)
                if len(recortado) < 3:
                    continue
                pontos = m3.projetar(np.array(recortado), self.focal, self.centro).tolist()
            else:
                pontos = pontos_sel[k][:n]
            saida.append((chaves[k], cores_sel[k], pontos, destaques[k], excede_sel[k]))
        return saida

    def _recortar_tela(self, pontos):
        """Recorte 2D contra a janela: polígonos muito grandes fora da tela custam caro ao rasterizar."""
        xs = [p[0] for p in pontos]
        ys = [p[1] for p in pontos]
        if min(xs) >= -4 and max(xs) <= self.largura + 4 and min(ys) >= -4 and max(ys) <= self.altura + 4:
            return pontos
        for eixo, limite, sinal in ((0, -2, 1), (0, self.largura + 2, -1), (1, -2, 1), (1, self.altura + 2, -1)):
            saida = []
            n = len(pontos)
            for i in range(n):
                a, b = pontos[i], pontos[(i + 1) % n]
                da, db = (a[eixo] - limite) * sinal, (b[eixo] - limite) * sinal
                if da >= 0:
                    saida.append(a)
                if (da >= 0) != (db >= 0):
                    t = da / (da - db)
                    saida.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            pontos = saida
            if len(pontos) < 3:
                return pontos
        return pontos

    def desenhar_lotes(self, tela, lotes, contorno=(255, 214, 90)):
        faces = []
        for lote in lotes:
            faces += self._preparar(lote)
        faces.sort(key=lambda f: -f[0])
        for _, cor, pontos, destaque, excede in faces:
            if excede:
                pontos = self._recortar_tela(pontos)
                if len(pontos) < 3:
                    continue
            pygame.draw.polygon(tela, cor, pontos)
            if destaque:
                pygame.draw.polygon(tela, contorno, pontos, 2)
