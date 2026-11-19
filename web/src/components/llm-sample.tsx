"use client";
import { useState } from "react";
import { post } from "@/lib/api";

export function LLMSample() {
  const [focus, setFocus] = useState("");
  const [result, setResult] = useState<unknown>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return <><p>Mengirim transkrip contoh ke provider pada server dan memvalidasi JSON hasilnya. Mode mock berjalan tanpa API key. Provider nyata memakai konfigurasi .env.</p><form onSubmit={async e => { e.preventDefault(); setBusy(true); setError(""); try { setResult(await post("/llm/sample", { focus })); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }}><label>Fokus contoh<textarea value={focus} maxLength={1000} onChange={e => setFocus(e.target.value)} /></label><button disabled={busy}>{busy ? "Memanggil LLM…" : "Jalankan sample LLM"}</button></form>{error && <p role="alert" className="error">{error}</p>}{result !== null && <pre data-testid="llm-result">{JSON.stringify(result, null, 2)}</pre>}</>;
}
