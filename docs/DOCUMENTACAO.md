# Arrow the Target: documentação técnica

Este documento explica como o jogo funciona por dentro e como cada parte atende ao enunciado da AP2 (`docs/enunciado_AP2.pdf`). Para instalar, rodar e jogar, veja o [README](../README.md).

## 1. Visão geral

Tiro com arco numa clareira de floresta, com tema medieval leve: alvos de palha em cavaletes, estandartes e cercas de madeira. O objetivo é **competição**, em três modos:

| Modo | Regras | Placar |
|---|---|---|
| Torneio | 15 flechas em 3 postos (15, 25 e 40 m), multiplicadores x1, x2 e x3 | top 5 com nome |
| Contra o tempo | 60 s, flechas sem limite | top 5 com nome |
| Treino livre | sem limite | não |

As **entradas** são:

- **Gesto** com até duas webcams (OpenCV + MediaPipe Hands). A mão esquerda segura o arco e mira; a mão direita fechada segura a corda, a distância entre as mãos é a força e abrir a mão solta a flecha.
- **Mouse**: mira; segurar o botão puxa, soltar atira; clique nos botões das telas.
- **Teclado**: navegação, teletransporte, nome do arqueiro, modos e atalhos.

As telas formam uma máquina de estados em `src/main.py`:

```
CAMERAS ──► MENU ──► CALIBRANDO ──► JOGANDO ⇄ PAUSADO
   ▲         ▲ │    (pulada se o         │
   └── Tab ──┘ │     arqueiro já         ▼
               │     calibrou)       RESULTADO ──► JOGANDO (R)
               └──────────── M ◄─────────┘
```

## 2. Arquitetura

| Módulo | Papel |
|---|---|
| `main.py` | Janela 1280×720 (`SCALED`; tela cheia = janela sem bordas do tamanho do monitor), laço com Δt, estados, modos, placar, navegação, disparo, persistência |
| `mat3d.py` | Matrizes 4×4, câmera, projeção, recorte no plano near, sombra planar, interpolação e easing |
| `modelos.py` | Malhas low-poly procedurais (árvores e versões simplificadas, bétula, arbusto, grama, flores, alvos, cercas, flecha, arco em primeira pessoa) e leitor OBJ |
| `render.py` | Renderização em software: transformação, descarte, iluminação com ciclo do dia, neblina e algoritmo do pintor |
| `cena.py` | Montagem da clareira, alvos animados (incluindo o bônus), estandartes, sombras projetadas e seleção por raio |
| `flecha.py` | Balística das flechas e colisão com alvos, árvores e chão |
| `gestos.py` | Busca de câmeras e uma thread por câmera com OpenCV + MediaPipe Hands |
| `entrada.py` | Converte gesto, mouse e teclado num `Comando` por quadro; filtro de Kalman; calibração guiada |
| `hud.py` | Mira, barra de força, placar, vento, prévias das câmeras, pausa e resultado |
| `telas.py` | Menu, escolha de câmeras e calibração guiada com ilustração em pergaminho |
| `sons.py` | Efeitos sonoros sintetizados com numpy |
| `particulas.py` | Partículas 3D (palha, terra, madeira, ouro) |
| `tutorial.py` | Tutorial demonstrativo: roteiro de cenas que joga sozinho e mostra mãos sintéticas |
| `teste_mat3d.py`, `teste_entrada.py` | Testes automáticos |

Dependências entre os módulos:

```
main ──► cena ──► modelos ──► mat3d
  │        └────► render ───► mat3d
  ├────► flecha ─► modelos, mat3d
  ├────► entrada ► gestos
  ├────► hud
  ├────► telas ──► entrada, hud
  ├────► particulas ► mat3d
  └────► sons
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
6. **Iluminação flat (Lambert)**: `ambiente + difusa · max(0, n·L)`. A **neblina** mistura a cor da face com a do horizonte conforme a distância.
7. **Algoritmo do pintor**: as faces são ordenadas da mais distante para a mais próxima. Os anéis do alvo são discos coplanares e recebem um **viés** de profundidade para que o anel menor fique sempre por cima.

O chão (trilha, manchas e sombras) é desenhado antes, como decalque. O **arco em primeira pessoa** é um modelo 3D preso à câmera (`T(câmera)·orientação · T(POSICAO_ARCO) · R_z(inclinação)`), desenhado por último. A flecha encaixada fica paralela ao eixo de visão, por isso aponta para o centro da mira. A malha do arco depende da força e fica em cache (`lru_cache`), com a força arredondada em passos de 2%. Sem o cache, ela era remontada a cada quadro, a um custo de ~11 ms.

### Sombras projetadas

`mat3d.sombra_planar(L)` é uma matriz que leva cada ponto até o chão ao longo da direção da luz:

```
P' = P − L · (P.y / L.y)          [ 1  −Lx/Ly  0  0 ]
                                  [ 0     0    0  h ]
                                  [ 0  −Lz/Ly  1  0 ]
                                  [ 0     0    0  1 ]
```

A sombra de cada objeto que se move (alvos, estandartes, flechas) é a sua malha, numa cor escura, desenhada com a matriz `sombra · modelo`. Como as faces achatadas apontando para baixo são descartadas, sobra a silhueta. As árvores, que são estáticas, usam manchas elípticas.

### Ciclo de luz

`render.Iluminacao` interpola duas paletas, tarde e pôr do sol: direção da luz, tom do sol, ambiente, céu, grama e neblina. A hora acompanha a partida: flechas usadas no torneio, tempo decorrido no modo contra o tempo. Cada `Lote` guarda a cor base das faces e só se reilumina quando a `versao` da luz muda, o que acontece no máximo a cada 2% de avanço da hora. Os gradientes do céu e do chão também só são refeitos nesse momento.

### Nível de detalhe

Árvores a mais de 35 m da área de jogo usam versões simplificadas (`pinheiro_simples`, `copa_simples`). Elas ficam cobertas de neblina, então a diferença não aparece, e a cena economiza polígonos para a vegetação perto do jogador (bétulas, arbustos, tufos de grama e flores).

## 4. Animação, física e efeitos

Tudo é atualizado por **Δt** (tempo decorrido), não por quadro. A pausa congela o tempo de jogo, então retomar não causa saltos.

- **Alvo no trilho**: `u = ease_in_out(vai_e_volta(t, período))` e `posição = lerp(A, B, u)` (aula 10).
- **Alvo pendurado**: composição hierárquica `T(pivô) · R_z(θ(t)) · R_y(giro)`, com o alvo e as cordas no espaço local do pivô.
- **Alvo bônus** (`AlvoBonus`): a cada 20 s, ele cruza a clareira por 7 s num percurso com easing, oscilação vertical e giro, `T(x(u), y(u), z(u)) · R_y · R_z(t)`. Vale 25 pontos vezes o multiplicador e some ao ser atingido. Escondido, sua matriz o leva para baixo do chão, e as flechas cravadas nele somem junto.
- **Estandartes**: giram em torno do poste conforme o vento e tremulam com um seno.
- **Teletransporte**: interpolação com ease-in-out entre os postos, com um pequeno arco vertical.
- **Flechas**: velocidade inicial de 22 a 68 m/s conforme a força, gravidade de 9,8 m/s² e vento lateral sorteado a cada tiro (até ±3 m/s²). A integração usa 4 subpassos por quadro.
- **Colisão com o alvo**: o segmento percorrido pela ponta é levado às **coordenadas locais do alvo** (matriz inversa) e cruzado com o plano dos anéis. A distância ao centro define a pontuação. Funciona igual para alvos parados, deslizando ou balançando.
- **Flecha cravada**: guarda a matriz local relativa ao alvo e é desenhada como `alvo.matriz @ local` (hierarquia).
- **Partículas** (`particulas.py`): no impacto, saem lascas de palha (alvo), terra (chão), madeira (árvore) ou ouro (bônus). Elas têm velocidade inicial aleatória com viés para trás, gravidade, arrasto e vida limitada, e são projetadas pela mesma câmera do jogo.
- **Seleção por raio**: a linha de visada é cruzada com cada alvo. O mais próximo atingido fica em foco e ganha contorno dourado.

### Câmera da flecha

Ao disparar, `Jogo.prever_impacto` simula uma **cópia da flecha** por até 2,5 s. O vento de cada flecha é fixo, então a simulação é determinística. A cada passo, ela chama `cena.atualizar(t_futuro)` para os alvos móveis estarem onde estarão, e no fim restaura a cena com `cena.atualizar(t_atual)`. O custo medido é de ~7 ms por disparo, e a previsão bate com o voo real.

Se o tiro previsto for 8, 10 ou o bônus, a câmera da flecha liga:

- o tempo do mundo passa a 30% (`CAMERA_LENTA`);
- a câmera segue atrás da flecha (`posição = flecha − direção·1,4 + 0,3 em y`, com yaw e pitch tirados da velocidade);
- aparecem faixas de cinema;
- depois do impacto, a cena fica 0,8 s no ar e a câmera volta ao arqueiro.

### Dificuldade adaptativa

`dificuldade ∈ [0,7; 1,6]` começa em 1,0 a cada partida e muda após cada flecha:

- +0,08 se fez 8 ou mais;
- +0,02 em outro acerto;
- −0,08 se errou.

O vento é sorteado em `±3·dificuldade`. Os alvos móveis usam um relógio próprio, `t_alvos += dt·dificuldade`, então aceleram e desaceleram sem saltos. Fora da partida (tutorial), a dificuldade não muda.

### Tutorial demonstrativo

O tutorial **não é jogável**: o jogador só assiste. `tutorial.Tutorial` segue um roteiro de 8 cenas (`CENAS`), cada uma com duração, legenda e um método que, dado o progresso `u ∈ [0, 1]`, define:

- as **mãos sintéticas** (`gestos.mao_sintetica`) da câmera frontal e da lateral de demonstração;
- a **mira** desejada;
- a **força**;
- ações pontuais: disparar, trocar de posto, fixar o bônus.

`Jogo.atualizar_tutorial` usa o mesmo mundo do jogo (`passo_do_mundo`, `mirar`, `disparar`, `atualizar_flechas`), mas o `Comando` vem do roteiro, não da câmera. Por isso a demonstração tem o mesmo rangido, câmera da flecha, partículas e pontuação flutuante de uma partida real.

Os tiros são certeiros porque `flecha.angulo_para(origem, alvo, velocidade)` resolve o pitch por **bisseção**, com gravidade e sem vento, e o yaw por `atan2`. Na cena do bônus, `AlvoBonus.fixar` o deixa parado. As duas câmeras de demonstração usam o mesmo desenho das prévias reais (`desenhar_maos` e `desenhar_puxada`), então o jogador vê exatamente o que fazer.

Fluxo da primeira execução: câmeras → tutorial → calibração (o `config.json` guarda `tutorial_visto`). Depois, o tutorial pode ser revisto no menu (`T`) e pulado com Enter.

## 5. Sons

`sons.py` sintetiza todos os efeitos com numpy na abertura do jogo, sem arquivos de áudio:

| Som | Síntese |
|---|---|
| puxar | ruído grave filtrado com modulação (rangido da madeira) |
| disparo | corda: fundamental com queda de altura + harmônicos + estalo de ruído |
| voo | ruído passa-alta com envelope em sino (assobio) |
| alvo / mosca | baque grave + ruído abafado; na mosca, mais um sino em 880/1320/1760 Hz |
| madeira / chão | batida seca curta / ruído grave abafado |
| bônus / fanfarra | arpejo ascendente / quatro notas de onda quadrada suavizada |
| ambiente | vento (ruído muito filtrado, em laço) + pios de pássaros |
| rangido | laço de 1 s: ruído grave + "grãos" de atrito irregulares (a corda deslizando e prendendo) |
| tensao1–4 | estalos curtos de onda quadrada filtrada, cada um mais agudo |

**Puxada**: ao começar a puxar, o rangido entra num canal próprio em laço. O volume é `0,12 + 0,55·força`, mais um extra enquanto a força está subindo. Os estalos `tensao1` a `tensao4` tocam ao cruzar 25%, 50%, 75% e 95%. Ao soltar ou cancelar, o laço some em 80 ms.

**Som posicional**: `Sons.tocar(nome, volume, pan)` divide o volume entre os canais esquerdo e direito com pan de potência constante (`cos`/`sen` de `(pan + 1)·π/4`). O pan do impacto vem da posição na tela, e o do disparo, da mira.

Os picos são normalizados para 0,9 antes da conversão para 16 bits. Sem dispositivo de som, ou com `--mudo`, todos os métodos viram operações vazias.

## 6. Gestos

### Landmarks usados (MediaPipe Hands)

| Landmark | Uso |
|---|---|
| 0 (pulso) e 9 (base do dedo médio) | **tamanho da mão** = distância 0→9, a escala que torna as medidas independentes da distância até a câmera; o ângulo 0→9 dá a inclinação da mão do arco |
| 9 | posição da palma (mira e distância entre as mãos) |
| 4 e 8 (pontas do polegar e do indicador) | pinça |
| 8, 12, 16 e 20 (pontas dos dedos) | curvatura (punho ou mão aberta) |
| 3, 4, 5, 6, 10, 14, 17 e 18 | polegar para cima ou para baixo |

### Regras

- **Papéis das mãos**: a lateralidade do MediaPipe (`Left`/`Right`) é ligada à mão real do usuário nas etapas 1 e 2 da calibração (`Entrada.rotulos`). A esquerda é o arco e a direita é a corda; `L` inverte. Se a lateralidade vier ambígua, a mão maior, mais perto da câmera frontal, é a do arco.
- **Câmera lateral**: de perfil, a lateralidade não é confiável. De que lado fica a mão da corda vem das etapas 1 e 2 da calibração (ou, se foram puladas, é a que mais se moveu na puxada) e, quadro a quadro, a atribuição que menos desloca as duas mãos em relação ao quadro anterior. Assim, a identificação sobrevive a cruzamentos rápidos. Se as duas saltarem muito, volta para a ordem em x calibrada.
- **Mira**: posição da palma esquerda em relação ao centro calibrado, com média móvel exponencial (`SUAVIZACAO = 0.35`). Vira yaw e pitch da câmera, limitados a ±32° e ±16°.
- **Inclinação**: o ângulo do vetor pulso → palma da mão esquerda (limitado a ±0,7 rad e suavizado) inclina o arco em primeira pessoa.
- **Mão fechada ou aberta, com histerese**: a mão é considerada fechada com pinça (`abertura < PINCA_FECHA`) **ou** punho (`curvatura < CURVA_FECHA`). Ela só é considerada aberta quando a pinça abre **e** os dedos se estendem. A faixa entre os limites evita que o estado oscile.
- **Força**: distância entre as palmas convertida pela escala calibrada, `(d − repouso) / (cheia − repouso)`, e suavizada por um **filtro de Kalman 1D** (`FiltroKalman1D`):
  - previsão: `p += q`;
  - ganho: `k = p / (p + r)`;
  - atualização: `x += k (z − x)` e `p *= 1 − k`.

  A câmera lateral tem prioridade na medida.
- **Disparo**: quando a mão direita abre durante a puxada, a flecha sai com a **força máxima dos últimos 0,25 s**. Abaixo de `FORCA_MINIMA = 0.2`, a puxada é cancelada. Se a mão da corda sumir no meio da puxada, ela também é cancelada.
- **Troca de posto pelos dedos de qualquer mão** (`Mao.dedos`, `Entrada._atualizar_dedos`). Todas as mãos da câmera frontal são consideradas: vale a contagem se só um valor aparecer, e contagens diferentes nas duas mãos não fazem nada. A mão da corda mostrando dedos **não inicia** uma puxada, porque 1 dedo pareceria punho.
  - um dedo conta como estendido quando `dist(ponta, pulso) > 1,15·dist(articulação PIP, pulso)`. A regra por distância funciona com a mão inclinada;
  - só valem contagens **contíguas a partir do indicador**: 1, 2 ou 3, com o mínimo dobrado. Mão aberta e punho não trocam de posto;
  - a contagem precisa ficar estável por `TEMPO_DEDOS = 0,8 s`, nunca durante uma puxada;
  - depois de disparar, só aceita de novo quando a contagem mudar.
- **Puxada desenhada nas câmeras** (`hud.desenhar_puxada`): `Entrada.pares` guarda, por câmera, as mãos do arco e da corda identificadas no último quadro, e `Entrada.rastros` guarda as últimas 15 posições da mão da corda. Sobre cada prévia são desenhados o arco estilizado, a corda das pontas até a mão direita (cheia quando fechada) e o rastro. Tudo, inclusive a borda da prévia, usa a cor de `cor_forca`: verde → amarelo → vermelho. O mesmo aparece nas prévias grandes da calibração.
- **Polegar para cima/baixo**: adaptado da regra de `ref/mediapipe/exercicios_mediapipe.pdf` e normalizado pelo tamanho da mão. Precisa ser mantido por 0,7 s.
- **Reconhecimento mais robusto** (`gestos.py`):
  - **Filtro One Euro** por mão (`FiltroOneEuro` e `SuavizadorMaos`), com as mãos associadas entre quadros pelo pulso mais próximo. O corte se adapta à velocidade, `corte = min_cutoff + beta·|velocidade|`: suaviza muito a mão parada e pouco a mão em movimento, então tira o tremor sem atraso;
  - **CLAHE** na luminância (espaço LAB) quando o brilho médio fica abaixo de 90, o que ajuda em quartos escuros;
  - **Modelo adaptativo**: começa com `model_complexity=1`, mais preciso, e cai para 0 se a detecção passar de 45 ms em média;
  - **Tolerância a perda**: a mão da corda pode sumir por até 0,25 s (oclusão, borrão) sem cancelar a puxada;
  - **Métricas por câmera**: fps, brilho, realce ligado e modelo em uso. O esqueleto não é mais desenhado na imagem pela thread: a interface desenha a partir dos landmarks e colore cada mão pelo papel.
- **Interface das câmeras** (`hud.desenhar_maos`, `hud.status_camera`, `Hud.previews`, `Hud.painel_arco`):
  - esqueleto com as 21 ligações: azul-claro para a mão do arco, cor da força para a da corda, cinza para as demais;
  - etiquetas E e D, com o número de dedos;
  - prévias que crescem 30% durante a puxada;
  - faixa de status com estado, fps e avisos ("pouca luz", "mão saindo do quadro", "mostre as duas mãos");
  - painel "Seu arco" (`G`), com ícones das mãos normalizados pelo contorno de cada uma.
- **Desempenho**: a detecção roda numa imagem de no máximo 480 px de largura (`LARGURA_DETECCAO`). Os landmarks são normalizados, então isso não muda as medidas e alivia a CPU com duas câmeras.

## 7. Calibração guiada e por pessoa

Feita em `Entrada.calibrar` e desenhada por `telas.tela_calibracao`, com o arqueiro ilustrado em pergaminho:

1. **Mão esquerda**: só a mão esquerda levantada, à frente do corpo, e a direita abaixada. Cada câmera precisa ver exatamente uma mão. A frontal guarda o rótulo que o MediaPipe deu a ela (`Entrada.rotulos["esquerda"]`), e a lateral guarda onde ela fica em x.
2. **Mão direita**: só a direita levantada, perto do rosto. Só conclui se a frontal der a ela um rótulo **diferente** do da esquerda; senão, avisa que confundiu as mãos. Com as posições das duas etapas, a lateral sabe de que lado (em x) fica a mão da corda.
3. **Arco em repouso**: define o centro da mira e a distância de repouso.
4. **Puxada completa**: mão direita fechada junto ao rosto. Define a força 100%. Se as etapas 1 e 2 foram puladas, também define qual mão é a da corda na lateral (a que mais se moveu).
5. **Tiro de teste**: mostra a força alcançada. Polegar para cima (ou Enter) começa; polegar para baixo (ou `K`) refaz.

Os papéis das mãos na frontal passam a usar os rótulos aprendidos, então funcionam mesmo se o MediaPipe chamar a mão esquerda de `Right`. Etapas puladas com Enter mantêm o padrão (`Left` = esquerda).

Cuidados de robustez:

- contagem regressiva de 3 s;
- checklist ao vivo;
- coleta só com a pose **parada** (`ESTABILIDADE`);
- **mediana** das amostras;
- repetição da etapa 4 se a amplitude for menor que `AMPLITUDE_MINIMA`.

A calibração é **salva por arqueiro** (`config.json → calibracoes[nome]`: centro, escalas, mão da corda na lateral, canhoto e rótulos das mãos; calibrações antigas, sem rótulos, usam o padrão). Ao jogar, quem já tem calibração vai direto para a partida; trocar o nome no menu carrega a calibração dessa pessoa.

## 8. Câmeras

`gestos.listar_fontes` monta a lista de câmeras:

- **DirectShow** com os nomes dos dispositivos (`pygrabber`). Cada câmera é aberta já pedindo a resolução, na ordem 640×480, 1280×720 e padrão. Algumas câmeras virtuais, como a *DroidCam Source 3*, só abrem assim.
- **Media Foundation** para câmeras que só abrem por ele, como a *DroidCam Video*. Câmeras com a mesma imagem nos dois sistemas são descartadas como duplicatas.
- **Tela de espera**: uma imagem de cor sólida, ou mais de 90% preta, indica câmera virtual conectada mas sem transmissão.

Cada câmera ganha um `RastreadorMaos` que **reconecta automaticamente** se ela cair. A escolha de frontal e lateral fica em `src/config.json`.

## 9. Persistência

| Arquivo (fora do git) | Conteúdo |
|---|---|
| `src/config.json` | câmeras escolhidas, nome do jogador, modo escolhido, calibrações por arqueiro |
| `src/placar.json` | top 5 por modo (`nome`, `pontos`); migra o `recorde.json` da versão anterior |

## 10. Parâmetros ajustáveis

| Constante | Arquivo | Valor | Efeito |
|---|---|---|---|
| `PINCA_FECHA`, `PINCA_ABRE` | `entrada.py` | 0,35 / 0,55 | limites da pinça (em tamanhos de mão) |
| `CURVA_FECHA`, `CURVA_ABRE` | `entrada.py` | 1,2 / 1,45 | limites de punho e mão aberta |
| `FiltroKalman1D(q, r)` | `entrada.py` | 0,02 / 0,04 | suavização da força (r maior = mais suave) |
| `FORCA_MINIMA` | `entrada.py` | 0,2 | força mínima para disparar |
| `SUAVIZACAO` | `entrada.py` | 0,35 | suavização da mira (maior = mais rápida) |
| `JANELA_DISPARO` | `entrada.py` | 0,25 s | janela para a força máxima do disparo |
| `TEMPO_PREPARO`, `TEMPO_ETAPA` | `entrada.py` | 3 s / 2 s | contagem e duração de cada etapa da calibração |
| `TEMPO_DEDOS` | `entrada.py` | 0,8 s | tempo segurando os dedos para trocar de posto |
| `TOLERANCIA_PERDA` | `entrada.py` | 0,25 s | tempo que a mão da corda pode sumir sem cancelar a puxada |
| `BRILHO_MINIMO`, `LIMITE_DETECCAO_MS` | `gestos.py` | 90 / 45 ms | quando ligar o realce de luz / trocar para o modelo leve |
| `FiltroOneEuro(min_cutoff, beta)` | `gestos.py` | 1,2 / 8 | suavização dos landmarks |
| `CENAS` | `tutorial.py` | 8 cenas, ~40 s | roteiro do tutorial demonstrativo |
| `CAMERA_LENTA`, `PONTOS_CAMERA_FLECHA` | `main.py` | 0,3 / 8 | velocidade e limiar da câmera da flecha |
| `DIFICULDADE_MIN`, `DIFICULDADE_MAX` | `main.py` | 0,7 / 1,6 | limites da dificuldade adaptativa |
| `ESTABILIDADE`, `AMPLITUDE_MINIMA` | `entrada.py` | 0,03 / 0,05 | "parado" e puxada mínima na calibração |
| `LARGURA_DETECCAO` | `gestos.py` | 480 px | largura da imagem usada pelo MediaPipe |
| `VELOCIDADE_MIN`, `VELOCIDADE_MAX` | `flecha.py` | 22 / 68 m/s | velocidade da flecha com força 0 e 1 |
| `YAW_MAX`, `PITCH_MAX` | `main.py` | 32° / 16° | alcance da mira |
| `FOV`, `ZOOM` | `main.py` | 68° / 12° | campo de visão e zoom na força máxima |
| `VENTO_MAX` | `main.py` | 3 m/s² | vento lateral máximo |
| `MODOS` | `main.py` | 15 flechas / 60 s | regras de cada modo |
| `TAMANHO_PLACAR` | `main.py` | 5 | posições guardadas por modo |
| `AlvoBonus(ciclo, duracao, atraso)` | `cena.py` | 20 / 7 / 8 s | frequência e duração do alvo bônus |
| `TARDE`, `POR_DO_SOL` | `render.py` | paletas | cores e luz do ciclo do dia |

## 11. Requisitos do enunciado

| Requisito | Como foi atendido | Onde |
|---|---|---|
| Aplicação interativa com navegação | Câmera em primeira pessoa; andar pela plataforma; teletransporte entre postos | `main.py` |
| Temática | Arrow the target, numa clareira medieval | `cena.py`, `modelos.py` |
| Tarefa (objetivo) | Competição em 3 modos, placar com nomes | `main.py`, `telas.py` |
| Entrada: teclado | Navegação, teletransporte, nome, modos, pausa, atalhos | `main.py`, `entrada.py` |
| Entrada: mouse | Mira e disparo; botões do menu e das telas | `entrada.py`, `telas.py` |
| Entrada: câmera com OpenCV + MediaPipe | Arco com as duas mãos, duas câmeras, polegar para confirmar | `gestos.py`, `entrada.py` |
| Objetos do cenário | ~120 árvores de 3 tipos (com nível de detalhe), arbustos, grama, flores, pedras, morros, cercas, plataformas, estandartes | `cena.py`, `modelos.py` |
| Objetos selecionáveis | 4 alvos (2 fixos, 1 no trilho, 1 pendurado) + alvo bônus | `cena.py` |
| Transformações (AP1) | T·R·S homogêneas, hierarquia, câmera, projeção, recorte, sombra planar | `mat3d.py`, `render.py` |
| Coerência e realismo | Balística com gravidade e vento, flechas cravadas que seguem o alvo, sombras, iluminação com ciclo do dia, neblina | `flecha.py`, `render.py`, `cena.py` |
| Navegação contínua | `A`/`D` e mira contínua por gesto ou mouse | `main.py` |
| Navegação por teletransporte | `1`/`2`/`3` ou 1, 2 ou 3 dedos de qualquer mão, com transição interpolada | `main.py`, `entrada.py` |
| Seleção por teclas, cliques e mãos | Disparo por Espaço, clique ou abrir a mão; menus por clique, Enter, mão fechada ou polegar | `entrada.py`, `telas.py` |
| Feedback de foco e seleção | Contorno dourado no alvo em foco, mira dourada com o nome do alvo, estandarte agitado, puxada desenhada nas câmeras na cor da força, anel de troca de posto, rangido da corda | `cena.py`, `hud.py`, `sons.py` |
| Pistas de ações passadas | Flechas cravadas, último acerto destacado, rastro da flecha e da mão, partículas, câmera da flecha, histórico e placar no resultado | `main.py`, `hud.py`, `particulas.py` |

## 12. Testes e verificação

- `src/teste_mat3d.py`: ordem das transformações, T·R·S, `direcao`/`orientacao`/`angulos_de`, câmera levando um ponto ao eixo óptico, projeção, recorte near, **sombra planar** (o ponto cai no chão ao longo da luz) e extremos dos easings.
- `src/teste_entrada.py` (16 testes, mãos sintéticas de `gestos.mao_sintetica`, sem câmera):
  - Kalman converge sem oscilar e reduz ruído;
  - disparo com força alta;
  - força mínima;
  - cancelamento quando a mão some;
  - histerese de mão fechada/aberta;
  - calibração completa;
  - repetição da puxada curta;
  - continuidade da mão da corda na lateral;
  - polegar para cima;
  - exportar/importar calibração;
  - contagem de dedos (1 a 3, mão inclinada, mão aberta, punho, contagem ambígua);
  - troca de posto: um único evento após 0,8 s e nenhum durante a puxada;
  - dedos de qualquer mão: a direita também troca de posto e não inicia puxada; contagens diferentes são ignoradas;
  - perda curta da mão não cancela a puxada, e perda longa cancela;
  - One Euro suaviza a mão parada e acompanha o movimento;
  - `angulo_para` acerta alvos a 15, 25 e 40 m;
  - sons dentro de [−1, 1].

  Os testes encontraram e corrigiram dois problemas: a troca de mãos num cruzamento na câmera lateral e a distorção do som de impacto.
- **Simulações sem janela** (`SDL_VIDEODRIVER=dummy`) durante o desenvolvimento:
  - partida com tiros mirados;
  - alvo bônus atingido (25 pontos);
  - pôr do sol;
  - resultado com placar;
  - telas renderizadas e salvas como imagem;
  - tutorial completo: os três tiros da demonstração acertam (10, 10×2 e bônus 25×2), e no fim o jogo vai para a calibração (ou para o menu, sem câmera).
- **Desempenho medido** (i7-3770, sem câmeras): ~16,5 ms por quadro (~60 fps), com ~6.400 faces estáticas, sombras e partículas. Antes das otimizações abaixo eram ~24 ms (~41 fps). Com as duas câmeras e o MediaPipe rodando na mesma máquina, a CPU fica disputada e o jogo cai para ~40 fps.
- **Otimizações do renderizador** (`render.py`), sem mudar a imagem:
  - cada malha guarda seus arrays de faces (`_arrays_da_malha`), e os lotes dinâmicos são montados por quadro só com numpy;
  - descarte grosso pela esfera de cada face (de costas, atrás, longe ou fora dos planos laterais) antes dos testes por vértice: das ~6.400 faces estáticas, só ~1.100 seguem;
  - conversão para listas agrupada pelo número de vértices, sem os índices de preenchimento;
  - recorte 2D só para polígonos que passam mais de `MARGEM_RECORTE` px acima ou abaixo da tela (o pygame percorre todas as linhas do polígono, mas corta cada linha na horizontal sem custo); a diferença são bordas de 1 px em polígonos que saem da tela;
  - o HUD guarda os textos e painéis já renderizados.
- **Laço**: `FPS_MAXIMO = 120`. Com o teto fixo em 60, qualquer atraso derrubava abaixo de 60.

## 13. Limitações conhecidas

- As regras de gesto são heurísticas geométricas e dependem de iluminação, pose e oclusão.
- Câmeras virtuais (DroidCam, OBS) só funcionam com o aplicativo delas transmitindo.
- O MediaPipe `mp.solutions` exige Python 3.12 ou anterior.
- A renderização em software não tem z-buffer: o pintor pode errar a ordem de faces que se cruzam, e o número de polígonos é limitado.
- As sombras projetadas são planares (só no chão), não caem sobre outros objetos.

## 14. Ideias futuras

- Trilha musical medieval (alaúde e flauta sintetizados).
- Multijogador local alternado (dois arqueiros, um placar).
- Calibração automática contínua (reajuste fino da força durante o jogo).
- Replay do melhor tiro da partida na tela de resultado.
- Conquistas ("3 na mosca seguidas", "acertou o bônus do posto 3").
