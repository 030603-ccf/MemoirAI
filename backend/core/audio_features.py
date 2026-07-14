# -*- coding: utf-8 -*-
"""
audio_features.py
=================
从用户上传的音频文件（wav/mp3）提取关键特征，用于 edge-tts SSML 风格模拟。

特征：
- duration: 音频时长（秒）
- sample_rate: 采样率
- rms: 平均能量（0-1，响度代理）
- f0_mean: 基频均值（Hz，音高代理；中文女声通常 180-250Hz，男声 80-180Hz）
- speech_rate: 语速（每秒有声段切换次数，粗略代理）

用法：
    feats = extract_features("path/to/sample.wav")
    rate, pitch, volume = map_to_ssml(feats)
"""
import wave
import struct
import json
import math
from pathlib import Path


def _read_wav(path: Path) -> tuple:
    """读 wav 文件，返回 (samples, sample_rate, n_channels, sample_width)。"""
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        n_ch = w.getnchannels()
        sw = w.getsampwidth()
        n = w.getnframes()
        raw = w.readframes(n)
    if sw == 1:
        # unsigned 8-bit
        samples = [(b - 128) / 128.0 for b in raw]
    elif sw == 2:
        # signed 16-bit
        samples = list(struct.unpack(f"<{n * n_ch}h", raw))
        samples = [s / 32768.0 for s in samples]
    elif sw == 4:
        samples = list(struct.unpack(f"<{n * n_ch}i", raw))
        samples = [s / 2147483648.0 for s in samples]
    else:
        raise ValueError(f"unsupported sample width: {sw}")
    # 单声道化（多声道取均值）
    if n_ch > 1:
        mono = []
        for i in range(0, len(samples), n_ch):
            chunk = samples[i:i + n_ch]
            mono.append(sum(chunk) / n_ch)
        samples = mono
    return samples, sr


# PyAV 支持的格式白名单（PyAV 自带 ffmpeg 解码器，不需要系统装 ffmpeg）
AV_SUPPORTED = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}


def convert_to_wav(
    input_path: str | Path,
    output_path: str | Path,
    target_sr: int = 16000,
    target_channels: int = 1,
) -> dict:
    """用 PyAV 把任意格式音频（mp3/m4a/aac/flac/ogg/opus/wav）解码 → 重采样 → 写 wav 文件。

    返回 dict: {sample_rate, channels, duration_s, samples} 方便调用方做进一步处理。

    用法：上传时统一转 wav 存盘 → 后续 TTS/特征提取不依赖第三方 codec。
    """
    import av  # PyAV

    src = Path(input_path)
    dst = Path(output_path)
    if not src.exists():
        raise FileNotFoundError(src)

    try:
        container = av.open(str(src))
    except Exception as e:
        raise ValueError(f"PyAV 无法打开 {src.name}: {e}") from e

    try:
        if not container.streams.audio:
            raise ValueError(f"{src.name} 里没有音频流")
        stream = container.streams.audio[0]
        # 源参数（用于日志）
        src_sr = stream.rate
        src_ch = stream.channels

        # 重采样：目标 s16 / mono / target_sr
        resampler = av.AudioResampler(
            format="s16",
            layout="mono" if target_channels == 1 else "stereo",
            rate=target_sr,
        )

        pcm_chunks = []
        for frame in container.decode(stream):
            for resampled in resampler.resample(frame):
                pcm_chunks.append(bytes(resampled.planes[0]))
        for flushed in resampler.resample(None):
            pcm_chunks.append(bytes(flushed.planes[0]))
    finally:
        container.close()

    raw = b"".join(pcm_chunks)
    n_samples = len(raw) // 2  # s16 = 2 bytes

    # 写 wav：s16 mono target_sr
    dst.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(target_channels)
        w.setsampwidth(2)  # s16
        w.setframerate(target_sr)
        w.writeframes(raw)

    duration = n_samples / target_sr
    return {
        "sample_rate": target_sr,
        "channels": target_channels,
        "duration_s": round(duration, 2),
        "samples": n_samples,
        "src_format": src.suffix.lower(),
        "src_sample_rate": src_sr,
        "src_channels": src_ch,
    }


def _read_with_av(path: Path) -> tuple:
    """用 PyAV 解码任意格式 → 重采样到 mono 16kHz s16 PCM → 返回 (samples, sr)。

    要求：已 pip install av（PyAV，自带 ffmpeg 库）。
    返回格式与 _read_wav 一致，方便 _autocorr_f0 / _speech_rate 直接用。
    """
    import av  # PyAV
    target_sr = 16000  # 重采样到 16k 够用，省 CPU

    try:
        container = av.open(str(path))
    except Exception as e:
        raise ValueError(f"PyAV 无法打开 {path.name}: {e}") from e

    try:
        if not container.streams.audio:
            raise ValueError(f"{path.name} 里没有音频流")
        stream = container.streams.audio[0]

        # 重采样器：强制 mono + 16kHz + s16 (有符号 16-bit)
        resampler = av.AudioResampler(
            format="s16",
            layout="mono",
            rate=target_sr,
        )

        pcm_chunks = []
        for frame in container.decode(stream):
            for resampled in resampler.resample(frame):
                # resampled 是新的 AudioFrame，planes[0] 是 s16 little-endian
                pcm_chunks.append(bytes(resampled.planes[0]))
            # 防止某些容器 seek/EOF 异常
            if frame is None:
                break

        # 关闭 resampler，把残留 PCM flush 出来
        for flushed in resampler.resample(None):
            pcm_chunks.append(bytes(flushed.planes[0]))

        raw = b"".join(pcm_chunks)
    finally:
        container.close()

    # raw 现在是 s16 mono 16kHz PCM；转 float in [-1, 1]
    n_samples = len(raw) // 2
    fmt = f"<{n_samples}h"
    samples = struct.unpack(fmt, raw)
    samples = [s / 32768.0 for s in samples]
    return samples, target_sr


def _autocorr_f0(samples: list, sr: int, fmin: float = 75.0, fmax: float = 400.0) -> float:
    """粗略估算基频：在一定窗内取多个短段做自相关，找平均周期。
    中文男声 ~120Hz，女声 ~200Hz。所以 fmin=75, fmax=400 足够。
    """
    # 取前 5 秒
    max_samples = sr * 5
    samples = samples[:max_samples]
    if len(samples) < sr // 4:
        return 0.0  # 太短
    # 切片成 100ms 段
    seg_len = sr // 10
    f0_values = []
    for start in range(0, len(samples) - seg_len, seg_len):
        seg = samples[start:start + seg_len]
        # 能量太低（静音）跳过
        energy = math.sqrt(sum(s * s for s in seg) / len(seg))
        if energy < 0.005:
            continue
        # 自相关
        min_lag = max(2, int(sr / fmax))
        max_lag = min(len(seg) - 1, int(sr / fmin))
        if max_lag <= min_lag:
            continue
        best_lag = 0
        best_corr = 0.0
        for lag in range(min_lag, max_lag):
            corr = 0.0
            for i in range(len(seg) - lag):
                corr += seg[i] * seg[i + lag]
            corr /= (len(seg) - lag)
            if corr > best_corr:
                best_corr = corr
                best_lag = lag
        if best_lag > 0 and best_corr > 0.01:
            f0_values.append(sr / best_lag)
    if not f0_values:
        return 0.0
    # 中位数（更鲁棒）
    f0_values.sort()
    return f0_values[len(f0_values) // 2]


def _speech_rate(samples: list, sr: int, frame_ms: int = 25) -> float:
    """估算语速：每秒有声段切换次数。
    算法：按 frame_ms 分帧，计算每帧能量。有声/无声阈值 = 0.01。
    统计有声→无声 / 无声→有声 切换次数，除以时长（秒）。
    """
    frame_len = int(sr * frame_ms / 1000)
    n_frames = len(samples) // frame_len
    if n_frames < 4:
        return 0.0
    energies = []
    for i in range(n_frames):
        seg = samples[i * frame_len: (i + 1) * frame_len]
        e = math.sqrt(sum(s * s for s in seg) / len(seg))
        energies.append(e)
    # 自适应阈值
    sorted_e = sorted(energies)
    threshold = sorted_e[len(sorted_e) // 4] * 4  # 25% 分位数的 4 倍
    threshold = max(threshold, 0.005)
    # 计算切换次数
    transitions = 0
    prev = False
    for e in energies:
        cur = e > threshold
        if cur != prev:
            transitions += 1
            prev = cur
    duration = n_frames * frame_ms / 1000.0
    if duration <= 0:
        return 0.0
    return transitions / duration


def extract_features(path: str) -> dict:
    """从音频文件提取特征。支持 wav（wave 模块）和 mp3/m4a/aac/flac/ogg/opus（PyAV）。

    Requirements:
        - .wav: Python 标准库
        - 其他: pip install av (PyAV，自带 ffmpeg 解码器)
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)

    suffix = p.suffix.lower()
    if suffix == ".wav":
        samples, sr = _read_wav(p)
    elif suffix in AV_SUPPORTED:
        try:
            samples, sr = _read_with_av(p)
        except ImportError:
            raise ValueError(
                f"分析 {suffix} 需要 PyAV。请先 `pip install av`，"
                "或用任意工具把 {p.name} 转成 wav 再上传。"
            )
    else:
        raise ValueError(
            f"暂不支持 {suffix} 格式（支持：wav / mp3 / m4a / aac / flac / ogg / opus）。"
            "请先转 wav 再上传，或联系开发者扩展。"
        )

    duration = len(samples) / sr

    # RMS 能量
    rms = math.sqrt(sum(s * s for s in samples) / max(1, len(samples)))

    # F0 基频
    f0 = _autocorr_f0(samples, sr)

    # 语速
    rate = _speech_rate(samples, sr)

    return {
        "duration": round(duration, 2),
        "sample_rate": sr,
        "rms": round(rms, 4),
        "f0_mean": round(f0, 1),
        "speech_rate": round(rate, 2),
        "format": suffix,
    }


def map_to_ssml(features: dict) -> dict:
    """把音频特征映射到 edge-tts SSML rate/pitch/volume 参数。

    基线参考（中文 edge-tts 默认女声"晓晓"）：
    - 语速 ~3-4 次/秒 (speech_rate)
    - 基频 ~200Hz (f0_mean)
    - RMS ~0.05-0.1
    """
    f0 = features.get("f0_mean", 0.0)
    rate = features.get("speech_rate", 0.0)
    rms = features.get("rms", 0.0)

    # 基频 → pitch (Hz 偏移)
    # 150Hz 以下（低沉男声）：-15Hz
    # 150-180Hz（普通男声）：-8Hz
    # 180-220Hz（女声）：0
    # 220Hz+（高亢女声）：+8Hz
    if f0 > 0:
        if f0 < 150:
            pitch = "-15Hz"
        elif f0 < 180:
            pitch = "-8Hz"
        elif f0 > 220:
            pitch = "+8Hz"
        else:
            pitch = "+0Hz"
    else:
        pitch = "+0Hz"

    # 语速 → rate
    # 3 以下（慢）：-15%
    # 3-5（正常）：0%
    # 5+（快）：+15%
    if rate > 0:
        if rate < 3.0:
            tts_rate = "-15%"
        elif rate > 5.0:
            tts_rate = "+15%"
        else:
            tts_rate = "+0%"
    else:
        tts_rate = "+0%"

    # 能量 → volume
    if rms > 0.15:
        volume = "+10%"
    elif rms < 0.04:
        volume = "-5%"
    else:
        volume = "+0%"

    return {"rate": tts_rate, "pitch": pitch, "volume": volume}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        f = extract_features(sys.argv[1])
        print(json.dumps(f, ensure_ascii=False, indent=2))
        ssml = map_to_ssml(f)
        print("ssml params:", ssml)