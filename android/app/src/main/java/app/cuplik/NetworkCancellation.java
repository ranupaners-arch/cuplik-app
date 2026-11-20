package app.cuplik;

import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import javax.net.ssl.HttpsURLConnection;

/** Closing a stalled socket must never block Android's main-thread service callbacks. */
final class NetworkCancellation {
  private final AtomicBoolean cancelled = new AtomicBoolean();
  private final AtomicReference<HttpsURLConnection> active = new AtomicReference<>();

  void observe(HttpsURLConnection connection) {
    active.set(connection);
    if (cancelled.get()) cancel();
  }

  void cancel() {
    cancelled.set(true);
    HttpsURLConnection connection = active.getAndSet(null);
    if (connection == null) return;
    Thread closer =
        new Thread(
            () -> {
              try {
                connection.disconnect();
              } catch (RuntimeException ignored) {
                /* Cancellation still remains latched. */
              }
            },
            "cuplik-network-cancel");
    closer.setDaemon(true);
    closer.start();
  }
}
