package app.cuplik;

import static org.junit.Assert.*;

import org.json.JSONObject;
import org.junit.Test;

public class AudioLevelsTest {
  @Test
  public void measuresEnergyWithoutCancellingOppositeStereoChannels() throws Exception {
    AudioLevels levels = new AudioLevels();
    // L=0.5, R=-0.5: the channel mean is zero, but both channels are audible.
    for (int i = 0; i < 48000; i++) levels.frame(.25, .5, 48000);
    JSONObject report = levels.report();
    assertEquals(-6.0206, report.getDouble("rms_dbfs"), .001);
    assertEquals(1, report.getDouble("decoded_duration_s"), .0001);
    assertEquals(0, report.getJSONArray("silence_spans").length());
    assertEquals(report.toString(), levels.report().toString());
  }

  @Test
  public void detectsTrailingSilenceAndBoundsReportSize() throws Exception {
    AudioLevels levels = new AudioLevels();
    for (int cycle = 0; cycle < 70; cycle++) {
      for (int i = 0; i < 25; i++) levels.frame(0, 0, 10);
      levels.frame(.1, .5, 10);
    }
    for (int i = 0; i < 31; i++) levels.frame(0, 0, 10);
    JSONObject report = levels.report();
    assertEquals(50, report.getJSONArray("silence_spans").length());
    assertEquals(3.1, report.getDouble("longest_silence_s"), .001);
    assertThrows(IllegalArgumentException.class, () -> levels.frame(0, 0, 10));
  }

  @Test
  public void flagsSilentTrackAndMissingExpectedAudioSeparately() throws Exception {
    AudioLevels levels = new AudioLevels();
    for (int i = 0; i < 300; i++) levels.frame(0, 0, 100);
    JSONObject silent = OutputQc.report(3, 3, true, true, levels.report());
    assertEquals("needs_review", silent.getString("status"));
    assertTrue(silent.getJSONArray("issues").toString().contains("very_quiet_audio"));
    assertTrue(silent.getJSONArray("issues").toString().contains("long_silence"));
    assertTrue(
        OutputQc.report(3, 3, false, true, null)
            .getJSONArray("issues")
            .toString()
            .contains("missing_audio"));
    assertEquals("pass", OutputQc.report(3, 3, false, false, null).getString("status"));
    assertEquals("needs_review", OutputQc.report(3, 3, true, true, null).getString("status"));
  }

  @Test
  public void flagsNearFullScaleAndRejectsInvalidPcm() throws Exception {
    AudioLevels levels = new AudioLevels();
    assertThrows(IllegalArgumentException.class, () -> levels.frame(Double.NaN, 1, 100));
    for (int i = 0; i < 100; i++) levels.frame(1, 1, 100);
    JSONObject report = OutputQc.report(1, 1, true, true, levels.report());
    assertTrue(report.getJSONArray("issues").toString().contains("near_fullscale_audio"));
    assertTrue(
        OutputQc.report(2, 1, false, false, null)
            .getJSONArray("issues")
            .toString()
            .contains("duration_mismatch"));
  }
}
