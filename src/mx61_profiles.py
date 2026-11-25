#!/usr/bin/env python3
"""
Yamaha MX61 Custom 8-Element Voice & 16-Part Performance Synthesis Catalog (`src/mx61_profiles.py`).

Implements the architectural strategy documented in `docs/ARC-001-ANL-v1.0-estrategia-engenharia-mx61.md`:
  1. Zero Overwrite of Factory Voices:
     - All 1,106 factory Preset Voices (`PRE1..PRE8`, `GM`) live in read-only ROM.
     - All 128 User Voice slots (`U001..U128`, `0E 0A 00..7F`, `MSB=63, LSB=8, PC=0..127`) ship
       100% empty (`Initialize`) from the factory — our custom Voices are stored there without
       ever overwriting a single original factory sound.
  2. Overcoming the Lack of Physical Sliders on the MX61:
     - Pillar 1 (Internal 8-Element Multi-Layering):
       Combines up to 8 independent AWM2 Elements inside a single `User Voice` (`41 00..07` / `42 00..07`).
       Elements 1..4 form the primary acoustic instrument (with `Element Insertion Effect Sw = ON` ->
       `Damper Resonance`, `VCM Compressor 376`, or `VCM Phaser Stereo`), while Elements 5..8 form the
       complementary layer (`Warm Pad`, `Strings`, `Felt Body`, or `FM DX Tines`) with `Insertion Effect Sw = OFF`
       (`thru` straight to `REV-X Hall`).
     - Pillar 2 (`Modulation Wheel` as Dedicated Layer Fader):
       Uses the 6-slot `Controller Set` matrix (`40 06 00..17`) + per-Element bitmask (`41 ee 12..13`)
       to bind `MW (Source = 1)` exclusively to `Element Level (Dest = 73)` and `Filter Cutoff (Dest = 98)`
       on the secondary Elements (`Elements 5..8`), leaving Elements 1..4 completely untouched by the wheel!
       Also configures `Part 2` in Performance `[LAYER]` mode with `Receive MW = OFF` on `Part 1` and
       `Receive MW = ON` on `Part 2`.
     - Pillar 3 (`Knobs [C] ASSIGN 1` & `[D] ASSIGN 2` as Macro-Knobs):
       Maps `ASSIGN 1 (Source = 8)` and `ASSIGN 2 (Source = 9)` across multiple synthesis destinations
       with bipolar depth (`-64..+63`) for acoustic body morphing and ambient bloom.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from mx61_sysex import (
    CTRL_DEST_AEG_RELEASE,
    CTRL_DEST_CHORUS_SEND,
    CTRL_DEST_CUTOFF,
    CTRL_DEST_ELEM_LEVEL,
    CTRL_DEST_INS_PARAM_1,
    CTRL_DEST_REVERB_SEND,
    CTRL_SRC_ASSIGN1,
    CTRL_SRC_ASSIGN2,
    CTRL_SRC_MW,
    FX_DAMPER_RESONANCE,
    FX_REV_X_HALL,
    FX_SPX_CHORUS,
    FX_SYMPHONIC,
    FX_VCM_COMPRESSOR_376,
    FX_VCM_EQ_501,
    FX_VCM_PHASER_STEREO,
    Mx61PerformancePatch,
    Mx61VoicePatch,
    XA_KEY_OFF,
    XA_NORMAL,
    pack_u14,
)

# Master EQ Frequency Table #3 Indices (`Data List` p. 59-60)
EQ_FREQ_80HZ = 0x08
EQ_FREQ_100HZ = 0x0A
EQ_FREQ_125HZ = 0x0C
EQ_FREQ_160HZ = 0x0E
EQ_FREQ_200HZ = 0x10
EQ_FREQ_250HZ = 0x12
EQ_FREQ_315HZ = 0x14
EQ_FREQ_400HZ = 0x16
EQ_FREQ_500HZ = 0x18
EQ_FREQ_630HZ = 0x1A
EQ_FREQ_800HZ = 0x1C
EQ_FREQ_1KHZ = 0x1E
EQ_FREQ_1_6KHZ = 0x22
EQ_FREQ_2KHZ = 0x24
EQ_FREQ_2_5KHZ = 0x26
EQ_FREQ_3_2KHZ = 0x28
EQ_FREQ_4KHZ = 0x2A
EQ_FREQ_5KHZ = 0x2C
EQ_FREQ_6_3KHZ = 0x2E
EQ_FREQ_8KHZ = 0x30
EQ_FREQ_10KHZ = 0x32
EQ_FREQ_12_5KHZ = 0x34

# Representative Motif XS / MX61 ROM Waveforms (`Data List` Wave List)
WAVE_CFX_ST_SOFT_L = 1       # Acoustic Grand Soft Stereo L
WAVE_CFX_ST_SOFT_R = 2       # Acoustic Grand Soft Stereo R
WAVE_CFX_ST_MED_L = 3        # Acoustic Grand Medium Stereo L
WAVE_CFX_ST_MED_R = 4        # Acoustic Grand Medium Stereo R
WAVE_CFX_ST_HARD_L = 5       # Acoustic Grand Hard Stereo L
WAVE_CFX_ST_HARD_R = 6       # Acoustic Grand Hard Stereo R
WAVE_PIANO_KEYOFF = 19       # Key-Off Damper Noise
WAVE_WARM_SOUNDBOARD = 11    # Warm Woody Grand Body
WAVE_RHODES_SOFT = 77        # Vintage 74 Suitcase Soft
WAVE_RHODES_MED = 79         # Vintage 74 Suitcase Med
WAVE_RHODES_DYNO = 83        # Vintage 74 Suitcase Bark/Dyno
WAVE_DX_FM_TINE = 118        # FM DX7 Legend Tine
WAVE_WARM_ANALOG_PAD = 712   # Warm Analog OB/Prophet Pad
WAVE_LUSH_STRINGS = 465      # Symphonic Ensemble Strings


@dataclass
class ElementSpec:
    """Declarative specification for one of the 8 Elements (`0..7`) in an `Mx61VoicePatch`."""
    index: int
    enabled: bool = True
    wave_number: int = WAVE_CFX_ST_MED_L
    xa_control: int = XA_NORMAL
    pan: int = 0                    # -63 (L) .. 0 (C) .. +63 (R)
    note_low: int = 0
    note_high: int = 127
    vel_low: int = 1
    vel_high: int = 127
    vel_crossfade: int = 0
    insert_fx_on: bool = True
    half_damper_on: bool = True
    half_damper_time: int = 68
    level: int = 120
    level_vel_sens: int = 24        # -64..+63
    aeg_attack: int = 0
    aeg_decay1: int = 86
    aeg_decay2: int = 96
    aeg_release: int = 72
    aeg_decay1_level: int = 110
    aeg_decay2_level: int = 0
    coarse_tune: int = 0
    fine_tune: int = 0
    filter_type: int = 0            # 0 = LPF24D
    filter_cutoff: int = 128        # 0..255
    filter_cutoff_vel_sens: int = 16
    filter_resonance: int = 16      # 8..71
    level_bp_notes: Tuple[int, int, int, int] = (36, 54, 72, 90)
    level_bp_offsets: Tuple[int, int, int, int] = (0, 0, 0, 0)
    filter_bp_notes: Tuple[int, int, int, int] = (36, 54, 72, 90)
    filter_bp_offsets: Tuple[int, int, int, int] = (0, 0, 0, 0)


@dataclass
class ControllerSetSpec:
    """Declarative specification for one of the 6 Controller Sets (`1..6`) in a Voice."""
    set_index_1_to_6: int
    source: int
    destination: int
    depth: int
    active_elements_0_to_7: Sequence[int]


@dataclass
class MasterEqBandSpec:
    """Specification for one of the 5 Parametric Master EQ bands (`0..4`)."""
    freq_idx: int
    gain_db: int
    q_x10: int = 10                 # 10 = Q 1.0
    shape_peaking: bool = True


@dataclass
class Mx61AcousticProfile:
    """
    Complete synthesis & performance profile for the Yamaha MX61:
      - Can be compiled into a 22-packet `Mx61VoicePatch` Bulk Dump (for `User Voice U001..U128`
        or volatile `Normal Voice Edit Buffer 0E 0F 00`).
      - Can be compiled into a 39-packet `Mx61PerformancePatch` Bulk Dump (for `User Performance 001..128`
        or volatile `Performance Edit Buffer 0E 5F 00`) with 5-Band Parametric Master EQ,
        `REV-X Hall`, and `[LAYER]` (`Part 1 + Part 2`) pre-configured.
    """
    profile_id: str
    voice_name: str                 # 10 ASCII chars max on MX61 LCD
    performance_name: str           # 10 ASCII chars max on MX61 LCD
    category_id: int                # 0=AP, 1=KB, 9=PAD
    description: str

    # Base Preset Voice (`MSB=63, LSB=0..7, PC=0..127`) used for Part 1 & Part 2 in Performance
    base_preset_bank_1_to_8: int = 1
    base_preset_program_0_to_127: int = 0  # PRE1:001 Full Concert Grand
    layer_part2_bank_msb: int = 63
    layer_part2_bank_lsb: int = 4          # PRE5 (Pad/Synth)
    layer_part2_program_0_to_127: int = 0  # Warm Pad
    enable_performance_layer: bool = False
    part2_initial_volume: int = 78
    part2_mw_only: bool = True

    # Voice Insertion Effect A (`40 03 00`)
    insertion_fx_type: Tuple[int, int] = FX_DAMPER_RESONANCE
    insertion_fx_preset: int = 0
    insertion_fx_params: Dict[int, int] = field(default_factory=dict)

    # 5-Band Parametric Master EQ (`36 10 00..13`)
    eq_low: MasterEqBandSpec = field(default_factory=lambda: MasterEqBandSpec(EQ_FREQ_125HZ, 0, 7, False))
    eq_lowmid: MasterEqBandSpec = field(default_factory=lambda: MasterEqBandSpec(EQ_FREQ_315HZ, 0, 14, True))
    eq_mid: MasterEqBandSpec = field(default_factory=lambda: MasterEqBandSpec(EQ_FREQ_630HZ, 0, 18, True))
    eq_himid: MasterEqBandSpec = field(default_factory=lambda: MasterEqBandSpec(EQ_FREQ_2_5KHZ, 0, 12, True))
    eq_high: MasterEqBandSpec = field(default_factory=lambda: MasterEqBandSpec(EQ_FREQ_8KHZ, 0, 7, False))

    # System Reverb (`REV-X Hall`) & Chorus
    reverb_send_part1: int = 38
    reverb_send_part2: int = 58
    chorus_send_part1: int = 0
    chorus_send_part2: int = 24

    # Part 1 Quick Offset Shaping (`37 00 23..2E`, signed -64..+63)
    part1_cutoff_offset: int = 0
    part1_resonance_offset: int = 0
    part1_attack_offset: int = 0
    part1_decay_offset: int = 0
    part1_release_offset: int = 0
    part1_vel_sens_depth: int = 64
    part1_vel_sens_offset: int = 64

    # 8 Elements (`41 00..07` & `42 00..07`) and 6 Controller Sets (`40 06 00..17`)
    elements: List[ElementSpec] = field(default_factory=list)
    controller_sets: List[ControllerSetSpec] = field(default_factory=list)

    # Recommended User Slot (None = auto-assign first `Initialize` slot found by `scan-slots`)
    recommended_user_voice_slot_1_to_128: Optional[int] = None
    recommended_performance_slot_1_to_128: Optional[int] = None

    def build_voice_patch(self, base_patch: Optional[Mx61VoicePatch] = None) -> Mx61VoicePatch:
        """
        Build a complete 20-block `Mx61VoicePatch` (Normal Voice) ready to send to the
        Normal Voice Edit Buffer (`0E 0F 00`), Mixing Part Edit Buffer (`0E 30 pp`),
        or any User Voice slot `U001..U128` (`0E 0A 00..7F`).
        """
        patch = base_patch if base_patch is not None else Mx61VoicePatch()
        patch.name = self.voice_name
        patch.category_id = self.category_id
        patch.volume = 120
        patch.common[0x1A] = 0x01  # Poly Mode = poly
        patch.common[0x40] = 0x40  # Pan = Center
        patch.common[0x41] = max(0, min(127, self.reverb_send_part1))
        patch.common[0x42] = max(0, min(127, self.chorus_send_part1))
        patch.common[0x4A] = 0x42  # Pitch Bend Upper = +2 semitones
        patch.common[0x4B] = 0x3E  # Pitch Bend Lower = -2 semitones

        patch.set_insertion_effect(
            fx_type=self.insertion_fx_type,
            preset=self.insertion_fx_preset,
            params=self.insertion_fx_params,
        )

        # Disable all 8 elements first unless specified in `self.elements`
        for ee in range(8):
            patch.configure_element(ee, enabled=False)

        for espec in self.elements:
            patch.configure_element(
                espec.index,
                enabled=espec.enabled,
                wave_number=espec.wave_number,
                xa_control=espec.xa_control,
                pan=espec.pan,
                note_low=espec.note_low,
                note_high=espec.note_high,
                vel_low=espec.vel_low,
                vel_high=espec.vel_high,
                vel_crossfade=espec.vel_crossfade,
                insert_fx_on=espec.insert_fx_on,
                half_damper_on=espec.half_damper_on,
                half_damper_time=espec.half_damper_time,
                level=espec.level,
                level_vel_sens=espec.level_vel_sens,
                aeg_attack=espec.aeg_attack,
                aeg_decay1=espec.aeg_decay1,
                aeg_decay2=espec.aeg_decay2,
                aeg_release=espec.aeg_release,
                aeg_decay1_level=espec.aeg_decay1_level,
                aeg_decay2_level=espec.aeg_decay2_level,
                coarse_tune=espec.coarse_tune,
                fine_tune=espec.fine_tune,
                filter_type=espec.filter_type,
                filter_cutoff=espec.filter_cutoff,
                filter_cutoff_vel_sens=espec.filter_cutoff_vel_sens,
                filter_resonance=espec.filter_resonance,
                level_bp_notes=espec.level_bp_notes,
                level_bp_offsets=espec.level_bp_offsets,
                filter_bp_notes=espec.filter_bp_notes,
                filter_bp_offsets=espec.filter_bp_offsets,
            )

        # Apply the 6 Controller Sets + per-Element bitmask (`41 ee 12..13`)
        for cspec in self.controller_sets:
            patch.set_controller_set(
                set_index_1_to_6=cspec.set_index_1_to_6,
                source=cspec.source,
                destination=cspec.destination,
                depth=cspec.depth,
                active_elements_0_to_7=cspec.active_elements_0_to_7,
            )

        return patch

    def build_performance_patch(
        self,
        user_voice_slot_1_to_128: Optional[int] = None,
        base_perf: Optional[Mx61PerformancePatch] = None,
    ) -> Mx61PerformancePatch:
        """
        Build a complete 37-block `Mx61PerformancePatch` with:
          - 5-Band Parametric Master EQ (`36 10 00..13`)
          - `REV-X Hall` System Reverb (`36 01 00`) & `Symphonic/SPX Chorus` (`36 02 00`)
          - Insertion Effects enabled on Parts 1..4 (`36 00 4C..4F`)
          - Part 1 pointing either to the custom `User Voice` (`MSB=63, LSB=8, PC=slot-1`)
            or to the base Preset Voice (`MSB=63, LSB=bank-1, PC=prog`)
          - Part 2 configured as the `[LAYER]` companion (`Receive MW = ON` on Part 2 and
            `Receive MW = OFF` on Part 1 when `part2_mw_only=True`).
        """
        perf = base_perf if base_perf is not None else Mx61PerformancePatch()
        perf.name = self.performance_name
        perf.common[0x1A] = 0x7F  # Performance Volume = 127
        perf.keyboard_mode = 1 if self.enable_performance_layer else 0  # 1 = Layer (Part 1 + Part 2)
        perf.split_point = 0x36   # F#2 (54)
        perf.part1_2_link = True  # Link Part 1 & Part 2 in Layer/Split

        # Enable Insertion Effects on Parts 1, 2, 3, and 4 simultaneously (4 simultaneous Insert FX!)
        perf.set_insertion_parts([0, 1, 2, 3])

        # System Reverb = REV-X Hall (01 00), Return = 96, Pan = Center
        perf.reverb[0x00] = FX_REV_X_HALL[0]
        perf.reverb[0x01] = FX_REV_X_HALL[1]
        perf.reverb[0x24] = 96
        perf.reverb[0x25] = 64

        # System Chorus = Symphonic (03 30), Return = 64, Pan = Center
        perf.chorus[0x00] = FX_SYMPHONIC[0]
        perf.chorus[0x01] = FX_SYMPHONIC[1]
        perf.chorus[0x24] = 64
        perf.chorus[0x25] = 64

        # 5-Band Parametric Master EQ (Low, Low-Mid, Mid, High-Mid, High)
        bands = [self.eq_low, self.eq_lowmid, self.eq_mid, self.eq_himid, self.eq_high]
        for idx, bspec in enumerate(bands):
            perf.set_master_eq_band(
                idx,
                gain_db=bspec.gain_db,
                freq_table_idx=bspec.freq_idx,
                q_x10=bspec.q_x10,
                shape_peaking=bspec.shape_peaking,
            )

        # Configure Part 1 (Main Voice)
        if user_voice_slot_1_to_128 is not None:
            p1_msb, p1_lsb, p1_pc = 63, 8, max(0, min(127, int(user_voice_slot_1_to_128) - 1))
        else:
            p1_msb = 63
            p1_lsb = max(0, min(7, int(self.base_preset_bank_1_to_8) - 1))
            p1_pc = max(0, min(127, int(self.base_preset_program_0_to_127)))

        perf.configure_part(
            0,
            bank_msb=p1_msb,
            bank_lsb=p1_lsb,
            program_0_to_127=p1_pc,
            receive_channel_0_to_15_or_7f=0,
            volume=124,
            pan=0,
            reverb_send=self.reverb_send_part1,
            chorus_send=self.chorus_send_part1,
            dry_level=127,
            note_low=0,
            note_high=127,
            vel_low=1,
            vel_high=127,
            vel_sens_depth=self.part1_vel_sens_depth,
            vel_sens_offset=self.part1_vel_sens_offset,
            cutoff_offset=self.part1_cutoff_offset,
            resonance_offset=self.part1_resonance_offset,
            aeg_attack_offset=self.part1_attack_offset,
            aeg_decay_offset=self.part1_decay_offset,
            aeg_release_offset=self.part1_release_offset,
            # When using internal 8-Element MW Layering inside Part 1, keep Receive MW = True on Part 1;
            # when using external Part 2 as the MW Layer, disable Receive MW on Part 1 so Part 1 never vibratos!
            receive_mw=(not self.part2_mw_only) or (not self.enable_performance_layer),
            receive_sustain=True,
            receive_assign1=True,
            receive_assign2=True,
        )

        # Configure Part 2 (Secondary Layer for Panel [LAYER] button)
        perf.configure_part(
            1,
            bank_msb=self.layer_part2_bank_msb,
            bank_lsb=self.layer_part2_bank_lsb,
            program_0_to_127=self.layer_part2_program_0_to_127,
            receive_channel_0_to_15_or_7f=0 if self.enable_performance_layer else 1,
            volume=self.part2_initial_volume,
            pan=0,
            reverb_send=self.reverb_send_part2,
            chorus_send=self.chorus_send_part2,
            dry_level=120,
            note_low=0,
            note_high=127,
            vel_low=1,
            vel_high=127,
            cutoff_offset=-10,
            aeg_attack_offset=14,
            aeg_release_offset=16,
            receive_mw=True,
            receive_sustain=True,
            receive_assign1=True,
            receive_assign2=True,
        )

        # Keep Parts 3..16 clean on channels 2..15
        for pp in range(2, 16):
            perf.configure_part(
                pp,
                bank_msb=63,
                bank_lsb=0,
                program_0_to_127=0,
                receive_channel_0_to_15_or_7f=pp,
                volume=100,
                pan=0,
                reverb_send=32,
                chorus_send=0,
                dry_level=127,
            )

        return perf


def _build_cfx_6_elements(
    *,
    cutoff_base: int = 138,
    body_level: int = 92,
    keyoff_level: int = 68,
     octave_4_5_lift_db: int = 5,
) -> List[ElementSpec]:
    """
    Build the 6 core Acoustic Grand Piano Elements (`Elements 1..6`):
      - Element 1: Stereo Soft/Med L (`vel 1..92`, crossfade `24`)
      - Element 2: Stereo Soft/Med R (`vel 1..92`, crossfade `24`)
      - Element 3: Stereo Hard/FF L (`vel 76..127`, crossfade `22`)
      - Element 4: Stereo Hard/FF R (`vel 76..127`, crossfade `22`)
      - Element 5: 9-ft Woody Soundboard Body (`note C1..C5`, warm LPF)
      - Element 6: Damper Key-Off Mechanical Resonance (`XA = Key-Off`)
    """
    bp_notes = (36, 54, 72, 90)  # C1, F#2, C4, F#5 (61-key MX61 register anchors)
    bp_lvl = (3, 1, octave_4_5_lift_db, octave_4_5_lift_db - 1)
    bp_flt = (-4, 0, octave_4_5_lift_db + 3, octave_4_5_lift_db + 4)

    return [
        ElementSpec(
            index=0,
            enabled=True,
            wave_number=WAVE_CFX_ST_MED_L,
            xa_control=XA_NORMAL,
            pan=-48,
            vel_low=1,
            vel_high=96,
            vel_crossfade=24,
            insert_fx_on=True,
            half_damper_on=True,
            level=122,
            level_vel_sens=24,
            aeg_attack=0,
            aeg_decay1=88,
            aeg_decay2=102,
            aeg_release=74,
            filter_cutoff=cutoff_base,
            filter_cutoff_vel_sens=18,
            level_bp_notes=bp_notes,
            level_bp_offsets=bp_lvl,
            filter_bp_notes=bp_notes,
            filter_bp_offsets=bp_flt,
        ),
        ElementSpec(
            index=1,
            enabled=True,
            wave_number=WAVE_CFX_ST_MED_R,
            xa_control=XA_NORMAL,
            pan=48,
            vel_low=1,
            vel_high=96,
            vel_crossfade=24,
            insert_fx_on=True,
            half_damper_on=True,
            level=122,
            level_vel_sens=24,
            aeg_attack=0,
            aeg_decay1=88,
            aeg_decay2=102,
            aeg_release=74,
            filter_cutoff=cutoff_base,
            filter_cutoff_vel_sens=18,
            level_bp_notes=bp_notes,
            level_bp_offsets=bp_lvl,
            filter_bp_notes=bp_notes,
            filter_bp_offsets=bp_flt,
        ),
        ElementSpec(
            index=2,
            enabled=True,
            wave_number=WAVE_CFX_ST_HARD_L,
            xa_control=XA_NORMAL,
            pan=-52,
            vel_low=74,
            vel_high=127,
            vel_crossfade=22,
            insert_fx_on=True,
            half_damper_on=True,
            level=125,
            level_vel_sens=28,
            aeg_attack=0,
            aeg_decay1=90,
            aeg_decay2=104,
            aeg_release=74,
            filter_cutoff=min(255, cutoff_base + 14),
            filter_cutoff_vel_sens=22,
            level_bp_notes=bp_notes,
            level_bp_offsets=bp_lvl,
            filter_bp_notes=bp_notes,
            filter_bp_offsets=bp_flt,
        ),
        ElementSpec(
            index=3,
            enabled=True,
            wave_number=WAVE_CFX_ST_HARD_R,
            xa_control=XA_NORMAL,
            pan=52,
            vel_low=74,
            vel_high=127,
            vel_crossfade=22,
            insert_fx_on=True,
            half_damper_on=True,
            level=125,
            level_vel_sens=28,
            aeg_attack=0,
            aeg_decay1=90,
            aeg_decay2=104,
            aeg_release=74,
            filter_cutoff=min(255, cutoff_base + 14),
            filter_cutoff_vel_sens=22,
            level_bp_notes=bp_notes,
            level_bp_offsets=bp_lvl,
            filter_bp_notes=bp_notes,
            filter_bp_offsets=bp_flt,
        ),
        ElementSpec(
            index=4,
            enabled=True,
            wave_number=WAVE_WARM_SOUNDBOARD,
            xa_control=XA_NORMAL,
            pan=-12,
            note_low=24,
            note_high=84,
            vel_low=1,
            vel_high=127,
            insert_fx_on=True,
            half_damper_on=True,
            level=body_level,
            level_vel_sens=18,
            aeg_attack=2,
            aeg_decay1=92,
            aeg_decay2=106,
            aeg_release=76,
            filter_cutoff=max(70, cutoff_base - 24),
            filter_cutoff_vel_sens=10,
            level_bp_notes=bp_notes,
            level_bp_offsets=(5, 4, 0, -6),
        ),
        ElementSpec(
            index=5,
            enabled=True,
            wave_number=WAVE_PIANO_KEYOFF,
            xa_control=XA_KEY_OFF,
            pan=0,
            vel_low=1,
            vel_high=127,
            insert_fx_on=True,
            half_damper_on=False,
            level=keyoff_level,
            level_vel_sens=12,
            aeg_attack=0,
            aeg_decay1=42,
            aeg_decay2=48,
            aeg_release=38,
            filter_cutoff=118,
        ),
    ]


PROFILES: Dict[str, Mx61AcousticProfile] = {
    "yamaha_factory_ap": Mx61AcousticProfile(
        profile_id="yamaha_factory_ap",
        voice_name="FullConGrd",
        performance_name="FactoryAP ",
        category_id=0,
        description=(
            "Baseline de fábrica do Yamaha MX61 (`PRE1:001(A01) Full Concert Grand`) com Master EQ flat (0 dB) "
            "para comparação A/B não-destrutiva via USB-Audio."
        ),
        base_preset_bank_1_to_8=1,
        base_preset_program_0_to_127=0,
        enable_performance_layer=False,
        insertion_fx_type=FX_DAMPER_RESONANCE,
        eq_low=MasterEqBandSpec(EQ_FREQ_125HZ, 0, 7, False),
        eq_lowmid=MasterEqBandSpec(EQ_FREQ_315HZ, 0, 10, True),
        eq_mid=MasterEqBandSpec(EQ_FREQ_630HZ, 0, 10, True),
        eq_himid=MasterEqBandSpec(EQ_FREQ_2_5KHZ, 0, 10, True),
        eq_high=MasterEqBandSpec(EQ_FREQ_8KHZ, 0, 7, False),
        reverb_send_part1=32,
        elements=_build_cfx_6_elements(cutoff_base=128, body_level=0, keyoff_level=60, octave_4_5_lift_db=0),
    ),

    "cfx_concert_grand": Mx61AcousticProfile(
        profile_id="cfx_concert_grand",
        voice_name="CFX ConcV1",
        performance_name="CFX9ftGrnd",
        category_id=0,
        description=(
            "Yamaha CFX 9-ft Concert Grand (6 Elements + Damper Resonance + Master EQ 5-Bandas Paramétrico: "
            "125Hz +3dB, 315Hz -2dB Q=1.8, 630Hz -2dB Q=2.0, 2.5kHz +2dB, 8.0kHz +2dB; "
            "Breakpoints BP3/BP4 abertos na 4ª e 5ª oitavas; ASSIGN 1 = Tampo/Felt, ASSIGN 2 = Ressonância/Hall)."
        ),
        recommended_user_voice_slot_1_to_128=1,
        recommended_performance_slot_1_to_128=1,
        base_preset_bank_1_to_8=1,
        base_preset_program_0_to_127=0,
        enable_performance_layer=False,
        insertion_fx_type=FX_DAMPER_RESONANCE,
        insertion_fx_preset=0,
        eq_low=MasterEqBandSpec(EQ_FREQ_125HZ, +3, 7, False),
        eq_lowmid=MasterEqBandSpec(EQ_FREQ_315HZ, -2, 18, True),
        eq_mid=MasterEqBandSpec(EQ_FREQ_630HZ, -2, 20, True),
        eq_himid=MasterEqBandSpec(EQ_FREQ_2_5KHZ, +2, 12, True),
        eq_high=MasterEqBandSpec(EQ_FREQ_8KHZ, +2, 7, False),
        reverb_send_part1=42,
        part1_cutoff_offset=4,
        part1_decay_offset=10,
        part1_release_offset=6,
        elements=_build_cfx_6_elements(cutoff_base=140, body_level=94, keyoff_level=70, octave_4_5_lift_db=5),
        controller_sets=[
            # MW (Source 1) -> Subtle Damper Resonance & Hall Bloom on Piano Elements
            ControllerSetSpec(1, CTRL_SRC_MW, CTRL_DEST_INS_PARAM_1, +28, [0, 1, 2, 3, 4]),
            ControllerSetSpec(2, CTRL_SRC_MW, CTRL_DEST_REVERB_SEND, +24, [0, 1, 2, 3, 4]),
            # Knob [C] ASSIGN 1 -> Lid / Felt Morph (Cutoff + Body Element 5 Balance)
            ControllerSetSpec(3, CTRL_SRC_ASSIGN1, CTRL_DEST_CUTOFF, +26, [0, 1, 2, 3]),
            ControllerSetSpec(4, CTRL_SRC_ASSIGN1, CTRL_DEST_ELEM_LEVEL, -18, [4]),
            # Knob [D] ASSIGN 2 -> Concert Hall Sustain & Envelope Release
            ControllerSetSpec(5, CTRL_SRC_ASSIGN2, CTRL_DEST_REVERB_SEND, +36, [0, 1, 2, 3, 4]),
            ControllerSetSpec(6, CTRL_SRC_ASSIGN2, CTRL_DEST_AEG_RELEASE, +18, [0, 1, 2, 3, 4]),
        ],
    ),

    "cfx_concert_pad_mw": Mx61AcousticProfile(
        profile_id="cfx_concert_pad_mw",
        voice_name="CFX+Pad MW",
        performance_name="CFX+Pad MW",
        category_id=0,
        description=(
            "Solução para ausência de Sliders no MX61: User Voice Híbrida de 8 Elementos onde Elements 1..4 "
            "são o Piano CFX Concert Grand (com Insert FX = Damper Resonance ON) e Elements 5..8 são Warm Pad "
            "+ Symphonic Strings (com Insert FX = OFF/thru) controlados de 0% a 100% exclusivamente pela "
            "Modulation Wheel (Dest 73 = Element Level + Dest 98 = Filter Cutoff nos Elements 5..8!)."
        ),
        recommended_user_voice_slot_1_to_128=2,
        recommended_performance_slot_1_to_128=2,
        base_preset_bank_1_to_8=1,
        base_preset_program_0_to_127=0,
        layer_part2_bank_msb=63,
        layer_part2_bank_lsb=4,
        layer_part2_program_0_to_127=0,  # Warm Pad on Part 2 when [LAYER] is pressed
        enable_performance_layer=True,
        part2_initial_volume=74,
        part2_mw_only=True,
        insertion_fx_type=FX_DAMPER_RESONANCE,
        eq_low=MasterEqBandSpec(EQ_FREQ_125HZ, +3, 7, False),
        eq_lowmid=MasterEqBandSpec(EQ_FREQ_315HZ, -3, 18, True),
        eq_mid=MasterEqBandSpec(EQ_FREQ_630HZ, -2, 18, True),
        eq_himid=MasterEqBandSpec(EQ_FREQ_2_5KHZ, +2, 12, True),
        eq_high=MasterEqBandSpec(EQ_FREQ_8KHZ, +2, 7, False),
        reverb_send_part1=44,
        reverb_send_part2=64,
        chorus_send_part2=32,
        part1_cutoff_offset=4,
        part1_decay_offset=10,
        elements=[
            *_build_cfx_6_elements(cutoff_base=140, body_level=90, keyoff_level=66, octave_4_5_lift_db=5)[:4],
            # Element 5: Warm Analog Pad L (Insert FX = OFF -> bypasses piano insert, controlled by MW!)
            ElementSpec(
                index=4,
                enabled=True,
                wave_number=WAVE_WARM_ANALOG_PAD,
                xa_control=XA_NORMAL,
                pan=-42,
                note_low=24,
                note_high=96,
                vel_low=1,
                vel_high=127,
                insert_fx_on=False,
                half_damper_on=False,
                level=38,
                level_vel_sens=8,
                aeg_attack=38,
                aeg_decay1=98,
                aeg_decay2=110,
                aeg_release=86,
                aeg_decay1_level=120,
                aeg_decay2_level=110,
                filter_cutoff=86,
                filter_cutoff_vel_sens=6,
            ),
            # Element 6: Warm Analog Pad R (Insert FX = OFF, controlled by MW!)
            ElementSpec(
                index=5,
                enabled=True,
                wave_number=WAVE_WARM_ANALOG_PAD,
                xa_control=XA_NORMAL,
                pan=42,
                note_low=24,
                note_high=96,
                vel_low=1,
                vel_high=127,
                insert_fx_on=False,
                half_damper_on=False,
                level=38,
                level_vel_sens=8,
                aeg_attack=38,
                aeg_decay1=98,
                aeg_decay2=110,
                aeg_release=86,
                aeg_decay1_level=120,
                aeg_decay2_level=110,
                fine_tune=4,
                filter_cutoff=86,
                filter_cutoff_vel_sens=6,
            ),
            # Element 7: Lush Symphonic Strings L (Insert FX = OFF, controlled by MW + ASSIGN 1!)
            ElementSpec(
                index=6,
                enabled=True,
                wave_number=WAVE_LUSH_STRINGS,
                xa_control=XA_NORMAL,
                pan=-50,
                note_low=36,
                note_high=96,
                vel_low=1,
                vel_high=127,
                insert_fx_on=False,
                half_damper_on=False,
                level=32,
                level_vel_sens=10,
                aeg_attack=44,
                aeg_decay1=100,
                aeg_decay2=112,
                aeg_release=88,
                aeg_decay1_level=122,
                aeg_decay2_level=112,
                filter_cutoff=82,
            ),
            # Element 8: Lush Symphonic Strings R (Insert FX = OFF, controlled by MW + ASSIGN 1!)
            ElementSpec(
                index=7,
                enabled=True,
                wave_number=WAVE_LUSH_STRINGS,
                xa_control=XA_NORMAL,
                pan=50,
                note_low=36,
                note_high=96,
                vel_low=1,
                vel_high=127,
                insert_fx_on=False,
                half_damper_on=False,
                level=32,
                level_vel_sens=10,
                aeg_attack=44,
                aeg_decay1=100,
                aeg_decay2=112,
                aeg_release=88,
                aeg_decay1_level=122,
                aeg_decay2_level=112,
                fine_tune=-4,
                filter_cutoff=82,
            ),
        ],
        controller_sets=[
            # PILLAR 2: Modulation Wheel (Source 1) acts as Dedicated Layer Fader for Elements 5..8 ONLY!
            ControllerSetSpec(1, CTRL_SRC_MW, CTRL_DEST_ELEM_LEVEL, +63, [4, 5, 6, 7]),
            ControllerSetSpec(2, CTRL_SRC_MW, CTRL_DEST_CUTOFF, +38, [4, 5, 6, 7]),
            # PILLAR 3: Knob [C] ASSIGN 1 morphs Pad/Strings Warmth vs. Piano Brightness
            ControllerSetSpec(3, CTRL_SRC_ASSIGN1, CTRL_DEST_CUTOFF, +32, [4, 5, 6, 7]),
            ControllerSetSpec(4, CTRL_SRC_ASSIGN1, CTRL_DEST_ELEM_LEVEL, +28, [6, 7]),
            # Knob [D] ASSIGN 2 controls Global REV-X Hall & Pad Release Tail
            ControllerSetSpec(5, CTRL_SRC_ASSIGN2, CTRL_DEST_REVERB_SEND, +42, [0, 1, 2, 3, 4, 5, 6, 7]),
            ControllerSetSpec(6, CTRL_SRC_ASSIGN2, CTRL_DEST_AEG_RELEASE, +24, [4, 5, 6, 7]),
        ],
    ),

    "sk_ex_warm_grand": Mx61AcousticProfile(
        profile_id="sk_ex_warm_grand",
        voice_name="SK-EX Warm",
        performance_name="KawaiSK-EX",
        category_id=0,
        description=(
            "Modelagem Kawai Shigeru SK-EX Concert Grand calibrada contra `ref_kawai_sk_ex.wav`: "
            "timbre amadeirado, denso em 160-350 Hz, ataque aveludado sem aspereza metálica e cauda longa."
        ),
        recommended_user_voice_slot_1_to_128=3,
        recommended_performance_slot_1_to_128=3,
        base_preset_bank_1_to_8=1,
        base_preset_program_0_to_127=1,  # Warm Grand / Glasgow
        enable_performance_layer=False,
        insertion_fx_type=FX_DAMPER_RESONANCE,
        eq_low=MasterEqBandSpec(EQ_FREQ_160HZ, +3, 8, False),
        eq_lowmid=MasterEqBandSpec(EQ_FREQ_250HZ, +1, 12, True),
        eq_mid=MasterEqBandSpec(EQ_FREQ_630HZ, -2, 18, True),
        eq_himid=MasterEqBandSpec(EQ_FREQ_2KHZ, +1, 12, True),
        eq_high=MasterEqBandSpec(EQ_FREQ_6_3KHZ, +1, 7, False),
        reverb_send_part1=46,
        part1_cutoff_offset=-3,
        part1_decay_offset=12,
        part1_release_offset=8,
        elements=_build_cfx_6_elements(cutoff_base=126, body_level=104, keyoff_level=64, octave_4_5_lift_db=4),
        controller_sets=[
            ControllerSetSpec(1, CTRL_SRC_MW, CTRL_DEST_INS_PARAM_1, +30, [0, 1, 2, 3, 4]),
            ControllerSetSpec(2, CTRL_SRC_ASSIGN1, CTRL_DEST_CUTOFF, +24, [0, 1, 2, 3, 4]),
            ControllerSetSpec(3, CTRL_SRC_ASSIGN2, CTRL_DEST_REVERB_SEND, +36, [0, 1, 2, 3, 4]),
        ],
    ),

    "nord_felt_worship_mw": Mx61AcousticProfile(
        profile_id="nord_felt_worship_mw",
        voice_name="NordFeltMW",
        performance_name="NordFeltMW",
        category_id=0,
        description=(
            "Nord White Grand Soft / Noire Felt Piano (Elements 1..4 com filtro suave de feltro e Damper Resonance) "
            "+ Atmosfera Shimmer/Warm Pad (Elements 5..8 em `thru`) controlada 100% pela Modulation Wheel."
        ),
        recommended_user_voice_slot_1_to_128=4,
        recommended_performance_slot_1_to_128=4,
        base_preset_bank_1_to_8=1,
        base_preset_program_0_to_127=4,  # Mellow Grand
        layer_part2_bank_msb=63,
        layer_part2_bank_lsb=4,
        layer_part2_program_0_to_127=2,
        enable_performance_layer=True,
        part2_initial_volume=72,
        part2_mw_only=True,
        insertion_fx_type=FX_DAMPER_RESONANCE,
        eq_low=MasterEqBandSpec(EQ_FREQ_125HZ, +3, 7, False),
        eq_lowmid=MasterEqBandSpec(EQ_FREQ_315HZ, -2, 16, True),
        eq_mid=MasterEqBandSpec(EQ_FREQ_800HZ, -3, 18, True),
        eq_himid=MasterEqBandSpec(EQ_FREQ_2_5KHZ, -1, 12, True),
        eq_high=MasterEqBandSpec(EQ_FREQ_8KHZ, +1, 7, False),
        reverb_send_part1=54,
        reverb_send_part2=72,
        part1_cutoff_offset=-8,
        part1_decay_offset=14,
        part1_release_offset=10,
        elements=[
            *_build_cfx_6_elements(cutoff_base=112, body_level=98, keyoff_level=74, octave_4_5_lift_db=4)[:4],
            ElementSpec(
                index=4,
                enabled=True,
                wave_number=WAVE_WARM_SOUNDBOARD,
                xa_control=XA_NORMAL,
                pan=0,
                note_low=24,
                note_high=88,
                insert_fx_on=True,
                half_damper_on=True,
                level=96,
                aeg_attack=2,
                aeg_decay1=96,
                aeg_decay2=108,
                aeg_release=78,
                filter_cutoff=96,
            ),
            ElementSpec(
                index=5,
                enabled=True,
                wave_number=WAVE_PIANO_KEYOFF,
                xa_control=XA_KEY_OFF,
                pan=0,
                insert_fx_on=True,
                half_damper_on=False,
                level=74,
                aeg_decay1=46,
                aeg_release=42,
                filter_cutoff=110,
            ),
            # Elements 7 & 8: Stereo Warm Ambient Pad on Modulation Wheel
            ElementSpec(
                index=6,
                enabled=True,
                wave_number=WAVE_WARM_ANALOG_PAD,
                xa_control=XA_NORMAL,
                pan=-46,
                insert_fx_on=False,
                half_damper_on=False,
                level=34,
                aeg_attack=42,
                aeg_decay1=102,
                aeg_decay2=114,
                aeg_release=90,
                aeg_decay1_level=122,
                aeg_decay2_level=114,
                filter_cutoff=78,
            ),
            ElementSpec(
                index=7,
                enabled=True,
                wave_number=WAVE_WARM_ANALOG_PAD,
                xa_control=XA_NORMAL,
                pan=46,
                insert_fx_on=False,
                half_damper_on=False,
                level=34,
                aeg_attack=42,
                aeg_decay1=102,
                aeg_decay2=114,
                aeg_release=90,
                aeg_decay1_level=122,
                aeg_decay2_level=114,
                fine_tune=5,
                filter_cutoff=78,
            ),
        ],
        controller_sets=[
            # MW controls Ambient Pad Level & Cutoff exclusively on Elements 7 & 8
            ControllerSetSpec(1, CTRL_SRC_MW, CTRL_DEST_ELEM_LEVEL, +63, [6, 7]),
            ControllerSetSpec(2, CTRL_SRC_MW, CTRL_DEST_CUTOFF, +40, [6, 7]),
            # ASSIGN 1 opens Felt Piano Filter from Intimate Felt to Open Studio Grand
            ControllerSetSpec(3, CTRL_SRC_ASSIGN1, CTRL_DEST_CUTOFF, +34, [0, 1, 2, 3, 4]),
            # ASSIGN 2 controls Lush REV-X Hall Send
            ControllerSetSpec(4, CTRL_SRC_ASSIGN2, CTRL_DEST_REVERB_SEND, +46, [0, 1, 2, 3, 4, 6, 7]),
        ],
    ),

    "rhodes_74_dyno_mw": Mx61AcousticProfile(
        profile_id="rhodes_74_dyno_mw",
        voice_name="74Rhod+DX ",
        performance_name="74Rhod+DX ",
        category_id=1,  # KB (Electric Piano)
        description=(
            "Vintage '74 Suitcase Rhodes (Elements 1..4 com `VCM Phaser Stereo` ON e bark dinâmico) "
            "+ FM DX7 Legend Tines & Warm Pad (Elements 5..8 em `thru`) controlados pela Modulation Wheel!"
        ),
        recommended_user_voice_slot_1_to_128=5,
        recommended_performance_slot_1_to_128=5,
        base_preset_bank_1_to_8=1,
        base_preset_program_0_to_127=18,  # Vintage '74
        layer_part2_bank_msb=63,
        layer_part2_bank_lsb=0,
        layer_part2_program_0_to_127=26,  # DX Legend
        enable_performance_layer=True,
        part2_initial_volume=68,
        part2_mw_only=True,
        insertion_fx_type=FX_VCM_PHASER_STEREO,
        eq_low=MasterEqBandSpec(EQ_FREQ_100HZ, +2, 7, False),
        eq_lowmid=MasterEqBandSpec(EQ_FREQ_315HZ, -2, 16, True),
        eq_mid=MasterEqBandSpec(EQ_FREQ_1KHZ, +2, 14, True),
        eq_himid=MasterEqBandSpec(EQ_FREQ_3_2KHZ, +3, 12, True),
        eq_high=MasterEqBandSpec(EQ_FREQ_10KHZ, +2, 7, False),
        reverb_send_part1=36,
        reverb_send_part2=48,
        chorus_send_part1=22,
        chorus_send_part2=38,
        elements=[
            # Elements 1..2: Rhodes Soft/Med Tine Body (VCM Phaser ON)
            ElementSpec(
                index=0,
                enabled=True,
                wave_number=WAVE_RHODES_SOFT,
                pan=-36,
                vel_low=1,
                vel_high=94,
                vel_crossfade=20,
                insert_fx_on=True,
                half_damper_on=True,
                level=120,
                aeg_decay1=86,
                aeg_decay2=98,
                aeg_release=68,
                filter_cutoff=134,
            ),
            ElementSpec(
                index=1,
                enabled=True,
                wave_number=WAVE_RHODES_MED,
                pan=36,
                vel_low=48,
                vel_high=112,
                vel_crossfade=22,
                insert_fx_on=True,
                half_damper_on=True,
                level=122,
                aeg_decay1=86,
                aeg_decay2=98,
                aeg_release=68,
                filter_cutoff=142,
            ),
            # Elements 3..4: Rhodes Dyno Bark on high velocity (VCM Phaser ON)
            ElementSpec(
                index=2,
                enabled=True,
                wave_number=WAVE_RHODES_DYNO,
                pan=-40,
                vel_low=96,
                vel_high=127,
                vel_crossfade=18,
                insert_fx_on=True,
                half_damper_on=True,
                level=125,
                aeg_decay1=82,
                aeg_decay2=94,
                aeg_release=66,
                filter_cutoff=168,
            ),
            ElementSpec(
                index=3,
                enabled=True,
                wave_number=WAVE_RHODES_DYNO,
                pan=40,
                vel_low=96,
                vel_high=127,
                vel_crossfade=18,
                insert_fx_on=True,
                half_damper_on=True,
                level=125,
                aeg_decay1=82,
                aeg_decay2=94,
                aeg_release=66,
                filter_cutoff=168,
            ),
            # Elements 5..6: FM DX7 Crystalline Tines (Insert FX = OFF -> clean stereo chorus, controlled by MW!)
            ElementSpec(
                index=4,
                enabled=True,
                wave_number=WAVE_DX_FM_TINE,
                pan=-44,
                vel_low=1,
                vel_high=127,
                insert_fx_on=False,
                half_damper_on=True,
                level=36,
                aeg_decay1=84,
                aeg_decay2=94,
                aeg_release=70,
                fine_tune=-3,
                filter_cutoff=144,
            ),
            ElementSpec(
                index=5,
                enabled=True,
                wave_number=WAVE_DX_FM_TINE,
                pan=44,
                vel_low=1,
                vel_high=127,
                insert_fx_on=False,
                half_damper_on=True,
                level=36,
                aeg_decay1=84,
                aeg_decay2=94,
                aeg_release=70,
                fine_tune=3,
                filter_cutoff=144,
            ),
            # Elements 7..8: Warm Analog Pad under-layer on MW
            ElementSpec(
                index=6,
                enabled=True,
                wave_number=WAVE_WARM_ANALOG_PAD,
                pan=-48,
                insert_fx_on=False,
                half_damper_on=False,
                level=30,
                aeg_attack=38,
                aeg_decay1=98,
                aeg_decay2=110,
                aeg_release=84,
                filter_cutoff=84,
            ),
            ElementSpec(
                index=7,
                enabled=True,
                wave_number=WAVE_WARM_ANALOG_PAD,
                pan=48,
                insert_fx_on=False,
                half_damper_on=False,
                level=30,
                aeg_attack=38,
                aeg_decay1=98,
                aeg_decay2=110,
                aeg_release=84,
                fine_tune=4,
                filter_cutoff=84,
            ),
        ],
        controller_sets=[
            # MW brings in FM DX7 Tines + Warm Pad (Elements 5..8)
            ControllerSetSpec(1, CTRL_SRC_MW, CTRL_DEST_ELEM_LEVEL, +63, [4, 5, 6, 7]),
            ControllerSetSpec(2, CTRL_SRC_MW, CTRL_DEST_CUTOFF, +30, [6, 7]),
            # ASSIGN 1 controls VCM Phaser Depth / Speed on Rhodes Elements 1..4
            ControllerSetSpec(3, CTRL_SRC_ASSIGN1, CTRL_DEST_INS_PARAM_1, +42, [0, 1, 2, 3]),
            # ASSIGN 2 controls Chorus + Reverb lushness
            ControllerSetSpec(4, CTRL_SRC_ASSIGN2, CTRL_DEST_CHORUS_SEND, +40, [0, 1, 2, 3, 4, 5]),
            ControllerSetSpec(5, CTRL_SRC_ASSIGN2, CTRL_DEST_REVERB_SEND, +34, [0, 1, 2, 3, 4, 5, 6, 7]),
        ],
    ),
}
