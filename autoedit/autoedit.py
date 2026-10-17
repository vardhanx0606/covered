#!/usr/bin/env python3
"""FLASHOOT auto-edit: cuts a folder of clips to a song in the FLASHOOT style.

Style (see EDITING_STYLE.md):
  flash-burst intro -> white flash into an opener hold -> establishing shots
  -> drop (white flash, one cut per beat) -> breather hold -> build -> fast
  climax -> fade to black.

Needs: ffmpeg + ffprobe on PATH, Python 3.8+, numpy.
"""
import argparse, os, random, re, shutil, subprocess, sys, tempfile
import numpy as np

VIDEO_EXT = ('.mp4', '.mov', '.m4v', '.mkv', '.avi', '.mts')


def run(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def duration(path):
    out = run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path]).stdout
    return float(out.strip())


def find_beats(song):
    """Return (beat_period_seconds, beat_times) using spectral-flux onset + autocorrelation."""
    sr, hop, n = 22050, 512, 1024
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', song, '-ac', '1', '-ar', str(sr), '-f', 's16le', '-'],
                         check=True, capture_output=True).stdout
    x = np.frombuffer(raw, np.int16).astype(float) / 32768
    frames = np.lib.stride_tricks.sliding_window_view(x, n)[::hop] * np.hanning(n)
    mag = np.log1p(np.abs(np.fft.rfft(frames, axis=1)))
    flux = np.maximum(0, np.diff(mag, axis=0)).sum(1)
    flux = (flux - flux.mean()) / (flux.std() + 1e-9)
    fps = sr / hop
    ac = np.correlate(flux, flux, 'full')[len(flux) - 1:]
    lo, hi = int(fps * 60 / 180), int(fps * 60 / 70)
    lag = lo + int(np.argmax(ac[lo:hi]))
    phase = max(range(lag), key=lambda p: flux[p::lag].sum())
    return lag / fps, np.arange(phase, len(flux), lag) / fps


def find_shots(path, min_len=0.4):
    """Split a clip into shots with ffmpeg scene detection."""
    d = duration(path)
    log = subprocess.run(['ffmpeg', '-hide_banner', '-i', path, '-vf', "select='gt(scene,0.3)',showinfo",
                          '-an', '-f', 'null', '-'], capture_output=True, text=True).stderr
    t = [0.0] + [float(m) for m in re.findall(r'pts_time:([0-9.]+)', log)] + [d]
    return [(a + 0.1, b - 0.1) for a, b in zip(t, t[1:]) if b - a - 0.2 >= min_len]


def build_timeline(period, first_beat, length):
    """Cut points in seconds, plus which cuts get a white flash."""
    p = period * 2 if period < 0.4 else period          # very fast songs: count in half-time
    cuts, flashes = [0.0], set()
    t = first_beat + 2 * p                               # flash-burst intro over the first 2 beats
    burst = np.arange(0.12, t, 0.12)
    cuts += list(burst[:-1]) if len(burst) > 1 else []
    def add(beats_per_cut, count, flash_first=False):
        nonlocal t
        for i in range(count):
            if flash_first and i == 0:
                flashes.add(len(cuts))
            cuts.append(t)
            t += beats_per_cut * p
    add(8, 1, True)      # opener hold
    add(4, 2)            # establishing
    add(1, 16, True)     # drop: one cut per beat
    add(8, 1, True)      # breather / hero shot
    add(2, 5)            # build
    while t < length:    # climax: one cut per beat
        add(1, 1, flash_first=(len(flashes) < 4))
    cuts = [c for c in cuts if c < length - 0.3] + [length]
    return cuts, flashes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('clips', help='folder of video clips')
    ap.add_argument('song', help='music file (mp3/wav/m4a, or a video to take audio from)')
    ap.add_argument('-o', '--out', default='flashoot_edit.mp4')
    ap.add_argument('-l', '--length', type=float, default=30, help='seconds (default 30)')
    ap.add_argument('--start', type=float, default=0, help='start the song at this second')
    ap.add_argument('--landscape', action='store_true', help='16:9 output instead of vertical 9:16')
    ap.add_argument('--logo', help='PNG watermark placed top-centre')
    ap.add_argument('--seed', type=int, default=7, help='change to get a different shot order')
    a = ap.parse_args()

    for tool in ('ffmpeg', 'ffprobe'):
        if not shutil.which(tool):
            sys.exit(f'{tool} not found. On Mac: brew install ffmpeg')
    random.seed(a.seed)
    W, H = (1920, 1080) if a.landscape else (1080, 1920)

    files = sorted(os.path.join(a.clips, f) for f in os.listdir(a.clips) if f.lower().endswith(VIDEO_EXT))
    if not files:
        sys.exit('No video clips found in ' + a.clips)
    print(f'Scanning {len(files)} clips for shots...')
    shots = [(f, s, e) for f in files for s, e in find_shots(f)]
    print(f'  {len(shots)} usable shots')

    tmp = tempfile.mkdtemp(prefix='flashoot_')
    song = os.path.join(tmp, 'song.wav')
    run(['ffmpeg', '-v', 'error', '-y', '-ss', str(a.start), '-i', a.song, '-t', str(a.length + 1),
         '-vn', '-ac', '2', '-ar', '44100', song])
    length = min(a.length, duration(song) - 0.2)
    period, beats = find_beats(song)
    print(f'Song tempo ~{60 / period:.0f} BPM')
    cuts, flashes = build_timeline(period, beats[0] if len(beats) else 0, length)

    used, parts, last_file = set(), [], None
    for i, (st, en) in enumerate(zip(cuts, cuts[1:])):
        d = en - st
        ok = [s for s in shots if s[2] - s[1] >= d and s not in used and s[0] != last_file] or \
             [s for s in shots if s[2] - s[1] >= d] or shots
        shot = max(ok, key=lambda s: s[2] - s[1]) if d >= 3 else random.choice(ok)
        used.add(shot); last_file = shot[0]
        f, s, e = shot
        start = s + max(0, ((e - s) - d) / 2)
        vf = (f'scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps=30,'
              'eq=saturation=1.12:contrast=1.04')
        if i in flashes:
            vf += ',fade=in:st=0:d=0.2:color=white'
        if i == len(cuts) - 2:
            vf += f',fade=out:st={max(0, d - 0.6):.2f}:d=0.6'
        out = os.path.join(tmp, f'{i:03d}.mp4')
        run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{start:.3f}', '-i', f, '-t', f'{d:.3f}', '-an', '-vf', vf,
             '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p', out])
        parts.append(out)
        print(f'  shot {i + 1:2d}/{len(cuts) - 1}  {d:4.2f}s  {os.path.basename(f)}{"  [flash]" if i in flashes else ""}')

    with open(os.path.join(tmp, 'list.txt'), 'w') as fh:
        fh.writelines(f"file '{p}'\n" for p in parts)
    cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', os.path.join(tmp, 'list.txt'),
           '-i', song]
    if a.logo:
        cmd += ['-i', a.logo, '-filter_complex',
                f'[2]scale={W // 6}:-1,format=rgba,colorchannelmixer=aa=0.85[l];[0][l]overlay=(W-w)/2:H*0.04[v]',
                '-map', '[v]', '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p']
    else:
        cmd += ['-map', '0:v', '-c:v', 'copy']
    cmd += ['-map', '1:a', '-af', f'afade=t=out:st={max(0, length - 1.2):.2f}:d=1.2', '-c:a', 'aac', '-b:a', '192k',
            '-t', f'{length:.3f}', '-movflags', '+faststart', a.out]
    run(cmd)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f'Done -> {a.out}')


if __name__ == '__main__':
    main()
