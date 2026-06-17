"""Concatenate per-segment WAV audio into one artifact with a common sample rate.

Mixed-language read-back (#2114) synthesizes each sentence with its own
language's voice. Different providers emit different sample rates (Piper 22050 Hz,
Kokoro 24000 Hz), so the per-segment WAV files cannot simply be byte-appended:
that would corrupt playback (wrong speed/pitch on every segment after the first).

This module reads each mono 16-bit PCM WAV, resamples every segment to a single
common rate (the maximum source rate, to avoid downsampling loss), and writes one
concatenated mono 16-bit WAV. It is local-only and dependency-free (stdlib
``wave`` + ``array``) so it stays 3.13-safe without ``audioop``.
"""

from __future__ import annotations

import wave
from array import array
from pathlib import Path


class TTSConcatError(RuntimeError):
    """Raised when per-segment WAV inputs cannot be concatenated safely."""


def _read_mono_pcm16(path: Path) -> tuple[array, int]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sampwidth = wav.getsampwidth()
        framerate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    if sampwidth != 2:
        raise TTSConcatError(
            f"unsupported sample width {sampwidth} (expected 16-bit PCM): {path}"
        )
    samples = array("h")
    samples.frombytes(frames)
    if channels > 1:
        # Downmix to mono by averaging interleaved channels.
        mono = array("h", [0]) * (len(samples) // channels)
        for i in range(len(mono)):
            acc = 0
            for c in range(channels):
                acc += samples[i * channels + c]
            mono[i] = int(acc / channels)
        samples = mono
    return samples, framerate


def _resample_pcm16(samples: array, src_rate: int, dst_rate: int) -> array:
    if src_rate == dst_rate or len(samples) == 0:
        return samples
    out_len = max(1, round(len(samples) * dst_rate / src_rate))
    out = array("h", [0]) * out_len
    last_src = len(samples) - 1
    for i in range(out_len):
        # Linear interpolation between neighbouring source samples.
        src_pos = i * src_rate / dst_rate
        left = int(src_pos)
        if left >= last_src:
            out[i] = samples[last_src]
            continue
        frac = src_pos - left
        value = samples[left] * (1.0 - frac) + samples[left + 1] * frac
        out[i] = int(max(-32768, min(32767, round(value))))
    return out


def common_sample_rate(rates: list[int]) -> int:
    """Pick the common output rate for a set of source rates.

    Upsamples to the maximum source rate so no segment loses fidelity.
    """
    valid = [rate for rate in rates if rate > 0]
    if not valid:
        raise TTSConcatError("no valid source sample rates to concatenate")
    return max(valid)


def concatenate_wavs(inputs: list[Path], output_path: Path) -> int:
    """Concatenate mono 16-bit WAVs into one WAV at a common sample rate.

    Returns the common sample rate used. Differing provider rates are normalized
    by resampling each segment to ``common_sample_rate`` before joining, so the
    output plays back without corruption regardless of provider mix.
    """
    if not inputs:
        raise TTSConcatError("no segment audio to concatenate")

    decoded: list[tuple[array, int]] = [_read_mono_pcm16(path) for path in inputs]
    target_rate = common_sample_rate([rate for _, rate in decoded])

    joined = array("h")
    for samples, src_rate in decoded:
        joined.extend(_resample_pcm16(samples, src_rate, target_rate))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(target_rate)
        wav.writeframes(joined.tobytes())
    return target_rate
