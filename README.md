# Yamaha MX61 — Suíte de Engenharia Acústica, Síntese AWM2 (8 Elements) & Calibração USB-MIDI/USB-Audio

Suíte de engenharia reversa, síntese avançada **AWM2 (motor Motif XS de 8 Elements)**, controle **MIDI SysEx (`Model ID = 7F 17`)** e calibração acústica **Hardware-in-the-Loop (via interface USB-Audio digital integrada do MX61)** para o sintetizador **Yamaha MX61**.

Este projeto evolui a metodologia desenvolvida em [`bchoelz/px5s`](https://github.com/bchoelz/px5s), adaptando toda a arquitetura para as características físicas e eletrônicas do **Yamaha MX61**:
1. **Teclado de 61 teclas Synth-Action (`C1–C6`, notas `36..96`)**: Calibração de curva de velocidade global (`VelCurve`), `Velocity Sensitivity Depth/Offset` por Parte/Elemento e `Velocity Cross Fade` suave entre camadas dinâmicas.
2. **Interface USB-Audio 2-In/2-Out Integrada (`USB [TO HOST]`)**: Captura digital *bit-perfect* pós-`Master EQ` diretamente pelo cabo USB do MX61 (sem necessidade de interface de áudio externa).
3. **Superação da Falta de Sliders Físicos e do Limite de Layer no Painel (`Part 1 + Part 2`)**:
   - **Multi-Layer Interno nos 8 Elements (`User Voice`)**: Cada `User Voice` (`U001..U128`) comporta até **8 Elements independentes** (qualquer uma das `1.566 Waveforms` da ROM de 166 MB do Motif XS, com filtro, envelope, *Breakpoint Scaling* e chave `Insertion Effect Thru/Ins` por Elemento). Assim, `Part 1 + Part 2` (`[LAYER]`) entrega até **16 Elements simultâneos**.
   - **`Modulation Wheel` como "Slider Físico de Layer"**: Mapeamento via **Matriz de 6 `Controller Sets` (`40 06 00..17`) + máscara por Elemento (`41 ee 12..13`)** para que a Roda de Modulação controle o volume (`Dest 73`) e a abertura de filtro (`Dest 98`) exclusivamente das camadas secundárias (ex.: Pad/Strings/Shimmer nos Elements 5–8 ou na `Part 2`), mantendo o Piano principal intacto.
   - **`Knobs [C] (ASSIGN 1)` e `[D] (ASSIGN 2)` como "Macro-Knobs"**: Controle simultâneo de até 6 parâmetros com curvas positivas ou negativas (*crossfade* entre timbres, `Damper Resonance`, compressão VCM e ambiência `REV-X Hall`).
4. **Zero Sobrescrita de Timbres Originais**:
   - Os **1.106 timbres originais (`Preset Voices`)** residem em memória ROM somente-leitura.
   - Os **128 slots `User Voice` (`U001..U128`)** vêm **100% vazios de fábrica (`Initialize`)**, permitindo salvar todos os novos timbres sem apagar nada original.
   - Testes A/B em tempo real são injetados diretamente nos **`Edit Buffers` voláteis de RAM (`0E 0F 00` / `0E 5F 00`)** antes de qualquer gravação em memória Flash.

---

## Documentação e Manuais Oficiais (`docs/`)

- [ARC-001-ANL-v1.0-estrategia-engenharia-mx61.md](docs/ARC-001-ANL-v1.0-estrategia-engenharia-mx61.md) — Avaliação do projeto `px5s`, comparativo arquitetural PX-5S vs. MX61, mapa completo de endereços MIDI SysEx e estratégia em 4 fases.
- [mx49mx61_en_om_b0.pdf](docs/mx49mx61_en_om_b0.pdf) — *Yamaha MX49/MX61 Owner's Manual (Rev. B0)*.
- [mx49mx61mx88_en_rm_b0.pdf](docs/mx49mx61mx88_en_rm_b0.pdf) — *Yamaha MX49/MX61/MX88 Reference Manual (Rev. B0)*.
- [mx49mx61_en_dl_a0.pdf](docs/mx49mx61_en_dl_a0.pdf) — *Yamaha MX49/MX61 Data List & MIDI SysEx Tables (Rev. A0)*.
- [mx49mx61synth_en_pm_a0.pdf](docs/mx49mx61synth_en_pm_a0.pdf) — *Yamaha Synthesizer Parameter Manual (Rev. A0)*.

---

## Estrutura do Repositório

```text
mx61/
├── AGENTS.md                  # Diretrizes operacionais e governança de memória/slots do MX61
├── README.md                  # Documentação principal do projeto
├── docs/                      # Manuais oficiais Yamaha (PDF) e documentos de arquitetura (ARC-*)
├── src/
│   ├── mx61_sysex.py          # Protocolo MIDI SysEx Yamaha MX61 (7F 17), Codec Voice (8 Elements) & Performance
│   ├── winmm_bridge.cs        # Ponte nativa Windows 11 C# (winmm.dll) para USB-MIDI Port 1 + USB-Audio
│   ├── midi_bridge.py         # Cliente Python de baixa latência (SysEx Bulk, Captura Digital USB e Telemetria)
│   ├── acoustic_analyzer.py   # Analisador espectral de 7 bandas + Motor de Inferência Fuzzy / Pareto
│   ├── mx61_profiles.py       # Perfis de síntese 8-Elements, Macro-Controllers (MW/Assign) e Master EQ
│   └── mx61_cli.py            # CLI interativa de backup, calibração acústica, geração de timbres e testes A/B
├── captures/                  # WAVs de referência acústica (CFX, SK-EX, Kurzweil, Nord)
├── presets/                   # Perfis exportados em SysEx (.syx) e JSON
└── backups/
    ├── full_initial/          # Backup imutável inicial das 128 User Voices, 128 Performances e System
    └── snapshots/             # Snapshots automáticos pré-gravação por slot
```

---

## Principais Comandos da CLI (`src/mx61_cli.py`)

```bash
# 1. Verificar conexão USB-MIDI (Port 1) e Interface USB-Audio integrada do MX61
python3 src/mx61_cli.py ping

# 2. Executar o Backup Completo Imutável (System + 128 User Voices + 128 Performances)
python3 src/mx61_cli.py full-backup

# 3. Escanear slots livres ('Initialize') em User Voices (U001..U128) e listar Performances
python3 src/mx61_cli.py scan-slots

# 4. Inspecionar os 8 Elements de qualquer Preset Voice de fábrica via Bulk Request
python3 src/mx61_cli.py inspect-preset --bank 1 --program 1

# 5. Medir a dinâmica real das 61 teclas sob o seu toque e calibrar VelCurve
python3 src/mx61_cli.py check-touch --duration 8

# 6. Testar um perfil no Edit Buffer (RAM, sem gravar na Flash) e comparar A/B com o original
python3 src/mx61_cli.py preview-profile --profile cfx_concert_pad_mw

# 7. Calibrar acusticamente via USB-Audio Digital + Lógica Fuzzy contra as referências
python3 src/mx61_cli.py auto-calibrate --profile cfx_concert_pad_mw

# 8. Salvar em um slot User Voice vazio (ex.: U001) com snapshot automático de rollback
python3 src/mx61_cli.py store-user-voice --profile cfx_concert_pad_mw --slot 1
```
