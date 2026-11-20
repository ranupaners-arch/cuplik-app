package app.cuplik;

import android.content.Context;
import android.util.AtomicFile;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import org.json.JSONArray;
import org.json.JSONObject;

final class Store {
  interface Editor {
    void apply(JSONObject state) throws Exception;
  }

  private static Store instance;
  final Context context;
  private JSONObject state;

  static synchronized Store get(Context context) {
    if (instance == null) instance = new Store(context.getApplicationContext());
    return instance;
  }

  Store(Context context) {
    this.context = context;
    try {
      state =
          new JSONObject(
              new String(
                  new AtomicFile(new File(context.getFilesDir(), "state.json")).readFully(),
                  StandardCharsets.UTF_8));
    } catch (Exception unreadable) {
      state =
          Json.obj(
              "status",
              "idle",
              "note",
              "Pilih video dari perangkat.",
              "sentences",
              new JSONArray(),
              "plan",
              new JSONArray(),
              "outputs",
              new JSONArray(),
              "progress",
              0);
      File damaged = new File(context.getFilesDir(), "state.json");
      if (damaged.isFile()) {
        damaged.renameTo(
            new File(
                context.getFilesDir(), "state-corrupt-" + System.currentTimeMillis() + ".json"));
        try {
          state.put("note", "Catatan proyek tidak dapat dibaca. Media dan model tetap disimpan.");
        } catch (Exception ignored) {
        }
      }
    }
    try {
      boolean recovered = JobJournal.recover(state);
      boolean recoveredProjects = new ProjectLibrary(context).recoverIndex(state);
      if (ProjectLibrary.syncIndex(state) || recovered || recoveredProjects) update(s -> {});
    } catch (Exception error) {
      throw new IllegalStateException(error);
    }
    File[] incomplete =
        new File(context.getFilesDir(), "media")
            .listFiles((parent, name) -> name.startsWith("partial-") && name.endsWith(".mp4"));
    if (incomplete != null) for (File file : incomplete) file.delete();
  }

  synchronized JSONObject state() {
    try {
      return new JSONObject(state.toString());
    } catch (Exception error) {
      throw new IllegalStateException(error);
    }
  }

  synchronized void update(Editor editor) {
    JSONObject next = state();
    AtomicFile target = new AtomicFile(new File(context.getFilesDir(), "state.json"));
    FileOutputStream stream = null;
    try {
      editor.apply(next);
      ProjectLibrary.syncIndex(next);
      stream = target.startWrite();
      stream.write(next.toString().getBytes(StandardCharsets.UTF_8));
      target.finishWrite(stream);
      state = next;
    } catch (Exception error) {
      if (stream != null) target.failWrite(stream);
      throw new IllegalStateException(error);
    }
  }

  void progress(String status, double progress, String note) {
    update(
        s -> {
          s.put("status", status);
          s.put("progress", progress);
          s.put("note", note);
          s.remove("error");
        });
  }

  synchronized boolean busy() {
    return JobJournal.busy(state);
  }

  synchronized boolean owns(String id) {
    return JobJournal.owns(state, id);
  }

  synchronized boolean cancelled(String id) {
    return JobJournal.cancelled(state, id);
  }

  synchronized boolean retryable() {
    return JobJournal.retryable(state);
  }

  synchronized JSONObject enqueue(String action, JSONObject options) {
    JSONObject[] result = new JSONObject[1];
    update(s -> result[0] = JobJournal.enqueue(s, action, options));
    return result[0];
  }

  synchronized JSONObject retry() {
    JSONObject[] result = new JSONObject[1];
    update(s -> result[0] = JobJournal.retry(s));
    return result[0];
  }

  synchronized boolean claim(String id) {
    boolean[] claimed = {false};
    update(s -> claimed[0] = JobJournal.claim(s, id));
    return claimed[0];
  }

  synchronized void requestCancel(String id) {
    update(s -> JobJournal.cancel(s, id));
  }

  synchronized void finish(String id, String result, String error) {
    if (owns(id)) update(s -> JobJournal.finish(s, id, result, error));
  }

  synchronized void updateJob(String id, Editor editor) {
    if (!owns(id) || cancelled(id))
      throw new IllegalStateException("Pekerjaan sudah dibatalkan atau tidak aktif.");
    update(editor);
  }

  synchronized void jobProgress(String id, String phase, double fraction, String note) {
    if (owns(id)) update(s -> JobJournal.progress(s, id, phase, fraction, note));
  }

  synchronized void editInputs(Editor editor) {
    if (busy()) throw new IllegalStateException("Proses masih berjalan.");
    update(
        s -> {
          editor.apply(s);
          s.put("input_revision", s.optLong("input_revision") + 1);
        });
  }

  synchronized void acceptSource(String owner, JSONObject source) {
    updateJob(owner, s -> new ProjectLibrary(context).acceptSource(s, source));
  }

  synchronized void saveDraft(JSONArray draft) throws Exception {
    if (busy()) throw new IllegalStateException("Proses masih berjalan.");
    JSONObject source = state.optJSONObject("source");
    if (source == null) return;
    JSONArray reviewed =
        Planner.review(
            state.getJSONArray("plan"),
            draft,
            state.optString("mode", "clips"),
            source.getDouble("duration_s"));
    if (!reviewed.toString().equals(state.getJSONArray("plan").toString()))
      editInputs(s -> s.put("plan", reviewed));
  }

  synchronized void openProject(String id, JSONArray draft) {
    editInputs(s -> new ProjectLibrary(context).open(s, id, draft));
  }

  synchronized void renameProject(String name) {
    String title = name.trim();
    if (title.isEmpty()
        || title.length() > 80
        || title.codePoints().anyMatch(Character::isISOControl))
      throw new IllegalArgumentException("Nama proyek harus 1–80 karakter tanpa karakter kontrol.");
    if (state.optJSONObject("source") == null)
      throw new IllegalStateException("Pilih video terlebih dahulu.");
    editInputs(s -> s.put("project_name", title));
  }

  File media(String name) {
    if (!name.matches("[A-Za-z0-9._-]{1,100}"))
      throw new IllegalArgumentException("Nama media tidak valid.");
    File root = new File(context.getFilesDir(), "media");
    if (!root.isDirectory() && !root.mkdirs())
      throw new IllegalStateException("Penyimpanan tidak tersedia.");
    return new File(root, name);
  }

  File model() {
    return new File(context.getFilesDir(), "ggml-tiny.bin");
  }
}
