# Arrow the Target: documentação técnica

Este documento explica como o jogo funciona por dentro e como cada parte atende ao enunciado da AP2 (`docs/enunciado_AP2.pdf`). Para instalar, rodar e jogar, veja o [README](../README.md).

## 1. Visão geral

Tiro com arco numa clareira de floresta, com tema medieval leve: alvos de palha em cavaletes, estandartes e cercas de madeira. O objetivo é **competição**: fazer o maior número de pontos com 15 flechas em 3 postos (15, 25 e 40 m, multiplicadores x1, x1,5 e x2) e bater o recorde salvo.

As **entradas** são:

- **Gesto** com até duas webcams (OpenCV + MediaPipe Hands). A mão esquerda segura o arco e mira; a mão direita fechada segura a corda, a distância entre as mãos é a força e abrir a mão solta a flecha.
- **Mouse**: mira; segurar o botão puxa, soltar atira.
- **Teclado**: navegação, teletransporte, pausa e atalhos.

As telas formam uma máquina de estados em `src/main.py`:

```
CAMERAS ──► MENU ──► CALIBRANDO ──► JOGANDO ⇄ PAUSADO
   ▲          │                         │
   └── Tab ───┘                         └──► RESULTADO ──► JOGANDO
```

## 2. Arquitetura

| Módulo | Papel |
|---|---|
| `main.py` | Janela 1280×720 (tela cheia `SCALED`), laço com Δt, estados, navegação, disparo, placar e recorde |
| `mat3d.py` | Matrizes 4×4, câmera, projeção, recorte no plano near, interpolação e easing |
| `modelos.py` | Malhas low-poly procedurais (árvores, alvos, cercas, flecha, arco em primeira pessoa) e leitor OBJ |
| `render.py` | Renderização em software: transformação, descarte, iluminação, neblina e algoritmo do pintor |
| `cena.py` | Montagem da clareira, alvos animados, estandartes e seleção por raio |
| `flecha.py` | Balística das flechas e colisão com alvos, árvores e chão |
| `gestos.py` | Busca de câmeras e uma thread por câmera com OpenCV + MediaPipe Hands |
| `entrada.py` | Converte gesto, mouse e teclado num `Comando` por quadro; calibração guiada |
| `hud.py` | Mira, barra de força, placar, vento, prévias das câmeras, menu, pausa e resultado |
| `telas.py` | Escolha de câmeras e calibração guiada com ilustração em pergaminho |
| `teste_mat3d.py` | Testes das transformações e da projeção |

Dependências entre os módulos:

```
main ──► cena ──► modelos ──► mat3d
  │        └────► render ───► mat3d
  ├────► flecha ─► modelos, mat3d
  ├────► entrada ► gestos
  ├────► hud
  └────► telas ──► entrada, hud
```

A câmera roda numa **thread separada** (`RastreadorMaos`), que só detecta e mede. A interpretação do gesto fica em `entrada.py`, no ritmo do jogo, para que a taxa de quadros não dependa do MediaPipe.

## 3. Pipeline gráfico

O mundo usa **x para a direita, y para cima e z para a frente**, ou seja, para longe do jogador.

1. **Modelo → mundo**: cada objeto tem uma matriz composta `T·R·S` em coordenadas homogêneas (`mat3d.compor`). A ordem importa, e `teste_mat3d.py` verifica que `T·R` e `R·T` dão resultados diferentes.
2. **Mundo → câmera**: `matriz_visao = rot_x(pitch) · rot_y(-yaw) · T(-posição)`, a inversa de posicionar a câmera.
3. **Descarte** (vetorizado com numpy em `Renderizador._preparar`):
   - faces de costas (normal oposta à direção da câmera);
   - faces atrás do plano near (`NEAR = 0.15`) ou além de `DISTANCIA_MAX = 230`;
   - faces inteiramente fora da janela;
   - faces menores que 1 pixel.
4. **Recorte**: polígonos que cruzam o plano near são recortados em 3D (Sutherland-Hodgman, `mat3d.recortar_near`). Polígonos que passam muito da janela são recortados em 2D (`_recortar_tela`). Sem esse recorte, polígonos com coordenadas enormes deixavam o pygame lento: o tempo por quadro caiu de 43 ms para 14 ms.
5. **Projeção perspectiva**: `x' = cx + f·x/z`, `y' = cy − f·y/z`, com `f` calculado pelo campo de visão. O campo de visão diminui ao puxar o arco, o que dá o efeito de zoom.
6. **Iluminação flat (Lambert)**: `ambiente + difusa · max(0, n·L)`, com luz de fim de tarde. A **neblina** mistura a cor da face com a do horizonte conforme a distância.
7. **Algoritmo do pintor**: as faces são ordenadas da mais distante para a mais próxima. Os anéis do alvo são discos coplanares e recebem um **viés** de profundidade para que o anel menor fique sempre por cima.

O chão (trilha, sombras das árvores) é desenhado antes, como decalque. O **arco em primeira pessoa** é um modelo 3D preso à câmera (`T(câmera)·orientação · T(POSICAO_ARCO) · R_z(INCLINACAO_ARCO)`), desenhado por último. A flecha encaixada fica paralela ao eixo de visão, por isso aponta para o centro da mira.

## 4. Animação e física

Tudo é atualizado por **Δt** (tempo decorrido), não por quadro. A pausa congela o tempo de jogo, então retomar não causa saltos.

- **Alvo no trilho**: `u = ease_in_out(vai_e_volta(t, período))` e `posição = lerp(A, B, u)` (aula 10).
- **Alvo pendurado**: composição hierárquica `T(pivô) · R_z(θ(t)) · R_y(giro)`, com o alvo e as cordas no espaço local do pivô.
- **Estandartes**: giram em torno do poste conforme o vento e tremulam com um seno. O estandarte perto do alvo em foco tremula mais.
- **Teletransporte**: interpolação com ease-in-out entre os postos, com um pequeno arco vertical.
- **Flechas**: velocidade inicial de `VELOCIDADE_MIN` a `VELOCIDADE_MAX` (22 a 68 m/s) conforme a força, gravidade de 9,8 m/s² e vento lateral sorteado a cada tiro (até ±3 m/s²). A integração usa 4 subpassos por quadro.
- **Colisão com o alvo**: o segmento percorrido pela ponta é levado às **coordenadas locais do alvo** (matriz inversa) e cruzado com o plano dos anéis. A distância ao centro define a pontuação (10/8/6/4/2, ou 0 na palha). Por usar coordenadas locais, a colisão funciona igual para alvos parados, deslizando ou balançando.
- **Flecha cravada**: guarda a matriz local relativa ao alvo e é desenhada como `alvo.matriz @ local`, então acompanha o alvo que se move (hierarquia).
- **Seleção por raio**: a linha de visada é cruzada com cada alvo. O mais próximo atingido fica em foco e ganha contorno dourado.

## 5. Gestos

### Landmarks usados (MediaPipe Hands)

| Landmark | Uso |
|---|---|
| 0 (pulso) e 9 (base do dedo médio) | **tamanho da mão** = distância 0→9, a escala que torna as medidas independentes da distância até a câmera |
| 9 | posição da palma (mira e distância entre as mãos) |
| 4 e 8 (pontas do polegar e do indicador) | pinça |
| 8, 12, 16 e 20 (pontas dos dedos) | curvatura (punho ou mão aberta) |
| 3, 4, 5, 6, 10, 14, 17 e 18 | polegar para cima ou para baixo |

### Regras

- **Papéis das mãos**: com a imagem espelhada, a lateralidade do MediaPipe (`Left`/`Right`) corresponde à mão real do usuário. A esquerda é o arco e a direita é a corda; `L` inverte. Se a lateralidade vier ambígua, a mão maior, mais perto da câmera frontal, é a do arco. Na câmera lateral, a mão da corda é identificada pela posição em x aprendida na calibração.
- **Mira**: posição da palma esquerda em relação ao centro calibrado, com média móvel exponencial (`SUAVIZACAO = 0.35`). Vira yaw e pitch da câmera, limitados a ±32° e ±16°.
- **Mão fechada ou aberta, com histerese**: a mão é considerada fechada com pinça (`abertura < PINCA_FECHA`) **ou** punho (`curvatura < CURVA_FECHA`). Ela só é considerada aberta quando a pinça abre (`> PINCA_ABRE`) **e** os dedos se estendem (`> CURVA_ABRE`). A diferença entre os limites evita que o estado oscile.
- **Força**: distância entre as palmas convertida pela escala calibrada, `(d − repouso) / (cheia − repouso)`. A câmera **lateral** tem prioridade, porque de perfil a puxada em direção ao rosto aparece como distância. Sem a lateral, a frontal mede.
- **Disparo**: quando a mão direita abre durante a puxada, a flecha sai com a **força máxima dos últimos 0,25 s**. Ao abrir, a mão se move um pouco e a força medida cai, por isso o pico recente é usado. Abaixo de `FORCA_MINIMA = 0.2`, a puxada é cancelada.
- **Polegar para cima/baixo**: adaptado da regra de `ref/mediapipe/exercicios_mediapipe.pdf` e normalizado pelo tamanho da mão. Precisa ser mantido por 0,7 s.

## 6. Calibração guiada

Feita em `Entrada.calibrar` e desenhada por `telas.tela_calibracao`, com o arqueiro ilustrado em pergaminho:

1. **Arco em repouso**: braço esquerdo esticado, mão direita fechada encostada na esquerda. Define o centro da mira e a distância de repouso.
2. **Puxada completa**: mão direita fechada junto ao rosto. Define a distância de força 100% e qual mão é a da corda na imagem lateral (a que mais se deslocou).
3. **Tiro de teste**: o usuário puxa e solta, e o jogo mostra a força alcançada. Polegar para cima (ou Enter) começa; polegar para baixo (ou `K`) refaz.

Cuidados de robustez:

- contagem regressiva de 3 s antes de cada etapa;
- checklist ao vivo: mão esquerda vista, mão direita fechada, câmera lateral vendo as duas mãos;
- a coleta só avança com a pose **parada** (deslocamento por quadro abaixo de `ESTABILIDADE`). Se a pessoa se mexe, o progresso recua;
- os valores usam a **mediana** das amostras;
- se a diferença entre repouso e puxada for menor que `AMPLITUDE_MINIMA`, a etapa 2 é repetida com um aviso.

## 7. Câmeras

`gestos.listar_fontes` monta a lista de câmeras:

- **DirectShow** com os nomes dos dispositivos (`pygrabber`). Cada câmera é aberta já pedindo a resolução, na ordem 640×480, 1280×720 e padrão. Algumas câmeras virtuais, como a *DroidCam Source 3*, só abrem assim.
- **Media Foundation** para câmeras que só abrem por ele, como a *DroidCam Video*. Câmeras com a mesma imagem nos dois sistemas são descartadas como duplicatas.
- **Tela de espera**: uma imagem de cor sólida, ou mais de 90% preta, indica câmera virtual conectada mas sem transmissão. O cartão mostra esse estado e muda sozinho quando a transmissão começa.

Cada câmera ganha um `RastreadorMaos` que **reconecta automaticamente** se ela cair. A escolha de frontal e lateral é salva em `src/config.json` (fora do git), e a tela de escolha é pulada quando as câmeras salvas estão com sinal.

## 8. Parâmetros ajustáveis

| Constante | Arquivo | Valor | Efeito |
|---|---|---|---|
| `PINCA_FECHA`, `PINCA_ABRE` | `entrada.py` | 0,35 / 0,55 | limites da pinça (em tamanhos de mão) |
| `CURVA_FECHA`, `CURVA_ABRE` | `entrada.py` | 1,2 / 1,45 | limites de punho e mão aberta |
| `FORCA_MINIMA` | `entrada.py` | 0,2 | força mínima para disparar |
| `SUAVIZACAO` | `entrada.py` | 0,35 | suavização da mira (maior = mais rápida) |
| `JANELA_DISPARO` | `entrada.py` | 0,25 s | janela para a força máxima do disparo |
| `TEMPO_PREPARO`, `TEMPO_ETAPA` | `entrada.py` | 3 s / 2 s | contagem e duração de cada etapa da calibração |
| `ESTABILIDADE`, `AMPLITUDE_MINIMA` | `entrada.py` | 0,03 / 0,05 | "parado" e puxada mínima na calibração |
| `VELOCIDADE_MIN`, `VELOCIDADE_MAX` | `flecha.py` | 22 / 68 m/s | velocidade da flecha com força 0 e 1 |
| `YAW_MAX`, `PITCH_MAX` | `main.py` | 32° / 16° | alcance da mira |
| `FOV`, `ZOOM` | `main.py` | 68° / 12° | campo de visão e zoom na força máxima |
| `VENTO_MAX` | `main.py` | 3 m/s² | vento lateral máximo |
| `POSICAO_ARCO`, `INCLINACAO_ARCO` | `main.py` | (−0,34, −0,2, 1,35) / −0,2 rad | posição e inclinação do arco em primeira pessoa |
| `POSTOS` | `cena.py` | 15, 25 e 40 m | distâncias e multiplicadores |

## 9. Requisitos do enunciado

| Requisito | Como foi atendido | Onde |
|---|---|---|
| Aplicação interativa com navegação | Câmera em primeira pessoa; andar pela plataforma; teletransporte entre postos | `main.py` |
| Temática | Arrow the target, numa clareira medieval | `cena.py`, `modelos.py` |
| Tarefa (objetivo) | Competição por pontos, com recorde salvo | `main.py` |
| Entrada: teclado | Navegação, teletransporte, pausa, atalhos, Espaço para atirar | `main.py`, `entrada.py` |
| Entrada: mouse | Mira e disparo; botões das telas | `entrada.py`, `telas.py` |
| Entrada: câmera com OpenCV + MediaPipe | Arco com as duas mãos, duas câmeras, polegar para confirmar | `gestos.py`, `entrada.py` |
| Objetos do cenário | ~120 árvores instanciadas com escala e rotação aleatórias, pedras, morros, cercas, plataformas, estandartes | `cena.py` |
| Objetos selecionáveis | 4 alvos (2 fixos, 1 no trilho, 1 pendurado) | `cena.py` |
| Transformações (AP1) | T·R·S homogêneas, hierarquia, câmera, projeção, recorte | `mat3d.py`, `render.py` |
| Coerência e realismo | Balística com gravidade e vento, flechas cravadas que seguem o alvo, iluminação e neblina | `flecha.py`, `render.py` |
| Navegação contínua | `A`/`D` e mira contínua por gesto ou mouse | `main.py` |
| Navegação por teletransporte | `1`/`2`/`3` com transição interpolada | `main.py` |
| Seleção por teclas, cliques e mãos | Disparo por Espaço, clique ou abrir a mão; menus por clique, Enter, mão fechada ou polegar | `entrada.py` |
| Feedback de foco e seleção | Contorno dourado no alvo em foco, mira dourada com o nome do alvo, estandarte agitado | `cena.py`, `hud.py` |
| Pistas de ações passadas | Flechas cravadas, último acerto destacado, rastro da flecha, histórico no resultado | `main.py`, `hud.py` |

## 10. Testes e verificação

- `src/teste_mat3d.py`: ordem das transformações, T·R·S, `direcao`/`orientacao`/`angulos_de`, câmera levando um ponto ao eixo óptico, projeção, recorte near, extremos dos easings.
- Durante o desenvolvimento, também foram usadas **simulações sem janela** (`SDL_VIDEODRIVER=dummy`):
  - partida com tiros mirados nos alvos, conferindo pontuação, teletransporte e tela de resultado;
  - lógica do gesto com **mãos sintéticas** nas duas câmeras: calibração, força crescente e disparo ao abrir a mão;
  - telas renderizadas e salvas como imagem, para conferir o layout.
- **Desempenho medido**: ~14 ms por quadro em janela e ~21 ms com a escala de tela cheia no driver sem vídeo, com cerca de 4.500 faces estáticas na cena.

## 11. Limitações conhecidas

- As regras de gesto são heurísticas geométricas: dependem de iluminação, pose e oclusão, por isso a calibração e a histerese.
- Câmeras virtuais (DroidCam, OBS) só funcionam com o aplicativo delas transmitindo.
- O MediaPipe `mp.solutions` exige Python 3.12 ou anterior.
- A renderização em software limita a quantidade de polígonos e não tem z-buffer. O algoritmo do pintor pode errar a ordem de faces que se cruzam.

## 12. Melhorias possíveis

- **Gesto**:
  - inclinar a mira pela rotação da mão do arco;
  - suavizar a força com filtro de Kalman;
  - salvar a calibração por pessoa;
  - detectar a lateralidade de forma mais robusta na câmera lateral.
- **Jogo**:
  - efeitos sonoros (corda, voo, impacto);
  - alvos bônus;
  - modos de jogo (contra o tempo, alvos que surgem);
  - placar com nomes.
- **Gráficos**:
  - sombras dos alvos e das flechas;
  - partículas de palha no impacto;
  - mais variedade de vegetação;
  - ciclo de luz do dia.
- **Desempenho**:
  - nível de detalhe para árvores distantes;
  - processar a câmera em resolução menor.
- **Robustez**:
  - testes automatizados de `entrada.py` com mãos sintéticas;
  - registro das sessões de calibração para ajustar os limites.
