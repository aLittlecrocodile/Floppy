#!/usr/bin/env python3
"""Fetch real, free-licensed sleep/relax audio from archive.org and cut 20-min slices.

Sources (all public-domain / CC on archive.org):
  - White noise:  collection "relaxingsounds" (public-domain field recordings)
  - Light music:  "musopen-chopin" (CC0 piano) + "MusopenCollectionAsFlac" (PD)

For multi-hour white-noise files we extract a 20-min window.
For classical movements (each only a few minutes) we concatenate consecutive
movements of the same work until we reach ~20 min.

Local, non-commercial demo use only. Each item records its source URL + license
in the manifest so provenance is auditable.
"""
from __future__ import annotations
import csv
import json
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

UA = "Mozilla/5.0 FloppyAudioFetcher (local non-commercial demo)"
DEST = Path.home() / "Desktop" / "Floppy_audio_v3"
SLICE_SEC = 20 * 60  # 20 minutes

ARCHIVE_DL = "https://archive.org/download"


@dataclass
class WhiteNoise:
    idx: int
    title: str
    desc: str
    item: str          # archive identifier
    filename: str      # exact file in the item
    start_sec: int     # where to start the 20-min slice


@dataclass
class MusicProgram:
    idx: int
    title: str
    desc: str
    item: str
    files: list[str] = field(default_factory=list)  # concatenated until ~20min
    license: str = ""


# ----------------------------------------------------------------------------
# Curated, verified picks (filenames confirmed via archive.org metadata API)
# ----------------------------------------------------------------------------

WHITE_NOISE = [
    WhiteNoise(1, "夜雨轻敲", "雨打帐篷帆布·中等轻柔·无雷声", "relaxingsounds",
               "Rain 6 (Light) 10h on Tent Canvas,(MediumGentle)-no thunder.mp3", 3600),
    WhiteNoise(2, "夜海浪涌", "夜晚海滩·温柔·无海鸥", "relaxingsounds",
               "Waves 3 10h Night Beach-Gentle, NO GULLS.mp3", 3600),
    WhiteNoise(3, "山涧瀑流", "低音山间溪流瀑布", "relaxingsounds",
               "Falls 2 3h (Low pitch)MountainStreamWaterfalls.mp3", 1800),
    WhiteNoise(4, "壁炉火焰", "熊熊燃烧的壁炉", "relaxingsounds",
               "FIRE 2 3h Blazing Fireplace.mp3", 1800),
    WhiteNoise(5, "南美雨林", "潺潺河流·鸟鸣·昆虫·白昼森林", "relaxingsounds",
               "Rainforest 5h Bubbling River Falls(gentle),Birds,Insects,Animals-Daytime,South America.mp3", 1800),
    WhiteNoise(6, "轻柔风扇", "温柔摆头风扇·持续低响", "relaxingsounds",
               "FAN 2 10h Gentle,Oscillating Fan.mp3", 3600),
]

CHOPIN_LIC = "http://creativecommons.org/publicdomain/zero/1.0/ (CC0)"
MUSOPEN_LIC = "http://creativecommons.org/publicdomain/mark/1.0/ (Public Domain)"

MUSIC = [
    MusicProgram(7, "肖邦钢琴夜曲集", "钢琴独奏·肖邦前奏曲/圆舞曲串联", "musopen-chopin",
                 files=[
                     "Prelude Op. 28 no. 15.mp3",
                     "Prelude Op. 28 no. 19.mp3",
                     "Prelude Op. 28 no. 17.mp3",
                     "Prelude Op. 28 no. 13.mp3",
                     "Waltz no. 19 - op. posth: A minor.mp3",
                     "Prelude Op. 28 no. 7.mp3",
                     "Waltz no. 18 - op. posth: Eb-major.mp3",
                 ], license=CHOPIN_LIC),
    MusicProgram(8, "舒伯特钢琴奏鸣曲 D.664", "钢琴独奏·完整三乐章", "MusopenCollectionAsFlac",
                 files=[
                     "Schubert_SonataInAMajorD.664/FranzSchubert-SonataInAMajorD.664-01-AllegroModerato.flac",
                     "Schubert_SonataInAMajorD.664/FranzSchubert-SonataInAMajorD.664-02-Andante.flac",
                     "Schubert_SonataInAMajorD.664/FranzSchubert-SonataInAMajorD.664-03-Allegro.flac",
                 ], license=MUSOPEN_LIC),
    MusicProgram(9, "德沃夏克《美国》弦乐四重奏", "弦乐合奏·完整四乐章", "MusopenCollectionAsFlac",
                 files=[
                     "Dvorak_StringQuartetNo.12inFMajorOp.96/AntonnDvorak-StringQuartetNo.12InFMajorOp.96American-01-AllegroMaNonTroppo.flac",
                     "Dvorak_StringQuartetNo.12inFMajorOp.96/AntonnDvorak-StringQuartetNo.12InFMajorOp.96American-02-Lento.flac",
                     "Dvorak_StringQuartetNo.12inFMajorOp.96/AntonnDvorak-StringQuartetNo.12InFMajorOp.96American-03-MoltoVivace.flac",
                     "Dvorak_StringQuartetNo.12inFMajorOp.96/AntonnDvorak-StringQuartetNo.12InFMajorOp.96American-04-Finale-VivaceMaNonTroppo.flac",
                 ], license=MUSOPEN_LIC),
    MusicProgram(10, "鲍罗丁第一弦乐四重奏", "弦乐合奏·大小提琴/大提琴·两个长乐章", "MusopenCollectionAsFlac",
                 files=[
                     "Borodin_StringQuartetNo.1inAMajor/AlexanderBorodin-StringQuartetNo.1InAMajor-01-Moderato-Allegro.flac",
                     "Borodin_StringQuartetNo.1inAMajor/AlexanderBorodin-StringQuartetNo.1InAMajor-02-AndanteConMoto.flac",
                 ], license=MUSOPEN_LIC),
    MusicProgram(11, "舒克《冥想曲》+ 莫扎特长笛序曲", "小提琴抒情 + 长笛/管乐", "MusopenCollectionAsFlac",
                 files=[
                     "Suk_Meditation/JosefSuk-Meditation.flac",
                     "Mozart_MagicFluteOverture/WolfgangAmadeusMozart-MagicFluteOverture.flac",
                     "Schubert_SonataInAMajorD.664/FranzSchubert-SonataInAMajorD.664-02-Andante.flac",
                 ], license=MUSOPEN_LIC),
]

WN_LICENSE = "archive.org item 'relaxingsounds' — Public Domain field recordings"


def run(cmd: list[str]) -> None:
    print("  $", " ".join(str(c) for c in cmd[:3]), "...")
    subprocess.run(cmd, check=True, capture_output=True)


def dl_url(item: str, filename: str) -> str:
    return f"{ARCHIVE_DL}/{item}/{urllib.parse.quote(filename)}"


def curl_to(url: str, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["curl", "-sL", "-A", UA, "-m", "1200", "--retry", "2", "-o", str(out), url],
        check=True,
    )


def slice_white_noise(wn: WhiteNoise, raw: Path, out: Path) -> None:
    # 20-min slice with 3s fade in/out, normalized loudness, re-encode to mp3
    run([
        "ffmpeg", "-y", "-ss", str(wn.start_sec), "-t", str(SLICE_SEC), "-i", str(raw),
        "-af", f"afade=t=in:st=0:d=3,afade=t=out:st={SLICE_SEC - 3}:d=3,loudnorm=I=-23:TP=-2",
        "-ac", "2", "-ar", "44100", "-b:a", "160k", str(out),
    ])


def build_music(mp: MusicProgram, parts: list[Path], out: Path, tmp: Path) -> None:
    # Decode each part (codecs/sample-rates differ across sources), concat via
    # the concat filter, trim to 20 min, fade in, normalize loudness -> mp3.
    inputs = []
    for p in parts:
        inputs += ["-i", str(p)]
    n = len(parts)
    streams = "".join(f"[{i}:a]" for i in range(n))
    filtergraph = (
        f"{streams}concat=n={n}:v=0:a=1[cat];"
        f"[cat]atrim=0:{SLICE_SEC},asetpts=N/SR/TB,"
        f"afade=t=in:st=0:d=2,loudnorm=I=-20:TP=-2[out]"
    )
    run([
        "ffmpeg", "-y", *inputs,
        "-filter_complex", filtergraph, "-map", "[out]",
        "-ac", "2", "-ar", "44100", "-b:a", "192k", str(out),
    ])


def probe_dur(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return 0.0


def main() -> None:
    raw_dir = DEST / "_raw_cache"
    tmp_dir = DEST / "_tmp"
    wn_dir = DEST / "01_white_noise_白噪音"
    mu_dir = DEST / "02_music_轻音乐"
    for d in (raw_dir, tmp_dir, wn_dir, mu_dir):
        d.mkdir(parents=True, exist_ok=True)

    rows = []

    # ---- White noise ----
    for wn in WHITE_NOISE:
        print(f"[WN {wn.idx}] {wn.title}")
        ext = Path(wn.filename).suffix
        raw = raw_dir / f"wn{wn.idx}{ext}"
        if not raw.exists() or raw.stat().st_size < 1_000_000:
            curl_to(dl_url(wn.item, wn.filename), raw)
        out = wn_dir / f"{wn.idx:02d}_{wn.title}_20min.mp3"
        slice_white_noise(wn, raw, out)
        dur = probe_dur(out)
        rows.append({
            "idx": wn.idx, "category": "white_noise", "title": wn.title,
            "desc": wn.desc, "duration_sec": round(dur, 1),
            "file": str(out.relative_to(DEST)),
            "source_url": f"https://archive.org/details/{wn.item}",
            "source_file": wn.filename, "license": WN_LICENSE,
        })
        print(f"    -> {out.name}  {dur/60:.1f}min")

    # ---- Music ----
    for mp in MUSIC:
        print(f"[MUSIC {mp.idx}] {mp.title}")
        parts = []
        for i, fn in enumerate(mp.files):
            ext = Path(fn).suffix
            raw = raw_dir / f"mu{mp.idx}_{i}{ext}"
            if not raw.exists() or raw.stat().st_size < 100_000:
                curl_to(dl_url(mp.item, fn), raw)
            parts.append(raw)
        out = mu_dir / f"{mp.idx:02d}_{mp.title}_20min.mp3"
        build_music(mp, parts, out, tmp_dir)
        dur = probe_dur(out)
        rows.append({
            "idx": mp.idx, "category": "music", "title": mp.title,
            "desc": mp.desc, "duration_sec": round(dur, 1),
            "file": str(out.relative_to(DEST)),
            "source_url": f"https://archive.org/details/{mp.item}",
            "source_file": "; ".join(mp.files), "license": mp.license,
        })
        print(f"    -> {out.name}  {dur/60:.1f}min")

    # ---- Manifest ----
    man = DEST / "manifest.csv"
    with man.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "idx", "category", "title", "desc", "duration_sec",
            "file", "source_url", "source_file", "license"])
        w.writeheader()
        w.writerows(rows)
    print(f"\nManifest -> {man}")
    print(f"Total items: {len(rows)}")


if __name__ == "__main__":
    main()
