package app.cuplik;

import org.json.JSONArray;
import org.json.JSONObject;

final class OutputQc {
  static JSONObject report(
      double actual, double expected, boolean audio, boolean sourceAudio, JSONObject levels) {
    JSONArray issues = new JSONArray();
    if (!Double.isFinite(actual)
        || actual <= 0
        || Math.abs(actual - expected) > Math.max(.15, expected * .03))
      issues.put("duration_mismatch");
    if (sourceAudio && !audio) issues.put("missing_audio");
    if (audio) {
      if (levels == null || levels.optDouble("decoded_duration_s", 0) <= 0)
        issues.put("audio_measurement_unavailable");
      else {
        if (levels.optDouble("rms_dbfs", -120) <= -50) issues.put("very_quiet_audio");
        if (levels.optDouble("longest_silence_s", 0) >= 2 - 1e-5) issues.put("long_silence");
        if (levels.optDouble("near_fullscale_fraction", 0) >= .001)
          issues.put("near_fullscale_audio");
        if (Math.abs(levels.optDouble("decoded_duration_s") - actual) > Math.max(.25, actual * .03))
          issues.put("audio_duration_mismatch");
      }
    }
    return Json.obj(
        "version",
        1,
        "status",
        issues.length() == 0 ? "pass" : "needs_review",
        "issues",
        issues,
        "audio",
        levels == null ? JSONObject.NULL : levels,
        "source_audio_present",
        sourceAudio,
        "note",
        "Pengukuran PCM/dBFS pada MP4 akhir, bukan LUFS atau penilaian kualitas ucapan. Hening"
            + " dapat berasal dari sumber; tinjau sebelum membagikan.");
  }

  private OutputQc() {}
}
