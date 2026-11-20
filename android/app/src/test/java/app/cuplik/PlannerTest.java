package app.cuplik;

import static org.junit.Assert.*;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;

public class PlannerTest {
  private JSONArray sentences() {
    return new JSONArray()
        .put(Json.obj("id", "s1", "start_s", 0, "end_s", 4, "text", "Siapkan alat."))
        .put(Json.obj("id", "s2", "start_s", 4, "end_s", 8, "text", "Lakukan langkahnya."))
        .put(Json.obj("id", "s3", "start_s", 8, "end_s", 12, "text", "Periksa hasil."));
  }

  private JSONObject response(String start, String end) {
    return Json.obj(
        "segments",
        new JSONArray()
            .put(Json.obj("start_id", start, "end_id", end, "title", "Langkah", "required", true)));
  }

  @Test
  public void rejectsInventedIdsAndIncompleteCoverage() {
    assertThrows(
        Exception.class,
        () -> Planner.validate(response("unknown", "s2"), sentences(), "clips", 12, 60));
    assertThrows(
        Exception.class,
        () -> Planner.validate(response("s2", "s3"), sentences(), "condense", 12, 60));
  }

  @Test
  public void rejectsOverlongClips() {
    assertThrows(
        Exception.class, () -> Planner.validate(response("s1", "s3"), sentences(), "clips", 12, 6));
  }

  @Test
  public void windowedChaptersPreserveGlobalSourceClock() throws Exception {
    JSONArray window =
        new JSONArray().put(Json.obj("id", "s9", "start_s", 60, "end_s", 64, "text", "Lanjutkan."));
    JSONArray result = Planner.validate(response("s9", "s9"), window, "condense", 70, 60, 60);
    assertEquals(60, result.getJSONObject(0).getDouble("start_s"), 0);
    assertEquals(70, result.getJSONObject(0).getDouble("end_s"), 0);
  }

  @Test
  public void requiredContentAndMinimumArePreserved() throws Exception {
    JSONArray plan = Planner.manual(sentences(), "condense", 12);
    assertThrows(Exception.class, () -> Planner.solve(plan, 4));
    JSONArray solved = Planner.solve(plan, 11);
    for (int i = 0; i < solved.length(); i++) {
      assertTrue(solved.getJSONObject(i).getBoolean("keep"));
      assertTrue(solved.getJSONObject(i).getDouble("speed") <= 1.15);
    }
    assertEquals(1, plan.getJSONObject(0).getDouble("speed"), 0);
  }

  @Test
  public void locksAndForgedReviewAreRejected() throws Exception {
    JSONArray plan = Planner.manual(sentences(), "condense", 12);
    JSONArray edit = new JSONArray(plan.toString());
    edit.getJSONObject(0).put("keep", false);
    assertThrows(Exception.class, () -> Planner.review(plan, edit, "condense", 12));
    edit.getJSONObject(0).put("keep", true).put("id", "forged");
    assertThrows(Exception.class, () -> Planner.review(plan, edit, "condense", 12));
  }

  @Test
  public void impossibleManualBoundsDoNotChangeSourcePlan() throws Exception {
    JSONArray plan = Planner.manual(sentences(), "clips", 12);
    JSONArray edit = new JSONArray(plan.toString());
    edit.getJSONObject(0).put("end_s", 1000);
    assertThrows(Exception.class, () -> Planner.review(plan, edit, "clips", 12));
    assertEquals(12, plan.getJSONObject(0).getDouble("end_s"), 0);
  }

  @Test
  public void lockedPlaybackIsNotRespedBySolver() throws Exception {
    JSONArray plan = Planner.manual(sentences(), "condense", 12);
    plan.getJSONObject(0).put("locked", true).put("speed", 1);
    JSONArray solved = Planner.solve(plan, 11);
    assertEquals(1, solved.getJSONObject(0).getDouble("speed"), 0);
  }

  @Test
  public void reviewCannotChangeAStillLockedDecision() throws Exception {
    JSONArray plan = Planner.manual(sentences(), "clips", 12);
    plan.getJSONObject(0).put("locked", true);
    JSONArray edits = new JSONArray(plan.toString());
    edits.getJSONObject(0).put("start_s", 1);
    assertThrows(Exception.class, () -> Planner.review(plan, edits, "clips", 12));
    edits.getJSONObject(0).put("locked", false);
    assertEquals(
        1, Planner.review(plan, edits, "clips", 12).getJSONObject(0).getDouble("start_s"), 0);
  }
}
