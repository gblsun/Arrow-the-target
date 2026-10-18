"""Interface sobre a cena: mira, arco em primeira pessoa, placar, avisos e telas de menu."""
import math

import numpy as np
import pygame

import mat3d as m3

OURO = (240, 204, 110)
PERGAMINHO = (238, 224, 190)
TINTA = (52, 36, 24)
MADEIRA = (110, 72, 40)
MADEIRA_CLARA = (160, 112, 64)
VERDE = (120, 200, 110)
VERMELHO = (220, 90, 70)


def cor_forca(forca):
    """Verde (fraca) -> amarelo -> vermelho (força máxima)."""
    verde, amarelo, vermelho = (110, 210, 90), (240, 210, 70), (230, 70, 50)
    if forca < 0.5:
        a, b, u = verde, amarelo, forca / 0.5
    else:
        a, b, u = amarelo, vermelho, (forca - 0.5) / 0.5
    return tuple(int(m3.lerp(x, y, m3.limitar(u))) for x, y in zip(a, b))


def desenhar_puxada(tela, rect, par, rastro, forca, puxando, fechada, fonte=None):
    """Desenha sobre a imagem da câmera o arco na mão esquerda, a corda até a mão direita
    e o rastro do movimento, tudo na cor da força (verde -> amarelo -> vermelho)."""
    arco, corda = par
    if arco is None and corda is None:
        return

    def tela_xy(p):
        return rect.x + p[0] * rect.w, rect.y + p[1] * rect.h

    cor = cor_forca(forca) if puxando else (225, 225, 210)
    espessura = 2 + int(4 * forca) if puxando else 2
    pontas = None
    if arco is not None:
        palma = tela_xy(arco.palma)
        altura = max(40.0, arco.tamanho * rect.h * 2.6)
        # A madeira do arco se curva para longe da mão da corda (para o alvo).
        sentido = 1.0
        if corda is not None:
            sentido = 1.0 if arco.palma[0] >= corda.palma[0] else -1.0
        curva = altura * (0.18 + 0.1 * forca)
        pontos = []
        for k in range(13):
            v = -1 + 2 * k / 12
            pontos.append((palma[0] + sentido * curva * (1 - v * v) - sentido * curva * 0.5, palma[1] + v * altura / 2))
        pygame.draw.lines(tela, (60, 36, 18), False, pontos, 7)
        pygame.draw.lines(tela, (170, 116, 60), False, pontos, 4)
        pontas = (pontos[0], pontos[-1])
        pygame.draw.circle(tela, (240, 230, 200), (int(palma[0]), int(palma[1])), 6, 2)
    if corda is not None:
        mao = tela_xy(corda.palma)
        if len(rastro) >= 2:
            pts = [tela_xy(p) for p in rastro]
            for i in range(1, len(pts)):
                alfa = i / len(pts)
                c = tuple(int(m3.lerp(60, v, alfa)) for v in cor)
                pygame.draw.line(tela, c, pts[i - 1], pts[i], 1 + int(3 * alfa))
        if pontas is not None:
            for ponta in pontas:
                pygame.draw.line(tela, cor, ponta, mao, espessura)
        raio = 9 + int(5 * forca) if puxando else 9
        if fechada:
            pygame.draw.circle(tela, cor, (int(mao[0]), int(mao[1])), raio)
        pygame.draw.circle(tela, (20, 14, 8), (int(mao[0]), int(mao[1])), raio, 2)
    if puxando:
        pygame.draw.rect(tela, cor, rect, 2 + int(3 * forca))
        if fonte is not None:
            rotulo = fonte.render(f"força {forca * 100:.0f}%", True, cor)
            fundo = pygame.Surface((rotulo.get_width() + 10, rotulo.get_height() + 4), pygame.SRCALPHA)
            fundo.fill((20, 14, 8, 170))
            tela.blit(fundo, (rect.x + 4, rect.y + 4))
            tela.blit(rotulo, (rect.x + 9, rect.y + 6))


COR_ARCO = (120, 196, 255)  # mão do arco (esqueleto azul-claro)
COR_OUTRA = (170, 170, 160)


def desenhar_maos(tela, rect, maos, par, forca=0.0, puxando=False, fonte=None):
    """Esqueleto das mãos sobre a prévia, colorido pelo papel: arco azul-claro, corda na cor da
    força, outras em cinza. Etiquetas E/D no pulso, com o número de dedos quando houver."""
    from gestos import CONEXOES
    arco, corda = par

    def xy(p):
        return int(rect.x + p[0] * rect.w), int(rect.y + p[1] * rect.h)

    for mao in maos:
        if mao is arco:
            cor, etiqueta = COR_ARCO, "E"
        elif mao is corda:
            cor, etiqueta = (cor_forca(forca) if puxando else (235, 235, 220)), "D"
        else:
            cor, etiqueta = COR_OUTRA, ""
        pontos = [xy(p) for p in mao.pontos]
        for a, b in CONEXOES:
            pygame.draw.line(tela, (15, 10, 6), pontos[a], pontos[b], 4)
            pygame.draw.line(tela, cor, pontos[a], pontos[b], 2)
        for q in pontos:
            pygame.draw.circle(tela, cor, q, 2)
        if fonte is not None:
            dedos = mao.dedos
            texto = (etiqueta + (f" {dedos}" if dedos else "")).strip()
            if texto:
                sup = fonte.render(texto, True, (20, 14, 8))
                caixa = sup.get_rect(center=(pontos[0][0], pontos[0][1] + 14)).inflate(10, 2)
                pygame.draw.rect(tela, cor, caixa, border_radius=6)
                tela.blit(sup, sup.get_rect(center=caixa.center))


def status_camera(rastreador, maos, par, forca, puxando, fechada):
    """(linha de estado, aviso ou None) para a faixa abaixo de cada prévia."""
    arco, corda = par
    partes = []
    if arco is not None:
        partes.append(f"E: {arco.dedos} dedos" if arco.dedos else "E: mira")
    if corda is not None:
        if corda.dedos:
            partes.append(f"D: {corda.dedos} dedos")
        elif puxando:
            partes.append(f"D: {forca * 100:.0f}%")
        else:
            partes.append("D: punho" if fechada else "D: aberta")
    aviso = None
    if rastreador is not None and getattr(rastreador, "realce", False):
        aviso = "pouca luz (realce ligado)"
    if any(min(m.palma) < 0.06 or max(m.palma) > 0.94 for m in maos):
        aviso = "mão saindo do quadro"
    elif len(maos) == 1:
        aviso = aviso or "mostre as duas mãos"
    elif not maos:
        aviso = "nenhuma mão"
    return "  ·  ".join(partes), aviso


def _fonte(tamanho, negrito=False):
    return pygame.font.SysFont("georgia,palatino linotype,constantia,serif", tamanho, bold=negrito)


class Popup:
    def __init__(self, texto, cor, posicao):
        self.texto, self.cor, self.posicao = texto, cor, posicao
        self.idade = 0.0


class Hud:
    DURACAO_POPUP = 1.4

    def __init__(self, largura, altura):
        self.largura, self.altura = largura, altura
        self.f_titulo = _fonte(76, True)
        self.f_grande = _fonte(40, True)
        self.f_media = _fonte(26, True)
        self.f_pequena = _fonte(19)
        self.popups = []
        self._preview_surface = None

    # ---------------------------------------------------------------- utilitários

    def texto(self, tela, texto, fonte, cor, pos, ancora="topleft", sombra=True):
        sup = fonte.render(texto, True, cor)
        rect = sup.get_rect(**{ancora: pos})
        if sombra:
            tela.blit(fonte.render(texto, True, (20, 14, 8)), rect.move(2, 2))
        tela.blit(sup, rect)
        return rect

    def painel(self, tela, rect, alfa=170):
        sup = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(sup, (34, 24, 16, alfa), sup.get_rect(), border_radius=10)
        pygame.draw.rect(sup, (*OURO, 200), sup.get_rect(), 2, border_radius=10)
        tela.blit(sup, rect)

    def adicionar_popup(self, texto, cor, posicao):
        self.popups.append(Popup(texto, cor, posicao))

    def atualizar(self, dt):
        for p in self.popups:
            p.idade += dt
        self.popups = [p for p in self.popups if p.idade < self.DURACAO_POPUP]

    # ---------------------------------------------------------------- jogo

    def mira(self, tela, foco, puxando, forca, gesto):
        cx, cy = self.largura // 2, self.altura // 2
        cor = OURO if foco else (250, 250, 240)
        raio = int(m3.lerp(22, 9, forca)) if puxando else 18
        pygame.draw.circle(tela, (20, 14, 8), (cx + 1, cy + 1), raio, 2)
        pygame.draw.circle(tela, cor, (cx, cy), raio, 2)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            a = (cx + dx * (raio + 4), cy + dy * (raio + 4))
            b = (cx + dx * (raio + 12), cy + dy * (raio + 12))
            pygame.draw.line(tela, cor, a, b, 2)
        pygame.draw.circle(tela, cor, (cx, cy), 2)
        if foco:
            self.texto(tela, foco.nome, self.f_pequena, OURO, (cx, cy + raio + 18), "midtop")
        if gesto:
            self.texto(tela, "gesto", self.f_pequena, VERDE, (cx + raio + 16, cy - raio - 10), "midleft")

    def barra_forca(self, tela, forca, puxando):
        if not puxando:
            return
        largura, altura = 300, 18
        rect = pygame.Rect(0, 0, largura, altura)
        rect.midbottom = (self.largura // 2, self.altura - 80)
        self.painel(tela, rect.inflate(10, 10), 150)
        pygame.draw.rect(tela, cor_forca(forca), (rect.x, rect.y, int(largura * forca), altura), border_radius=5)
        self.texto(tela, "FORÇA", self.f_pequena, PERGAMINHO, (rect.centerx, rect.y - 8), "midbottom")

    def placar(self, tela, pontos, recorde, flechas, total_flechas, posto, vento, tempo_restante=None, modo="",
               dificuldade=None, tendencia=0):
        rect = pygame.Rect(16, 16, 270, 112)
        self.painel(tela, rect)
        self.texto(tela, f"{pontos} pts", self.f_grande, OURO, (rect.x + 16, rect.y + 8))
        self.texto(tela, f"Recorde: {recorde}", self.f_pequena, PERGAMINHO, (rect.x + 18, rect.y + 58))
        self.texto(tela, f"Posto {posto[0]}: {posto[1]} m  (x{posto[2]:g})", self.f_pequena, PERGAMINHO, (rect.x + 18, rect.y + 82))

        rect2 = pygame.Rect(self.largura - 16 - 270, 16, 270, 76)
        self.painel(tela, rect2)
        self.texto(tela, modo or "Flechas", self.f_pequena, PERGAMINHO, (rect2.x + 16, rect2.y + 8))
        if tempo_restante is not None:
            cor = VERMELHO if tempo_restante < 10 else OURO
            self.texto(tela, f"{max(0, tempo_restante):04.1f} s", self.f_grande, cor, (rect2.right - 16, rect2.y + 26), "topright")
            return self._vento(tela, vento, dificuldade, tendencia)
        if flechas is None:
            self.texto(tela, "flechas sem limite", self.f_pequena, OURO, (rect2.x + 16, rect2.y + 40))
            return self._vento(tela, vento, dificuldade, tendencia)
        for i in range(total_flechas):
            x = rect2.x + 18 + i * 16
            cor = (196, 150, 96) if i < flechas else (80, 64, 50)
            pygame.draw.line(tela, cor, (x, rect2.bottom - 14), (x, rect2.y + 36), 3)
            pygame.draw.polygon(tela, (160, 160, 168) if i < flechas else (70, 64, 60),
                                [(x - 4, rect2.y + 38), (x + 4, rect2.y + 38), (x, rect2.y + 30)])
        self._vento(tela, vento, dificuldade, tendencia)

    def _vento(self, tela, vento, dificuldade=None, tendencia=0):
        rect3 = pygame.Rect(0, 0, 210, 54)
        rect3.midtop = (self.largura // 2, 16)
        self.painel(tela, rect3)
        self.texto(tela, "Vento", self.f_pequena, PERGAMINHO, (rect3.x + 14, rect3.centery), "midleft")
        cx, cy = rect3.x + 130, rect3.centery
        comprimento = 18 + 16 * abs(vento)
        sinal = 1 if vento >= 0 else -1
        a, b = (cx - sinal * comprimento / 2, cy), (cx + sinal * comprimento / 2, cy)
        pygame.draw.line(tela, PERGAMINHO, a, b, 4)
        pygame.draw.polygon(tela, PERGAMINHO, [(b[0] + sinal * 8, cy), (b[0] - sinal * 2, cy - 8), (b[0] - sinal * 2, cy + 8)])
        self.texto(tela, f"{abs(vento):.1f}", self.f_pequena, OURO, (rect3.right - 12, rect3.centery), "midright")
        if dificuldade is not None:
            seta = {1: "  (subiu)", -1: "  (desceu)"}.get(tendencia, "")
            cor = VERMELHO if tendencia > 0 else (VERDE if tendencia < 0 else PERGAMINHO)
            texto = f"Dificuldade {dificuldade:.1f}x".replace(".", ",") + seta
            self.texto(tela, texto, self.f_pequena, cor, (rect3.centerx, rect3.bottom + 6), "midtop")

    def indicador_posto(self, tela, dedos, progresso, posto_atual):
        """Anel de progresso enquanto a mão esquerda mostra 1, 2 ou 3 dedos."""
        if not dedos or progresso <= 0:
            return
        cx, cy = self.largura // 2 - 120, self.altura // 2 - 60
        mesmo = dedos == posto_atual
        cor = PERGAMINHO if mesmo else OURO
        pygame.draw.circle(tela, (34, 24, 16), (cx, cy), 30)
        pygame.draw.arc(tela, cor, pygame.Rect(cx - 30, cy - 30, 60, 60), math.pi / 2, math.pi / 2 + 2 * math.pi * progresso, 5)
        self.texto(tela, str(dedos), self.f_grande, cor, (cx, cy), "center")
        texto = "já está neste posto" if mesmo else f"indo para o posto {dedos}..."
        self.texto(tela, texto, self.f_pequena, cor, (cx, cy + 36), "midtop")

    def faixas_cinema(self, tela, quanto, texto):
        """Faixas pretas de cinema (câmera da flecha). `quanto` em [0, 1] anima a entrada."""
        h = int(70 * m3.ease_out(m3.limitar(quanto)))
        if h <= 0:
            return
        pygame.draw.rect(tela, (0, 0, 0), (0, 0, self.largura, h))
        pygame.draw.rect(tela, (0, 0, 0), (0, self.altura - h, self.largura, h))
        self.texto(tela, texto, self.f_media, OURO, (self.largura // 2, self.altura - h // 2), "center")

    def painel_tutorial(self, tela, indice, total, titulo, texto, t):
        """Pergaminho no topo com o passo atual do tutorial."""
        rect = pygame.Rect(0, 0, 760, 92)
        rect.midtop = (self.largura // 2, 86)
        pygame.draw.rect(tela, (20, 14, 8), rect.move(5, 5), border_radius=8)
        pygame.draw.rect(tela, (236, 220, 178), rect, border_radius=8)
        pygame.draw.rect(tela, (120, 88, 58), rect, 2, border_radius=8)
        self.texto(tela, f"Tutorial {indice + 1}/{total} · {titulo}", self.f_media, (66, 44, 28),
                   (rect.x + 18, rect.y + 10), sombra=False)
        self.texto(tela, texto, self.f_pequena, (66, 44, 28), (rect.x + 18, rect.y + 52), sombra=False)
        for k in range(total):
            centro = (rect.right - 24 - (total - 1 - k) * 20, rect.y + 24)
            if k < indice:
                pygame.draw.circle(tela, (90, 150, 70), centro, 7)
            elif k == indice:
                raio = 7 + int(2 * (0.5 + 0.5 * math.sin(t * 5)))
                pygame.draw.circle(tela, (176, 40, 34), centro, raio, 2)
            else:
                pygame.draw.circle(tela, (150, 130, 100), centro, 7, 2)

    def ajuda(self, tela, gesto_disponivel):
        linhas = ["A/D andar  1/2/3 postos  P pausa  R reinicia  M menu  Esc sair"]
        if gesto_disponivel:
            linhas.insert(0, "Esquerda mira, direita fechada puxa, abra para soltar")
            linhas.insert(1, "Qualquer mão: 1, 2 ou 3 dedos = posto  ·  G painel das mãos")
            linhas.insert(2, "L canhoto  K recalibrar  V troca câmeras  C câmeras  T tutorial")
        else:
            linhas.insert(0, "Mouse: mire e segure o botão para puxar, solte para atirar")
        for i, linha in enumerate(linhas):
            self.texto(tela, linha, self.f_pequena, PERGAMINHO,
                       (self.largura - 16, self.altura - 26 - (len(linhas) - 1 - i) * 22), "bottomright")

    def desenhar_popups(self, tela):
        for p in self.popups:
            u = p.idade / self.DURACAO_POPUP
            x, y = p.posicao
            y -= 60 * m3.ease_out(u)
            alfa = int(255 * (1 - u ** 2))
            for cor, deslocamento in (((20, 14, 8), 2), (p.cor, 0)):
                sup = self.f_grande.render(p.texto, True, cor)
                sup.set_alpha(alfa)
                tela.blit(sup, sup.get_rect(center=(x + deslocamento, y + deslocamento)))

    def previews(self, tela, rastreadores, entrada, forca=0.0, puxando=False):
        """Câmeras no canto inferior esquerdo: imagem, esqueleto por papel, puxada na cor da força
        e uma faixa de status. Crescem durante a puxada para dar para ver o movimento."""
        self._escala_prev = m3.lerp(getattr(self, "_escala_prev", 1.0), 1.3 if puxando else 1.0, 0.15)
        largura = int(224 * self._escala_prev)
        altura = largura * 3 // 4
        x = 16
        y = self.altura - 16 - altura - 46
        for rastreador, papel in rastreadores:
            chave = papel.lower()
            rect = pygame.Rect(x, y, largura, altura + 46)
            self.painel(tela, rect.inflate(8, 8), 200)
            area = pygame.Rect(x, y, largura, altura)
            quadro = rastreador.preview() if rastreador else None
            maos = entrada.maos_camera.get(chave, [])
            par = entrada.pares[chave]
            if quadro is not None:
                sup = pygame.image.frombuffer(quadro.tobytes(), (quadro.shape[1], quadro.shape[0]), "RGB")
                tela.blit(pygame.transform.smoothscale(sup, area.size), area)
                desenhar_puxada(tela, area, par, entrada.rastros[chave], forca, puxando, entrada.mao_fechada, self.f_pequena)
                desenhar_maos(tela, area, maos, par, forca, puxando, self.f_pequena)
            else:
                msg = "Sem câmera" if rastreador is None else (rastreador.erro or "Iniciando...")
                self.texto(tela, msg, self.f_pequena, PERGAMINHO, area.center, "center")
            usada = (papel == "Frontal" and entrada.fonte_forca != "lateral") or (papel == "Lateral" and entrada.fonte_forca == "lateral")
            cabecalho = papel + (" (força)" if usada and entrada.fonte_forca else "")
            fps = f"{rastreador.fps:.0f} fps" if rastreador is not None and getattr(rastreador, "fps", 0) else ""
            self.texto(tela, cabecalho, self.f_pequena, OURO, (x + 6, area.bottom + 2))
            self.texto(tela, fps, self.f_pequena, (190, 175, 150), (rect.right - 6, area.bottom + 2), "topright", sombra=False)
            estado, aviso = status_camera(rastreador, maos, par, forca, puxando, entrada.mao_fechada)
            if aviso:
                self.texto(tela, aviso, self.f_pequena, VERMELHO, (x + 6, area.bottom + 23))
            else:
                self.texto(tela, estado, self.f_pequena, VERDE, (x + 6, area.bottom + 23))
            x += largura + 16
        if entrada.canhoto:
            self.texto(tela, "[canhoto]", self.f_pequena, OURO, (16, y - 14), "bottomleft")

    def painel_arco(self, tela, entrada, forca, puxando):
        """Painel "Seu arco" (tecla G): ícones grandes das duas mãos e a força."""
        rect = pygame.Rect(self.largura - 16 - 300, self.altura - 108 - 190, 300, 182)
        self.painel(tela, rect, 200)
        self.texto(tela, "Seu arco", self.f_pequena, OURO, (rect.x + 12, rect.y + 6))
        arco, corda = entrada.pares["frontal"]
        if entrada.pares["lateral"][1] is not None and corda is None:
            corda = entrada.pares["lateral"][1]
        for i, (mao, nome, cor) in enumerate(((arco, "Esquerda", COR_ARCO),
                                             (corda, "Direita", cor_forca(forca) if puxando else (235, 235, 220)))):
            caixa = pygame.Rect(rect.x + 14 + i * 146, rect.y + 32, 126, 110)
            pygame.draw.rect(tela, (24, 16, 10), caixa, border_radius=8)
            if mao is not None:
                xs = [p[0] for p in mao.pontos]
                ys = [p[1] for p in mao.pontos]
                lado = max(max(xs) - min(xs), max(ys) - min(ys), 1e-3) * 1.25
                cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
                normal = [((x - cx) / lado + 0.5, (y - cy) / lado + 0.5) for x, y in zip(xs, ys)]
                from gestos import Mao
                icone = Mao(normal, mao.lado)
                desenhar_maos(tela, caixa.inflate(-10, -10), [icone], (icone, None) if i == 0 else (None, icone), forca, puxando)
                if i == 0:
                    estado = f"{mao.dedos} dedos" if mao.dedos else "mirando"
                else:
                    estado = f"{mao.dedos} dedos" if mao.dedos else (f"puxando {forca * 100:.0f}%" if puxando else
                                                                     ("punho" if entrada.mao_fechada else "aberta"))
            else:
                estado = "não vista"
                self.texto(tela, "?", self.f_grande, (120, 110, 100), caixa.center, "center", sombra=False)
            pygame.draw.rect(tela, cor, caixa, 2, border_radius=8)
            self.texto(tela, nome, self.f_pequena, cor, (caixa.x + 6, caixa.y + 2), sombra=False)
            self.texto(tela, estado, self.f_pequena, cor, (caixa.centerx, caixa.bottom + 4), "midtop")

    # ---------------------------------------------------------------- telas

    def escurecer(self, tela, alfa=120):
        sombra = pygame.Surface((self.largura, self.altura), pygame.SRCALPHA)
        sombra.fill((10, 8, 4, alfa))
        tela.blit(sombra, (0, 0))

    def tela_pausa(self, tela):
        self.escurecer(tela, 140)
        self.texto(tela, "Pausado", self.f_titulo, OURO, (self.largura // 2, self.altura // 2 - 30), "center")
        self.texto(tela, "P: continuar  |  R: reiniciar  |  M: menu  |  Esc: sair", self.f_media, PERGAMINHO,
                   (self.largura // 2, self.altura // 2 + 40), "center")

    def tela_resultado(self, tela, pontos, recorde, novo_recorde, acertos, historico, modo="", ranking=(), nome=""):
        self.escurecer(tela, 150)
        cx = self.largura // 2
        self.texto(tela, "Fim do torneio" if not modo else f"Fim · {modo}", self.f_titulo, OURO, (cx, 110), "center")
        self.texto(tela, f"{nome}: {pontos} pontos" if nome else f"{pontos} pontos", self.f_grande, PERGAMINHO, (cx, 190), "center")
        if novo_recorde:
            self.texto(tela, "Novo recorde da clareira!", self.f_media, VERDE, (cx, 236), "center")
        else:
            self.texto(tela, f"Recorde: {recorde}", self.f_media, PERGAMINHO, (cx, 236), "center")
        rect = pygame.Rect(0, 0, 720, 200)
        rect.center = (cx, 380)
        self.painel(tela, rect)
        self.texto(tela, f"Acertos no alvo: {acertos} de {len(historico)}", self.f_media, PERGAMINHO, (cx, rect.y + 28), "center")
        largura = (rect.w - 40) / max(1, len(historico))
        for i, (posto, valor) in enumerate(historico):
            x = rect.x + 20 + i * largura
            h = min(8 + 5.5 * valor, 120) if valor else 6
            cor = OURO if valor >= 10 else (VERDE if valor > 0 else VERMELHO)
            pygame.draw.rect(tela, cor, (x + 2, rect.bottom - 30 - h, max(2, largura - 4), h), border_radius=3)
            if largura >= 26:
                self.texto(tela, f"{valor:g}", self.f_pequena, PERGAMINHO, (x + largura / 2, rect.bottom - 34 - h), "midbottom", sombra=False)
                self.texto(tela, str(posto), self.f_pequena, (180, 170, 150), (x + largura / 2, rect.bottom - 6), "midbottom", sombra=False)
        if ranking:
            caixa = pygame.Rect(0, 0, 720, 96)
            caixa.midtop = (cx, rect.bottom + 18)
            self.painel(tela, caixa)
            self.texto(tela, "Melhores da clareira", self.f_pequena, OURO, (caixa.x + 16, caixa.y + 8))
            for i, item in enumerate(ranking[:5]):
                destaque = item.get("nome") == nome and item.get("pontos") == pontos
                cor = VERDE if destaque else PERGAMINHO
                x = caixa.x + 16 + i * 140
                self.texto(tela, f"{i + 1}. {item.get('nome', '?')[:10]}", self.f_pequena, cor, (x, caixa.y + 38))
                self.texto(tela, f"{item.get('pontos', 0)} pts", self.f_pequena, cor, (x, caixa.y + 62))
        self.texto(tela, "R ou mão fechada: jogar de novo  |  M: menu  |  Esc: sair", self.f_media, PERGAMINHO,
                   (cx, self.altura - 40), "center")
