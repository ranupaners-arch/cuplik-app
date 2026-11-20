package app.cuplik;

import static org.junit.Assert.*;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;

public class JobJournalTest {
  private JSONObject state() {
    return Json.obj(
        "source",
        Json.obj("file", "source-a.mp4"),
        "plan",
        new JSONArray(),
        "sentences",
        new JSONArray());
  }

  @Test
  public void persistsIntentBeforeClaimAndRejectsDuplicateCommands() throws Exception {
    JSONObject state = state(), payload = Json.obj("mode", "clips", "manual", true);
    JSONObject job = JobJournal.enqueue(state, "analyze", payload);
    payload.put("mode", "condense");
    assertTrue(JobJournal.busy(state));
    assertEquals("clips", job.getJSONObject("payload").getString("mode"));
    assertThrows(
        IllegalStateException.class, () -> JobJournal.enqueue(state, "model", new JSONObject()));
    assertTrue(JobJournal.claim(state, job.getString("id")));
    assertFalse(JobJournal.claim(state, job.getString("id")));
  }

  @Test
  public void queuedCancellationCannotStartWork() throws Exception {
    JSONObject state = state(), job = JobJournal.enqueue(state, "model", new JSONObject());
    String id = job.getString("id");
    assertTrue(JobJournal.cancel(state, id));
    assertFalse(JobJournal.claim(state, id));
    assertFalse(JobJournal.busy(state));
    assertEquals("cancelled", job.getString("status"));
    assertTrue(JobJournal.retryable(state));
  }

  @Test
  public void restartRetriesOriginalSourceAndRejectsLateCallbacks() throws Exception {
    JSONObject state = state(),
        old = JobJournal.enqueue(state, "render", Json.obj("plan", new JSONArray()));
    String oldId = old.getString("id");
    JobJournal.claim(state, oldId);
    state.put("next_chunk", 3);
    state = new JSONObject(state.toString());
    assertTrue(JobJournal.recover(state));
    assertEquals(3, state.getInt("next_chunk"));
    JSONObject retry = JobJournal.retry(state);
    assertEquals(2, retry.getInt("attempt"));
    assertEquals(oldId, retry.getString("retry_of"));
    assertEquals(
        old.getJSONObject("payload").toString(), retry.getJSONObject("payload").toString());
    assertFalse(JobJournal.progress(state, oldId, "done", 1, "stale"));
    assertFalse(JobJournal.finish(state, oldId, "done", null));
    assertEquals(retry.getString("id"), state.getJSONObject("active_job").getString("id"));
  }

  @Test
  public void changedSourceOrReviewedInputsInvalidatesRetry() throws Exception {
    JSONObject state = state(),
        job = JobJournal.enqueue(state, "analyze", Json.obj("manual", true));
    JobJournal.finish(state, job.getString("id"), "failed", "fixture");
    state.getJSONObject("source").put("file", "source-b.mp4");
    assertFalse(JobJournal.retryable(state));
    state.getJSONObject("source").put("file", "source-a.mp4");
    assertTrue(JobJournal.retryable(state));
    state.put("input_revision", 1);
    assertFalse(JobJournal.retryable(state));
    assertThrows(IllegalStateException.class, () -> JobJournal.retry(state));
  }

  @Test
  public void cancellationCannotBeOverwrittenBySuccessOrProgress() throws Exception {
    JSONObject state = state(), job = JobJournal.enqueue(state, "model", new JSONObject());
    String id = job.getString("id");
    JobJournal.claim(state, id);
    JobJournal.cancel(state, id);
    JobJournal.progress(state, id, "model", .5, "still running");
    assertEquals("cancelling", state.getString("status"));
    JobJournal.finish(state, id, "done", null);
    assertEquals("cancelled", job.getString("status"));
    assertFalse(JobJournal.progress(state, id, "ready", 1, "late"));
  }
}
