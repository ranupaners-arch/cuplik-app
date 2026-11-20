package app.cuplik;

import java.util.Set;
import java.util.UUID;
import org.json.JSONObject;

/** Source-bound durable intent. Mutations are committed by Store as one atomic state write. */
final class JobJournal {
  private static final Set<String> ACTIVE = Set.of("queued", "running", "cancelling");
  private static final Set<String> RETRY = Set.of("failed", "cancelled", "interrupted");
  private static final Set<String> ACTIONS =
      Set.of("model", "import", "analyze", "render", "connection");

  static boolean busy(JSONObject state) {
    JSONObject job = state.optJSONObject("active_job");
    return job != null && ACTIVE.contains(job.optString("status"));
  }

  static boolean owns(JSONObject state, String id) {
    JSONObject job = state.optJSONObject("active_job");
    return job != null
        && job.optString("id").equals(id)
        && ACTIVE.contains(job.optString("status"));
  }

  static JSONObject enqueue(JSONObject state, String action, JSONObject payload) throws Exception {
    if (busy(state))
      throw new IllegalStateException("Tunggu proses selesai atau batalkan terlebih dahulu.");
    if (!ACTIONS.contains(action)) throw new IllegalArgumentException("Operasi tidak dikenal.");
    if (payload.toString().length() > 1_000_000)
      throw new IllegalArgumentException("Permintaan terlalu besar.");
    Set<String> fields =
        switch (action) {
          case "analyze" ->
              Set.of(
                  "mode",
                  "language",
                  "clip_count",
                  "max_clip_seconds",
                  "target_seconds",
                  "layout",
                  "captions",
                  "manual");
          case "render" -> Set.of("plan", "layout", "captions");
          case "import" -> Set.of("uri", "name");
          default -> Set.of();
        };
    for (java.util.Iterator<String> keys = payload.keys(); keys.hasNext(); )
      if (!fields.contains(keys.next()))
        throw new IllegalArgumentException("Pengaturan pekerjaan tidak dikenal.");
    JSONObject source = state.optJSONObject("source");
    if ((action.equals("analyze") || action.equals("render")) && source == null)
      throw new IllegalStateException("Pilih video terlebih dahulu.");
    long now = System.currentTimeMillis();
    JSONObject job =
        Json.obj(
            "id",
            UUID.randomUUID().toString(),
            "action",
            action,
            "payload",
            new JSONObject(payload.toString()),
            "status",
            "queued",
            "phase",
            action,
            "progress",
            0,
            "attempt",
            1,
            "created_at",
            now,
            "updated_at",
            now,
            "source_file",
            source == null ? "" : source.optString("file"),
            "input_revision",
            state.optLong("input_revision"));
    state.put("active_job", job);
    state.put("status", "queued");
    state.put("progress", 0);
    state.put("note", "Pekerjaan disimpan; menunggu layanan perangkat.");
    state.remove("error");
    return job;
  }

  static boolean claim(JSONObject state, String id) throws Exception {
    if (!owns(state, id)) return false;
    JSONObject job = state.getJSONObject("active_job");
    if (job.optString("status").equals("cancelling")) {
      finish(state, id, "cancelled", "Proses dibatalkan sebelum mulai.");
      return false;
    }
    if (!job.optString("status").equals("queued")) return false;
    job.put("status", "running");
    job.put("started_at", System.currentTimeMillis());
    job.put("updated_at", System.currentTimeMillis());
    return true;
  }

  static boolean cancel(JSONObject state, String id) throws Exception {
    if (!owns(state, id)) return false;
    JSONObject job = state.getJSONObject("active_job");
    job.put("status", "cancelling");
    job.put("updated_at", System.currentTimeMillis());
    state.put("status", "cancelling");
    state.put("note", "Membatalkan proses; checkpoint dan hasil selesai dipertahankan.");
    return true;
  }

  static boolean cancelled(JSONObject state, String id) {
    return owns(state, id)
        && state.optJSONObject("active_job").optString("status").equals("cancelling");
  }

  static boolean progress(JSONObject state, String id, String phase, double value, String note)
      throws Exception {
    if (!owns(state, id)) return false;
    if (!Double.isFinite(value)) throw new IllegalArgumentException("Progres tidak valid.");
    JSONObject job = state.getJSONObject("active_job");
    job.put("phase", phase);
    job.put("progress", Math.max(0, Math.min(1, value)));
    job.put("updated_at", System.currentTimeMillis());
    state.put("progress", job.getDouble("progress"));
    if (!cancelled(state, id)) {
      state.put("status", phase);
      state.put("note", note);
      state.remove("error");
    }
    return true;
  }

  static boolean finish(JSONObject state, String id, String result, String error) throws Exception {
    if (!owns(state, id)) return false;
    if (!Set.of("done", "failed", "cancelled", "interrupted").contains(result))
      throw new IllegalArgumentException("Status pekerjaan tidak valid.");
    JSONObject job = state.getJSONObject("active_job");
    if (result.equals("done") && cancelled(state, id)) result = "cancelled";
    job.put("status", result);
    job.put("finished_at", System.currentTimeMillis());
    job.put("updated_at", System.currentTimeMillis());
    if (!result.equals("done")) {
      state.put("status", result);
      state.put("error", error == null ? "Proses dibatalkan; checkpoint tetap tersimpan." : error);
      state.put("note", "Sumber dan hasil yang selesai tetap tersimpan. Kamu dapat mencoba ulang.");
    }
    return true;
  }

  static boolean recover(JSONObject state) throws Exception {
    if (busy(state)) {
      JSONObject job = state.getJSONObject("active_job");
      return finish(
          state,
          job.getString("id"),
          "interrupted",
          "Proses sistem sebelumnya terhenti. Coba ulang untuk melanjutkan checkpoint.");
    }
    if (Set.of("importing", "model", "transcribing", "planning", "rendering", "connection")
        .contains(state.optString("status"))) {
      state.put("status", "interrupted");
      state.put("note", "Proses sebelumnya terhenti. Sumber dan checkpoint tetap tersedia.");
      return true;
    }
    return false;
  }

  static boolean retryable(JSONObject state) {
    JSONObject job = state.optJSONObject("active_job");
    if (busy(state) || job == null || !RETRY.contains(job.optString("status"))) return false;
    if (job.optLong("input_revision") != state.optLong("input_revision")) return false;
    if (Set.of("analyze", "render").contains(job.optString("action"))) {
      JSONObject source = state.optJSONObject("source");
      return source != null && job.optString("source_file").equals(source.optString("file"));
    }
    return true;
  }

  static JSONObject retry(JSONObject state) throws Exception {
    if (!retryable(state))
      throw new IllegalStateException(
          "Pekerjaan tidak dapat dilanjutkan. Sumber atau pilihan sudah berubah; buat permintaan"
              + " baru.");
    JSONObject previous = state.getJSONObject("active_job");
    JSONObject job =
        enqueue(state, previous.getString("action"), previous.getJSONObject("payload"));
    job.put("attempt", previous.optInt("attempt", 1) + 1);
    job.put("retry_of", previous.getString("id"));
    return job;
  }

  private JobJournal() {}
}
