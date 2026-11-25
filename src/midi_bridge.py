#!/usr/bin/env python3
"""
Bidirectional USB-MIDI & Built-in USB-Audio Hardware Bridge for the Yamaha MX49/MX61 (`src/midi_bridge.py`).

Supports two transparent execution environments:
  1. Windows 11 / WSL2 (`powershell.exe` + compiled `Mx61MidiBridge.exe` via `winmm.dll`):
     - Automatically selects `Yamaha MX49/MX61-1` (MIDI Port 1 — main synth & SysEx engine)
     - Automatically selects the MX61's built-in 2-In/2-Out USB-Audio interface (`Yamaha MX49/MX61` / `Steinberg`)
       over the same single USB cable (`USB [TO HOST]`).
  2. Native Linux / Termux (`amidi` / `arecord` when connected via OTG/ALSA, or deterministic offline
     simulation mode when developing/testing without hardware attached).

Implements:
  - `ping_mx61()`: Universal Identity Request (`F0 7E 7F 06 01 F7`) + Active Performance bulk check
  - `scan_user_voices()`: Reads `U001..U128` (`0E 0A 00..7F`) to list voice names & find empty `"Initialize"` slots
  - `scan_performances()`: Reads `001..128` (`0E 50 00..7F`) to list Performance names
  - `inspect_preset_voice()`: Requests full 8-Element Bulk Dump of any factory Preset Voice (`0E 00..07 nn`)
  - `full_backup()` & `restore_full_backup()`: Complete non-destructive backup of `SYSTEM` + User Voices + User Performances
  - `save_slot_snapshot()`: Automatic rollback snapshot before writing to any User Voice or Performance slot
  - `monitor_keyboard_touch()`: Listens to physical keystrokes, Pitch Bend, Modulation Wheel (`CC#1`), and Knobs (`CC#74/71/16/17`)
  - `capture_acoustic_probe()`: Sends deterministic multi-velocity MIDI test phrases across the MX61's 61-key range (`C1..C6`)
    while recording digital stereo 44.1kHz/48kHz 16-bit WAV directly from the MX61's built-in USB-Audio interface.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
from typing import Dict, List, Optional, Sequence, Tuple, Union

from mx61_sysex import (
    Mx61PerformancePatch,
    Mx61VoicePatch,
    build_identity_request,
    parse_sysex_message,
    request_performance_edit_buffer_bulk,
    request_preset_voice_bulk,
    request_system_bulk,
    request_user_drum_bulk,
    request_user_performance_bulk,
    request_user_voice_bulk,
    request_voice_edit_buffer_bulk,
    split_concatenated_sysex,
)

POWERSHELL_EXE = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
CSHARP_SOURCE = Path(__file__).with_name("winmm_bridge.cs")
DEFAULT_BACKUP_DIR = Path(__file__).resolve().parent.parent / "backups"


class Mx61BridgeError(RuntimeError):
    """Raised when the USB-MIDI or USB-Audio bridge encounters a hardware/driver error."""


class Mx61Bridge:
    """High-level USB-MIDI + Built-in USB-Audio interface to the Yamaha MX61."""

    def __init__(self) -> None:
        self.has_wsl_powershell = Path(POWERSHELL_EXE).exists()
        self.win_work_dir: Optional[str] = None
        self.wsl_work_dir: Optional[Path] = None
        self.exe_win_path: Optional[str] = None

        if self.has_wsl_powershell:
            self.win_work_dir = self._resolve_windows_work_dir()
            self.wsl_work_dir = self._win_to_wsl_path(self.win_work_dir)
            self.wsl_work_dir.mkdir(parents=True, exist_ok=True)
            self.exe_win_path = f"{self.win_work_dir}\\Mx61MidiBridge.exe"
            self._ensure_compiled()

    def _resolve_windows_work_dir(self) -> str:
        proc = subprocess.run(
            [POWERSHELL_EXE, "-NoProfile", "-Command", "$env:USERPROFILE"],
            capture_output=True,
            text=True,
            check=True,
        )
        profile = proc.stdout.strip()
        if not profile:
            raise Mx61BridgeError("Could not resolve Windows %USERPROFILE% via PowerShell.")
        return f"{profile}\\.mx61_midi"

    @staticmethod
    def _win_to_wsl_path(win_path: str) -> Path:
        normalized = win_path.replace("\\", "/")
        if len(normalized) >= 2 and normalized[1] == ":":
            drive = normalized[0].lower()
            rest = normalized[2:].lstrip("/")
            return Path(f"/mnt/{drive}/{rest}")
        raise Mx61BridgeError(f"Unsupported Windows path format: {win_path}")

    def _ensure_compiled(self) -> None:
        if not self.has_wsl_powershell or self.wsl_work_dir is None or self.win_work_dir is None or self.exe_win_path is None:
            return
        cs_dest = self.wsl_work_dir / "winmm_bridge.cs"
        exe_dest = self.wsl_work_dir / "Mx61MidiBridge.exe"

        need_compile = not exe_dest.exists()
        if cs_dest.exists():
            if CSHARP_SOURCE.read_text(encoding="utf-8") != cs_dest.read_text(encoding="utf-8"):
                need_compile = True
        else:
            need_compile = True

        if not need_compile:
            return

        shutil.copyfile(CSHARP_SOURCE, cs_dest)
        csc_candidates = [
            r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
            r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe",
        ]
        ps_cmd = (
            f"$csc = '{csc_candidates[0]}'; "
            f"if (-not (Test-Path $csc)) {{ $csc = '{csc_candidates[1]}' }}; "
            f"& $csc /nologo /optimize+ /out:'{self.exe_win_path}' '{self.win_work_dir}\\winmm_bridge.cs'"
        )
        proc = subprocess.run(
            [POWERSHELL_EXE, "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 or not exe_dest.exists():
            raise Mx61BridgeError(
                f"Failed to compile Mx61MidiBridge.exe (exit={proc.returncode}):\n{proc.stdout}\n{proc.stderr}"
            )

    def list_devices(self) -> Dict[str, List[Dict[str, object]]]:
        """List all MIDI Out, MIDI In, Audio In, and Audio Out devices."""
        if not self.has_wsl_powershell or self.exe_win_path is None:
            return {
                "midi_out": [],
                "midi_in": [],
                "audio_in": [],
                "audio_out": [],
                "mode": [{"runtime": "linux_or_offline"}],
            }

        proc = subprocess.run(
            [POWERSHELL_EXE, "-NoProfile", "-Command", f"& '{self.exe_win_path}' list"],
            capture_output=True,
            text=True,
            check=True,
        )
        out_devs: List[Dict[str, object]] = []
        in_devs: List[Dict[str, object]] = []
        audio_in_devs: List[Dict[str, object]] = []
        audio_out_devs: List[Dict[str, object]] = []

        for raw_line in proc.stdout.splitlines():
            line = raw_line.strip()
            if line.startswith("MIDI_OUT:"):
                parts = line.split(":")
                out_devs.append({"index": int(parts[1]), "name": parts[2], "mid": parts[3], "pid": parts[4]})
            elif line.startswith("MIDI_IN:"):
                parts = line.split(":")
                in_devs.append({"index": int(parts[1]), "name": parts[2], "mid": parts[3], "pid": parts[4]})
            elif line.startswith("AUDIO_IN:"):
                parts = line.split(":")
                audio_in_devs.append({
                    "index": int(parts[1]),
                    "name": parts[2],
                    "channels": int(parts[3].split("=")[1]),
                    "mid": parts[4],
                    "pid": parts[5],
                })
            elif line.startswith("AUDIO_OUT:"):
                parts = line.split(":")
                audio_out_devs.append({
                    "index": int(parts[1]),
                    "name": parts[2],
                    "channels": int(parts[3].split("=")[1]),
                    "mid": parts[4],
                    "pid": parts[5],
                })
        return {
            "midi_out": out_devs,
            "midi_in": in_devs,
            "audio_in": audio_in_devs,
            "audio_out": audio_out_devs,
        }

    def execute_transaction(
        self,
        packets: Sequence[Union[bytes, bytearray, str]],
        inter_packet_delay_ms: int = 15,
        listen_window_ms: int = 500,
    ) -> Dict[str, object]:
        """
        Send a batch of raw MIDI / SysEx packets (or `"SLEEP:<ms>"` directives) and capture incoming
        MIDI / SysEx replies during `listen_window_ms`.
        """
        if not self.has_wsl_powershell or self.wsl_work_dir is None or self.win_work_dir is None or self.exe_win_path is None:
            return {
                "port_out": -1,
                "port_in": -1,
                "rx_count": 0,
                "rx_events": [],
                "offline": True,
                "hint": "Windows PowerShell / winmm.dll bridge not detected on this host; running in offline mode.",
            }

        pkt_file_wsl = self.wsl_work_dir / "tx_packets.txt"
        pkt_file_win = f"{self.win_work_dir}\\tx_packets.txt"

        hex_lines: List[str] = []
        for pkt in packets:
            if isinstance(pkt, str):
                s = pkt.strip()
                if s.upper().startswith("SLEEP:"):
                    hex_lines.append(s.upper())
                else:
                    hex_lines.append(s.replace(" ", "").upper())
            else:
                hex_lines.append(bytes(pkt).hex().upper())

        pkt_file_wsl.write_text("\n".join(hex_lines) + ("\n" if hex_lines else ""), encoding="ascii")

        cmd = f"& '{self.exe_win_path}' txrx {int(inter_packet_delay_ms)} {int(listen_window_ms)} '{pkt_file_win}'"
        proc = subprocess.run(
            [POWERSHELL_EXE, "-NoProfile", "-Command", cmd],
            capture_output=True,
            text=True,
            check=True,
        )

        port_out = -1
        port_in = -1
        rx_events: List[Dict[str, object]] = []

        for raw_line in proc.stdout.splitlines():
            line = raw_line.strip()
            if line.startswith("ERROR:"):
                raise Mx61BridgeError(f"WinMM Bridge Error: {line}")
            if line.startswith("PORT_OUT:"):
                parts = line.split(":")
                port_out = int(parts[1])
                port_in = int(parts[3])
            elif line.startswith("RX:SYSEX:"):
                hex_str = line[len("RX:SYSEX:") :].strip()
                raw_bytes = bytes.fromhex(hex_str)
                # Split in case multiple F0..F7 blocks were concatenated in one buffer
                for single_msg in split_concatenated_sysex(raw_bytes):
                    rx_events.append({
                        "kind": "SYSEX",
                        "hex": single_msg.hex().upper(),
                        "parsed": parse_sysex_message(single_msg),
                    })
            elif line.startswith("RX:SHORT:"):
                hex_str = line[len("RX:SHORT:") :].strip()
                rx_events.append({"kind": "SHORT", "hex": hex_str})

        return {
            "port_out": port_out,
            "port_in": port_in,
            "rx_count": len(rx_events),
            "rx_events": rx_events,
        }

    def ping_mx61(self, dev_num: int = 0) -> Dict[str, object]:
        """
        Verify bidirectional communication with the Yamaha MX61 via USB-MIDI Port 1
        and check the built-in USB-Audio interface (`Yamaha MX49/MX61`).
        """
        devs = self.list_devices()
        tx = self.execute_transaction(
            [
                build_identity_request(0x7F),
                "SLEEP:50",
                request_performance_edit_buffer_bulk(dev_num=dev_num),
            ],
            inter_packet_delay_ms=15,
            listen_window_ms=800,
        )

        identity = None
        perf_blocks = 0
        perf_name = None

        for ev in tx.get("rx_events", []):  # type: ignore[union-attr]
            if ev.get("kind") == "SYSEX":
                parsed = ev.get("parsed", {})
                if parsed.get("type") == "IDENTITY_REPLY":
                    identity = parsed
                elif parsed.get("type") == "BULK_BLOCK":
                    perf_blocks += 1
                    if parsed.get("address") == (0x36, 0x00, 0x00):
                        perf_name = parsed.get("ascii_10", "").strip()

        return {
            "connected": bool(identity or perf_blocks > 0),
            "devices": devs,
            "identity": identity,
            "active_performance_name": perf_name,
            "active_performance_blocks_received": perf_blocks,
            "raw_transaction": tx,
        }

    def fetch_voice_patch(
        self,
        *,
        user_slot_0_to_127: Optional[int] = None,
        preset_bank_1_to_8: Optional[int] = None,
        preset_program_0_to_127: Optional[int] = None,
        dev_num: int = 0,
    ) -> Tuple[Mx61VoicePatch, List[bytes]]:
        """
        Request and reconstruct a complete 8-Element `Mx61VoicePatch` from the MX61:
          - If `user_slot_0_to_127` is set: reads User Voice `U001..U128` (`0E 0A nn`)
          - If `preset_bank_1_to_8` and `preset_program_0_to_127` are set: reads Preset Voice (`0E 00..07 nn`)
          - Otherwise: reads the active Normal Voice Edit Buffer (`0E 0F 00`).
        """
        if user_slot_0_to_127 is not None:
            req = request_user_voice_bulk(user_slot_0_to_127, dev_num=dev_num)
        elif preset_bank_1_to_8 is not None and preset_program_0_to_127 is not None:
            req = request_preset_voice_bulk(preset_bank_1_to_8, preset_program_0_to_127, dev_num=dev_num)
        else:
            req = request_voice_edit_buffer_bulk(dev_num=dev_num)

        tx = self.execute_transaction([req], inter_packet_delay_ms=10, listen_window_ms=900)
        raw_msgs = [
            bytes.fromhex(ev["hex"])
            for ev in tx.get("rx_events", [])  # type: ignore[union-attr]
            if ev.get("kind") == "SYSEX"
        ]
        patch = Mx61VoicePatch.from_bulk_messages(raw_msgs)
        return patch, raw_msgs

    def fetch_performance_patch(
        self,
        *,
        user_slot_0_to_127: Optional[int] = None,
        dev_num: int = 0,
    ) -> Tuple[Mx61PerformancePatch, List[bytes]]:
        """
        Request and reconstruct a complete 16-Part `Mx61PerformancePatch` from the MX61:
          - If `user_slot_0_to_127` is set: reads User Performance `001..128` (`0E 50 nn`)
          - Otherwise: reads the active Performance Edit Buffer (`0E 5F 00`).
        """
        if user_slot_0_to_127 is not None:
            req = request_user_performance_bulk(user_slot_0_to_127, dev_num=dev_num)
        else:
            req = request_performance_edit_buffer_bulk(dev_num=dev_num)

        tx = self.execute_transaction([req], inter_packet_delay_ms=10, listen_window_ms=1100)
        raw_msgs = [
            bytes.fromhex(ev["hex"])
            for ev in tx.get("rx_events", [])  # type: ignore[union-attr]
            if ev.get("kind") == "SYSEX"
        ]
        perf = Mx61PerformancePatch.from_bulk_messages(raw_msgs)
        return perf, raw_msgs

    def scan_user_voices(
        self,
        start_slot_1_to_128: int = 1,
        end_slot_1_to_128: int = 128,
        dev_num: int = 0,
    ) -> Dict[str, object]:
        """
        Scan User Normal Voice slots `U001..U128` (`0E 0A 00..7F`) and classify which slots
        are still at factory `"Initialize"` vs. occupied by custom User Voices.
        """
        s0 = max(0, min(127, int(start_slot_1_to_128) - 1))
        s1 = max(s0, min(127, int(end_slot_1_to_128) - 1))

        slots: List[Dict[str, object]] = []
        empty_slots: List[int] = []
        occupied_slots: List[int] = []

        for idx in range(s0, s1 + 1):
            patch, raw_msgs = self.fetch_voice_patch(user_slot_0_to_127=idx, dev_num=dev_num)
            name = patch.name if raw_msgs else "OFFLINE"
            is_init = name.lower().startswith("init") or name == ""
            slot_num = idx + 1
            if is_init:
                empty_slots.append(slot_num)
            else:
                occupied_slots.append(slot_num)
            slots.append({
                "slot_number": slot_num,
                "slot_label": f"U{slot_num:03d}",
                "program_0_to_127": idx,
                "name": name,
                "is_empty_initialize": is_init,
                "blocks_received": len(raw_msgs),
            })

        return {
            "range": f"U{s0 + 1:03d}..U{s1 + 1:03d}",
            "empty_initialize_slots": empty_slots,
            "occupied_slots": occupied_slots,
            "first_available_slot": empty_slots[0] if empty_slots else None,
            "slots": slots,
        }

    def scan_performances(
        self,
        start_slot_1_to_128: int = 1,
        end_slot_1_to_128: int = 32,
        dev_num: int = 0,
    ) -> Dict[str, object]:
        """Scan User Performance slots `001..128` (`0E 50 00..7F`)."""
        s0 = max(0, min(127, int(start_slot_1_to_128) - 1))
        s1 = max(s0, min(127, int(end_slot_1_to_128) - 1))

        slots: List[Dict[str, object]] = []
        for idx in range(s0, s1 + 1):
            perf, raw_msgs = self.fetch_performance_patch(user_slot_0_to_127=idx, dev_num=dev_num)
            name = perf.name if raw_msgs else "OFFLINE"
            slot_num = idx + 1
            slots.append({
                "slot_number": slot_num,
                "slot_label": f"P{slot_num:03d}",
                "program_0_to_127": idx,
                "name": name,
                "keyboard_mode": perf.keyboard_mode,
                "part1_2_link": perf.part1_2_link,
                "blocks_received": len(raw_msgs),
            })
        return {
            "range": f"P{s0 + 1:03d}..P{s1 + 1:03d}",
            "slots": slots,
        }

    def save_slot_snapshot(
        self,
        kind: str,
        slot_0_to_127: int,
        dev_num: int = 0,
        backup_root: Path = DEFAULT_BACKUP_DIR,
    ) -> Optional[Path]:
        """
        Save an automatic timestamped `.syx` snapshot of a User Voice (`kind="voice"`)
        or User Performance (`kind="performance"`) before writing to it.
        """
        snap_dir = backup_root / "snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        if kind == "voice":
            _, raw_msgs = self.fetch_voice_patch(user_slot_0_to_127=slot_0_to_127, dev_num=dev_num)
            prefix = f"user_voice_U{slot_0_to_127 + 1:03d}"
        else:
            _, raw_msgs = self.fetch_performance_patch(user_slot_0_to_127=slot_0_to_127, dev_num=dev_num)
            prefix = f"user_perf_P{slot_0_to_127 + 1:03d}"

        if not raw_msgs:
            return None

        out_path = snap_dir / f"{prefix}_{ts}.syx"
        out_path.write_bytes(b"".join(raw_msgs))
        return out_path

    def full_backup(
        self,
        backup_dir: Optional[Union[str, Path]] = None,
        max_performances: int = 128,
        dev_num: int = 0,
    ) -> Dict[str, object]:
        """
        Perform a complete non-destructive backup of the Yamaha MX61 internal user memory:
          - `system.syx` (`00 00 00`, `00 05 00`, `00 06 00`)
          - `user_voices/U001..U128.syx` (`0E 0A 00..7F`)
          - `user_drums/UD01..UD08.syx` (`0E 28 00..07`)
          - `performances/P001..P128.syx` (`0E 50 00..7F`)
          - `manifest.json`
        """
        target_dir = Path(backup_dir) if backup_dir else (DEFAULT_BACKUP_DIR / "full_initial")
        voices_dir = target_dir / "user_voices"
        drums_dir = target_dir / "user_drums"
        perfs_dir = target_dir / "performances"
        voices_dir.mkdir(parents=True, exist_ok=True)
        drums_dir.mkdir(parents=True, exist_ok=True)
        perfs_dir.mkdir(parents=True, exist_ok=True)

        manifest: Dict[str, object] = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "model": "Yamaha MX49/MX61 (7F 17)",
            "system_blocks": 0,
            "user_voices": [],
            "user_drums": [],
            "performances": [],
        }

        # 1. System Bulk
        sys_tx = self.execute_transaction(request_system_bulk(dev_num=dev_num), inter_packet_delay_ms=25, listen_window_ms=800)
        sys_msgs = [
            bytes.fromhex(ev["hex"])
            for ev in sys_tx.get("rx_events", [])  # type: ignore[union-attr]
            if ev.get("kind") == "SYSEX"
        ]
        if sys_msgs:
            (target_dir / "system.syx").write_bytes(b"".join(sys_msgs))
        manifest["system_blocks"] = len(sys_msgs)

        # 2. User Voices U001..U128
        for idx in range(128):
            patch, raw_msgs = self.fetch_voice_patch(user_slot_0_to_127=idx, dev_num=dev_num)
            slot_label = f"U{idx + 1:03d}"
            if raw_msgs:
                (voices_dir / f"{slot_label}.syx").write_bytes(b"".join(raw_msgs))
            manifest["user_voices"].append({  # type: ignore[attr-defined]
                "slot": slot_label,
                "name": patch.name if raw_msgs else "OFFLINE",
                "bytes": sum(len(m) for m in raw_msgs),
            })

        # 3. User Drum Kits UD01..UD08
        for idx in range(8):
            tx = self.execute_transaction([request_user_drum_bulk(idx, dev_num=dev_num)], inter_packet_delay_ms=15, listen_window_ms=800)
            raw_msgs = [
                bytes.fromhex(ev["hex"])
                for ev in tx.get("rx_events", [])  # type: ignore[union-attr]
                if ev.get("kind") == "SYSEX"
            ]
            slot_label = f"UD{idx + 1:02d}"
            if raw_msgs:
                (drums_dir / f"{slot_label}.syx").write_bytes(b"".join(raw_msgs))
            manifest["user_drums"].append({  # type: ignore[attr-defined]
                "slot": slot_label,
                "bytes": sum(len(m) for m in raw_msgs),
            })

        # 4. User Performances P001..P128
        for idx in range(max(0, min(128, int(max_performances)))):
            perf, raw_msgs = self.fetch_performance_patch(user_slot_0_to_127=idx, dev_num=dev_num)
            slot_label = f"P{idx + 1:03d}"
            if raw_msgs:
                (perfs_dir / f"{slot_label}.syx").write_bytes(b"".join(raw_msgs))
            manifest["performances"].append({  # type: ignore[attr-defined]
                "slot": slot_label,
                "name": perf.name if raw_msgs else "OFFLINE",
                "bytes": sum(len(m) for m in raw_msgs),
            })

        manifest_path = target_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        return {
            "backup_dir": str(target_dir),
            "manifest_path": str(manifest_path),
            "system_blocks": len(sys_msgs),
            "voices_backed_up": len(manifest["user_voices"]),  # type: ignore[arg-type]
            "performances_backed_up": len(manifest["performances"]),  # type: ignore[arg-type]
        }

    def restore_syx_file(self, syx_path: Union[str, Path], inter_packet_delay_ms: int = 20) -> Dict[str, object]:
        """Transmit any saved `.syx` backup or snapshot file back to the Yamaha MX61."""
        path = Path(syx_path)
        if not path.exists():
            raise Mx61BridgeError(f"SysEx file not found: {path}")
        messages = split_concatenated_sysex(path.read_bytes())
        tx = self.execute_transaction(messages, inter_packet_delay_ms=inter_packet_delay_ms, listen_window_ms=300)
        return {
            "restored_file": str(path),
            "packets_sent": len(messages),
            "transaction": tx,
        }

    def monitor_keyboard_touch(self, duration_sec: float = 8.0) -> Dict[str, object]:
        """
        Listen for physical keystrokes (`Note On/Off`), `Modulation Wheel (CC#1)`, `Sustain (CC#64)`,
        and `Knobs [A..D]` (`CC#74, 71, 73, 75, 16, 17, 91, 93`) from the Yamaha MX61.
        """
        listen_ms = max(500, int(duration_sec * 1000))
        tx = self.execute_transaction([], inter_packet_delay_ms=10, listen_window_ms=listen_ms)

        notes: List[Dict[str, int]] = []
        controllers: List[Dict[str, int]] = []
        sysex_events: List[Dict[str, object]] = []

        for ev in tx.get("rx_events", []):  # type: ignore[union-attr]
            if ev.get("kind") == "SHORT":
                raw = bytes.fromhex(ev["hex"])
                st = raw[0] & 0xF0
                ch = (raw[0] & 0x0F) + 1
                d1, d2 = raw[1], raw[2]
                if st == 0x90 and d2 > 0:
                    notes.append({"channel": ch, "note": d1, "velocity": d2})
                elif st == 0xB0:
                    controllers.append({"channel": ch, "cc": d1, "value": d2})
            elif ev.get("kind") == "SYSEX":
                sysex_events.append(ev.get("parsed", {}))

        velocities = [n["velocity"] for n in notes]
        return {
            "duration_sec": duration_sec,
            "notes_count": len(notes),
            "velocity_min": min(velocities) if velocities else None,
            "velocity_max": max(velocities) if velocities else None,
            "velocity_mean": round(sum(velocities) / len(velocities), 1) if velocities else None,
            "notes": notes,
            "controllers": controllers,
            "sysex_events": sysex_events,
        }

    @staticmethod
    def build_61key_acoustic_probe_packets(
        channel_0_to_15: int = 0,
        test_mod_wheel_layer: bool = False,
    ) -> Tuple[List[Union[bytes, str]], int]:
        """
        Build a deterministic multi-register acoustic piano test sequence tailored to the
        Yamaha MX61's 61-key range (`C1=36` .. `C6=96`):
          1. Sustain Pedal ON (`CC#64 = 127`)
          2. Warm 9-ft Bass & Woody Midrange Arpeggio (`C2=48, G2=55, C3=60, E3=64, G3=67, C4=72, E4=76, G4=79, C5=84`)
          3. Dynamic Hammer Presence Chord (`C4-E4-G4-C5` at `ff` velocity `108`)
          4. Optional Modulation Wheel sweep (`CC#1 = 96`) to test Secondary Layer blend
          5. Sustain release & tail capture.
        Returns `(packets, total_duration_ms)`.
        """
        ch = channel_0_to_15 & 0x0F
        pkts: List[Union[bytes, str]] = [
            # Ensure Volume=127, Expression=127, MW=0 initially
            bytes([0xB0 | ch, 0x07, 127]),
            bytes([0xB0 | ch, 0x0B, 127]),
            bytes([0xB0 | ch, 0x01, 92 if test_mod_wheel_layer else 0]),
            bytes([0xB0 | ch, 0x40, 127]),  # Sustain ON
            "SLEEP:120",
        ]

        probe_notes = [
            (48, 86, 220),   # C2 (Bass Body 130 Hz)
            (55, 84, 220),   # G2 (Low-Mid 196 Hz)
            (60, 88, 220),   # C3 (Woody Warmth 261 Hz)
            (64, 86, 220),   # E3 (329 Hz)
            (67, 90, 220),   # G3 (392 Hz)
            (72, 94, 220),   # C4 (523 Hz)
            (76, 98, 220),   # E4 (659 Hz)
            (79, 102, 220),  # G4 (784 Hz)
            (84, 106, 350),  # C5 (1046 Hz)
        ]
        for note, vel, wait_ms in probe_notes:
            pkts.append(bytes([0x90 | ch, note, vel]))
            pkts.append(f"SLEEP:{wait_ms}")

        # Let sustain ring for 1100 ms, then release
        pkts.append("SLEEP:1100")
        for note, _, _ in probe_notes:
            pkts.append(bytes([0x80 | ch, note, 0]))
        pkts.append(bytes([0xB0 | ch, 0x40, 0]))  # Sustain OFF
        pkts.append(bytes([0xB0 | ch, 0x01, 0]))  # Reset MW
        pkts.append("SLEEP:450")

        total_duration_ms = 3900
        return pkts, total_duration_ms

    def capture_acoustic_probe(
        self,
        wav_path: Union[str, Path],
        setup_packets: Optional[Sequence[Union[bytes, str]]] = None,
        sample_rate: int = 44100,
        test_mod_wheel_layer: bool = False,
    ) -> Dict[str, object]:
        """
        Send `setup_packets` (e.g., Voice/Performance Edit Buffer Bulk Dump) to the MX61,
        then record stereo digital USB-Audio (`44.1kHz` or `48kHz` 16-bit PCM) directly from the MX61's
        built-in USB audio interface while playing the 61-key acoustic probe sequence.
        """
        out_wav = Path(wav_path).resolve()
        out_wav.parent.mkdir(parents=True, exist_ok=True)

        if setup_packets:
            self.execute_transaction(setup_packets, inter_packet_delay_ms=18, listen_window_ms=350)

        probe_pkts, duration_ms = self.build_61key_acoustic_probe_packets(
            channel_0_to_15=0,
            test_mod_wheel_layer=test_mod_wheel_layer,
        )

        if not self.has_wsl_powershell or self.wsl_work_dir is None or self.win_work_dir is None or self.exe_win_path is None:
            return {
                "ok": False,
                "offline": True,
                "wav_path": str(out_wav),
                "hint": "Windows USB-Audio bridge not available on this host; use offline synthesizer or run from WSL2/Windows.",
            }

        pkt_file_wsl = self.wsl_work_dir / "probe_packets.txt"
        pkt_file_win = f"{self.win_work_dir}\\probe_packets.txt"
        win_wav_tmp = f"{self.win_work_dir}\\capture_tmp.wav"
        wsl_wav_tmp = self.wsl_work_dir / "capture_tmp.wav"

        hex_lines: List[str] = []
        for pkt in probe_pkts:
            if isinstance(pkt, str):
                hex_lines.append(pkt.strip().upper())
            else:
                hex_lines.append(bytes(pkt).hex().upper())
        pkt_file_wsl.write_text("\n".join(hex_lines) + "\n", encoding="ascii")

        cmd = f"& '{self.exe_win_path}' record '{win_wav_tmp}' {duration_ms} {int(sample_rate)} '{pkt_file_win}' 10"
        proc = subprocess.run(
            [POWERSHELL_EXE, "-NoProfile", "-Command", cmd],
            capture_output=True,
            text=True,
            check=True,
        )

        for raw_line in proc.stdout.splitlines():
            line = raw_line.strip()
            if line.startswith("ERROR:"):
                raise Mx61BridgeError(f"Audio capture failed: {line}")

        if not wsl_wav_tmp.exists():
            raise Mx61BridgeError("Audio capture finished without producing WAV file.")

        shutil.copyfile(wsl_wav_tmp, out_wav)
        return {
            "ok": True,
            "wav_path": str(out_wav),
            "sample_rate": sample_rate,
            "duration_ms": duration_ms,
            "stdout": proc.stdout.strip(),
        }
