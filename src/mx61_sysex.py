#!/usr/bin/env python3
"""
Yamaha MX49/MX61 MIDI SysEx Protocol & Binary Patch Codec (`src/mx61_sysex.py`).

Implements the complete official specification from `mx49mx61_en_dl_a0.pdf` (pages 53-66)
for Model ID `7F 17` (Yamaha MX49/MX61):
  - Native Parameter Change (`F0 43 1n 7F 17 ah am al dd... F7`)
  - Native Parameter Request (`F0 43 3n 7F 17 ah am al F7`)
  - Native Bulk Dump (`F0 43 0n 7F 17 bh bl ah am al dd... cc F7`)
  - Native Bulk Dump Request (`F0 43 2n 7F 17 ah am al F7`)
  - Universal Identity Request / Reply (`F0 7E 7F 06 01 F7`)
  - High-level 8-Element Normal Voice (`40..42`) & 16-Part Performance (`36..38`) builders,
    including the 6-slot Controller Set Matrix (`40 06 00..17`) + Element Bitmask (`41 ee 12..13`)
    that turns the Modulation Wheel and Assignable Knobs into dedicated Layer Faders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple, Union

YAMAHA_MFG_ID = 0x43
MX_MODEL_ID_HI = 0x7F
MX_MODEL_ID_LO = 0x17

# Controller Set Sources (Data List p. 63)
CTRL_SRC_PB = 0x00
CTRL_SRC_MW = 0x01
CTRL_SRC_AT = 0x03
CTRL_SRC_FC1 = 0x04
CTRL_SRC_FS = 0x05
CTRL_SRC_RB = 0x06
CTRL_SRC_BC = 0x07
CTRL_SRC_ASSIGN1 = 0x08  # Knob [C] Function 3 (AKN1)
CTRL_SRC_ASSIGN2 = 0x09  # Knob [D] Function 3 (AKN2)
CTRL_SRC_FC2 = 0x0C
CTRL_SRC_AF1 = 0x0D      # Assignable Switch 1 (ASW1)
CTRL_SRC_AF2 = 0x0E      # Assignable Switch 2 (ASW2)

# Key Controller Set Destinations (Data List p. 52)
CTRL_DEST_OFF = 0
CTRL_DEST_INS_PARAM_1 = 1    # 1..16 = Insertion Effect A Parameter 1..16
CTRL_DEST_VOLUME = 65        # Common Voice Volume
CTRL_DEST_REVERB_SEND = 66   # Common Reverb Send
CTRL_DEST_CHORUS_SEND = 67   # Common Chorus Send
CTRL_DEST_LFO_SPEED = 68
CTRL_DEST_LFO_DEPTH1 = 69
CTRL_DEST_LFO_DEPTH2 = 70
CTRL_DEST_LFO_DEPTH3 = 71
CTRL_DEST_PORTA_TIME = 72
CTRL_DEST_ELEM_LEVEL = 73    # Element Level (per-Element via bitmask 41 ee 12..13!)
CTRL_DEST_ELEM_PAN = 74
CTRL_DEST_ELEM_DELAY = 75
CTRL_DEST_ELEM_LFO_SPEED = 76
CTRL_DEST_ELEM_LFO_PMD = 77
CTRL_DEST_ELEM_LFO_AMD = 78
CTRL_DEST_ELEM_LFO_FMD = 79
CTRL_DEST_COARSE_TUNE = 80
CTRL_DEST_FINE_TUNE = 81
CTRL_DEST_PEG_DEPTH = 82
CTRL_DEST_AEG_ATTACK = 88
CTRL_DEST_AEG_DECAY1 = 89
CTRL_DEST_AEG_DECAY2 = 90
CTRL_DEST_AEG_RELEASE = 91
CTRL_DEST_FEG_DEPTH = 92
CTRL_DEST_FEG_ATTACK = 94
CTRL_DEST_FEG_DECAY1 = 95
CTRL_DEST_FEG_RELEASE = 97
CTRL_DEST_CUTOFF = 98        # Element Filter Cutoff Frequency (per-Element!)
CTRL_DEST_RESONANCE = 99     # Element Filter Resonance (per-Element!)

# XA (eXpanded Articulation) Modes (Data List p. 63)
XA_NORMAL = 0
XA_LEGATO = 1
XA_KEY_OFF = 2
XA_WAVE_CYCLE = 3
XA_WAVE_RANDOM = 4
XA_ALL_AF_OFF = 5
XA_AF1_ON = 6
XA_AF2_ON = 7

# Voice Main Categories (Data List p. 62)
VOICE_CATEGORIES = {
    0: "AP",
    1: "KB",
    2: "ORG",
    3: "GTR",
    4: "BAS",
    5: "STR",
    6: "BRS",
    7: "WND",
    8: "LD",
    9: "PAD",
    10: "CMP",
    11: "CP",
    12: "DR",
    13: "SFX",
    14: "MFX",
    15: "ETH",
    17: "NoAsg",
}

# Popular Insertion / System Effect Types (MSB, LSB) from Data List p. 32
FX_THRU = (0x00, 0x00)
FX_REV_X_HALL = (0x01, 0x00)
FX_R3_HALL = (0x01, 0x01)
FX_SPX_HALL = (0x01, 0x02)
FX_REV_X_ROOM = (0x01, 0x10)
FX_R3_ROOM = (0x01, 0x11)
FX_SPX_ROOM = (0x01, 0x12)
FX_R3_PLATE = (0x01, 0x20)
FX_SPX_STAGE = (0x01, 0x30)
FX_CROSS_DELAY = (0x02, 0x00)
FX_TEMPO_CROSS_DELAY = (0x02, 0x10)
FX_TEMPO_DELAY_STEREO = (0x02, 0x28)
FX_G_CHORUS = (0x03, 0x00)
FX_2_MODULATOR = (0x03, 0x10)
FX_SPX_CHORUS = (0x03, 0x20)
FX_SYMPHONIC = (0x03, 0x30)
FX_ENSEMBLE_DETUNE = (0x03, 0x40)
FX_VCM_FLANGER = (0x04, 0x00)
FX_VCM_PHASER_MONO = (0x05, 0x00)
FX_VCM_PHASER_STEREO = (0x05, 0x10)
FX_AUTO_PAN = (0x06, 0x00)
FX_TREMOLO = (0x06, 0x10)
FX_ROTARY_SPEAKER = (0x06, 0x20)
FX_AMP_SIMULATOR_2 = (0x07, 0x10)
FX_COMP_DISTORTION = (0x07, 0x20)
FX_VCM_COMPRESSOR_376 = (0x08, 0x00)
FX_CLASSIC_COMPRESSOR = (0x08, 0x10)
FX_MULTI_BAND_COMP = (0x08, 0x20)
FX_VCM_AUTO_WAH = (0x0A, 0x00)
FX_VCM_TOUCH_WAH = (0x0A, 0x10)
FX_VCM_EQ_501 = (0x0D, 0x00)
FX_HARMONIC_ENHANCER = (0x0D, 0x10)
FX_DAMPER_RESONANCE = (0x0D, 0x30)
FX_PITCH_CHANGE = (0x0D, 0x40)
FX_EARLY_REFLECTION = (0x0D, 0x50)


def yamaha_checksum(body: Union[bytes, bytearray, Sequence[int]]) -> int:
    """
    Calculate the 7-bit Yamaha Bulk Dump checksum (`Data List` p. 55):
    `cc = (-sum(bh, bl, ah, am, al, data...)) & 0x7F`
    """
    return (-sum(int(b) & 0x7F for b in body)) & 0x7F


def pack_u14(val: int) -> Tuple[int, int]:
    """Pack an unsigned 14-bit integer into `(msb_7bit, lsb_7bit)`."""
    v = max(0, min(0x3FFF, int(val)))
    return (v >> 7) & 0x7F, v & 0x7F


def unpack_u14(msb: int, lsb: int) -> int:
    """Unpack `(msb_7bit, lsb_7bit)` into an unsigned 14-bit integer."""
    return ((int(msb) & 0x7F) << 7) | (int(lsb) & 0x7F)


def pack_signed_offset_14bit(offset: int) -> Tuple[int, int]:
    """
    Pack a signed offset (`-128..+127`, where `0` is encoded as `0x01 0x00` = `128`)
    used by Level Scaling Offset, Filter Cutoff Scaling Offset, PEG/FEG Level, etc.
    (`Data List` p. 64: Default `0` -> `01 00`).
    """
    raw = max(0, min(255, int(offset) + 128))
    return (raw >> 7) & 0x01, raw & 0x7F


def unpack_signed_offset_14bit(msb: int, lsb: int) -> int:
    """Unpack a 2-byte signed offset centered at `0x01 0x00` (`128` -> `0`)."""
    raw = ((int(msb) & 0x01) << 7) | (int(lsb) & 0x7F)
    return raw - 128


def build_identity_request(device_no: int = 0x7F) -> bytes:
    """Build Universal Device Inquiry (`F0 7E <dev> 06 01 F7`)."""
    return bytes([0xF0, 0x7E, device_no & 0x7F, 0x06, 0x01, 0xF7])


def build_gm_system_on() -> bytes:
    """Build Universal GM System On (`F0 7E 7F 09 01 F7`)."""
    return bytes([0xF0, 0x7E, 0x7F, 0x09, 0x01, 0xF7])


def build_master_volume_sysex(volume: int = 127) -> bytes:
    """Build Universal Realtime MIDI Master Volume (`F0 7F 7F 04 01 00 <mm> F7`)."""
    return bytes([0xF0, 0x7F, 0x7F, 0x04, 0x01, 0x00, max(0, min(127, int(volume))), 0xF7])


def build_param_change(
    ah: int,
    am: int,
    al: int,
    data: Union[int, bytes, bytearray, Sequence[int]],
    dev_num: int = 0,
) -> bytes:
    """
    Build a Yamaha MX61 Native Parameter Change message (`Data List` p. 55):
    `F0 43 1n 7F 17 <ah> <am> <al> <dd...> F7`
    """
    if isinstance(data, int):
        payload = [data & 0x7F]
    else:
        payload = [int(b) & 0x7F for b in data]
    return bytes([
        0xF0,
        YAMAHA_MFG_ID,
        0x10 | (dev_num & 0x0F),
        MX_MODEL_ID_HI,
        MX_MODEL_ID_LO,
        ah & 0x7F,
        am & 0x7F,
        al & 0x7F,
        *payload,
        0xF7,
    ])


def build_param_request(ah: int, am: int, al: int, dev_num: int = 0) -> bytes:
    """
    Build a Yamaha MX61 Native Parameter Request message (`Data List` p. 55):
    `F0 43 3n 7F 17 <ah> <am> <al> F7`
    """
    return bytes([
        0xF0,
        YAMAHA_MFG_ID,
        0x30 | (dev_num & 0x0F),
        MX_MODEL_ID_HI,
        MX_MODEL_ID_LO,
        ah & 0x7F,
        am & 0x7F,
        al & 0x7F,
        0xF7,
    ])


def build_bulk_dump(
    ah: int,
    am: int,
    al: int,
    payload: Union[bytes, bytearray, Sequence[int]],
    dev_num: int = 0,
) -> bytes:
    """
    Build a Yamaha MX61 Native Bulk Dump message (`Data List` pp. 55, 57):
    `F0 43 0n 7F 17 <bh> <bl> <ah> <am> <al> <dd...> <cc> F7`
    """
    data_bytes = [int(b) & 0x7F for b in payload]
    bh, bl = pack_u14(len(data_bytes))
    check_region = [bh, bl, ah & 0x7F, am & 0x7F, al & 0x7F, *data_bytes]
    cc = yamaha_checksum(check_region)
    return bytes([
        0xF0,
        YAMAHA_MFG_ID,
        0x00 | (dev_num & 0x0F),
        MX_MODEL_ID_HI,
        MX_MODEL_ID_LO,
        *check_region,
        cc,
        0xF7,
    ])


def build_bulk_request(ah: int, am: int, al: int, dev_num: int = 0) -> bytes:
    """
    Build a Yamaha MX61 Native Bulk Dump Request (`Data List` pp. 55, 57):
    `F0 43 2n 7F 17 <ah> <am> <al> F7`
    """
    return bytes([
        0xF0,
        YAMAHA_MFG_ID,
        0x20 | (dev_num & 0x0F),
        MX_MODEL_ID_HI,
        MX_MODEL_ID_LO,
        ah & 0x7F,
        am & 0x7F,
        al & 0x7F,
        0xF7,
    ])


def build_bulk_header(mm: int, nn: int, dev_num: int = 0) -> bytes:
    """Build Bulk Header packet (`0E mm nn`, byte count = 0)."""
    return build_bulk_dump(0x0E, mm & 0x7F, nn & 0x7F, b"", dev_num=dev_num)


def build_bulk_footer(mm: int, nn: int, dev_num: int = 0) -> bytes:
    """Build Bulk Footer packet (`0F mm nn`, byte count = 0)."""
    return build_bulk_dump(0x0F, mm & 0x7F, nn & 0x7F, b"", dev_num=dev_num)


# -----------------------------------------------------------------------------
# Bulk Dump Request Helpers (Data List p. 58)
# -----------------------------------------------------------------------------

def request_system_bulk(dev_num: int = 0) -> List[bytes]:
    """Request SYSTEM (`00 00 00`), Sequencer Setup (`00 05 00`), and Remote (`00 06 00`)."""
    return [
        build_bulk_request(0x00, 0x00, 0x00, dev_num=dev_num),
        build_bulk_request(0x00, 0x05, 0x00, dev_num=dev_num),
        build_bulk_request(0x00, 0x06, 0x00, dev_num=dev_num),
    ]


def request_preset_voice_bulk(preset_bank_1_to_8: int, program_0_to_127: int, dev_num: int = 0) -> bytes:
    """
    Request full 8-Element Bulk Dump of any factory Preset Normal Voice (`0E 00..07 nn`).
    `preset_bank_1_to_8`: 1..8 (corresponding to LSB 0..7 in the Data List).
    `program_0_to_127`: 0..127 (PC 1..128 in the Data List).
    """
    bank_idx = max(0, min(7, int(preset_bank_1_to_8) - 1))
    prog_idx = max(0, min(127, int(program_0_to_127)))
    return build_bulk_request(0x0E, bank_idx, prog_idx, dev_num=dev_num)


def request_user_voice_bulk(slot_0_to_127: int, dev_num: int = 0) -> bytes:
    """Request full Bulk Dump of a User Normal Voice `U001..U128` (`0E 0A nn`, `nn = 0..127`)."""
    return build_bulk_request(0x0E, 0x0A, max(0, min(127, int(slot_0_to_127))), dev_num=dev_num)


def request_voice_edit_buffer_bulk(dev_num: int = 0) -> bytes:
    """Request Normal Voice Edit Buffer (`0E 0F 00`)."""
    return build_bulk_request(0x0E, 0x0F, 0x00, dev_num=dev_num)


def request_part_voice_edit_buffer_bulk(part_0_to_15: int = 0, dev_num: int = 0) -> bytes:
    """Request Mixing Part Voice Edit Buffer (`0E 30 pp`, `pp = 0..15`)."""
    return build_bulk_request(0x0E, 0x30, max(0, min(15, int(part_0_to_15))), dev_num=dev_num)


def request_user_drum_bulk(slot_0_to_7: int, dev_num: int = 0) -> bytes:
    """Request User Drum Kit `U001..U008` (`0E 28 nn`, `nn = 0..7`)."""
    return build_bulk_request(0x0E, 0x28, max(0, min(7, int(slot_0_to_7))), dev_num=dev_num)


def request_user_performance_bulk(slot_0_to_127: int, dev_num: int = 0) -> bytes:
    """Request full Bulk Dump of User Performance `001..128` (`0E 50 nn`, `nn = 0..127`)."""
    return build_bulk_request(0x0E, 0x50, max(0, min(127, int(slot_0_to_127))), dev_num=dev_num)


def request_performance_edit_buffer_bulk(dev_num: int = 0) -> bytes:
    """Request Performance Edit Buffer (`0E 5F 00`)."""
    return build_bulk_request(0x0E, 0x5F, 0x00, dev_num=dev_num)


# -----------------------------------------------------------------------------
# SysEx Parser & Validator
# -----------------------------------------------------------------------------

def parse_sysex_message(raw: Union[bytes, bytearray]) -> Dict[str, object]:
    """
    Parse any incoming MIDI SysEx message from the Yamaha MX61 into a structured dictionary.
    Supports Universal Identity Reply, Yamaha Bulk Dump (`0n`), and Yamaha Parameter Change (`1n`).
    """
    b = bytes(raw)
    if len(b) < 4 or b[0] != 0xF0 or b[-1] != 0xF7:
        return {"type": "INVALID", "raw_hex": b.hex().upper()}

    # Universal Non-Realtime Identity Reply: F0 7E <dev> 06 02 43 00 41 47 06 ... F7
    if len(b) >= 15 and b[1] == 0x7E and b[3] == 0x06 and b[4] == 0x02:
        mfg = b[5]
        family = (b[7] << 7) | b[6]
        member = (b[9] << 7) | b[8]
        return {
            "type": "IDENTITY_REPLY",
            "device_no": b[2],
            "manufacturer_id": mfg,
            "family_code": f"0x{family:04X}",
            "member_code": f"0x{member:04X}",
            "is_mx49_mx61": (mfg == 0x43 and b[6] == 0x00 and b[7] == 0x41 and b[8] == 0x47 and b[9] == 0x06),
            "raw_hex": b.hex().upper(),
        }

    if len(b) >= 9 and b[1] == YAMAHA_MFG_ID and b[3] == MX_MODEL_ID_HI and b[4] == MX_MODEL_ID_LO:
        cmd_hi = b[2] & 0xF0
        dev_no = b[2] & 0x0F

        # Bulk Dump: F0 43 0n 7F 17 bh bl ah am al <data...> cc F7
        if cmd_hi == 0x00 and len(b) >= 12:
            bh, bl = b[5], b[6]
            byte_count = unpack_u14(bh, bl)
            ah, am, al = b[7], b[8], b[9]
            payload = b[10:-2]
            rx_cc = b[-2]
            calc_cc = yamaha_checksum(b[5:-2])
            kind = "BULK_BLOCK"
            if ah == 0x0E:
                kind = "BULK_HEADER"
            elif ah == 0x0F:
                kind = "BULK_FOOTER"
            ascii_preview = "".join(chr(c) if 32 <= c <= 126 else "." for c in payload[:10])
            return {
                "type": kind,
                "device_no": dev_no,
                "address": (ah, am, al),
                "address_hex": f"{ah:02X} {am:02X} {al:02X}",
                "byte_count": byte_count,
                "actual_len": len(payload),
                "checksum_ok": (rx_cc == calc_cc and len(payload) == byte_count),
                "rx_checksum": rx_cc,
                "calc_checksum": calc_cc,
                "data": payload,
                "ascii_10": ascii_preview,
            }

        # Parameter Change: F0 43 1n 7F 17 ah am al <data...> F7
        if cmd_hi == 0x10 and len(b) >= 9:
            ah, am, al = b[5], b[6], b[7]
            payload = b[8:-1]
            ascii_preview = "".join(chr(c) if 32 <= c <= 126 else "" for c in payload)
            return {
                "type": "PARAM_CHANGE",
                "device_no": dev_no,
                "address": (ah, am, al),
                "address_hex": f"{ah:02X} {am:02X} {al:02X}",
                "data": payload,
                "ascii": ascii_preview,
            }

    return {"type": "UNKNOWN_SYSEX", "raw_hex": b.hex().upper()}


def split_concatenated_sysex(raw_stream: Union[bytes, bytearray, Sequence[bytes]]) -> List[bytes]:
    """
    Split a raw byte buffer or list of chunks into individual `F0 ... F7` SysEx messages.
    Important because Windows `winmm.dll` may deliver a multi-block Yamaha Bulk Dump
    either as separate `MIM_LONGDATA` callbacks or concatenated within buffers.
    """
    if isinstance(raw_stream, (bytes, bytearray)):
        buf = bytes(raw_stream)
    else:
        buf = b"".join(bytes(x) for x in raw_stream)

    messages: List[bytes] = []
    start = -1
    for i, byte_val in enumerate(buf):
        if byte_val == 0xF0:
            start = i
        elif byte_val == 0xF7 and start >= 0:
            messages.append(buf[start : i + 1])
            start = -1
    return messages


# -----------------------------------------------------------------------------
# High-Level Normal Voice (8 Elements) & Performance (16 Parts) Codec
# -----------------------------------------------------------------------------

@dataclass
class ControllerSetEntry:
    """One of the 6 Controller Sets (`40 06 00..17`) inside a Normal Voice."""
    source: int = CTRL_SRC_MW
    destination: int = CTRL_DEST_OFF
    depth: int = 0  # -64..+63 (encoded as 0..127 where 64 = 0)

    def to_bytes(self) -> bytes:
        depth_byte = max(0, min(127, int(self.depth) + 64))
        dest_hi, dest_lo = pack_u14(self.destination)
        return bytes([depth_byte, self.source & 0x0F, dest_hi, dest_lo])


@dataclass
class Mx61VoicePatch:
    """
    Complete representation of a Yamaha MX61 Normal Voice (20 blocks total):
      - Common (`40 00 00`, 80 bytes)
      - Insertion A (`40 03 00`, 36 bytes)
      - Controller + LFO (`40 06 00`, 60 bytes)
      - Arpeggio (`40 30 00`, 86 bytes)
      - Elements 1..8 Osc+Amp+Pitch (`41 00..07 00`, 88 bytes each)
      - Elements 1..8 Filter+EQ+LFO (`42 00..07 00`, 74 bytes each)
    """
    common: bytearray = field(default_factory=lambda: bytearray(80))
    insertion_a: bytearray = field(default_factory=lambda: bytearray(36))
    ctrl_lfo: bytearray = field(default_factory=lambda: bytearray(60))
    arpeggio: bytearray = field(default_factory=lambda: bytearray(86))
    elem_osc: List[bytearray] = field(default_factory=lambda: [bytearray(88) for _ in range(8)])
    elem_flt: List[bytearray] = field(default_factory=lambda: [bytearray(74) for _ in range(8)])

    @classmethod
    def from_bulk_messages(cls, messages: Sequence[bytes]) -> "Mx61VoicePatch":
        """Reconstruct an `Mx61VoicePatch` from a list of raw SysEx Bulk Dump packets."""
        patch = cls()
        for msg in split_concatenated_sysex(messages):
            parsed = parse_sysex_message(msg)
            if parsed.get("type") != "BULK_BLOCK":
                continue
            ah, am, al = parsed["address"]  # type: ignore[misc]
            data = bytes(parsed["data"])    # type: ignore[arg-type]
            if ah == 0x40 and am == 0x00 and al == 0x00 and len(data) == 80:
                patch.common[:] = data
            elif ah == 0x40 and am == 0x03 and al == 0x00 and len(data) == 36:
                patch.insertion_a[:] = data
            elif ah == 0x40 and am == 0x06 and al == 0x00 and len(data) == 60:
                patch.ctrl_lfo[:] = data
            elif ah == 0x40 and am == 0x30 and al == 0x00 and len(data) == 86:
                patch.arpeggio[:] = data
            elif ah == 0x41 and 0x00 <= am <= 0x07 and al == 0x00 and len(data) == 88:
                patch.elem_osc[am][:] = data
            elif ah == 0x42 and 0x00 <= am <= 0x07 and al == 0x00 and len(data) == 74:
                patch.elem_flt[am][:] = data
        return patch

    def to_bulk_messages(self, target_mm: int = 0x0F, target_nn: int = 0x00, dev_num: int = 0) -> List[bytes]:
        """
        Serialize this `Mx61VoicePatch` into the complete sequence of 22 SysEx Bulk Dump packets:
          - `target_mm=0x0F, target_nn=0x00`: Normal Voice Edit Buffer (volatile RAM preview)
          - `target_mm=0x30, target_nn=part`: Mixing Part Voice Edit Buffer (`part = 0..15`)
          - `target_mm=0x0A, target_nn=slot`: User Normal Voice `U001..U128` (`slot = 0..127`)
        """
        pkts: List[bytes] = [
            build_bulk_header(target_mm, target_nn, dev_num=dev_num),
            build_bulk_dump(0x40, 0x00, 0x00, self.common, dev_num=dev_num),
            build_bulk_dump(0x40, 0x03, 0x00, self.insertion_a, dev_num=dev_num),
            build_bulk_dump(0x40, 0x06, 0x00, self.ctrl_lfo, dev_num=dev_num),
            build_bulk_dump(0x40, 0x30, 0x00, self.arpeggio, dev_num=dev_num),
        ]
        for ee in range(8):
            pkts.append(build_bulk_dump(0x41, ee, 0x00, self.elem_osc[ee], dev_num=dev_num))
            pkts.append(build_bulk_dump(0x42, ee, 0x00, self.elem_flt[ee], dev_num=dev_num))
        pkts.append(build_bulk_footer(target_mm, target_nn, dev_num=dev_num))
        return pkts

    @property
    def name(self) -> str:
        return bytes(self.common[0:10]).decode("ascii", errors="replace").strip()

    @name.setter
    def name(self, val: str) -> None:
        padded = val.encode("ascii", errors="replace")[:10].ljust(10, b" ")
        self.common[0:10] = padded

    @property
    def category_id(self) -> int:
        return int(self.common[0x18])

    @category_id.setter
    def category_id(self, cat: int) -> None:
        self.common[0x18] = max(0, min(0x11, int(cat)))

    @property
    def volume(self) -> int:
        return int(self.common[0x3F])

    @volume.setter
    def volume(self, val: int) -> None:
        self.common[0x3F] = max(0, min(127, int(val)))

    def set_insertion_effect(
        self,
        fx_type: Tuple[int, int],
        preset: int = 0,
        params: Optional[Dict[int, int]] = None,
    ) -> None:
        """
        Configure the Voice's Insertion Effect A (`40 03 00..23`).
        `fx_type`: `(msb, lsb)` from `FX_*` constants (e.g. `FX_DAMPER_RESONANCE`).
        `params`: `{param_index_1_to_16: uint14_value}`.
        """
        self.insertion_a[0x00] = fx_type[0] & 0x7F
        self.insertion_a[0x01] = fx_type[1] & 0x7F
        self.insertion_a[0x02] = preset & 0x7F
        if params:
            for p_idx, val in params.items():
                if 1 <= p_idx <= 16:
                    offset = 0x04 + (p_idx - 1) * 2
                    hi, lo = pack_u14(val)
                    self.insertion_a[offset] = hi
                    self.insertion_a[offset + 1] = lo

    def set_controller_set(
        self,
        set_index_1_to_6: int,
        source: int,
        destination: int,
        depth: int,
        active_elements_0_to_7: Optional[Sequence[int]] = None,
    ) -> None:
        """
        Configure one of the 6 Controller Sets (`40 06 00..17`) and optionally update
        each Element's `Controller Set Element Sw` bitmask (`41 ee 12..13`) so that
        only the specified Elements respond to this Controller Set!
        """
        idx = max(1, min(6, int(set_index_1_to_6))) - 1
        base = idx * 4
        entry = ControllerSetEntry(source=source, destination=destination, depth=depth)
        self.ctrl_lfo[base : base + 4] = entry.to_bytes()

        if active_elements_0_to_7 is not None:
            active_set = set(active_elements_0_to_7)
            bit_mask = 1 << idx
            for ee in range(8):
                cur_sw = self.elem_osc[ee][0x13] & 0x3F
                if ee in active_set:
                    cur_sw |= bit_mask
                else:
                    cur_sw &= ~bit_mask
                self.elem_osc[ee][0x12] = 0x00
                self.elem_osc[ee][0x13] = cur_sw & 0x3F

    def get_element_summary(self, ee: int) -> Dict[str, object]:
        """Return a readable summary of Element `ee` (`0..7`)."""
        osc = self.elem_osc[ee]
        flt = self.elem_flt[ee]
        wave_num = unpack_u14(osc[0x02], osc[0x03])
        cutoff = unpack_u14(flt[0x02], flt[0x03])
        return {
            "element": ee + 1,
            "enabled": bool(osc[0x00]),
            "wave_number": wave_num,
            "xa_control": int(osc[0x09]),
            "note_limit": (int(osc[0x0A]), int(osc[0x0B])),
            "velocity_limit": (int(osc[0x0C]), int(osc[0x0D])),
            "velocity_crossfade": int(osc[0x0E]),
            "insert_fx_routed": bool(osc[0x11]),
            "controller_set_mask": f"0b{osc[0x13]:06b}",
            "half_damper_switch": bool(osc[0x17]),
            "level": int(osc[0x1A]),
            "level_vel_sens": int(osc[0x1B]) - 64,
            "coarse_tune": int(osc[0x3A]) - 64,
            "fine_tune": int(osc[0x3B]) - 64,
            "filter_type": int(flt[0x00]),
            "filter_cutoff": cutoff,
            "filter_resonance": int(flt[0x05]),
            "level_scaling_bp_notes": [int(osc[0x2C + i]) for i in range(4)],
            "level_scaling_offsets": [
                unpack_signed_offset_14bit(osc[0x30 + i * 2], osc[0x31 + i * 2]) for i in range(4)
            ],
            "filter_scaling_bp_notes": [int(flt[0x25 + i]) for i in range(4)],
            "filter_scaling_offsets": [
                unpack_signed_offset_14bit(flt[0x2A + i * 2], flt[0x2B + i * 2]) for i in range(4)
            ],
        }

    def configure_element(
        self,
        ee: int,
        *,
        enabled: Optional[bool] = None,
        wave_number: Optional[int] = None,
        xa_control: Optional[int] = None,
        pan: Optional[int] = None,
        note_low: Optional[int] = None,
        note_high: Optional[int] = None,
        vel_low: Optional[int] = None,
        vel_high: Optional[int] = None,
        vel_crossfade: Optional[int] = None,
        insert_fx_on: Optional[bool] = None,
        half_damper_on: Optional[bool] = None,
        half_damper_time: Optional[int] = None,
        level: Optional[int] = None,
        level_vel_sens: Optional[int] = None,
        level_vel_offset: Optional[int] = None,
        level_vel_curve: Optional[int] = None,
        aeg_attack: Optional[int] = None,
        aeg_decay1: Optional[int] = None,
        aeg_decay2: Optional[int] = None,
        aeg_release: Optional[int] = None,
        aeg_decay1_level: Optional[int] = None,
        aeg_decay2_level: Optional[int] = None,
        coarse_tune: Optional[int] = None,
        fine_tune: Optional[int] = None,
        filter_type: Optional[int] = None,
        filter_cutoff: Optional[int] = None,
        filter_cutoff_vel_sens: Optional[int] = None,
        filter_resonance: Optional[int] = None,
        filter_gain: Optional[int] = None,
        level_bp_notes: Optional[Tuple[int, int, int, int]] = None,
        level_bp_offsets: Optional[Tuple[int, int, int, int]] = None,
        filter_bp_notes: Optional[Tuple[int, int, int, int]] = None,
        filter_bp_offsets: Optional[Tuple[int, int, int, int]] = None,
    ) -> None:
        """Modify parameters of Element `ee` (`0..7`) in-place."""
        osc = self.elem_osc[ee]
        flt = self.elem_flt[ee]

        if enabled is not None:
            osc[0x00] = 1 if enabled else 0
        if wave_number is not None:
            wh, wl = pack_u14(max(1, min(1566, int(wave_number))))
            osc[0x02] = wh
            osc[0x03] = wl
        if pan is not None:
            osc[0x05] = max(1, min(127, int(pan) + 64))
        if xa_control is not None:
            osc[0x09] = max(0, min(7, int(xa_control)))
        if note_low is not None:
            osc[0x0A] = max(0, min(127, int(note_low)))
        if note_high is not None:
            osc[0x0B] = max(0, min(127, int(note_high)))
        if vel_low is not None:
            osc[0x0C] = max(1, min(127, int(vel_low)))
        if vel_high is not None:
            osc[0x0D] = max(1, min(127, int(vel_high)))
        if vel_crossfade is not None:
            osc[0x0E] = max(0, min(127, int(vel_crossfade)))
        if insert_fx_on is not None:
            osc[0x11] = 1 if insert_fx_on else 0
        if half_damper_on is not None:
            osc[0x17] = 1 if half_damper_on else 0
        if level is not None:
            osc[0x1A] = max(0, min(127, int(level)))
        if level_vel_sens is not None:
            osc[0x1B] = max(0, min(127, int(level_vel_sens) + 64))
        if level_vel_offset is not None:
            osc[0x1C] = max(0, min(127, int(level_vel_offset)))
        if level_vel_curve is not None:
            osc[0x1D] = max(0, min(4, int(level_vel_curve)))
        if aeg_attack is not None:
            osc[0x1E] = max(0, min(127, int(aeg_attack)))
        if aeg_decay1 is not None:
            osc[0x1F] = max(0, min(127, int(aeg_decay1)))
        if aeg_decay2 is not None:
            osc[0x20] = max(0, min(127, int(aeg_decay2)))
        if half_damper_time is not None:
            osc[0x21] = max(0, min(127, int(half_damper_time)))
        if aeg_release is not None:
            osc[0x22] = max(0, min(127, int(aeg_release)))
        if aeg_decay1_level is not None:
            osc[0x25] = max(0, min(127, int(aeg_decay1_level)))
        if aeg_decay2_level is not None:
            osc[0x26] = max(0, min(127, int(aeg_decay2_level)))
        if coarse_tune is not None:
            osc[0x3A] = max(0x10, min(0x70, int(coarse_tune) + 64))
        if fine_tune is not None:
            osc[0x3B] = max(0, min(127, int(fine_tune) + 64))

        if level_bp_notes is not None:
            for i in range(4):
                osc[0x2C + i] = max(i, min(0x7C + i, int(level_bp_notes[i])))
        if level_bp_offsets is not None:
            for i in range(4):
                msb, lsb = pack_signed_offset_14bit(level_bp_offsets[i])
                osc[0x30 + i * 2] = msb
                osc[0x31 + i * 2] = lsb

        if filter_type is not None:
            flt[0x00] = max(0, min(21, int(filter_type)))
        if filter_cutoff is not None:
            ch, cl = pack_u14(max(0, min(255, int(filter_cutoff))))
            flt[0x02] = ch
            flt[0x03] = cl
        if filter_cutoff_vel_sens is not None:
            flt[0x04] = max(0, min(127, int(filter_cutoff_vel_sens) + 64))
        if filter_resonance is not None:
            flt[0x05] = max(8, min(71, int(filter_resonance)))
        if filter_gain is not None:
            gh, gl = pack_u14(max(0, min(255, int(filter_gain))))
            flt[0x0C] = gh
            flt[0x0D] = gl
        if filter_bp_notes is not None:
            for i in range(4):
                flt[0x25 + i] = max(i, min(0x7C + i, int(filter_bp_notes[i])))
        if filter_bp_offsets is not None:
            for i in range(4):
                msb, lsb = pack_signed_offset_14bit(filter_bp_offsets[i])
                flt[0x2A + i * 2] = msb
                flt[0x2B + i * 2] = lsb


@dataclass
class Mx61PerformancePatch:
    """
    Complete representation of a Yamaha MX61 Performance (`MULTI`, 37 blocks total):
      - Common (`36 00 00`, 80 bytes)
      - Reverb (`36 01 00`, 38 bytes)
      - Chorus (`36 02 00`, 40 bytes)
      - Master EQ (`36 10 00`, 20 bytes)
      - Arpeggio Common (`36 30 00`, 14 bytes)
      - Parts 1..16 (`37 00..0F 00`, 62 bytes each)
      - Arpeggio Parts 1..16 (`38 00..0F 00`, 72 bytes each)
    """
    common: bytearray = field(default_factory=lambda: bytearray(80))
    reverb: bytearray = field(default_factory=lambda: bytearray(38))
    chorus: bytearray = field(default_factory=lambda: bytearray(40))
    master_eq: bytearray = field(default_factory=lambda: bytearray(20))
    arp_common: bytearray = field(default_factory=lambda: bytearray(14))
    parts: List[bytearray] = field(default_factory=lambda: [bytearray(62) for _ in range(16)])
    arp_parts: List[bytearray] = field(default_factory=lambda: [bytearray(72) for _ in range(16)])

    @classmethod
    def from_bulk_messages(cls, messages: Sequence[bytes]) -> "Mx61PerformancePatch":
        perf = cls()
        for msg in split_concatenated_sysex(messages):
            parsed = parse_sysex_message(msg)
            if parsed.get("type") != "BULK_BLOCK":
                continue
            ah, am, al = parsed["address"]  # type: ignore[misc]
            data = bytes(parsed["data"])    # type: ignore[arg-type]
            if ah == 0x36 and am == 0x00 and al == 0x00 and len(data) == 80:
                perf.common[:] = data
            elif ah == 0x36 and am == 0x01 and al == 0x00 and len(data) == 38:
                perf.reverb[:] = data
            elif ah == 0x36 and am == 0x02 and al == 0x00 and len(data) == 40:
                perf.chorus[:] = data
            elif ah == 0x36 and am == 0x10 and al == 0x00 and len(data) == 20:
                perf.master_eq[:] = data
            elif ah == 0x36 and am == 0x30 and al == 0x00 and len(data) == 14:
                perf.arp_common[:] = data
            elif ah == 0x37 and 0x00 <= am <= 0x0F and al == 0x00 and len(data) == 62:
                perf.parts[am][:] = data
            elif ah == 0x38 and 0x00 <= am <= 0x0F and al == 0x00 and len(data) == 72:
                perf.arp_parts[am][:] = data
        return perf

    def to_bulk_messages(self, target_mm: int = 0x5F, target_nn: int = 0x00, dev_num: int = 0) -> List[bytes]:
        """
        Serialize this `Mx61PerformancePatch` into the complete sequence of 39 SysEx Bulk Dump packets:
          - `target_mm=0x5F, target_nn=0x00`: Performance Edit Buffer (volatile RAM preview)
          - `target_mm=0x50, target_nn=slot`: User Performance `001..128` (`slot = 0..127`)
        """
        pkts: List[bytes] = [
            build_bulk_header(target_mm, target_nn, dev_num=dev_num),
            build_bulk_dump(0x36, 0x00, 0x00, self.common, dev_num=dev_num),
            build_bulk_dump(0x36, 0x01, 0x00, self.reverb, dev_num=dev_num),
            build_bulk_dump(0x36, 0x02, 0x00, self.chorus, dev_num=dev_num),
            build_bulk_dump(0x36, 0x10, 0x00, self.master_eq, dev_num=dev_num),
            build_bulk_dump(0x36, 0x30, 0x00, self.arp_common, dev_num=dev_num),
        ]
        for pp in range(16):
            pkts.append(build_bulk_dump(0x37, pp, 0x00, self.parts[pp], dev_num=dev_num))
            pkts.append(build_bulk_dump(0x38, pp, 0x00, self.arp_parts[pp], dev_num=dev_num))
        pkts.append(build_bulk_footer(target_mm, target_nn, dev_num=dev_num))
        return pkts

    @property
    def name(self) -> str:
        return bytes(self.common[0:10]).decode("ascii", errors="replace").strip()

    @name.setter
    def name(self, val: str) -> None:
        padded = val.encode("ascii", errors="replace")[:10].ljust(10, b" ")
        self.common[0:10] = padded

    @property
    def keyboard_mode(self) -> int:
        """0 = single, 1 = layer, 2 = split (`36 00 41`)."""
        return int(self.common[0x41])

    @keyboard_mode.setter
    def keyboard_mode(self, mode: int) -> None:
        self.common[0x41] = max(0, min(2, int(mode)))

    @property
    def split_point(self) -> int:
        return int(self.common[0x42])

    @split_point.setter
    def split_point(self, note: int) -> None:
        self.common[0x42] = max(1, min(127, int(note)))

    @property
    def part1_2_link(self) -> bool:
        return bool(self.common[0x44])

    @part1_2_link.setter
    def part1_2_link(self, enabled: bool) -> None:
        self.common[0x44] = 1 if enabled else 0

    def set_insertion_parts(self, active_parts_0_to_15: Sequence[int]) -> None:
        """
        Enable Insertion Effects on up to 4 Parts simultaneously (`36 00 4C..4F`).
        Bit layout from `Data List` p. 60:
          - `4F` (`4th byte`): bits 0..6 = Parts 1..7 (`pp = 0..6`)
          - `4E` (`3rd byte`): bits 0..6 = Parts 8..14 (`pp = 7..13`)
          - `4D` (`2nd byte`): bits 0..1 = Parts 15..16 (`pp = 14..15`)
        """
        chosen = list(dict.fromkeys(int(p) for p in active_parts_0_to_15 if 0 <= int(p) <= 15))[:4]
        b1, b2, b3 = 0x04, 0x00, 0x00
        for pp in chosen:
            if pp < 7:
                b3 |= 1 << pp
            elif pp < 14:
                b2 |= 1 << (pp - 7)
            else:
                b1 |= 1 << (pp - 14)
        self.common[0x4C] = 0x00
        self.common[0x4D] = b1 & 0x7F
        self.common[0x4E] = b2 & 0x7F
        self.common[0x4F] = b3 & 0x7F

    def set_master_eq_band(
        self,
        band_idx_0_to_4: int,
        *,
        gain_db: Optional[int] = None,
        freq_table_idx: Optional[int] = None,
        q_x10: Optional[int] = None,
        shape_peaking: Optional[bool] = None,
    ) -> None:
        """
        Configure one of the 5 Parametric Master EQ bands (`36 10 00..13`, `Data List` p. 60):
          - `band_idx_0_to_4`: 0=Low, 1=Low-Mid, 2=Mid, 3=High-Mid, 4=High
          - `gain_db`: `-12..+12` dB (encoded as `0x34..0x4C`, `0x40 = 0 dB`)
          - `freq_table_idx`: index from Table #3 (`0x04..0x3A`)
          - `q_x10`: `1..120` representing `Q = 0.1..12.0` (`0x01..0x78`)
          - `shape_peaking`: `False` = shelving, `True` = peaking (valid for Low=0 and High=4)
        """
        b = max(0, min(4, int(band_idx_0_to_4))) * 4
        if gain_db is not None:
            self.master_eq[b + 0] = max(0x34, min(0x4C, int(round(gain_db)) + 0x40))
        if freq_table_idx is not None:
            self.master_eq[b + 1] = max(0x04, min(0x3A, int(freq_table_idx)))
        if q_x10 is not None:
            self.master_eq[b + 2] = max(0x01, min(0x78, int(q_x10)))
        if shape_peaking is not None and band_idx_0_to_4 in (0, 4):
            self.master_eq[b + 3] = 1 if shape_peaking else 0

    def configure_part(
        self,
        part_0_to_15: int,
        *,
        bank_msb: Optional[int] = None,
        bank_lsb: Optional[int] = None,
        program_0_to_127: Optional[int] = None,
        receive_channel_0_to_15_or_7f: Optional[int] = None,
        volume: Optional[int] = None,
        pan: Optional[int] = None,
        reverb_send: Optional[int] = None,
        chorus_send: Optional[int] = None,
        dry_level: Optional[int] = None,
        note_shift: Optional[int] = None,
        note_low: Optional[int] = None,
        note_high: Optional[int] = None,
        vel_low: Optional[int] = None,
        vel_high: Optional[int] = None,
        vel_sens_depth: Optional[int] = None,
        vel_sens_offset: Optional[int] = None,
        cutoff_offset: Optional[int] = None,
        resonance_offset: Optional[int] = None,
        aeg_attack_offset: Optional[int] = None,
        aeg_decay_offset: Optional[int] = None,
        aeg_sustain_offset: Optional[int] = None,
        aeg_release_offset: Optional[int] = None,
        receive_mw: Optional[bool] = None,
        receive_sustain: Optional[bool] = None,
        receive_assign1: Optional[bool] = None,
        receive_assign2: Optional[bool] = None,
    ) -> None:
        """Configure Part `part_0_to_15` (`0..15`) parameters (`37 pp 00..3D`, `Data List` p. 61)."""
        p = self.parts[max(0, min(15, int(part_0_to_15)))]
        if bank_msb is not None:
            p[0x01] = bank_msb & 0x7F
        if bank_lsb is not None:
            p[0x02] = bank_lsb & 0x7F
        if program_0_to_127 is not None:
            p[0x03] = max(0, min(127, int(program_0_to_127)))
        if receive_channel_0_to_15_or_7f is not None:
            p[0x04] = receive_channel_0_to_15_or_7f & 0x7F
        if vel_low is not None:
            p[0x06] = max(1, min(127, int(vel_low)))
        if vel_high is not None:
            p[0x07] = max(1, min(127, int(vel_high)))
        if note_low is not None:
            p[0x08] = max(0, min(127, int(note_low)))
        if note_high is not None:
            p[0x09] = max(0, min(127, int(note_high)))
        if vel_sens_depth is not None:
            p[0x0C] = max(0, min(127, int(vel_sens_depth)))
        if vel_sens_offset is not None:
            p[0x0D] = max(0, min(127, int(vel_sens_offset)))
        if volume is not None:
            p[0x0E] = max(0, min(127, int(volume)))
        if pan is not None:
            p[0x0F] = max(1, min(127, int(pan) + 64))
        if reverb_send is not None:
            p[0x12] = max(0, min(127, int(reverb_send)))
        if chorus_send is not None:
            p[0x13] = max(0, min(127, int(chorus_send)))
        if dry_level is not None:
            p[0x15] = max(0, min(127, int(dry_level)))
        if note_shift is not None:
            p[0x16] = max(0x28, min(0x58, int(note_shift) + 0x40))
        if receive_mw is not None:
            if receive_mw:
                p[0x20] |= 1 << 3
            else:
                p[0x20] &= ~(1 << 3)
        if receive_sustain is not None:
            if receive_sustain:
                p[0x20] |= 1 << 2
            else:
                p[0x20] &= ~(1 << 2)
        if receive_assign1 is not None:
            if receive_assign1:
                p[0x21] |= 1 << 3
            else:
                p[0x21] &= ~(1 << 3)
        if receive_assign2 is not None:
            if receive_assign2:
                p[0x21] |= 1 << 4
            else:
                p[0x21] &= ~(1 << 4)
        if aeg_attack_offset is not None:
            p[0x23] = max(0, min(127, int(aeg_attack_offset) + 64))
        if aeg_decay_offset is not None:
            p[0x24] = max(0, min(127, int(aeg_decay_offset) + 64))
        if aeg_sustain_offset is not None:
            p[0x25] = max(0, min(127, int(aeg_sustain_offset) + 64))
        if aeg_release_offset is not None:
            p[0x26] = max(0, min(127, int(aeg_release_offset) + 64))
        if cutoff_offset is not None:
            p[0x2D] = max(0, min(127, int(cutoff_offset) + 64))
        if resonance_offset is not None:
            p[0x2E] = max(0, min(127, int(resonance_offset) + 64))


# -----------------------------------------------------------------------------
# Real-time Live Parameter Shaper (`Mx61LiveShaper`)
# -----------------------------------------------------------------------------

class Mx61LiveShaper:
    """Real-time single-parameter SysEx builders for instant tweaking on the MX61."""

    @staticmethod
    def set_velocity_curve(curve_0_to_4: int = 0, dev_num: int = 0) -> bytes:
        """Set Global Velocity Curve (`00 00 11`): 0=norm, 1=soft, 2=hard, 3=wide, 4=fixed."""
        return build_param_change(0x00, 0x00, 0x11, max(0, min(4, int(curve_0_to_4))), dev_num=dev_num)

    @staticmethod
    def set_half_damper_pedal(mode_0_to_2: int = 0, dev_num: int = 0) -> bytes:
        """Set Foot Switch Pedal Select (`00 00 33`): 0=FC3 (Half On), 1=FC3 (Half Off), 2=FC4/5."""
        return build_param_change(0x00, 0x00, 0x33, max(0, min(2, int(mode_0_to_2))), dev_num=dev_num)

    @staticmethod
    def set_keyboard_mode(mode_0_to_2: int = 0, dev_num: int = 0) -> bytes:
        """Set Performance Keyboard Mode (`36 00 41`): 0=single, 1=layer, 2=split."""
        return build_param_change(0x36, 0x00, 0x41, max(0, min(2, int(mode_0_to_2))), dev_num=dev_num)

    @staticmethod
    def set_part1_2_link(enabled: bool = True, dev_num: int = 0) -> bytes:
        """Set Performance Part 1-2 Link (`36 00 44`): 0=off, 1=on."""
        return build_param_change(0x36, 0x00, 0x44, 1 if enabled else 0, dev_num=dev_num)

    @staticmethod
    def set_master_eq_band_live(
        band_idx_0_to_4: int,
        gain_db: int,
        freq_idx: int,
        q_x10: int,
        shape_peaking: bool = True,
        dev_num: int = 0,
    ) -> List[bytes]:
        """Send live Parameter Change packets for a single Master EQ band (`36 10 00..13`)."""
        b = max(0, min(4, int(band_idx_0_to_4))) * 4
        pkts = [
            build_param_change(0x36, 0x10, b + 0, max(0x34, min(0x4C, int(gain_db) + 0x40)), dev_num=dev_num),
            build_param_change(0x36, 0x10, b + 1, max(0x04, min(0x3A, int(freq_idx))), dev_num=dev_num),
            build_param_change(0x36, 0x10, b + 2, max(0x01, min(0x78, int(q_x10))), dev_num=dev_num),
        ]
        if band_idx_0_to_4 in (0, 4):
            pkts.append(build_param_change(0x36, 0x10, b + 3, 1 if shape_peaking else 0, dev_num=dev_num))
        return pkts

    @staticmethod
    def select_performance(perf_0_to_127: int, basic_channel: int = 0) -> List[bytes]:
        """Select a User Performance `001..128` via Bank Select (`MSB=63, LSB=80`) + Program Change."""
        ch = basic_channel & 0x0F
        pc = max(0, min(127, int(perf_0_to_127)))
        return [
            bytes([0xB0 | ch, 0x00, 63]),
            bytes([0xB0 | ch, 0x20, 80]),
            bytes([0xC0 | ch, pc]),
        ]

    @staticmethod
    def select_part_voice(
        part_0_to_15: int,
        msb: int,
        lsb: int,
        program_0_to_127: int,
        dev_num: int = 0,
    ) -> List[bytes]:
        """Assign a Voice (`MSB, LSB, PC`) to Part `part_0_to_15` via SysEx (`37 pp 01..03`)."""
        pp = max(0, min(15, int(part_0_to_15)))
        return [
            build_param_change(0x37, pp, 0x01, [msb & 0x7F, lsb & 0x7F, program_0_to_127 & 0x7F], dev_num=dev_num),
        ]
