package app.cuplik;

import android.content.Context;
import android.util.AtomicFile;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.UUID;
import org.json.JSONArray;
import org.json.JSONObject;

/** Archived projects are separate atomic files; the live state remains the source of truth. */
final class ProjectLibrary {
  private static final List<String> FIELDS =
      List.of(
          "source",
          "sentences",
          "plan",
          "outputs",
          "settings",
          "mode",
          "analysis_provider",
          "next_chunk",
          "transcript_language",
          "project_name");
  private final File directory;

  ProjectLibrary(Context context) {
    directory = new File(context.getFilesDir(), "projects");
  }

  static boolean syncIndex(JSONObject state) throws Exception {
    JSONObject source = state.optJSONObject("source");
    if (source == null) return false;
    String id = state.optString("active_project");
    boolean created = id.isEmpty();
    if (created) {
      id = "project-" + UUID.randomUUID();
      state.put("active_project", id);
    }
    JSONArray projects = state.optJSONArray("projects");
    if (projects == null) {
      projects = new JSONArray();
      state.put("projects", projects);
    }
    JSONObject entry = null;
    for (int i = 0; i < projects.length(); i++)
      if (id.equals(projects.getJSONObject(i).optString("id"))) entry = projects.getJSONObject(i);
    if (entry == null) {
      entry = Json.obj("id", id, "created_at", System.currentTimeMillis());
      projects.put(entry);
    }
    entry.put("name", state.optString("project_name", source.optString("name", "Video perangkat")));
    entry.put("source_file", source.optString("file"));
    entry.put("duration_s", source.optDouble("duration_s", 0));
    entry.put("updated_at", System.currentTimeMillis());
    entry.put(
        "output_count",
        state.optJSONArray("outputs") == null ? 0 : state.getJSONArray("outputs").length());
    return created;
  }

  boolean recoverIndex(JSONObject state) throws Exception {
    if (state.optJSONObject("source") != null
        || (state.optJSONArray("projects") != null && state.getJSONArray("projects").length() > 0))
      return false;
    File[] archives =
        directory.listFiles(
            (parent, name) -> name.startsWith("project-") && name.endsWith(".json"));
    if (archives == null) return false;
    JSONArray recovered = new JSONArray();
    for (File archive : archives) {
      try {
        String id = archive.getName().replaceFirst("\\.json$", "");
        JSONObject saved =
            new JSONObject(
                new String(new AtomicFile(file(id)).readFully(), StandardCharsets.UTF_8));
        if (!id.equals(saved.optString("id")) || saved.optJSONObject("source") == null) continue;
        saved.put("active_project", id);
        saved.put("projects", new JSONArray());
        syncIndex(saved);
        JSONObject entry = saved.getJSONArray("projects").getJSONObject(0);
        entry.put("updated_at", archive.lastModified());
        recovered.put(entry);
      } catch (Exception unreadable) {
        /* Preserve unreadable archives and media for manual recovery. */
      }
    }
    if (recovered.length() == 0) return false;
    state.put("projects", recovered);
    state.put("note", "Daftar proyek dipulihkan dari arsip lokal. Pilih proyek untuk membukanya.");
    return true;
  }

  private File file(String id) {
    if (!id.matches("project-[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"))
      throw new IllegalArgumentException("ID proyek tidak valid.");
    if (!directory.isDirectory() && !directory.mkdirs())
      throw new IllegalStateException("Penyimpanan proyek tidak tersedia.");
    return new File(directory, id + ".json");
  }

  private void archive(JSONObject state) throws Exception {
    if (state.optJSONObject("source") == null) return;
    syncIndex(state);
    JSONObject saved = Json.obj("id", state.getString("active_project"));
    for (String key : FIELDS) if (state.has(key)) saved.put(key, state.get(key));
    AtomicFile target = new AtomicFile(file(saved.getString("id")));
    FileOutputStream output = null;
    try {
      output = target.startWrite();
      output.write(saved.toString().getBytes(StandardCharsets.UTF_8));
      target.finishWrite(output);
    } catch (Exception failure) {
      if (output != null) target.failWrite(output);
      throw failure;
    }
  }

  void acceptSource(JSONObject state, JSONObject source) throws Exception {
    archive(state);
    for (String key : FIELDS) state.remove(key);
    state.put("active_project", "project-" + UUID.randomUUID());
    state.put("source", source);
    state.put("sentences", new JSONArray());
    state.put("plan", new JSONArray());
    state.put("outputs", new JSONArray());
    state.put("next_chunk", 0);
    state.put("input_revision", state.optLong("input_revision") + 1);
    state.put("status", "ready");
    state.put("progress", 0);
    state.put("note", "Proyek baru tersimpan lokal. Proyek sebelumnya dapat dibuka dari daftar.");
    state.remove("error");
    syncIndex(state);
  }

  void open(JSONObject state, String id, JSONArray draft) throws Exception {
    JSONObject source = state.optJSONObject("source");
    if (source != null)
      state.put(
          "plan",
          Planner.review(
              state.optJSONArray("plan"),
              draft,
              state.optString("mode", "clips"),
              source.getDouble("duration_s")));
    if (id.equals(state.optString("active_project"))) return;
    boolean known = false;
    JSONArray projects = state.optJSONArray("projects");
    if (projects != null)
      for (int i = 0; i < projects.length(); i++)
        if (id.equals(projects.getJSONObject(i).optString("id"))) known = true;
    if (!known) throw new IllegalArgumentException("Proyek tidak ditemukan.");
    JSONObject target =
        new JSONObject(new String(new AtomicFile(file(id)).readFully(), StandardCharsets.UTF_8));
    if (!id.equals(target.optString("id")) || target.optJSONObject("source") == null)
      throw new IllegalArgumentException(
          "Catatan proyek tidak dapat dibaca. Proyek saat ini tetap tersedia.");
    // Archive first. If the following root write fails, its previous live project is still intact.
    archive(state);
    for (String key : FIELDS) {
      state.remove(key);
      if (target.has(key)) state.put(key, target.get(key));
    }
    state.put("active_project", id);
    state.put("status", state.optJSONArray("plan").length() > 0 ? "awaiting_review" : "ready");
    state.put("progress", 0);
    state.remove("error");
    state.put("note", "Proyek dibuka. Transkrip, keputusan dan hasil tersimpan telah dipulihkan.");
    syncIndex(state);
  }

  void clear() throws Exception {
    File[] files = directory.listFiles();
    if (files != null)
      for (File file : files)
        if (!file.delete()) throw new IllegalStateException("Sebagian proyek belum dapat dihapus.");
  }
}
