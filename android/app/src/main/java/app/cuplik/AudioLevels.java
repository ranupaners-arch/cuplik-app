package app.cuplik;

import org.json.JSONArray;
import org.json.JSONObject;

/** Bounded-memory PCM measurements. dBFS/RMS is not perceptual or integrated LUFS. */
final class AudioLevels {
  private double seconds, energy, peak, nearRailSeconds, windowSeconds, windowEnergy;
  private double silentStart = -1, longestSilence;
  private final JSONArray silences = new JSONArray();
  private boolean finished;

  void frame(double meanSquare, double framePeak, int rate) {
    if (finished
        || rate < 1
        || !Double.isFinite(meanSquare)
        || meanSquare < 0
        || !Double.isFinite(framePeak)
        || framePeak < 0) throw new IllegalArgumentException("Sampel pengukuran tidak valid.");
    double step = 1.0 / rate;
    seconds += step;
    energy += meanSquare * step;
    peak = Math.max(peak, framePeak);
    if (framePeak >= .999) nearRailSeconds += step;
    windowSeconds += step;
    windowEnergy += meanSquare * step;
    if (windowSeconds >= .1 - 1e-8) window();
  }

  private void window() {
    if (windowSeconds <= 0) return;
    if (windowEnergy / windowSeconds <= 1e-5) {
      if (silentStart < 0) silentStart = Math.max(0, seconds - windowSeconds);
    } else closeSilence(Math.max(0, seconds - windowSeconds));
    windowSeconds = 0;
    windowEnergy = 0;
  }

  private void closeSilence(double end) {
    if (silentStart < 0) return;
    double length = Math.max(0, end - silentStart);
    longestSilence = Math.max(longestSilence, length);
    if (length >= 2 - 1e-5 && silences.length() < 50)
      silences.put(Json.obj("start_s", silentStart, "end_s", end));
    silentStart = -1;
  }

  JSONObject report() {
    if (!finished) {
      window();
      closeSilence(seconds);
      finished = true;
    }
    return Json.obj(
        "decoded_duration_s",
        seconds,
        "rms_dbfs",
        10 * Math.log10(Math.max(1e-12, energy / Math.max(seconds, 1e-12))),
        "peak_dbfs",
        20 * Math.log10(Math.max(1e-6, peak)),
        "near_fullscale_fraction",
        nearRailSeconds / Math.max(seconds, 1e-12),
        "longest_silence_s",
        longestSilence,
        "silence_spans",
        silences,
        "silence_threshold_dbfs",
        -50,
        "window_seconds",
        .1);
  }
}
