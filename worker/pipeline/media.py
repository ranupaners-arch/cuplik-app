import json
import subprocess
from pathlib import Path
from threading import Timer

from api.app.config import get_settings
from api.app.schemas import Sentence, Transcript, finite_duration, youtube_url
from worker.pipeline.transcription import segment_words as segment_words
from worker.pipeline.transcription import transcribe as transcribe
from worker.pipeline.ytdlp import command as ytdlp_command


class MediaError(RuntimeError):
    pass


def run(command: list[str], *, cwd: Path | None = None, timeout: int = 600, env=None) -> str:
    try:
        result = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env
        )
    except FileNotFoundError as exc:
        raise MediaError(f"{command[0]} belum tersedia. Pasang FFmpeg/ffprobe.") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError(
            "Batas waktu pemrosesan media terlewati; coba video lebih pendek."
        ) from exc
    if result.returncode:
        # Keep full diagnostics local; the API never returns subprocess arguments or credentials.
        if cwd:
            (cwd / "media-error.log").write_text(result.stderr[-12000:])
        if "yt_dlp" in command:
            raise MediaError(ytdlp_error(result.stderr))
        raise MediaError(
            f"{Path(command[0]).name} gagal memproses media. Periksa berkas, audio, atau akses link; lihat log worker."
        )
    return result.stdout


def ytdlp_error(stderr: str) -> str:
    message = stderr.casefold()
    if "private video" in message or "members-only" in message:
        return "Video privat atau khusus anggota. Unggah berkas yang dapat Anda akses."
    if any(text in message for text in ("age-restricted", "confirm your age", "age restricted")):
        return "Video dibatasi usia. Unduh melalui akun Anda lalu unggah berkas lokal."
    if "sign in" in message or "not a bot" in message:
        return "YouTube meminta verifikasi akun. Coba unggah berkas lokal."
    if "not available" in message or "unavailable" in message or "removed" in message:
        return "Video tidak tersedia atau sudah dihapus. Periksa link atau unggah berkas lokal."
    if "playlist" in message:
        return "Playlist belum didukung; gunakan link satu video."
    if "timed out" in message or "network" in message or "unable to download" in message:
        return (
            "Koneksi unduhan terputus. Coba lagi; bagian unduhan yang tersimpan akan dilanjutkan."
        )
    return "yt-dlp gagal membaca video. Jalankan make update-ytdlp lalu coba lagi, atau unggah berkas lokal."


def probe_file(path: Path) -> dict:
    info = json.loads(
        run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)])
    )
    duration = finite_duration(float(info.get("format", {}).get("duration", 0)))
    if not any(stream.get("codec_type") == "video" for stream in info["streams"]):
        raise MediaError("Berkas tidak berisi video.")
    if not any(stream.get("codec_type") == "audio" for stream in info["streams"]):
        raise MediaError("Video tidak memiliki audio.")
    if duration > get_settings().max_source_seconds:
        raise MediaError("Video melebihi batas durasi konfigurasi.")
    return {"duration_s": duration, "streams": info["streams"]}


def probe_url(url: str) -> dict:
    youtube_url(url)
    command, env = ytdlp_command(
        [
            "--ignore-config",
            "--no-playlist",
            "--skip-download",
            "--dump-single-json",
            "--socket-timeout",
            "15",
            "--retries",
            "2",
            "--extractor-retries",
            "2",
            "--js-runtimes",
            "node",
            "--",
            url,
        ]
    )
    data = json.loads(
        run(
            command,
            env=env,
            timeout=90,
        )
    )
    if data.get("_type") in ("playlist", "multi_video"):
        raise MediaError("Playlist belum didukung; gunakan satu video.")
    if data.get("is_live") or data.get("live_status") == "is_live":
        raise MediaError("Live masih berlangsung. Tunggu selesai atau unggah rekamannya.")
    if data.get("live_status") == "is_upcoming":
        raise MediaError("Video belum tayang. Tunggu sampai rekamannya tersedia.")
    try:
        duration = finite_duration(float(data.get("duration") or 0))
    except (ValueError, TypeError) as exc:
        raise MediaError(
            "Durasi video belum tersedia atau tidak valid. Coba lagi atau unggah berkas lokal."
        ) from exc
    if duration > get_settings().max_source_seconds:
        raise MediaError("Video melebihi batas durasi konfigurasi.")
    if not any(f.get("acodec") not in (None, "none") for f in data.get("formats", [])):
        raise MediaError("Video tidak memiliki audio yang dapat diunduh.")
    return {
        "title": data.get("title", "Video YouTube"),
        "duration_s": duration,
        "language": data.get("language") or "auto",
        "is_live": False,
    }


def download(url: str, path: Path, progress=lambda *_: None):
    metadata = probe_url(url)
    command, env = ytdlp_command(
        [
            "--ignore-config",
            "--no-playlist",
            "--socket-timeout",
            "15",
            "--retries",
            "2",
            "--js-runtimes",
            "node",
            "--newline",
            "--progress",
            "--progress-template",
            'download:CUPLIK_PROGRESS:{"downloaded":%(progress.downloaded_bytes)j,"total":%(progress.total_bytes)j,"estimate":%(progress.total_bytes_estimate)j}',
            "-f",
            "bv*[height<=1080]+ba/b[height<=1080]",
            "--merge-output-format",
            "mp4",
            "--remux-video",
            "mp4",
            "-o",
            str(path.parent / "source.download.%(ext)s"),
            "--",
            url,
        ]
    )
    log = path.parent / "download-error.log"
    timed_out = False
    with log.open("w") as errors:
        process = subprocess.Popen(
            command,
            env=env,
            cwd=path.parent,
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            start_new_session=False,
        )

        def expire():
            nonlocal timed_out
            timed_out = True
            try:
                process.kill()
            except ProcessLookupError:
                pass

        timer = Timer(get_settings().job_timeout_seconds, expire)
        timer.start()
        try:
            for line in process.stdout:
                if line.startswith("CUPLIK_PROGRESS:"):
                    try:
                        value = json.loads(line.split(":", 1)[1])
                        done = float(value.get("downloaded") or 0)
                        total = value.get("total") or value.get("estimate")
                        fraction = (
                            min(0.99, done / float(total))
                            if isinstance(total, (float, int)) and total
                            else 0
                        )
                        progress(
                            fraction,
                            f"Mengunduh bagian media: {done / 1024**2:.1f} MiB"
                            + (
                                f" / {float(total) / 1024**2:.1f} MiB"
                                if isinstance(total, (float, int))
                                else ""
                            ),
                        )
                    except (ValueError, TypeError):
                        pass
            process.wait()
        finally:
            timer.cancel()
            if process.poll() is None:
                expire()
                process.wait()
            process.stdout.close()
    if timed_out:
        raise MediaError("Batas waktu unduh terlewati. Coba lagi atau unggah berkas lokal.")
    if process.returncode:
        raise MediaError(ytdlp_error(log.read_text()[-12000:]))
    downloaded = path.parent / "source.download.mp4"
    probe_file(downloaded)
    downloaded.replace(path)
    return metadata


def extract_audio(source: Path, destination: Path):
    temporary = destination.with_name("audio.tmp.wav")
    run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(temporary),
        ],
        cwd=source.parent,
        timeout=get_settings().job_timeout_seconds,
    )
    temporary.replace(destination)


DEMO_TEXT = [
    "Banyak orang mengira modal adalah masalah utama usaha.",
    "Padahal pencatatan yang buruk membuat uang cepat hilang.",
    "Mulai hari ini pisahkan uang pribadi dan uang usaha.",
    "Langkah kedua adalah menghitung biaya setiap produk.",
    "Masukkan bahan tenaga dan pengiriman ke dalam biaya.",
    "Harga jual harus menutup biaya dan memberikan margin.",
    "Selanjutnya catat transaksi pada hari yang sama.",
    "Gunakan tabel sederhana dengan kolom masuk dan keluar.",
    "Periksa saldo setiap sore agar kesalahan cepat terlihat.",
    "Terakhir tinjau laporan usaha pada akhir pekan.",
    "Bandingkan pendapatan biaya dan keuntungan yang tersisa.",
    "Dengan kebiasaan ini keputusan usaha menjadi lebih jelas.",
]


def demo_transcript() -> Transcript:
    return Transcript(
        source="demo",
        sentences=[
            Sentence(id=f"s{i + 1}", start=i * 4, end=(i + 1) * 4, text=text)
            for i, text in enumerate(DEMO_TEXT)
        ],
    )


def make_demo(path: Path):
    temporary = path.with_name("source.tmp.mp4")
    run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=24:duration=48",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100:duration=48",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "30",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            "-movflags",
            "+faststart",
            str(temporary),
        ],
        cwd=path.parent,
    )
    temporary.replace(path)
