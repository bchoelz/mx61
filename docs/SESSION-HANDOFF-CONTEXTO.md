# Histórico da Conversa, Decisões de Projeto e Guia de Continuidade (`SESSION-HANDOFF-CONTEXTO.md`)

> **Propósito deste documento**: Permitir que **qualquer agente de IA ou desenvolvedor em outro terminal/computador** (ex.: no notebook Windows 11 / WSL2 conectado fisicamente ao teclado **Yamaha MX61**) assuma o projeto imediatamente com **100% do contexto das decisões tomadas até aqui**, sem precisar repetir análises preliminares.

---

## 1. Resumo Cronológico das Decisões Alinhadas com o Usuário

### 1.1. Origem do Projeto e Comparação com `bchoelz/px5s`
- **Solicitação Inicial**: Avaliar como foi desenvolvido o projeto anterior [`bchoelz/px5s`](https://github.com/bchoelz/px5s) (melhoria e criação de timbres para o piano digital Casio Privia PX-5S), baixar os manuais oficiais do **Yamaha MX61** e formular uma nova estratégia de engenharia acústica adaptada às diferenças físicas e eletrônicas do MX61.
- **Manuais Oficiais Baixados em `docs/`**:
  1. `docs/mx49mx61_en_om_b0.pdf` — *Owner's Manual*
  2. `docs/mx49mx61mx88_en_rm_b0.pdf` — *Reference Manual* (Arquitetura interna de 8 Elements, Performance de 16 Parts, VCM Effects, Controller Sets)
  3. `docs/mx49mx61_en_dl_a0.pdf` — *Data List* (Lista de 1.106 Preset Voices, 1.566 Waveforms do Motif XS, Tabelas de Efeitos e Especificação Completa MIDI SysEx `Model ID = 7F 17`, págs. 53–66)
  4. `docs/mx49mx61synth_en_pm_a0.pdf` — *Synthesizer Parameter Manual*

### 1.2. Conexão Física: Cabo USB Único (Sem Necessidade da M-Audio M-Track Plus)
- **Alinhamento do Usuário**: *"O MX61 será conectado da mesma forma via USB ao notebook, mas como você já analisou não haverá a necessidade da M-Audio dado que o MX61 já possui interface de áudio embutida."*
- **Implicação Técnica Implementada (`src/winmm_bridge.cs` e `src/midi_bridge.py`)**:
  - Pelo único cabo **`USB [TO HOST]`**, o MX61 expõe simultaneamente:
    - **USB-MIDI Porta 1 (`Yamaha MX49/MX61-1`)**: Única porta que conversa com o Gerador de Som (TG) e o motor SysEx (`7F 17`). As portas 2–5 são de controle remoto de DAW e são ignoradas automaticamente pelo `FindMxOutPort()` / `FindMxInPort()`.
    - **Interface USB-Audio Estéreo Integrada (`Yamaha MX49/MX61` / `Steinberg USB Audio`, 2-In/2-Out, 44.1 kHz / 48 kHz)**: O áudio digital pós-`Master EQ` retorna diretamente para o notebook via USB sem conversões D/A → A/D analógicas e sem desbalanceamento de potenciômetros físicos de ganho L/R.

### 1.3. Como Contornar a Ausência de Sliders Físicos e o Limite de Layer no Painel do MX61
- **Alinhamento do Usuário**: *"Diferente do PX-5S, no MX61 não tenho tantos knobs e sliders, basicamente ele só controla layer somando 1 timbre ao principal."*
- **Solução Arquitetural em 3 Pilares Implementada (`src/mx61_sysex.py` e `src/mx61_profiles.py`)**:
  1. **Pilar 1 — Multi-Layer Interno nos 8 Elements de uma Única `User Voice` (`41 00..07` / `42 00..07`)**:
     - Cada `User Voice` do MX61 possui **8 Elements independentes** (contra 4 do PX-5S).
     - Cada Element possui seu próprio filtro (`LPF24D`/`LPF18`, `Cutoff`, `Resonance`), envelope (`AEG`/`FEG`), `Note Limit`, `Velocity Limit`, `Velocity Cross Fade` e chave individual **`Element Insertion Effect Sw` (`41 ee 11`: `0 = thru`, `1 = ins`)**.
     - Assim, dentro de **uma única `User Voice`**, construímos timbres híbridos completos:
       - **Elements 1–4**: Piano Acústico CFX / Felt Piano / Vintage '74 Rhodes passando pelo `Insertion Effect A` (`ins = 1`, ex.: `Damper Resonance` ou `VCM Phaser Stereo`).
       - **Elements 5–8**: *Warm Analog Pad*, *Symphonic Strings* ou *FM DX7 Legend Tines* com `ins = 0 (thru)`, desviando do efeito do piano e indo direto para o `REV-X Hall`.
     - Quando o botão **`[LAYER]` (`Part 1 + Part 2`)** do painel é acionado, somam-se **até 16 Elements simultâneos** e **2 Insertion Effects independentes**.
  2. **Pilar 2 — `Modulation Wheel (MW)` Transformada em "Slider Físico de Layer"**:
     - Em timbres de Piano/EP/Worship, a `Modulation Wheel (Source = 1, CC#1)` **não aplica vibrato (`LFO PMD = 0`)**.
     - Usamos a **Matriz de 6 `Controller Sets` (`40 06 00..17`) + Máscara Binária por Elemento (`Controller Set Element Sw` em `41 ee 12..13`)** para ligar `MW (Source = 1)` ao **`Element Level` (`Dest = 73`)** e ao **`Filter Cutoff` (`Dest = 98`)** **exclusivamente nos Elements da camada secundária (Elements 5–8)**!
     - Além disso, no modo `[LAYER]` (`Part 1 + Part 2`), configuramos `Receive MW = OFF` na `Part 1` (`37 00 20` bit 3 = `0`) e `Receive MW = ON` na `Part 2`, permitindo controlar o volume/filtro da `Part 2` de 0% a 100% pela roda de modulação sem alterar a `Part 1`.
  3. **Pilar 3 — `Knobs [C] (ASSIGN 1)` e `[D] (ASSIGN 2)` como "Macro-Knobs"**:
     - Mapeados nos `Controller Sets` (`Source = 8` e `Source = 9`) com profundidades bipolares (`-64..+63`) para controlar abertura de tampa/feltro (`Cutoff` dos Elements 1–4), intensidade do `Insertion Effect A` (`Dest 1..16`) e ambiência `REV-X Hall` (`Dest 66`), operando conjuntamente quando `[PART 1-2 LINK]` (`36 00 44 = 1`) está ativo.

### 1.4. Onde os Timbres São Salvos e Garantia de Zero Sobrescrita de Timbres Originais
- **Alinhamento do Usuário**: *"Onde os timbres serão salvos? Vai ser necessário sobrescrever algum timbre original?"*
- **Resposta e Governança Implementada (`AGENTS.md` e `src/mx61_cli.py`)**:
  - **Nenhum timbre original de fábrica jamais é sobrescrito**:
    1. Os **1.106 timbres de fábrica (`Preset Voices`, `PRE1..PRE8` e `GM`)** estão gravados em memória **ROM somente-leitura** — é fisicamente impossível apagá-los.
    2. O MX61 possui um banco dedicado de **128 `User Voices` (`U001..U128`, `MSB=63, LSB=8, PC=0..127`, endereço SysEx Bulk `0E 0A 00..7F`)** que **vem 100% vazio de fábrica** (todos os 128 slots vêm preenchidos apenas com um timbre neutro chamado **`Initialize`**).
    3. Todos os novos timbres de 8 Elements são salvos nesses slots vazios `Initialize` (`U001..U128`).
    4. Para ouvir e calibrar antes de salvar na memória Flash, a CLI injeta os timbres diretamente na memória **RAM volátil (`Normal Voice Edit Buffer 0E 0F 00`, `Mixing Part Voice Edit Buffer 0E 30 pp` e `Performance Edit Buffer 0E 5F 00`)**. Basta trocar de timbre ou desligar o teclado para o buffer volátil sumir sem deixar rastro.
    5. Antes de qualquer gravação definitiva, o comando `full-backup` salva toda a memória de usuário em `backups/full_initial/` e os comandos `store-voice` / `store-perf` geram snapshots automáticos de rollback em `backups/snapshots/`.

---

## 2. Estado Atual do Código e Presets (`bchoelz/mx61`)

Tudo abaixo já está implementado, testado offline e sincronizado no branch `main`:

| Arquivo / Diretório | Estado | Descrição |
| :--- | :---: | :--- |
| `docs/ARC-001-ANL-v1.0-estrategia-engenharia-mx61.md` | ✅ Concluído | Documento completo de arquitetura, comparativo PX-5S vs. MX61 e mapa de endereços SysEx. |
| `docs/*.pdf` (4 manuais) | ✅ Concluído | *Owner's Manual*, *Reference Manual*, *Data List* e *Synthesizer Parameter Manual*. |
| `src/mx61_sysex.py` | ✅ Concluído | Codec binário SysEx (`7F 17`), checksum Yamaha, `Mx61VoicePatch` (20 blocos / 8 Elements / 6 Controller Sets) e `Mx61PerformancePatch` (37 blocos / 16 Parts / Master EQ 5 bandas). |
| `src/winmm_bridge.cs` | ✅ Concluído | Ponte nativa Windows C# (`winmm.dll`) com detecção prioritária de `Yamaha MX49/MX61-1` (MIDI Out/In) e `Yamaha MX49/MX61` / `Steinberg` (USB-Audio In/Out). |
| `src/midi_bridge.py` | ✅ Concluído | Orquestrador Python/WSL2 para transações SysEx, `ping`, `full-backup`, `scan-slots`, `check-touch` e captura de sonda acústica de 61 teclas (`C1..C6`). |
| `src/mx61_profiles.py` | ✅ Concluído | 6 perfis completos (`yamaha_factory_ap`, `cfx_concert_grand`, `cfx_concert_pad_mw`, `sk_ex_warm_grand`, `nord_felt_worship_mw`, `rhodes_74_dyno_mw`). |
| `src/acoustic_analyzer.py` | ✅ Concluído | Analisador espectral de 7 bandas + Avaliador Fuzzy/Pareto mapeado para o Master EQ Paramétrico de 5 Bandas (`Low`, `Low-Mid`, `Mid`, `High-Mid`, `High` com `Q`). |
| `src/mx61_cli.py` | ✅ Concluído | CLI completa com 12 subcomandos (`list-profiles`, `export-syx`, `ping`, `full-backup`, `restore-backup`, `scan-slots`, `inspect-preset`, `check-touch`, `preview`, `store-voice`, `store-perf`, `analyze-wav`, `auto-calibrate`, `download-ref`). |
| `presets/*.syx` (24 arquivos) | ✅ Concluído | Pacotes SysEx prontos para *preview* em RAM (`*_editbuf.syx`) e gravação em `U001..U005` / `P001..P005`. |
| `captures/ref_*.wav` (4 arquivos) | ✅ Concluído | Referências acústicas (`ref_yamaha_cfx.wav`, `ref_kawai_sk_ex.wav`, `ref_nord_white_grand_soft.wav`, `ref_kurzweil_stage_grand.wav`). |

---

## 3. Roteiro Passo a Passo para o Próximo Agente / Terminal (Com o MX61 Conectado no Notebook)

Quando este repositório for aberto no terminal do notebook conectado via USB ao **Yamaha MX61**, siga exatamente esta sequência operacional:

### Passo 1 — Conferir Configuração MIDI no Painel do MX61
No painel físico do teclado, pressione **`[UTILITY]`** → navegue até **`02:MIDI`** e confirme:
- `MIDI IN/OUT` = **`USB`**
- `DeviceNo.` = **`all`** (ou `1`)
- `RcvBulk` = **`on`**

### Passo 2 — Testar Comunicação USB-MIDI (Porta 1) e Interface USB-Audio Integrada
```bash
python3 src/mx61_cli.py ping
```
- **O que validar**:
  - Verificar se a porta MIDI `Yamaha MX49/MX61-1` e o dispositivo de gravação de áudio USB `Yamaha MX49/MX61` (ou `Steinberg`) aparecem listados em `devices`.
  - Confirmar se `connected: true` e se o MX61 respondeu ao `Identity Request` e ao dump do `Performance Edit Buffer`.

### Passo 3 — Executar o Backup Inicial Imutável e Escanear os Slots `Initialize`
```bash
python3 src/mx61_cli.py full-backup
python3 src/mx61_cli.py scan-slots --start 1 --end 32
```
- **O que validar**:
  - Confirmar que `backups/full_initial/` salvou `system.syx`, `user_voices/U001..U128.syx`, `user_drums/UD01..UD08.syx`, `performances/P001..P128.syx` e `manifest.json`.
  - Verificar a lista `empty_initialize_slots` (slots `U001..U128` que estão com o nome `"Initialize"`).

### Passo 4 — Inspecionar os Wave Numbers Reais dos Presets de Fábrica do MX61
Como os `Wave Numbers` (`1..1566`) das tabelas internas do Motif XS/MX61 variam conforme a categoria, antes de calibrar ou gravar cada perfil, inspecione os Presets de fábrica de referência diretamente do hardware para usar os `Wave Numbers` exatos da ROM nas nossas `User Voices` de 8 Elements:
```bash
# Inspecionar PRE1:001 (Full Concert Grand), PRE1:019 (Vintage '74) e PRE5:001 (Warm Pad)
python3 src/mx61_cli.py inspect-preset --bank 1 --program 1
python3 src/mx61_cli.py inspect-preset --bank 1 --program 19
python3 src/mx61_cli.py inspect-preset --bank 5 --program 1
```
- **Ação importante para o agente**: Use o dump retornado por `inspect-preset` (ou `bridge.fetch_voice_patch(preset_bank_1_to_8=..., preset_program_0_to_127=...)`) como `base_patch` real ou atualize as constantes `WAVE_*` em `src/mx61_profiles.py` com os números exatos lidos da ROM do MX61!

### Passo 5 — Medir o Toque Físico do Usuário nas 61 Teclas e Testar `preview` na RAM
```bash
# Medir faixa real de velocidade (vel_min..vel_max) e testar a Roda de Modulação (CC#1)
python3 src/mx61_cli.py check-touch --duration 8

# Enviar o perfil híbrido CFX + Warm Pad na Modulation Wheel para o Edit Buffer volátil (RAM)
python3 src/mx61_cli.py preview --profile cfx_concert_pad_mw
```

### Passo 6 — Rodar a Calibração Fechada via USB-Audio Digital e Gravar nos Slots `U001..U005`
```bash
# Calibrar o Master EQ de 5 bandas e Cutoff/Sustain via captura digital USB-Audio contra a referência CFX
python3 src/mx61_cli.py auto-calibrate --profile cfx_concert_grand --ref captures/ref_yamaha_cfx.wav --iterations 3

# Salvar os timbres aprovados pelo usuário nos slots vazios User Voice U001..U005
python3 src/mx61_cli.py store-voice --profile cfx_concert_grand --slot 1
python3 src/mx61_cli.py store-voice --profile cfx_concert_pad_mw --slot 2
python3 src/mx61_cli.py store-voice --profile sk_ex_warm_grand --slot 3
python3 src/mx61_cli.py store-voice --profile nord_felt_worship_mw --slot 4
python3 src/mx61_cli.py store-voice --profile rhodes_74_dyno_mw --slot 5
```
