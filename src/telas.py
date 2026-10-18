"""Telas de escolha de câmeras e de calibração guiada, com ilustração em pergaminho."""
import math

import pygame

import mat3d as m3
from entrada import ETAPAS_CALIBRACAO
from hud import OURO, PERGAMINHO, VERDE, VERMELHO, desenhar_maos, desenhar_puxada, status_camera

TINTA = (66, 44, 28)
TINTA_CLARA = (120, 88, 58)
PAPEL = (236, 220, 178)
PAPEL_SOMBRA = (204, 182, 134)
DESTAQUE = (176, 40, 34)


def _preview_superficie(rastreador, tamanho):
    quadro = rastreador.preview() if rastreador else None
    if quadro is None:
        return None
    sup = pygame.image.frombuffer(quadro.tobytes(), (quadro.shape[1], quadro.shape[0]), "RGB")
    return pygame.transform.smoothscale(sup, tamanho)


def _marca(tela, centro, ok):
    """Círculo com ✓ (verde) ou ✗ (vermelho), desenhado à mão para não depender da fonte."""
    x, y = centro
    pygame.draw.circle(tela, VERDE if ok else VERMELHO, centro, 10)
    if ok:
        pygame.draw.lines(tela, (20, 40, 20), False, [(x - 5, y), (x - 1, y + 4), (x + 5, y - 4)], 3)
    else:
        pygame.draw.line(tela, (60, 16, 12), (x - 4, y - 4), (x + 4, y + 4), 3)
        pygame.draw.line(tela, (60, 16, 12), (x + 4, y - 4), (x - 4, y + 4), 3)


def _quebrar(fonte, texto, largura):
    """Quebra o texto em linhas que cabem na largura (em pixels)."""
    linhas, atual = [], ""
    for palavra in texto.split():
        tentativa = f"{atual} {palavra}".strip()
        if fonte.size(tentativa)[0] <= largura or not atual:
            atual = tentativa
        else:
            linhas.append(atual)
            atual = palavra
    return linhas + ([atual] if atual else [])


class Botao:
    def __init__(self, rect, texto, acao, ativo=False):
        self.rect, self.texto, self.acao, self.ativo = rect, texto, acao, ativo

    def desenhar(self, tela, hud, mouse):
        sobre = self.rect.collidepoint(mouse)
        fundo = (150, 106, 50) if self.ativo else ((96, 66, 40) if sobre else (64, 44, 28))
        pygame.draw.rect(tela, fundo, self.rect, border_radius=8)
        pygame.draw.rect(tela, OURO if (self.ativo or sobre) else (150, 120, 80), self.rect, 2, border_radius=8)
        hud.texto(tela, self.texto, hud.f_pequena, PERGAMINHO, self.rect.center, "center")


# ---------------------------------------------------------------- ilustração

def pergaminho(tela, rect):
    """Folha de pergaminho com as pontas enroladas."""
    sombra = rect.move(6, 6)
    pygame.draw.rect(tela, (20, 14, 8), sombra, border_radius=6)
    pygame.draw.rect(tela, PAPEL, rect, border_radius=6)
    for i in range(0, rect.h, 6):  # textura leve de fibras
        cor = PAPEL_SOMBRA if (i // 6) % 7 == 0 else (230, 213, 170)
        pygame.draw.line(tela, cor, (rect.x + 8, rect.y + i), (rect.right - 8, rect.y + i), 1)
    for y in (rect.y, rect.bottom):
        rolo = pygame.Rect(rect.x - 10, y - 12, rect.w + 20, 24)
        pygame.draw.rect(tela, PAPEL_SOMBRA, rolo, border_radius=12)
        pygame.draw.rect(tela, TINTA_CLARA, rolo, 2, border_radius=12)
    pygame.draw.rect(tela, TINTA_CLARA, rect, 2, border_radius=6)


def _mao(tela, pos, fechada, cor=TINTA):
    x, y = int(pos[0]), int(pos[1])
    if fechada:
        pygame.draw.circle(tela, cor, (x, y), 9)
    else:
        pygame.draw.circle(tela, cor, (x, y), 7, 3)
        for ang in (-0.9, -0.3, 0.3, 0.9):
            pygame.draw.line(tela, cor, (x, y), (x + 15 * math.cos(ang), y + 15 * math.sin(ang)), 3)


def _seta(tela, a, b, cor=DESTAQUE):
    pygame.draw.line(tela, cor, a, b, 3)
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    for d in (2.6, -2.6):
        pygame.draw.line(tela, cor, b, (b[0] + 12 * math.cos(ang + d), b[1] + 12 * math.sin(ang + d)), 3)


def ilustracao_arqueiro(tela, hud, rect, etapa, t):
    """Arqueiro de perfil (visão da câmera lateral), desenhado a tinta no pergaminho."""
    pergaminho(tela, rect)
    cx, base = rect.x + rect.w * 0.42, rect.y + 40
    # Movimento da mão direita na etapa de puxada: vai e volta entre repouso e âncora.
    if etapa == 0:
        u = 0.0
    elif etapa == 1:
        u = m3.ease_in_out(m3.vai_e_volta(t * 0.8, 1.0))
    else:
        u = 1.0
    cabeca = (cx - 30, base + 70)
    pescoco = (cx - 30, base + 92)
    ombro = (cx - 28, base + 108)
    quadril = (cx - 38, base + 215)
    mao_esq = (cx + 120, base + 112)
    ancora = (cx - 8, base + 92)
    repouso = (mao_esq[0] - 26, mao_esq[1] + 2)
    mao_dir = (m3.lerp(repouso[0], ancora[0], u), m3.lerp(repouso[1], ancora[1], u))
    cotovelo = (m3.lerp(cx + 30, cx - 70, u), m3.lerp(base + 140, base + 128, u))

    # Corpo (a cabeça é desenhada por cima dos braços)
    pygame.draw.line(tela, TINTA, pescoco, quadril, 5)
    pygame.draw.line(tela, TINTA, quadril, (cx - 75, base + 305), 5)
    pygame.draw.line(tela, TINTA, quadril, (cx, base + 305), 5)
    pygame.draw.line(tela, TINTA, ombro, mao_esq, 5)  # braço do arco, esticado
    pygame.draw.line(tela, TINTA, ombro, cotovelo, 5)
    pygame.draw.line(tela, TINTA, cotovelo, mao_dir, 5)

    # Arco: madeira curvada para o alvo; corda puxada pela mão direita.
    curva = 18 + 14 * u
    topo, fundo = base + 10, base + 214
    pontos = []
    for i in range(21):
        k = i / 20
        y = m3.lerp(topo, fundo, k)
        x = mao_esq[0] + 6 - (curva + 16) * (1 - math.sin(math.pi * k))
        pontos.append((x, y))
    pygame.draw.lines(tela, (110, 70, 36), False, pontos, 7)
    encaixe = (mao_dir[0] + 4, mao_dir[1]) if u > 0.02 else (pontos[0][0], mao_esq[1])
    pygame.draw.line(tela, TINTA_CLARA, pontos[0], encaixe, 2)
    pygame.draw.line(tela, TINTA_CLARA, pontos[-1], encaixe, 2)

    if etapa < 2:
        ponta = (encaixe[0] + 175, encaixe[1] + (mao_esq[1] - encaixe[1]) * 175 / max(1, mao_esq[0] - encaixe[0]))
        pygame.draw.line(tela, (150, 104, 60), encaixe, ponta, 4)
        pygame.draw.polygon(tela, TINTA, [ponta, (ponta[0] - 12, ponta[1] - 6), (ponta[0] - 12, ponta[1] + 6)])
    else:
        # Flecha já solta, voando rumo ao alvo.
        voo = (t * 1.2) % 1.0
        x = m3.lerp(mao_esq[0] + 30, rect.right - 70, voo)
        pygame.draw.line(tela, (150, 104, 60), (x - 70, mao_esq[1]), (x, mao_esq[1]), 4)
        pygame.draw.polygon(tela, TINTA, [(x + 10, mao_esq[1]), (x - 2, mao_esq[1] - 6), (x - 2, mao_esq[1] + 6)])

    pygame.draw.circle(tela, PAPEL, (int(cabeca[0]), int(cabeca[1])), 18)
    pygame.draw.circle(tela, TINTA, (int(cabeca[0]), int(cabeca[1])), 20, 4)
    pygame.draw.polygon(tela, TINTA, [(cabeca[0] - 22, cabeca[1] - 6), (cabeca[0] + 4, cabeca[1] - 30),
                                      (cabeca[0] + 16, cabeca[1] - 10)])  # capuz
    _mao(tela, mao_esq, fechada=True)
    _mao(tela, mao_dir, fechada=etapa < 2, cor=DESTAQUE)
    hud.texto(tela, "esquerda", hud.f_pequena, TINTA, (mao_esq[0] + 8, mao_esq[1] + 16), "midtop", sombra=False)
    if u < 0.5:
        hud.texto(tela, "direita", hud.f_pequena, DESTAQUE, (mao_dir[0] - 8, mao_dir[1] - 14), "midbottom", sombra=False)
    else:
        hud.texto(tela, "direita", hud.f_pequena, DESTAQUE, (mao_dir[0] + 14, mao_dir[1] + 14), "topleft", sombra=False)
    if etapa == 1:
        _seta(tela, (repouso[0] - 20, repouso[1] + 44), (ancora[0] + 10, repouso[1] + 44))
        hud.texto(tela, "puxe até o rosto", hud.f_pequena, DESTAQUE, ((repouso[0] + ancora[0]) / 2, repouso[1] + 52), "midtop", sombra=False)
    elif etapa == 2:
        hud.texto(tela, "abra a mão: solta!", hud.f_pequena, DESTAQUE, (mao_dir[0] + 40, mao_dir[1] - 34), "bottomleft", sombra=False)

    # Alvo à direita e câmera frontal ao lado dele.
    ax, ay = rect.right - 46, base + 112
    for r, cor in ((30, (236, 232, 220)), (24, (40, 40, 44)), (18, (52, 108, 196)), (12, (206, 48, 44)), (6, (238, 196, 52))):
        pygame.draw.ellipse(tela, cor, (ax - r * 0.35, ay - r, r * 0.7, r * 2))
    cam = pygame.Rect(0, 0, 34, 22)
    cam.center = (ax - 30, base + 236)
    pygame.draw.rect(tela, TINTA, cam, border_radius=4)
    pygame.draw.circle(tela, PAPEL, (cam.x + 8, cam.centery), 6)
    hud.texto(tela, "câmera frontal", hud.f_pequena, TINTA, (rect.right - 16, cam.bottom + 4), "topright", sombra=False)
    hud.texto(tela, "Você visto pela câmera lateral", hud.f_pequena, TINTA_CLARA, (rect.centerx, rect.bottom - 20), "midbottom", sombra=False)


# ---------------------------------------------------------------- calibração

def tela_calibracao(tela, hud, entrada, forca, t):
    hud.escurecer(tela, 150)
    etapa = entrada.etapa
    titulo, instrucoes = ETAPAS_CALIBRACAO[etapa]
    hud.texto(tela, f"Calibração {etapa + 1}/3 · {titulo}", hud.f_grande, OURO, (hud.largura // 2, 46), "center")

    ilustracao_arqueiro(tela, hud, pygame.Rect(40, 100, 500, 400), etapa, t)

    painel = pygame.Rect(570, 90, 670, 560)
    hud.painel(tela, painel, 200)
    y = painel.y + 18
    for linha in instrucoes:
        hud.texto(tela, linha, hud.f_pequena, PERGAMINHO, (painel.x + 20, y))
        y += 26
    y += 6
    for texto, ok in entrada.checklist:
        _marca(tela, (painel.x + 32, y + 11), ok)
        hud.texto(tela, texto, hud.f_pequena, VERDE if ok else PERGAMINHO, (painel.x + 52, y))
        y += 28

    # Prévias das câmeras escolhidas.
    y += 6
    for i, (rastreador, papel) in enumerate(((entrada.frontal, "Frontal"), (entrada.lateral, "Lateral"))):
        caixa = pygame.Rect(painel.x + 20 + i * 322, y, 306, 230)
        pygame.draw.rect(tela, (20, 14, 8), caixa)
        sup = _preview_superficie(rastreador, caixa.size)
        if sup:
            tela.blit(sup, caixa)
            chave = papel.lower()
            desenhar_puxada(tela, caixa, entrada.pares[chave], entrada.rastros[chave], forca, forca > 0,
                            entrada.mao_fechada, hud.f_pequena)
            maos = entrada.maos_camera.get(chave, [])
            desenhar_maos(tela, caixa, maos, entrada.pares[chave], forca, forca > 0, hud.f_pequena)
            _, aviso = status_camera(rastreador, maos, entrada.pares[chave], forca, forca > 0, entrada.mao_fechada)
            if aviso:
                hud.texto(tela, aviso, hud.f_pequena, VERMELHO, (caixa.x + 8, caixa.bottom - 26))
        else:
            msg = "sem câmera lateral" if rastreador is None else (rastreador.erro or "iniciando...")
            hud.texto(tela, msg, hud.f_pequena, PERGAMINHO, caixa.center, "center")
        pygame.draw.rect(tela, OURO, caixa, 2)
        hud.texto(tela, papel, hud.f_pequena, OURO, (caixa.x + 8, caixa.y + 4))
    y += 244

    # Rodapé: contagem, progresso ou teste.
    barra = pygame.Rect(painel.x + 20, y, painel.w - 40, 22)
    if etapa < 2:
        if entrada.fase == "preparar":
            n = max(1, math.ceil(entrada.contagem))
            hud.texto(tela, f"Prepare-se... {n}", hud.f_media, OURO, (painel.centerx, y + 10), "center")
        else:
            pygame.draw.rect(tela, (40, 30, 20), barra, border_radius=6)
            pygame.draw.rect(tela, VERDE, (barra.x, barra.y, int(barra.w * entrada.progresso_etapa), barra.h), border_radius=6)
            pygame.draw.rect(tela, OURO, barra, 2, border_radius=6)
        if entrada.aviso:
            hud.texto(tela, entrada.aviso, hud.f_pequena, OURO, (painel.centerx, y + 36), "midtop")
        hud.texto(tela, "Enter pula esta etapa", hud.f_pequena, (190, 175, 150), (painel.right - 16, painel.bottom - 8), "bottomright")
    else:
        pygame.draw.rect(tela, (40, 30, 20), barra, border_radius=6)
        cor = tuple(int(m3.lerp(a, b, forca)) for a, b in zip((230, 200, 90), (220, 70, 50)))
        pygame.draw.rect(tela, cor, (barra.x, barra.y, int(barra.w * forca), barra.h), border_radius=6)
        pygame.draw.rect(tela, OURO, barra, 2, border_radius=6)
        if entrada.teste_forca is not None:
            texto = f"Flecha de teste: força {entrada.teste_forca * 100:.0f}%"
            cor_txt = VERDE if entrada.teste_forca > 0.6 else OURO
        else:
            texto, cor_txt = "Puxe e solte para testar", PERGAMINHO
        hud.texto(tela, texto, hud.f_media, cor_txt, (painel.centerx, y + 36), "midtop")
        p = entrada.progresso_polegar
        if p > 0:
            pygame.draw.arc(tela, VERDE if entrada._polegar == "cima" else VERMELHO,
                            pygame.Rect(painel.right - 70, y + 30, 44, 44), math.pi / 2, math.pi / 2 + 2 * math.pi * p, 5)
        hud.texto(tela, "Polegar para cima / Enter: jogar   ·   polegar para baixo / K: refazer", hud.f_pequena,
                  (190, 175, 150), (painel.centerx, painel.bottom - 8), "midbottom")


# ---------------------------------------------------------------- escolha de câmeras

def tela_cameras(tela, hud, fontes, rastreadores, escolha, procurando, t):
    """Cartões com prévia de cada câmera. Devolve os botões para o laço tratar os cliques."""
    hud.escurecer(tela, 160)
    cx = hud.largura // 2
    hud.texto(tela, "Escolha das câmeras", hud.f_grande, OURO, (cx, 50), "center")
    hud.texto(tela, "Frontal: de frente para você (mira).  Lateral: de lado, vendo o perfil (força).",
              hud.f_pequena, PERGAMINHO, (cx, 92), "center")
    mouse = pygame.mouse.get_pos()
    botoes = []
    if procurando:
        hud.texto(tela, "Procurando câmeras...", hud.f_media, OURO, (cx, hud.altura // 2), "center")
        return botoes

    n = max(1, len(fontes))
    largura = min(380, (hud.largura - 80 - 20 * (n - 1)) // n)
    altura_prev = int(largura * 0.75)
    x0 = cx - (n * largura + (n - 1) * 20) // 2
    for i, fonte in enumerate(fontes):
        rect = pygame.Rect(x0 + i * (largura + 20), 130, largura, altura_prev + 150)
        hud.painel(tela, rect.inflate(12, 12), 210)
        prev = pygame.Rect(rect.x, rect.y, largura, altura_prev)
        pygame.draw.rect(tela, (20, 14, 8), prev)
        rastreador = rastreadores.get(fonte)
        sup = _preview_superficie(rastreador, prev.size)
        if sup:
            tela.blit(sup, prev)
            desenhar_maos(tela, prev, rastreador.leitura().maos, (None, None))
            if rastreador.transmitindo:
                maos = len(rastreador.leitura().maos)
                status, cor = f"Com sinal · {maos} mão" + ("s" if maos != 1 else ""), VERDE
            else:
                status, cor = "Conectada, sem transmissão: inicie no celular", OURO
        else:
            status = (rastreador.erro if rastreador and rastreador.erro else "Iniciando...")
            if status == "Sem sinal":
                status = "Não abre: o app da câmera está aberto?"
            cor = OURO
            hud.texto(tela, "sem imagem", hud.f_pequena, (150, 135, 110), prev.center, "center")
        papel = "Frontal" if escolha.get("frontal") == fonte else ("Lateral" if escolha.get("lateral") == fonte else None)
        if papel:
            pygame.draw.rect(tela, OURO, prev, 3)
            hud.texto(tela, papel, hud.f_media, OURO, (prev.x + 10, prev.y + 6))
        nome = _quebrar(hud.f_pequena, fonte.rotulo, largura - 8)[0]
        hud.texto(tela, nome, hud.f_pequena, PERGAMINHO, (rect.x + 4, prev.bottom + 8))
        for k, linha in enumerate(_quebrar(hud.f_pequena, status, largura - 8)[:2]):
            hud.texto(tela, linha, hud.f_pequena, cor, (rect.x + 4, prev.bottom + 34 + 22 * k))
        meio = (largura - 10) // 2
        for j, (texto, acao) in enumerate((("Frontal", "frontal"), ("Lateral", "lateral"))):
            b = Botao(pygame.Rect(rect.x + j * (meio + 10), rect.bottom - 44, meio, 38), texto, (acao, fonte),
                      ativo=escolha.get(acao) == fonte)
            b.desenhar(tela, hud, mouse)
            botoes.append(b)

    if not fontes:
        hud.texto(tela, "Nenhuma câmera encontrada.", hud.f_media, OURO, (cx, 300), "center")

    y = hud.altura - 120
    dicas = "Mostre as mãos: os pontos aparecem na prévia da câmera que está funcionando."
    hud.texto(tela, dicas, hud.f_pequena, (200, 186, 160), (cx, y - 26), "center")
    for k, (texto, acao) in enumerate((("Procurar de novo", "procurar"), ("Só mouse e teclado", "sem_camera"),
                                       ("Confirmar", "confirmar"))):
        b = Botao(pygame.Rect(cx - 330 + k * 230, y, 200, 46), texto, (acao, None), ativo=acao == "confirmar" and bool(escolha.get("frontal")))
        b.desenhar(tela, hud, mouse)
        botoes.append(b)
    hud.texto(tela, "Câmeras virtuais (DroidCam, OBS) só têm sinal com o aplicativo transmitindo.  Enter confirma.",
              hud.f_pequena, (170, 156, 130), (cx, hud.altura - 30), "center")
    return botoes


# ---------------------------------------------------------------- menu

def tela_menu(tela, hud, nome, editando, modo, modos, ranking, calibrado, cameras, t, tutorial_visto=True):
    """Menu com nome do arqueiro, modos de jogo e placar. Devolve os botões clicáveis."""
    hud.escurecer(tela, 110)
    cx = hud.largura // 2
    mouse = pygame.mouse.get_pos()
    botoes = []
    hud.texto(tela, "Arrow the Target", hud.f_titulo, OURO, (cx, 78), "center")
    hud.texto(tela, "Torneio de arqueiros da clareira", hud.f_media, PERGAMINHO, (cx, 134), "center")

    esquerda = pygame.Rect(150, 170, 480, 486)
    hud.painel(tela, esquerda, 200)
    hud.texto(tela, "Arqueiro", hud.f_pequena, OURO, (esquerda.x + 20, esquerda.y + 14))
    caixa = pygame.Rect(esquerda.x + 20, esquerda.y + 40, esquerda.w - 40, 44)
    pygame.draw.rect(tela, (30, 22, 14), caixa, border_radius=8)
    pygame.draw.rect(tela, OURO if editando else (150, 120, 80), caixa, 2, border_radius=8)
    cursor = "|" if editando and int(t * 2) % 2 == 0 else ""
    hud.texto(tela, (nome or "") + cursor, hud.f_media, PERGAMINHO, (caixa.x + 12, caixa.centery), "midleft")
    dica = "digite e tecle Enter" if editando else ("calibração salva" if calibrado else "clique para mudar (N)")
    hud.texto(tela, dica, hud.f_pequena, (190, 175, 150), (caixa.right - 10, caixa.centery), "midright", sombra=False)
    botoes.append(Botao(caixa, "", ("nome", None)))

    hud.texto(tela, "Modo de jogo  (setas esquerda/direita)", hud.f_pequena, OURO, (esquerda.x + 20, esquerda.y + 100))
    y = esquerda.y + 126
    for chave, info in modos.items():
        rect = pygame.Rect(esquerda.x + 20, y, esquerda.w - 40, 56)
        ativo = chave == modo
        sobre = rect.collidepoint(mouse)
        pygame.draw.rect(tela, (150, 106, 50) if ativo else ((96, 66, 40) if sobre else (64, 44, 28)), rect, border_radius=8)
        pygame.draw.rect(tela, OURO if ativo or sobre else (150, 120, 80), rect, 2, border_radius=8)
        hud.texto(tela, info["nome"], hud.f_media, PERGAMINHO, (rect.x + 14, rect.y + 4))
        hud.texto(tela, info["descricao"], hud.f_pequena, (225, 210, 180), (rect.x + 14, rect.y + 33), sombra=False)
        botoes.append(Botao(rect, "", ("modo", chave)))
        y += 62

    tutorial = Botao(pygame.Rect(esquerda.x + 20, esquerda.bottom - 128, esquerda.w - 40, 44),
                     "Como jogar (tutorial)  ·  T", ("tutorial", None), ativo=not tutorial_visto)
    tutorial.desenhar(tela, hud, mouse)
    botoes.append(tutorial)
    jogar = Botao(pygame.Rect(esquerda.x + 20, esquerda.bottom - 70, esquerda.w - 40, 52), "", ("jogar", None), ativo=True)
    jogar.desenhar(tela, hud, mouse)
    pulso = 0.5 + 0.5 * math.sin(t * 3)
    cor = tuple(int(m3.lerp(a, b, pulso)) for a, b in zip(PERGAMINHO, OURO))
    hud.texto(tela, "Jogar  (Enter, clique ou feche a mão direita)", hud.f_pequena, cor, jogar.rect.center, "center")
    botoes.append(jogar)

    direita = pygame.Rect(660, 170, 470, 486)
    hud.painel(tela, direita, 200)
    titulo = f"Melhores · {modos[modo]['nome']}"
    hud.texto(tela, titulo, hud.f_media, OURO, (direita.x + 20, direita.y + 12))
    if not modos[modo].get("placar", True):
        hud.texto(tela, "O treino livre não entra no placar.", hud.f_pequena, PERGAMINHO, (direita.x + 20, direita.y + 60))
    elif not ranking:
        hud.texto(tela, "Ninguém pontuou ainda. Seja o primeiro!", hud.f_pequena, PERGAMINHO, (direita.x + 20, direita.y + 60))
    for i, item in enumerate(ranking[:5]):
        yy = direita.y + 60 + i * 36
        cor = OURO if i == 0 else PERGAMINHO
        hud.texto(tela, f"{i + 1}.", hud.f_media, cor, (direita.x + 24, yy))
        hud.texto(tela, str(item.get("nome", "?"))[:16], hud.f_media, cor, (direita.x + 64, yy))
        hud.texto(tela, f"{item.get('pontos', 0)}", hud.f_media, cor, (direita.right - 24, yy), "topright")

    frontal, lateral = cameras
    linhas = [("Câmera frontal: " + ("pronta" if frontal else "indisponível"), frontal),
              ("Câmera lateral: " + ("pronta" if lateral else "indisponível"), lateral)]
    for i, (texto, ok) in enumerate(linhas):
        _marca(tela, (direita.x + 32, direita.bottom - 70 + i * 30 + 10), bool(ok))
        hud.texto(tela, texto, hud.f_pequena, VERDE if ok else PERGAMINHO, (direita.x + 52, direita.bottom - 70 + i * 30))
    if not frontal:
        hud.texto(tela, "Sem câmera: jogue com mouse e teclado.", hud.f_pequena, OURO, (direita.x + 20, direita.bottom - 104))

    hud.texto(tela, "Tab: câmeras  ·  K: calibrar  ·  N: nome  ·  setas: modo  ·  F11: tela cheia  ·  Esc: sair",
              hud.f_pequena, (200, 186, 160), (cx, hud.altura - 30), "center")
    return botoes
