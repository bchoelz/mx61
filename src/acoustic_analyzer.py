#!/usr/bin/env python3
"""
Yamaha MX61 Hardware-in-the-Loop Acoustic Analyzer & Reference Comparator (`src/acoustic_analyzer.py`).

Performs mathematical DSP spectral & temporal analysis using `numpy` (or stdlib radix-2 FFT fallback) on:
  1. Stereo 44.1kHz / 48kHz WAV recordings captured directly from the Yamaha MX61's built-in
     USB-Audio interface (`USB [TO HOST]` — zero analog conversion losses).
  2. Reference audio extracted from flagship pianos (`captures/ref_yamaha_cfx.wav`,
     `captures/ref_kawai_sk_ex.wav`, `captures/ref_nord_white_grand_soft.wav`,
     `captures/ref_kurzweil_stage_grand.wav`, or YouTube URLs).

Computes:
  - 7-Band Acoustic Piano Spectral Balance (normalized to the 400–1000 Hz woody midrange anchor):
      1. Sub-Bass (40 - 100 Hz)
      2. Bass Body (100 - 200 Hz)        -> Maps to MX61 Master EQ Band 1 (`Low`: 100/125/160 Hz)
      3. Low-Mid Boxiness (200 - 400 Hz) -> Maps to MX61 Master EQ Band 2 (`Low-Mid`: 250/315 Hz, `Q=1.4..2.0`)
      4. Woody Warmth (400 - 1000 Hz)    -> Reference 0.0 dB anchor + MX61 Master EQ Band 3 (`Mid`: 630 Hz)
      5. Hammer Presence (1.2 - 3.2 kHz) -> Maps to MX61 Master EQ Band 4 (`High-Mid`: 2.0/2.5 kHz) + Element Cutoff
      6. Brilliance (3.2 - 6.5 kHz)      -> Maps to Element Filter Cutoff + Breakpoint Scaling (`BP3/BP4`)
      7. Air & Shimmer (6.5 - 14.0 kHz)  -> Maps to MX61 Master EQ Band 5 (`High`: 8.0/10.0 kHz)
  - Fuzzy Logic Perceptual & Parsimony Evaluator (`mu_character_affinity`, `mu_hardware_naturalness`,
    `mu_parsimony`, `fuzzy_pareto_satisfaction`)
  - Closed-Loop Auto-Tuning Recommendations mapped directly to the MX61's 5-Band Parametric Master EQ
    (`36 10 00..13`) and Element / Part offsets (`37 00 23..2E`).
"""

from __future__ import annotations

import array
import cmath
import math
from pathlib import Path
import subprocess
from typing import Dict, List, Optional, Tuple, Union
import wave

try:
    import numpy as np  # type: ignore[import-not-found]
except ImportError:
    np = None  # type: ignore[assignment]

from mx61_profiles import Mx61AcousticProfile

_FFT_PLAN_CACHE: Dict[int, Tuple[List[int], List[Tuple[int, int, List[complex]]], List[float], List[float]]] = {}


def _get_stdlib_fft_plan(
    win_size: int, sr: int
) -> Tuple[List[int], List[Tuple[int, int, List[complex]]], List[float], List[float]]:
    key = (win_size << 20) ^ sr
    if key in _FFT_PLAN_CACHE:
        return _FFT_PLAN_CACHE[key]
    bits = int(round(math.log2(win_size)))
    rev = [0] * win_size
    for i in range(win_size):
        b = 0
        x = i
        for _ in range(bits):
            b = (b << 1) | (x & 1)
            x >>= 1
        rev[i] = b
    stages: List[Tuple[int, int, List[complex]]] = []
    step = 1
    while step < win_size:
        half = step
        step <<= 1
        w_step = cmath.exp(-1j * math.pi / half)
        w_list = [1.0 + 0j]
        w = 1.0 + 0j
        for _ in range(1, half):
            w *= w_step
            w_list.append(w)
        stages.append((half, step, w_list))
    denom = float(max(1, win_size - 1))
    window = [0.5 - 0.5 * math.cos(2.0 * math.pi * i / denom) for i in range(win_size)]
    freqs = [i * (float(sr) / float(win_size)) for i in range(win_size // 2 + 1)]
    plan = (rev, stages, window, freqs)
    _FFT_PLAN_CACHE[key] = plan
    return plan


def _stdlib_rfft_mag_sq(
    seg: List[float],
    window: List[float],
    rev: List[int],
    stages: List[Tuple[int, int, List[complex]]],
    win_size: int,
) -> List[float]:
    buf = [seg[rev[i]] * window[rev[i]] + 0j for i in range(win_size)]
    for half, step, w_list in stages:
        for i in range(0, win_size, step):
            for j in range(half):
                t = w_list[j] * buf[i + j + half]
                u = buf[i + j]
                buf[i + j] = u + t
                buf[i + j + half] = u - t
    inv_n = 1.0 / float(win_size)
    return [((c.real * c.real + c.imag * c.imag) * inv_n) for c in buf[: win_size // 2 + 1]]


ACOUSTIC_BANDS: List[Tuple[str, float, float]] = [
    ("sub_bass_40_100hz", 40.0, 100.0),
    ("bass_body_100_200hz", 100.0, 200.0),
    ("lowmid_box_200_400hz", 200.0, 400.0),
    ("woody_warmth_400_1000hz", 400.0, 1000.0),
    ("hammer_presence_1200_3200hz", 1200.0, 3200.0),
    ("brilliance_3200_6500hz", 3200.0, 6500.0),
    ("air_6500_14000hz", 6500.0, 14000.0),
]


def load_wav_stereo(path: Union[str, Path]) -> Tuple[int, "np.ndarray"]:
    wav_path = Path(path)
    with wave.open(str(wav_path), "rb") as wf:
        channels = wf.getnchannels()
        sample_rate = wf.getframerate()
        sampwidth = wf.getsampwidth()
        nframes = wf.getnframes()
        raw = wf.readframes(nframes)

    if sampwidth == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    elif sampwidth == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        signed = (
            b[:, 0].astype(np.int32)
            | (b[:, 1].astype(np.int32) << 8)
            | (b[:, 2].astype(np.int8).astype(np.int32) << 16)
        )
        data = signed.astype(np.float64) / 8388608.0
    elif sampwidth == 4:
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float64) / 2147483648.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {sampwidth} bytes")

    if channels == 1:
        stereo = np.column_stack([data, data])
    else:
        stereo = data.reshape(-1, channels)[:, :2]
    return sample_rate, stereo


def _load_wav_stereo_lists(path: Union[str, Path]) -> Tuple[int, List[float], List[float]]:
    wav_path = Path(path)
    with wave.open(str(wav_path), "rb") as wf:
        channels = wf.getnchannels()
        sample_rate = wf.getframerate()
        sampwidth = wf.getsampwidth()
        nframes = wf.getnframes()
        raw = wf.readframes(nframes)

    if sampwidth == 2:
        arr = array.array("h")
        arr.frombytes(raw)
        inv = 1.0 / 32768.0
        if channels == 1:
            left = [x * inv for x in arr]
            right = list(left)
        else:
            left = [x * inv for x in arr[0::channels]]
            right = [x * inv for x in arr[1::channels]]
    elif sampwidth == 4:
        arr = array.array("i")
        arr.frombytes(raw)
        inv = 1.0 / 2147483648.0
        if channels == 1:
            left = [x * inv for x in arr]
            right = list(left)
        else:
            left = [x * inv for x in arr[0::channels]]
            right = [x * inv for x in arr[1::channels]]
    else:
        raise ValueError(f"Unsupported WAV sample width without numpy: {sampwidth} bytes")
    return sample_rate, left, right


def _build_usb_audio_gain_warnings(peak_dbfs: float, lr_balance_db: float) -> List[str]:
    warnings: List[str] = []
    if peak_dbfs > -0.8:
        warnings.append(
            f"RISCO DE CLIPPING DIGITAL ({peak_dbfs:.1f} dBFS): reduza `Performance Volume` ou `Part Volume` "
            "para ~118-122 ou modere ganhos positivos no Master EQ de 5 bandas."
        )
    elif peak_dbfs < -20.0:
        warnings.append(
            f"SINAL USB-AUDIO BAIXO ({peak_dbfs:.1f} dBFS): verifique `Utility -> USB Audio Volume` no MX61 "
            "ou suba `Part Volume` / `Voice Volume`."
        )
    if abs(lr_balance_db) > 2.5:
        heavier = "Esquerdo (L)" if lr_balance_db > 0 else "Direito (R)"
        warnings.append(
            f"ASSIMETRIA ESTÉREO ({lr_balance_db:+.2f} dB mais forte no canal {heavier}): "
            "verifique o Pan dos Elements 1..8 ou Part Pan."
        )
    return warnings


def _extract_acoustic_signature_stdlib(wav_path: Union[str, Path]) -> Dict[str, object]:
    sr, left, right = _load_wav_stereo_lists(wav_path)
    n_samples = len(left)
    mono = [(l + r) * 0.5 for l, r in zip(left, right)]
    duration_sec = n_samples / float(sr) if sr > 0 else 0.0

    eps = 1e-12
    peak_lin = max(max((abs(x) for x in left), default=0.0), max((abs(x) for x in right), default=0.0))
    rms_lin = math.sqrt(sum(x * x for x in mono) / max(1, n_samples)) if n_samples > 0 else 0.0
    peak_dbfs = 20.0 * math.log10(max(eps, peak_lin))
    rms_dbfs = 20.0 * math.log10(max(eps, rms_lin))

    win_size = min(4096, max(512, 1 << int(math.log2(max(512, n_samples // 4)))))
    hop_size = win_size // 2
    rev, stages, window, freqs = _get_stdlib_fft_plan(win_size, sr)
    n_bins = len(freqs)

    frame_rms_db: List[float] = []
    frame_centroids: List[float] = []
    active_psd_accum = [0.0] * n_bins
    active_frames = 0

    for start in range(0, max(1, n_samples - win_size + 1), hop_size):
        seg = mono[start : start + win_size]
        if len(seg) < win_size:
            seg = seg + [0.0] * (win_size - len(seg))
        f_rms = math.sqrt(sum(x * x for x in seg) / float(win_size))
        f_db = 20.0 * math.log10(max(eps, f_rms))
        frame_rms_db.append(f_db)

        mag_sq = _stdlib_rfft_mag_sq(seg, window, rev, stages, win_size)
        mag = [math.sqrt(m) for m in mag_sq]
        mag_sum = sum(mag)
        centroid = sum(f * m for f, m in zip(freqs, mag)) / mag_sum if mag_sum > eps else 0.0
        frame_centroids.append(centroid)

        if f_db > (rms_dbfs - 22.0):
            for bi in range(n_bins):
                active_psd_accum[bi] += mag_sq[bi]
            active_frames += 1

    if active_frames == 0 and n_samples > 0:
        seg = mono[:win_size] + [0.0] * max(0, win_size - len(mono))
        active_psd_accum = _stdlib_rfft_mag_sq(seg, window, rev, stages, win_size)
        active_frames = 1

    inv_active = 1.0 / float(max(1, active_frames))
    mean_psd = [v * inv_active for v in active_psd_accum]

    raw_band_db: Dict[str, float] = {}
    for b_name, f_lo, f_hi in ACOUSTIC_BANDS:
        vals = [mean_psd[i] for i, f in enumerate(freqs) if f_lo <= f < f_hi]
        band_power = (sum(vals) / float(len(vals))) if vals else eps
        raw_band_db[b_name] = 10.0 * math.log10(max(eps, band_power))

    anchor_db = raw_band_db.get("woody_warmth_400_1000hz", -60.0)
    relative_bands_db = {k: round(v - anchor_db, 2) for k, v in raw_band_db.items()}

    if frame_rms_db:
        sorted_rms = sorted(frame_rms_db)
        idx10 = (len(sorted_rms) - 1) * 0.10
        lo_i = int(math.floor(idx10))
        hi_i = int(math.ceil(idx10))
        frac = idx10 - lo_i
        noise_floor_dbfs = sorted_rms[lo_i] * (1.0 - frac) + sorted_rms[hi_i] * frac
    else:
        noise_floor_dbfs = -90.0

    onset_indices: List[int] = []
    for i, r_val in enumerate(frame_rms_db):
        diff = 0.0 if i == 0 else (r_val - frame_rms_db[i - 1])
        if diff > 4.5 and r_val > rms_dbfs - 15.0:
            onset_indices.append(i)
    if not onset_indices and frame_rms_db:
        onset_indices = [max(range(len(frame_rms_db)), key=lambda idx: frame_rms_db[idx])]

    attack_centroids: List[float] = []
    sustain_centroids: List[float] = []
    for idx in onset_indices:
        attack_centroids.append(frame_centroids[idx])
        sus_start = min(len(frame_centroids) - 1, idx + 4)
        sus_end = min(len(frame_centroids), idx + 12)
        if sus_end > sus_start:
            sub = frame_centroids[sus_start:sus_end]
            sustain_centroids.append(sum(sub) / float(len(sub)))

    mean_cent = (sum(frame_centroids) / float(len(frame_centroids))) if frame_centroids else 0.0
    attack_centroid_hz = (sum(attack_centroids) / float(len(attack_centroids))) if attack_centroids else mean_cent
    sustain_centroid_hz = (sum(sustain_centroids) / float(len(sustain_centroids))) if sustain_centroids else mean_cent

    decay_slope_db_per_sec = -8.0
    if len(frame_rms_db) >= 6:
        peak_idx = max(range(len(frame_rms_db)), key=lambda idx: frame_rms_db[idx])
        tail = frame_rms_db[peak_idx:]
        valid_len = 0
        for val in tail:
            if val > noise_floor_dbfs + 6.0:
                valid_len += 1
            else:
                break
        if valid_len >= 4:
            frame_dt = hop_size / float(sr)
            t_vec = [i * frame_dt for i in range(valid_len)]
            y_vec = tail[:valid_len]
            t_mean = sum(t_vec) / float(valid_len)
            y_mean = sum(y_vec) / float(valid_len)
            denom = sum((t - t_mean) ** 2 for t in t_vec)
            if denom > eps:
                decay_slope_db_per_sec = sum((t - t_mean) * (y - y_mean) for t, y in zip(t_vec, y_vec)) / denom

    l_rms = math.sqrt(sum(x * x for x in left) / max(1, n_samples)) if n_samples > 0 else eps
    r_rms = math.sqrt(sum(x * x for x in right) / max(1, n_samples)) if n_samples > 0 else eps
    lr_balance_db = round(20.0 * math.log10(max(eps, l_rms) / max(eps, r_rms)), 2)

    l_mean = sum(left) / max(1, n_samples)
    r_mean = sum(right) / max(1, n_samples)
    l_std = math.sqrt(sum((x - l_mean) ** 2 for x in left) / max(1, n_samples))
    r_std = math.sqrt(sum((x - r_mean) ** 2 for x in right) / max(1, n_samples))
    if l_std > eps and r_std > eps:
        cov = sum((l - l_mean) * (r - r_mean) for l, r in zip(left, right)) / max(1, n_samples)
        stereo_corr = cov / (l_std * r_std)
    else:
        stereo_corr = 1.0

    side_rms = math.sqrt(sum(((l - r) * 0.5) ** 2 for l, r in zip(left, right)) / max(1, n_samples))
    stereo_width_pct = round(min(100.0, (side_rms / max(eps, rms_lin)) * 100.0), 1)
    gain_warnings = _build_usb_audio_gain_warnings(peak_dbfs, lr_balance_db)

    return {
        "file": str(wav_path),
        "sample_rate_hz": sr,
        "duration_sec": round(duration_sec, 2),
        "levels": {
            "peak_dbfs": round(peak_dbfs, 2),
            "rms_dbfs": round(rms_dbfs, 2),
            "noise_floor_dbfs": round(noise_floor_dbfs, 2),
            "dynamic_range_db": round(peak_dbfs - noise_floor_dbfs, 2),
            "lr_balance_db": lr_balance_db,
            "gain_staging_status": "OK_DIGITAL_USB_AUDIO" if not gain_warnings else "CHECK_USB_GAIN",
            "gain_staging_warnings": gain_warnings,
        },
        "spectral_bands_rel_db": relative_bands_db,
        "timbre_dynamics": {
            "attack_centroid_hz": round(attack_centroid_hz, 1),
            "sustain_centroid_hz": round(sustain_centroid_hz, 1),
            "attack_to_sustain_ratio": round(attack_centroid_hz / max(1.0, sustain_centroid_hz), 3),
            "decay_slope_db_per_sec": round(decay_slope_db_per_sec, 2),
        },
        "stereo_field": {
            "lr_correlation": round(stereo_corr, 3),
            "stereo_width_pct": stereo_width_pct,
        },
    }


def extract_acoustic_signature(wav_path: Union[str, Path]) -> Dict[str, object]:
    """Compute the complete spectral, dynamic, transient, and stereo signature of a WAV recording."""
    if np is None:
        return _extract_acoustic_signature_stdlib(wav_path)
    sr, stereo = load_wav_stereo(wav_path)
    mono = 0.5 * (stereo[:, 0] + stereo[:, 1])
    n_samples = len(mono)
    duration_sec = n_samples / float(sr) if sr > 0 else 0.0

    eps = 1e-12
    peak_lin = float(np.max(np.abs(stereo))) if n_samples > 0 else 0.0
    rms_lin = float(np.sqrt(np.mean(mono ** 2))) if n_samples > 0 else 0.0
    peak_dbfs = 20.0 * math.log10(max(eps, peak_lin))
    rms_dbfs = 20.0 * math.log10(max(eps, rms_lin))

    win_size = min(4096, max(512, 1 << int(math.log2(max(512, n_samples // 4)))))
    hop_size = win_size // 2
    window = np.hanning(win_size)
    freqs = np.fft.rfftfreq(win_size, d=1.0 / sr)

    frame_rms_db: List[float] = []
    frame_centroids: List[float] = []
    active_psd_accum = np.zeros(len(freqs), dtype=np.float64)
    active_frames = 0

    for start in range(0, max(1, n_samples - win_size + 1), hop_size):
        seg = mono[start : start + win_size]
        if len(seg) < win_size:
            seg = np.pad(seg, (0, win_size - len(seg)))
        f_rms = float(np.sqrt(np.mean(seg ** 2)))
        f_db = 20.0 * math.log10(max(eps, f_rms))
        frame_rms_db.append(f_db)

        spec = np.fft.rfft(seg * window)
        mag_sq = (np.abs(spec) ** 2) / win_size
        mag = np.sqrt(mag_sq)
        mag_sum = float(np.sum(mag))
        centroid = float(np.sum(freqs * mag) / mag_sum) if mag_sum > eps else 0.0
        frame_centroids.append(centroid)

        if f_db > (rms_dbfs - 22.0):
            active_psd_accum += mag_sq
            active_frames += 1

    if active_frames == 0 and n_samples > 0:
        spec = np.fft.rfft(mono[:win_size] * window)
        active_psd_accum = (np.abs(spec) ** 2) / win_size
        active_frames = 1

    mean_psd = active_psd_accum / max(1, active_frames)

    raw_band_db: Dict[str, float] = {}
    for b_name, f_lo, f_hi in ACOUSTIC_BANDS:
        mask = (freqs >= f_lo) & (freqs < f_hi)
        band_power = float(np.mean(mean_psd[mask])) if np.any(mask) else eps
        raw_band_db[b_name] = 10.0 * math.log10(max(eps, band_power))

    anchor_db = raw_band_db.get("woody_warmth_400_1000hz", -60.0)
    relative_bands_db = {k: round(v - anchor_db, 2) for k, v in raw_band_db.items()}

    rms_arr = np.array(frame_rms_db, dtype=np.float64)
    cent_arr = np.array(frame_centroids, dtype=np.float64)
    noise_floor_dbfs = float(np.percentile(rms_arr, 10)) if len(rms_arr) > 0 else -90.0

    diffs = np.diff(rms_arr, prepend=rms_arr[0])
    onset_indices = np.where((diffs > 4.5) & (rms_arr > rms_dbfs - 15.0))[0]
    if len(onset_indices) == 0 and len(rms_arr) > 0:
        onset_indices = np.array([int(np.argmax(rms_arr))])

    attack_centroids: List[float] = []
    sustain_centroids: List[float] = []
    for idx in onset_indices:
        attack_centroids.append(float(cent_arr[idx]))
        sus_start = min(len(cent_arr) - 1, idx + 4)
        sus_end = min(len(cent_arr), idx + 12)
        if sus_end > sus_start:
            sustain_centroids.append(float(np.mean(cent_arr[sus_start:sus_end])))

    attack_centroid_hz = float(np.mean(attack_centroids)) if attack_centroids else float(np.mean(cent_arr))
    sustain_centroid_hz = float(np.mean(sustain_centroids)) if sustain_centroids else float(np.mean(cent_arr))

    decay_slope_db_per_sec = -8.0
    if len(rms_arr) >= 6:
        peak_idx = int(np.argmax(rms_arr))
        tail = rms_arr[peak_idx:]
        valid_len = 0
        for val in tail:
            if val > noise_floor_dbfs + 6.0:
                valid_len += 1
            else:
                break
        if valid_len >= 4:
            frame_dt = hop_size / float(sr)
            t_vec = np.arange(valid_len, dtype=np.float64) * frame_dt
            y_vec = tail[:valid_len]
            slope, _ = np.polyfit(t_vec, y_vec, 1)
            decay_slope_db_per_sec = float(slope)

    left = stereo[:, 0]
    right = stereo[:, 1]
    l_rms = float(np.sqrt(np.mean(left ** 2))) if n_samples > 0 else eps
    r_rms = float(np.sqrt(np.mean(right ** 2))) if n_samples > 0 else eps
    lr_balance_db = round(20.0 * math.log10(max(eps, l_rms) / max(eps, r_rms)), 2)

    l_std = float(np.std(left))
    r_std = float(np.std(right))
    if l_std > eps and r_std > eps:
        stereo_corr = float(np.mean((left - np.mean(left)) * (right - np.mean(right))) / (l_std * r_std))
    else:
        stereo_corr = 1.0
    side_rms = float(np.sqrt(np.mean((0.5 * (left - right)) ** 2)))
    mid_rms = float(np.sqrt(np.mean(mono ** 2)))
    stereo_width_pct = round(min(100.0, (side_rms / max(eps, mid_rms)) * 100.0), 1)
    gain_warnings = _build_usb_audio_gain_warnings(peak_dbfs, lr_balance_db)

    return {
        "file": str(wav_path),
        "sample_rate_hz": sr,
        "duration_sec": round(duration_sec, 2),
        "levels": {
            "peak_dbfs": round(peak_dbfs, 2),
            "rms_dbfs": round(rms_dbfs, 2),
            "noise_floor_dbfs": round(noise_floor_dbfs, 2),
            "dynamic_range_db": round(peak_dbfs - noise_floor_dbfs, 2),
            "lr_balance_db": lr_balance_db,
            "gain_staging_status": "OK_DIGITAL_USB_AUDIO" if not gain_warnings else "CHECK_USB_GAIN",
            "gain_staging_warnings": gain_warnings,
        },
        "spectral_bands_rel_db": relative_bands_db,
        "timbre_dynamics": {
            "attack_centroid_hz": round(attack_centroid_hz, 1),
            "sustain_centroid_hz": round(sustain_centroid_hz, 1),
            "attack_to_sustain_ratio": round(attack_centroid_hz / max(1.0, sustain_centroid_hz), 3),
            "decay_slope_db_per_sec": round(decay_slope_db_per_sec, 2),
        },
        "stereo_field": {
            "lr_correlation": round(stereo_corr, 3),
            "stereo_width_pct": stereo_width_pct,
        },
    }


def trapmf(x: float, a: float, b: float, c: float, d: float) -> float:
    if b <= x <= c:
        return 1.0
    if x < b:
        if a == b or x <= a:
            return 1.0 if a == b else 0.0
        return max(0.0, min(1.0, (x - a) / float(b - a)))
    if c == d or x >= d:
        return 1.0 if c == d else 0.0
    return max(0.0, min(1.0, (d - x) / float(d - c)))


def fuzzy_plateau_similarity(abs_delta: float, core_tol: float, support_tol: float) -> float:
    d = abs(float(abs_delta))
    if d <= core_tol:
        return 1.0
    if d >= support_tol:
        return 0.0
    norm = (d - core_tol) / float(support_tol - core_tol)
    return round(0.5 * (1.0 + math.cos(math.pi * norm)), 4)


def fuzzify_acoustic_signature(sig: Dict[str, object]) -> Dict[str, Dict[str, float]]:
    bands: Dict[str, float] = sig["spectral_bands_rel_db"]  # type: ignore[assignment]
    dyn: Dict[str, float] = sig["timbre_dynamics"]  # type: ignore[assignment]

    bass_idx = float(bands["bass_body_100_200hz"]) + 0.35 * max(-6.0, float(bands["sub_bass_40_100hz"]))
    lowmid_idx = float(bands["lowmid_box_200_400hz"])
    pres_db = float(bands["hammer_presence_1200_3200hz"])
    atk_ratio = float(dyn["attack_to_sustain_ratio"])
    bite_idx = pres_db + (atk_ratio - 1.05) * 14.0
    air_idx = float(bands["brilliance_3200_6500hz"]) + 0.35 * (float(bands["air_6500_14000hz"]) + 60.0)
    decay_slope = float(dyn["decay_slope_db_per_sec"])

    return {
        "low_body_warmth": {
            "magro_seco": round(trapmf(bass_idx, -20.0, -20.0, 3.5, 5.8), 3),
            "equilibrado_natural": round(trapmf(bass_idx, 4.2, 5.8, 7.8, 9.2), 3),
            "quente_encorpado": round(trapmf(bass_idx, 7.2, 8.6, 11.2, 13.0), 3),
            "profundo_concert_9ft": round(trapmf(bass_idx, 10.2, 11.8, 25.0, 25.0), 3),
        },
        "lowmid_wood_clarity": {
            "limpo_escavado": round(trapmf(lowmid_idx, -15.0, -15.0, 3.8, 5.5), 3),
            "amadeirado_natural": round(trapmf(lowmid_idx, 4.5, 5.8, 7.6, 8.8), 3),
            "denso_quente": round(trapmf(lowmid_idx, 7.2, 8.2, 10.2, 11.5), 3),
            "encaixotado_boxy": round(trapmf(lowmid_idx, 10.2, 11.8, 25.0, 25.0), 3),
        },
        "hammer_bite_presence": {
            "macio_aveludado": round(trapmf(bite_idx, -35.0, -35.0, -16.8, -14.5), 3),
            "articulado_natural": round(trapmf(bite_idx, -16.2, -14.8, -12.2, -10.5), 3),
            "presente_stage_cut": round(trapmf(bite_idx, -12.5, -11.0, -8.5, -6.5), 3),
            "cristalino_brilhante": round(trapmf(bite_idx, -8.8, -7.0, 10.0, 10.0), 3),
        },
        "treble_air_sparkle": {
            "intimo_escuro": round(trapmf(air_idx, -60.0, -60.0, -30.5, -27.5), 3),
            "aberto_natural": round(trapmf(air_idx, -29.5, -27.0, -22.5, -19.5), 3),
            "luminoso_airy": round(trapmf(air_idx, -22.0, -19.5, 10.0, 10.0), 3),
        },
        "sustain_envelope": {
            "curto_enxuto_stage": round(trapmf(decay_slope, -30.0, -30.0, -13.0, -10.8), 3),
            "natural_studio": round(trapmf(decay_slope, -12.5, -10.8, -8.5, -7.0), 3),
            "longo_concert_hall": round(trapmf(decay_slope, -8.5, -7.0, 0.0, 0.0), 3),
        },
    }


def _fuzzy_set_overlap_affinity(
    sets_mx: Dict[str, Dict[str, float]],
    sets_ref: Dict[str, Dict[str, float]],
) -> Tuple[float, Dict[str, float]]:
    dim_weights = {
        "low_body_warmth": 0.22,
        "lowmid_wood_clarity": 0.22,
        "hammer_bite_presence": 0.26,
        "treble_air_sparkle": 0.16,
        "sustain_envelope": 0.14,
    }
    dim_affinities: Dict[str, float] = {}
    weighted_sum = 0.0

    for dim, weight in dim_weights.items():
        v_mx = [float(v) for v in sets_mx[dim].values()]
        v_ref = [float(v) for v in sets_ref[dim].values()]
        norm_mx = math.sqrt(sum(x * x for x in v_mx))
        norm_ref = math.sqrt(sum(x * x for x in v_ref))
        if norm_mx > 1e-9 and norm_ref > 1e-9:
            cos_sim = sum(a * b for a, b in zip(v_mx, v_ref)) / (norm_mx * norm_ref)
        else:
            cos_sim = 1.0
        mean_abs_diff = sum(abs(a - b) for a, b in zip(v_mx, v_ref)) / float(max(1, len(v_mx)))
        l1_sim = max(0.0, 1.0 - mean_abs_diff * 0.85)
        aff = round(0.60 * cos_sim + 0.40 * l1_sim, 3)
        dim_affinities[dim] = aff
        weighted_sum += weight * aff

    return round(weighted_sum, 3), dim_affinities


def evaluate_fuzzy_convergence_and_parsimony(
    sig_mx: Dict[str, object],
    sig_ref: Dict[str, object],
    band_deltas_db: Dict[str, float],
    current_profile: Optional[Mx61AcousticProfile] = None,
) -> Dict[str, object]:
    """
    Fuzzy Inference System for Yamaha MX61 Acoustic Modeling:
      - Evaluates `mu_character_affinity`, `mu_hardware_naturalness`, and `mu_parsimony`
      - Determines whether the 5-Band Parametric Master EQ & 8-Element Voice have converged
        to the Pareto-optimal perceptual plateau (`STOP_OPTIMAL_MATCH`).
    """
    sets_mx = fuzzify_acoustic_signature(sig_mx)
    sets_ref = fuzzify_acoustic_signature(sig_ref)
    linguistic_affinity, dim_affinities = _fuzzy_set_overlap_affinity(sets_mx, sets_ref)

    band_sims = {
        "bass_body": fuzzy_plateau_similarity(band_deltas_db["bass_body_100_200hz"], core_tol=1.8, support_tol=8.0),
        "lowmid_clarity": fuzzy_plateau_similarity(band_deltas_db["lowmid_box_200_400hz"], core_tol=1.6, support_tol=7.5),
        "hammer_presence": fuzzy_plateau_similarity(band_deltas_db["hammer_presence_1200_3200hz"], core_tol=1.8, support_tol=8.0),
        "brilliance": fuzzy_plateau_similarity(band_deltas_db["brilliance_3200_6500hz"], core_tol=2.2, support_tol=9.0),
        "air": fuzzy_plateau_similarity(band_deltas_db["air_6500_14000hz"], core_tol=2.8, support_tol=11.0),
    }
    plateau_band_affinity = (
        0.24 * band_sims["bass_body"]
        + 0.24 * band_sims["lowmid_clarity"]
        + 0.26 * band_sims["hammer_presence"]
        + 0.16 * band_sims["brilliance"]
        + 0.10 * band_sims["air"]
    )

    mu_character = round(0.55 * linguistic_affinity + 0.45 * plateau_band_affinity, 3)
    mu_naturalness = 0.95
    mu_parsimony = 0.94

    if current_profile is not None:
        eq_gains = [
            abs(current_profile.eq_low.gain_db),
            abs(current_profile.eq_lowmid.gain_db),
            abs(current_profile.eq_mid.gain_db),
            abs(current_profile.eq_himid.gain_db),
            abs(current_profile.eq_high.gain_db),
        ]
        max_eq = max(eq_gains)
        mean_eq = sum(eq_gains) / 5.0
        mu_eq_nat = trapmf(max_eq, 0.0, 0.0, 4.5, 11.0) * 0.7 + trapmf(mean_eq, 0.0, 0.0, 3.0, 8.0) * 0.3
        mu_cut_nat = trapmf(abs(current_profile.part1_cutoff_offset), 0.0, 0.0, 10.0, 24.0)
        mu_naturalness = round(0.65 * mu_eq_nat + 0.35 * mu_cut_nat, 3)

    fuzzy_satisfaction = round(
        (mu_character ** 0.60) * (mu_naturalness ** 0.25) * (mu_parsimony ** 0.15),
        3,
    )

    if mu_character >= 0.80 and mu_naturalness >= 0.80:
        status = "STOP_OPTIMAL_MATCH"
        verdict = (
            f"CONVERGÊNCIA FUZZY ATINGIDA (μ_caráter={mu_character:.2f}, μ_naturalidade={mu_naturalness:.2f}): "
            "O timbre do Yamaha MX61 já está dentro da zona de identidade perceptual do alvo."
        )
    elif mu_character >= 0.68 and mu_naturalness < 0.72:
        status = "STOP_HARDWARE_CEILING"
        verdict = (
            f"TETO FÍSICO SAUDÁVEL ATINGIDO (μ_caráter={mu_character:.2f}, μ_naturalidade={mu_naturalness:.2f}): "
            "A amostra AWM2 atingiu o ponto ótimo de Pareto sem distorcer a fase."
        )
    else:
        status = "CONTINUE_PARSIMONIOUS_TWEAK"
        verdict = (
            f"AJUSTE SELETIVO RECOMENDADO (μ_caráter={mu_character:.2f}, μ_naturalidade={mu_naturalness:.2f}): "
            "Aplique apenas os deltas sugeridos no Master EQ de 5 bandas e Cutoff/Sustain."
        )

    return {
        "decision_status": status,
        "verdict": verdict,
        "fuzzy_indices": {
            "mu_character_affinity": mu_character,
            "mu_hardware_naturalness": mu_naturalness,
            "mu_parsimony": mu_parsimony,
            "fuzzy_pareto_satisfaction": fuzzy_satisfaction,
        },
        "dimension_affinities": dim_affinities,
        "band_plateau_similarities": band_sims,
        "mx61_fuzzy_sets": sets_mx,
        "reference_fuzzy_sets": sets_ref,
    }


def compare_mx61_to_reference(
    mx61_wav: Union[str, Path],
    target_wav: Union[str, Path],
    current_profile: Optional[Mx61AcousticProfile] = None,
) -> Dict[str, object]:
    """
    Compare a Yamaha MX61 USB-Audio recording against a target flagship reference WAV
    and compute closed-loop adjustments for the MX61's 5-Band Parametric Master EQ (`36 10 00..13`)
    and Part/Element parameters.
    """
    sig_mx = extract_acoustic_signature(mx61_wav)
    sig_ref = extract_acoustic_signature(target_wav)

    bands_mx: Dict[str, float] = sig_mx["spectral_bands_rel_db"]  # type: ignore[assignment]
    bands_ref: Dict[str, float] = sig_ref["spectral_bands_rel_db"]  # type: ignore[assignment]

    band_deltas_db: Dict[str, float] = {}
    sq_err_sum = 0.0
    for b_name, _, _ in ACOUSTIC_BANDS:
        delta = round(bands_ref[b_name] - bands_mx[b_name], 2)
        band_deltas_db[b_name] = delta
        sq_err_sum += delta ** 2

    rmse_db = math.sqrt(sq_err_sum / len(ACOUSTIC_BANDS))
    similarity_score = round(max(0.0, min(100.0, 100.0 - (rmse_db * 6.5))), 1)

    fuzzy_eval = evaluate_fuzzy_convergence_and_parsimony(
        sig_mx=sig_mx,
        sig_ref=sig_ref,
        band_deltas_db=band_deltas_db,
        current_profile=current_profile,
    )

    def parsimonious_step(val: float, deadzone: float = 1.8, limit: int = 3) -> int:
        if abs(val) <= deadzone:
            return 0
        effective = val - math.copysign(deadzone * 0.5, val)
        return max(-limit, min(limit, int(round(effective * 0.60))))

    d_low = parsimonious_step(band_deltas_db["bass_body_100_200hz"])
    d_lowmid = parsimonious_step(band_deltas_db["lowmid_box_200_400hz"], deadzone=1.6)
    d_mid = parsimonious_step(-0.5 * band_deltas_db["lowmid_box_200_400hz"], deadzone=2.0)
    d_himid = parsimonious_step(band_deltas_db["hammer_presence_1200_3200hz"])
    d_high = parsimonious_step(band_deltas_db["air_6500_14000hz"], deadzone=2.4)
    d_brilliance = band_deltas_db["brilliance_3200_6500hz"]

    cutoff_step = 0 if abs(d_brilliance) <= 2.2 else max(-6, min(6, int(round(d_brilliance * 0.65))))

    dyn_mx = sig_mx["timbre_dynamics"]  # type: ignore[index]
    dyn_ref = sig_ref["timbre_dynamics"]  # type: ignore[index]
    decay_diff = float(dyn_ref["decay_slope_db_per_sec"]) - float(dyn_mx["decay_slope_db_per_sec"])
    decay_offset_step = 0 if abs(decay_diff) <= 1.8 else max(-8, min(8, int(round(decay_diff * 1.2))))

    recommendations: Dict[str, object] = {
        "fuzzy_decision": fuzzy_eval["decision_status"],
        "fuzzy_verdict": fuzzy_eval["verdict"],
        "master_eq_5band_deltas_db": {
            "band1_low_125hz_delta_db": d_low,
            "band2_lowmid_315hz_delta_db": d_lowmid,
            "band3_mid_630hz_delta_db": d_mid,
            "band4_himid_2500hz_delta_db": d_himid,
            "band5_high_8000hz_delta_db": d_high,
        },
        "voice_and_part_deltas": {
            "part1_cutoff_offset_step": cutoff_step,
            "part1_decay_offset_step": decay_offset_step,
        },
    }

    return {
        "fuzzy_evaluation": fuzzy_eval,
        "similarity_score_pct": similarity_score,
        "spectral_rmse_db": round(rmse_db, 2),
        "band_deltas_target_minus_mx61_db": band_deltas_db,
        "mx61_signature": sig_mx,
        "reference_signature": sig_ref,
        "recommendations": recommendations,
    }


def download_youtube_reference_wav(
    url: str,
    out_wav: Union[str, Path],
    start_sec: float = 0.0,
    duration_sec: float = 15.0,
) -> Dict[str, object]:
    """Download reference audio from YouTube using `yt-dlp` + `ffmpeg` into a 44.1kHz/48kHz Stereo WAV."""
    out_path = Path(out_wav).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    yt_dlp_bin = "yt-dlp"
    local_yt = Path.home() / ".local" / "bin" / "yt-dlp"
    if local_yt.exists():
        yt_dlp_bin = str(local_yt)

    ffmpeg_bin = "ffmpeg"
    try:
        import imageio_ffmpeg  # type: ignore[import-not-found]
        ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass

    tmp_audio = out_path.parent / f".tmp_yt_{out_path.stem}.webm"
    if tmp_audio.exists():
        tmp_audio.unlink()

    dl_cmd = [
        yt_dlp_bin,
        "--no-check-certificates",
        "--no-playlist",
        "-f",
        "251/bestaudio",
        "-o",
        str(tmp_audio),
        url,
    ]
    try:
        proc = subprocess.run(dl_cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0 or not tmp_audio.exists():
            return {"ok": False, "error": proc.stderr.strip() or "yt-dlp failed"}
        conv_cmd = [
            ffmpeg_bin,
            "-y",
            "-ss",
            str(start_sec),
            "-t",
            str(duration_sec),
            "-i",
            str(tmp_audio),
            "-ar",
            "44100",
            "-ac",
            "2",
            "-sample_fmt",
            "s16",
            str(out_path),
        ]
        cproc = subprocess.run(conv_cmd, capture_output=True, text=True, timeout=60)
        tmp_audio.unlink(missing_ok=True)
        if cproc.returncode != 0 or not out_path.exists():
            return {"ok": False, "error": cproc.stderr.strip() or "ffmpeg conversion failed"}
        return {"ok": True, "wav_path": str(out_path)}
    except FileNotFoundError as e:
        return {"ok": False, "error": f"Binary not found: {e}"}
