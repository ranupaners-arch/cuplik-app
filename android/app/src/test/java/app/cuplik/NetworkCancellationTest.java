package app.cuplik;

import static org.junit.Assert.*;

import java.net.URL;
import java.security.cert.Certificate;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import javax.net.ssl.HttpsURLConnection;
import org.junit.Test;

public class NetworkCancellationTest {
  private static class Connection extends HttpsURLConnection {
    final CountDownLatch closed = new CountDownLatch(1), release = new CountDownLatch(1);
    final AtomicInteger calls = new AtomicInteger();
    final AtomicReference<Thread> closer = new AtomicReference<>();

    Connection() throws Exception {
      super(new URL("https://example.invalid/"));
    }

    @Override
    public void disconnect() {
      calls.incrementAndGet();
      closer.set(Thread.currentThread());
      closed.countDown();
      try {
        release.await(3, TimeUnit.SECONDS);
      } catch (InterruptedException ignored) {
        Thread.currentThread().interrupt();
      }
    }

    @Override
    public boolean usingProxy() {
      return false;
    }

    @Override
    public void connect() {}

    @Override
    public String getCipherSuite() {
      return "fixture";
    }

    @Override
    public Certificate[] getLocalCertificates() {
      return null;
    }

    @Override
    public Certificate[] getServerCertificates() {
      return null;
    }
  }

  @Test(timeout = 5000)
  public void cancellationReturnsWhileSocketCloseIsBlocked() throws Exception {
    NetworkCancellation cancellation = new NetworkCancellation();
    Connection connection = new Connection();
    var caller = Executors.newSingleThreadExecutor();
    try {
      cancellation.observe(connection);
      caller.submit(cancellation::cancel).get(1, TimeUnit.SECONDS);
      assertTrue(connection.closed.await(1, TimeUnit.SECONDS));
      assertNotEquals(Thread.currentThread(), connection.closer.get());
      cancellation.cancel();
      assertEquals(1, connection.calls.get());
    } finally {
      connection.release.countDown();
      caller.shutdownNow();
    }
  }

  @Test(timeout = 5000)
  public void cancellationIsLatchedBeforeConnectionRegistration() throws Exception {
    NetworkCancellation cancellation = new NetworkCancellation();
    Connection connection = new Connection();
    try {
      cancellation.cancel();
      cancellation.observe(connection);
      assertTrue(connection.closed.await(1, TimeUnit.SECONDS));
      assertEquals(1, connection.calls.get());
    } finally {
      connection.release.countDown();
    }
  }
}
