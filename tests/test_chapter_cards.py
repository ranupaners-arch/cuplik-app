import json
import subprocess

import numpy as np
import pytest

from api.app.models import Beat, Chapter
from api.app.schemas import OutputSettings
from worker.pipeline.media import probe_file
from worker.pipeline.render import render_condensed, subtitles


def frame(path, time):
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            str(time),
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    return np.frombuffer(result.stdout, dtype=np.uint8).reshape(320, 568, 3)


def test_cards_continue_across_short_beats_preserve_duration_and_audio(client, video, tmp_path):
    chapters = [
        Chapter(
            id=f"c{i}", output_id="o", order=i, title=f"Langkah {i}", goal="Uji", importance="core"
        )
        for i in (1, 2)
    ]
    beats = [
        Beat(
            id=str(i),
            output_id="o",
            chapter_id=f"c{1 if i < 3 else 2}",
            sentence_id=f"s{i}",
            start_s=start,
            end_s=end,
            text="",
            decision="keep",
        )
        for i, (start, end) in enumerate([(0, 1), (1, 4), (4, 7)], 1)
    ]
    plain, cards = tmp_path / "plain", tmp_path / "cards"
    plain.mkdir()
    cards.mkdir()
    normal = render_condensed(video, beats, plain, False, lambda *_: None)
    labeled = render_condensed(
        video,
        beats,
        cards,
        False,
        lambda *_: None,
        settings=OutputSettings(chapter_cards=True),
        chapters=chapters,
    )
    assert abs(probe_file(normal)["duration_s"] - probe_file(labeled)["duration_s"]) < 0.05
    spans = json.loads((cards / "condensed.timeline.json").read_text())["spans"]
    assert sum(
        s["chapter_card"]["duration_s"] for s in spans if s["chapter_id"] == "c1"
    ) == pytest.approx(2)
    assert spans[2]["chapter_card"]["duration_s"] == 2
    assert all(s["audio_mode"] == "source" for s in spans)
    for time in (0.5, 1.5, 4.5):
        # Verify the actual encoded pixels contain an overlay, including after the first short beat.
        difference = np.abs(frame(labeled, time).astype(float) - frame(normal, time).astype(float))
        assert difference[:80, :280].mean() > 0.5
    for path in (normal, labeled):
        audio = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(path),
                "-map",
                "0:a:0",
                "-f",
                "f32le",
                "-ac",
                "1",
                "pipe:1",
            ],
            check=True,
            capture_output=True,
        )
        assert np.sqrt(np.mean(np.frombuffer(audio.stdout, dtype="<f4") ** 2)) > 0.01
    before = {p.name: p.stat().st_mtime_ns for p in cards.glob("part-*.mp4")}
    render_condensed(
        video,
        beats,
        cards,
        False,
        lambda *_: None,
        settings=OutputSettings(chapter_cards=True),
        chapters=chapters,
    )
    assert before == {p.name: p.stat().st_mtime_ns for p in cards.glob("part-*.mp4")}


def test_card_text_is_bounded_escaped_and_separate_from_speed_badge(tmp_path):
    path = tmp_path / "overlay.ass"
    subtitles(
        path,
        [],
        1280,
        720,
        chapter_card=(r"{\\pos(0,0)} " + "langkah " * 80, 2),
        speed_badge=(4, 3),
    )
    text = path.read_text()
    card = next(
        line for line in text.splitlines() if line.startswith("Dialogue") and ",Chapter," in line
    )
    assert "{\\" not in card and card.count(r"\N") <= 1 and "…" in card
    assert ",Speed," in text and "CEPAT 4x - AUDIO HENING" in text


def test_missing_chapter_title_fails_before_encoding(client, video, tmp_path):
    beat = Beat(
        id="1", output_id="o", chapter_id="missing", sentence_id="s1", start_s=0, end_s=2, text=""
    )
    with pytest.raises(ValueError, match="Judul bab"):
        render_condensed(
            video,
            [beat],
            tmp_path,
            False,
            lambda *_: None,
            settings=OutputSettings(chapter_cards=True),
        )
    assert not list(tmp_path.glob("*.mp4"))
