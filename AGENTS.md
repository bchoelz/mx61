# Diretrizes Operacionais para Agentes de IA (`AGENTS.md`) — Projeto Yamaha MX61

Este documento define as **regras obrigatórias de segurança de hardware, governança de memória e arquitetura de síntese** para qualquer agente que opere sobre o sintetizador **Yamaha MX61** neste repositório.

> **Leitura Obrigatória ao Iniciar em Novo Terminal**: Leia primeiro [`docs/SESSION-HANDOFF-CONTEXTO.md`](docs/SESSION-HANDOFF-CONTEXTO.md) e [`docs/ARC-001-ANL-v1.0-estrategia-engenharia-mx61.md`](docs/ARC-001-ANL-v1.0-estrategia-engenharia-mx61.md) para carregar todo o histórico da conversa, decisões alinhadas com o usuário e o roteiro exato de continuidade com o hardware conectado.

---

## 1. Regras de Ouro de Proteção de Memória e Slots do MX61

1. **Intocabilidade da Memória de Fábrica (`Preset Voices`)**:
   - Os **1.106 timbres originais** (`Preset 1..8`, `MSB=63, LSB=0..7`) e **61 Drum Kits** estão em ROM somente-leitura. Para melhorá-los, faça o *Bulk Dump Request* do Preset (`0E 00..07 nn`), edite a estrutura de 8 Elements e envie para o **`Normal Voice Edit Buffer` (`0E 0F 00`)** ou salve em um slot vazio de **`User Voice` (`U001..U128`, `0E 0A nn`)**.
2. **Prioridade Absoluta aos Slots Vazios de `User Voice` (`U001..U128` = `"Initialize"`)**:
   - De fábrica, todos os 128 slots de `User Voice` (`U001..U128`, `MSB=63, LSB=8, PC=0..127`) vêm vazios com o nome **`Initialize`**.
   - **Nunca sobrescreva** uma `User Voice` cujo nome atual no teclado seja diferente de `Initialize` sem autorização explícita do usuário e sem antes salvar um snapshot individual em `backups/snapshots/`.
3. **Proteção da `Performance 001 (A01: MXCategory)` (Baseline de Referência)**:
   - A `Performance 001` é a cena inicial padrão do MX61 onde o músico navega pelas categorias (`[PIANO]`, `[KEYBOARD]`, etc.). **Jamais sobrescreva a `Performance 001` permanentemente na Flash**.
   - Para testes em tempo real, utilize sempre os **Edit Buffers voláteis de RAM**:
     - `Normal Voice Edit Buffer`: Header `0E 0F 00` / Footer `0F 0F 00` (ou `Mixing Part Voice Edit Buffer` `0E 30 pp`).
     - `Performance Edit Buffer`: Header `0E 5F 00` / Footer `0F 5F 00`.
4. **Backup em Duas Camadas Obrigatório (`backups/`)**:
   - **`backups/full_initial/` (Imutável)**: Antes da primeira gravação no teclado, execute `full-backup` para salvar em disco o bloco `SYSTEM`, todas as **128 User Voices (`U001..U128`)**, os **8 User Drum Kits** e todas as **128 User Performances (`001..128`)**. Nunca sobrescreva `backups/full_initial/` se já estiver completo.
   - **`backups/snapshots/` (Pré-Gravação)**: Antes de gravar em qualquer slot `User Voice` (`0E 0A nn`) ou `User Performance` (`0E 50 nn`), faça o dump prévio do slot para `backups/snapshots/` permitindo rollback imediato.

---

## 2. Arquitetura de Controles Físicos do MX61 (Como Contornar a Falta de Sliders)

Diferente do Casio PX-5S (que possuía 6 sliders + 4 knobs e 4 zonas independentes no painel), o **Yamaha MX61** possui no painel físico apenas:
- **Roda de Modulação (`MW`, Source = `1`, CC#1)** e **Pitch Bend (`PB`, Source = `0`)**;
- **4 Knobs (`[A]–[D]`)** alternados pelo botão `[KNOB FUNCTION]` em 3 linhas (`1: Cutoff/Reso/Chorus/Reverb`, `2: Attack/Decay/Sustain/Release`, `3: Volume/Pan/Assign1/Assign2`) e o botão **`[PART 1-2 LINK]`**;
- No modo *standalone* (`LocalCtrl = on`), o teclado físico toca apenas **`Part 1` (Principal) + `Part 2` (`[LAYER]` / `[SPLIT]`)**.

Portanto, **todo timbre multi-camada projetado para o MX61 deve seguir estas 3 diretrizes**:
1. **Multi-Layer Interno nos 8 Elements da `User Voice`**:
   - Construa timbres ricos combinando os **8 Elements (`41 00..07` / `42 00..07`) dentro de uma única `User Voice`** (ex.: Elements 1–4 = Piano Acústico calibrado com `Insertion Effect Sw = ins`; Elements 5–8 = Warm Pad / Strings / DX Tines com `Insertion Effect Sw = thru` indo direto para o `REV-X Hall`).
   - Dessa forma, mesmo sem ativar `[LAYER]`, uma única `User Voice` já oferece múltiplas camadas; e quando `[LAYER]` (`Part 1 + Part 2`) é ativado, somam-se **até 16 Elements e 2 Insertion Effects independentes**.
2. **`Modulation Wheel (MW)` Mapeada como "Slider Físico de Layer"**:
   - Em timbres de Piano/EP/Worship, **não desperdice a `Modulation Wheel` com vibrato (`LFO PMD`)**.
   - Configure a **Matriz de 6 `Controller Sets` (`40 06 00..17`) + `Controller Set Element Sw` (`41 ee 12..13`)** para que `MW (Source = 1)` controle o **`Element Level` (`Dest = 73`)** e/ou **`Filter Cutoff` (`Dest = 98`)** exclusivamente dos Elements de camada secundária (Elements 5–8) ou exclusivamente da `Part 2` (desativando `Receive MW` na `Part 1` em `37 00 20` bit 3).
3. **`Knobs [C] (ASSIGN 1)` e `[D] (ASSIGN 2)` como "Macro-Knobs"**:
   - Programe `ASSIGN 1 (Source = 8)` e `ASSIGN 2 (Source = 9)` nos `Controller Sets` para controlar parâmetros de expressão, *crossfade* entre camadas ou intensidade do `Insertion Effect A` (`Dest 1..16`) e `Reverb Send` (`Dest 66`), mantendo `[PART 1-2 LINK]` ativo quando `Part 1` e `Part 2` atuarem juntas.

---

## 3. Comunicação USB-MIDI e Captura Digital USB-Audio

- **Cabo Único `USB [TO HOST]`**:
  - **MIDI**: Utilize sempre a **Porta 1 (`Yamaha MX49/MX61-1`)**, que é a única porta reconhecida pelo bloco Gerador de Som e pelo motor SysEx do MX61 (`Reference Manual` pág. 20).
  - **Áudio Digital**: Utilize a interface de áudio USB estéreo embutida no próprio MX61 (`Line (Yamaha MX49/MX61)` / `Steinberg USB Audio`) para gravação e análise espectral sem ruído analógico.
- **Pré-requisitos no Painel do MX61** (`[UTILITY] -> 02:MIDI`):
  - `MIDI IN/OUT` = `USB`
  - `DeviceNo.` = `all` (ou `1`)
  - `RcvBulk` = `on`
