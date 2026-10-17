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

    def arco(self, tela, forca, carregado, t):
        """Arco em primeira pessoa no canto inferior, com a corda recuando conforme a força."""
        base_x, topo, fundo = self.largura * 0.5 - 330, self.altura * 0.52, self.altura + 90
        tremor = (math.sin(t * 37) * 2.5 * max(0, forca - 0.85) / 0.15) if forca > 0.85 else 0
        meio_y = (topo + fundo) / 2
        curva = 70 + 22 * forca
        pontos = []
        for i in range(21):
            u = i / 20
            y = m3.lerp(topo, fundo, u)
            x = base_x - curva * math.sin(math.pi * u) + tremor
            pontos.append((x, y))
        pygame.draw.lines(tela, (40, 26, 14), False, [(x + 3, y + 3) for x, y in pontos], 14)
        pygame.draw.lines(tela, MADEIRA, False, pontos, 12)
        pygame.draw.lines(tela, MADEIRA_CLARA, False, [(x - 3, y) for x, y in pontos], 3)
        pegada = pygame.Rect(0, 0, 22, 70)
        pegada.center = (base_x - curva + tremor, meio_y)
        pygame.draw.rect(tela, (70, 40, 26), pegada, border_radius=6)
        recuo = 150 * forca
        nock = (base_x + 60 + recuo + tremor, meio_y + 0.4 * recuo)
        pygame.draw.line(tela, (230, 224, 200), pontos[0], nock, 2)
        pygame.draw.line(tela, (230, 224, 200), pontos[-1], nock, 2)
        if carregado:
            ponta = (self.largura / 2 - 30, self.altura / 2 + 60)
            pygame.draw.line(tela, (40, 26, 14), (nock[0] + 2, nock[1] + 2), (ponta[0] + 2, ponta[1] + 2), 7)
            pygame.draw.line(tela, (196, 150, 96), nock, ponta, 5)
            d = np.subtract(ponta, nock)
            d = d / np.linalg.norm(d)
            n = np.array((-d[1], d[0]))
            p = np.array(ponta)
            pygame.draw.polygon(tela, (160, 160, 168), [p + d * 22, p + n * 9, p - n * 9])
            pena = np.array(nock) + d * 26
            pygame.draw.polygon(tela, (200, 52, 44), [pena, pena - d * 30 + n * 12, np.array(nock) + n * 8])
            pygame.draw.polygon(tela, (236, 230, 214), [pena, pena - d * 30 - n * 12, np.array(nock) - n * 8])

    def barra_forca(self, tela, forca, puxando):
        if not puxando:
            return
        largura, altura = 300, 18
        rect = pygame.Rect(0, 0, largura, altura)
        rect.midbottom = (self.largura // 2, self.altura - 80)
        self.painel(tela, rect.inflate(10, 10), 150)
        cor = tuple(int(m3.lerp(a, b, forca)) for a, b in zip((230, 200, 90), (220, 70, 50)))
        pygame.draw.rect(tela, cor, (rect.x, rect.y, int(largura * forca), altura), border_radius=5)
        self.texto(tela, "FORÇA", self.f_pequena, PERGAMINHO, (rect.centerx, rect.y - 8), "midbottom")

    def placar(self, tela, pontos, recorde, flechas, total_flechas, posto, vento):
        rect = pygame.Rect(16, 16, 270, 112)
        self.painel(tela, rect)
        self.texto(tela, f"{pontos} pts", self.f_grande, OURO, (rect.x + 16, rect.y + 8))
        self.texto(tela, f"Recorde: {recorde}", self.f_pequena, PERGAMINHO, (rect.x + 18, rect.y + 58))
        self.texto(tela, f"Posto {posto[0]}: {posto[1]} m  (x{posto[2]:g})", self.f_pequena, PERGAMINHO, (rect.x + 18, rect.y + 82))

        rect2 = pygame.Rect(self.largura - 16 - 270, 16, 270, 76)
        self.painel(tela, rect2)
        self.texto(tela, "Flechas", self.f_pequena, PERGAMINHO, (rect2.x + 16, rect2.y + 8))
        for i in range(total_flechas):
            x = rect2.x + 18 + i * 16
            cor = (196, 150, 96) if i < flechas else (80, 64, 50)
            pygame.draw.line(tela, cor, (x, rect2.bottom - 14), (x, rect2.y + 36), 3)
            pygame.draw.polygon(tela, (160, 160, 168) if i < flechas else (70, 64, 60),
                                [(x - 4, rect2.y + 38), (x + 4, rect2.y + 38), (x, rect2.y + 30)])

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

    def ajuda(self, tela, gesto_disponivel):
        linhas = ["A/D andar   1/2/3 teleporte   P pausa   R reinicia   C câmera   Esc sair"]
        if gesto_disponivel:
            linhas.insert(0, "Arco: estique uma mão, pince com a outra, afaste e solte  |  L canhoto  K recalibrar")
        else:
            linhas.insert(0, "Mouse: mire e segure o botão para puxar, solte para atirar (ou Espaço)")
        for i, linha in enumerate(linhas):
            self.texto(tela, linha, self.f_pequena, PERGAMINHO, (self.largura // 2, self.altura - 10 - (len(linhas) - 1 - i) * 22), "midbottom")

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

    def preview(self, tela, quadro, rastreador, entrada):
        """Imagem da webcam com landmarks no canto inferior esquerdo."""
        rect = pygame.Rect(16, self.altura - 16 - 192 - 30, 256, 222)
        self.painel(tela, rect.inflate(8, 8), 190)
        if quadro is not None:
            sup = pygame.image.frombuffer(quadro.tobytes(), (quadro.shape[1], quadro.shape[0]), "RGB")
            tela.blit(sup, (rect.x, rect.y))
        else:
            self.texto(tela, rastreador.erro or "Iniciando câmera...", self.f_pequena, PERGAMINHO,
                       (rect.centerx, rect.y + 96), "center")
        maos = entrada.maos_visiveis
        if maos >= 2:
            estado, cor = ("Puxando" if entrada.pinca else "Arco pronto"), VERDE
        elif maos == 1:
            estado, cor = "Mostre as duas mãos", OURO
        else:
            estado, cor = "Nenhuma mão", VERMELHO
        if entrada.canhoto:
            estado += " (canhoto)"
        self.texto(tela, estado, self.f_pequena, cor, (rect.x + 6, rect.bottom - 4), "bottomleft")

    # ---------------------------------------------------------------- telas

    def escurecer(self, tela, alfa=120):
        sombra = pygame.Surface((self.largura, self.altura), pygame.SRCALPHA)
        sombra.fill((10, 8, 4, alfa))
        tela.blit(sombra, (0, 0))

    def tela_menu(self, tela, recorde, camera_ok, t):
        self.escurecer(tela, 90)
        cx = self.largura // 2
        self.texto(tela, "Arrow the Target", self.f_titulo, OURO, (cx, 150), "center")
        self.texto(tela, "Torneio de arqueiros da clareira", self.f_media, PERGAMINHO, (cx, 215), "center")
        rect = pygame.Rect(0, 0, 640, 230)
        rect.center = (cx, 420)
        self.painel(tela, rect)
        linhas = [
            "15 flechas, 3 postos de tiro (15, 25 e 40 m).",
            "Quanto mais longe o posto, maior o multiplicador.",
            "Fique de olho no vento e nos alvos que se movem.",
        ]
        for i, l in enumerate(linhas):
            self.texto(tela, l, self.f_pequena, PERGAMINHO, (cx, rect.y + 34 + i * 30), "center")
        pulso = 0.5 + 0.5 * math.sin(t * 3)
        cor = tuple(int(m3.lerp(a, b, pulso)) for a, b in zip(PERGAMINHO, OURO))
        acao = "Faça uma pinça, clique ou tecle Enter para começar"
        self.texto(tela, acao, self.f_media, cor, (cx, rect.y + 150), "center")
        cam = "Câmera: pronta para gestos" if camera_ok else "Câmera indisponível: jogando com mouse e teclado"
        self.texto(tela, cam, self.f_pequena, VERDE if camera_ok else OURO, (cx, rect.y + 196), "center")
        self.texto(tela, f"Recorde: {recorde}", self.f_media, OURO, (cx, rect.bottom + 40), "center")

    def tela_calibracao(self, tela, progresso, maos):
        self.escurecer(tela, 110)
        cx, cy = self.largura // 2, self.altura // 2 - 40
        self.texto(tela, "Calibrando o arco", self.f_grande, OURO, (cx, cy - 120), "center")
        instrucoes = [
            "Estique a mão do arco para a frente, na altura do peito.",
            "Com a outra mão, faça a pinça (polegar + indicador) encostada nela.",
            "Fique parado até a barra encher.  Enter pula a calibração.",
        ]
        for i, l in enumerate(instrucoes):
            self.texto(tela, l, self.f_pequena, PERGAMINHO, (cx, cy - 60 + i * 28), "center")
        rect = pygame.Rect(0, 0, 420, 26)
        rect.center = (cx, cy + 60)
        self.painel(tela, rect.inflate(10, 10))
        pygame.draw.rect(tela, VERDE, (rect.x, rect.y, int(rect.w * progresso), rect.h), border_radius=6)
        aviso = "Duas mãos detectadas" if maos >= 2 else f"Mãos detectadas: {maos}"
        self.texto(tela, aviso, self.f_pequena, VERDE if maos >= 2 else OURO, (cx, cy + 100), "center")

    def tela_pausa(self, tela):
        self.escurecer(tela, 140)
        self.texto(tela, "Pausado", self.f_titulo, OURO, (self.largura // 2, self.altura // 2 - 30), "center")
        self.texto(tela, "P para continuar  |  R para reiniciar  |  Esc para sair", self.f_media, PERGAMINHO,
                   (self.largura // 2, self.altura // 2 + 40), "center")

    def tela_resultado(self, tela, pontos, recorde, novo_recorde, acertos, historico):
        self.escurecer(tela, 150)
        cx = self.largura // 2
        self.texto(tela, "Fim do torneio", self.f_titulo, OURO, (cx, 130), "center")
        self.texto(tela, f"{pontos} pontos", self.f_grande, PERGAMINHO, (cx, 215), "center")
        if novo_recorde:
            self.texto(tela, "Novo recorde da clareira!", self.f_media, VERDE, (cx, 262), "center")
        else:
            self.texto(tela, f"Recorde: {recorde}", self.f_media, PERGAMINHO, (cx, 262), "center")
        rect = pygame.Rect(0, 0, 720, 200)
        rect.center = (cx, 420)
        self.painel(tela, rect)
        self.texto(tela, f"Acertos no alvo: {acertos} de {len(historico)}", self.f_media, PERGAMINHO, (cx, rect.y + 28), "center")
        largura = (rect.w - 40) / max(1, len(historico))
        for i, (posto, valor) in enumerate(historico):
            x = rect.x + 20 + i * largura
            h = 8 + 5.5 * valor if valor else 6  # valor máximo: 10 pontos x2 = 20
            cor = OURO if valor >= 10 else (VERDE if valor > 0 else VERMELHO)
            pygame.draw.rect(tela, cor, (x + 4, rect.bottom - 30 - h, largura - 8, h), border_radius=3)
            self.texto(tela, f"{valor:g}", self.f_pequena, PERGAMINHO, (x + largura / 2, rect.bottom - 34 - h), "midbottom", sombra=False)
            self.texto(tela, str(posto), self.f_pequena, (180, 170, 150), (x + largura / 2, rect.bottom - 6), "midbottom", sombra=False)
        self.texto(tela, "R ou pinça para jogar de novo  |  Esc para sair", self.f_media, PERGAMINHO, (cx, rect.bottom + 50), "center")
