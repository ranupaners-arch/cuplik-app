package app.cuplik;

import java.text.BreakIterator;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import org.json.JSONArray;
import org.json.JSONObject;

/** Compact cues with measured glyph widths; timing remains an estimate within ASR segments. */
final class CaptionTimeline {
  interface Measure {
    double width(String text);
  }

  record Cue(double start, double end, String text) {}

  private final List<Cue> cues = new ArrayList<>();

  CaptionTimeline(
      JSONArray sentences,
      double clipStart,
      double clipEnd,
      int words,
      double maxWidth,
      Measure measure) {
    for (int i = 0; i < sentences.length(); i++) {
      JSONObject row = sentences.optJSONObject(i);
      if (row == null) continue;
      double start = row.optDouble("start_s"), end = row.optDouble("end_s");
      if (!Double.isFinite(start)
          || !Double.isFinite(end)
          || end <= start
          || end <= clipStart
          || start >= clipEnd) continue;
      List<String> parts = split(row.optString("text"), words, maxWidth, measure);
      int total = parts.stream().mapToInt(text -> text.codePointCount(0, text.length())).sum();
      int consumed = 0;
      for (String text : parts) {
        double a = start + (end - start) * consumed / Math.max(1, total);
        consumed += text.codePointCount(0, text.length());
        double b = start + (end - start) * consumed / Math.max(1, total);
        a = Math.max(a, clipStart);
        b = Math.min(b, clipEnd);
        if (!cues.isEmpty()) a = Math.max(a, cues.get(cues.size() - 1).end());
        if (b > a) cues.add(new Cue(a, b, text));
      }
    }
  }

  String at(double sourceTime) {
    int low = 0, high = cues.size() - 1;
    while (low <= high) {
      int middle = (low + high) >>> 1;
      Cue cue = cues.get(middle);
      if (sourceTime < cue.start()) high = middle - 1;
      else if (sourceTime >= cue.end()) low = middle + 1;
      else return cue.text();
    }
    return "";
  }

  static List<String> split(String input, int maxWords, double maxWidth, Measure measure) {
    List<String> result = new ArrayList<>();
    String current = "";
    int count = 0;
    for (String word : input.trim().split("\\s+")) {
      if (word.isEmpty()) continue;
      String candidate = current.isEmpty() ? word : current + " " + word;
      if (!current.isEmpty() && (count >= maxWords || measure.width(candidate) > maxWidth)) {
        result.add(current);
        current = "";
        count = 0;
      }
      if (measure.width(word) > maxWidth) {
        BreakIterator graphemes = BreakIterator.getCharacterInstance(Locale.ROOT);
        graphemes.setText(word);
        String fragment = "";
        for (int a = graphemes.first(), b = graphemes.next();
            b != BreakIterator.DONE;
            a = b, b = graphemes.next()) {
          String next = word.substring(a, b);
          if (!fragment.isEmpty() && measure.width(fragment + next) > maxWidth) {
            result.add(fragment);
            fragment = "";
          }
          fragment += next;
        }
        current = fragment;
        count = 1;
      } else {
        current = current.isEmpty() ? word : current + " " + word;
        count++;
      }
    }
    if (!current.isEmpty()) result.add(current);
    return result;
  }
}
