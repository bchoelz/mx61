#!/usr/bin/env python3
"""
Yamaha MX61 Hardware-in-the-Loop Acoustic Engineering & Layer Synthesis CLI (`src/mx61_cli.py`).

Commands:
  - `list-profiles`: List all engineered MX61 8-Element `User Voice` & 16-Part `Performance` profiles
  - `export-syx`: Export `.syx` Bulk Dump files (`presets/`) for volatile Edit Buffer preview and User slots
  - `ping`: Verify bidirectional USB-MIDI (`Yamaha MX49/MX61-1`) & built-in USB-Audio (`Yamaha MX49/MX61`)
  - `full-backup`: Backup `SYSTEM` + 128 User Voices + 8 User Drum Kits + 128 Performances (`backups/full_initial/`)
  - `restore-backup`: Restore any `.syx` backup or snapshot file to the MX61
  - `scan-slots`: Scan `U001..U128` (`0E 0A nn`) to locate empty `"Initialize"` User Voice slots (zero factory overwrite!)
  - `inspect-preset`: Request and decode the 8-Element architecture of any factory Preset Voice (`PRE1..PRE8`)
  - `check-touch`: Monitor physical keystrokes, velocity range, Modulation Wheel (`CC#1`), and Knobs (`CC#74..17`)
  - `preview`: Load a profile non-destructively into the volatile RAM Edit Buffer (`0E 0F 00` / `0E 5F 00`)
  - `store-voice`: Save a custom 8-Element Voice into a User Voice slot `U001..U128` (with automatic rollback snapshot)
  - `store-perf`: Save a custom 16-Part Performance into a User Performance slot `001..128` (with automatic snapshot)
  - `analyze-wav`: Compare any captured WAV against a target reference (`captures/ref_*.wav`) using 7-Band + Fuzzy/Pareto DSP
  - `auto-calibrate`: Run closed-loop USB-MIDI + Built-in USB-Audio acoustic calibration against a target reference WAV
  - `download-ref`: Download a reference piano WAV from YouTube via `yt-dlp` + `ffmpeg`
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Dict, List, Optional

from acoustic_analyzer import (
    compare_mx61_to_reference,
    download_youtube_reference_wav,
    extract_acoustic_signature,
)
from midi_bridge import Mx61Bridge
from mx61_profiles import PROFILES, Mx61AcousticProfile

REPO_ROOT = Path(__file__).resolve().parent.parent
PRESETS_DIR = REPO_ROOT / "presets"
CAPTURES_DIR = REPO_ROOT / "captures"


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_list_profiles(_args: argparse.Namespace) -> int:
    rows: List[Dict[str, object]] = []
    for pid, prof in PROFILES.items():
        active_elems = [e.index + 1 for e in prof.elements if e.enabled]
        mw_elems = []
        for cs in prof.controller_sets:
            if cs.source == 1:  # MW
                mw_elems.extend(e + 1 for e in cs.active_elements_0_to_7)
        rows.append({
            "profile_id": pid,
            "voice_name": prof.voice_name.strip(),
            "performance_name": prof.performance_name.strip(),
            "recommended_user_voice_slot": (
                f"U{prof.recommended_user_voice_slot_1_to_128:03d}"
                if prof.recommended_user_voice_slot_1_to_128
                else "Read-Only Baseline"
            ),
            "active_elements": active_elems,
            "mw_controlled_elements": sorted(set(mw_elems)),
            "performance_layer_mode": prof.enable_performance_layer,
            "master_eq_5band_db": {
                "low": prof.eq_low.gain_db,
                "lowmid": prof.eq_lowmid.gain_db,
                "mid": prof.eq_mid.gain_db,
                "himid": prof.eq_himid.gain_db,
                "high": prof.eq_high.gain_db,
            },
            "description": prof.description,
        })
    _print_json({"count": len(rows), "profiles": rows})
    return 0


def _export_single_profile(prof: Mx61AcousticProfile, out_dir: Path) -> Dict[str, object]:
    out_dir.mkdir(parents=True, exist_ok=True)
    vpatch = prof.build_voice_patch()
    u_slot = prof.recommended_user_voice_slot_1_to_128 or 1
    p_slot = prof.recommended_performance_slot_1_to_128 or 1

    # 1. Volatile Voice Edit Buffer (`0E 0F 00`)
    v_edit_pkts = vpatch.to_bulk_messages(target_mm=0x0F, target_nn=0x00)
    v_edit_path = out_dir / f"{prof.profile_id}_voice_editbuf.syx"
    v_edit_path.write_bytes(b"".join(v_edit_pkts))

    # 2. User Voice Slot `U001..U128` (`0E 0A nn`)
    v_user_pkts = vpatch.to_bulk_messages(target_mm=0x0A, target_nn=u_slot - 1)
    v_user_path = out_dir / f"{prof.profile_id}_user_voice_U{u_slot:03d}.syx"
    v_user_path.write_bytes(b"".join(v_user_pkts))

    # 3. Volatile Performance Edit Buffer (`0E 5F 00`) + Mixing Part 1 Voice Edit Buffer (`0E 30 00`)
    ppatch = prof.build_performance_patch(
        user_voice_slot_1_to_128=prof.recommended_user_voice_slot_1_to_128
    )
    p_edit_pkts = ppatch.to_bulk_messages(target_mm=0x5F, target_nn=0x00)
    p_part1_pkts = vpatch.to_bulk_messages(target_mm=0x30, target_nn=0x00)
    p_edit_path = out_dir / f"{prof.profile_id}_perf_editbuf.syx"
    p_edit_path.write_bytes(b"".join(p_edit_pkts + p_part1_pkts))

    # 4. User Performance Slot `P001..P128` (`0E 50 nn`)
    p_user_pkts = ppatch.to_bulk_messages(target_mm=0x50, target_nn=p_slot - 1)
    p_user_path = out_dir / f"{prof.profile_id}_user_perf_P{p_slot:03d}.syx"
    p_user_path.write_bytes(b"".join(p_user_pkts))

    return {
        "profile_id": prof.profile_id,
        "voice_name": vpatch.name,
        "performance_name": ppatch.name,
        "voice_editbuf_syx": str(v_edit_path),
        "user_voice_syx": str(v_user_path),
        "perf_editbuf_syx": str(p_edit_path),
        "user_perf_syx": str(p_user_path),
        "voice_packets": len(v_edit_pkts),
        "perf_packets": len(p_edit_pkts),
    }


def cmd_export_syx(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir) if args.out_dir else PRESETS_DIR
    exported: List[Dict[str, object]] = []
    if args.all:
        for prof in PROFILES.values():
            exported.append(_export_single_profile(prof, out_dir))
    else:
        if args.profile not in PROFILES:
            print(f"Unknown profile '{args.profile}'. Choices: {', '.join(PROFILES)}", file=sys.stderr)
            return 1
        exported.append(_export_single_profile(PROFILES[args.profile], out_dir))
    _print_json({"exported_count": len(exported), "files": exported})
    return 0


def cmd_ping(_args: argparse.Namespace) -> int:
    bridge = Mx61Bridge()
    _print_json(bridge.ping_mx61())
    return 0


def cmd_full_backup(args: argparse.Namespace) -> int:
    bridge = Mx61Bridge()
    res = bridge.full_backup(backup_dir=args.out_dir, max_performances=args.max_performances)
    _print_json(res)
    return 0


def cmd_restore_backup(args: argparse.Namespace) -> int:
    bridge = Mx61Bridge()
    res = bridge.restore_syx_file(args.syx_file)
    _print_json(res)
    return 0


def cmd_scan_slots(args: argparse.Namespace) -> int:
    bridge = Mx61Bridge()
    voices = bridge.scan_user_voices(start_slot_1_to_128=args.start, end_slot_1_to_128=args.end)
    _print_json(voices)
    return 0


def cmd_inspect_preset(args: argparse.Namespace) -> int:
    bridge = Mx61Bridge()
    patch, raw_msgs = bridge.fetch_voice_patch(
        preset_bank_1_to_8=args.bank,
        preset_program_0_to_127=args.program - 1,
    )
    elements = [patch.get_element_summary(ee) for ee in range(8)]
    _print_json({
        "preset": f"PRE{args.bank}:{args.program:03d}",
        "name": patch.name,
        "category_id": patch.category_id,
        "volume": patch.volume,
        "blocks_received": len(raw_msgs),
        "elements": elements,
    })
    return 0


def cmd_check_touch(args: argparse.Namespace) -> int:
    bridge = Mx61Bridge()
    _print_json(bridge.monitor_keyboard_touch(duration_sec=args.duration))
    return 0


def cmd_preview(args: argparse.Namespace) -> int:
    if args.profile not in PROFILES:
        print(f"Unknown profile '{args.profile}'. Choices: {', '.join(PROFILES)}", file=sys.stderr)
        return 1
    prof = PROFILES[args.profile]
    vpatch = prof.build_voice_patch()
    ppatch = prof.build_performance_patch(user_voice_slot_1_to_128=prof.recommended_user_voice_slot_1_to_128)

    # Send Performance Edit Buffer (`0E 5F 00`) + Part 1 Mixing Voice Edit Buffer (`0E 30 00`)
    pkts = ppatch.to_bulk_messages(target_mm=0x5F, target_nn=0x00) + vpatch.to_bulk_messages(target_mm=0x30, target_nn=0x00)
    bridge = Mx61Bridge()
    tx = bridge.execute_transaction(pkts, inter_packet_delay_ms=18, listen_window_ms=300)
    _print_json({
        "action": "PREVIEW_VOLATILE_RAM_EDIT_BUFFER",
        "profile_id": prof.profile_id,
        "voice_name": vpatch.name,
        "performance_name": ppatch.name,
        "packets_sent": len(pkts),
        "zero_factory_overwrite": True,
        "transaction": tx,
    })
    return 0


def cmd_store_voice(args: argparse.Namespace) -> int:
    if args.profile not in PROFILES:
        print(f"Unknown profile '{args.profile}'.", file=sys.stderr)
        return 1
    prof = PROFILES[args.profile]
    bridge = Mx61Bridge()

    slot_num = args.slot
    if slot_num is None:
        scan = bridge.scan_user_voices(1, 32)
        slot_num = scan.get("first_available_slot") or prof.recommended_user_voice_slot_1_to_128 or 1

    slot_idx = max(0, min(127, int(slot_num) - 1))

    # 1. Take automatic snapshot of target User Voice slot before writing
    snap_path = bridge.save_slot_snapshot("voice", slot_idx)

    # 2. Check if slot is non-empty and `--force` was not passed
    existing_patch, existing_msgs = bridge.fetch_voice_patch(user_slot_0_to_127=slot_idx)
    if existing_msgs and existing_patch.name and not existing_patch.name.lower().startswith("init") and not args.force:
        _print_json({
            "ok": False,
            "error": f"User Voice slot U{slot_idx + 1:03d} already contains '{existing_patch.name}'. Use --force or pick an empty Initialize slot.",
            "snapshot_saved": str(snap_path) if snap_path else None,
        })
        return 1

    vpatch = prof.build_voice_patch()
    pkts = vpatch.to_bulk_messages(target_mm=0x0A, target_nn=slot_idx)
    tx = bridge.execute_transaction(pkts, inter_packet_delay_ms=20, listen_window_ms=400)
    _print_json({
        "ok": True,
        "stored_user_voice_slot": f"U{slot_idx + 1:03d}",
        "bank_select": {"msb": 63, "lsb": 8, "program_0_to_127": slot_idx},
        "profile_id": prof.profile_id,
        "voice_name": vpatch.name,
        "snapshot_saved": str(snap_path) if snap_path else None,
        "packets_sent": len(pkts),
        "transaction": tx,
    })
    return 0


def cmd_store_perf(args: argparse.Namespace) -> int:
    if args.profile not in PROFILES:
        print(f"Unknown profile '{args.profile}'.", file=sys.stderr)
        return 1
    prof = PROFILES[args.profile]
    bridge = Mx61Bridge()

    slot_num = args.slot or prof.recommended_performance_slot_1_to_128 or 1
    slot_idx = max(0, min(127, int(slot_num) - 1))
    voice_slot = args.voice_slot or prof.recommended_user_voice_slot_1_to_128

    snap_path = bridge.save_slot_snapshot("performance", slot_idx)
    ppatch = prof.build_performance_patch(user_voice_slot_1_to_128=voice_slot)
    pkts = ppatch.to_bulk_messages(target_mm=0x50, target_nn=slot_idx)
    tx = bridge.execute_transaction(pkts, inter_packet_delay_ms=20, listen_window_ms=450)
    _print_json({
        "ok": True,
        "stored_performance_slot": f"P{slot_idx + 1:03d}",
        "linked_user_voice_slot": f"U{voice_slot:03d}" if voice_slot else "Preset Voice",
        "profile_id": prof.profile_id,
        "performance_name": ppatch.name,
        "snapshot_saved": str(snap_path) if snap_path else None,
        "packets_sent": len(pkts),
        "transaction": tx,
    })
    return 0


def cmd_analyze_wav(args: argparse.Namespace) -> int:
    prof = PROFILES.get(args.profile) if args.profile else None
    if args.ref:
        res = compare_mx61_to_reference(args.wav, args.ref, current_profile=prof)
    else:
        res = extract_acoustic_signature(args.wav)
    _print_json(res)
    return 0


def cmd_auto_calibrate(args: argparse.Namespace) -> int:
    if args.profile not in PROFILES:
        print(f"Unknown profile '{args.profile}'.", file=sys.stderr)
        return 1
    prof = PROFILES[args.profile]
    ref_path = Path(args.ref)
    if not ref_path.exists():
        print(f"Reference WAV not found: {ref_path}", file=sys.stderr)
        return 1

    bridge = Mx61Bridge()
    history: List[Dict[str, object]] = []

    for it in range(1, max(1, int(args.iterations)) + 1):
        vpatch = prof.build_voice_patch()
        ppatch = prof.build_performance_patch(user_voice_slot_1_to_128=prof.recommended_user_voice_slot_1_to_128)
        setup_pkts = (
            ppatch.to_bulk_messages(target_mm=0x5F, target_nn=0x00)
            + vpatch.to_bulk_messages(target_mm=0x30, target_nn=0x00)
        )
        cap_wav = CAPTURES_DIR / f"mx61_{prof.profile_id}_iter{it}.wav"
        cap_res = bridge.capture_acoustic_probe(cap_wav, setup_packets=setup_pkts, sample_rate=44100)
        if not cap_res.get("ok"):
            _print_json({"ok": False, "iteration": it, "capture": cap_res})
            return 1

        cmp_res = compare_mx61_to_reference(cap_wav, ref_path, current_profile=prof)
        rec = cmp_res["recommendations"]  # type: ignore[index]
        eq_deltas = rec["master_eq_5band_deltas_db"]  # type: ignore[index]
        vp_deltas = rec["voice_and_part_deltas"]      # type: ignore[index]

        history.append({
            "iteration": it,
            "captured_wav": str(cap_wav),
            "similarity_score_pct": cmp_res["similarity_score_pct"],
            "spectral_rmse_db": cmp_res["spectral_rmse_db"],
            "fuzzy_decision": rec["fuzzy_decision"],
            "fuzzy_indices": cmp_res["fuzzy_evaluation"]["fuzzy_indices"],  # type: ignore[index]
            "eq_before": {
                "low": prof.eq_low.gain_db,
                "lowmid": prof.eq_lowmid.gain_db,
                "mid": prof.eq_mid.gain_db,
                "himid": prof.eq_himid.gain_db,
                "high": prof.eq_high.gain_db,
            },
            "recommended_deltas": rec,
        })

        if rec["fuzzy_decision"] in ("STOP_OPTIMAL_MATCH", "STOP_HARDWARE_CEILING"):
            break

        # Apply parsimonious closed-loop updates clamped to [-6..+6 dB]
        prof.eq_low.gain_db = max(-6, min(6, prof.eq_low.gain_db + int(eq_deltas["band1_low_125hz_delta_db"])))
        prof.eq_lowmid.gain_db = max(-6, min(6, prof.eq_lowmid.gain_db + int(eq_deltas["band2_lowmid_315hz_delta_db"])))
        prof.eq_mid.gain_db = max(-6, min(6, prof.eq_mid.gain_db + int(eq_deltas["band3_mid_630hz_delta_db"])))
        prof.eq_himid.gain_db = max(-6, min(6, prof.eq_himid.gain_db + int(eq_deltas["band4_himid_2500hz_delta_db"])))
        prof.eq_high.gain_db = max(-6, min(6, prof.eq_high.gain_db + int(eq_deltas["band5_high_8000hz_delta_db"])))
        prof.part1_cutoff_offset = max(-14, min(14, prof.part1_cutoff_offset + int(vp_deltas["part1_cutoff_offset_step"])))
        prof.part1_decay_offset = max(-16, min(16, prof.part1_decay_offset + int(vp_deltas["part1_decay_offset_step"])))

    _print_json({
        "ok": True,
        "profile_id": prof.profile_id,
        "reference_wav": str(ref_path),
        "iterations_run": len(history),
        "history": history,
    })
    return 0


def cmd_download_ref(args: argparse.Namespace) -> int:
    res = download_youtube_reference_wav(
        url=args.url,
        out_wav=args.out,
        start_sec=args.start,
        duration_sec=args.duration,
    )
    _print_json(res)
    return 0 if res.get("ok") else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Yamaha MX61 Hardware-in-the-Loop Synthesis & Calibration CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-profiles", help="List all MX61 8-Element Voice & Performance profiles")

    p_exp = sub.add_parser("export-syx", help="Export .syx Bulk Dump files into presets/")
    p_exp.add_argument("--profile", default="cfx_concert_pad_mw", help="Profile ID to export")
    p_exp.add_argument("--all", action="store_true", help="Export all profiles")
    p_exp.add_argument("--out-dir", default=None, help="Output directory (default: presets/)")

    sub.add_parser("ping", help="Ping the Yamaha MX61 via USB-MIDI Port 1 and list USB-Audio devices")

    p_bak = sub.add_parser("full-backup", help="Full non-destructive backup of SYSTEM + User Voices + Performances")
    p_bak.add_argument("--out-dir", default=None, help="Backup directory (default: backups/full_initial)")
    p_bak.add_argument("--max-performances", type=int, default=128)

    p_res = sub.add_parser("restore-backup", help="Restore a saved .syx file to the MX61")
    p_res.add_argument("syx_file", help="Path to .syx file")

    p_scan = sub.add_parser("scan-slots", help="Scan User Voice slots U001..U128 for empty Initialize slots")
    p_scan.add_argument("--start", type=int, default=1)
    p_scan.add_argument("--end", type=int, default=32)

    p_insp = sub.add_parser("inspect-preset", help="Inspect the 8-Element structure of any factory Preset Voice")
    p_insp.add_argument("--bank", type=int, default=1, help="Preset Bank 1..8")
    p_insp.add_argument("--program", type=int, default=1, help="Program Number 1..128")

    p_touch = sub.add_parser("check-touch", help="Monitor physical keyboard velocity, MW (CC#1), and Knobs")
    p_touch.add_argument("--duration", type=float, default=8.0)

    p_prev = sub.add_parser("preview", help="Send profile to volatile RAM Edit Buffer (zero overwrite)")
    p_prev.add_argument("--profile", required=True, choices=list(PROFILES.keys()))

    p_sv = sub.add_parser("store-voice", help="Save custom 8-Element Voice to User Voice slot U001..U128")
    p_sv.add_argument("--profile", required=True, choices=list(PROFILES.keys()))
    p_sv.add_argument("--slot", type=int, default=None, help="User Voice slot 1..128 (auto-picks empty Initialize if omitted)")
    p_sv.add_argument("--force", action="store_true", help="Allow overwriting a non-Initialize User Voice slot")

    p_sp = sub.add_parser("store-perf", help="Save custom Performance to User Performance slot 001..128")
    p_sp.add_argument("--profile", required=True, choices=list(PROFILES.keys()))
    p_sp.add_argument("--slot", type=int, default=None, help="Performance slot 1..128")
    p_sp.add_argument("--voice-slot", type=int, default=None, help="User Voice slot 1..128 for Part 1")

    p_ana = sub.add_parser("analyze-wav", help="Analyze a WAV file or compare against a reference WAV")
    p_ana.add_argument("--wav", required=True, help="Captured WAV file")
    p_ana.add_argument("--ref", default=None, help="Optional reference WAV file")
    p_ana.add_argument("--profile", default=None, choices=list(PROFILES.keys()))

    p_cal = sub.add_parser("auto-calibrate", help="Run closed-loop USB-MIDI + Built-in USB-Audio calibration")
    p_cal.add_argument("--profile", default="cfx_concert_grand", choices=list(PROFILES.keys()))
    p_cal.add_argument("--ref", default=str(CAPTURES_DIR / "ref_yamaha_cfx.wav"))
    p_cal.add_argument("--iterations", type=int, default=3)

    p_dl = sub.add_parser("download-ref", help="Download a reference WAV from YouTube")
    p_dl.add_argument("--url", required=True)
    p_dl.add_argument("--out", required=True)
    p_dl.add_argument("--start", type=float, default=0.0)
    p_dl.add_argument("--duration", type=float, default=15.0)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    dispatch = {
        "list-profiles": cmd_list_profiles,
        "export-syx": cmd_export_syx,
        "ping": cmd_ping,
        "full-backup": cmd_full_backup,
        "restore-backup": cmd_restore_backup,
        "scan-slots": cmd_scan_slots,
        "inspect-preset": cmd_inspect_preset,
        "check-touch": cmd_check_touch,
        "preview": cmd_preview,
        "store-voice": cmd_store_voice,
        "store-perf": cmd_store_perf,
        "analyze-wav": cmd_analyze_wav,
        "auto-calibrate": cmd_auto_calibrate,
        "download-ref": cmd_download_ref,
    }
    return dispatch[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
