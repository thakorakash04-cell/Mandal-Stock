package com.mandal.stock;

import android.app.Activity;
import android.os.Handler;
import android.os.Looper;
import android.net.Uri;
import android.webkit.*;
import android.view.View;
import org.json.*;
import java.util.*;

/** Reuses the existing hosted Streamlit component protocol as a data transport.
 * No website UI is shown: MainActivity renders native Android views.
 */
final class StreamlitConnection {
    final Activity activity; final WebView view; final Handler ui=new Handler(Looper.getMainLooper());
    final ArrayDeque<Job> queue=new ArrayDeque<>();
    String base="",client=""; boolean ready=false,loading=false,closed=false;
    Job current; JSONObject latest=new JSONObject(); Runnable deadline;
    static class Job {
        String base,path,method,delivery; JSONObject payload,event; MainActivity.Result result;
        Job(String b,String m,String p,JSONObject v,MainActivity.Result r){base=b;method=m;path=p;payload=v;result=r;}
    }
    StreamlitConnection(Activity owner){
        activity=owner;view=new WebView(owner);view.setVisibility(View.INVISIBLE);
        view.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);
        WebSettings settings=view.getSettings();settings.setJavaScriptEnabled(true);settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        CookieManager.getInstance().setAcceptCookie(true);CookieManager.getInstance().setAcceptThirdPartyCookies(view,true);
        view.addJavascriptInterface(new Object(){@JavascriptInterface public void deliver(String raw){
            if(raw==null||raw.length()>6500000)return;
            ui.post(()->receive(raw));
        }},"MandalTransport");
        view.setWebViewClient(new WebViewClient(){
            public boolean shouldOverrideUrlLoading(WebView v,WebResourceRequest r){
                Uri url=r.getUrl();Uri allowed=Uri.parse(base);
                return !("https".equals(url.getScheme())&&url.getHost()!=null&&url.getHost().equalsIgnoreCase(allowed.getHost()));
            }
            public void onReceivedError(WebView v,WebResourceRequest r,WebResourceError e){if(r.isForMainFrame())fail("Cannot reach the existing website. Check internet and try again.");}
            public void onReceivedHttpError(WebView v,WebResourceRequest r,WebResourceResponse e){if(r.isForMainFrame()&&e.getStatusCode()>=400)fail("The existing website could not be opened. Check its address and hosting status.");}
        });
    }
    void request(String host,String method,String path,JSONObject payload,MainActivity.Result result){
        if(closed){result.done(null,"Connection closed.",0);return;}
        if(queue.size()>12){result.done(null,"Please wait for the current update.",0);return;}
        queue.add(new Job(host,method,path,payload,result));kick();
    }
    void kick(){
        if(closed||current!=null||queue.isEmpty())return;
        current=queue.removeFirst();
        if(!current.base.equals(base)||(!ready&&!loading)){
            base=current.base;ready=false;loading=true;client=UUID.randomUUID().toString();
            Uri uri=Uri.parse(base).buildUpon().appendQueryParameter("mandal_native","1").appendQueryParameter("native_client",client).build();
            view.loadUrl(uri.toString());
        }
        arm();if(ready)dispatch();
    }
    void arm(){if(deadline!=null)ui.removeCallbacks(deadline);deadline=()->fail("The website connection timed out. Check that the latest Mandal Stock update is deployed. If Streamlit is asleep, open the website once, then retry.");ui.postDelayed(deadline,60000);}
    void dispatch(){
        if(current==null||!ready)return;
        Job j=current;
        if(j.path.equals("/health")){
            JSONObject health=new JSONObject();put(health,"service","mandal-stock-existing");put(health,"version",3);put(health,"ok",!latest.optBoolean("setupNeeded"));
            if(latest.optBoolean("setupNeeded"))finish(null,"The existing website needs its database configuration checked.",503);else finish(health,null,200);
            return;
        }
        if(j.delivery!=null)return;
        JSONObject e=new JSONObject();
        if(j.path.startsWith("/v1/register")){
            put(e,"action","native_sync");Uri u=Uri.parse(j.path);String page=u.getQueryParameter("page");put(e,"page",page==null?1:Integer.parseInt(page));put(e,"query",u.getQueryParameter("query"));put(e,"kind",u.getQueryParameter("kind"));
        }else if(j.path.equals("/v1/login")){
            put(e,"action","login");put(e,"username",j.payload.optString("username"));put(e,"password",j.payload.optString("password"));
        }else if(j.path.equals("/v1/logout")){put(e,"action","logout");}
        else if(j.path.equals("/v1/actions")||j.path.equals("/v1/photos")){
            try{e=new JSONObject(j.payload.toString());}catch(JSONException ex){finish(null,"Invalid request.",400);return;}
        }else{finish(null,"Unsupported request.",400);return;}
        if(!e.has("id"))put(e,"id",UUID.randomUUID().toString());
        j.event=e;j.delivery=UUID.randomUUID().toString();
        JSONObject message=new JSONObject();put(message,"mandalNativeRequest",true);put(message,"client",client);put(message,"delivery",j.delivery);put(message,"request",e);
        // Credentials go only to the same-origin dedicated data component, never
        // to unrelated Streamlit iframes or external pages.
        String script="(function(){const message="+message.toString()+";let sent=false;for(const frame of document.querySelectorAll('iframe')){try{const u=new URL(frame.src,location.href);if(u.origin===location.origin&&u.pathname.includes('samaan_native_connection')){frame.contentWindow.postMessage(message,location.origin);sent=true;}}catch(e){}}return sent;})()";
        view.evaluateJavascript(script,sent->{if("false".equals(sent))fail("Update the existing Mandal Stock deployment before connecting this APK.");});
        j.payload=null; // Discard password-bearing request objects after dispatch.
    }
    void receive(String raw){
        if(closed)return;
        try{
            JSONObject envelope=new JSONObject(raw);
            if(envelope.optInt("protocol")!=3||!client.equals(envelope.optString("client")))return;
            JSONObject d=envelope.optJSONObject("data");if(d!=null)latest=d;
            boolean first=!ready;ready=true;loading=false;
            if(current==null){kick();return;}
            if(first||current.path.equals("/health")){dispatch();if(current==null)return;}
            JSONObject response=envelope.optJSONObject("response");
            if(response==null||current.delivery==null||!current.delivery.equals(response.optString("delivery")))return;
            if(!response.optBoolean("ok")){
                String error=response.optString("error","Could not save. Refresh and try again.");
                int code=(current.path.equals("/v1/login")||error.toLowerCase(Locale.ROOT).contains("sign in as admin"))?401:400;
                finish(response,error,code);return;
            }
            if(current.path.startsWith("/v1/register")){finish(latest,null,200);return;}
            JSONObject a=new JSONObject();put(a,"ok",true);put(a,"data",latest);put(a,"message",response.optString("message","Saved."));
            if(current.path.equals("/v1/login"))put(a,"token","existing-streamlit-session");
            if(current.path.equals("/v1/photos"))put(a,"images",response.optJSONArray("images"));
            finish(a,null,200);
        }catch(JSONException ex){fail("The website returned an invalid response. Refresh and retry.");}
    }
    void finish(JSONObject value,String error,int code){
        if(deadline!=null)ui.removeCallbacks(deadline);
        Job j=current;current=null;if(j!=null){j.event=null;j.payload=null;j.result.done(value,error,code);}ui.post(this::kick);
    }
    void fail(String message){
        if(closed)return;ready=false;loading=false;client=UUID.randomUUID().toString();
        if(deadline!=null)ui.removeCallbacks(deadline);
        ArrayList<Job> failed=new ArrayList<>();if(current!=null)failed.add(current);current=null;
        while(!queue.isEmpty())failed.add(queue.removeFirst());
        view.stopLoading();
        for(Job j:failed){j.event=null;j.payload=null;j.result.done(null,message,0);}
    }
    void put(JSONObject o,String k,Object v){try{o.put(k,v);}catch(JSONException ignored){}}
    void close(){closed=true;if(deadline!=null)ui.removeCallbacks(deadline);queue.clear();current=null;view.removeJavascriptInterface("MandalTransport");view.destroy();}
}
