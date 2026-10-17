# FLASHOOT auto-edit

Cuts a folder of clips to a song in the FLASHOOT style (see `../EDITING_STYLE.md`).

## Setup on Mac (one time)
```bash
# install Homebrew if you don't have it: https://brew.sh
brew install ffmpeg python
pip3 install numpy
git clone https://github.com/vardhanx0606/covered.git
cd covered && git checkout claude/editing-style-xkdmk4
```

## Make an edit
```bash
python3 autoedit/autoedit.py ~/Desktop/event_clips ~/Desktop/song.mp3 -o ~/Desktop/reel.mp4
```

Options:
- `-l 30` length in seconds (default 30)
- `--start 45` start the song at 0:45 (use the drop / hook part)
- `--logo flashoot.png` put your logo top-centre
- `--landscape` 16:9 instead of vertical
- `--seed 3` different shot order if you don't like the first one
