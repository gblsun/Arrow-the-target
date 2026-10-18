"""Arrow the Target: tiro com arco numa clareira, mirando com as mãos pela webcam.

Uso:
    python src/main.py                         # escolhe as câmeras na tela inicial, tela cheia
    python src/main.py --sem-camera --janela   # mouse/teclado, em janela
"""
import argparse
import json
import math
import random
from pathlib import Path

import numpy as np
import pygame

import mat3d as m3
from cena import ALTURA_OLHOS, LIMITE_LATERAL, POSTOS, Cena
from entrada import Entrada
from flecha import MALHA as MALHA_FLECHA
from flecha import Flecha
from hud import OURO, PERGAMINHO, VERDE, VERMELHO, Hud
from modelos import arco_primeira_pessoa
from render import Lote, Renderizador
import telas

LARGURA, ALTURA = 1280, 720
TOTAL_FLECHAS = 15
YAW_MAX, PITCH_MAX = math.radians(32), math.radians(16)
FOV, ZOOM = 68.0, 12.0
VELOCIDADE_ANDAR = 3.0
DURACAO_TELEPORTE = 0.9
RECARGA = 0.6
VENTO_MAX = 3.0
MAX_FLECHAS_CENA = 40
POSICAO_ARCO = (-0.34, -0.2, 1.35)  # empunhadura em coordenadas de câmera (m)
INCLINACAO_ARCO = -0.2  # arco levemente inclinado, como o arqueiro segura
ARQUIVO_RECORDE = Path(__file__).with_name("recorde.json")
ARQUIVO_CONFIG = Path(__file__).with_name("config.json")


def carregar_recorde():
    try:
        return int(json.loads(ARQUIVO_RECORDE.read_text(encoding="utf-8"))["recorde"])
    except (OSError, ValueError, KeyError):
        return 0


def salvar_recorde(valor):
    try:
        ARQUIVO_RECORDE.write_text(json.dumps({"recorde": valor}), encoding="utf-8")
    except OSError:
        pass


def carregar_config():
    try:
        return json.loads(ARQUIVO_CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def salvar_config(dados):
    try:
        ARQUIVO_CONFIG.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


class Jogo:
    def __init__(self, usar_camera=True, tela_cheia=True):
        pygame.init()
        # Renderiza em 1280x720 e o SDL amplia para a tela inteira (SCALED mantém a proporção).
        bandeiras = pygame.SCALED | (pygame.FULLSCREEN if tela_cheia else 0)
        self.tela = pygame.display.set_mode((LARGURA, ALTURA), bandeiras)
        pygame.display.set_caption("Arrow the Target")
        self.relogio = pygame.time.Clock()

        self.entrada = Entrada(None, None, LARGURA, ALTURA)
        self.cena = Cena()
        self.render = Renderizador(LARGURA, ALTURA)
        self.hud = Hud(LARGURA, ALTURA)
        self.fonte_fps = pygame.font.SysFont("consolas", 14)

        self.estado = "MENU"
        self.t_real = 0.0
        self.recorde = carregar_recorde()
        self.novo_recorde = False
        self.mostrar_camera = True
        self.reiniciar()

        # Câmeras: cada fonte encontrada ganha um rastreador; a escolha define frontal e lateral.
        self.usar_camera = usar_camera
        self.fontes, self.rastreadores, self.escolha, self.botoes = [], {}, {}, []
        self.procurando = False
        if usar_camera:
            self.estado = "CAMERAS"
            self.procurar_cameras(primeira_vez=True)

    # ---------------------------------------------------------------- estado da partida

    def reiniciar(self):
        self.pontos = 0
        self.flechas = []
        self.restantes = TOTAL_FLECHAS
        self.posto = 0
        self.pos_camera = np.array((0.0, ALTURA_OLHOS, POSTOS[0][0]))
        self.transicao = None
        self.t_jogo = 0.0
        self.recarga = 0.0
        self.vento = random.uniform(-VENTO_MAX, VENTO_MAX)
        self.historico = []
        self.fim = 0.0
        self.ultimo_impacto = None
        self.yaw = self.pitch = 0.0
        self.foco = None
        self.cmd = None
        self.hud.popups.clear()
        self.novo_recorde = False

    @property
    def camera_ok(self):
        return self.entrada.frontal is not None and self.entrada.frontal.ativo

    @property
    def lateral_ok(self):
        return self.entrada.lateral is not None and self.entrada.lateral.ativo

    def mudar_estado(self, novo):
        self.estado = novo
        self.entrada.soltar_tudo()
        pygame.mouse.set_visible(novo != "JOGANDO")

    # ---------------------------------------------------------------- câmeras

    def procurar_cameras(self, primeira_vez=False):
        from gestos import RastreadorMaos, listar_fontes
        self.procurando = True
        self.desenhar()
        pygame.display.flip()
        for rastreador in self.rastreadores.values():
            rastreador.parar()
        for rastreador in self.rastreadores.values():
            rastreador.join(timeout=2.0)
        self.rastreadores = {}
        self.entrada.definir_cameras(None, None)
        encontradas = listar_fontes()
        self.fontes = [f for f, _ in encontradas]
        com_sinal = [f for f, estado in encontradas if estado == "ok"]
        for fonte in self.fontes:
            self.rastreadores[fonte] = RastreadorMaos(fonte)
            self.rastreadores[fonte].start()
        self.procurando = False

        # Pré-seleção: a escolha salva, se as câmeras ainda existem; senão, as que têm sinal.
        salvo = carregar_config()
        por_nome = {f.rotulo: f for f in self.fontes}
        frontal, lateral = por_nome.get(salvo.get("frontal")), por_nome.get(salvo.get("lateral"))
        if frontal is None:
            frontal = com_sinal[0] if com_sinal else None
            lateral = next((f for f in com_sinal if f != frontal), None)
        self.escolha = {"frontal": frontal, "lateral": lateral if lateral != frontal else None}
        if primeira_vez and frontal in com_sinal and salvo.get("frontal") and (
                salvo.get("lateral") is None or lateral in com_sinal):
            self.aplicar_cameras()

    def garantir_rastreadores(self):
        from gestos import RastreadorMaos
        for fonte in self.fontes:
            if fonte not in self.rastreadores:
                self.rastreadores[fonte] = RastreadorMaos(fonte)
                self.rastreadores[fonte].start()

    def clicar_camera(self, acao, fonte):
        if acao in ("frontal", "lateral"):
            outro = "lateral" if acao == "frontal" else "frontal"
            self.escolha[acao] = None if self.escolha.get(acao) == fonte else fonte
            if self.escolha.get(outro) == fonte and self.escolha[acao] == fonte:
                self.escolha[outro] = None
        elif acao == "procurar":
            self.procurar_cameras()
        elif acao == "sem_camera":
            self.escolha = {}
            self.aplicar_cameras()
        elif acao == "confirmar" and self.escolha.get("frontal"):
            self.aplicar_cameras()

    def aplicar_cameras(self):
        """Liga as câmeras escolhidas à entrada e desliga as outras (poupa CPU)."""
        frontal, lateral = self.escolha.get("frontal"), self.escolha.get("lateral")
        for fonte in list(self.rastreadores):
            if fonte not in (frontal, lateral):
                self.rastreadores.pop(fonte).parar()
        self.entrada.definir_cameras(self.rastreadores.get(frontal), self.rastreadores.get(lateral))
        salvar_config({"frontal": frontal.rotulo if frontal else None,
                       "lateral": lateral.rotulo if lateral else None})
        self.mudar_estado("MENU")

    def iniciar_calibracao(self):
        self.entrada.reiniciar_calibracao()
        self.mudar_estado("CALIBRANDO")

    def comecar_partida(self):
        self.reiniciar()
        self.mudar_estado("JOGANDO")

    def teleportar(self, indice):
        if indice == self.posto and self.transicao is None and abs(self.pos_camera[0]) < 0.01:
            return
        destino = np.array((0.0, ALTURA_OLHOS, POSTOS[indice][0]))
        self.transicao = (self.pos_camera.copy(), destino, 0.0)
        self.posto = indice

    # ---------------------------------------------------------------- laço principal

    def executar(self):
        while True:
            dt = min(self.relogio.tick(60) / 1000, 0.05)
            self.t_real += dt
            for ev in pygame.event.get():
                if not self.tratar_evento(ev):
                    self.encerrar()
                    return
                self.entrada.processar_evento(ev)
            self.atualizar(dt)
            self.desenhar()
            pygame.display.flip()

    def encerrar(self):
        for rastreador in self.rastreadores.values():
            rastreador.parar()
        pygame.quit()

    def tratar_evento(self, ev):
        if ev.type == pygame.QUIT:
            return False
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self.estado == "CAMERAS":
                for botao in self.botoes:
                    if botao.rect.collidepoint(ev.pos):
                        self.clicar_camera(*botao.acao)
                        break
            elif self.estado == "CALIBRANDO" and self.entrada.etapa == 2:
                self.comecar_partida()
            return True
        if ev.type != pygame.KEYDOWN:
            return True
        tecla = ev.key
        if tecla == pygame.K_ESCAPE:
            return False
        if tecla == pygame.K_p and self.estado in ("JOGANDO", "PAUSADO"):
            self.mudar_estado("PAUSADO" if self.estado == "JOGANDO" else "JOGANDO")
        elif tecla == pygame.K_r and self.estado in ("JOGANDO", "PAUSADO", "RESULTADO"):
            self.reiniciar()
            self.mudar_estado("JOGANDO")
        elif tecla == pygame.K_F11:
            pygame.display.toggle_fullscreen()
        elif tecla == pygame.K_v and self.entrada.frontal and self.entrada.lateral:
            self.entrada.trocar_cameras()
            if self.estado in ("JOGANDO", "CALIBRANDO"):
                self.iniciar_calibracao()
        elif tecla == pygame.K_TAB and self.usar_camera and self.estado in ("MENU", "PAUSADO", "RESULTADO"):
            self.garantir_rastreadores()
            self.mudar_estado("CAMERAS")
        elif tecla in (pygame.K_RETURN, pygame.K_KP_ENTER) and self.estado == "CAMERAS":
            self.clicar_camera("confirmar", None)
        elif tecla == pygame.K_c:
            self.mostrar_camera = not self.mostrar_camera
        elif tecla == pygame.K_l:
            self.entrada.canhoto = not self.entrada.canhoto
        elif tecla == pygame.K_k and self.camera_ok and self.estado in ("MENU", "JOGANDO", "CALIBRANDO"):
            self.iniciar_calibracao()
        elif tecla in (pygame.K_RETURN, pygame.K_KP_ENTER) and self.estado == "CALIBRANDO":
            if self.entrada.etapa == 2:
                self.comecar_partida()
            else:
                self.entrada.avancar_etapa()
        elif self.estado == "JOGANDO" and tecla in (pygame.K_1, pygame.K_2, pygame.K_3):
            self.teleportar(tecla - pygame.K_1)
        return True

    # ---------------------------------------------------------------- atualização

    def atualizar(self, dt):
        self.hud.atualizar(dt)
        if self.estado in ("MENU", "CAMERAS"):
            self.cena.atualizar(self.t_real)
            self.yaw = 0.35 * math.sin(self.t_real * 0.15)
            self.pitch = 0.04
        if self.estado == "MENU":
            self.cmd = self.entrada.atualizar(dt)
            if self.cmd.confirmar:
                if self.camera_ok and not self.entrada.calibrado:
                    self.iniciar_calibracao()
                else:
                    self.comecar_partida()
        elif self.estado == "CALIBRANDO":
            self.cena.atualizar(self.t_real)
            self.entrada.calibrar(dt)
            if self.entrada.etapa == 2:
                # Tiro de teste: usa o gesto normal e confirma com o polegar.
                self.cmd = self.entrada.atualizar(dt)
                if self.cmd.disparou:
                    self.entrada.teste_forca = self.cmd.forca_disparo
                polegar = self.entrada.gesto_polegar(dt)
                if polegar == "cima":
                    self.comecar_partida()
                elif polegar == "baixo":
                    self.iniciar_calibracao()
        elif self.estado == "JOGANDO":
            self.atualizar_jogo(dt)
        elif self.estado == "RESULTADO":
            self.cmd = self.entrada.atualizar(dt)
            self.cena.atualizar(self.t_jogo)
            if self.cmd.confirmar:
                self.reiniciar()
                self.mudar_estado("JOGANDO")
        # PAUSADO: nada avança; o tempo de jogo fica congelado.

    def atualizar_jogo(self, dt):
        self.t_jogo += dt
        self.cena.atualizar(self.t_jogo)
        cmd = self.cmd = self.entrada.atualizar(dt)

        # Navegação: teletransporte interpolado ou caminhada contínua pela plataforma.
        if self.transicao:
            a, b, t = self.transicao
            t += dt
            u = m3.limitar(t / DURACAO_TELEPORTE)
            self.pos_camera = m3.lerp(a, b, m3.ease_in_out(u)) + np.array((0, 0.5 * math.sin(math.pi * u), 0))
            self.transicao = None if u >= 1 else (a, b, t)
        else:
            teclas = pygame.key.get_pressed()
            passo = (teclas[pygame.K_d] or teclas[pygame.K_RIGHT]) - (teclas[pygame.K_a] or teclas[pygame.K_LEFT])
            self.pos_camera[0] = m3.limitar(self.pos_camera[0] + passo * VELOCIDADE_ANDAR * dt, -LIMITE_LATERAL, LIMITE_LATERAL)

        # Mira: suaviza a orientação da câmera em direção ao comando.
        alvo_yaw = cmd.mira[0] * YAW_MAX
        alvo_pitch = -cmd.mira[1] * PITCH_MAX + 0.03
        k = 1 - math.exp(-dt * 14)
        self.yaw = m3.lerp(self.yaw, alvo_yaw, k)
        self.pitch = m3.lerp(self.pitch, alvo_pitch, k)
        direcao = m3.direcao(self.yaw, self.pitch)
        self.foco = self.cena.alvo_na_mira(self.pos_camera, direcao)

        self.recarga -= dt
        if cmd.disparou and self.restantes > 0 and self.recarga <= 0 and self.transicao is None:
            origem = self.pos_camera + direcao * 0.6 + np.array((0, -0.08, 0))
            self.flechas.append(Flecha(origem, direcao, cmd.forca_disparo, self.vento, POSTOS[self.posto][2]))
            self.restantes -= 1
            self.recarga = RECARGA
            self.vento = random.uniform(-VENTO_MAX, VENTO_MAX)

        for f in self.flechas:
            evento = f.atualizar(dt, self.cena)
            if evento:
                self.registrar_impacto(f, evento)
        if len(self.flechas) > MAX_FLECHAS_CENA:
            self.flechas = self.flechas[-MAX_FLECHAS_CENA:]

        voando = any(f.estado == "voando" for f in self.flechas)
        if self.restantes == 0 and not voando:
            self.fim += dt
            if self.fim > 1.6:
                if self.pontos > self.recorde:
                    self.recorde, self.novo_recorde = self.pontos, True
                    salvar_recorde(self.recorde)
                self.mudar_estado("RESULTADO")

    def registrar_impacto(self, flecha, evento):
        tipo, alvo, pontos = evento
        posicao = self.render.projetar_ponto(flecha.ponta_mundo()) or (LARGURA / 2, ALTURA / 2 - 60)
        if tipo == "alvo":
            valor = round(pontos * flecha.multiplicador)
            self.pontos += valor
            self.ultimo_impacto = flecha
            if pontos == 10:
                self.hud.adicionar_popup(f"Na mosca! +{valor}", OURO, posicao)
            elif pontos:
                self.hud.adicionar_popup(f"+{valor}", VERDE, posicao)
            else:
                self.hud.adicionar_popup("Só a palha", PERGAMINHO, posicao)
        else:
            valor = 0
            texto = {"arvore": "Na árvore!", "chao": "Errou", "perdida": "Perdida..."}[tipo]
            self.hud.adicionar_popup(texto, VERMELHO, posicao)
        self.historico.append((self.posto + 1, valor))

    # ---------------------------------------------------------------- desenho

    def desenhar(self):
        cmd = self.cmd
        puxando = bool(cmd and cmd.puxando and self.estado == "JOGANDO")
        forca = cmd.forca if puxando else 0.0
        self.render.definir_camera(self.pos_camera, self.yaw, self.pitch, FOV - ZOOM * forca)
        self.render.desenhar_fundo(self.tela, self.cena.direcao_sol)
        self.render.desenhar_lotes(self.tela, [self.cena.lote_chao])

        tempo_cena = self.t_jogo if self.estado != "MENU" else self.t_real
        extras = [(MALHA_FLECHA, f.matriz(), f is self.ultimo_impacto) for f in self.flechas if f.estado != "perdida"]
        foco = self.foco if self.estado == "JOGANDO" else None
        dinamico = self.cena.lote_dinamico(tempo_cena, self.vento, foco, extras)
        self.render.desenhar_lotes(self.tela, [self.cena.lote_estatico, dinamico])
        self.desenhar_rastros()

        if self.estado in ("JOGANDO", "PAUSADO"):
            pronto = self.restantes > 0 and self.recarga <= 0 and self.transicao is None
            self.desenhar_arco(forca, pronto)
            self.hud.mira(self.tela, foco, puxando, forca, cmd is not None and cmd.fonte == "gesto")
            self.hud.barra_forca(self.tela, forca, puxando)
            self.hud.placar(self.tela, self.pontos, self.recorde, self.restantes, TOTAL_FLECHAS,
                            (self.posto + 1, POSTOS[self.posto][1], POSTOS[self.posto][2]), self.vento)
            self.hud.desenhar_popups(self.tela)
            self.hud.ajuda(self.tela, self.camera_ok)

        if self.entrada.frontal and self.mostrar_camera and self.estado not in ("CAMERAS", "CALIBRANDO"):
            self.hud.previews(self.tela, [(self.entrada.frontal, "Frontal"), (self.entrada.lateral, "Lateral")], self.entrada)

        if self.estado == "MENU":
            self.hud.tela_menu(self.tela, self.recorde, (self.camera_ok, self.lateral_ok), self.t_real)
        elif self.estado == "CAMERAS":
            self.botoes = telas.tela_cameras(self.tela, self.hud, self.fontes, self.rastreadores, self.escolha,
                                             self.procurando, self.t_real)
        elif self.estado == "CALIBRANDO":
            forca = self.cmd.forca if self.cmd and self.cmd.puxando and self.entrada.etapa == 2 else 0.0
            telas.tela_calibracao(self.tela, self.hud, self.entrada, forca, self.t_real)
        elif self.estado == "PAUSADO":
            self.hud.tela_pausa(self.tela)
        elif self.estado == "RESULTADO":
            acertos = sum(1 for _, v in self.historico if v > 0)
            self.hud.tela_resultado(self.tela, self.pontos, self.recorde, self.novo_recorde, acertos, self.historico)

        fps = self.fonte_fps.render(f"{self.relogio.get_fps():.0f} fps", True, (230, 230, 220))
        self.tela.blit(fps, (LARGURA - fps.get_width() - 8, ALTURA - 20))

    def desenhar_arco(self, forca, carregado):
        """Arco 3D preso à câmera (mão esquerda à frente), desenhado por cima da cena.

        A flecha fica paralela ao eixo de visão, então converge para o centro da mira.
        """
        tremor = 0.004 * math.sin(self.t_real * 31) * max(0.0, forca - 0.85) / 0.15
        camera_mundo = m3.compor(m3.translacao(*self.pos_camera), m3.orientacao(self.yaw, self.pitch))
        local = m3.compor(m3.translacao(POSICAO_ARCO[0] + tremor, POSICAO_ARCO[1], POSICAO_ARCO[2]), m3.rot_z(INCLINACAO_ARCO))
        malha = arco_primeira_pessoa(forca, carregado)
        self.render.desenhar_lotes(self.tela, [Lote([(malha, camera_mundo @ local, False)])])

    def desenhar_rastros(self):
        for f in self.flechas:
            if f.estado != "voando" or len(f.rastro) < 2:
                continue
            pontos = [p for p in (self.render.projetar_ponto(q) for q in f.rastro) if p]
            for i in range(1, len(pontos)):
                alfa = i / len(pontos)
                cor = tuple(int(m3.lerp(150, 255, alfa)) for _ in range(3))
                pygame.draw.line(self.tela, cor, pontos[i - 1], pontos[i], 1 + int(2 * alfa))


def main():
    parser = argparse.ArgumentParser(description="Arrow the Target")
    parser.add_argument("--sem-camera", action="store_true", help="joga só com mouse e teclado")
    parser.add_argument("--janela", action="store_true", help="abre em janela em vez de tela cheia")
    args = parser.parse_args()
    Jogo(usar_camera=not args.sem_camera, tela_cheia=not args.janela).executar()


if __name__ == "__main__":
    main()
