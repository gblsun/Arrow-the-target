# Arrow the Target

AP2 de Computação Gráfica e RV/RA (CC6AM, 2026.2).

Torneio de tiro com arco numa clareira da floresta. A mira é feita com as mãos pela webcam, imitando um arco: uma mão segura o arco e a outra puxa a corda. A cena 3D é renderizada "na mão" com pygame e matrizes numpy (sem OpenGL), como nos exemplos de `ref/exercicios/pygame_aulas_1_a_9`.

## Como rodar

O MediaPipe com a API `mp.solutions` (usada em `ref/mediapipe`) precisa de Python 3.12 ou anterior.

```bash
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python src\main.py               # webcam + mouse/teclado
.venv\Scripts\python src\main.py --sem-camera  # só mouse/teclado
.venv\Scripts\python src\main.py --camera 1    # outra webcam
.venv\Scripts\python src\teste_mat3d.py        # testes das transformações
```

Sem webcam ou sem MediaPipe, o jogo continua funcionando só com mouse e teclado.

## Como jogar

São 15 flechas e 3 postos de tiro, a 15, 25 e 40 m dos alvos, com multiplicadores de pontos x1, x1,5 e x2. Os anéis valem 10, 8, 6, 4 e 2 pontos, de dentro para fora. Há 4 alvos:

- dois fixos;
- um que corre num trilho;
- um pendurado que balança.

O vento muda a cada flecha e empurra o voo para o lado. As bandeiras mostram a direção dele.

### Gesto do arco (webcam)

1. **Calibração**: estique a mão do arco e faça a pinça (polegar + indicador) com a outra mão, encostada nela. Fique parado ~2 s.
2. **Mirar**: mova a mão do arco. A câmera do jogo acompanha.
3. **Puxar**: com a pinça fechada, afaste a mão da corda da mão do arco. Quanto maior a distância, maior a força (o zoom aumenta).
4. **Atirar**: abra a pinça. Com força baixa demais, a puxada é cancelada.

Para destros, a mão da corda é a que aparece à direita na imagem espelhada. A tecla `L` troca para canhoto.

### Teclado e mouse

| Entrada | Ação |
|---|---|
| Mouse | mira; segurar o botão puxa, soltar atira |
| `Espaço` | puxar/atirar, alternativa ao botão do mouse |
| `A`/`D` ou setas | andar pela plataforma (navegação contínua) |
| `1` `2` `3` | teletransporte entre os postos |
| `P` / `R` | pausa / reinicia |
| `C` | mostra ou esconde a webcam |
| `L` / `K` | modo canhoto / recalibrar gesto |
| `Esc` | sair |

## Requisitos do enunciado

| Requisito | Onde |
|---|---|
| Tema e tarefa | Arrow the target, com competição por pontos e recorde salvo |
| Entradas | Teclado, mouse e câmera com OpenCV + MediaPipe (`gestos.py`, `entrada.py`) |
| Objetos do cenário / selecionáveis | Floresta, cercas, postos e estandartes / 4 alvos (`cena.py`, `modelos.py`) |
| Transformações | Matrizes T·R·S em coordenadas homogêneas, câmera (visão + perspectiva), recorte (`mat3d.py`, `render.py`) |
| Animação | Por Δt: alvo no trilho com ease-in-out, pêndulo hierárquico T(pivô)·R(θ), flechas cravadas que seguem o alvo, estandartes ao vento, teletransporte interpolado |
| Navegação | Contínua (`A`/`D`, mira) e por teletransporte (`1`/`2`/`3`) |
| Seleção | Linha de visada destaca o alvo em foco; disparo por gesto, clique ou tecla |
| Feedback | Contorno dourado no alvo em foco, barra de força e zoom, rastro da flecha, pontuação flutuante, flechas cravadas e o último acerto destacado (pistas de ações passadas) |

## Estrutura

```
docs/
  enunciado_AP2.pdf          enunciado da avaliação
src/
  main.py                    laço do jogo e máquina de estados
  mat3d.py                   matrizes 4x4, câmera, projeção, interpolação
  modelos.py                 malhas low-poly procedurais
  render.py                  pipeline de renderização em software (pintor)
  cena.py                    clareira, alvos animados e estandartes
  flecha.py                  balística e colisões
  gestos.py                  thread OpenCV + MediaPipe Hands
  entrada.py                 gesto/mouse/teclado -> comando do arco
  hud.py                     interface e telas
  teste_mat3d.py             testes das transformações
ref/                         material de referência da disciplina
  aulas/                     slides das aulas 01 a 12
  exercicios/                enunciados de exercícios por aula
    pygame_aulas_1_a_9/      exercícios pygame + modelos .obj
  mediapipe/                 guia e exercícios do MediaPipe
  notebooks/                 notebooks Jupyter das aulas
```
