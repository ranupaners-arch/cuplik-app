package app.cuplik;

import static org.junit.Assert.*;

import android.content.Context;
import android.content.ContextWrapper;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.UUID;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class ProjectLibraryTest {
  private Context isolated() {
    Context base = InstrumentationRegistry.getInstrumentation().getTargetContext();
    File root = new File(base.getCacheDir(), "projects-test-" + UUID.randomUUID());
    assertTrue(root.mkdirs());
    return new ContextWrapper(base) {
      @Override
      public File getFilesDir() {
        return root;
      }
    };
  }

  private String add(Store store, String name) throws Exception {
    JSONObject job = store.enqueue("import", new JSONObject());
    String owner = job.getString("id");
    assertTrue(store.claim(owner));
    Files.write(store.media(name).toPath(), new byte[] {1});
    store.acceptSource(owner, Json.obj("file", name, "name", name, "duration_s", 10));
    store.finish(owner, "done", null);
    return store.state().getString("active_project");
  }

  @Test
  public void switchingRestoresPerSourceTranscriptPlanAndCompletedExports() throws Exception {
    Context context = isolated();
    Store store = new Store(context);
    String first = add(store, "source-first.mp4");
    JSONArray plan =
        new JSONArray()
            .put(Json.obj("id", "p1", "start_s", 0, "end_s", 5, "speed", 1, "keep", true));
    store.update(
        s -> {
          s.put("sentences", new JSONArray().put(Json.obj("id", "s1", "text", "saved first")));
          s.put("plan", plan);
          s.put("next_chunk", 3);
          s.put("mode", "clips");
          s.put("outputs", new JSONArray().put(Json.obj("file", "export-first.mp4")));
        });
    store.renameProject("Proyek pertama");
    String second = add(store, "source-second.mp4");
    assertEquals(0, store.state().getJSONArray("outputs").length());
    assertEquals(2, store.state().getJSONArray("projects").length());
    store.openProject(first, new JSONArray());
    assertEquals(
        "saved first", store.state().getJSONArray("sentences").getJSONObject(0).getString("text"));
    assertEquals(3, store.state().getInt("next_chunk"));
    assertEquals(
        "export-first.mp4",
        store.state().getJSONArray("outputs").getJSONObject(0).getString("file"));
    assertEquals("Proyek pertama", store.state().getString("project_name"));
    JSONArray draft = new JSONArray(plan.toString());
    draft.getJSONObject(0).put("speed", 1.1);
    store.openProject(second, draft);
    Store restarted = new Store(context);
    restarted.openProject(first, new JSONArray());
    assertEquals(
        1.1, restarted.state().getJSONArray("plan").getJSONObject(0).getDouble("speed"), .001);
    assertTrue(store.media("source-first.mp4").isFile());
    assertTrue(store.media("source-second.mp4").isFile());
  }

  @Test
  public void corruptArchiveAndQueuedJobCannotOverwriteTheLiveProject() throws Exception {
    Context context = isolated();
    Store store = new Store(context);
    String first = add(store, "source-first.mp4"), second = add(store, "source-second.mp4");
    Files.write(
        new File(context.getFilesDir(), "projects/" + first + ".json").toPath(),
        "invalid JSON".getBytes(StandardCharsets.UTF_8));
    assertThrows(IllegalStateException.class, () -> store.openProject(first, new JSONArray()));
    assertEquals(second, store.state().getString("active_project"));
    assertEquals("source-second.mp4", store.state().getJSONObject("source").getString("file"));
    store.enqueue("model", new JSONObject());
    assertThrows(IllegalStateException.class, () -> store.renameProject("while busy"));
    assertThrows(IllegalStateException.class, () -> store.openProject(first, new JSONArray()));
  }

  @Test
  public void migratesLegacySourceWithoutDeletingItsOutputs() throws Exception {
    Context context = isolated();
    Store store = new Store(context);
    store.update(
        s -> {
          s.put("source", Json.obj("file", "legacy.mp4", "duration_s", 10));
          s.put("outputs", new JSONArray().put(Json.obj("file", "export-legacy.mp4")));
        });
    Store restarted = new Store(context);
    assertFalse(restarted.state().getString("active_project").isEmpty());
    assertEquals(1, restarted.state().getJSONArray("projects").length());
    assertEquals(
        "export-legacy.mp4",
        restarted.state().getJSONArray("outputs").getJSONObject(0).getString("file"));
    assertThrows(IllegalArgumentException.class, () -> restarted.renameProject(" "));
    assertThrows(
        IllegalStateException.class, () -> restarted.openProject("../state", new JSONArray()));
  }

  @Test
  public void corruptLiveStateRecoversArchivedProjectsWithoutDiscardingMedia() throws Exception {
    Context context = isolated();
    Store store = new Store(context);
    String first = add(store, "source-first.mp4");
    add(store, "source-second.mp4");
    Files.write(
        new File(context.getFilesDir(), "state.json").toPath(),
        "broken".getBytes(StandardCharsets.UTF_8));
    Store recovered = new Store(context);
    assertEquals(1, recovered.state().getJSONArray("projects").length());
    assertFalse(recovered.state().has("source"));
    recovered.openProject(first, new JSONArray());
    assertEquals("source-first.mp4", recovered.state().getJSONObject("source").getString("file"));
    assertTrue(recovered.media("source-second.mp4").isFile());
  }
}
