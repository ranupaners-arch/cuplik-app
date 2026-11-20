package app.cuplik;

import android.content.Context;
import android.util.AtomicFile;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

final class Store {
    interface Editor { void apply(JSONObject state) throws Exception; }
    private static Store instance;
    final Context context;
    private JSONObject state;
    static synchronized Store get(Context context) {
        if (instance == null) instance = new Store(context.getApplicationContext());
        return instance;
    }
    private Store(Context context) {
        this.context = context;
        try { state = new JSONObject(new String(Files.readAllBytes(new File(context.getFilesDir(), "state.json").toPath()), StandardCharsets.UTF_8)); }
        catch (Exception ignored) { state = Json.obj("status", "idle", "note", "Pilih video dari perangkat.", "sentences", new JSONArray(), "plan", new JSONArray(), "outputs", new JSONArray(), "progress", 0); }
    }
    synchronized JSONObject state() {
        try { return new JSONObject(state.toString()); }
        catch (Exception error) { throw new IllegalStateException(error); }
    }
    synchronized void update(Editor editor) {
        JSONObject next = state();
        AtomicFile target = new AtomicFile(new File(context.getFilesDir(), "state.json"));
        FileOutputStream stream = null;
        try {
            editor.apply(next);
            stream = target.startWrite();
            stream.write(next.toString().getBytes(StandardCharsets.UTF_8));
            target.finishWrite(stream);
            state = next;
        } catch (Exception error) { if (stream != null) target.failWrite(stream); throw new IllegalStateException(error); }
    }
    void progress(String status, double progress, String note) {
        update(s -> { s.put("status", status); s.put("progress", progress); s.put("note", note); s.remove("error"); });
    }
    File media(String name) {
        if (!name.matches("[A-Za-z0-9._-]{1,100}")) throw new IllegalArgumentException("Nama media tidak valid.");
        File root = new File(context.getFilesDir(), "media");
        if (!root.isDirectory() && !root.mkdirs()) throw new IllegalStateException("Penyimpanan tidak tersedia.");
        return new File(root, name);
    }
    File model() { return new File(context.getFilesDir(), "ggml-tiny.bin"); }
}
