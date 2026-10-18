"""Arrow the Target: tiro com arco numa clareira, mirando com as mãos pela webcam.

Uso:
    python src/main.py                         # escolhe as câmeras na tela inicial, tela cheia
    python src/main.py --sem-camera --janela   # mouse/teclado, em janela
    python src/main.py --mudo                  # sem sons
"""
import argparse
import copy
import json
import math
import random
from pathlib import Path

import numpy as np
import pygame

import mat3d as m3
import telas
from tutorial import Tutorial
from cena import ALTURA_OLHOS, LIMITE_LATERAL, POSTOS, Cena
from entrada import Entrada
from flecha import MALHA as MALHA_FLECHA
from flecha import Flecha
from hud import OURO, PERGAMINHO, VERDE, VERMELHO, Hud
from modelos import PALHA, arco_primeira_pessoa
from particulas import Particulas
from render import ILUMINACAO, Lote, Renderizador
from sons import TAXA, Sons

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
TAMANHO_PLACAR = 5
NOME_MAXIMO = 14
ARQUIVO_PLACAR = Path(__file__).with_name("placar.json")
ARQUIVO_RECORDE_ANTIGO = Path(__file__).with_name("recorde.json")
ARQUIVO_CONFIG = Path(__file__).with_name("config.json")

MODOS = {
    "torneio": {"nome": "Torneio", "descricao": "15 flechas em 3 postos (x1, x2, x3)",
                "flechas": TOTAL_FLECHAS, "tempo": None, "placar": True},
    "tempo": {"nome": "Contra o tempo", "descricao": "60 segundos, flechas sem limite",
              "flechas": None, "tempo": 60.0, "placar": True},
    "treino": {"nome": "Treino livre", "descricao": "sem limite e sem placar, para praticar",
               "flechas": None, "tempo": None, "placar": False},
}
ORDEM_MODOS = list(MODOS)

COR_PALHA = [PALHA, (190, 156, 88), (236, 214, 150)]
COR_TERRA = [(110, 86, 58), (92, 70, 46), (132, 108, 76)]
COR_MADEIRA = [(120, 84, 50), (160, 118, 72), (90, 62, 38)]
COR_OURO = [(255, 226, 120), (240, 196, 60), (255, 250, 220)]

CAMERA_LENTA = 0.3  # escala do tempo durante a câmera da flecha
PONTOS_CAMERA_FLECHA = 8  # tiros previstos com pelo menos isso (ou bônus) ganham a câmera da flecha
DIFICULDADE_MIN, DIFICULDADE_MAX = 0.7, 1.6

# ---------------------------------------------------------------- persistência

def _ler_json(caminho):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _gravar_json(caminho, dados):
    try:
        caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def carregar_config():
    return _ler_json(ARQUIVO_CONFIG)


def atualizar_config(**campos):
    """Mescla os campos no config.json (câmeras, nome do jogador, calibrações por pessoa)."""
    dados = carregar_config()
    dados.update(campos)
    _gravar_json(ARQUIVO_CONFIG, dados)


def carregar_placar():
    placar = _ler_json(ARQUIVO_PLACAR)
    if not placar and ARQUIVO_RECORDE_ANTIGO.exists():
        # Migra o recorde único da versão anterior.
        antigo = _ler_json(ARQUIVO_RECORDE_ANTIGO).get("recorde", 0)
        if antigo:
            placar = {"torneio": [{"nome": "Arqueiro", "pontos": int(antigo)}]}
    return {modo: list(placar.get(modo, [])) for modo in MODOS}


class Jogo:
    def __init__(self, usar_camera=True, tela_cheia=True, som=True):
        pygame.mixer.pre_init(TAXA, -16, 2, 512)
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
        self.particulas = Particulas()
        self.sons = Sons(ligado=som)
        self.sons.ambiente()
        self.fonte_fps = pygame.font.SysFont("consolas", 14)

        config = carregar_config()
        self.nome = config.get("jogador") or "Arqueiro"
        self.modo = config.get("modo") if config.get("modo") in MODOS else "torneio"
        self.tutorial_visto = bool(config.get("tutorial_visto"))
        self.demo = None
        self._depois_tutorial = "menu"
        self.mostrar_painel_arco = False
        self.editando_nome = False
        self.placar = carregar_placar()
        self.estado = "MENU"
        self.t_real = 0.0
        self.novo_recorde = False
        self.mostrar_camera = True
        self.botoes = []
        self._puxando_antes = False
        self._forca_antes = 0.0
        self.reiniciar()

        # Câmeras: cada fonte encontrada ganha um rastreador; a escolha define frontal e lateral.
        self.usar_camera = usar_camera
        self.fontes, self.rastreadores, self.escolha = [], {}, {}
        self.procurando = False
        if usar_camera:
            self.estado = "CAMERAS"
            self.procurar_cameras(primeira_vez=True)
        elif not self.tutorial_visto:
            self.iniciar_tutorial(depois="menu")

    # ---------------------------------------------------------------- estado da partida

    @property
    def info_modo(self):
        return MODOS[self.modo]

    @property
    def recorde(self):
        lista = self.placar.get(self.modo, [])
        return lista[0]["pontos"] if lista else 0

    @property
    def tempo_restante(self):
        limite = self.info_modo["tempo"]
        return None if limite is None else limite - self.t_jogo

    def reiniciar(self):
        self.pontos = 0
        self.flechas = []
        self.restantes = self.info_modo["flechas"]  # None = sem limite
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
        self.ranking_final = []
        # Dificuldade adaptativa e relógio próprio dos alvos (anda mais rápido quando ela sobe).
        self.dificuldade, self.tendencia = 1.0, 0
        self.t_alvos = 0.0
        self.camera_flecha = None
        self.cena.alvos[-1].fixar(None)

    @property
    def camera_ok(self):
        return self.entrada.frontal is not None and self.entrada.frontal.ativo

    @property
    def lateral_ok(self):
        return self.entrada.lateral is not None and self.entrada.lateral.ativo

    def mudar_estado(self, novo):
        self.estado = novo
        self.entrada.soltar_tudo()
        self.sons.parar_rangido()
        self._puxando_antes = False
        pygame.mouse.set_visible(novo != "JOGANDO")

    def hora_do_dia(self):
        """0 = tarde, 1 = pôr do sol: avança com o andamento da partida."""
        if self.estado in ("MENU", "CAMERAS", "CALIBRANDO", "TUTORIAL"):
            return 0.0
        if self.info_modo["flechas"]:
            return 0.9 * (self.info_modo["flechas"] - (self.restantes or 0)) / self.info_modo["flechas"]
        if self.info_modo["tempo"]:
            return 0.9 * m3.limitar(self.t_jogo / self.info_modo["tempo"])
        return 0.9 * m3.limitar(self.t_jogo / 240.0)

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
        self.sons.tocar("clique", 0.6)
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
        self.carregar_calibracao()
        atualizar_config(frontal=frontal.rotulo if frontal else None, lateral=lateral.rotulo if lateral else None)
        if not self.tutorial_visto:
            self.iniciar_tutorial(depois="calibrar" if frontal else "menu")
        else:
            self.mudar_estado("MENU")

    # ---------------------------------------------------------------- jogador e calibração por pessoa

    def carregar_calibracao(self):
        """Usa a calibração salva para o arqueiro atual, se houver."""
        salvas = carregar_config().get("calibracoes", {})
        if self.nome in salvas:
            self.entrada.importar_calibracao(salvas[self.nome])
        else:
            self.entrada.reiniciar_calibracao()

    def salvar_calibracao(self):
        salvas = carregar_config().get("calibracoes", {})
        salvas[self.nome] = self.entrada.exportar_calibracao()
        atualizar_config(calibracoes=salvas)

    def terminar_edicao_nome(self):
        self.editando_nome = False
        self.nome = self.nome.strip() or "Arqueiro"
        atualizar_config(jogador=self.nome)
        self.carregar_calibracao()

    def mudar_modo(self, passo=None, chave=None):
        indice = ORDEM_MODOS.index(self.modo)
        self.modo = chave or ORDEM_MODOS[(indice + passo) % len(ORDEM_MODOS)]
        atualizar_config(modo=self.modo)
        self.sons.tocar("clique", 0.6)

    def iniciar_tutorial(self, depois="menu"):
        """Demonstração não jogável; ao fim vai para a calibração (primeira vez) ou volta ao menu."""
        self.reiniciar()
        self.restantes = None
        self.vento = 0.0
        self.demo = Tutorial(self)
        self._depois_tutorial = depois
        self.mudar_estado("TUTORIAL")

    def terminar_tutorial(self):
        self.demo = None
        self.cena.alvos[-1].fixar(None)
        self.tutorial_visto = True
        atualizar_config(tutorial_visto=True)
        self.reiniciar()
        if self._depois_tutorial == "calibrar" and self.camera_ok:
            self.iniciar_calibracao()
        else:
            self.mudar_estado("MENU")

    def iniciar_calibracao(self):
        self.entrada.reiniciar_calibracao()
        self.mudar_estado("CALIBRANDO")

    def jogar(self):
        """Do menu: calibra antes se houver câmera e o arqueiro ainda não estiver calibrado."""
        self.sons.tocar("clique", 0.7)
        if self.camera_ok and not self.entrada.calibrado:
            self.iniciar_calibracao()
        else:
            self.comecar_partida()

    def comecar_partida(self):
        if self.estado == "CALIBRANDO" and self.entrada.calibrado:
            self.salvar_calibracao()
        self.reiniciar()
        self.mudar_estado("JOGANDO")

    def finalizar(self):
        """Fim da partida: registra no placar do modo e mostra o resultado."""
        if self.info_modo["placar"]:
            lista = self.placar[self.modo]
            recorde_antes = self.recorde
            lista.append({"nome": self.nome, "pontos": self.pontos})
            lista.sort(key=lambda item: -item["pontos"])
            del lista[TAMANHO_PLACAR:]
            self.novo_recorde = self.pontos > recorde_antes
            _gravar_json(ARQUIVO_PLACAR, self.placar)
        self.ranking_final = list(self.placar.get(self.modo, []))
        self.sons.tocar("fanfarra", 0.7)
        self.sons.parar_rangido()
        self.mudar_estado("RESULTADO")

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
                if not self.editando_nome:
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
        if self.editando_nome:
            return self.tratar_edicao_nome(ev)
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            self.tratar_clique(ev.pos)
            return True
        if ev.type != pygame.KEYDOWN:
            return True
        tecla = ev.key
        if tecla == pygame.K_ESCAPE:
            return False
        if tecla == pygame.K_p and self.estado in ("JOGANDO", "PAUSADO"):
            self.mudar_estado("PAUSADO" if self.estado == "JOGANDO" else "JOGANDO")
        elif tecla == pygame.K_r and self.estado in ("JOGANDO", "PAUSADO", "RESULTADO"):
            self.comecar_partida()
        elif tecla == pygame.K_m and self.estado in ("JOGANDO", "PAUSADO", "RESULTADO"):
            self.mudar_estado("MENU")
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
        elif tecla in (pygame.K_RETURN, pygame.K_KP_ENTER) and self.estado == "TUTORIAL":
            self.terminar_tutorial()
        elif tecla == pygame.K_t and self.estado == "MENU":
            self.iniciar_tutorial(depois="menu")
        elif tecla == pygame.K_g:
            self.mostrar_painel_arco = not self.mostrar_painel_arco
        elif tecla == pygame.K_n and self.estado == "MENU":
            self.editando_nome = True
        elif tecla in (pygame.K_LEFT, pygame.K_RIGHT) and self.estado == "MENU":
            self.mudar_modo(passo=1 if tecla == pygame.K_RIGHT else -1)
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
        elif self.estado == "JOGANDO" and tecla == pygame.K_SPACE and self.camera_flecha:
            self.camera_flecha = None
        return True

    def tratar_clique(self, posicao):
        if self.estado in ("CAMERAS", "MENU"):
            for botao in self.botoes:
                if botao.rect.collidepoint(posicao):
                    acao, valor = botao.acao
                    if self.estado == "CAMERAS":
                        self.clicar_camera(acao, valor)
                    elif acao == "nome":
                        self.editando_nome = True
                    elif acao == "modo":
                        self.mudar_modo(chave=valor)
                    elif acao == "jogar":
                        self.jogar()
                    elif acao == "tutorial":
                        self.iniciar_tutorial(depois="menu")
                    return
        elif self.estado == "CALIBRANDO" and self.entrada.etapa == 2:
            self.comecar_partida()
        elif self.estado == "JOGANDO" and self.camera_flecha:
            self.camera_flecha = None

    def tratar_edicao_nome(self, ev):
        if ev.type == pygame.TEXTINPUT:
            if len(self.nome) < NOME_MAXIMO:
                self.nome += ev.text
        elif ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_BACKSPACE:
                self.nome = self.nome[:-1]
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE, pygame.K_TAB):
                self.terminar_edicao_nome()
        elif ev.type == pygame.MOUSEBUTTONDOWN:
            self.terminar_edicao_nome()
        return True

    # ---------------------------------------------------------------- atualização

    def atualizar(self, dt):
        self.hud.atualizar(dt)
        self.particulas.atualizar(dt)
        ILUMINACAO.definir_hora(self.hora_do_dia())
        if self.estado in ("MENU", "CAMERAS"):
            self.cena.atualizar(self.t_real)
            self.yaw = 0.35 * math.sin(self.t_real * 0.15)
            self.pitch = 0.04
        if self.estado == "MENU":
            self.cmd = self.entrada.atualizar(dt)
            if self.cmd.confirmar and not self.editando_nome:
                self.jogar()
        elif self.estado == "CALIBRANDO":
            self.cena.atualizar(self.t_real)
            self.entrada.calibrar(dt)
            if self.entrada.etapa == 2:
                # Tiro de teste: usa o gesto normal e confirma com o polegar.
                self.cmd = self.entrada.atualizar(dt)
                self.som_da_puxada(self.cmd, dt)
                if self.cmd.disparou:
                    self.entrada.teste_forca = self.cmd.forca_disparo
                    self.sons.tocar("disparo")
                polegar = self.entrada.gesto_polegar(dt)
                if polegar == "cima":
                    self.comecar_partida()
                elif polegar == "baixo":
                    self.iniciar_calibracao()
        elif self.estado == "JOGANDO":
            self.atualizar_jogo(dt)
        elif self.estado == "TUTORIAL":
            self.atualizar_tutorial(dt)
        elif self.estado == "RESULTADO":
            self.cmd = self.entrada.atualizar(dt)
            self.cena.atualizar(self.t_alvos)
            if self.cmd.confirmar:
                self.comecar_partida()
        # PAUSADO: nada avança; o tempo de jogo fica congelado.

    def som_da_puxada(self, cmd, dt):
        """Rangido contínuo da corda: começa ao puxar, acompanha a força e para ao soltar."""
        if cmd.puxando:
            if not self._puxando_antes:
                self.sons.tocar("puxar", 0.5)
                self.sons.iniciar_rangido()
            velocidade = (cmd.forca - self._forca_antes) / max(dt, 1e-3)
            self.sons.ajustar_rangido(cmd.forca, velocidade)
        elif self._puxando_antes:
            self.sons.parar_rangido()
        self._puxando_antes = cmd.puxando
        self._forca_antes = cmd.forca if cmd.puxando else 0.0

    def pode_atirar(self):
        if self.camera_flecha:
            return False
        sem_flechas = self.restantes is not None and self.restantes <= 0
        sem_tempo = self.tempo_restante is not None and self.tempo_restante <= 0
        return not sem_flechas and not sem_tempo and self.recarga <= 0 and self.transicao is None

    def passo_do_mundo(self, dt_real):
        """Tempo, alvos e teletransporte. Na câmera da flecha, o mundo anda em câmera lenta."""
        dt = dt_real * CAMERA_LENTA if self.camera_flecha else dt_real
        self.atualizar_camera_flecha(dt_real)
        self.t_jogo += dt
        escala_alvos = self.dificuldade if self.estado == "JOGANDO" else 1.0
        self.t_alvos += dt * escala_alvos
        self.cena.atualizar(self.t_alvos)
        if self.transicao:
            a, b, t = self.transicao
            t += dt
            u = m3.limitar(t / DURACAO_TELEPORTE)
            self.pos_camera = m3.lerp(a, b, m3.ease_in_out(u)) + np.array((0, 0.5 * math.sin(math.pi * u), 0))
            self.transicao = None if u >= 1 else (a, b, t)
        return dt

    def mirar(self, alvo_yaw, alvo_pitch, dt, rapidez=14.0):
        k = 1 - math.exp(-dt * rapidez)
        self.yaw = m3.lerp(self.yaw, alvo_yaw, k)
        self.pitch = m3.lerp(self.pitch, alvo_pitch, k)
        direcao = m3.direcao(self.yaw, self.pitch)
        self.foco = self.cena.alvo_na_mira(self.pos_camera, direcao)
        return direcao

    def disparar(self, direcao, forca):
        origem = self.pos_camera + direcao * 0.6 + np.array((0, -0.08, 0))
        flecha = Flecha(origem, direcao, forca, self.vento, POSTOS[self.posto][2])
        self.flechas.append(flecha)
        if self.restantes is not None:
            self.restantes -= 1
        self.recarga = RECARGA
        if self.estado == "JOGANDO":
            self.vento = random.uniform(-VENTO_MAX, VENTO_MAX) * self.dificuldade
        pan = self.yaw / YAW_MAX * 0.6
        self.sons.tocar("disparo", 0.9, pan)
        self.sons.tocar("voo", 0.4 + 0.5 * forca, pan)
        self.talvez_camera_flecha(flecha)

    def atualizar_flechas(self, dt):
        for f in self.flechas:
            evento = f.atualizar(dt, self.cena)
            if evento:
                self.registrar_impacto(f, evento)
        if len(self.flechas) > MAX_FLECHAS_CENA:
            self.flechas = self.flechas[-MAX_FLECHAS_CENA:]

    def atualizar_jogo(self, dt_real):
        dt = self.passo_do_mundo(dt_real)
        cmd = self.cmd = self.entrada.atualizar(dt_real)
        self.som_da_puxada(cmd, dt_real)
        if cmd.posto and not self.camera_flecha:
            self.sons.tocar("clique", 0.7)
            self.teleportar(cmd.posto - 1)

        # Navegação contínua pela plataforma (o teletransporte anda em passo_do_mundo).
        if not self.transicao:
            teclas = pygame.key.get_pressed()
            passo = (teclas[pygame.K_d] or teclas[pygame.K_RIGHT]) - (teclas[pygame.K_a] or teclas[pygame.K_LEFT])
            self.pos_camera[0] = m3.limitar(self.pos_camera[0] + passo * VELOCIDADE_ANDAR * dt, -LIMITE_LATERAL, LIMITE_LATERAL)

        direcao = self.mirar(cmd.mira[0] * YAW_MAX, -cmd.mira[1] * PITCH_MAX + 0.03, dt)
        self.recarga -= dt
        if cmd.disparou and self.pode_atirar():
            self.disparar(direcao, cmd.forca_disparo)
        self.atualizar_flechas(dt)

        voando = any(f.estado == "voando" for f in self.flechas)
        acabou = (self.restantes is not None and self.restantes <= 0) or \
                 (self.tempo_restante is not None and self.tempo_restante <= 0)
        if acabou and not voando and not self.camera_flecha:
            self.fim += dt
            if self.fim > 1.6:
                self.finalizar()

    def atualizar_tutorial(self, dt_real):
        """O roteiro faz o papel do jogador: a entrada real é ignorada."""
        dt = self.passo_do_mundo(dt_real)
        cmd = self.cmd = self.demo.atualizar(dt_real)
        self.som_da_puxada(cmd, dt_real)
        if cmd.posto and not self.camera_flecha:
            self.sons.tocar("clique", 0.7)
            self.teleportar(cmd.posto - 1)
        direcao = self.mirar(*self.demo.mira, dt_real, rapidez=6.0)
        self.recarga -= dt
        if cmd.disparou and not self.camera_flecha:
            self.disparar(direcao, cmd.forca_disparo)
        self.atualizar_flechas(dt)
        if self.demo.acabou and not self.camera_flecha:
            self.terminar_tutorial()

    # ---------------------------------------------------------------- câmera da flecha

    def prever_impacto(self, flecha, duracao=2.5, passo=1 / 60):
        """Simula uma cópia da flecha (vento fixo => determinística), com os alvos andando
        no tempo futuro, e devolve o evento de impacto previsto. Depois restaura a cena."""
        copia = copy.copy(flecha)
        copia.pos, copia.vel, copia.rastro = flecha.pos.copy(), flecha.vel.copy(), []
        escala = self.dificuldade if self.estado == "JOGANDO" else 1.0
        t = self.t_alvos
        evento = None
        for _ in range(int(duracao / passo)):
            t += passo * escala
            self.cena.atualizar(t)
            evento = copia.atualizar(passo, self.cena)
            if evento:
                break
        self.cena.atualizar(self.t_alvos)
        return evento

    def talvez_camera_flecha(self, flecha):
        if self.camera_flecha or any(f.estado == "voando" and f is not flecha for f in self.flechas):
            return
        evento = self.prever_impacto(flecha)
        if evento and evento[0] == "alvo" and (evento[2] >= PONTOS_CAMERA_FLECHA or (evento[1].bonus and evento[2])):
            self.camera_flecha = {"flecha": flecha, "idade": 0.0, "depois": None, "pose": None}

    def atualizar_camera_flecha(self, dt_real):
        cam = self.camera_flecha
        if not cam:
            return
        cam["idade"] += dt_real
        f = cam["flecha"]
        if f.estado == "voando":
            direcao = f.vel / (np.linalg.norm(f.vel) + 1e-9)
            yaw, pitch = m3.angulos_de(direcao)
            cam["pose"] = (f.pos - direcao * 1.4 + np.array((0, 0.3, 0)), yaw, pitch - 0.1)
        else:
            cam["depois"] = (cam["depois"] or 0.0) + dt_real
            if cam["depois"] > 0.8:
                self.camera_flecha = None

    def ajustar_dificuldade(self, pontos, acertou):
        if self.estado != "JOGANDO":
            return
        delta = 0.08 if pontos >= 8 else (0.02 if acertou else -0.08)
        anterior = self.dificuldade
        self.dificuldade = m3.limitar(self.dificuldade + delta, DIFICULDADE_MIN, DIFICULDADE_MAX)
        self.tendencia = (self.dificuldade > anterior) - (self.dificuldade < anterior)

    def registrar_impacto(self, flecha, evento):
        tipo, alvo, pontos = evento
        ponta = flecha.ponta_mundo()
        posicao = self.render.projetar_ponto(ponta) or (LARGURA / 2, ALTURA / 2 - 60)
        pan = m3.limitar(2 * posicao[0] / LARGURA - 1, -1, 1)
        voo = -flecha.vel / (np.linalg.norm(flecha.vel) + 1e-9)
        self.ajustar_dificuldade(pontos, tipo == "alvo" and pontos > 0)
        if tipo == "alvo":
            valor = round(pontos * flecha.multiplicador)
            self.pontos += valor
            self.ultimo_impacto = flecha
            if alvo.bonus and pontos:
                alvo.atingido()
                self.hud.adicionar_popup(f"Bônus! +{valor}", OURO, posicao)
                self.particulas.emitir(ponta, COR_OURO, 60, velocidade=5.0, tamanho=0.06)
                self.sons.tocar("bonus", 1.0, pan)
            elif pontos == 10:
                self.hud.adicionar_popup(f"Na mosca! +{valor}", OURO, posicao)
                self.particulas.emitir(ponta, COR_PALHA + COR_OURO, 36, direcao=voo)
                self.sons.tocar("mosca", 1.0, pan)
            elif pontos:
                self.hud.adicionar_popup(f"+{valor}", VERDE, posicao)
                self.particulas.emitir(ponta, COR_PALHA, 24, direcao=voo)
                self.sons.tocar("alvo", 1.0, pan)
            else:
                self.hud.adicionar_popup("Só a palha", PERGAMINHO, posicao)
                self.particulas.emitir(ponta, COR_PALHA, 30, direcao=voo)
                self.sons.tocar("alvo", 0.7, pan)
        else:
            valor = 0
            texto = {"arvore": "Na árvore!", "chao": "Errou", "perdida": "Perdida..."}[tipo]
            self.hud.adicionar_popup(texto, VERMELHO, posicao)
            if tipo == "arvore":
                self.particulas.emitir(ponta, COR_MADEIRA, 16, direcao=voo, velocidade=2.5)
                self.sons.tocar("madeira", 1.0, pan)
            elif tipo == "chao":
                self.particulas.emitir(ponta, COR_TERRA, 18, velocidade=2.0, tamanho=0.04)
                self.sons.tocar("chao", 1.0, pan)
        self.historico.append((self.posto + 1, valor))

    # ---------------------------------------------------------------- desenho

    def desenhar(self):
        cmd = self.cmd
        puxando = bool(cmd and cmd.puxando and self.estado == "JOGANDO")
        forca = cmd.forca if puxando else 0.0
        if self.estado == "TUTORIAL" and self.cmd is not None:
            puxando, forca = self.cmd.puxando, self.cmd.forca
        cam = self.camera_flecha if self.estado in ("JOGANDO", "TUTORIAL") else None
        if cam and cam["pose"] is not None:
            posicao, yaw, pitch = cam["pose"]
            self.render.definir_camera(posicao, yaw, pitch, FOV)
        else:
            self.render.definir_camera(self.pos_camera, self.yaw, self.pitch, FOV - ZOOM * forca)
        self.render.desenhar_fundo(self.tela)

        tempo_cena = self.t_alvos if self.estado not in ("MENU", "CAMERAS") else self.t_real
        visiveis = [f for f in self.flechas if f.estado != "perdida"]
        matrizes = [f.matriz() for f in visiveis]
        sombras = self.cena.lote_sombras(tempo_cena, self.vento, ILUMINACAO.luz, matrizes, MALHA_FLECHA)
        self.render.desenhar_lotes(self.tela, [self.cena.lote_chao, sombras])

        extras = [(MALHA_FLECHA, m, f is self.ultimo_impacto) for f, m in zip(visiveis, matrizes)]
        foco = self.foco if self.estado in ("JOGANDO", "TUTORIAL") else None
        dinamico = self.cena.lote_dinamico(tempo_cena, self.vento, foco, extras)
        self.render.desenhar_lotes(self.tela, [self.cena.lote_estatico, dinamico])
        self.desenhar_rastros()
        self.particulas.desenhar(self.tela, self.render)

        if self.estado == "TUTORIAL":
            if cam:
                self.hud.faixas_cinema(self.tela, cam["idade"] / 0.3, "Câmera da flecha")
            else:
                self.desenhar_arco(forca, self.recarga <= 0)
                self.hud.mira(self.tela, foco, puxando, forca, False)
                self.hud.barra_forca(self.tela, forca, puxando)
            self.hud.desenhar_popups(self.tela)
            self.demo.desenhar(self.tela, self.hud, self.t_real)
        elif self.estado in ("JOGANDO", "PAUSADO") and cam:
            self.hud.desenhar_popups(self.tela)
            self.hud.faixas_cinema(self.tela, cam["idade"] / 0.3, "Câmera da flecha   (Espaço ou clique pula)")
        elif self.estado in ("JOGANDO", "PAUSADO"):
            self.desenhar_arco(forca, self.pode_atirar())
            self.hud.mira(self.tela, foco, puxando, forca, cmd is not None and cmd.fonte == "gesto")
            self.hud.indicador_posto(self.tela, self.entrada.dedos_atual, self.entrada.progresso_dedos, self.posto + 1)
            self.hud.barra_forca(self.tela, forca, puxando)
            self.hud.placar(self.tela, self.pontos, self.recorde, self.restantes, TOTAL_FLECHAS,
                            (self.posto + 1, POSTOS[self.posto][1], POSTOS[self.posto][2]), self.vento,
                            tempo_restante=self.tempo_restante, modo=self.info_modo["nome"],
                            dificuldade=self.dificuldade, tendencia=self.tendencia)
            if self.mostrar_painel_arco and self.camera_ok:
                self.hud.painel_arco(self.tela, self.entrada, forca, puxando)
            self.hud.desenhar_popups(self.tela)
            self.hud.ajuda(self.tela, self.camera_ok)

        if self.entrada.frontal and self.mostrar_camera and self.estado not in ("CAMERAS", "CALIBRANDO", "MENU", "TUTORIAL"):
            self.hud.previews(self.tela, [(self.entrada.frontal, "Frontal"), (self.entrada.lateral, "Lateral")],
                              self.entrada, forca, puxando)

        if self.estado == "MENU":
            self.botoes = telas.tela_menu(self.tela, self.hud, self.nome, self.editando_nome, self.modo, MODOS,
                                          self.placar.get(self.modo, []), self.entrada.calibrado,
                                          (self.camera_ok, self.lateral_ok), self.t_real, self.tutorial_visto)
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
            self.hud.tela_resultado(self.tela, self.pontos, self.recorde, self.novo_recorde, acertos, self.historico,
                                    self.info_modo["nome"], self.ranking_final, self.nome)

        fps = self.fonte_fps.render(f"{self.relogio.get_fps():.0f} fps", True, (230, 230, 220))
        self.tela.blit(fps, (LARGURA - fps.get_width() - 8, ALTURA - 20))

    def desenhar_arco(self, forca, carregado):
        """Arco 3D preso à câmera (mão esquerda à frente), desenhado por cima da cena.

        A flecha fica paralela ao eixo de visão, então converge para o centro da mira.
        A inclinação acompanha a rotação da mão do arco quando o gesto está ativo.
        """
        tremor = 0.004 * math.sin(self.t_real * 31) * max(0.0, forca - 0.85) / 0.15
        inclinacao = INCLINACAO_ARCO
        if self.estado == "JOGANDO" and self.cmd is not None and self.cmd.fonte == "gesto":
            inclinacao -= 0.8 * self.entrada.inclinacao
        camera_mundo = m3.compor(m3.translacao(*self.pos_camera), m3.orientacao(self.yaw, self.pitch))
        local = m3.compor(m3.translacao(POSICAO_ARCO[0] + tremor, POSICAO_ARCO[1], POSICAO_ARCO[2]), m3.rot_z(inclinacao))
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
    parser.add_argument("--mudo", action="store_true", help="desliga os sons")
    args = parser.parse_args()
    Jogo(usar_camera=not args.sem_camera, tela_cheia=not args.janela, som=not args.mudo).executar()


if __name__ == "__main__":
    main()
