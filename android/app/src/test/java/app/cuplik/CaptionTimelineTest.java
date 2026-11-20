package app.cuplik;

import static org.junit.Assert.*;

import java.util.List;
import org.json.JSONArray;
import org.junit.Test;

public class CaptionTimelineTest {
  @Test
  public void wrapsLongWordsWithoutDroppingCharacters() {
    String text = "Siapkan pneumonoultramicroscopicsilicovolcanoconiosis lalu periksa hasil.";
    List<String> phrases = CaptionTimeline.split(text, 3, 18, String::length);
    assertEquals(text.replace(" ", ""), String.join("", phrases).replace(" ", ""));
    for (String phrase : phrases) {
      assertTrue(phrase.length() <= 18);
      assertTrue(phrase.split(" ").length <= 3);
    }
  }

  @Test
  public void keepsUnicodeCharactersWhole() {
    List<String> phrases =
        CaptionTimeline.split(
            "Cek 😀😀😀 hasil", 3, 2, text -> text.codePointCount(0, text.length()));
    assertEquals("Cek😀😀😀hasil", String.join("", phrases).replace(" ", ""));
    for (String phrase : phrases) {
      assertFalse(Character.isLowSurrogate(phrase.charAt(0)));
      assertFalse(Character.isHighSurrogate(phrase.charAt(phrase.length() - 1)));
    }
  }

  @Test
  public void distributesCueTimeByTextLengthAndRetainsGaps() {
    JSONArray rows =
        new JSONArray()
            .put(Json.obj("start_s", 2, "end_s", 8, "text", "a bbbb cc"))
            .put(Json.obj("start_s", 10, "end_s", 12, "text", "selesai"));
    CaptionTimeline timeline = new CaptionTimeline(rows, 0, 11, 1, 50, String::length);
    assertEquals("", timeline.at(0));
    assertEquals("a", timeline.at(2));
    assertEquals("bbbb", timeline.at(3));
    assertEquals("cc", timeline.at(7.5));
    assertEquals("", timeline.at(8));
    assertEquals("selesai", timeline.at(10));
    assertEquals("", timeline.at(11));
  }

  @Test
  public void ignoresInvalidSegmentsAndEndsAtClipBoundary() {
    JSONArray rows =
        new JSONArray()
            .put(Json.obj("start_s", 0, "end_s", 0, "text", "invalid"))
            .put(Json.obj("start_s", 0, "end_s", 5, "text", "tes"));
    CaptionTimeline timeline = new CaptionTimeline(rows, 1, 3, 3, 50, String::length);
    assertEquals("", timeline.at(.5));
    assertEquals("tes", timeline.at(1));
    assertEquals("", timeline.at(3));
  }
}
