package app.cuplik;

import android.view.View;
import android.view.ViewGroup;
import android.webkit.WebView;
import androidx.test.core.app.ActivityScenario;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class AndroidUiTest {
    private WebView find(View view){if(view instanceof WebView)return(WebView)view;if(view instanceof ViewGroup){ViewGroup group=(ViewGroup)view;for(int i=0;i<group.getChildCount();i++){WebView found=find(group.getChildAt(i));if(found!=null)return found;}}return null;}
    @Test public void packagedMantineUiLoadsWithNativeBridge()throws Exception{
        if(android.os.Build.VERSION.SDK_INT>=33)InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand("pm grant app.cuplik android.permission.POST_NOTIFICATIONS").close();
        try(ActivityScenario<MainActivity> activity=ActivityScenario.launch(MainActivity.class)){
            AtomicBoolean loaded=new AtomicBoolean(false);
            for(int i=0;i<30&&!loaded.get();i++){
                CountDownLatch checked=new CountDownLatch(1);
                activity.onActivity(screen->{WebView web=find(screen.findViewById(android.R.id.content));web.evaluateJavascript("Boolean(window.CuplikNative && document.getElementById('root').textContent.includes('Pilih video dari hape'))",value->{loaded.set("true".equals(value));checked.countDown();});});
                assertTrue(checked.await(2,TimeUnit.SECONDS));
                if(!loaded.get())Thread.sleep(300);
            }
            assertTrue("Packaged UI and native bridge must both load",loaded.get());
        }
    }
}
