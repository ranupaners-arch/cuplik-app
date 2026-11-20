package app.cuplik;

import org.json.JSONArray;
import org.json.JSONObject;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

final class Planner {
    static JSONArray validate(JSONObject response, JSONArray sentences, String mode, double duration, double maximum) throws Exception {
        return validate(response,sentences,mode,duration,maximum,0);
    }
    static JSONArray validate(JSONObject response, JSONArray sentences, String mode, double duration, double maximum, double windowStart) throws Exception {
        Map<String,Integer> positions=new HashMap<>();
        for(int i=0;i<sentences.length();i++) positions.put(sentences.getJSONObject(i).getString("id"),i);
        JSONArray rows=response.getJSONArray("segments"), plan=new JSONArray();
        int last=-1;
        if(rows.length()==0 || rows.length()>20) throw new IllegalArgumentException("Jumlah bagian AI tidak valid.");
        for(int i=0;i<rows.length();i++) {
            JSONObject row=rows.getJSONObject(i);
            Integer a=positions.get(row.getString("start_id")), b=positions.get(row.getString("end_id"));
            if(a==null || b==null || b<a || a<=last || (mode.equals("condense") && a!=last+1)) throw new IllegalArgumentException("AI mengirim ID sumber, urutan atau cakupan yang tidak valid.");
            double start=sentences.getJSONObject(a).getDouble("start_s"), end=sentences.getJSONObject(b).getDouble("end_s");
            if(mode.equals("condense")) { start=a==0?windowStart:sentences.getJSONObject(a).getDouble("start_s"); end=b+1<sentences.length()?sentences.getJSONObject(b+1).getDouble("start_s"):duration; }
            if(!Double.isFinite(start)||!Double.isFinite(end)||start<0||end<=start||end>duration+.05||(!mode.equals("condense")&&end-start>maximum+.01)) throw new IllegalArgumentException("Durasi pilihan AI tidak valid.");
            StringBuilder text=new StringBuilder();
            for(int s=a;s<=b;s++) text.append(sentences.getJSONObject(s).getString("text")).append(' ');
            plan.put(Json.obj("id","p"+(i+1),"start_s",start,"end_s",Math.min(end,duration),"title",row.optString("title","Bagian "+(i+1)).substring(0,Math.min(160,row.optString("title","Bagian "+(i+1)).length())),"required",mode.equals("condense")&&row.optBoolean("required",true),"keep",true,"locked",false,"speed",1,"score",Math.max(0,Math.min(10,row.optDouble("score",5))),"text",text.toString().trim()));
            last=b;
        }
        if(mode.equals("condense")&&last!=sentences.length()-1) throw new IllegalArgumentException("Bab AI belum mencakup seluruh transkrip.");
        return plan;
    }
    static JSONArray manual(JSONArray sentences, String mode, double duration) throws Exception {
        JSONArray rows=new JSONArray();
        if(mode.equals("condense")&&sentences.length()>0) {
            for(int i=0;i<sentences.length();i++) rows.put(Json.obj("start_id",sentences.getJSONObject(i).getString("id"),"end_id",sentences.getJSONObject(i).getString("id"),"title","Langkah "+(i+1),"required",true));
            // Manual plans may have more than the API's chapter limit.
            JSONArray result=new JSONArray();
            for(int i=0;i<sentences.length();i++) {
                JSONObject sentence=sentences.getJSONObject(i);
                result.put(Json.obj("id","p"+(i+1),"start_s",i==0?0:sentence.getDouble("start_s"),"end_s",i+1<sentences.length()?sentences.getJSONObject(i+1).getDouble("start_s"):duration,"title","Langkah "+(i+1),"required",true,"keep",true,"locked",false,"speed",1,"score",5,"text",sentence.getString("text")));
            }
            return result;
        }
        return new JSONArray().put(Json.obj("id","p1","start_s",0,"end_s",Math.min(60,duration),"title","Klip pilihan manual","required",false,"keep",true,"locked",false,"speed",1,"score",0,"text",""));
    }
    static JSONArray review(JSONArray original, JSONArray edits, String mode, double duration) throws Exception {
        if(edits.length()!=original.length()) throw new IllegalArgumentException("Kirim seluruh ID rencana.");
        Set<String> seen=new HashSet<>(); JSONArray result=new JSONArray();
        for(int i=0;i<original.length();i++) {
            JSONObject old=original.getJSONObject(i), edit=edits.getJSONObject(i);
            String id=old.getString("id");
            if(!id.equals(edit.getString("id"))||!seen.add(id)) throw new IllegalArgumentException("ID rencana tidak valid.");
            JSONObject row=new JSONObject(old.toString());
            double a=mode.equals("clips")?edit.optDouble("start_s",old.getDouble("start_s")):old.getDouble("start_s");
            double b=mode.equals("clips")?edit.optDouble("end_s",old.getDouble("end_s")):old.getDouble("end_s");
            double speed=edit.optDouble("speed",1);
            if(!Double.isFinite(a)||!Double.isFinite(b)||a<0||b<=a||b>duration||(!mode.equals("condense")&&b-a>180)||!Double.isFinite(speed)||speed<1||speed>1.25) throw new IllegalArgumentException("Batas atau kecepatan bagian tidak valid.");
            boolean required=mode.equals("condense")&&edit.optBoolean("required",old.optBoolean("required"));
            boolean keep=edit.optBoolean("keep",true);
            if(old.optBoolean("locked")&&edit.optBoolean("locked")&&(keep!=old.optBoolean("keep")||speed!=old.optDouble("speed",1)||a!=old.optDouble("start_s")||b!=old.optDouble("end_s")||required!=old.optBoolean("required")))throw new IllegalArgumentException("Buka kunci sebelum mengubah keputusan.");
            if(required&&!keep) throw new IllegalArgumentException("Bab wajib tidak boleh dibuang.");
            row.put("start_s",a);row.put("end_s",b);row.put("required",required);row.put("keep",keep);row.put("locked",edit.optBoolean("locked"));row.put("speed",speed);
            result.put(row);
        }
        return result;
    }
    static JSONArray solve(JSONArray input, double target) throws Exception {
        if(!Double.isFinite(target)||target<3||target>3600) throw new IllegalArgumentException("Target harus 3–3600 detik.");
        JSONArray result=new JSONArray(input.toString()); List<JSONObject> flexible=new ArrayList<>(), optional=new ArrayList<>(); double fixed=0, required=0;
        for(int i=0;i<result.length();i++) {
            JSONObject row=result.getJSONObject(i); double length=row.getDouble("end_s")-row.getDouble("start_s");
            if(row.optBoolean("locked")) { if(row.optBoolean("keep"))fixed+=length/row.optDouble("speed",1); else if(row.optBoolean("required"))throw new IllegalArgumentException("Bab wajib terkunci sebagai dibuang."); }
            else if(row.optBoolean("required")) { row.put("keep",true);flexible.add(row);required+=length/1.15; }
            else { row.put("keep",false);optional.add(row); }
        }
        if(fixed+required>target+.01) throw new IllegalArgumentException("Target terlalu pendek. Durasi minimum "+Math.ceil(fixed+required)+" detik.");
        optional.sort(Comparator.comparingDouble((JSONObject r)->-r.optDouble("score",5)/(r.optDouble("end_s")-r.optDouble("start_s"))));
        double minimum=fixed+required;
        for(JSONObject row:optional){double cost=(row.getDouble("end_s")-row.getDouble("start_s"))/1.15;if(minimum+cost<=target){row.put("keep",true);flexible.add(row);minimum+=cost;}}
        double natural=0; for(JSONObject row:flexible)natural+=row.getDouble("end_s")-row.getDouble("start_s");
        double speed=Math.max(1,Math.min(1.15,natural/Math.max(.001,target-fixed)));
        for(JSONObject row:flexible)row.put("speed",speed);
        if(fixed+natural==0) throw new IllegalArgumentException("Pilih setidaknya satu bagian.");
        return result;
    }
}
